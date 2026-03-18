"""Task A — Stage 1: RAG-based industry/product extraction.

For each of the 626 cases, retrieves relevant chunks and uses an LLM
to extract product descriptions and any explicit HS codes.

Title parsing extracts a product hint from "{Respondent} — {Product}" format
(available for ~396 of 626 cases). This serves as ground truth for verification.
RAG runs on ALL cases regardless.

Output: Data/Output/industry_extraction.csv
"""

import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from tqdm import tqdm

from rag.config import (
    CASES_CSV_PATH,
    CHECKPOINT_EVERY,
    EXTRACTION_MODEL,
    MAX_WORKERS,
    OUTPUT_DIR,
)
from rag.retrieval import retrieve
from rag.schemas import IndustryExtraction

logger = logging.getLogger(__name__)

# ── Prompt ────────────────────────────────────────────────────

INDUSTRY_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are an expert trade analyst specializing in WTO disputes "
     "and the Harmonized System (HS) classification.\n\n"
     "Your task: Extract the specific traded products that are SUBJECT TO the "
     "disputed measure in this WTO case.\n\n"
     "Rules:\n"
     "1. Identify the specific products that the trade remedy or measure targets. "
     "For example, if a countervailing duty is imposed on 'hot-rolled carbon steel flat products', "
     "the product is 'hot-rolled carbon steel flat products' — NOT upstream inputs like iron ore, "
     "coal, or mining rights, and NOT the legal measure itself.\n"
     "2. Use natural language descriptions (e.g., 'hot-rolled steel products', "
     "'fresh and chilled Atlantic salmon').\n"
     "3. If you find explicit HS codes (e.g., 'HS 7208', 'heading 72.08', "
     "'tariff item 8708.29', 'Chapter 87'), include them in explicit_hs_codes.\n"
     "4. If the dispute challenges a systemic measure (an entire law, customs procedures, "
     "IP regime) rather than targeting specific traded products, set is_systemic=True.\n"
     "5. If the dispute concerns services (GATS) rather than goods, set is_services=True.\n"
     "6. Do NOT invent or guess HS codes. Only include codes explicitly stated in the text.\n"
     "7. Do NOT list upstream inputs, raw materials, or production processes — "
     "only the final products subject to the measure."),
    ("human",
     "Case: DS{case_id}\nTitle: {case_title}\n\n"
     "Retrieved documents:\n{context}\n\n"
     "Extract the specific traded products subject to the disputed measure."),
])


# ── Title parsing ─────────────────────────────────────────────

# Parenthetical at end is usually complainant, e.g. "Carbon Steel (India)"
_PAREN_COMPLAINANT = re.compile(r"\s*\([^)]+\)\s*$")


def _parse_title_product(title: str) -> str:
    """Extract product hint from WTO case title.

    Titles follow '{Respondent} — {Product/Measure}' format.
    Returns the product part with complainant parenthetical stripped,
    or empty string if no title or no dash separator.
    """
    if not title or not isinstance(title, str) or " — " not in title:
        return ""
    parts = title.split(" — ", 1)
    if len(parts) < 2:
        return ""
    product = parts[1].strip()
    # Strip trailing complainant parenthetical: "Carbon Steel (India)" → "Carbon Steel"
    product = _PAREN_COMPLAINANT.sub("", product).strip()
    return product


# ── Helpers ───────────────────────────────────────────────────

def _load_case_metadata() -> pd.DataFrame:
    """Load case metadata from wto_cases.csv."""
    df = pd.read_csv(CASES_CSV_PATH)
    df = df.rename(columns={
        "case": "case_id",
        "Complainant": "complainant",
        "Respondent": "respondent",
        "title": "case_title",
    })
    # Strip "DS" prefix: "DS379" → "379"
    df["case_id"] = df["case_id"].astype(str).str.replace(r"^DS", "", regex=True)
    return df


def _build_query(case_id: str, case_title: str) -> str:
    """Build retrieval query from case ID and title."""
    return (
        f"What specific traded products are subject to the disputed measure "
        f"in WTO dispute DS{case_id}? {case_title}"
    )


# ── Per-case worker ──────────────────────────────────────────

