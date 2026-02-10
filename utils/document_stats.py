"""Calculate true document counts accounting for multi-part files.

Multi-part files (like 308R-00.pdf, 308R-01.pdf) represent a single original
document split across multiple PDFs. This module provides functions to:
1. Group multi-part files into original documents
2. Calculate accurate document counts
3. Generate statistics by document type
"""

import pandas as pd
import json
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict


def load_processed_data(jsonl_path: str) -> pd.DataFrame:
    """Load processed documents from JSONL file.

    Args:
        jsonl_path: Path to the JSONL file (e.g., wto_documents_full.jsonl)

    Returns:
        DataFrame with all processed documents
    """
    records = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    return pd.DataFrame(records)


def create_document_grouping_key(row: pd.Series) -> Tuple:
    """Create a grouping key for multi-part documents.

    Documents with the same grouping key are parts of the same original document.

    Args:
        row: DataFrame row containing document metadata

    Returns:
        Tuple that uniquely identifies the original document
    """
    # Extract relevant fields
    case = row['case_number']
    doc_class = row['doc_class']
    variant = row.get('variant')

    # For numbered documents, use the doc number from original filename
    # Extract from original filename (e.g., "267-45.pdf" → doc_num=45)
    original = row['original_filename']

    # Try to extract doc_number from various patterns
    import re
    doc_num = None

    # Pattern: {case}-{num}
    m = re.match(rf'^{case}-(\d+)', original)
    if m:
        doc_num = int(m.group(1))

    # For reports (R, ABR, RW, ARB), extract the variant number if any
    # Pattern: {case}R{num}, {case}RW{num}, {case}ABR, {case}ABRA{num}
    variant_num = None
    if 'R' in original and doc_class in ['PANEL_REPORT', 'AB_REPORT', 'RECOURSE', 'ARBITRATION']:
        # Extract number after R, RW, ABR, ABRA, etc.
        patterns = [
            r'RW(\d+)', r'RA(\d+)', r'ABRA(\d+)', r'ABRW(\d+)',
            r'ARB(\d+)', r'R(\d+)'
        ]
        for pattern in patterns:
            m = re.search(pattern, original)
            if m:
                variant_num = int(m.group(1))
                break

    # Create grouping key
    # Documents with same (case, doc_num, doc_class, variant, variant_num) are the same original doc
    key = (case, doc_num, doc_class, variant, variant_num)

    return key


