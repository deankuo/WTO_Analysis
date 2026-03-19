"""Task B: Third party engagement scoring.

Scores each third party's engagement intensity using their
Request_To_Join_Consultations documents.

Cases where a third party has no joining request document are marked
as "no_document" — these are countries that joined later (post-consultation),
indicating lower political engagement.

Output: Data/Output/third_party_scores_raw.csv
"""

import ast
import logging
import os
import threading
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
from rag.schemas import ThirdPartyScore

logger = logging.getLogger(__name__)

# ── Prompt ────────────────────────────────────────────────────

THIRD_PARTY_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are an expert in WTO dispute settlement analyzing the political "
     "engagement intensity of third party interventions.\n\n"
     "A third party has requested to join consultations in a WTO dispute. "
     "Score their intervention on three dimensions using a 1-3 scale. "
     "Base your scores ONLY on the text provided.\n\n"
     "DIMENSION 1 — Engagement Intensity:\n"
     "1 = Formulaic: standard 'substantial trade interest' language only\n"
     "2 = Moderate: specific reasons for interest, economic rationale stated\n"
     "3 = Strong: emphatic language, urgency, direct trade impact emphasized\n\n"
     "DIMENSION 2 — Stake Specificity:\n"
     "1 = Generic: 'trade interest' with no specifics\n"
     "2 = Moderate: mentions specific products, sectors, or trade relationships\n"
     "3 = Detailed: quantified trade impact, specific tariff lines, market share data\n\n"
     "DIMENSION 3 — Systemic Framing:\n"
     "1 = Bilateral focus: only concerned with own trade interest\n"
     "2 = Broader: references WTO obligations, precedent, or rule-making implications\n"
     "3 = Systemic: frames as threat to multilateral trading system or fundamental principles\n\n"
     "For each dimension, provide a brief evidence excerpt from the text."),
    ("human",
     "Case: DS{case_id}\nThird party: {third_party}\n\n"
     "Request to join consultations text:\n{context}\n\n"
     "Score this third party's engagement."),
])


# ── Helpers ───────────────────────────────────────────────────

def _parse_list_field(val) -> list[str]:
    """Parse stringified list from CSV."""
    if not val or val == "[]" or (isinstance(val, float) and pd.isna(val)):
        return []
    try:
        items = ast.literal_eval(val) if isinstance(val, str) else val
        if isinstance(items, list):
            return [str(x).strip() for x in items if str(x).strip()]
    except Exception:
        pass
    return [str(val).strip()] if str(val).strip() else []


# ── Per-case worker ──────────────────────────────────────────

def _score_one_third_party(
    case_id: str,
    third_party: str,
    structured_llm,
) -> dict:
    """Score a single third party's engagement. Thread-safe."""
    query = (
        f"Third party interest and engagement in WTO dispute DS{case_id}. "
        f"Request to join consultations by {third_party}"
    )

    try:
        parent_texts = retrieve(query, case_id, task="third_party_scoring")

        # Filter to docs mentioning this specific third party
        relevant = [t for t in parent_texts if third_party.lower() in t.lower()]
        if not relevant:
            relevant = parent_texts  # Fallback to all retrieved docs

        context = "\n\n---\n\n".join(relevant) if relevant else ""

        if not context:
            # No documents found — third party likely joined post-consultation
            return {
                "case_id": case_id,
                "third_party": third_party,
                "engagement_intensity": None,
                "engagement_evidence": "no_document",
                "stake_specificity": None,
                "stake_evidence": "",
                "systemic_framing": None,
                "systemic_evidence": "",
                "has_joining_request": False,
                "n_parents_retrieved": 0,
            }

        result = structured_llm.invoke(
            THIRD_PARTY_PROMPT.format_messages(
                case_id=case_id,
                third_party=third_party,
                context=context,
            )
        )

        return {
            "case_id": case_id,
            "third_party": third_party,
            "engagement_intensity": result.engagement_intensity,
            "engagement_evidence": result.engagement_evidence,
            "stake_specificity": result.stake_specificity,
            "stake_evidence": result.stake_evidence,
            "systemic_framing": result.systemic_framing,
            "systemic_evidence": result.systemic_evidence,
            "has_joining_request": True,
            "n_parents_retrieved": len(relevant),
        }

    except Exception as e:
        logger.error("Failed DS%s third party %s: %s", case_id, third_party, e)
        return {
            "case_id": case_id,
            "third_party": third_party,
            "engagement_intensity": None,
            "engagement_evidence": f"ERROR: {e}",
            "stake_specificity": None,
            "stake_evidence": "",
            "systemic_framing": None,
            "systemic_evidence": "",
            "has_joining_request": False,
            "n_parents_retrieved": 0,
        }


