"""
WTO RAG System — Ingest Pipeline
=================================
Reads preprocessed JSONL, adds authoring entity labels, creates chunks,
embeds into ChromaDB, stores parents in LocalFileStore, builds BM25 index.

Run ONCE. After completion, stores are read-only during retrieval.

Usage:
    python ingest.py
    python ingest.py --label-only   # Only run authoring entity labeling, skip embedding
    python ingest.py --skip-label   # Skip labeling, assume already done

Prerequisites:
    pip install langchain langchain-openai langchain-community chromadb rank-bm25 pandas tqdm pydantic tiktoken
    export OPENAI_API_KEY="..."
    export ANTHROPIC_API_KEY="..."  # Optional, if using Claude for labeling
"""

import os
import json
import pickle
import logging
import argparse
import time
from pathlib import Path
from typing import List, Dict, Optional, Literal
from dataclasses import dataclass

import tiktoken
import pandas as pd
from tqdm import tqdm

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_classic.storage import LocalFileStore
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

# ============================================================
# Configuration — matches your project structure
# ============================================================

# Paths (from your modified spec)
JSONL_PATH = "Data/WTO/wto_documents_full.jsonl"
CHROMA_DB_DIR = "stores/chroma_db"
PARENT_STORE_DIR = "stores/parent_store"
BM25_INDEX_PATH = "stores/bm25_index.pkl"
OUTPUT_DIR = "Data"
LABELED_JSONL_PATH = "Data/WTO/wto_documents_labeled.jsonl"  # After adding authoring_entity

# Embedding
EMBEDDING_MODEL = "text-embedding-3-small"

# LLM for authoring entity labeling
LABELING_MODEL = "gpt-5-mini"  # Cheap and fast for this simple classification task

# Chunking thresholds
SHORT_DOC_TOKEN_THRESHOLD = 6000  # ≤ this → no split
CHILD_CHUNK_SIZE = 1200           # characters (~300 tokens)
CHILD_CHUNK_OVERLAP = 200         # characters (~50 tokens)
PARENT_CHUNK_SIZE = 6000          # characters (~1500 tokens)
PARENT_CHUNK_OVERLAP = 800        # characters (~200 tokens)

# ChromaDB
CHROMA_COLLECTION_NAME = "wto_child_chunks"
BATCH_SIZE = 500  # Documents per batch for ChromaDB insertion

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================
# JSONL Field Mapping
# ============================================================
# Your JSONL has these fields (from the sample you provided):
#   folder_number, case_number, original_filename, new_filename,
#   doc_sequence, doc_type, doc_type_raw, doc_class, variant,
#   part_number, case_title, date, header_codes, agreement_indicators,
#   complainant, respondent, third_parties, dispute_stage,
#   agreements_cited, case_summary, page_count, clean_text, processing_date

# We map these to our internal field names:
FIELD_MAP = {
    "case_id": "case_number",           # "1", "379", etc.
    "doc_id": "doc_sequence",           # 1, 2, 3, ...
    "doc_type": "doc_type",             # "Request_For_Consultations", etc.
    "doc_type_raw": "doc_type_raw",     # Full descriptive type
    "title": "case_title",              # "MALAYSIA - PROHIBITION OF IMPORTS..."
    "text": "clean_text",               # The actual document text
    "page_count": "page_count",         # Number of pages
    "source_file": "new_filename",      # e.g., "DS1_SEQ01_Request_For_Consultations.pdf"
    "date": "date",
    "complainant": "complainant",
    "respondent": "respondent",
    "header_codes": "header_codes",     # e.g., "WT/DS1/1"
    "agreements_cited": "agreements_cited",
}


# ============================================================
# Step 0: Authoring Entity Labeling
# ============================================================

class AuthoringEntity(BaseModel):
    """Structured output for document authoring entity classification."""
    entity_type: Literal[
        "complainant",
        "respondent",
        "third_party",
        "panel",
        "appellate_body",
        "arbitrator",
        "secretariat",
        "joint",
        "unknown"
    ] = Field(
        description="The type of entity that authored this document."
    )
    entity_name: str = Field(
        description="The specific name of the authoring entity. "
        "For countries, use the country name. "
        "For panel/AB/secretariat, use 'Panel', 'Appellate Body', 'Secretariat'. "
        "For joint documents, list all parties."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Confidence in the classification."
    )


