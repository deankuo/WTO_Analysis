# WTO Dispute Settlement Network Analysis & RAG System

## Project Overview

This project analyzes World Trade Organization (WTO) dispute settlement cases through:
1. **Social Network Analysis (SNA)**: Mapping relationships between countries in trade disputes
2. **Document Processing Pipeline**: Renaming, classifying, and extracting text from 9,417 PDFs across 626 cases
3. **RAG System**: Retrieval-augmented generation for LLM-based case severity comparison

**Data Source:** [WTO Dispute Settlement](https://www.wto.org/english/tratop_e/dispu_e/dispu_e.htm)

## Project Structure

```
WTO/
├── Data/
│   ├── country_meta_1995_2024.csv      # Country-year panel (196 x 30 years, 77 cols)
│   ├── wto_cases.csv                   # Case metadata (626 cases)
│   ├── wto_dyadic.csv                  # WTO dispute dyads (8,145 rows)
│   ├── bilateral_trade_wto.csv         # Dyad-year trade + ATOP + DESTA (545k rows)
│   ├── bilateral_trade_section_wto.csv # Dyad-year-section trade (6.4M rows)
│   ├── desta_panel_1995_2025.csv       # DESTA trade agreement panel (235k rows)
│   └── wto_mem_list.csv                # WTO membership list (166 members)
├── WTO_DSB_Cases/
│   └── [1-626]/                        # PDF documents by case number (9,417 files)
├── utils/
│   ├── filename_parser.py              # WTO filename pattern parsing (20+ patterns)
│   ├── text_cleaner.py                 # Content extraction & header cleaning
│   ├── processor.py                    # Main orchestrator, naming, output
│   ├── basic_matrix.py                 # SNA network metrics
│   └── visualization.py               # Network visualization
├── rag/
│   ├── config.py                       # ChromaDB & embedding settings
│   ├── indexer.py                      # JSONL -> ChromaDB indexing
│   └── retriever.py                    # Semantic search with metadata filters
├── scripts/
│   ├── process_sample.py               # Process sample cases
│   ├── process_all.py                  # Process all 626 cases
│   ├── build_index.py                  # Build vector index
│   ├── build_baci_trade.py             # BACI trade aggregation (dual EU representation)
│   └── build_dyadic_datasets.py        # Merge ATOP + DESTA + WTO filter
├── Output/
│   ├── sample/                         # Sample outputs (CSV, JSONL, manifests)
│   └── full/                           # Full run outputs
├── Data.md                             # Full data codebook
├── CLAUDE.md                           # Development guidance
└── README.md                           # This file
```

## Document Processing Pipeline

### What It Does

1. **Parses filenames** to extract structural metadata (case number, document class, variant, part)
2. **Extracts text** using PyPDFLoader, with OCR fallback (Tesseract) for scanned PDFs
3. **Reads first page** to extract date, WTO header codes, agreement indicators, document type
4. **Filters TOC pages** from long documents (>5 pages) using pattern detection
5. **Generates semantic filenames**: `DS{case}_SEQ{nn}_{DocType}[_Suffix].pdf`
6. **Outputs**: metadata CSV (no text), JSONL with clean text, rename manifest, third-party joiners, manual review list

### Preprocessing

- 63 PDFs pre-split on WTO website (2+ hyphens like `8-11-00.pdf`) were manually combined back into single files (folders 8, 99, 302, 457)
- Text cleaned via 10-step pipeline: header boilerplate removal, footnote removal, non-English line filtering, page number removal, punctuation artifact cleanup — all optimized for RAG embeddings

### Processing Statistics (March 2026)

- **Total documents**: 9,417 PDFs across 626 cases
- **Successfully classified**: 9,414 (99.97%)
- **Manual review**: 3 files (non-English cross-references)
- **Document types**: 42 types
- **Date coverage**: ~90% (multilingual + inheritance)
- **Third-party joinings**: 1,036 entries detected
- **Multi-part documents**: Automatic inheritance working

### Naming Convention

| Pattern | Example |
|---------|---------|
| Base document | `DS135_SEQ04_Note_By_Secretariat.pdf` |
| With variant | `DS626_SEQ02_Request_For_Consultations_Corr.pdf` |
| Multi-part | `DS135_SEQ13_Report_Of_Panel_00.pdf` |
| Duplicate type | `DS135_SEQ05_Communication_From_Chairman_Of_Panel_00.pdf` |

### Quick Start

```bash
# Process sample (cases 135, 624, 625, 626)
python scripts/process_sample.py

# Process all 626 cases (dry run)
python scripts/process_all.py

# Execute renames
python scripts/process_all.py --rename
```

## RAG System

Uses ChromaDB with child-chunk retrieval. Documents are chunked into small pieces for semantic search, with full document context available via metadata.

```bash
# Build index from processed JSONL
python scripts/build_index.py --input Output/sample/wto_sample.jsonl
```

Requires `OPENAI_API_KEY` in `.env` file.

## Social Network Analysis

### Network Model

- **Nodes**: Countries/entities
- **Edge Types**:
  - Complainant <-> Respondent: Conflict (red)
  - Complainant <-> Third Party: Cooperation (green)
  - Respondent <-> Third Party: Complex (orange)
- **Community Detection**: Louvain algorithm with modified modularity for signed networks

### Key Metrics

- Conflict density, modularity, centrality, betweenness
- Balanced/unbalanced triangle analysis
- Community detection with internal relation typing

## Research Objectives

1. Map and analyze relationships between countries in WTO dispute cases
2. Identify patterns in trade conflicts and cooperation
3. Build LLM-as-judge system for case severity comparison:
   - Severity relative to complainant's historical cases
   - Severity compared to similar industry cases
4. Develop predictive models for dispute outcomes

## Datasets

### Panel Data

| File | Unit | Rows | Cols | Sources |
|------|------|------|------|---------|
| `Data/country_meta_1995_2024.csv` | Country-year | 5,880 | 77 | WTO, WDI, WGI, UN Voting, V-Dem, COW NMC, EU/ATOP |
| `Data/wto_panel_1995_2024.csv` | Country-year | 5,880 | 18 | WTO subset of above |
| `Data/wto_mem_list.csv` | WTO member | 166 | 5 | WTO official records |

### Dyadic Data

| File | Unit | Rows | Description |
|------|------|------|-------------|
| `Data/wto_dyadic.csv` | Case-dyad | 8,145 | WTO dispute country pairs with case metadata |
| `Data/bilateral_trade_wto.csv` | Directed dyad-year | 545,333 | BACI trade + ATOP alliances + DESTA agreements, WTO-filtered |
| `Data/bilateral_trade_section_wto.csv` | Directed dyad-year-section | 6,374,486 | Sector-level trade, WTO-filtered |
| `Data/desta_panel_1995_2025.csv` | Undirected dyad-year | 235,011 | DESTA trade agreement panel |

### WTO Case Data

- **626 cases** (DS1–DS626) with metadata: complainant, respondent, third parties, agreements cited, procedural dates, dispute stage
- **9,417 PDFs** across 626 folders, processed into 35 document types
- Coverage: 1995–2024

> See [`Data/Data.md`](Data/Data.md) for the full variable codebook, source citations, and systematic missing data documentation.

## Environment Setup

### Python Dependencies

```bash
pip install langchain langchain-community langchain-openai chromadb networkx pandas matplotlib selenium pypdf pytesseract pdf2image country_converter
```

### System Dependencies (for OCR)

```bash
# macOS
brew install tesseract poppler

# Ubuntu/Debian
sudo apt-get install tesseract-ocr poppler-utils

# Windows
# Download from: https://github.com/UB-Mannheim/tesseract/wiki
```

### Environment Variables

Create `.env` file:
```
OPENAI_API_KEY=your_key_here
LANGCHAIN_API_KEY=your_key_here  # optional, for LangSmith tracing
```
