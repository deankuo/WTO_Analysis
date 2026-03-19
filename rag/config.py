"""Configuration for WTO RAG system.

All paths, model names, API keys, and tuning constants live here.
Retrieval, extraction, and scoring modules import from this file.
"""

import os
from pathlib import Path

# ── Project root ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── API keys (from environment / .env) ────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
COHERE_API_KEY = os.getenv("COHERE_API_KEY")

# ── Models ────────────────────────────────────────────────────
EMBEDDING_MODEL = "text-embedding-3-small"
EXTRACTION_MODEL = "gpt-5-mini"   # Task A industry extraction
CLASSIFICATION_MODEL = "gpt-5-mini"              # Task A HS classification
SEVERITY_MODEL = "gpt-5-mini"     # Task B severity scoring
RERANK_MODEL = "rerank-v3.5"                      # Cohere reranking

# ── Store paths (pre-built, read-only) ────────────────────────
CHROMA_DB_DIR = str(PROJECT_ROOT / "Data" / "stores" / "chroma_db")
PARENT_STORE_DIR = str(PROJECT_ROOT / "Data" / "stores" / "parent_store")
BM25_INDEX_PATH = str(PROJECT_ROOT / "Data" / "stores" / "bm25_index.pkl")
CHROMA_COLLECTION_NAME = "wto_child_chunks"

# ── Data paths ────────────────────────────────────────────────
JSONL_PATH = str(PROJECT_ROOT / "Data" / "WTO" / "wto_documents_full.jsonl")
LABELED_JSONL_PATH = str(PROJECT_ROOT / "Data" / "WTO" / "wto_documents_labeled.jsonl")
CASES_CSV_PATH = str(PROJECT_ROOT / "Data" / "wto_cases_v2.csv")
HS_MAPPING_PATH = str(PROJECT_ROOT / "Data" / "hs_section_mapping.json")
OUTPUT_DIR = str(PROJECT_ROOT / "Data" / "Output")

# ── Chunking params (must match ingest.py values) ────────────
SHORT_DOC_TOKEN_THRESHOLD = 6000
PARENT_CHUNK_SIZE = 6000
PARENT_CHUNK_OVERLAP = 800
CHILD_CHUNK_SIZE = 1200
CHILD_CHUNK_OVERLAP = 200

# ── Retrieval tuning ─────────────────────────────────────────
# Task-specific routing defaults
INDUSTRY_DOC_TYPE_FILTER = ["Request_For_Consultations", "Panel_Report"]
INDUSTRY_BM25_WEIGHT = 0.5
INDUSTRY_SEMANTIC_WEIGHT = 0.5
INDUSTRY_USE_HYDE = False
INDUSTRY_USE_MULTI_QUERY = False    # Title + single query is sufficient
INDUSTRY_PRE_RERANK_K = 15

SEVERITY_AUTHORING_ENTITY_FILTER = ["complainant"]
SEVERITY_BM25_WEIGHT = 0.3
SEVERITY_SEMANTIC_WEIGHT = 0.7
SEVERITY_USE_HYDE = True
SEVERITY_USE_MULTI_QUERY = True
SEVERITY_PRE_RERANK_K = 15

TOP_K_FINAL = 8          # Final parent chunks returned to LLM
RRF_K = 60               # RRF smoothing constant
NUM_QUERY_VARIANTS = 3   # Multi-query expansion count

# ── RAG document coverage ───────────────────────────────────
MAX_CASE_NUM = 626   # Documents collected up to DS626; cases 627+ have no PDFs

# ── Batch processing ─────────────────────────────────────────
COHERE_SLEEP_SECONDS = 6   # Rate limit pause between rerank calls
LLM_BATCH_PAUSE = 0.5      # Pause between LLM calls
CHECKPOINT_EVERY = 10      # Write intermediate results every N cases
MAX_WORKERS = 4            # Parallel threads for LLM calls
