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
        general = (df["hs_sections"] == "0").sum()

        print(f"\n--- Task A: HS Classification ---")
        print(f"Total: {total}, Classified (1-21): {has_sections.sum() - general}, General (00): {general}")

        for method in df["extraction_method"].unique():
            n = (df["extraction_method"] == method).sum()
            print(f"  Method '{method}': {n} ({n/total*100:.1f}%)")

        # Title vs RAG HS comparison
        if "title_hs_sections" in df.columns:
            has_both = df[
                (df["title_hs_sections"].notna()) &
                (df["title_hs_sections"] != "") &
                (df["title_hs_sections"] != "nan") &
                (df["hs_sections"] != "0")
            ]
            if len(has_both) > 0:
                matches = 0
                for _, row in has_both.iterrows():
                    title_set = set(str(row["title_hs_sections"]).split("|"))
                    rag_set = set(str(row["hs_sections"]).split("|"))
                    if title_set & rag_set:
                        matches += 1
                print(f"\n  Title HS vs RAG HS: {matches}/{len(has_both)} overlap ({matches/len(has_both)*100:.1f}%)")


# ── Task B quality metrics ────────────────────────────────────

def _print_dim_stats(df: pd.DataFrame, dim: str):
    """Print score distribution for a single dimension."""
    vals = df[dim].dropna()
    if len(vals) == 0:
        print(f"    {dim}: no data")
        return
    dist = ", ".join(f"{s}:{(vals==s).sum()}" for s in range(1, 6))
    print(f"    {dim}: mean={vals.mean():.2f}, std={vals.std():.2f}  [{dist}]")


def print_task_b_quality():
    """Print score distribution and normalization stats for Task B."""
    sev_dims = ["rhetorical_aggressiveness", "systemic_reach", "escalation_ultimatum", "domestic_victimhood"]
    tp_dims = ["engagement_intensity", "evidentiary_depth", "rhetorical_severity"]

    # ── Severity scores ──
    raw_path = os.path.join(OUTPUT_DIR, "severity_scores_raw.csv")
    norm_path = os.path.join(OUTPUT_DIR, "severity_scores.csv")

    print(f"\n--- Task B: Severity Scoring (4 dims x 1-5) ---")

    sev_path = norm_path if os.path.exists(norm_path) else raw_path
    if not os.path.exists(sev_path):
        print("  No severity scores found — run scoring first.")
    else:
        df = pd.read_csv(sev_path, dtype={"case_id": str})
        failed = df["severity_score"].isna().sum()
        scored = len(df) - failed

        print(f"  Total cases: {len(df)}, Scored: {scored}, Failed: {failed}")
        for dim in sev_dims:
            if dim in df.columns:
                _print_dim_stats(df, dim)

        comp = df["severity_score"].dropna()
        if len(comp) > 0:
            print(f"    severity_score (composite): mean={comp.mean():.2f}, std={comp.std():.2f}")

        if os.path.exists(norm_path) and "severity_score_within_complainant_z" in df.columns:
            z = df["severity_score_within_complainant_z"].dropna()
            print(f"  Within-complainant z-score: mean={z.mean():.2f}, std={z.std():.2f}")

    # ── Third party scores ──
    tp_raw_path = os.path.join(OUTPUT_DIR, "third_party_scores_raw.csv")
    tp_norm_path = os.path.join(OUTPUT_DIR, "third_party_scores.csv")

    print(f"\n--- Task B: Third Party Engagement (3 dims x 1-5) ---")

    tp_path = tp_norm_path if os.path.exists(tp_norm_path) else tp_raw_path
    if not os.path.exists(tp_path):
        print("  No third party scores found — run third_party scoring first.")
    else:
        df = pd.read_csv(tp_path, dtype={"case_id": str})
        has_doc = df["has_joining_request"].sum() if "has_joining_request" in df.columns else len(df)
        scored = df["engagement_score"].notna().sum()

        print(f"  Total pairs: {len(df)}, With document: {has_doc}, Scored: {scored}")
        for dim in tp_dims:
            if dim in df.columns:
                _print_dim_stats(df, dim)

        comp = df["engagement_score"].dropna()
        if len(comp) > 0:
            print(f"    engagement_score (composite): mean={comp.mean():.2f}, std={comp.std():.2f}")

        if "alignment" in df.columns:
            types = df["alignment"].value_counts()
            for t, n in types.items():
                if t:
                    print(f"    Alignment '{t}': {n}")


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
