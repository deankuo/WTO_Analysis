"""Task A — Stage 2: HS section classification (NO RAG).

Reads industry_extraction.csv and classifies each case into HS sections (1-21).
Two paths:
  A) Explicit HS codes → deterministic lookup
  B) Product descriptions only → LLM classification

Outputs:
  - Data/Output/case_hs_sections.csv       (one row per case)
  - Data/Output/case_section_expanded.csv   (one row per case-section pair)
"""

import json
import logging
import os
import time

import pandas as pd
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from tqdm import tqdm

from rag.config import (
    CLASSIFICATION_MODEL,
    CHECKPOINT_EVERY,
    HS_MAPPING_PATH,
    LLM_BATCH_PAUSE,
    OUTPUT_DIR,
)
from rag.schemas import HSClassification

logger = logging.getLogger(__name__)

# ── HS Section reference (21 sections) ────────────────────────

HS_SECTIONS = {
    1: "Live animals; animal products",
    2: "Vegetable products",
    3: "Animal or vegetable fats and oils",
    4: "Prepared foodstuffs; beverages; tobacco",
    5: "Mineral products",
    6: "Products of the chemical or allied industries",
    7: "Plastics and rubber",
    8: "Raw hides, skins, leather, furs",
    9: "Wood and articles of wood; cork",
    10: "Pulp of wood; paper and paperboard",
    11: "Textiles and textile articles",
    12: "Footwear, headgear, umbrellas",
    13: "Articles of stone, plaster, cement, ceramic, glass",
    14: "Natural or cultured pearls, precious stones, metals",
    15: "Base metals and articles of base metal",
    16: "Machinery and mechanical/electrical equipment",
    17: "Vehicles, aircraft, vessels, transport equipment",
    18: "Optical, photographic, medical, musical instruments",
    19: "Arms and ammunition",
    20: "Miscellaneous manufactured articles",
    21: "Works of art, collectors' pieces, antiques",
}

# HS chapter → section mapping (chapters 1-97)
_CHAPTER_TO_SECTION = {}


def _load_chapter_mapping():
    """Load or build the HS chapter-to-section mapping."""
    global _CHAPTER_TO_SECTION

    if os.path.exists(HS_MAPPING_PATH):
        with open(HS_MAPPING_PATH) as f:
            raw = json.load(f)
            _CHAPTER_TO_SECTION = {int(k): v for k, v in raw.items()}
        return

    # Build from standard HS structure
    section_ranges = [
        (1, 1, 5),    (2, 6, 14),   (3, 15, 15),  (4, 16, 24),
        (5, 25, 27),  (6, 28, 38),  (7, 39, 40),  (8, 41, 43),
        (9, 44, 46),  (10, 47, 49), (11, 50, 63), (12, 64, 67),
        (13, 68, 70), (14, 71, 71), (15, 72, 83), (16, 84, 85),
        (17, 86, 89), (18, 90, 92), (19, 93, 93), (20, 94, 96),
        (21, 97, 97),
    ]
    for section, ch_start, ch_end in section_ranges:
        for ch in range(ch_start, ch_end + 1):
            _CHAPTER_TO_SECTION[ch] = section

    # Persist for future use
    os.makedirs(os.path.dirname(HS_MAPPING_PATH), exist_ok=True)
    with open(HS_MAPPING_PATH, "w") as f:
        json.dump(_CHAPTER_TO_SECTION, f, indent=2)
    logger.info("Created HS mapping at %s", HS_MAPPING_PATH)


def _hs_code_to_sections(codes: list[str]) -> list[int]:
    """Map explicit HS codes to section numbers via chapter lookup."""
    if not _CHAPTER_TO_SECTION:
        _load_chapter_mapping()

    sections = set()
    for code in codes:
        # Extract first 2 digits (chapter) from codes like "7208", "72.08", "8708.29"
        cleaned = code.strip().replace(".", "").replace(" ", "")
        # Remove "HS" prefix if present
        cleaned = cleaned.upper().replace("HS", "").strip()
        if len(cleaned) >= 2:
            try:
                chapter = int(cleaned[:2])
                if chapter in _CHAPTER_TO_SECTION:
                    sections.add(_CHAPTER_TO_SECTION[chapter])
            except ValueError:
                logger.warning("Could not parse HS code: %s", code)
    return sorted(sections)


