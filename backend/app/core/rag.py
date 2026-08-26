"""
Track 3: persistent vector storage + real RAG knowledge base.

Previously this module was a stub: a hardcoded fake 4-dimensional vector,
one hardcoded demo payload, and `qdrant-client` wasn't even in
requirements.txt -- it couldn't have run. This is the real version:
- Real OpenAI embeddings (text-embedding-3-small, 1536-dim), routed through
  the same BYOK-aware client helper every agent uses -- a tenant's own
  OpenAI key is used for their own document embeddings when configured.
- Every point stored in Qdrant carries a `client_id` payload field, and
  every query filters on it -- this is what makes a shared Qdrant
  collection safe for a multi-tenant app. Skipping this filter would let
  one tenant's uploaded policy/SOP documents leak into another tenant's
  search results, so it's applied on every write and every read, not
  optional.
- Qdrant's own persistent volume (see docker-compose.yml's `qdrant_data`
  volume) is what makes this storage survive a restart -- that volume
  already existed; what was missing was real code actually writing real
  data to it.

Simple fixed-size chunking (character-based, with overlap) is used rather
than a smarter semantic chunker -- a reasonable default for policy/SOP-
style documents, not a hard requirement of the storage layer itself.
"""
import os
import logging
import uuid
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

try:
    from backend.model_registry import get_model
    from backend.byok import get_openai_client_for_tenant_sync
except ImportError:
    from model_registry import get_model
    from byok import get_openai_client_for_tenant_sync

logger = logging.getLogger("eivanta.rag")

EMBEDDING_DIM = 1536  # text-embedding-3-small's real output size
COLLECTION_NAME = "eivanta_knowledge_base"
CHUNK_SIZE_CHARS = 1500
CHUNK_OVERLAP_CHARS = 200

AI_REQUEST_TIMEOUT_SECONDS = 30.0
AI_MAX_RETRIES = 2

platform_api_key = os.getenv("OPENAI_API_KEY")


def _get_qdrant_client() -> QdrantClient:
    """
    Prefers QDRANT_URL (what docker-compose.yml sets for the backend
    container: http://qdrant:6333) when present, falling back to
    QDRANT_HOST/QDRANT_PORT for local dev outside Docker.
    """
    url = os.getenv("QDRANT_URL")
    if url:
        return QdrantClient(url=url)
    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", 6333))
    return QdrantClient(host=host, port=port)


client = _get_qdrant_client()


def init_vector_db():
    """Idempotent -- safe to call on every startup, same shape as db_manager's migrations."""
    collections = client.get_collections().collections
    exists = any(c.name == COLLECTION_NAME for c in collections)
    if not exists:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        logger.info(f"RAG: created Qdrant collection '{COLLECTION_NAME}' (dim={EMBEDDING_DIM}).")


def _chunk_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= CHUNK_SIZE_CHARS:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE_CHARS
        chunks.append(text[start:end])
        start = end - CHUNK_OVERLAP_CHARS
        if start <= 0:
            break
    return chunks


def _embed(client_id: str, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    openai_client = get_openai_client_for_tenant_sync(client_id, platform_api_key, AI_REQUEST_TIMEOUT_SECONDS, AI_MAX_RETRIES)
    if not openai_client:
        raise RuntimeError("No OpenAI API key available (neither BYOK nor platform key configured).")
    model = get_model("knowledge_base_embedding")
    res = openai_client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in res.data]


def add_document(client_id: str, doc_id: str, filename: str, text: str) -> int:
    """
    Chunks and embeds `text`, upserting one Qdrant point per chunk under
    this tenant's client_id. Returns the number of chunks written. Callers
    (the /api/v1/knowledge/upload endpoint) are responsible for extracting
    real text from whatever source file was uploaded -- this function only
    ever deals with plain text.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    if not doc_id:
        raise ValueError("doc_id is required.")
    chunks = _chunk_text(text)
    if not chunks:
        raise ValueError("No text content to index -- the document appears to be empty.")

    init_vector_db()
    vectors = _embed(client_id, chunks)
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "client_id": client_id,
                "doc_id": doc_id,
                "filename": filename,
                "chunk_index": i,
                "content": chunk,
            },
        )
        for i, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    client.upsert(collection_name=COLLECTION_NAME, points=points)
    return len(points)


def query_knowledge_base(client_id: str, query_text: str, limit: int = 5) -> list[dict]:
    """
    Tenant-scoped semantic search -- the Filter below is what prevents
    tenant A's documents from ever appearing in tenant B's results, even
    though they share one Qdrant collection.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    if not query_text or not query_text.strip():
        return []

    init_vector_db()
    [query_vector] = _embed(client_id, [query_text])
    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        query_filter=Filter(must=[FieldCondition(key="client_id", match=MatchValue(value=client_id))]),
        limit=limit,
    )
    return [
        {
            "content": hit.payload.get("content", ""),
            "filename": hit.payload.get("filename", ""),
            "doc_id": hit.payload.get("doc_id", ""),
            "score": hit.score,
        }
        for hit in results
    ]


def list_documents(client_id: str) -> list[dict]:
    """
    Returns one summary row per distinct doc_id for this tenant (filename,
    chunk count) -- scrolls the collection filtered by client_id rather
    than tracking documents in a separate table, since Qdrant's payload is
    already the source of truth for what's indexed.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    init_vector_db()
    docs: dict[str, dict] = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(must=[FieldCondition(key="client_id", match=MatchValue(value=client_id))]),
            limit=200,
            offset=offset,
            with_payload=True,
        )
        for p in points:
            doc_id = p.payload.get("doc_id")
            if doc_id not in docs:
                docs[doc_id] = {"doc_id": doc_id, "filename": p.payload.get("filename", ""), "chunk_count": 0}
            docs[doc_id]["chunk_count"] += 1
        if offset is None:
            break
    return list(docs.values())


def delete_document(client_id: str, doc_id: str) -> int:
    """Deletes every chunk for this tenant's doc_id. Returns nothing reliably countable pre-delete, so this reports success via the caller checking list_documents again -- kept simple."""
    if not client_id or not doc_id:
        raise ValueError("client_id and doc_id are required.")
    init_vector_db()
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[
                FieldCondition(key="client_id", match=MatchValue(value=client_id)),
                FieldCondition(key="doc_id", match=MatchValue(value=doc_id)),
            ]
        ),
    )
    return 1