# Many doc types can be classified by rules alone, no LLM needed
DOC_TYPE_TO_ENTITY_RULES = {
    "Request_For_Consultations": "complainant",
    "Panel_Report": "panel",
    "Appellate_Body_Report": "appellate_body",
    "Arbitration_Award": "arbitrator",
    "Communication_From_Director_General": "secretariat",
    "Constitution_Of_The_Panel": "secretariat",
    "Working_Procedures": "panel",
    "Notification_Of_Mutually_Agreed_Solution": "joint",
    "Notification_Of_Appeal": None,      # Could be either party → needs LLM or doc_type_raw
    "Third_Party_Submission": "third_party",
}


def label_authoring_entities(
    input_path: str = JSONL_PATH,
    output_path: str = LABELED_JSONL_PATH,
    max_records: int = 0,
):
    """
    Add authoring_entity and authoring_entity_name fields to each document.
    Uses rule-based classification first, falls back to LLM for ambiguous cases.
    """
    logger.info(f"Labeling authoring entities from {input_path}")

    # Load LLM for ambiguous cases
    llm = ChatOpenAI(model=LABELING_MODEL, temperature=0)
    structured_llm = llm.with_structured_output(AuthoringEntity)

    labeling_prompt = ChatPromptTemplate.from_messages([
        ("system", """Classify who authored this WTO dispute document. 
Options: complainant, respondent, third_party, panel, appellate_body, arbitrator, secretariat, joint, unknown.
Use the document type, header codes, and the first 500 characters of text to determine the author."""),
        ("human", """Case: DS{case_id} — {case_title}
Complainant: {complainant}
Respondent: {respondent}
Document type: {doc_type_raw}
Header codes: {header_codes}
First 500 chars of text:
{text_preview}

Who authored this document?"""),
    ])

    records = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line.strip()))

    if max_records > 0:
        records = records[:max_records]
        logger.info(f"Test mode: labeling only {max_records} documents")

    logger.info(f"Loaded {len(records)} documents")

    llm_call_count = 0
    rule_count = 0

    with open(output_path, "w", encoding="utf-8") as out_f:
        for rec in tqdm(records, desc="Labeling authoring entities"):
            doc_type = rec.get("doc_type", "")
            doc_type_raw = rec.get("doc_type_raw", "")
            complainant = rec.get("complainant", "[]")
            respondent = rec.get("respondent", "[]")

            # Try rule-based classification first
            rule_entity = DOC_TYPE_TO_ENTITY_RULES.get(doc_type)

            if rule_entity is not None:
                # Resolve "complainant"/"respondent" to actual country names
                if rule_entity == "complainant":
                    entity_name = complainant
                elif rule_entity == "respondent":
                    entity_name = respondent
                elif rule_entity == "joint":
                    entity_name = f"{complainant} & {respondent}"
                else:
                    entity_name = rule_entity.replace("_", " ").title()

                rec["authoring_entity"] = rule_entity
                rec["authoring_entity_name"] = entity_name
                rec["authoring_entity_confidence"] = "high"
                rule_count += 1

            else:
                # Fallback: use doc_type_raw to try rule-based
                raw_lower = doc_type_raw.lower()

                # Heuristic rules on doc_type_raw
                if "by " in raw_lower:
                    # e.g., "Request for Consultations under Article XXIII:1 by Singapore"
                    # The country after "by" is the author
                    after_by = doc_type_raw.split("by ")[-1].strip()
                    if any(c in after_by for c in eval(complainant) if isinstance(eval(complainant), list)):
                        rec["authoring_entity"] = "complainant"
                        rec["authoring_entity_name"] = after_by
                        rec["authoring_entity_confidence"] = "medium"
                        rule_count += 1
                    elif any(c in after_by for c in eval(respondent) if isinstance(eval(respondent), list)):
                        rec["authoring_entity"] = "respondent"
                        rec["authoring_entity_name"] = after_by
                        rec["authoring_entity_confidence"] = "medium"
                        rule_count += 1
                    else:
                        # "by" some third party or unknown
                        rec["authoring_entity"] = "third_party"
                        rec["authoring_entity_name"] = after_by
                        rec["authoring_entity_confidence"] = "medium"
                        rule_count += 1

                elif "panel" in raw_lower and "report" in raw_lower:
                    rec["authoring_entity"] = "panel"
                    rec["authoring_entity_name"] = "Panel"
                    rec["authoring_entity_confidence"] = "high"
                    rule_count += 1

                elif "appellate" in raw_lower:
                    rec["authoring_entity"] = "appellate_body"
                    rec["authoring_entity_name"] = "Appellate Body"
                    rec["authoring_entity_confidence"] = "high"
                    rule_count += 1

                elif "arbitrat" in raw_lower:
                    rec["authoring_entity"] = "arbitrator"
                    rec["authoring_entity_name"] = "Arbitrator"
                    rec["authoring_entity_confidence"] = "high"
                    rule_count += 1

                else:
                    # Truly ambiguous → use LLM
                    try:
                        text_preview = rec.get("clean_text", "")[:500]
                        result = structured_llm.invoke(
                            labeling_prompt.format_messages(
                                case_id=rec.get("case_number", ""),
                                case_title=rec.get("case_title", ""),
                                complainant=complainant,
                                respondent=respondent,
                                doc_type_raw=doc_type_raw,
                                header_codes=rec.get("header_codes", ""),
                                text_preview=text_preview,
                            )
                        )
                        rec["authoring_entity"] = result.entity_type
                        rec["authoring_entity_name"] = result.entity_name
                        rec["authoring_entity_confidence"] = result.confidence
                        llm_call_count += 1

                        # Rate limit
                        if llm_call_count % 50 == 0:
                            time.sleep(1)

                    except Exception as e:
                        logger.warning(f"LLM labeling failed for {rec.get('new_filename', '')}: {e}")
                        rec["authoring_entity"] = "unknown"
                        rec["authoring_entity_name"] = "Unknown"
                        rec["authoring_entity_confidence"] = "low"

            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    logger.info(
        f"Labeling complete. Rule-based: {rule_count}, LLM: {llm_call_count}, "
        f"Total: {rule_count + llm_call_count}"
    )
    logger.info(f"Saved labeled JSONL to {output_path}")