# ── Keyword fallback ──────────────────────────────────────────

KEYWORD_TO_SECTIONS = {
    "salmon": [1], "shrimp": [1], "beef": [1], "poultry": [1],
    "chicken": [1], "pork": [1], "meat": [1], "fish": [1],
    "dairy": [1, 4], "milk": [4],
    "cotton": [2, 11], "rice": [2], "sugar": [4], "banana": [2],
    "corn": [2], "maize": [2], "wheat": [2], "soybean": [2],
    "olive": [2, 3], "wine": [4], "spirit": [4], "tobacco": [4],
    "petroleum": [5], "oil": [5], "mineral": [5], "coal": [5],
    "pharmaceutical": [6], "chemical": [6], "fertilizer": [6],
    "plastic": [7], "rubber": [7], "tyre": [7], "tire": [7],
    "leather": [8], "hide": [8],
    "lumber": [9], "softwood": [9], "timber": [9], "wood": [9],
    "paper": [10], "pulp": [10],
    "textile": [11], "garment": [11], "apparel": [11], "fabric": [11],
    "footwear": [12], "shoe": [12],
    "cement": [13], "glass": [13], "ceramic": [13],
    "steel": [15], "iron": [15], "aluminium": [15], "aluminum": [15],
    "copper": [15], "zinc": [15], "metal": [15],
    "semiconductor": [16], "machinery": [16], "electronic": [16],
    "computer": [16], "turbine": [16],
    "automobile": [17], "auto part": [17], "vehicle": [17],
    "aircraft": [17], "ship": [17], "railway": [17],
    "solar panel": [16], "photovoltaic": [16], "wind turbine": [16],
}


def _keyword_sections(product_descriptions: str) -> list[int]:
    """Fallback: match product descriptions against keyword map."""
    lower = product_descriptions.lower()
    sections = set()
    for keyword, secs in KEYWORD_TO_SECTIONS.items():
        if keyword in lower:
            sections.update(secs)
    return sorted(sections)


# ── LLM classification prompt ─────────────────────────────────

HS_CLASSIFICATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are an expert in the Harmonized System (HS) trade classification.\n\n"
     "Given product descriptions from a WTO dispute, classify them into the appropriate "
     "HS Sections (1-21). Here are the 21 sections:\n\n"
     + "\n".join(f"Section {num}: {desc}" for num, desc in HS_SECTIONS.items()) +
     "\n\nA dispute may involve multiple sections. Return all applicable sections. "
     "If the products are too vague to classify, return the most likely section(s)."),
    ("human",
     "Product descriptions: {product_descriptions}\nCase title: {case_title}\n\n"
     "Classify into HS sections."),
])


# ── Main classification ──────────────────────────────────────

