"""
WTO RAG System — Ingest Pipeline
=================================
Reads preprocessed JSONL, adds authoring entity labels, creates chunks,
embeds into ChromaDB, stores parents in LocalFileStore, builds BM25 index.

Run ONCE. After completion, stores are read-only during retrieval.

Usage:
    python scripts/ingest.py
    python scripts/ingest.py --label-only   # Only run authoring entity labeling, skip embedding
    python scripts/ingest.py --skip-label   # Skip labeling, assume already done
    python scripts/ingest.py --dry-run      # Chunk + stats, no embedding

Prerequisites:
    pip install langchain-openai langchain-community langchain-classic chromadb rank-bm25 pandas tqdm pydantic tiktoken
    export OPENAI_API_KEY="..."
"""

import os
import re
import ast
import json
import pickle
import logging
import argparse
import time
from pathlib import Path
from typing import List, Dict, Optional, Literal, Tuple
from dataclasses import dataclass

import tiktoken
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
# Configuration
# ============================================================

JSONL_PATH = "./Data/WTO/wto_documents_full.jsonl"
CHROMA_DB_DIR = "./Data/stores/chroma_db"
PARENT_STORE_DIR = "./Data/stores/parent_store"
BM25_INDEX_PATH = "./Data/stores/bm25_index.pkl"
LABELED_JSONL_PATH = "./Data/WTO/wto_documents_labeled.jsonl"

EMBEDDING_MODEL = "text-embedding-3-small"
LABELING_MODEL = "gpt-5-mini"

SHORT_DOC_TOKEN_THRESHOLD = 6000
CHILD_CHUNK_SIZE = 1200
CHILD_CHUNK_OVERLAP = 200
PARENT_CHUNK_SIZE = 6000
PARENT_CHUNK_OVERLAP = 800

CHROMA_COLLECTION_NAME = "wto_child_chunks"
BATCH_SIZE = 500

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# Step 0: Authoring Entity Labeling
# ============================================================

# ---------- Helpers ----------

def _parse_party_list(val) -> List[str]:
    """Parse '["Country1", "Country2"]' string into list."""
    if not val or val == '[]':
        return []
    try:
        parsed = ast.literal_eval(val)
        return [str(x) for x in parsed] if isinstance(parsed, list) else [str(parsed)]
    except Exception:
        return [str(val)]


# Common WTO country name aliases (normalized form → canonical)
_ALIASES = {
    'u.s.': 'united states', 'us': 'united states', 'usa': 'united states',
    'ec': 'european communities', 'eu': 'european union',
    'uk': 'united kingdom',
    'korea': 'korea, republic of', 'south korea': 'korea, republic of',
    'dominican': 'dominican republic',
    'chinese taipei': 'separate customs territory of taiwan',
    'hong kong': 'hong kong, china',
    'viet nam': 'vietnam',
}


def _normalize(name: str) -> str:
    """Normalize a country/entity name for matching."""
    n = name.strip().lower()
    n = re.sub(r'^the\s+', '', n)
    n = re.sub(r'[,;:!*]+$', '', n)  # Don't strip periods (part of abbreviations like U.S.)
    n = n.strip()
    return n


def _resolve_alias(name: str) -> str:
    """Resolve a normalized name through aliases, trying multiple forms."""
    # Try exact match first
    if name in _ALIASES:
        return _ALIASES[name]
    # Try without trailing period (U.S. → u.s → u.s.)
    stripped = name.rstrip('.')
    if stripped in _ALIASES:
        return _ALIASES[stripped]
    # Try with trailing period
    dotted = name + '.'
    if dotted in _ALIASES:
        return _ALIASES[dotted]
    return name


def _name_matches(extracted: str, known: str) -> bool:
    """Check if an extracted name matches a known party name."""
    ext = _normalize(extracted)
    kn = _normalize(known)
    if not ext or not kn:
        return False

    # Direct match
    if ext == kn:
        return True

    # Alias resolution
    ext_a = _resolve_alias(ext)
    kn_a = _resolve_alias(kn)
    if ext_a == kn_a:
        return True

    # Containment (both directions, min length 3 to avoid false matches)
    if len(ext_a) >= 3 and len(kn_a) >= 3:
        if ext_a in kn_a or kn_a in ext_a:
            return True
    return False


