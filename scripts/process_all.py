"""Process ALL 626 WTO DSB cases.

Usage:
  python scripts/process_all.py              # Dry run (no renames)
  python scripts/process_all.py --rename     # Actually rename files
"""

import sys
import argparse
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.processor import WTODocumentProcessor

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = PROJECT_ROOT / "WTO_DSB_Cases"
METADATA_CSV = PROJECT_ROOT / "Data" / "wto_cases.csv"
OUTPUT_DIR = PROJECT_ROOT / "Data" / "WTO"


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

    # ---- Detailed Summary ----
    print(f"\n{'='*60}")
    print(f"PROCESSING SUMMARY")
    print(f"{'='*60}")
    print(f"Total documents processed: {len(docs)}")

    # Document type distribution
    type_counts = Counter(d.doc_type for d in docs)
    print(f"\nDocument types ({len(type_counts)} types):")
    for dtype, count in type_counts.most_common(15):
        print(f"  {dtype:<45} {count:>5}")
    if len(type_counts) > 15:
        print(f"  ... and {len(type_counts) - 15} more types")

    # Files that could not be read or classified
    if processor.manual_review:
        print(f"\n{'='*60}")
        print(f"FILES NEEDING MANUAL REVIEW ({len(processor.manual_review)})")
        print(f"{'='*60}")
        reason_counts = Counter(m.get('reason', 'unknown') for m in processor.manual_review)
        for reason, count in reason_counts.most_common():
            print(f"  {reason}: {count}")
        print()
        for entry in processor.manual_review:
            reason = entry.get('reason', '')
            error = entry.get('error', '')
            detail = reason or error
            print(f"  {entry.get('folder', '?')}/{entry.get('filename', '?')} ({detail})")

    # Rename mapping sample
    print(f"\n{'='*60}")
    print(f"RENAME MAPPING (first 20)")
    print(f"{'='*60}")
    for doc in docs[:20]:
        changed = " " if doc.original_filename == doc.new_filename else "*"
        print(f"  {changed} {doc.folder_number}/{doc.original_filename}")
        print(f"    -> {doc.new_filename}")

    print(f"\nOutputs saved to: {OUTPUT_DIR}")
    print(f"  - wto_documents_full.csv   (metadata, no text)")
    print(f"  - wto_documents_full.jsonl (full data with clean_text)")
    print(f"  - rename_manifest_full.json")
    print(f"  - manual_review_full.json  ({len(processor.manual_review)} files)")
    print(f"  - third_party_full.json    ({len(processor.third_party_joinings)} entries)")


if __name__ == "__main__":
    main()
