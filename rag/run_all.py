"""Main orchestrator for the WTO RAG pipeline.

Usage:
    python -m rag.run_all all                   # Run industry + hs + severity + normalize
    python -m rag.run_all industry              # Task A Stage 1 only
    python -m rag.run_all hs                    # Task A Stage 2 only
    python -m rag.run_all severity              # Task B only (raw scores)
    python -m rag.run_all normalize             # Z-score normalization (needs severity + hs done)
    python -m rag.run_all industry hs           # Multiple steps
    python -m rag.run_all validate              # Run validation report
    python -m rag.run_all industry --cases 379 436   # Specific cases
    python -m rag.run_all all --fresh           # Start fresh, ignore checkpoints
"""

import logging
import os
import sys
import time

from rag.config import COHERE_API_KEY, OPENAI_API_KEY, OUTPUT_DIR

logger = logging.getLogger(__name__)

VALID_STEPS = {"industry", "hs", "severity", "third_party", "normalize", "validate", "all"}


def _check_env():
    """Verify required API keys are set."""
    missing = []
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not COHERE_API_KEY:
        missing.append("COHERE_API_KEY")
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        logger.error("Set them in .env or export before running.")
        sys.exit(1)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="WTO RAG Pipeline",
        usage="python -m rag.run_all <steps> [options]",
    )
    parser.add_argument(
        "steps", nargs="+", choices=sorted(VALID_STEPS),
        help="Steps to run: industry, hs, severity, validate, all",
    )
    parser.add_argument("--cases", nargs="*", help="Specific case IDs (default: all 626)")
    parser.add_argument("--workers", type=int, default=4, help="Parallel threads (default: 4)")
    parser.add_argument("--fresh", action="store_true", help="Start fresh, ignore existing checkpoints")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    _check_env()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    resume = not args.fresh

    steps = set(args.steps)
    if "all" in steps:
        steps = {"industry", "hs", "severity", "third_party", "normalize", "validate"}

    start = time.time()

    # ── Industry extraction (Task A Stage 1) ──
    if "industry" in steps:
        logger.info("=" * 50)
        logger.info("Task A Stage 1: Industry extraction")
        logger.info("=" * 50)
        from rag.task_a_industry import extract_all
        extract_all(case_ids=args.cases, resume=resume, max_workers=args.workers)

    # ── HS classification (Task A Stage 2) ──
    if "hs" in steps:
        logger.info("=" * 50)
        logger.info("Task A Stage 2: HS section classification")
        logger.info("=" * 50)
        from rag.task_a_hs_classification import classify_all
        classify_all(resume=resume)

    # ── Severity scoring (Task B) ──
    if "severity" in steps:
        logger.info("=" * 50)
        logger.info("Task B: Severity scoring (raw)")
        logger.info("=" * 50)
        from rag.task_b_severity import score_all
        score_all(case_ids=args.cases, resume=resume, max_workers=args.workers)

    # ── Third party scoring ──
    if "third_party" in steps:
        logger.info("=" * 50)
        logger.info("Task B: Third party scoring (raw)")
        logger.info("=" * 50)
        from rag.task_b_third_party import score_third_parties
        score_third_parties(case_ids=args.cases, resume=resume, max_workers=args.workers)

    # ── Normalization (z-scores) ──
    if "normalize" in steps:
        logger.info("=" * 50)
        logger.info("Normalization: z-scores")
        logger.info("=" * 50)
        from rag.normalize import normalize_all
        normalize_all()

    # ── Validation report ──
    if "validate" in steps:
        logger.info("=" * 50)
        logger.info("Validation report")
        logger.info("=" * 50)
        from rag.validation import full_report
        full_report()

    elapsed = time.time() - start
    logger.info("Pipeline complete in %.1f minutes", elapsed / 60)


if __name__ == "__main__":
    main()
