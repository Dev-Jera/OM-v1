"""
Qdrant vector store wrapper (RAG namespace).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
import uuid


@dataclass
class QdrantVectorStore:
    collection: str
    client: QdrantClient

    @classmethod
    def from_local_path(cls, *, collection: str, path: str) -> "QdrantVectorStore":
        client = QdrantClient(path=path)
        return cls(collection=collection, client=client)

    @classmethod
    def from_http(cls, *, collection: str, host: str, port: int) -> "QdrantVectorStore":
        client = QdrantClient(host=host, port=port)
        return cls(collection=collection, client=client)

    def ensure_collection(self, vector_size: int) -> None:
        # qdrant-client API differs across versions; avoid relying on collection_exists()
        try:
            collections = self.client.get_collections()
            names = {c.name for c in collections.collections}
            if self.collection in names:
                return
        except Exception:
            # Older local client may not support get_collections; fall back to probing.
            try:
                self.client.get_collection(self.collection)
                return
            except Exception:
                pass
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
        )

    def upsert(
        self,
        *,
        ids: List[str],
        vectors: List[List[float]],
        payloads: List[dict],
    ) -> None:
        # qdrant-client local storage (and some server configs) may require UUID point IDs.
        # Convert stable string IDs into deterministic UUIDv5.
        point_ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, _id)) for _id in ids]
        points = [qm.PointStruct(id=_id, vector=vec, payload=payload) for _id, vec, payload in zip(point_ids, vectors, payloads, strict=True)]
        self.client.upsert(collection_name=self.collection, points=points)

    def search(
        self,
        *,
        query_vector: List[float],
        limit: int = 8,
        filter: qm.Filter | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for similar vectors in Qdrant.

        Args:
            query_vector: The query embedding vector
            limit: Maximum number of results to return
            filter: Optional Qdrant filter for metadata filtering
        """
        res = self.client.search(
            collection_name=self.collection,
            query_vector=query_vector,
            limit=limit,
            query_filter=filter,
        )
        out: list[dict[str, Any]] = []
        for p in res:
            payload = p.payload or {}
            stable_id = None
            if isinstance(payload, dict):
                stable_id = payload.get("id") or payload.get("chunk_id")
            out.append(
                {
                    # Prefer the original chunk id (stored in payload during ingest)
                    # over the Qdrant point id (UUID).
                    "id": str(stable_id or p.id),
                    "score": float(p.score),
                    "payload": payload,
                }
            )
        return out
