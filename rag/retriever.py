"""Retriever for WTO DSB documents from ChromaDB.

Supports metadata filtering (by case, complainant, agreement, etc.)
and semantic similarity search.
"""

from typing import Dict, List, Optional

from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain.schema import Document

from rag.config import (
    CHROMA_PERSIST_DIR, COLLECTION_NAME, TOP_K, EMBEDDING_MODEL,
)


def get_vectorstore(persist_dir: Optional[str] = None) -> Chroma:
    """Load existing ChromaDB vector store."""
    persist = persist_dir or CHROMA_PERSIST_DIR
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=persist,
    )


def search(query: str, k: int = TOP_K,
           filters: Optional[Dict] = None,
           persist_dir: Optional[str] = None) -> List[Document]:
    """Semantic search with optional metadata filters.

    Args:
        query: Natural language query
        k: Number of results
        filters: ChromaDB where clause, e.g. {"case_number": "135"}
    """
    vs = get_vectorstore(persist_dir)
    kwargs = {"k": k}
    if filters:
        kwargs["filter"] = filters
    return vs.similarity_search(query, **kwargs)


def search_by_case(query: str, case_number: str, k: int = TOP_K) -> List[Document]:
    """Search within a specific DS case."""
    return search(query, k=k, filters={"case_number": case_number})


def search_by_complainant(query: str, complainant: str, k: int = TOP_K) -> List[Document]:
    """Search cases filed by a specific complainant."""
    return search(query, k=k, filters={"complainant": complainant})