# ── Main scoring ──────────────────────────────────────────────

def score_third_parties(
    case_ids: list[str] | None = None,
    resume: bool = True,
    max_workers: int = MAX_WORKERS,
) -> pd.DataFrame:
    """Score third party engagement for all cases with third parties.

    Returns DataFrame with one row per case-third_party pair.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    raw_path = os.path.join(OUTPUT_DIR, "third_party_scores_raw.csv")

    # Load case metadata
    cases_df = pd.read_csv(CASES_CSV_PATH, encoding="utf-8")
    cases_df = cases_df.rename(columns={"case": "case_id"})
    cases_df["case_id"] = cases_df["case_id"].astype(str).str.replace(r"^DS", "", regex=True)
    cases_df = cases_df[cases_df["case_id"].astype(int) <= MAX_CASE_NUM]
    if case_ids:
        cases_df = cases_df[cases_df["case_id"].isin(case_ids)]

    # Build work items: (case_id, third_party_name) pairs
    work_items = []
    for _, row in cases_df.iterrows():
        cid = str(row["case_id"])
        third_parties = _parse_list_field(row.get("third_parties", "[]"))
        for tp in third_parties:
            work_items.append((cid, tp))

    logger.info("Found %d case-third_party pairs across %d cases", len(work_items), len(cases_df))

    # Resume support
    completed = set()
    results = []
    if resume and os.path.exists(raw_path):
        try:
            existing = pd.read_csv(raw_path, dtype={"case_id": str})
            completed = set(zip(existing["case_id"], existing["third_party"]))
            results = existing.to_dict("records")
            logger.info("Resuming: %d pairs already scored", len(completed))
        except pd.errors.EmptyDataError:
            pass

    # LLM setup
    llm = ChatOpenAI(model=SEVERITY_MODEL, temperature=0)
    structured_llm = llm.with_structured_output(ThirdPartyScore)

    pending = [(cid, tp) for cid, tp in work_items if (cid, tp) not in completed]
    logger.info("Scoring %d pairs (%d already done, %d workers)", len(pending), len(completed), max_workers)

    if not pending:
        logger.info("Nothing to process")
        return pd.DataFrame(results)

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
        for cid, tp in tqdm(pending, desc="Third party scoring"):
            result = _score_one_third_party(cid, tp, structured_llm)
            _on_complete(result)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_score_one_third_party, cid, tp, structured_llm): (cid, tp)
                for cid, tp in pending
            }
            with tqdm(total=len(futures), desc="Third party scoring") as pbar:
                for future in as_completed(futures):
                    result = future.result()
                    _on_complete(result)
                    pbar.update(1)

    # Save raw scores
    raw_df = pd.DataFrame(results)
    raw_df.to_csv(raw_path, index=False)
    logger.info("Saved %d raw third party scores to %s", len(raw_df), raw_path)

    # Stats
    has_doc = raw_df["has_joining_request"].sum() if "has_joining_request" in raw_df.columns else 0
    logger.info("Third parties with joining request: %d/%d (%.0f%%)",
                has_doc, len(raw_df), has_doc / len(raw_df) * 100 if len(raw_df) > 0 else 0)

    return raw_df


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Task B: Third party engagement scoring")
    parser.add_argument("--cases", nargs="*", help="Specific case IDs to process")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help="Parallel threads")
    args = parser.parse_args()

    score_third_parties(case_ids=args.cases, resume=not args.no_resume, max_workers=args.workers)