# ============================================================
# Step 1: Token Counting
# ============================================================

def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """Count tokens using tiktoken (OpenAI tokenizer)."""
    try:
        enc = tiktoken.get_encoding(model)
        return len(enc.encode(text))
    except Exception:
        # Fallback: rough estimate
        return int(len(text.split()) * 1.3)


# ============================================================
# Step 2: Chunking
# ============================================================

def create_chunks(
    records: List[Dict],
) -> tuple[List[Document], Dict[str, Dict]]:
    """
    Process all documents into child chunks and parent chunks.

    Returns:
        child_docs: List[Document] — all child chunks with metadata (for ChromaDB + BM25)
        parent_map: Dict[parent_id, {"text": str, "metadata": dict}] — parent chunks (for LocalFileStore)
    """
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHILD_CHUNK_SIZE,
        chunk_overlap=CHILD_CHUNK_OVERLAP,
        length_function=len,  # Character-based
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=PARENT_CHUNK_SIZE,
        chunk_overlap=PARENT_CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    child_docs = []
    parent_map = {}

    stats = {"short": 0, "long": 0, "empty": 0}

    for rec in tqdm(records, desc="Chunking documents"):
        text = rec.get("clean_text", "")
        if not text or len(text.strip()) < 50:
            stats["empty"] += 1
            continue

        case_id = str(rec.get("case_number", ""))
        doc_seq = str(rec.get("doc_sequence", ""))
        doc_id = f"DS{case_id}_SEQ{doc_seq.zfill(2)}"

        # Common metadata for this document
        base_metadata = {
            "case_id": case_id,
            "doc_id": doc_id,
            "doc_type": rec.get("doc_type", "unknown"),
            "doc_type_raw": rec.get("doc_type_raw", ""),
            "source_file": rec.get("new_filename", ""),
            "case_title": rec.get("case_title", ""),
            "date": rec.get("date", ""),
            "complainant": rec.get("complainant", ""),
            "respondent": rec.get("respondent", ""),
            "authoring_entity": rec.get("authoring_entity", "unknown"),
            "authoring_entity_name": rec.get("authoring_entity_name", ""),
            "header_codes": rec.get("header_codes", ""),
        }

        token_count = count_tokens(text)

        if token_count <= SHORT_DOC_TOKEN_THRESHOLD:
            # ---- SHORT DOCUMENT: No split ----
            stats["short"] += 1

            chunk_id = f"{doc_id}_full"
            parent_id = chunk_id  # Same as child

            metadata = {
                **base_metadata,
                "parent_id": parent_id,
                "is_chunked": False,
                "chunk_index": 0,
                "token_count": token_count,
            }

            # Child doc (for ChromaDB + BM25)
            child_docs.append(Document(
                page_content=text,
                metadata=metadata,
            ))

            # Parent (same content, stored in LocalFileStore)
            parent_map[parent_id] = {
                "text": text,
                "metadata": metadata,
            }

        else:
            # ---- LONG DOCUMENT: Parent/Child split ----
            stats["long"] += 1

            # Create parent chunks
            parent_texts = parent_splitter.split_text(text)
            parent_entries = []
            parent_char_ranges = []

            search_start = 0
            for i, pt in enumerate(parent_texts):
                p_id = f"{doc_id}_parent_{i:03d}"
                p_start = text.find(pt[:100], search_start)  # Find approximate position
                if p_start == -1:
                    p_start = search_start
                p_end = p_start + len(pt)
                search_start = max(search_start, p_start + len(pt) // 2)  # Move forward

                p_metadata = {
                    **base_metadata,
                    "parent_id": p_id,
                    "is_chunked": True,
                    "parent_index": i,
                    "token_count": count_tokens(pt),
                }

                parent_map[p_id] = {
                    "text": pt,
                    "metadata": p_metadata,
                }

                parent_entries.append((p_id, p_start, p_end))
                parent_char_ranges.append((p_start, p_end, p_id))

            # Create child chunks
            child_texts = child_splitter.split_text(text)

            child_search_start = 0
            for j, ct in enumerate(child_texts):
                c_id = f"{doc_id}_child_{j:04d}"

                # Find this child's position in the original text
                c_start = text.find(ct[:80], child_search_start)
                if c_start == -1:
                    c_start = child_search_start
                child_search_start = max(child_search_start, c_start + len(ct) // 2)

                # Determine which parent this child belongs to
                assigned_parent_id = parent_entries[-1][0]  # Default to last parent
                for p_id, p_start, p_end in parent_entries:
                    if p_start <= c_start < p_end:
                        assigned_parent_id = p_id
                        break

                c_metadata = {
                    **base_metadata,
                    "parent_id": assigned_parent_id,
                    "is_chunked": True,
                    "chunk_index": j,
                    "token_count": count_tokens(ct),
                }

                child_docs.append(Document(
                    page_content=ct,
                    metadata=c_metadata,
                ))

    logger.info(
        f"Chunking complete. Short docs: {stats['short']}, Long docs: {stats['long']}, "
        f"Empty/skipped: {stats['empty']}"
    )
    logger.info(f"Total child chunks: {len(child_docs)}, Total parent entries: {len(parent_map)}")

    return child_docs, parent_map


# ============================================================
# Step 3: Build Stores
# ============================================================

def build_chroma_store(
    child_docs: List[Document],
    persist_dir: str = CHROMA_DB_DIR,
) -> Chroma:
    """Embed child chunks and store in ChromaDB."""
    logger.info(f"Building ChromaDB at {persist_dir} with {len(child_docs)} child chunks...")

    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)

    # Process in batches
    vectorstore = None
    total_batches = (len(child_docs) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in tqdm(range(total_batches), desc="Embedding batches"):
        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(child_docs))
        batch = child_docs[start:end]

        # Generate unique IDs for each chunk
        ids = []
        for doc in batch:
            if doc.metadata.get("is_chunked"):
                ids.append(f"{doc.metadata['doc_id']}_child_{doc.metadata['chunk_index']:04d}")
            else:
                ids.append(f"{doc.metadata['doc_id']}_full")

        if vectorstore is None:
            vectorstore = Chroma.from_documents(
                documents=batch,
                embedding=embeddings,
                collection_name=CHROMA_COLLECTION_NAME,
                persist_directory=persist_dir,
                ids=ids,
            )
        else:
            vectorstore.add_documents(batch, ids=ids)

        # Small delay to avoid hitting API rate limits
        if batch_idx % 10 == 0 and batch_idx > 0:
            time.sleep(1)

    logger.info(f"ChromaDB built successfully. Collection: {CHROMA_COLLECTION_NAME}")
    return vectorstore


def build_parent_store(
    parent_map: Dict[str, Dict],
    store_dir: str = PARENT_STORE_DIR,
) -> LocalFileStore:
    """Store parent chunks in LocalFileStore."""
    logger.info(f"Building LocalFileStore at {store_dir} with {len(parent_map)} parent chunks...")

    os.makedirs(store_dir, exist_ok=True)
    store = LocalFileStore(root_path=store_dir)

    # Store in batches
    batch = []
    for parent_id, parent_data in tqdm(parent_map.items(), desc="Storing parents"):
        encoded = json.dumps(parent_data, ensure_ascii=False).encode("utf-8")
        batch.append((parent_id, encoded))

        if len(batch) >= BATCH_SIZE:
            store.mset(batch)
            batch = []

    # Store remaining
    if batch:
        store.mset(batch)

    logger.info("LocalFileStore built successfully.")
    return store


def build_bm25_index(
    child_docs: List[Document],
    index_path: str = BM25_INDEX_PATH,
) -> BM25Retriever:
    """Build and persist BM25 index from child chunks."""
    logger.info(f"Building BM25 index from {len(child_docs)} child chunks...")

    bm25_retriever = BM25Retriever.from_documents(child_docs)
    bm25_retriever.k = 30  # Retrieve more than needed; filter + fuse later

    # Persist
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "wb") as f:
        pickle.dump(bm25_retriever, f)

    logger.info(f"BM25 index saved to {index_path}")
    return bm25_retriever