def _match_party(
    entity_name: str,
    complainants: List[str],
    respondents: List[str],
    third_parties: List[str],
) -> Tuple[str, str]:
    """Match an extracted entity name against known case parties.

    Returns (entity_type, matched_name).
    """
    # Check institutional entities first
    lower = _normalize(entity_name)
    if any(kw in lower for kw in ['chairman of the panel', 'chairperson of the panel', 'panel']):
        return 'panel', 'Panel'
    if 'appellate body' in lower or 'appellate division' in lower:
        return 'appellate_body', 'Appellate Body'
    if any(kw in lower for kw in ['arbitrator', 'arbitrators']):
        return 'arbitrator', 'Arbitrator'
    if any(kw in lower for kw in ['secretariat', 'director-general', 'director general',
                                   'chairman of the dsb', 'chairperson of the dsb',
                                   'chairman of the dispute settlement body',
                                   'chairperson of the dispute settlement body']):
        return 'secretariat', 'Secretariat'

    # Check against case parties
    for c in complainants:
        if _name_matches(entity_name, c):
            return 'complainant', c
    for r in respondents:
        if _name_matches(entity_name, r):
            return 'respondent', r
    for tp in third_parties:
        if _name_matches(entity_name, tp):
            return 'third_party', tp

    # Unresolved country name — likely a third party not in the metadata
    # (can happen when the third_parties field is incomplete)
    cleaned = re.sub(r'^the\s+', '', entity_name.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r'[.,;:]+$', '', cleaned).strip()
    if cleaned and len(cleaned) > 2:
        return 'third_party', cleaned

    return 'unknown', entity_name


# ---------- Entity extraction from text ----------

# Regex: capture entity name after "by" or "from", stop at common WTO delimiters
_ENTITY_BOUNDARY = (
    r'(?=\s*(?:'
    r'Addendum|Corrigendum|Revision|Supplement|Annex|'
    r'under\s+(?:Article|paragraph|the\s+Understanding|the\s+DSU)|'
    r'pursuant|The\s+following|This\s+communication|'
    r'Thefollowing|$|\n|\r'
    r'))'
)

_BY_FROM_RE = re.compile(
    r'\b(?:Communication\s+)?(?:by|from)\s+'
    r'((?:the\s+)?(?:Permanent\s+Mission\s+of\s+)?'
    r'.+?)'
    + _ENTITY_BOUNDARY,
    re.IGNORECASE | re.DOTALL
)

# Specific pattern: "from the Permanent Mission of [Country] to the"
_PERM_MISSION_RE = re.compile(
    r'from\s+the\s+Permanent\s+Mission\s+of\s+(.+?)\s+to\s+the',
    re.IGNORECASE
)

# "Submissions of [Country]" pattern for Submission type
_SUBMISSIONS_OF_RE = re.compile(
    r'submissions?\s+of\s+((?:the\s+)?.+?)(?:\s+Contents|\s+Page|\n|$)',
    re.IGNORECASE
)


