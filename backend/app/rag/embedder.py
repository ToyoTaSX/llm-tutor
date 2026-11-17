"""Эмбеддер BGE-M3: плотные + разреженные векторы (из rag_lab/rag_core.py)."""
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class SparseVec:
    indices: list[int]
    values: list[float]


class BgeM3Embedder:
    """Один экземпляр на процесс. encode() защищён блокировкой: модель не
    гарантирует потокобезопасность, а индексация и вопросы идут параллельно."""

    def __init__(self, model_path: Path, device: str = "cuda", batch: int = 16):
        self.model_path = model_path
        self.device = device
        self.batch = batch
        self._model = None
        self._lock = threading.Lock()
        self.ready = threading.Event()
        self.error: str | None = None

    def load(self) -> None:
        try:
            if not (self.model_path / "config.json").exists():
                raise FileNotFoundError(f"Модель эмбеддингов не найдена: ожидалась папка {self.model_path}")
            from FlagEmbedding import BGEM3FlagModel

            use_fp16 = self.device == "cuda"
            try:
                self._model = BGEM3FlagModel(str(self.model_path), use_fp16=use_fp16, devices=[self.device])
            except TypeError:  # старые версии FlagEmbedding без devices
                self._model = BGEM3FlagModel(str(self.model_path), use_fp16=use_fp16)
            self.encode(["прогрев"])
            log.info("BGE-M3 загружен (%s) из %s", self.device, self.model_path)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            log.exception("Не удалось загрузить эмбеддер")
        finally:
            self.ready.set()

    def encode(self, texts: list[str], max_length: int = 512) -> tuple[list[list[float]], list[SparseVec]]:
        if self._model is None:
            raise RuntimeError(self.error or "Эмбеддер ещё не загружен")
        with self._lock:
            out = self._model.encode(
                texts,
                batch_size=self.batch,
                max_length=max_length,
                return_dense=True,
                return_sparse=True,
                return_colbert_vecs=False,
            )
        dense = [v.tolist() for v in out["dense_vecs"]]
        sparse = [
            SparseVec(indices=[int(k) for k in w.keys()], values=[float(x) for x in w.values()])
            for w in out["lexical_weights"]
        ]
        return dense, sparse
