"""Task B: Dispute severity scoring.

Scores each case on 4 dimensions (1-5 each) of political framing intensity
using only the complainant's own documents (filtered at retrieval).

Dimensions: rhetorical_aggressiveness, systemic_reach, escalation_ultimatum, domestic_victimhood
Composite: mean of the 4 dimension scores

Output: Data/Output/severity_scores_raw.csv
"""

import ast
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from tqdm import tqdm

from rag.config import (
    CASES_CSV_PATH,
    CHECKPOINT_EVERY,
    MAX_CASE_NUM,
    MAX_WORKERS,
    OUTPUT_DIR,
    SEVERITY_MODEL,
)
from rag.retrieval import retrieve
from rag.schemas import SeverityScore

logger = logging.getLogger(__name__)

# ── Prompt ────────────────────────────────────────────────────

SEVERITY_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are an expert in WTO dispute settlement and International Political Economy. "
     "Analyze the political framing intensity of the following 'Request for Consultations' (RfC).\n\n"
     
     "### SCORING RUBRIC (1-5 Scale) ###\n"
     "DIMENSION 1: Rhetorical Aggressiveness\n"
     "- 1 (Purely Procedural): Uses hedged, boilerplate language ('appears to be inconsistent').\n"
     "- 2 (Formal): Standard legal assertions without added emphasis.\n"
     "- 3 (Assertive): Uses active verbs like 'fails to conform' or 'violates'.\n"
     "- 4 (Strong): Employs emphatic language like 'serious nullification' or 'severely undermines'.\n"
     "- 5 (Hostile/Geopolitical): Uses inflammatory terms like 'coercive', 'blatant', or 'economic isolation'.\n\n"
     
     "DIMENSION 2: Systemic Reach (Scope of Target)\n"
     "- 1 (Product-specific): Targets a single HS code or a specific import shipment.\n"
     "- 2 (Multi-product): Targets a group of related goods.\n"
     "- 3 (Sector-wide): Targets an entire industry (e.g., all agricultural subsidies).\n"
     "- 4 (Policy/Methodology): Challenges an administrative method or specific regulation (As-applied).\n"
     "- 5 (Regime-challenging): Challenges a national law, constitutionality, or horizontal system (As-such).\n\n"
     
     "DIMENSION 3: Escalation & Ultimatum\n"
     "- 1 (Routine): Purely procedural request to initiate the 60-day window.\n"
     "- 2 (Frictional): Briefly mentions previous bilateral attempts to resolve the issue.\n"
     "- 3 (Breakdown): Explicitly states that prior consultations or negotiations have failed.\n"
     "- 4 (Pattern-based): Cites a systemic, long-term pattern of non-compliance by the respondent.\n"
     "- 5 (Retaliatory): Implies the need for rebalancing, retaliation, or 'all available remedies'.\n\n"

     "DIMENSION 4: Domestic Victimhood Framing\n"
     "- 1 (None): Purely technical legal claims; no mention of domestic economic pain.\n"
     "- 2 (Market Access): Mentions barriers to exporters without describing specific damage.\n"
     "- 3 (Economic Loss): Cites specific data on production loss, unemployment, or trade volume drop.\n"
     "- 4 (National Interest): Frames the measure as a threat to national economic strategy or core sectors.\n"
     "- 5 (Existential): Describes the measure as a threat to national livelihoods or survival.\n\n"

     "### ANCHOR CASES ###\n"
     "- L1: DS3 (US v S. Korea) - Purely hedged boilerplate.\n"
     "- L3: DS267 (Brazil v US) - Cites $600M+ losses and 'serious prejudice'.\n"
     "- L5: DS574 (Venezuela v US) - Uses 'coercive' and 'geopolitical' framing.\n\n"
     
     "### OUTPUT REQUIREMENTS ###\n"
     "Return a JSON object with 'scores' (dict), 'reasoning' (max 2 sentences per dimension), and 'evidence' (exact quotes)."),
    ("human", "Case: DS{case_id}\nComplainant: {complainant}\n\nText:\n{context}")
])


# ── Helpers ───────────────────────────────────────────────────

def _parse_complainant(val) -> str:
    """Extract complainant name from stringified list."""
    if not val or val == "[]":
        return "Unknown"
    try:
        items = ast.literal_eval(val) if isinstance(val, str) else val
        if isinstance(items, list):
            return ", ".join(str(x) for x in items)
    except Exception:
        pass
    return str(val)


def _build_query(case_id: str, case_title: str, complainant: str) -> str:
    """Build retrieval query for severity scoring."""
    return (
        f"Political framing and language intensity in the consultation request "
        f"for WTO dispute DS{case_id}. Complainant {complainant}: {case_title}"
    )



# ── Per-case worker ──────────────────────────────────────────

