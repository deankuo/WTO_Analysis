"""Process ALL 626 WTO DSB cases.

Usage:
  python scripts/process_all.py              # Dry run (no renames)
  python scripts/process_all.py --rename     # Actually rename files
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.processor import WTODocumentProcessor

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = PROJECT_ROOT / "WTO_DSB_Cases"
METADATA_CSV = PROJECT_ROOT / "data" / "wto_cases.csv"
OUTPUT_DIR = PROJECT_ROOT / "Output" / "full"


def main():
    parser = argparse.ArgumentParser(description="Process all WTO DSB case documents")
    parser.add_argument('--rename', action='store_true', help='Execute renames (default: dry run)')
    args = parser.parse_args()

    processor = WTODocumentProcessor(CASES_DIR, METADATA_CSV, OUTPUT_DIR)
    docs = processor.process_cases()

    processor.save_csv(docs, 'wto_documents_full.csv')
    processor.save_jsonl(docs, 'wto_documents_full.jsonl')
    processor.save_rename_manifest(docs, 'rename_manifest_full.json')
    processor.save_manual_review('manual_review_full.json')
    processor.save_third_party_joinings('third_party_full.json')

    processor.execute_renames(docs, dry_run=not args.rename)

    print(f"\nTotal documents processed: {len(docs)}")
    print(f"Manual review needed: {len(processor.manual_review)}")
    print(f"Outputs in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