def _extract_entity_from_text(text: str, max_chars: int = 500) -> Optional[str]:
    """Extract authoring entity name from document text.

    Looks for 'by [Entity]' or 'from [Entity]' in the first max_chars.
    Returns the extracted entity name, or None.
    """
    if not text:
        return None
    snippet = text[:max_chars]

    # Try Permanent Mission pattern first (most specific)
    m = _PERM_MISSION_RE.search(snippet)
    if m:
        name = m.group(1).strip()
        name = re.sub(r'[.,;:]+$', '', name).strip()
        if len(name) > 2:
            return name

    # Try general by/from pattern
    m = _BY_FROM_RE.search(snippet)
    if m:
        name = m.group(1).strip()
        # Strip "the Permanent Mission of" prefix if present
        name = re.sub(r'^the\s+Permanent\s+Mission\s+of\s+', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[.,;:]+$', '', name).strip()
        if len(name) > 2:
            return name

    return None


# ---------- Rule-based entity classification ----------

# doc_type → (entity_type, entity_name_or_None)
# None means entity_type is known but name must come from case metadata
# Full None value means doc_type alone is ambiguous → need text analysis
DOC_TYPE_ENTITY_RULES = {
    # Complainant
    'Request_For_Consultations': ('complainant', None),
    'Request_For_Establishment_Of_Panel': ('complainant', None),
    'Request_Regarding_Consultations': ('complainant', None),
    'Request_To_Reactivate_Consultations': ('complainant', None),

    # Third party (name from text)
    'Request_To_Join_Consultations': ('third_party', None),

    # Panel
    'Report_Of_Panel': ('panel', 'Panel'),
    'Working_Procedures': ('panel', 'Panel'),
    'Questions_And_Replies': ('panel', 'Panel'),
    'Interim_Review': ('panel', 'Panel'),
    'Terms_Of_Reference': ('panel', 'Panel'),

    # Appellate Body
    'Report_Of_Appellate_Body': ('appellate_body', 'Appellate Body'),
    'Appellate_Body_Report_And_Panel_Report': ('appellate_body', 'Appellate Body'),

    # Arbitrator
    'Arbitration_Award': ('arbitrator', 'Arbitrator'),
    'Appointment_Of_Arbitrator': ('secretariat', 'Secretariat'),

    # Secretariat
    'Note_By_Secretariat': ('secretariat', 'Secretariat'),
    'Cancelled_Document': ('secretariat', 'Secretariat'),
    'DSB_Action': ('secretariat', 'Secretariat'),
    'Panel_Composition': ('secretariat', 'Secretariat'),
    'Extension_Of_Time_Period': ('secretariat', 'Secretariat'),

    # Joint / agreed
    'Notification_Of_Mutually_Agreed_Solution': ('joint', None),
    'Understanding': ('joint', None),
    'Agreed_Procedures': ('joint', None),
    'Agreement_Art_21_3': ('joint', None),
    'Notification_Of_Agreement': ('joint', None),

    # Secretariat corrections
    'Corrigendum': ('secretariat', 'Secretariat'),
    'Modification': ('secretariat', 'Secretariat'),

    # Need text analysis (set to None)
    'Communication': None,
    'Status_Report': None,
    'Notification_Of_Appeal': None,
    'Recourse': None,
    'Addendum': None,
    'Request_For_Decision': None,
    'Submission': None,
    'Executive_Summary': None,
    'Request_For_Arbitration': None,
    'Arbitration': None,
    'Surveillance_Of_Implementation': None,
    'Implementation_Report': None,
    'Report_By_Director_General': ('secretariat', 'Secretariat'),
    'Statement': None,
    'Transcript': ('panel', 'Panel'),
}


class AuthoringEntity(BaseModel):
    """Structured output for LLM-based entity classification."""
    entity_type: Literal[
        "complainant", "respondent", "third_party",
        "panel", "appellate_body", "arbitrator",
        "secretariat", "joint", "unknown"
    ] = Field(description="The type of entity that authored this document.")
    entity_name: str = Field(
        description="The specific name of the authoring entity. "
        "For countries, use the country name. "
        "For panel/AB/secretariat, use 'Panel', 'Appellate Body', 'Secretariat'."
    )


def label_authoring_entities(
    input_path: str = JSONL_PATH,
    output_path: str = LABELED_JSONL_PATH,
    max_records: int = 0,
):
    """Add authoring_entity and authoring_entity_name fields to each document.

    Pipeline:
      1. Rule-based from doc_type (covers ~45% of docs unambiguously)
      2. Extract entity from doc_type_raw using by/from patterns
      3. Extract entity from first 500 chars of clean_text
      4. Match extracted name against complainant/respondent/third_parties
      5. LLM fallback for truly ambiguous cases
    """
    logger.info(f"Labeling authoring entities from {input_path}")

    records = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if max_records > 0:
        records = records[:max_records]
        logger.info(f"Test mode: labeling only {max_records} documents")

    logger.info(f"Loaded {len(records)} documents (after dedup)")

    # LLM setup (lazy — only initialized if needed)
    llm = None
    labeling_prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "Classify who authored this WTO dispute document.\n"
            "Options: complainant, respondent, third_party, panel, "
            "appellate_body, arbitrator, secretariat, joint, unknown.\n"
            "Return the entity_type and the specific entity_name."
        )),
        ("human", (
            "Case: DS{case_id} — {case_title}\n"
            "Complainant: {complainant}\n"
            "Respondent: {respondent}\n"
            "Third parties: {third_parties}\n"
            "Document type: {doc_type} (raw: {doc_type_raw})\n"
            "Header codes: {header_codes}\n"
            "First 500 chars of text:\n{text_preview}\n\n"
            "Who authored this document?"
        )),
    ])

    stats = {'rule': 0, 'raw_extract': 0, 'text_extract': 0, 'llm': 0, 'unknown': 0}

    with open(output_path, "w", encoding="utf-8") as out_f:
        for rec in tqdm(records, desc="Labeling"):
            doc_type = rec.get("doc_type", "")
            doc_type_raw = rec.get("doc_type_raw", "")
            clean_text = rec.get("clean_text", "")
            complainants = _parse_party_list(rec.get("complainant", "[]"))
            respondents = _parse_party_list(rec.get("respondent", "[]"))
            third_parties = _parse_party_list(rec.get("third_parties", "[]"))

            entity_type = None
            entity_name = None
            confidence = "low"

            # ---- Step 1: Rule-based from doc_type ----
            rule = DOC_TYPE_ENTITY_RULES.get(doc_type)
            if rule is not None:
                entity_type, entity_name = rule

                # Resolve placeholder names
                if entity_type == 'complainant' and entity_name is None:
                    entity_name = ', '.join(complainants) if complainants else 'Complainant'
                elif entity_type == 'respondent' and entity_name is None:
                    entity_name = ', '.join(respondents) if respondents else 'Respondent'
                elif entity_type == 'joint' and entity_name is None:
                    entity_name = f"{', '.join(complainants)} & {', '.join(respondents)}"
                elif entity_type == 'third_party' and entity_name is None:
                    # For Request_To_Join_Consultations: extract name from text
                    extracted = _extract_entity_from_text(doc_type_raw) or _extract_entity_from_text(clean_text)
                    if extracted:
                        _, matched = _match_party(extracted, complainants, respondents, third_parties)
                        entity_name = matched
                    else:
                        entity_name = 'Third Party'

                confidence = "high"
                stats['rule'] += 1

            # ---- Step 2: Extract from doc_type_raw ----
            if entity_type is None:
                extracted = _extract_entity_from_text(doc_type_raw)
                if extracted:
                    entity_type, entity_name = _match_party(
                        extracted, complainants, respondents, third_parties
                    )
                    confidence = "high" if entity_type != 'unknown' else "medium"
                    stats['raw_extract'] += 1

            # ---- Step 3: Extract from first 500 chars of clean_text ----
            if entity_type is None:
                extracted = _extract_entity_from_text(clean_text, max_chars=500)
                if extracted:
                    entity_type, entity_name = _match_party(
                        extracted, complainants, respondents, third_parties
                    )
                    confidence = "medium"
                    stats['text_extract'] += 1

            # ---- Step 4: Addendum/Submission/Executive_Summary heuristic ----
            if entity_type is None and doc_type in ('Addendum', 'Executive_Summary', 'Submission'):
                # Try "Submissions of [Country]" pattern for Executive_Summary
                m = _SUBMISSIONS_OF_RE.search(doc_type_raw) or _SUBMISSIONS_OF_RE.search(clean_text[:500])
                if m:
                    extracted_name = m.group(1).strip()
                    extracted_name = re.sub(r'[.,;:]+$', '', extracted_name)
                    if 'third part' in extracted_name.lower():
                        entity_type, entity_name = 'third_party', 'Third Parties'
                    else:
                        entity_type, entity_name = _match_party(
                            extracted_name, complainants, respondents, third_parties
                        )
                    confidence = "medium"
                    stats['text_extract'] += 1

            # ---- Step 5: LLM fallback ----
            if entity_type is None:
                try:
                    if llm is None:
                        llm = ChatOpenAI(model=LABELING_MODEL, temperature=0)
                        llm = llm.with_structured_output(AuthoringEntity)

                    text_preview = clean_text[:500] if clean_text else "(no text)"
                    result = llm.invoke(
                        labeling_prompt.format_messages(
                            case_id=rec.get("case_number", ""),
                            case_title=rec.get("case_title", ""),
                            complainant=', '.join(complainants),
                            respondent=', '.join(respondents),
                            third_parties=', '.join(third_parties),
                            doc_type=doc_type,
                            doc_type_raw=doc_type_raw[:200],
                            header_codes=rec.get("header_codes", ""),
                            text_preview=text_preview,
                        )
                    )
                    entity_type = result.entity_type
                    entity_name = result.entity_name
                    confidence = "medium"
                    stats['llm'] += 1

                    if stats['llm'] % 50 == 0:
                        time.sleep(1)

                except Exception as e:
                    logger.warning(f"LLM failed for {rec.get('new_filename', '')}: {e}")
                    entity_type = "unknown"
                    entity_name = "Unknown"
                    confidence = "low"
                    stats['unknown'] += 1

            rec["authoring_entity"] = entity_type
            rec["authoring_entity_name"] = entity_name
            rec["authoring_entity_confidence"] = confidence

            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    logger.info(
        f"Labeling complete. Rule: {stats['rule']}, Raw extract: {stats['raw_extract']}, "
        f"Text extract: {stats['text_extract']}, LLM: {stats['llm']}, Unknown: {stats['unknown']}"
    )
    logger.info(f"Saved labeled JSONL to {output_path}")