def _score_one_case(case_id: str, case_title: str, complainant: str, structured_llm) -> dict:
    """Score a single case. Thread-safe — called from pool."""
    query = _build_query(case_id, case_title, complainant)

    try:
        parent_texts = retrieve(query, case_id, task="severity_scoring")
        context = "\n\n---\n\n".join(parent_texts) if parent_texts else "(No documents retrieved)"

        result = structured_llm.invoke(
            SEVERITY_PROMPT.format_messages(
                case_id=case_id,
                complainant=complainant,
                context=context,
            )
        )

        severity_score = (
            result.rhetorical_aggressiveness
            + result.systemic_reach
            + result.escalation_ultimatum
            + result.domestic_victimhood
        ) / 4.0

        return {
            "case_id": case_id,
            "complainant": complainant,
            "rhetorical_aggressiveness": result.rhetorical_aggressiveness,
            "systemic_reach": result.systemic_reach,
            "escalation_ultimatum": result.escalation_ultimatum,
            "domestic_victimhood": result.domestic_victimhood,
            "severity_score": round(severity_score, 2),
            "reasoning": result.reasoning,
            "evidence": result.evidence,
            "n_parents_retrieved": len(parent_texts),
        }

    except Exception as e:
        logger.error("Failed case DS%s: %s", case_id, e)
        return {
            "case_id": case_id,
            "complainant": complainant,
            "rhetorical_aggressiveness": None,
            "systemic_reach": None,
            "escalation_ultimatum": None,
            "domestic_victimhood": None,
            "severity_score": None,
            "reasoning": f"ERROR: {e}",
            "evidence": "",
            "n_parents_retrieved": 0,
        }


# ── Main scoring ──────────────────────────────────────────────

def score_all(
    case_ids: list[str] | None = None,
    resume: bool = True,
    max_workers: int = MAX_WORKERS,
) -> pd.DataFrame:
    """Run severity scoring for all (or specified) cases.

    Args:
        case_ids: List of case IDs to process. None = all 626.
        resume: If True, skip cases already in the output CSV.
        max_workers: Number of parallel threads.

    Returns:
        DataFrame with severity scores.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    raw_path = os.path.join(OUTPUT_DIR, "severity_scores_raw.csv")

    cases_df = pd.read_csv(CASES_CSV_PATH, encoding="utf-8")
    cases_df = cases_df.rename(columns={
        "case": "case_id",
        "title": "case_title",
    })
    # Strip "DS" prefix: "DS379" → "379"
    cases_df["case_id"] = cases_df["case_id"].astype(str).str.replace(r"^DS", "", regex=True)
    # Only include cases with collected documents (DS1–DS626)
    cases_df = cases_df[cases_df["case_id"].astype(int) <= MAX_CASE_NUM]
    if case_ids:
        cases_df = cases_df[cases_df["case_id"].isin(case_ids)]

    # Resume support
    completed = set()
    results = []
    if resume and os.path.exists(raw_path):
        try:
            existing = pd.read_csv(raw_path, dtype={"case_id": str})
            completed = set(existing["case_id"].tolist())
            results = existing.to_dict("records")
            logger.info("Resuming: %d cases already scored", len(completed))
        except pd.errors.EmptyDataError:
            pass

    # LLM setup
    llm = ChatOpenAI(model=SEVERITY_MODEL, temperature=0)
    structured_llm = llm.with_structured_output(SeverityScore)

    pending = cases_df[~cases_df["case_id"].isin(completed)]
    logger.info("Scoring %d cases (%d already done, %d workers)", len(pending), len(completed), max_workers)

    if pending.empty:
        logger.info("Nothing to process")
        return pd.DataFrame(results)

    # Prepare work items
    work_items = [
        (str(row["case_id"]), str(row.get("case_title", "")), _parse_complainant(row.get("complainant", "")))
        for _, row in pending.iterrows()
    ]

    # Thread-safe result collection + checkpointing
    lock = threading.Lock()
    done_count = 0

    def _on_complete(result: dict):
        nonlocal done_count
        with lock:
            results.append(result)
            done_count += 1
            if done_count % CHECKPOINT_EVERY == 0:
                pd.DataFrame(results).to_csv(raw_path, index=False)
                logger.info("Checkpoint: saved %d results", len(results))

    if max_workers <= 1:
        for case_id, case_title, complainant in tqdm(work_items, desc="Severity scoring"):
            result = _score_one_case(case_id, case_title, complainant, structured_llm)
            _on_complete(result)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_score_one_case, cid, ctitle, comp, structured_llm): cid
                for cid, ctitle, comp in work_items
            }
            with tqdm(total=len(futures), desc="Severity scoring") as pbar:
                for future in as_completed(futures):
                    result = future.result()
                    _on_complete(result)
                    pbar.update(1)

    # Save raw scores
    raw_df = pd.DataFrame(results)
    raw_df.to_csv(raw_path, index=False)
    logger.info("Saved %d raw scores to %s", len(raw_df), raw_path)

    return raw_df


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Task B: Severity scoring")
    parser.add_argument("--cases", nargs="*", help="Specific case IDs to process")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help="Parallel threads")
    args = parser.parse_args()

    score_all(case_ids=args.cases, resume=not args.no_resume, max_workers=args.workers)
