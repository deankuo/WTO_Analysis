"""Export LocalFileStore parent chunks to a SQLite database for HuggingFace upload.

The LocalFileStore (Data/stores/parent_store/) holds 65k+ files where each
filename is the parent_id key and each file contains UTF-8 JSON: {"text": "..."}.

This script reads every file and writes it into a single SQLite database:

    CREATE TABLE chunks (key TEXT PRIMARY KEY, text TEXT NOT NULL)

The resulting .db file is compact (~50-80 MB), trivially uploaded to HF, and
supports O(log n) key lookups without loading everything into memory.

Usage:
    python scripts/export_parentstore_sqlite.py \\
        Data/stores/parent_store \\
        parent_store.db

Then upload to the same HF dataset repo:
    huggingface-cli upload YOUR_USERNAME/wto-rag-stores parent_store.db
"""

import argparse
import json
import sqlite3
from pathlib import Path


def export(input_dir: Path, output_path: Path) -> None:
    files = [f for f in input_dir.iterdir() if f.is_file()]
    print(f"Found {len(files):,} files in {input_dir}")

    conn = sqlite3.connect(output_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chunks (key TEXT PRIMARY KEY, text TEXT NOT NULL)"
    )
    # Explicit index is redundant for a PRIMARY KEY column in SQLite, but makes
    # the intent clear and guarantees the B-tree index is present.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_key ON chunks (key)")

    inserted = 0
    skipped  = 0
    total    = len(files)

    # Commit in batches of 5000 to balance memory and I/O
    BATCH = 5000
    batch_rows = []

    def flush():
        nonlocal inserted
        conn.executemany(
            "INSERT OR REPLACE INTO chunks (key, text) VALUES (?, ?)", batch_rows
        )
        conn.commit()
        inserted += len(batch_rows)
        batch_rows.clear()

    for fp in files:
        try:
            raw = fp.read_bytes()
            data = json.loads(raw.decode("utf-8"))
            text = data["text"]
            batch_rows.append((fp.name, text))
        except Exception as e:
            print(f"  Skipping {fp.name}: {e}")
            skipped += 1
            continue

        if len(batch_rows) >= BATCH:
            flush()
            print(f"  Inserted {inserted:,} / {total:,} ...")

    if batch_rows:
        flush()

    conn.close()

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"\nDone. Exported {inserted:,} chunks, skipped {skipped}.")
    print(f"Output: {output_path}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Export LocalFileStore → SQLite for HF upload"
    )
    parser.add_argument("input_dir", type=Path, help="LocalFileStore root directory")
    parser.add_argument("output_db", type=Path,  help="Output SQLite .db file path")
    args = parser.parse_args()

    if not args.input_dir.is_dir():
        raise SystemExit(f"Error: {args.input_dir} is not a directory")

    export(args.input_dir, args.output_db)