# ============================================================
# Step 4: Summary Statistics
# ============================================================

def print_ingest_summary(
    child_docs: List[Document],
    parent_map: Dict[str, Dict],
):
    """Print summary statistics after ingest."""
    print("\n" + "=" * 60)
    print("INGEST PIPELINE — SUMMARY")
    print("=" * 60)

    # Document counts
    short_docs = sum(1 for d in child_docs if not d.metadata.get("is_chunked"))
    long_doc_children = sum(1 for d in child_docs if d.metadata.get("is_chunked"))
    total_child = len(child_docs)
    total_parent = len(parent_map)

    print(f"Total child chunks (ChromaDB + BM25):  {total_child:,}")
    print(f"  - From short docs (unsplit):          {short_docs:,}")
    print(f"  - From long docs (split):             {long_doc_children:,}")
    print(f"Total parent entries (LocalFileStore):  {total_parent:,}")

    # Token distribution
    token_counts = [d.metadata.get("token_count", 0) for d in child_docs]
    if token_counts:
        print(f"\nChild chunk token stats:")
        print(f"  Min: {min(token_counts):,}, Max: {max(token_counts):,}, "
              f"Mean: {sum(token_counts)/len(token_counts):.0f}")

    # Case coverage
    case_ids = set(d.metadata.get("case_id") for d in child_docs)
    print(f"\nUnique cases covered: {len(case_ids)}")

    # Doc type distribution
    doc_types = {}
    for d in child_docs:
        dt = d.metadata.get("doc_type", "unknown")
        doc_types[dt] = doc_types.get(dt, 0) + 1
    print(f"\nDoc type distribution (child chunks):")
    for dt, count in sorted(doc_types.items(), key=lambda x: -x[1]):
        print(f"  {dt:40s}: {count:,}")

    # Authoring entity distribution
    entities = {}
    for d in child_docs:
        ent = d.metadata.get("authoring_entity", "unknown")
        entities[ent] = entities.get(ent, 0) + 1
    print(f"\nAuthoring entity distribution (child chunks):")
    for ent, count in sorted(entities.items(), key=lambda x: -x[1]):
        print(f"  {ent:20s}: {count:,}")

    # Storage estimates
    chroma_path = Path(CHROMA_DB_DIR)
    if chroma_path.exists():
        chroma_size = sum(f.stat().st_size for f in chroma_path.rglob("*") if f.is_file())
        print(f"\nChromaDB size on disk: {chroma_size / 1024 / 1024:.1f} MB")

    bm25_path = Path(BM25_INDEX_PATH)
    if bm25_path.exists():
        print(f"BM25 index size: {bm25_path.stat().st_size / 1024 / 1024:.1f} MB")

    print("=" * 60)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="WTO RAG Ingest Pipeline")
    parser.add_argument("--label-only", action="store_true",
                        help="Only run authoring entity labeling, skip embedding")
    parser.add_argument("--skip-label", action="store_true",
                        help="Skip labeling, assume wto_documents_labeled.jsonl already exists")
    parser.add_argument("--test", type=int, default=0,
                        help="Test mode: process only N documents")
    parser.add_argument("--dry-run", action="store_true",
                        help="Dry run: only chunk and print stats, do NOT embed or write stores")
    args = parser.parse_args()

    # ---- Step 0: Authoring entity labeling ----
    if not args.skip_label:
        if not os.path.exists(JSONL_PATH):
            logger.error(f"Input JSONL not found: {JSONL_PATH}")
            return
        label_authoring_entities(JSONL_PATH, LABELED_JSONL_PATH, max_records=args.test)
        if args.label_only:
            logger.info("Label-only mode. Done.")
            return
    else:
        if not os.path.exists(LABELED_JSONL_PATH):
            logger.error(f"Labeled JSONL not found: {LABELED_JSONL_PATH}")
            logger.info("Run without --skip-label first.")
            return

    # ---- Step 1: Load labeled documents ----
    logger.info(f"Loading labeled documents from {LABELED_JSONL_PATH}")
    records = []
    with open(LABELED_JSONL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    logger.info(f"Loaded {len(records)} documents")

    if args.test > 0:
        records = records[:args.test]
        logger.info(f"Test mode: processing {args.test} documents")

    # ---- Step 2: Chunk documents ----
    child_docs, parent_map = create_chunks(records)

    if not child_docs:
        logger.error("No child chunks created. Check your JSONL data.")
        return

    # ---- Dry run: print stats and sample, then exit ----
    if args.dry_run:
        print_ingest_summary(child_docs, parent_map)

        # Show sample chunks for inspection
        print("\n--- SAMPLE CHILD CHUNKS (first 3) ---")
        for i, doc in enumerate(child_docs[:3]):
            print(f"\n[Child {i}] metadata: {json.dumps({k: str(v)[:60] for k, v in doc.metadata.items()}, indent=2)}")
            print(f"  text preview: {doc.page_content[:200]}...")

        print("\n--- SAMPLE PARENT ENTRIES (first 3) ---")
        for i, (pid, pdata) in enumerate(list(parent_map.items())[:3]):
            print(f"\n[Parent] id={pid}")
            print(f"  text preview: {pdata['text'][:200]}...")

        logger.info("Dry run complete. No stores written.")
        return

    # ---- Step 3: Build stores ----
    # Ensure directories exist
    os.makedirs(CHROMA_DB_DIR, exist_ok=True)
    os.makedirs(PARENT_STORE_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(BM25_INDEX_PATH), exist_ok=True)

    # ChromaDB
    vectorstore = build_chroma_store(child_docs)

    # LocalFileStore
    parent_store = build_parent_store(parent_map)

    # BM25
    bm25_retriever = build_bm25_index(child_docs)

    # ---- Step 4: Print summary ----
    print_ingest_summary(child_docs, parent_map)

    logger.info("Ingest pipeline complete. Stores are ready for retrieval.")


if __name__ == "__main__":
    main()
