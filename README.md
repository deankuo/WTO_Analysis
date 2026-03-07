# WTO Dispute Settlement Network Analysis & RAG System

## Project Overview

This project analyzes World Trade Organization (WTO) dispute settlement cases through:
1. **Social Network Analysis (SNA)**: Mapping relationships between countries in trade disputes
2. **Document Processing Pipeline**: Renaming, classifying, and extracting text from 9,435 PDFs across 626 cases
3. **RAG System**: Retrieval-augmented generation for LLM-based case severity comparison

**Data Source:** [WTO Dispute Settlement](https://www.wto.org/english/tratop_e/dispu_e/dispu_e.htm)

## Project Structure

```
WTO/
├── data/
│   └── wto_cases.csv              # Case metadata (626 cases)
├── WTO_DSB_Cases/
│   └── [1-629]/                   # PDF documents by case number (9,435 files)
├── utils/
│   ├── filename_parser.py         # WTO filename pattern parsing (20+ patterns)
│   ├── text_cleaner.py            # Content extraction & header cleaning
│   ├── processor.py               # Main orchestrator, naming, output
│   ├── basic_matrix.py            # SNA network metrics
│   └── visualization.py           # Network visualization
├── rag/
│   ├── config.py                  # ChromaDB & embedding settings
│   ├── indexer.py                 # JSONL -> ChromaDB indexing
│   └── retriever.py               # Semantic search with metadata filters
├── scripts/
│   ├── process_sample.py          # Process sample cases
│   ├── process_all.py             # Process all 626 cases
│   ├── build_index.py             # Build vector index
│   └── build_baci_trade.py        # BACI trade aggregation (dual EU representation)
├── Output/
│   ├── sample/                    # Sample outputs (CSV, JSONL, manifests)
│   └── full/                      # Full run outputs
├── wto_document_processor.py      # Legacy monolithic processor (superseded by utils/)
├── CLAUDE.md                      # Development guidance
└── README.md                      # This file
```

## Document Processing Pipeline

### What It Does

1. **Parses filenames** to extract structural metadata (case number, document class, variant, part)
2. **Extracts text** using PyPDFLoader, with OCR fallback (Tesseract) for scanned PDFs
3. **Reads first page** to extract date, WTO header codes, agreement indicators, document type
4. **Filters TOC pages** from long documents (>5 pages) using pattern detection
5. **Generates semantic filenames**: `DS{case}_SEQ{nn}_{DocType}[_Suffix].pdf`
6. **Outputs**: metadata CSV (no text), JSONL with clean text, rename manifest, third-party joiners, manual review list

### Processing Statistics (Feb 2026)

- **Total documents**: 9,480 PDFs across 626 cases
- **Successfully classified**: 9,398 (99.1%)
- **Manual review**: 82 files (78 scanned, 3 non-English, 1 error)
- **Document types**: 35 consolidated types (from 56)
- **Date coverage**: ~90% (multilingual + inheritance)
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

## Environment Setup

### Python Dependencies

```bash
pip install langchain langchain-community langchain-openai chromadb networkx pandas matplotlib selenium pypdf pytesseract pdf2image
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

## Datasets

### WTO Case Data

- **626 cases** (DS1–DS626) with metadata: complainant, respondent, third parties, agreements cited, procedural dates, dispute stage
- **9,480 PDFs** across 629 folders, processed into 35 document types
- Coverage: 1995–2024

### Country-Year Analysis Panel (`Data/country_meta_1995_2024.csv`)

A comprehensive country-year panel integrating six major data sources for **196 countries/polities × 30 years (1995–2024)** = 5,880 observations and 77 variables.

| Source | Variables | Coverage |
|--------|-----------|----------|
| WTO membership & dispute records | `wto_member`, `complainant`, `respondent`, `third_party`, cumulative counts | 1995–2024 |
| World Development Indicators (WDI) | GDP, GDP per capita, population, trade, FDI, exports, imports, unemployment | 1995–2024 |
| Worldwide Governance Indicators (WGI) | Voice, stability, efficiency, regulatory quality, rule of law, corruption | 1995–2024 (interpolated for pre-2002 gaps) |
| UN Voting Ideal Points (Bailey, Strezhnev & Voeten 2017) | `idealpointfp`, `idealpointall`, posterior quantiles | 1995–2024 |
| V-Dem v15 | Electoral democracy, liberal democracy, regime type, election type | 1995–2024 |
| COW NMC 6.0 | CINC, military expenditures, military personnel, energy consumption, population | 1995–**2016** only |
| EU / ATOP alliance data | EU membership, eurozone, alliance obligations | 1995–2024 |

> See [`Data/Data.md`](Data/Data.md) for the full variable codebook, source citations with page references, range/unit details, and systematic missing data documentation.

### Bilateral Trade Datasets

Constructed from BACI HS92 data by `scripts/build_baci_trade.py`. Uses **dual EU representation**: individual EU member states retain their own trade rows (including intra-EU trade) while an `EUN` aggregate captures the EU as a single external trade actor. Includes paired `export_dependence` and `import_dependence` indices measuring asymmetric bilateral trade interdependence.

| File | Unit | Rows |
|------|------|------|
| `Data/bilateral_trade_aggregate.csv` | Directed dyad-year | ~1.2M |
| `Data/bilateral_trade_by_section.csv` | Directed dyad-year-section | ~10M |
| `Data/baci_to_iso3_mapping.csv` | Reference mapping | ~250 |
| `Data/eu_membership_1995_2024.csv` | Country-year (28 EU members x 30 years) | 840 |

> See [`Data/Data.md`](Data/Data.md) Sections 6--8 for full column definitions and EU representation details.

### Dyads Dataset (Forthcoming)

A directed country-pair-year panel (`dyads_1995_2024.csv`) capturing bilateral dispute history, UN voting alignment, trade flows, and ATOP alliance obligations. Structure documented in `Data/Data.md`.