def calculate_original_document_stats(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
    """Calculate statistics for original documents (grouping multi-part files).

    Args:
        df: DataFrame with processed documents

    Returns:
        Tuple of (original_docs_df, stats_dict):
        - original_docs_df: DataFrame with one row per original document
        - stats_dict: Dictionary with overall statistics
    """
    # Add grouping key to each row
    df['group_key'] = df.apply(create_document_grouping_key, axis=1)

    # Group by key
    grouped = df.groupby('group_key')

    # Create one row per original document
    original_docs = []

    for group_key, group_df in grouped:
        # Sort by part_number to get correct first part
        group_df = group_df.sort_values('part_number', na_position='first')

        # Use the first part's metadata (or only part if single-file doc)
        first_part = group_df.iloc[0]

        # Create original document record
        original_doc = {
            'case_number': first_part['case_number'],
            'doc_type': first_part['doc_type'],
            'doc_class': first_part['doc_class'],
            'variant': first_part['variant'],
            'date': first_part['date'],
            'num_parts': len(group_df),
            'is_multi_part': len(group_df) > 1,
            'part_filenames': ', '.join(group_df['original_filename'].tolist()),
            'new_filename_base': first_part['new_filename'],
            'page_count_total': group_df['page_count'].sum(),
        }

        original_docs.append(original_doc)

    original_docs_df = pd.DataFrame(original_docs)

    # Calculate overall statistics
    stats = {
        'total_files': len(df),
        'total_original_documents': len(original_docs_df),
        'multi_part_documents': len(original_docs_df[original_docs_df['is_multi_part']]),
        'single_file_documents': len(original_docs_df[~original_docs_df['is_multi_part']]),
        'total_pages': original_docs_df['page_count_total'].sum(),
        'avg_pages_per_document': original_docs_df['page_count_total'].mean(),
        'max_parts_in_document': original_docs_df['num_parts'].max(),
    }

    # Document type statistics (for original documents, not files)
    type_counts = original_docs_df['doc_type'].value_counts().to_dict()
    stats['documents_by_type'] = type_counts

    # Multi-part statistics by type
    multi_part_by_type = original_docs_df[original_docs_df['is_multi_part']].groupby('doc_type').size().to_dict()
    stats['multi_part_documents_by_type'] = multi_part_by_type

    return original_docs_df, stats


def print_document_statistics(stats: Dict):
    """Print formatted document statistics.

    Args:
        stats: Dictionary returned by calculate_original_document_stats
    """
    print("="*80)
    print("WTO DOCUMENT STATISTICS (Original Documents)")
    print("="*80)
    print()

    print(f"Total PDF files:              {stats['total_files']:,}")
    print(f"Total original documents:     {stats['total_original_documents']:,}")
    print(f"  - Single-file documents:    {stats['single_file_documents']:,}")
    print(f"  - Multi-part documents:     {stats['multi_part_documents']:,}")
    print()

    print(f"Total pages:                  {stats['total_pages']:,}")
    print(f"Average pages per document:   {stats['avg_pages_per_document']:.1f}")
    print(f"Max parts in one document:    {stats['max_parts_in_document']}")
    print()

    print("Top 15 Document Types (by original document count):")
    print("-"*80)
    type_counts = stats['documents_by_type']
    for doc_type, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
        multi_part = stats['multi_part_documents_by_type'].get(doc_type, 0)
        multi_part_pct = (multi_part / count * 100) if count > 0 else 0
        print(f"  {count:4d}  {doc_type:40s}  ({multi_part} multi-part, {multi_part_pct:.1f}%)")
    print()

    print(f"Total document types: {len(type_counts)}")
    print("="*80)


def export_document_stats(original_docs_df: pd.DataFrame, output_path: str):
    """Export original document statistics to CSV.

    Args:
        original_docs_df: DataFrame with original documents
        output_path: Path to save CSV file
    """
    original_docs_df.to_csv(output_path, index=False)
    print(f"Exported original document statistics to: {output_path}")


def analyze_documents(jsonl_path: str, export_csv: bool = True) -> Tuple[pd.DataFrame, Dict]:
    """Convenience function to analyze documents and print statistics.

    Args:
        jsonl_path: Path to JSONL file
        export_csv: Whether to export results to CSV (default: True)

    Returns:
        Tuple of (original_docs_df, stats_dict)

    Example:
        >>> from utils.document_stats import analyze_documents
        >>> df, stats = analyze_documents('Output/full/wto_documents_full.jsonl')
        >>> print(f"Total original documents: {stats['total_original_documents']}")
    """
    df = load_processed_data(jsonl_path)
    original_docs_df, stats = calculate_original_document_stats(df)
    print_document_statistics(stats)

    if export_csv:
        output_dir = Path(jsonl_path).parent
        csv_path = output_dir / "original_documents_stats.csv"
        export_document_stats(original_docs_df, str(csv_path))

    return original_docs_df, stats


# Example usage
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m utils.document_stats <jsonl_file>")
        print("Example: python -m utils.document_stats Output/full/wto_documents_full.jsonl")
        sys.exit(1)

    jsonl_path = sys.argv[1]

    print(f"Loading data from: {jsonl_path}")
    df = load_processed_data(jsonl_path)
    print(f"Loaded {len(df)} document records")
    print()

    print("Calculating original document statistics...")
    original_docs_df, stats = calculate_original_document_stats(df)
    print()

    print_document_statistics(stats)

    # Optionally export to CSV
    output_dir = Path(jsonl_path).parent
    csv_path = output_dir / "original_documents_stats.csv"
    export_document_stats(original_docs_df, str(csv_path))

    # Show examples of multi-part documents
    print("\nExamples of Multi-Part Documents:")
    print("-"*80)
    multi_part = original_docs_df[original_docs_df['is_multi_part']].sort_values('num_parts', ascending=False)
    for _, row in multi_part.head(10).iterrows():
        print(f"{row['doc_type']:30s} | Case {row['case_number']:3s} | {row['num_parts']} parts | {row['part_filenames'][:80]}...")