def classify_all(resume: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read industry_extraction.csv and classify into HS sections.

    Returns:
        (case_hs_sections_df, case_section_expanded_df)
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    input_path = os.path.join(OUTPUT_DIR, "industry_extraction.csv")
    output_path = os.path.join(OUTPUT_DIR, "case_hs_sections.csv")
    expanded_path = os.path.join(OUTPUT_DIR, "case_section_expanded.csv")

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Run task_a_industry.py first: {input_path}")

    _load_chapter_mapping()

    try:
        df = pd.read_csv(input_path, dtype={"case_id": str})
    except pd.errors.EmptyDataError:
        logger.error("industry_extraction.csv is empty — run industry extraction first")
        return pd.DataFrame(), pd.DataFrame()

    if df.empty:
        logger.warning("No cases in industry_extraction.csv — nothing to classify")
        return pd.DataFrame(), pd.DataFrame()

    logger.info("Loaded %d cases from %s", len(df), input_path)

    # Resume support
    completed = set()
    results = []
    if resume and os.path.exists(output_path):
        existing = pd.read_csv(output_path, dtype={"case_id": str})
        completed = set(existing["case_id"].tolist())
        results = existing.to_dict("records")
        logger.info("Resuming: %d cases already classified", len(completed))

    # LLM for path B
    llm = ChatOpenAI(model=CLASSIFICATION_MODEL, temperature=0)
    structured_llm = llm.with_structured_output(HSClassification)

    pending = df[~df["case_id"].isin(completed)]

    for idx, (_, row) in enumerate(tqdm(pending.iterrows(), total=len(pending), desc="HS classification")):
        case_id = str(row["case_id"])
        product_descriptions = str(row.get("product_descriptions", ""))
        explicit_codes_str = str(row.get("explicit_hs_codes", ""))
        is_systemic = row.get("is_systemic", False)
        is_services = row.get("is_services", False)
        case_title = str(row.get("case_title", ""))

        explicit_codes = [c.strip() for c in explicit_codes_str.split("|") if c.strip()]

        # Systemic / services cases: no classification
        if is_systemic or is_services:
            results.append({
                "case_id": case_id,
                "hs_sections": "",
                "product_descriptions": product_descriptions,
                "extraction_method": "not_applicable",
                "confidence": "not_applicable",
                "reasoning": "Systemic measure" if is_systemic else "Services dispute",
            })
            continue

        # Path A: explicit HS codes → deterministic lookup
        if explicit_codes:
            sections = _hs_code_to_sections(explicit_codes)
            if sections:
                results.append({
                    "case_id": case_id,
                    "hs_sections": "|".join(str(s) for s in sections),
                    "product_descriptions": product_descriptions,
                    "extraction_method": "explicit_hs",
                    "confidence": "high",
                    "reasoning": f"Mapped from explicit codes: {', '.join(explicit_codes)}",
                })
                continue

        # Path B: LLM classification from product descriptions
        if product_descriptions:
            try:
                result = structured_llm.invoke(
                    HS_CLASSIFICATION_PROMPT.format_messages(
                        product_descriptions=product_descriptions,
                        case_title=case_title,
                    )
                )
                sections = sorted(set(s for s in result.sections if 1 <= s <= 21))

                # Validate with keyword fallback
                if not sections:
                    sections = _keyword_sections(product_descriptions)

                results.append({
                    "case_id": case_id,
                    "hs_sections": "|".join(str(s) for s in sections),
                    "product_descriptions": product_descriptions,
                    "extraction_method": "llm_classification",
                    "confidence": "medium" if sections else "low",
                    "reasoning": result.reasoning,
                })
                time.sleep(LLM_BATCH_PAUSE)

            except Exception as e:
                logger.error("LLM classification failed for DS%s: %s", case_id, e)
                # Keyword fallback
                sections = _keyword_sections(product_descriptions)
                results.append({
                    "case_id": case_id,
                    "hs_sections": "|".join(str(s) for s in sections),
                    "product_descriptions": product_descriptions,
                    "extraction_method": "keyword_fallback",
                    "confidence": "low",
                    "reasoning": f"LLM failed, keyword match: {e}",
                })
        else:
            results.append({
                "case_id": case_id,
                "hs_sections": "",
                "product_descriptions": "",
                "extraction_method": "no_data",
                "confidence": "low",
                "reasoning": "No product descriptions available",
            })

        # Checkpoint
        if (idx + 1) % CHECKPOINT_EVERY == 0:
            pd.DataFrame(results).to_csv(output_path, index=False)

    # Save case-level output
    sections_df = pd.DataFrame(results)
    sections_df.to_csv(output_path, index=False)
    logger.info("Saved %d rows to %s", len(sections_df), output_path)

    # Build expanded table (one row per case-section pair)
    expanded_rows = []
    for _, row in sections_df.iterrows():
        hs_str = str(row.get("hs_sections", ""))
        if not hs_str or hs_str == "nan":
            continue
        for sec in hs_str.split("|"):
            sec = sec.strip()
            if sec:
                expanded_rows.append({
                    "case_id": row["case_id"],
                    "hs_section": int(sec),
                    "extraction_method": row["extraction_method"],
                    "confidence": row["confidence"],
                })

    expanded_df = pd.DataFrame(expanded_rows)
    expanded_df.to_csv(expanded_path, index=False)
    logger.info("Saved %d rows to %s", len(expanded_df), expanded_path)

    return sections_df, expanded_df


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Task A Stage 2: HS classification")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    classify_all(resume=not args.no_resume)
