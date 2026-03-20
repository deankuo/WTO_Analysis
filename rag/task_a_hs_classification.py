"""Task A — Stage 2: HS section classification.

Two-step classification per case:
  Step 1: LLM decides if the case is PRODUCT-specific or POLICY/systemic.
  Step 2: LLM classifies into HS sections (1-21) with reasoning.

Inputs:
  - Data/Output/industry_extraction.csv (product_descriptions, notes from Stage 1)
  - Data/wto_cases_v2.csv (product column = title-derived ground truth)
  - RAG retrieval (original document text, re-retrieved per case)

Outputs:
  - Data/Output/case_hs_sections.csv       (one row per case)
  - Data/Output/case_section_expanded.csv   (one row per case-section pair)

Mutual exclusivity: each case is either PRODUCT or POLICY, never both.
  - PRODUCT: product_descriptions populated, policy empty → sections from products
  - POLICY: policy populated, product_descriptions empty → sections from policy scope
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
    CASES_CSV_PATH,
    CLASSIFICATION_MODEL,
    CHECKPOINT_EVERY,
    HS_MAPPING_PATH,
    LLM_BATCH_PAUSE,
    LLM_TIMEOUT,
    MAX_CASE_NUM,
    MAX_CONTEXT_CHARS,
    OUTPUT_DIR,
)
from rag.schemas import HSClassification

logger = logging.getLogger(__name__)

# ── HS Section reference (1-21 = standard sections) ─────────

ALL_SECTIONS_STR = "|".join(str(i) for i in range(1, 22))  # "1|2|3|...|21"

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
        cleaned = code.strip().replace(".", "").replace(" ", "")
        cleaned = cleaned.upper().replace("HS", "").strip()
        if not cleaned or cleaned == "NAN":
            continue
        if len(cleaned) >= 2:
            try:
                chapter = int(cleaned[:2])
                if chapter in _CHAPTER_TO_SECTION:
                    sections.add(_CHAPTER_TO_SECTION[chapter])
            except ValueError:
                logger.warning("Could not parse HS code: %s", code)
    return sorted(sections)


# ── LLM classification prompt ────────────────────────────────

_HS_SECTION_LIST = "\n".join(
    f"Section {num}: {desc}" for num, desc in HS_SECTIONS.items()
)

HS_CLASSIFICATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are an expert in the Harmonized System (HS) trade classification and WTO disputes.\n\n"
     "Your task has TWO STEPS:\n\n"
     "### STEP 1: Determine case type ###\n"
     "Decide if this is a PRODUCT dispute or a POLICY dispute:\n"
     "- PRODUCT: The dispute targets specific traded goods (e.g., steel, salmon, automobiles, "
     "semiconductors). The measure may be anti-dumping duties, countervailing duties, safeguards, "
     "or other measures, but they are applied to identifiable products.\n"
     "- POLICY: The dispute challenges a law, regulation, methodology, or systemic measure "
     "that does NOT target specific traded goods (e.g., customs valuation procedures, "
     "IP regime, import licensing system, zeroing methodology).\n\n"
     "### STEP 2: Classify into HS sections ###\n"
     "Here are the 21 HS sections:\n" + _HS_SECTION_LIST + "\n\n"
     "- For PRODUCT cases: identify the specific HS sections (1-21) the products fall under. "
     "You MUST identify at least one specific section. Do NOT return all 21 unless the "
     "products genuinely span all sectors.\n"
     "- For POLICY cases: determine if the policy is HORIZONTAL (affects all sectors → all 21 sections) "
     "or SECTOR-SPECIFIC (e.g., 'agricultural subsidies' → sections 1-4, "
     "'anti-dumping on steel' → section 15). Use your judgment.\n\n"
     "### OUTPUT ###\n"
     "- case_type: 'product' or 'policy'\n"
     "- sections: list of HS section numbers (1-21)\n"
     "- reasoning: explain your classification decision\n"
     "- policy_description: (only for policy cases) brief description of the policy/measure"),
    ("human",
     "Case: DS{case_id}\nCase title: {case_title}\n"
     "Title product (from case title): {title_product}\n\n"
     "RAG-extracted product descriptions: {product_descriptions}\n"
     "Extraction notes: {notes}\n\n"
     "Original document text:\n{context}\n\n"
     "Classify this dispute."),
])

TITLE_CLASSIFICATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are an expert in the Harmonized System (HS) trade classification.\n\n"
     "Given ONLY the product name from a WTO dispute case title, classify it.\n\n"
     "### STEP 1: Determine case type ###\n"
     "- PRODUCT: Targets specific traded goods.\n"
     "- POLICY: Challenges a law, regulation, or systemic measure.\n\n"
     "### STEP 2: Classify into HS sections ###\n"
     "Here are the 21 sections:\n" + _HS_SECTION_LIST + "\n\n"
     "For product cases: return specific sections. "
     "For policy cases: return all 21 if horizontal, or specific sectors if sector-specific.\n\n"
     "Output: case_type, sections, reasoning, policy_description (if policy)."),
    ("human",
     "Product from case title: {title_product}\n\n"
     "Classify this dispute based ONLY on this product name."),
])


# ── Title-based ground truth classification ──────────────────

def _classify_title_product(
    title_product: str,
    structured_llm,
) -> tuple[str, str, str]:
    """Classify a title product into HS sections using LLM.

    Returns (hs_sections_str, case_type, reasoning).
    Never returns empty sections — worst case returns ALL_SECTIONS_STR.
    """
    if not title_product or title_product == "nan":
        return ALL_SECTIONS_STR, "policy", "No title product available"

    try:
        result = structured_llm.invoke(
            TITLE_CLASSIFICATION_PROMPT.format_messages(title_product=title_product)
        )
        sections = sorted(set(s for s in result.sections if 1 <= s <= 21))
        if sections:
            return "|".join(str(s) for s in sections), result.case_type, result.reasoning
    except Exception as e:
        logger.warning("Title classification failed for '%s': %s", title_product, e)

    return ALL_SECTIONS_STR, "policy", "Classification failed — defaulting to all sections"


# ── Main classification ──────────────────────────────────────

def classify_all(resume: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read industry_extraction.csv and classify into HS sections.

    Two-step process per case:
      1. Determine product vs policy (LLM decision, not keyword heuristic)
      2. Classify into HS sections with reasoning

    Two independent classifications per case:
      - title_hs_sections: from `product` column in wto_cases_v2.csv (ground truth)
      - hs_sections: from RAG product_descriptions + retrieved context

    Mutual exclusivity enforced:
      - Product cases: product_descriptions populated, policy empty
      - Policy cases: policy populated, product_descriptions cleared

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

    # Load product column from wto_cases_v2.csv as ground truth
    cases_df = pd.read_csv(CASES_CSV_PATH, dtype={"case": str})
    cases_df["case_id"] = cases_df["case"].str.replace(r"^DS", "", regex=True)
    product_lookup = cases_df.set_index("case_id")["product"].to_dict()
    title_lookup = cases_df.set_index("case_id")["title"].to_dict()
    n_with_product = sum(1 for v in product_lookup.values() if isinstance(v, str) and v.strip())
    logger.info("Loaded %d products from %s (ground truth)", n_with_product, CASES_CSV_PATH)

    # Resume support
    completed = set()
    results = []
    if resume and os.path.exists(output_path):
        existing = pd.read_csv(output_path, dtype={"case_id": str})
        completed = set(existing["case_id"].tolist())
        results = existing.to_dict("records")
        logger.info("Resuming: %d cases already classified", len(completed))

    # LLM setup
    llm = ChatOpenAI(model=CLASSIFICATION_MODEL, temperature=0, request_timeout=LLM_TIMEOUT)
    structured_llm = llm.with_structured_output(HSClassification)

    pending = df[~df["case_id"].isin(completed)]

    for idx, (_, row) in enumerate(tqdm(pending.iterrows(), total=len(pending), desc="HS classification")):
        case_id = str(row["case_id"])
        case_title = str(title_lookup.get(case_id, row.get("case_title", "")))
        product = str(product_lookup.get(case_id, ""))  # Ground truth from title
        product_descriptions = str(row.get("product_descriptions", ""))
        explicit_codes_str = str(row.get("explicit_hs_codes", ""))
        notes = str(row.get("notes", ""))
        context = str(row.get("retrieved_context", ""))

        explicit_codes = [
            c.strip() for c in explicit_codes_str.split("|")
            if c.strip() and c.strip().upper() != "NAN"
        ]

        # ── Ground truth: classify from product column (title-derived) ──
        title_hs, title_case_type, title_reasoning = _classify_title_product(
            product, structured_llm
        )
        time.sleep(LLM_BATCH_PAUSE)

        # ── RAG-based classification ──

        # Path A: explicit HS codes → deterministic lookup (always product case)
        if explicit_codes:
            sections = _hs_code_to_sections(explicit_codes)
            if sections:
                results.append({
                    "case_id": case_id,
                    "case_title": case_title,
                    "product": product if product != "nan" else "",
                    "title_hs_sections": title_hs,
                    "title_case_type": title_case_type,
                    "hs_sections": "|".join(str(s) for s in sections),
                    "case_type": "product",
                    "product_descriptions": product_descriptions if product_descriptions != "nan" else "",
                    "policy": "",
                    "extraction_method": "explicit_hs",
                    "confidence": "high",
                    "reasoning": f"Mapped from explicit codes: {', '.join(explicit_codes)}",
                })
                continue

        # Path B: LLM classification with context from Stage 1
        if not context or context == "nan":
            context = "(No documents retrieved)"
        elif len(context) > MAX_CONTEXT_CHARS:
            context = context[:MAX_CONTEXT_CHARS] + "\n\n[... truncated]"

        try:
            result = structured_llm.invoke(
                HS_CLASSIFICATION_PROMPT.format_messages(
                    case_id=case_id,
                    case_title=case_title,
                    title_product=product if product != "nan" else "(none)",
                    product_descriptions=product_descriptions if product_descriptions != "nan" else "(none)",
                    notes=notes if notes != "nan" else "",
                    context=context,
                )
            )

            sections = sorted(set(s for s in result.sections if 1 <= s <= 21))
            if not sections:
                # LLM returned no valid sections — default to all
                sections = list(range(1, 22))
                logger.warning("DS%s: LLM returned no valid sections, defaulting to all", case_id)

            hs_str = "|".join(str(s) for s in sections)
            case_type = result.case_type

            # Enforce mutual exclusivity
            if case_type == "product":
                out_product_desc = product_descriptions if product_descriptions != "nan" else ""
                out_policy = ""
            else:
                out_product_desc = ""
                out_policy = result.policy_description if result.policy_description else case_title

            results.append({
                "case_id": case_id,
                "case_title": case_title,
                "product": product if product != "nan" else "",
                "title_hs_sections": title_hs,
                "title_case_type": title_case_type,
                "hs_sections": hs_str,
                "case_type": case_type,
                "product_descriptions": out_product_desc,
                "policy": out_policy,
                "extraction_method": "llm_classification",
                "confidence": "high" if case_type == "product" and hs_str != ALL_SECTIONS_STR else "medium",
                "reasoning": result.reasoning,
            })
            time.sleep(LLM_BATCH_PAUSE)

        except Exception as e:
            logger.error("LLM classification failed for DS%s: %s", case_id, e)
            # Fallback: use title classification
            results.append({
                "case_id": case_id,
                "case_title": case_title,
                "product": product if product != "nan" else "",
                "title_hs_sections": title_hs,
                "title_case_type": title_case_type,
                "hs_sections": title_hs,
                "case_type": title_case_type,
                "product_descriptions": product_descriptions if product_descriptions != "nan" else "",
                "policy": "",
                "extraction_method": "title_fallback",
                "confidence": "low",
                "reasoning": f"LLM failed ({e}), using title classification",
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
            if sec and sec != "nan":
                try:
                    expanded_rows.append({
                        "case_id": row["case_id"],
                        "hs_section": int(sec),
                        "case_type": row["case_type"],
                        "extraction_method": row["extraction_method"],
                        "confidence": row["confidence"],
                    })
                except ValueError:
                    pass

    expanded_df = pd.DataFrame(expanded_rows)
    expanded_df.to_csv(expanded_path, index=False)
    logger.info("Saved %d rows to %s", len(expanded_df), expanded_path)

    # Print summary stats
    n_product = (sections_df["case_type"] == "product").sum()
    n_policy = (sections_df["case_type"] == "policy").sum()
    n_all_sections = (sections_df["hs_sections"] == ALL_SECTIONS_STR).sum()
    has_policy = (sections_df["policy"] != "").sum() if "policy" in sections_df.columns else 0
    has_product_desc = (sections_df["product_descriptions"] != "").sum() if "product_descriptions" in sections_df.columns else 0

    logger.info(
        "Classification: %d product, %d policy | "
        "%d all-sections | %d with product_descriptions, %d with policy",
        n_product, n_policy, n_all_sections, has_product_desc, has_policy,
    )

    # Extraction method distribution
    method_counts = sections_df["extraction_method"].value_counts()
    for method, count in method_counts.items():
        logger.info("  extraction_method=%s: %d", method, count)

    # Title vs RAG comparison (exclude all-section cases)
    specific_both = sections_df[
        (sections_df["title_hs_sections"] != ALL_SECTIONS_STR) &
        (sections_df["hs_sections"] != ALL_SECTIONS_STR)
    ]
    if len(specific_both) > 0:
        matches = 0
        for _, row in specific_both.iterrows():
            title_set = set(str(row["title_hs_sections"]).split("|"))
            rag_set = set(str(row["hs_sections"]).split("|"))
            if title_set & rag_set:  # any overlap
                matches += 1
        logger.info(
            "HS validation: %d/%d specific cases where title overlaps RAG sections (%.0f%%)",
            matches, len(specific_both), matches / len(specific_both) * 100,
        )

    return sections_df, expanded_df


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Task A Stage 2: HS classification")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    classify_all(resume=not args.no_resume)
