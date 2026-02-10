"""Index WTO documents into ChromaDB using ParentDocumentRetriever.

Reads processed JSONL, splits into parent/child chunks, and stores in ChromaDB.
"""

import json
from pathlib import Path
from typing import Optional

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain.schema import Document

from rag.config import (
    CHROMA_PERSIST_DIR, COLLECTION_NAME,
    PARENT_CHUNK_SIZE, CHILD_CHUNK_SIZE, CHUNK_OVERLAP,
    EMBEDDING_MODEL,
)


def load_documents(jsonl_path: Path) -> list[Document]:
    """Load JSONL into LangChain Document objects."""
    docs = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            record = json.loads(line.strip())
            if not record.get('clean_text'):
                continue

            metadata = {k: v for k, v in record.items() if k != 'clean_text'}
            docs.append(Document(page_content=record['clean_text'], metadata=metadata))

    print(f"Loaded {len(docs)} documents from {jsonl_path}")
    return docs


def build_index(jsonl_path: Path, persist_dir: Optional[str] = None):
    """Build ChromaDB index from JSONL file."""
    persist = persist_dir or CHROMA_PERSIST_DIR
    documents = load_documents(jsonl_path)

    if not documents:
        print("No documents to index.")
        return

    # Split into child chunks for retrieval
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHILD_CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )

    child_docs = []
    for doc in documents:
        chunks = child_splitter.split_text(doc.page_content)
        for i, chunk in enumerate(chunks):
            child_meta = {**doc.metadata, 'chunk_index': i, 'total_chunks': len(chunks)}
            child_docs.append(Document(page_content=chunk, metadata=child_meta))

    print(f"Split into {len(child_docs)} child chunks")

    # Build vector store
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    vectorstore = Chroma.from_documents(
        documents=child_docs,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=persist,
    )

    print(f"Index built: {len(child_docs)} chunks in {persist}")
    return vectorstore
