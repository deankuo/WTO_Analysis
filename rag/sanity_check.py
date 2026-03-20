"""Sanity check and re-run for cases with missing data.

Identifies cases with empty product_descriptions or missing HS sections,
removes them from output CSVs, and re-runs extraction + classification
for just those cases.

Usage:
    python -m rag.sanity_check              # Report only
    python -m rag.sanity_check --fix        # Re-run problematic cases
    python -m rag.sanity_check --fix --workers 8
"""

import logging
import os

import pandas as pd

from rag.config import OUTPUT_DIR

logger = logging.getLogger(__name__)


def find_problems() -> dict:
    """Identify cases with missing data in outputs.

    Returns dict with lists of case_ids for each problem type.
    """
    problems = {
        "empty_product_descriptions": [],
        "empty_hs_sections": [],
        "empty_title_hs": [],
        "mutual_exclusivity_violation": [],
        "failed_severity": [],
    }

    # Check industry_extraction.csv
    extraction_path = os.path.join(OUTPUT_DIR, "industry_extraction.csv")
    if os.path.exists(extraction_path):
        df = pd.read_csv(extraction_path, dtype={"case_id": str})
        empty_pd = df[
            df["product_descriptions"].isna() |
            (df["product_descriptions"] == "") |
            (df["product_descriptions"] == "nan")
        ]
        problems["empty_product_descriptions"] = empty_pd["case_id"].tolist()

    # Check case_hs_sections.csv
    hs_path = os.path.join(OUTPUT_DIR, "case_hs_sections.csv")
    if os.path.exists(hs_path):
        df = pd.read_csv(hs_path, dtype={"case_id": str})

        empty_hs = df[
            df["hs_sections"].isna() |
            (df["hs_sections"] == "") |
            (df["hs_sections"] == "nan")
        ]
        problems["empty_hs_sections"] = empty_hs["case_id"].tolist()

        empty_title = df[
            df["title_hs_sections"].isna() |
            (df["title_hs_sections"] == "") |
            (df["title_hs_sections"] == "nan")
        ]
        problems["empty_title_hs"] = empty_title["case_id"].tolist()

        # Check mutual exclusivity: product_descriptions XOR policy
        if "case_type" in df.columns:
            for _, row in df.iterrows():
                has_pd = bool(row.get("product_descriptions") and str(row["product_descriptions"]).strip() not in ("", "nan"))
                has_policy = bool(row.get("policy") and str(row["policy"]).strip() not in ("", "nan"))
                if has_pd and has_policy:
                    problems["mutual_exclusivity_violation"].append(str(row["case_id"]))
                elif not has_pd and not has_policy:
                    problems["mutual_exclusivity_violation"].append(str(row["case_id"]))

    # Check severity_scores_raw.csv
    severity_path = os.path.join(OUTPUT_DIR, "severity_scores_raw.csv")
    if os.path.exists(severity_path):
        df = pd.read_csv(severity_path, dtype={"case_id": str})
        failed = df[df["severity_score"].isna()]
        problems["failed_severity"] = failed["case_id"].tolist()

    return problems


def print_report(problems: dict):
    """Print a summary of data quality issues."""
    print("\n" + "=" * 60)
    print("SANITY CHECK REPORT")
    print("=" * 60)

    total_issues = 0
    for problem_type, case_ids in problems.items():
        label = problem_type.replace("_", " ").title()
        count = len(case_ids)
        total_issues += count
        if count > 0:
            preview = ", ".join(case_ids[:10])
            if count > 10:
                preview += f", ... (+{count - 10} more)"
            print(f"\n  {label}: {count} cases")
            print(f"    Case IDs: {preview}")
        else:
            print(f"\n  {label}: 0 (OK)")

    print(f"\n{'=' * 60}")
    if total_issues == 0:
        print("All checks passed.")
    else:
        print(f"Total issues: {total_issues}")
        print("Run with --fix to re-process problematic cases.")
    print("=" * 60 + "\n")


def fix_extraction(case_ids: list[str], max_workers: int = 4):
    """Re-run industry extraction for specific cases.

    Removes these cases from existing output, then re-runs.
    """
    if not case_ids:
        return

    extraction_path = os.path.join(OUTPUT_DIR, "industry_extraction.csv")
    if os.path.exists(extraction_path):
        df = pd.read_csv(extraction_path, dtype={"case_id": str})
        before = len(df)
        df = df[~df["case_id"].isin(case_ids)]
        df.to_csv(extraction_path, index=False)
        logger.info("Removed %d cases from industry_extraction.csv", before - len(df))

    from rag.task_a_industry import extract_all
    logger.info("Re-running industry extraction for %d cases: %s", len(case_ids), case_ids)
    extract_all(case_ids=case_ids, resume=True, max_workers=max_workers)


def fix_hs_classification(case_ids: list[str]):
    """Re-run HS classification for specific cases.

    Removes these cases from existing outputs, then re-runs.
    """
    if not case_ids:
        return

    for filename in ["case_hs_sections.csv", "case_section_expanded.csv"]:
        path = os.path.join(OUTPUT_DIR, filename)
        if os.path.exists(path):
            df = pd.read_csv(path, dtype={"case_id": str})
            before = len(df)
            df = df[~df["case_id"].isin(case_ids)]
            df.to_csv(path, index=False)
            logger.info("Removed %d rows from %s", before - len(df), filename)

    from rag.task_a_hs_classification import classify_all
    logger.info("Re-running HS classification for %d cases", len(case_ids))
    classify_all(resume=True)


def fix_severity(case_ids: list[str], max_workers: int = 4):
    """Re-run severity scoring for specific cases."""
    if not case_ids:
        return

    raw_path = os.path.join(OUTPUT_DIR, "severity_scores_raw.csv")
    if os.path.exists(raw_path):
        df = pd.read_csv(raw_path, dtype={"case_id": str})
        before = len(df)
        df = df[~df["case_id"].isin(case_ids)]
        df.to_csv(raw_path, index=False)
        logger.info("Removed %d cases from severity_scores_raw.csv", before - len(df))

    from rag.task_b_severity import score_all
    logger.info("Re-running severity scoring for %d cases: %s", len(case_ids), case_ids)
    score_all(case_ids=case_ids, resume=True, max_workers=max_workers)


def fix_all(problems: dict, max_workers: int = 4):
    """Re-run all problematic cases."""
    # Fix extraction first (HS depends on it)
    extraction_cases = problems["empty_product_descriptions"]
    if extraction_cases:
        fix_extraction(extraction_cases, max_workers)

    # Fix HS classification (includes cases from extraction + own issues)
    hs_cases = set(problems["empty_hs_sections"] + problems["empty_title_hs"] + extraction_cases)
    if hs_cases:
        fix_hs_classification(list(hs_cases))

    # Fix severity
    severity_cases = problems["failed_severity"]
    if severity_cases:
        fix_severity(severity_cases, max_workers)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Sanity check and re-run")
    parser.add_argument("--fix", action="store_true", help="Re-run problematic cases")
    parser.add_argument("--workers", type=int, default=4, help="Parallel threads for re-runs")
    args = parser.parse_args()

    problems = find_problems()
    print_report(problems)

    if args.fix:
        any_issues = any(len(v) > 0 for v in problems.values())
        if any_issues:
            fix_all(problems, max_workers=args.workers)
            # Re-check after fixes
            print("\n--- POST-FIX CHECK ---")
            problems = find_problems()
            print_report(problems)
        else:
            print("Nothing to fix.")
