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
│   ├── wto_cases_v2.csv                # Case metadata (644 cases, 29 cols)
│   ├── wto_cases_harmonized.csv        # Harmonized case data with standardized names
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
│   ├── config.py                       # All configuration (paths, models, tuning)
│   ├── schemas.py                      # Pydantic models for structured LLM output
│   ├── retrieval.py                    # Hybrid search (BM25 + semantic) + RRF + Cohere rerank
│   ├── task_a_industry.py              # Stage 1: RAG-based product extraction
│   ├── task_a_hs_classification.py     # Stage 2: HS section classification (no RAG)
│   ├── task_b_severity.py              # Severity scoring (3 dimensions)
│   ├── validation.py                   # Ground truth tests + quality metrics
│   └── run_all.py                      # Pipeline orchestrator
├── scripts/
│   ├── ingest.py                       # Authoring entity labeling + chunking + store building
│   ├── scrape_wto_cases.py             # Selenium scraper for WTO case metadata (644 cases)
│   ├── process_sample.py               # Process sample cases
│   ├── process_all.py                  # Process all 626 cases
│   ├── build_index.py                  # Build vector index (legacy, superseded by ingest.py)
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

Retrieval-augmented generation system for two analytical tasks:

**Task A — Industry/HS Classification** (two stages):
1. RAG-based extraction of product descriptions and explicit HS codes from dispute documents
2. Classification into HS sections (0-21) via deterministic lookup or LLM; section 0 = general/systemic/services
   - Two independent classifications: `title_hs_sections` (from `product` column, ground truth) vs `hs_sections` (from RAG)

**Note:** RAG pipeline processes DS1-DS626 only (documents collected up to DS626). Cases DS627+ have metadata but no PDFs.

**Task B — Severity Scoring**:
Scores political framing intensity on 3 dimensions (rhetorical intensity, core principles invocation, escalation signals) using only the complainant's own documents. Post-hoc z-score normalization within complainant and sector.

### Architecture

```
Retrieval pipeline (retrieval.py):
  Query → Multi-query expansion → Hybrid search (ChromaDB + BM25) → RRF fusion → Cohere rerank → Parent chunk lookup

Pre-built stores (Data/stores/, read-only):
  chroma_db/      — Child chunk vectors (text-embedding-3-small)
  parent_store/   — Parent chunk texts (65k entries, LocalFileStore)
  bm25_index.pkl  — BM25 index (1.3 GB)
```

### Running the RAG Pipeline

```bash
# Set API keys
export OPENAI_API_KEY="..."
export COHERE_API_KEY="..."

# Run individual steps
python -m rag.run_all industry              # Task A Stage 1: extract products
python -m rag.run_all hs                    # Task A Stage 2: classify HS sections
python -m rag.run_all severity              # Task B: score severity
python -m rag.run_all validate              # Quality report

# Run everything
python -m rag.run_all all

# Options
python -m rag.run_all industry --cases 379 436 18   # Specific cases
python -m rag.run_all all --workers 8                # More parallelism
python -m rag.run_all all --fresh                    # Ignore checkpoints
```

### RAG Outputs

| File | Rows | Description |
|------|------|-------------|
| `Data/Output/industry_extraction.csv` | 626 | Products, explicit HS codes, systemic/services flags |
| `Data/Output/case_hs_sections.csv` | 626 | HS sections per case (title ground truth + RAG) |
| `Data/Output/case_section_expanded.csv` | ~800-1200 | One row per case-section pair (for trade merge) |
| `Data/Output/severity_scores.csv` | 626 | 3 dimensions + composite + z-scores |

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

- **644 cases** (DS1–DS644) in `wto_cases_v2.csv`: complainant, respondent, third parties, product, dispute_stage, current_status, key facts, summary (29 columns)
- **Country name harmonization**: European Communities → European Union, Turkey → Türkiye
- **9,417 PDFs** across 626 folders (DS1–DS626), processed into 42 document types
- RAG pipeline limited to DS1–DS626 (documents collected); cases DS627+ have metadata only
- Coverage: 1995–2024

> See [`Data/Data.md`](Data/Data.md) for the full variable codebook, source citations, and systematic missing data documentation.

## Environment Setup

### Python Dependencies

```bash
# Core
pip install langchain langchain-openai langchain-community langchain-chroma langchain-classic chromadb
pip install networkx pandas matplotlib selenium pypdf pytesseract pdf2image country_converter

# RAG pipeline
pip install cohere rank-bm25 tiktoken tqdm pydantic
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
COHERE_API_KEY=your_key_here        # For reranking (free tier sufficient)
LANGCHAIN_API_KEY=your_key_here     # Optional, for LangSmith tracing
```
