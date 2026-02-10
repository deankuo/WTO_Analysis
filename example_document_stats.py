"""Example: Calculate true document counts accounting for multi-part files."""

from utils.document_stats import analyze_documents

# Analyze documents from the full processing output
print("Analyzing WTO documents...")
print()

df, stats = analyze_documents('Output/full/wto_documents_full.jsonl')

print("\n" + "="*80)
print("ADDITIONAL ANALYSIS")
print("="*80)

# Show breakdown by case count
print(f"\nDocuments per case (average): {stats['total_original_documents'] / 626:.1f}")

# Show multi-part percentage
multi_part_pct = (stats['multi_part_documents'] / stats['total_original_documents']) * 100
print(f"Multi-part document rate: {multi_part_pct:.1f}%")

# Show how much consolidation happened
files = stats['total_files']
docs = stats['total_original_documents']
reduction = ((files - docs) / files) * 100
print(f"File count reduction: {files} files → {docs} original documents ({reduction:.1f}% reduction)")

# Show type distribution
print("\nAll Document Types:")
print("-"*80)
for doc_type, count in sorted(stats['documents_by_type'].items(), key=lambda x: x[1], reverse=True):
    print(f"  {count:4d}  {doc_type}")

# Access the DataFrame for further analysis
print("\n" + "="*80)
print("DataFrame available for further analysis:")
print(f"  - Shape: {df.shape}")
print(f"  - Columns: {list(df.columns)}")
print()
print("Example queries:")
print("  df[df['is_multi_part']].head()  # Show multi-part documents")
print("  df.groupby('doc_type')['num_parts'].mean()  # Average parts per type")
print("  df[df['num_parts'] > 10]  # Documents with more than 10 parts")
