"""Validation framework for the WTO RAG system.

- Title-based validation for Task A: compares RAG-extracted products against
  the product hint parsed from case titles (available for ~396 of 626 cases)
- Quality metrics for both tasks
- Inter-rater reliability reporting for Task B
"""

import json
import logging
import os

import pandas as pd

from rag.config import OUTPUT_DIR

logger = logging.getLogger(__name__)


# ── Task A: Title-based validation ────────────────────────────

def validate_task_a_titles(verbose: bool = True) -> dict:
    """Validate RAG extraction against title-parsed product hints.

    For each case that has a title_product (parsed from "{Respondent} — {Product}"),
    check whether the RAG-extracted product_descriptions contain the title product
    as a substring. This is a soft check — the title is a short label, the RAG
    extraction should be more detailed.

    Returns dict with match/mismatch counts and details.
    """
    industry_path = os.path.join(OUTPUT_DIR, "industry_extraction.csv")

    if not os.path.exists(industry_path):
        logger.error("industry_extraction.csv not found")
        return {"total": 0, "with_title": 0, "matched": 0, "mismatched": 0, "details": []}

    df = pd.read_csv(industry_path, dtype={"case_id": str})

    # Only validate cases that have a title product
    has_title = df["title_product"].notna() & (df["title_product"] != "") & (df["title_product"] != "nan")
    titled = df[has_title].copy()

    report = {
        "total": len(df),
        "with_title": len(titled),
        "matched": 0,
        "mismatched": 0,
        "no_extraction": 0,
        "details": [],
    }

    for _, row in titled.iterrows():
        case_id = row["case_id"]
        title_product = str(row["title_product"]).lower().strip()
        rag_products = str(row.get("product_descriptions", "")).lower()

        # Soft match: check if key words from title appear in RAG output
        # Split title product into words, check if the most specific word appears
        title_words = [w for w in title_product.split() if len(w) > 3]
        if not title_words:
            title_words = title_product.split()

        matched = any(w in rag_products for w in title_words) if rag_products else False

        if not rag_products or rag_products == "nan" or rag_products == "":
            report["no_extraction"] += 1
            status = "NO_DATA"
        elif matched:
            report["matched"] += 1
            status = "MATCH"
        else:
            report["mismatched"] += 1
            status = "MISMATCH"

        detail = {
            "case_id": case_id,
            "title_product": row["title_product"],
            "rag_products": row.get("product_descriptions", "")[:120],
            "status": status,
        }
        report["details"].append(detail)

        if verbose and status == "MISMATCH":
            print(f"  [MISMATCH] DS{case_id}: title='{row['title_product']}' vs rag='{row.get('product_descriptions', '')[:80]}'")

    if verbose:
        match_rate = report["matched"] / report["with_title"] * 100 if report["with_title"] > 0 else 0
        print(f"\n  Title validation: {report['matched']}/{report['with_title']} matched ({match_rate:.1f}%)")
        print(f"  Mismatched: {report['mismatched']}, No extraction: {report['no_extraction']}")

    return report


# ── Task A quality metrics ────────────────────────────────────

def print_task_a_quality():
    """Print coverage and confidence distribution for Task A."""
    industry_path = os.path.join(OUTPUT_DIR, "industry_extraction.csv")
    sections_path = os.path.join(OUTPUT_DIR, "case_hs_sections.csv")

    if os.path.exists(industry_path):
        df = pd.read_csv(industry_path, dtype={"case_id": str})
        total = len(df)
        has_products = df["product_descriptions"].notna() & (df["product_descriptions"] != "")
        has_title = df["title_product"].notna() & (df["title_product"] != "") & (df["title_product"] != "nan")

        print(f"\n--- Task A: Industry Extraction ---")
        print(f"Total cases: {total}")
        print(f"RAG extraction coverage: {has_products.sum()}/{total} ({has_products.mean()*100:.1f}%)")
        print(f"Title product available: {has_title.sum()}/{total} ({has_title.mean()*100:.1f}%)")

        for conf in ["high", "medium", "low"]:
            n = (df["confidence"] == conf).sum()
            if n > 0:
                print(f"  Confidence '{conf}': {n} ({n/total*100:.1f}%)")

        systemic = df["is_systemic"].sum() if "is_systemic" in df.columns else 0
        services = df["is_services"].sum() if "is_services" in df.columns else 0
        print(f"  Systemic: {systemic}, Services: {services}")

    if os.path.exists(sections_path):
        df = pd.read_csv(sections_path, dtype={"case_id": str})
        total = len(df)
        has_sections = df["hs_sections"].notna() & (df["hs_sections"] != "") & (df["hs_sections"] != "nan")

        print(f"\n--- Task A: HS Classification ---")
        print(f"Coverage: {has_sections.sum()}/{total} ({has_sections.mean()*100:.1f}%) — target >85%")

        for method in df["extraction_method"].unique():
            n = (df["extraction_method"] == method).sum()
            print(f"  Method '{method}': {n} ({n/total*100:.1f}%)")


# ── Task B quality metrics ────────────────────────────────────

def print_task_b_quality():
    """Print score distribution and normalization stats for Task B."""
    output_path = os.path.join(OUTPUT_DIR, "severity_scores.csv")
    if not os.path.exists(output_path):
        print("severity_scores.csv not found — run scoring first.")
        return

    df = pd.read_csv(output_path, dtype={"case_id": str})
    dims = ["rhetorical_intensity", "core_principles", "escalation_signals"]

    print(f"\n--- Task B Quality Report ---")
    print(f"Total scored: {len(df)} cases")

    for dim in dims:
        vals = df[dim].dropna()
        print(f"\n  {dim}:")
        for score in [1, 2, 3]:
            n = (vals == score).sum()
            print(f"    Score {score}: {n} ({n/len(vals)*100:.1f}%)")
        print(f"    Mean: {vals.mean():.2f}, Std: {vals.std():.2f}")

    if "composite" in df.columns:
        comp = df["composite"].dropna()
        print(f"\n  Composite: mean={comp.mean():.2f}, std={comp.std():.2f}")

    raw_path = os.path.join(OUTPUT_DIR, "severity_scores_raw.csv")
    if os.path.exists(raw_path):
        raw = pd.read_csv(raw_path, dtype={"case_id": str})
        failed = raw["rhetorical_intensity"].isna().sum()
        if failed > 0:
            print(f"\n  WARNING: {failed} cases failed scoring (see severity_scores_raw.csv)")


# ── Full report ───────────────────────────────────────────────

def full_report():
    """Run all validations and print comprehensive report."""
    print("=" * 60)
    print("WTO RAG SYSTEM — VALIDATION REPORT")
    print("=" * 60)

    print("\n1. Title-Based Validation (Task A)")
    title_report = validate_task_a_titles(verbose=True)

    print("\n2. Task A Quality Metrics")
    print_task_a_quality()

    print("\n3. Task B Quality Metrics")
    print_task_b_quality()

    # Save report as JSON
    report_path = os.path.join(OUTPUT_DIR, "validation_report.json")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(title_report, f, indent=2, default=str)
    print(f"\nValidation report saved to {report_path}")
    print("=" * 60)


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Validation & quality reports")
    parser.add_argument("--full-report", action="store_true", help="Run full validation report")
    args = parser.parse_args()

    if args.full_report:
        full_report()
    else:
        print("Title-Based Validation (Task A):")
        validate_task_a_titles(verbose=True)
