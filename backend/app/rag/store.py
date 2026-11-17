"""Векторное хранилище Qdrant (сервер): коллекция фрагментов всех лекций (design D10)."""
import uuid

from qdrant_client import QdrantClient, models

from .embedder import SparseVec

POINT_NS = uuid.UUID("6f1c1d1e-3b0a-4c55-9a52-3c1f7c1d0b11")


def point_id(doc_id: int, chunk_no: int) -> str:
    return str(uuid.uuid5(POINT_NS, f"{doc_id}:{chunk_no}"))


class QdrantStore:
    def __init__(self, url: str, collection: str, dim: int = 1024):
        self.client = QdrantClient(url=url, timeout=30)
        self.collection = collection
        self.dim = dim

    def ping(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:  # noqa: BLE001
            return False

    def ensure_collection(self) -> None:
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                vectors_config={"dense": models.VectorParams(size=self.dim, distance=models.Distance.COSINE)},
                sparse_vectors_config={"sparse": models.SparseVectorParams()},
            )
        self.client.create_payload_index(self.collection, "doc_id", models.PayloadSchemaType.INTEGER)

    def upsert_chunks(
        self,
        doc_id: int,
        doc_title: str,
        start_no: int,
        texts: list[str],
        dense: list[list[float]],
        sparse: list[SparseVec],
    ) -> None:
        points = [
            models.PointStruct(
                id=point_id(doc_id, start_no + i),
                vector={
                    "dense": dense[i],
                    "sparse": models.SparseVector(indices=sparse[i].indices, values=sparse[i].values),
                },
                payload={"doc_id": doc_id, "doc_title": doc_title, "chunk_no": start_no + i, "text": texts[i]},
            )
            for i in range(len(texts))
        ]
        self.client.upsert(self.collection, points=points, wait=True)

    def _doc_filter(self, doc_id: int) -> models.Filter:
        return models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])

    def delete_by_doc(self, doc_id: int) -> None:
        self.client.delete(
            self.collection, points_selector=models.FilterSelector(filter=self._doc_filter(doc_id)), wait=True
        )

    def count_by_doc(self, doc_id: int) -> int:
        return self.client.count(self.collection, count_filter=self._doc_filter(doc_id), exact=True).count

    def search(
        self,
        dense: list[float],
        sparse: SparseVec,
        ready_ids: list[int],
        k: int,
        candidates: int,
        rrf_k: int,
    ) -> list[dict]:
        """Гибрид: смысловой + лексический поиск, слияние рангов RRF (как в rag_lab).
        Ищем только среди документов в статусе «готов»."""
        if not ready_ids:
            return []
        flt = models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchAny(any=ready_ids))])
        lists = [
            self.client.query_points(
                self.collection, query=dense, using="dense", limit=candidates, with_payload=True, query_filter=flt
            ).points,
            self.client.query_points(
                self.collection,
                query=models.SparseVector(indices=sparse.indices, values=sparse.values),
                using="sparse",
                limit=candidates,
                with_payload=True,
                query_filter=flt,
            ).points,
        ]
        scores: dict = {}
        payloads: dict = {}
        for lst in lists:
            for rank, p in enumerate(lst):
                scores[p.id] = scores.get(p.id, 0.0) + 1.0 / (rrf_k + rank + 1)
                payloads[p.id] = p.payload
        top = sorted(scores, key=scores.get, reverse=True)[:k]
        return [{"score": scores[i], **payloads[i]} for i in top]
