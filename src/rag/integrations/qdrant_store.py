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
    def from_http(
        cls,
        *,
        collection: str,
        host: str = "localhost",
        port: int = 6333,
        url: str | None = None,
        api_key: str | None = None,
    ) -> "QdrantVectorStore":
        if url:
            # Qdrant Cloud / HTTPS endpoint: QdrantClient(url=..., api_key=...)
            client = QdrantClient(url=url, api_key=api_key)
        else:
            client = QdrantClient(host=host, port=port, api_key=api_key, https=bool(api_key))
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

    def delete_stale_points(self, valid_chunk_ids) -> int:
        """
        Delete points whose payload chunk id is not in ``valid_chunk_ids``.

        Used to sync Qdrant to the current chunks JSONL after a re-scrape, so
        stale site chunks are removed while added (PDF/text) chunks are kept.
        Returns the number of points deleted.
        """
        valid = {str(i) for i in valid_chunk_ids}
        stale: List[str] = []
        next_offset: Any = None

        while True:
            kwargs: dict[str, Any] = {"limit": 100, "with_payload": True, "with_vectors": False}
            if next_offset is not None:
                kwargs["offset"] = next_offset
            points, next_offset = self.client.scroll(collection_name=self.collection, **kwargs)
            for p in points:
                payload = p.payload or {}
                chunk_id = payload.get("id") or payload.get("chunk_id")
                if chunk_id is not None and str(chunk_id) not in valid:
                    stale.append(str(p.id))
            if not points or next_offset is None:
                break

        if stale:
            self.client.delete(collection_name=self.collection, points_selector=stale)
        return len(stale)
