"""Hybrid retrieval pipeline for WTO dispute documents.

Exposes a single function `retrieve()` that both tasks call.
Internally: routing → multi-query → hybrid search → RRF → rerank → parent lookup.

Stores are loaded lazily on first call and kept in module-level singletons.
"""

import json
import logging
import pickle
import time
from typing import Dict, List, Literal, Optional

import cohere
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_classic.storage import LocalFileStore
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from rag.config import (
    BM25_INDEX_PATH,
    CHROMA_COLLECTION_NAME,
    CHROMA_DB_DIR,
    COHERE_API_KEY,
    COHERE_SLEEP_SECONDS,
    EMBEDDING_MODEL,
    EXTRACTION_MODEL,
    INDUSTRY_BM25_WEIGHT,
    INDUSTRY_DOC_TYPE_FILTER,
    INDUSTRY_PRE_RERANK_K,
    INDUSTRY_SEMANTIC_WEIGHT,
    INDUSTRY_USE_HYDE,
    INDUSTRY_USE_MULTI_QUERY,
    NUM_QUERY_VARIANTS,
    PARENT_STORE_DIR,
    RERANK_MODEL,
    RRF_K,
    SEVERITY_AUTHORING_ENTITY_FILTER,
    SEVERITY_BM25_WEIGHT,
    SEVERITY_PRE_RERANK_K,
    SEVERITY_SEMANTIC_WEIGHT,
    SEVERITY_USE_HYDE,
    SEVERITY_USE_MULTI_QUERY,
    TOP_K_FINAL,
)
from rag.schemas import QueryVariants

logger = logging.getLogger(__name__)

# ── Module-level singletons (lazy-loaded) ─────────────────────

_vectorstore: Optional[Chroma] = None
_bm25_retriever = None
_parent_store: Optional[LocalFileStore] = None
_cohere_client: Optional[cohere.Client] = None
_query_llm = None


def _get_vectorstore() -> Chroma:
    global _vectorstore
    if _vectorstore is None:
        logger.info("Loading ChromaDB from %s ...", CHROMA_DB_DIR)
        embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
        _vectorstore = Chroma(
            collection_name=CHROMA_COLLECTION_NAME,
            persist_directory=CHROMA_DB_DIR,
            embedding_function=embeddings,
        )
        logger.info("ChromaDB loaded.")
    return _vectorstore


def _get_bm25():
    global _bm25_retriever
    if _bm25_retriever is None:
        logger.info("Loading BM25 index from %s ...", BM25_INDEX_PATH)
        with open(BM25_INDEX_PATH, "rb") as f:
            _bm25_retriever = pickle.load(f)
        logger.info("BM25 index loaded.")
    return _bm25_retriever


def _get_parent_store() -> LocalFileStore:
    global _parent_store
    if _parent_store is None:
        logger.info("Loading LocalFileStore from %s ...", PARENT_STORE_DIR)
        _parent_store = LocalFileStore(root_path=PARENT_STORE_DIR)
        logger.info("LocalFileStore loaded.")
    return _parent_store


def _get_cohere() -> cohere.Client:
    global _cohere_client
    if _cohere_client is None:
        _cohere_client = cohere.Client(api_key=COHERE_API_KEY)
    return _cohere_client


def _get_query_llm():
    global _query_llm
    if _query_llm is None:
        _query_llm = ChatOpenAI(model=EXTRACTION_MODEL, temperature=0.7)
    return _query_llm


# ── Stage 1: Task-Based Routing ───────────────────────────────

def _get_routing_params(task: str) -> Dict:
    """Return task-specific retrieval parameters."""
    if task == "industry_extraction":
        return {
            "doc_type_filter": INDUSTRY_DOC_TYPE_FILTER,
            "authoring_entity_filter": None,
            "bm25_weight": INDUSTRY_BM25_WEIGHT,
            "semantic_weight": INDUSTRY_SEMANTIC_WEIGHT,
            "use_hyde": INDUSTRY_USE_HYDE,
            "use_multi_query": INDUSTRY_USE_MULTI_QUERY,
            "pre_rerank_k": INDUSTRY_PRE_RERANK_K,
        }
    elif task == "severity_scoring":
        return {
            "doc_type_filter": None,
            "authoring_entity_filter": SEVERITY_AUTHORING_ENTITY_FILTER,
            "bm25_weight": SEVERITY_BM25_WEIGHT,
            "semantic_weight": SEVERITY_SEMANTIC_WEIGHT,
            "use_hyde": SEVERITY_USE_HYDE,
            "use_multi_query": SEVERITY_USE_MULTI_QUERY,
            "pre_rerank_k": SEVERITY_PRE_RERANK_K,
        }
    else:
        raise ValueError(f"Unknown task: {task!r}")


