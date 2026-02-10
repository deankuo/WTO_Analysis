"""Process a diverse sample of WTO DSB cases for validation."""

import sys
from pathlib import Path
from collections import Counter

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.processor import WTODocumentProcessor

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = PROJECT_ROOT / "WTO_DSB_Cases"
METADATA_CSV = PROJECT_ROOT / "data" / "wto_cases.csv"
OUTPUT_DIR = PROJECT_ROOT / "Output" / "sample"

SAMPLE_CASES = ['135', '624', '625', '626']


def main():
    processor = WTODocumentProcessor(CASES_DIR, METADATA_CSV, OUTPUT_DIR)
    docs = processor.process_cases(SAMPLE_CASES)

    # Save all outputs
    processor.save_csv(docs, 'wto_sample.csv')
    processor.save_jsonl(docs, 'wto_sample.jsonl')
    processor.save_rename_manifest(docs, 'rename_manifest_sample.json')
    processor.save_manual_review('manual_review_sample.json')
    processor.save_third_party_joinings('third_party_sample.json')

    # Dry-run rename
    processor.execute_renames(docs, dry_run=True)

    # Summary
    print(f"\n{'='*60}")
    print("SAMPLE PROCESSING SUMMARY")
    print(f"{'='*60}")
    print(f"Documents processed: {len(docs)}")
    print(f"Manual review needed: {len(processor.manual_review)}")
    print(f"Third-party joinings detected: {len(processor.third_party_joinings)}")

    type_dist = Counter(d.doc_type for d in docs)
    print(f"\nDocument types found:")
    for dtype, count in type_dist.most_common():
        print(f"  {dtype}: {count}")

    print(f"\nRename preview:")
    for doc in docs:
        print(f"  {doc.original_filename:25s} -> {doc.new_filename}")

    print(f"\nOutputs in: {OUTPUT_DIR}")
    return docs


if __name__ == "__main__":
    main()
