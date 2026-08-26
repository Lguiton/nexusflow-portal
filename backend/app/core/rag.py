import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import uuid

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))

client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
COLLECTION_NAME = "nexus_knowledge_base"

def init_vector_db():
    collections = client.get_collections().collections
    exists = any(c.name == COLLECTION_NAME for c in collections)
    if not exists:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=4, distance=Distance.COSINE),
        )
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=[0.1, 0.2, 0.3, 0.4],
                    payload={"content": "Eivanta AI Agents reduce manual CRM entry time by 80% using async ETL pipelines."}
                )
            ]
        )

def query_knowledge_base(vector_query: list[float]):
    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector_query,
        limit=2
    )
    return [hit.payload["content"] for hit in results]
