"""Post-hoc normalization for severity and third party scores.

Run AFTER all raw scoring tasks (severity + third_party) and HS classification
are complete. Computes z-scores over the full population.

Inputs:
  - Data/Output/severity_scores_raw.csv
  - Data/Output/third_party_scores_raw.csv (optional)
  - Data/Output/case_section_expanded.csv (optional, for sector z-scores)

Outputs:
  - Data/Output/severity_scores.csv       (complainant, with z-scores)
  - Data/Output/third_party_scores.csv    (third party, with z-scores)
"""

import logging
import os

import pandas as pd

from rag.config import OUTPUT_DIR

logger = logging.getLogger(__name__)

SEVERITY_DIMS = [
    "rhetorical_aggressiveness",
    "systemic_reach",
    "escalation_ultimatum",
    "domestic_victimhood",
]

THIRD_PARTY_DIMS = [
    "engagement_intensity",
    "evidentiary_depth",
    "rhetorical_severity",
]


def _compute_z_scores(
    df: pd.DataFrame,
    score_col: str,
    group_col: str,
    suffix: str,
) -> pd.DataFrame:
    """Compute within-group z-score for a single score column."""
    col = f"{score_col}_{suffix}"
    df[col] = df.groupby(group_col)[score_col].transform(
        lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0.0
    )
    return df


def normalize_severity() -> pd.DataFrame | None:
    """Normalize complainant severity scores.

    Computes within-complainant and within-sector z-scores for:
      - each of the 4 dimensions
      - the composite severity_score

    Returns normalized DataFrame, or None if raw scores not found.
    """
    raw_path = os.path.join(OUTPUT_DIR, "severity_scores_raw.csv")
    output_path = os.path.join(OUTPUT_DIR, "severity_scores.csv")
    expanded_path = os.path.join(OUTPUT_DIR, "case_section_expanded.csv")

    if not os.path.exists(raw_path):
        logger.error("severity_scores_raw.csv not found — run severity scoring first")
        return None

    raw_df = pd.read_csv(raw_path, dtype={"case_id": str})
    df = raw_df.dropna(subset=["severity_score"]).copy()

    if len(df) < len(raw_df):
        logger.warning("%d cases failed scoring — excluded from normalization", len(raw_df) - len(df))

    if df.empty:
        logger.error("No valid scores to normalize")
        return None

    logger.info("Normalizing %d severity scores", len(df))

    # Z-scores for composite + each dimension
    score_cols = ["severity_score"] + SEVERITY_DIMS

    # Within-complainant z-scores
    for col in score_cols:
        if col in df.columns:
            df = _compute_z_scores(df, col, "complainant", "within_complainant_z")

    # Within-sector z-scores (requires HS data)
    if os.path.exists(expanded_path):
        expanded = pd.read_csv(expanded_path, dtype={"case_id": str})
        first_section = expanded.drop_duplicates(subset="case_id", keep="first")
        df = df.merge(first_section[["case_id", "hs_section"]], on="case_id", how="left")
        for col in score_cols:
            if col in df.columns:
                df = _compute_z_scores(df, col, "hs_section", "within_sector_z")
        logger.info("Sector z-scores computed using %d HS sections", df["hs_section"].nunique())
    else:
        logger.warning("case_section_expanded.csv not found — skipping sector normalization")

    df.to_csv(output_path, index=False)
    logger.info("Saved %d normalized scores to %s", len(df), output_path)
    return df


def normalize_third_party() -> pd.DataFrame | None:
    """Normalize third party engagement scores.

    Computes within-third_party and within-sector z-scores for:
      - each of the 3 dimensions
      - the composite engagement_score

    Returns normalized DataFrame, or None if raw scores not found.
    """
    raw_path = os.path.join(OUTPUT_DIR, "third_party_scores_raw.csv")
    output_path = os.path.join(OUTPUT_DIR, "third_party_scores.csv")
    expanded_path = os.path.join(OUTPUT_DIR, "case_section_expanded.csv")

    if not os.path.exists(raw_path):
        logger.warning("third_party_scores_raw.csv not found — skipping third party normalization")
        return None

    raw_df = pd.read_csv(raw_path, dtype={"case_id": str})
    df = raw_df.dropna(subset=["engagement_score"]).copy()

    if df.empty:
        logger.warning("No valid third party scores to normalize")
        return None

    logger.info("Normalizing %d third party scores", len(df))

    # Z-scores for composite + each dimension
    score_cols = ["engagement_score"] + THIRD_PARTY_DIMS

    # Within-third-party z-scores
    for col in score_cols:
        if col in df.columns:
            df = _compute_z_scores(df, col, "third_party", "within_third_party_z")

    # Within-sector z-scores
    if os.path.exists(expanded_path):
        expanded = pd.read_csv(expanded_path, dtype={"case_id": str})
        first_section = expanded.drop_duplicates(subset="case_id", keep="first")
        df = df.merge(first_section[["case_id", "hs_section"]], on="case_id", how="left")
        for col in score_cols:
            if col in df.columns:
                df = _compute_z_scores(df, col, "hs_section", "within_sector_z")
    else:
        logger.warning("case_section_expanded.csv not found — skipping sector normalization")

    df.to_csv(output_path, index=False)
    logger.info("Saved %d normalized third party scores to %s", len(df), output_path)
    return df


def normalize_all():
    """Run all normalization steps."""
    normalize_severity()
    normalize_third_party()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    normalize_all()
