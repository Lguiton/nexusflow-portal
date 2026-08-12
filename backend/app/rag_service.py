from qdrant_client import QdrantClient
from qdrant_client.http import models

class SMBKnowledgeBase:
    def __init__(self):
        # Local in-memory vector storage for fast SMB telemetry queries
        self.client = QdrantClient(":memory:")
        self.collection = "support_knowledge"
        
        self.client.recreate_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE),
        )
        
        # Seed initial operational knowledge base
        self.seed_knowledge()

    def seed_knowledge(self):
        sample_docs = [
            {"id": 1, "vector": [0.1, 0.9, 0.2, 0.1], "text": "Billing error resolution: Verify stripe webhook logs and issue manual credit via dashboard."},
            {"id": 2, "vector": [0.8, 0.1, 0.1, 0.9], "text": "API authentication failure: Check JWT token expiration settings and rotate bearer keys."},
            {"id": 3, "vector": [0.3, 0.3, 0.8, 0.2], "text": "Database latency spike: Scale connection pool limits and check active pg_stat_activity queries."}
        ]
        
        for doc in sample_docs:
            self.client.upsert(
                collection_name=self.collection,
                points=[
                    models.PointStruct(
                        id=doc["id"],
                        vector=doc["vector"],
                        payload={"text": doc["text"]}
                    )
                ]
            )

    def search_docs(self, query_vector: list[float]):
        hits = self.client.search(
            collection_name=self.collection,
            query_vector=query_vector,
            limit=2
        )
        return [hit.payload["text"] for hit in hits]

rag_engine = SMBKnowledgeBase()