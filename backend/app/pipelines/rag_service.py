import logging
from typing import List, Dict, Any

logger = logging.getLogger("eivanta.pipeline.rag_service")

class InMemoryRAGService:
    """
    Retrieval-Augmented Generation (RAG) vector and keyword search engine for ledger context.
    """
    def __init__(self):
        self.document_store: List[Dict[str, Any]] = []

    def add_documents(self, docs: List[Dict[str, Any]]):
        self.document_store.extend(docs)
        logger.info("Indexed %d documents into RAG vector store.", len(docs))

    def search_context(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        query_terms = query.lower().split()
        scored_docs = []
        for doc in self.document_store:
            content = str(doc.get("content", "")).lower()
            score = sum(1 for term in query_terms if term in content)
            if score > 0:
                scored_docs.append((score, doc))
        
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored_docs[:top_k]]