# ── Stage 2: Query Translation ────────────────────────────────

_MULTI_QUERY_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are an expert in WTO trade disputes. Given the following search query, "
     "generate 3 different versions of this query that would help find relevant "
     "information in WTO dispute documents. Each version should approach the "
     "information need from a different angle."),
    ("human",
     "Original query: {query}\n\n"
     "Return exactly 3 alternative queries."),
])

_HYDE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are an expert in WTO trade disputes. Write a short paragraph (100-150 words) "
     "that would appear in a WTO consultation request with strong political framing. "
     "The paragraph should describe a trade dispute involving the following query context. "
     "Write as if you are the complainant country drafting the consultation request. "
     "Use formal WTO legal language."),
    ("human", "{query}"),
])


def _generate_query_variants(query: str) -> List[str]:
    """Generate multi-query variants + optional HyDE paragraph."""
    llm = _get_query_llm()
    structured = llm.with_structured_output(QueryVariants)
    try:
        result = structured.invoke(
            _MULTI_QUERY_PROMPT.format_messages(query=query)
        )
        variants = result.queries[:NUM_QUERY_VARIANTS]
    except Exception as e:
        logger.warning("Multi-query generation failed: %s — using original only", e)
        variants = []
    return variants


def _generate_hyde(query: str) -> Optional[str]:
    """Generate a hypothetical document for HyDE retrieval."""
    llm = _get_query_llm()
    try:
        result = llm.invoke(_HYDE_PROMPT.format_messages(query=query))
        return result.content.strip()
    except Exception as e:
        logger.warning("HyDE generation failed: %s", e)
        return None


# ── Stage 3: Hybrid Search ────────────────────────────────────

def _build_chroma_filter(
    case_id: str,
    doc_type_filter: Optional[List[str]],
    authoring_entity_filter: Optional[List[str]],
) -> Dict:
    """Build a ChromaDB $and filter dict."""
    conditions = [{"case_id": case_id}]
    if doc_type_filter:
        conditions.append({"doc_type": {"$in": doc_type_filter}})
    if authoring_entity_filter:
        conditions.append({"authoring_entity": {"$in": authoring_entity_filter}})

    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _semantic_search(
    query: str,
    chroma_filter: Dict,
    k: int,
) -> List[Document]:
    """Run similarity search on ChromaDB with metadata filter."""
    vs = _get_vectorstore()
    try:
        return vs.similarity_search(query, k=k, filter=chroma_filter)
    except Exception as e:
        logger.warning("Semantic search failed: %s", e)
        return []


def _bm25_search(
    query: str,
    case_id: str,
    doc_type_filter: Optional[List[str]],
    authoring_entity_filter: Optional[List[str]],
    k: int,
) -> List[Document]:
    """Run BM25 search and post-filter by metadata."""
    bm25 = _get_bm25()
    try:
        raw_results = bm25.invoke(query)
    except Exception as e:
        logger.warning("BM25 search failed: %s", e)
        return []

    filtered = []
    for doc in raw_results:
        meta = doc.metadata
        if meta.get("case_id") != case_id:
            continue
        if doc_type_filter and meta.get("doc_type") not in doc_type_filter:
            continue
        if authoring_entity_filter and meta.get("authoring_entity") not in authoring_entity_filter:
            continue
        filtered.append(doc)
        if len(filtered) >= k:
            break
    return filtered


# ── Stage 4: RRF Fusion ──────────────────────────────────────

def _reciprocal_rank_fusion(
    result_lists: List[List[Document]],
    weights: List[float],
    k: int = RRF_K,
) -> List[Document]:
    """Fuse multiple ranked lists using weighted Reciprocal Rank Fusion.

    RRF_score(doc) = Σ weight_i / (k + rank_i)
    """
    fused_scores: Dict[str, float] = {}
    doc_map: Dict[str, Document] = {}

    for list_idx, docs in enumerate(result_lists):
        w = weights[list_idx]
        for rank, doc in enumerate(docs):
            doc_key = doc.metadata.get("parent_id", str(id(doc)))
            if doc_key not in fused_scores:
                fused_scores[doc_key] = 0.0
                doc_map[doc_key] = doc
            fused_scores[doc_key] += w / (k + rank)

    sorted_keys = sorted(fused_scores, key=fused_scores.get, reverse=True)
    return [doc_map[k] for k in sorted_keys]