# ============================================================
# Step 1: Token Counting
# ============================================================

_ENCODING = None

def count_tokens(text: str) -> int:
    """Count tokens using tiktoken (cl100k_base for OpenAI models)."""
    global _ENCODING
    if _ENCODING is None:
        _ENCODING = tiktoken.get_encoding("cl100k_base")
    try:
        return len(_ENCODING.encode(text))
    except Exception:
        return int(len(text.split()) * 1.3)


# ============================================================
# Step 2: Chunking
# ============================================================

def create_chunks(
    records: List[Dict],
) -> tuple[List[Document], Dict[str, Dict]]:
    """Process documents into child chunks + parent chunks.

    Short docs (≤ SHORT_DOC_TOKEN_THRESHOLD tokens): stored as-is (child = parent).
    Long docs: split into parent chunks, then child chunks within each parent.

    Returns:
        child_docs: List[Document] for ChromaDB + BM25
        parent_map: Dict[parent_id → {"text": str, "metadata": dict}] for LocalFileStore
    """
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHILD_CHUNK_SIZE,
        chunk_overlap=CHILD_CHUNK_OVERLAP,
        length_function=len,
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
        folder = str(rec.get("folder_number", ""))
        doc_seq = str(rec.get("doc_sequence", ""))
        doc_id = f"F{folder}_DS{case_id}_SEQ{doc_seq.zfill(2)}"

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

            metadata = {
                **base_metadata,
                "parent_id": chunk_id,
                "is_chunked": False,
                "chunk_index": 0,
                "token_count": token_count,
            }

            child_docs.append(Document(page_content=text, metadata=metadata))
            parent_map[chunk_id] = {"text": text, "metadata": metadata}

        else:
            # ---- LONG DOCUMENT: Parent/Child split ----
            stats["long"] += 1

            # Create parent chunks
            parent_texts = parent_splitter.split_text(text)
            parent_entries = []

            search_start = 0
            for i, pt in enumerate(parent_texts):
                p_id = f"{doc_id}_parent_{i:03d}"
                p_start = text.find(pt[:100], search_start)
                if p_start == -1:
                    p_start = search_start
                p_end = p_start + len(pt)
                search_start = max(search_start, p_start + len(pt) // 2)

                p_metadata = {
                    **base_metadata,
                    "parent_id": p_id,
                    "is_chunked": True,
                    "parent_index": i,
                    "token_count": count_tokens(pt),
                }

                parent_map[p_id] = {"text": pt, "metadata": p_metadata}
                parent_entries.append((p_id, p_start, p_end))

            # Create child chunks
            child_texts = child_splitter.split_text(text)
            child_search_start = 0

            for j, ct in enumerate(child_texts):
                c_start = text.find(ct[:80], child_search_start)
                if c_start == -1:
                    c_start = child_search_start
                child_search_start = max(child_search_start, c_start + len(ct) // 2)

                # Determine parent
                assigned_parent_id = parent_entries[-1][0]
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

                child_docs.append(Document(page_content=ct, metadata=c_metadata))

    logger.info(
        f"Chunking complete. Short: {stats['short']}, Long: {stats['long']}, "
        f"Empty/skipped: {stats['empty']}"
    )
    logger.info(f"Total child chunks: {len(child_docs)}, Total parents: {len(parent_map)}")
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
    vectorstore = None
    total_batches = (len(child_docs) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in tqdm(range(total_batches), desc="Embedding batches"):
        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(child_docs))
        batch = child_docs[start:end]

        ids = []
        for doc in batch:
            if doc.metadata.get("is_chunked"):
                ids.append(f"{doc.metadata['doc_id']}_child_{doc.metadata['chunk_index']:04d}")
            else:
                ids.append(f"{doc.metadata['doc_id']}_full")

        for attempt in range(5):
            try:
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
                break
            except Exception as e:
                if "429" in str(e) or "rate_limit" in str(e).lower():
                    wait = 10 * (attempt + 1)
                    logger.warning(f"Rate limited (attempt {attempt+1}/5), waiting {wait}s...")
                    time.sleep(wait)
                else:
                    raise

        # ~100k tokens per batch; 1M TPM limit → pause 6s to stay under limit
        time.sleep(6)

    logger.info(f"ChromaDB built. Collection: {CHROMA_COLLECTION_NAME}")
    return vectorstore


def build_parent_store(
    parent_map: Dict[str, Dict],
    store_dir: str = PARENT_STORE_DIR,
) -> LocalFileStore:
    """Store parent chunks in LocalFileStore for retrieval."""
    logger.info(f"Building LocalFileStore at {store_dir} with {len(parent_map)} parent chunks...")

    os.makedirs(store_dir, exist_ok=True)
    store = LocalFileStore(root_path=store_dir)

    batch = []
    for parent_id, parent_data in tqdm(parent_map.items(), desc="Storing parents"):
        encoded = json.dumps(parent_data, ensure_ascii=False).encode("utf-8")
        batch.append((parent_id, encoded))

        if len(batch) >= BATCH_SIZE:
            store.mset(batch)
            batch = []

    if batch:
        store.mset(batch)

    logger.info("LocalFileStore built.")
    return store


def build_bm25_index(
    child_docs: List[Document],
    index_path: str = BM25_INDEX_PATH,
) -> BM25Retriever:
    """Build and persist BM25 index from child chunks."""
    logger.info(f"Building BM25 index from {len(child_docs)} child chunks...")

    bm25_retriever = BM25Retriever.from_documents(child_docs)
    bm25_retriever.k = 30

    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "wb") as f:
        pickle.dump(bm25_retriever, f)

    logger.info(f"BM25 index saved to {index_path}")
    return bm25_retriever


BM25_PER_CASE_PATH = "./Data/stores/bm25_per_case.pkl"


def build_bm25_per_case(
    child_docs: List[Document],
    index_path: str = BM25_PER_CASE_PATH,
) -> Dict[str, BM25Retriever]:
    """Build per-case BM25 indexes: {case_id: BM25Retriever}.

    Each case gets its own BM25 index over only its child chunks,
    so retrieval searches ~100 docs instead of 65k+.
    """
    from collections import defaultdict

    # Group child docs by case_id
    case_docs: Dict[str, List[Document]] = defaultdict(list)
    for doc in child_docs:
        cid = doc.metadata.get("case_id", "")
        if cid:
            case_docs[cid].append(doc)

    logger.info(f"Building per-case BM25 indexes for {len(case_docs)} cases...")

    bm25_dict: Dict[str, BM25Retriever] = {}
    for case_id in tqdm(sorted(case_docs.keys(), key=lambda x: int(x)), desc="BM25 per case"):
        docs = case_docs[case_id]
        retriever = BM25Retriever.from_documents(docs)
        retriever.k = 15
        bm25_dict[case_id] = retriever

    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "wb") as f:
        pickle.dump(bm25_dict, f)

    logger.info(f"Per-case BM25 index saved to {index_path} ({len(bm25_dict)} cases)")
    return bm25_dict


