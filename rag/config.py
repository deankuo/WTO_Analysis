"""Configuration for WTO RAG system."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ChromaDB
CHROMA_PERSIST_DIR = str(PROJECT_ROOT / "Data" / "chroma_db_wto")
COLLECTION_NAME = "wto_dsb_documents"

# Chunking (for ParentDocumentRetriever)
PARENT_CHUNK_SIZE = 2000   # Parent chunks stored for context
CHILD_CHUNK_SIZE = 400     # Child chunks used for retrieval
CHUNK_OVERLAP = 100

# Retrieval
TOP_K = 5

# Embedding model (OpenAI by default; swap for local if needed)
EMBEDDING_MODEL = "text-embedding-3-small"