# ── Stage 5: Cohere Rerank ────────────────────────────────────

def _rerank(
    query: str,
    documents: List[Document],
    top_n: int,
) -> List[Document]:
    """Rerank child chunks using Cohere."""
    if not documents:
        return []

    co = _get_cohere()
    texts = [doc.page_content for doc in documents]

    for attempt in range(5):
        try:
            response = co.rerank(
                model=RERANK_MODEL,
                query=query,
                documents=texts,
                top_n=min(top_n, len(texts)),
            )
            return [documents[r.index] for r in response.results]
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                wait = COHERE_SLEEP_SECONDS * (attempt + 1)
                logger.warning("Cohere rate limited (attempt %d/5), waiting %ds", attempt + 1, wait)
                time.sleep(wait)
            else:
                logger.warning("Cohere rerank failed: %s — returning unranked", e)
                return documents[:top_n]

    logger.warning("Cohere rerank exhausted retries — returning unranked")
    return documents[:top_n]


# ── Stage 6: Parent Lookup ────────────────────────────────────

def _lookup_parents(documents: List[Document]) -> List[str]:
    """Resolve child chunks to unique parent texts via LocalFileStore."""
    store = _get_parent_store()

    # Preserve order, deduplicate by parent_id
    parent_ids = list(dict.fromkeys(
        doc.metadata["parent_id"] for doc in documents
    ))

    parent_texts = []
    for pid in parent_ids:
        raw = store.mget([pid])[0]
        if raw:
            try:
                parent_data = json.loads(raw.decode("utf-8"))
                parent_texts.append(parent_data["text"])
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to parse parent %s: %s", pid, e)
        else:
            logger.warning("Parent %s not found in store", pid)

    return parent_texts


# ── Public API ────────────────────────────────────────────────

def retrieve(
    query: str,
    case_id: str,
    task: Literal["industry_extraction", "severity_scoring"],
    top_k_final: int = TOP_K_FINAL,
) -> List[str]:
    """Retrieve parent chunk texts relevant to a query for a given case.

    This is the ONLY retrieval interface. Both tasks call this.

    Returns:
        List of parent chunk texts, ranked by relevance (typically 5-8 items).
    """
    # ── Stage 1: Routing ──
    params = _get_routing_params(task)
    doc_type_filter = params["doc_type_filter"]
    authoring_entity_filter = params["authoring_entity_filter"]
    bm25_weight = params["bm25_weight"]
    semantic_weight = params["semantic_weight"]
    use_hyde = params["use_hyde"]
    use_multi_query = params["use_multi_query"]
    pre_rerank_k = params["pre_rerank_k"]

    # ── Stage 2: Query translation ──
    all_queries = [query]

    if use_multi_query:
        variants = _generate_query_variants(query)
        all_queries.extend(variants)

    if use_hyde:
        hyde_text = _generate_hyde(query)
        if hyde_text:
            all_queries.append(hyde_text)

    # ── Stage 3: Hybrid search (per query) ──
    chroma_filter = _build_chroma_filter(case_id, doc_type_filter, authoring_entity_filter)

    result_lists: List[List[Document]] = []
    weights: List[float] = []

    for q in all_queries:
        sem_results = _semantic_search(q, chroma_filter, k=pre_rerank_k)
        result_lists.append(sem_results)
        weights.append(semantic_weight)

        bm25_results = _bm25_search(q, case_id, doc_type_filter, authoring_entity_filter, k=pre_rerank_k)
        result_lists.append(bm25_results)
        weights.append(bm25_weight)

    # ── Stage 4: RRF fusion ──
    fused = _reciprocal_rank_fusion(result_lists, weights)
    top_children = fused[:pre_rerank_k]

    if not top_children:
        logger.warning("No results for case %s, task %s", case_id, task)
        return []

    # ── Stage 5: Cohere rerank ──
    reranked = _rerank(query, top_children, top_n=top_k_final)

    # ── Stage 6: Parent lookup ──
    parent_texts = _lookup_parents(reranked)

    return parent_texts