# ============================================================
# Step 4: Summary
# ============================================================

def print_ingest_summary(child_docs: List[Document], parent_map: Dict[str, Dict]):
    """Print summary statistics."""
    print("\n" + "=" * 60)
    print("INGEST PIPELINE — SUMMARY")
    print("=" * 60)

    short_docs = sum(1 for d in child_docs if not d.metadata.get("is_chunked"))
    long_children = sum(1 for d in child_docs if d.metadata.get("is_chunked"))
    print(f"Total child chunks (ChromaDB + BM25):  {len(child_docs):,}")
    print(f"  - From short docs (unsplit):          {short_docs:,}")
    print(f"  - From long docs (split):             {long_children:,}")
    print(f"Total parent entries (LocalFileStore):  {len(parent_map):,}")

    token_counts = [d.metadata.get("token_count", 0) for d in child_docs]
    if token_counts:
        print(f"\nChild chunk token stats:")
        print(f"  Min: {min(token_counts):,}, Max: {max(token_counts):,}, "
              f"Mean: {sum(token_counts)/len(token_counts):.0f}")

    case_ids = set(d.metadata.get("case_id") for d in child_docs)
    print(f"\nUnique cases covered: {len(case_ids)}")

    # Doc type distribution
    doc_types = {}
    for d in child_docs:
        dt = d.metadata.get("doc_type", "unknown")
        doc_types[dt] = doc_types.get(dt, 0) + 1
    print(f"\nDoc type distribution (child chunks):")
    for dt, count in sorted(doc_types.items(), key=lambda x: -x[1])[:20]:
        print(f"  {dt:45s}: {count:,}")
    if len(doc_types) > 20:
        print(f"  ... and {len(doc_types) - 20} more types")

    # Authoring entity distribution
    entities = {}
    for d in child_docs:
        ent = d.metadata.get("authoring_entity", "unknown")
        entities[ent] = entities.get(ent, 0) + 1
    print(f"\nAuthoring entity distribution (child chunks):")
    for ent, count in sorted(entities.items(), key=lambda x: -x[1]):
        print(f"  {ent:20s}: {count:,}")

    # Storage sizes
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
                        help="Chunk and print stats, do NOT embed or write stores")
    parser.add_argument("--bm25-only", action="store_true",
                        help="Rebuild only BM25 per-case index (skip ChromaDB, parent store, labeling)")
    args = parser.parse_args()

    # ---- BM25-only mode: rebuild per-case BM25 from labeled JSONL ----
    if args.bm25_only:
        if not os.path.exists(LABELED_JSONL_PATH):
            logger.error(f"Labeled JSONL not found: {LABELED_JSONL_PATH}")
            return
        logger.info(f"BM25-only mode: loading from {LABELED_JSONL_PATH}")
        records = []
        with open(LABELED_JSONL_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        logger.info(f"Loaded {len(records)} documents")
        child_docs, _ = create_chunks(records)
        build_bm25_per_case(child_docs)
        logger.info("BM25 per-case index built. Done.")
        return

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

    # ---- Dry run ----
    if args.dry_run:
        print_ingest_summary(child_docs, parent_map)

        print("\n--- SAMPLE CHILD CHUNKS (first 3) ---")
        for i, doc in enumerate(child_docs[:3]):
            meta_preview = {k: str(v)[:60] for k, v in doc.metadata.items()}
            print(f"\n[Child {i}] metadata: {json.dumps(meta_preview, indent=2)}")
            print(f"  text preview: {doc.page_content[:200]}...")

        print("\n--- SAMPLE PARENT ENTRIES (first 3) ---")
        for i, (pid, pdata) in enumerate(list(parent_map.items())[:3]):
            print(f"\n[Parent] id={pid}")
            print(f"  text preview: {pdata['text'][:200]}...")

        logger.info("Dry run complete. No stores written.")
        return

    # ---- Step 3: Build stores ----
    os.makedirs(CHROMA_DB_DIR, exist_ok=True)
    os.makedirs(PARENT_STORE_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(BM25_INDEX_PATH), exist_ok=True)

    build_chroma_store(child_docs)
    build_parent_store(parent_map)
    build_bm25_index(child_docs)
    build_bm25_per_case(child_docs)

    # ---- Step 4: Print summary ----
    print_ingest_summary(child_docs, parent_map)

    logger.info("Ingest pipeline complete. Stores are ready for retrieval.")


if __name__ == "__main__":
    main()
