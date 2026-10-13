"""
FRIDAY knowledge base (RAG), fully local and free.

Documents are split into chunks, embedded on this machine and stored under
.knowledge/ (gitignored). Embeddings: fastembed (BAAI/bge-small-en-v1.5, runs
locally via ONNX) when installed; otherwise a built-in hashing embedder so the
feature still works offline with no download.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
KB_DIR = BASE_DIR / ".knowledge"
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".js", ".html", ".log", ".yaml", ".yml", ".rst"}


class HashEmbedder:
    """Dependency-free local embedder (feature hashing of words + bigrams)."""
    name = "hash-512"
    dim = 512

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            words = re.findall(r"\w+", t.lower())
            for j, w in enumerate(words):
                out[i, _h(w) % self.dim] += 1.0
                if j + 1 < len(words):
                    out[i, _h(w + " " + words[j + 1]) % self.dim] += 0.5
            n = np.linalg.norm(out[i])
            if n:
                out[i] /= n
        return out


def _h(s: str) -> int:
    # stable across runs (python's hash() is salted)
    h = 2166136261
    for ch in s.encode("utf-8"):
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h


class FastEmbedder:
    name = "bge-small-en-v1.5"

    def __init__(self):
        from fastembed import TextEmbedding
        self._m = TextEmbedding("BAAI/bge-small-en-v1.5")

    def embed(self, texts: list[str]) -> np.ndarray:
        v = np.array(list(self._m.embed(texts)), dtype=np.float32)
        n = np.linalg.norm(v, axis=1, keepdims=True)
        return v / np.maximum(n, 1e-9)


def default_embedder():
    try:
        return FastEmbedder()
    except Exception:
        return HashEmbedder()


def chunk_text(text: str, size: int = 800, overlap: int = 120) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        if i + size >= len(text):
            break
        i += size - overlap
    return out


def read_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in TEXT_EXT:
        return path.read_text(encoding="utf-8", errors="ignore")
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
        except Exception as e:                      # noqa: BLE001
            raise ValueError(f"Could not read PDF (install pypdf): {e}")
    raise ValueError(f"Unsupported file type '{ext}'. Supported: text/markdown/code/csv/json/pdf.")


class KnowledgeBase:
    def __init__(self, directory: Path | None = None, embedder=None):
        self.dir = Path(directory or KB_DIR)
        self._embedder = embedder
        self._chunks: list[dict] = []
        self._vecs = np.zeros((0, 1), dtype=np.float32)
        self._load()

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = default_embedder()
        return self._embedder

    def _load(self):
        meta, vecs = self.dir / "chunks.json", self.dir / "vectors.npy"
        if meta.exists() and vecs.exists():
            try:
                d = json.loads(meta.read_text(encoding="utf-8"))
                self._chunks, self._emb_name = d["chunks"], d.get("embedder", "")
                self._vecs = np.load(vecs)
            except Exception:
                self._chunks, self._emb_name = [], ""
        else:
            self._emb_name = ""

    def _save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "chunks.json").write_text(
            json.dumps({"embedder": self.embedder.name, "chunks": self._chunks}), encoding="utf-8")
        np.save(self.dir / "vectors.npy", self._vecs)

    def _ensure_compatible(self):
        """If the stored vectors came from another embedder, re-embed them."""
        if self._chunks and self._emb_name and self._emb_name != self.embedder.name:
            self._vecs = self.embedder.embed([c["text"] for c in self._chunks])
        self._emb_name = self.embedder.name

    def add_text(self, name: str, text: str) -> int:
        self._ensure_compatible()
        pieces = chunk_text(text)
        if not pieces:
            return 0
        # replace any older version of the same document
        keep = [i for i, c in enumerate(self._chunks) if c["source"] != name]
        self._chunks = [self._chunks[i] for i in keep]
        self._vecs = self._vecs[keep] if len(keep) and self._vecs.size else np.zeros((0, 1), np.float32)
        new = self.embedder.embed(pieces)
        self._vecs = new if self._vecs.size == 0 else np.vstack([self._vecs, new])
        self._chunks += [{"source": name, "text": p} for p in pieces]
        self._save()
        return len(pieces)

    def add_file(self, path: str) -> int:
        p = Path(path).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"File not found: {p}")
        return self.add_text(p.name, read_file(p))

    def sources(self) -> list[str]:
        return sorted({c["source"] for c in self._chunks})

    def remove(self, name: str) -> int:
        keep = [i for i, c in enumerate(self._chunks) if c["source"] != name]
        removed = len(self._chunks) - len(keep)
        if removed:
            self._chunks = [self._chunks[i] for i in keep]
            self._vecs = self._vecs[keep] if keep else np.zeros((0, 1), np.float32)
            self._save()
        return removed

    def search(self, query: str, k: int = 4) -> list[dict]:
        if not self._chunks:
            return []
        self._ensure_compatible()
        q = self.embedder.embed([query])[0]
        scores = self._vecs @ q
        order = np.argsort(-scores)[:k]
        return [{"source": self._chunks[i]["source"], "text": self._chunks[i]["text"],
                 "score": float(scores[i])} for i in order if scores[i] > 0]