def _process_one_case(case_id: str, case_title: str, structured_llm) -> dict:
    """Process a single case. Thread-safe — called from pool."""
    title_product = _parse_title_product(case_title)
    query = _build_query(case_id, case_title)

    try:
        parent_texts = retrieve(query, case_id, task="industry_extraction")
        context = "\n\n---\n\n".join(parent_texts) if parent_texts else "(No documents retrieved)"

        result = structured_llm.invoke(
            INDUSTRY_PROMPT.format_messages(
                case_id=case_id,
                case_title=case_title if case_title and isinstance(case_title, str) else "(No title)",
                context=context,
            )
        )

        return {
            "case_id": case_id,
            "case_title": case_title,
            "title_product": title_product,
            "product_descriptions": "|".join(result.product_descriptions),
            "explicit_hs_codes": "|".join(result.explicit_hs_codes),
            "is_systemic": result.is_systemic,
            "is_services": result.is_services,
            "confidence": result.confidence,
            "notes": result.notes,
            "n_parents_retrieved": len(parent_texts),
        }

    except Exception as e:
        logger.error("Failed case DS%s: %s", case_id, e)
        return {
            "case_id": case_id,
            "case_title": case_title,
            "title_product": title_product,
            "product_descriptions": "",
            "explicit_hs_codes": "",
            "is_systemic": False,
            "is_services": False,
            "confidence": "low",
            "notes": f"ERROR: {e}",
            "n_parents_retrieved": 0,
        }


# ── Main extraction ───────────────────────────────────────────

def extract_all(
    case_ids: list[str] | None = None,
    resume: bool = True,
    max_workers: int = MAX_WORKERS,
) -> pd.DataFrame:
    """Run industry extraction for all (or specified) cases.

    Args:
        case_ids: List of case IDs to process. None = all 626.
        resume: If True, skip cases already in the output CSV.
        max_workers: Number of parallel threads.

    Returns:
        DataFrame with extraction results.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, "industry_extraction.csv")

    cases_df = _load_case_metadata()
    if case_ids:
        cases_df = cases_df[cases_df["case_id"].isin(case_ids)]

    # Resume support
    completed = set()
    results = []
    if resume and os.path.exists(output_path):
        try:
            existing = pd.read_csv(output_path, dtype={"case_id": str})
            completed = set(existing["case_id"].tolist())
            results = existing.to_dict("records")
            logger.info("Resuming: %d cases already completed", len(completed))
        except pd.errors.EmptyDataError:
            pass

    # LLM setup
    llm = ChatOpenAI(model=EXTRACTION_MODEL, temperature=0)
    structured_llm = llm.with_structured_output(IndustryExtraction)

    pending = cases_df[~cases_df["case_id"].isin(completed)]
    logger.info("Processing %d cases (%d already done, %d workers)", len(pending), len(completed), max_workers)

    if pending.empty:
        logger.info("Nothing to process")
        return pd.DataFrame(results)

    # Prepare work items
    work_items = [
        (str(row["case_id"]), str(row.get("case_title", "")))
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
                pd.DataFrame(results).to_csv(output_path, index=False)
                logger.info("Checkpoint: saved %d results", len(results))

    if max_workers <= 1:
        for case_id, case_title in tqdm(work_items, desc="Industry extraction"):
            result = _process_one_case(case_id, case_title, structured_llm)
            _on_complete(result)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_process_one_case, cid, ctitle, structured_llm): cid
                for cid, ctitle in work_items
            }
            with tqdm(total=len(futures), desc="Industry extraction") as pbar:
                for future in as_completed(futures):
                    result = future.result()
                    _on_complete(result)
                    pbar.update(1)

    # Final save
    df = pd.DataFrame(results)
    df.to_csv(output_path, index=False)
    logger.info("Saved %d results to %s", len(df), output_path)

    # Print title coverage stats
    has_title = df["title_product"].notna() & (df["title_product"] != "")
    logger.info("Title product coverage: %d/%d (%.0f%%)", has_title.sum(), len(df), has_title.mean() * 100)

    return df


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Task A Stage 1: Industry extraction")
    parser.add_argument("--cases", nargs="*", help="Specific case IDs to process")
    parser.add_argument("--no-resume", action="store_true", help="Start fresh, ignore existing output")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help="Parallel threads")
    args = parser.parse_args()

    extract_all(case_ids=args.cases, resume=not args.no_resume, max_workers=args.workers)
