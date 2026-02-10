"""Build ChromaDB vector index from processed JSONL.

Usage:
  python scripts/build_index.py                              # Default: sample
  python scripts/build_index.py --input Output/full/wto_documents_full.jsonl
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.indexer import build_index

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSONL = PROJECT_ROOT / "Output" / "sample" / "wto_sample.jsonl"


def main():
    parser = argparse.ArgumentParser(description="Build ChromaDB index from JSONL")
    parser.add_argument('--input', type=str, default=str(DEFAULT_JSONL),
                        help='Path to JSONL file')
    parser.add_argument('--persist-dir', type=str, default=None,
                        help='ChromaDB persistence directory (default: from rag/config.py)')
    args = parser.parse_args()

    build_index(jsonl_path=Path(args.input), persist_dir=args.persist_dir)


if __name__ == "__main__":
    main()
