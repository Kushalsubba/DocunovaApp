"""
vector_store.py — Milvus Lite vector store for document chunks.

Embeddings: nomic-embed-text:latest (768-dim) via local Ollama.
Storage: Milvus Lite (single-file DB, no Docker needed).
"""

import re
import json
import urllib.request
from typing import List, Dict, Optional, Any

from config import settings

COLLECTION = "document_chunks"
EMBED_DIM = 768          # nomic-embed-text:latest output dimension
CHUNK_WORDS = 200        # words per chunk
OVERLAP_WORDS = 50       # word overlap between consecutive chunks (25% of chunk)


# ── Embedding ─────────────────────────────────────────────────────────────────

def get_embedding(text: str) -> Optional[List[float]]:
    """Return 768-dim embedding for a single text. None on failure."""
    results = get_embeddings_batch([text])
    return results[0] if results else None


def get_embeddings_batch(texts: List[str],
                         batch_size: int = 16) -> List[Optional[List[float]]]:
    """Return embeddings for a list of texts using Ollama batch API."""
    all_results: List[Optional[List[float]]] = []
    for i in range(0, len(texts), batch_size):
        batch = [t[:8000] for t in texts[i: i + batch_size]]
        try:
            payload = json.dumps({
                "model": settings.embedding_model,
                "input": batch,
            }).encode()
            req = urllib.request.Request(
                f"{settings.ollama_url}/api/embed",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            embeddings = data.get("embeddings", [])
            for emb in embeddings:
                all_results.append(emb if len(emb) == EMBED_DIM else None)
            # Pad if fewer returned than sent
            while len(all_results) < i + len(batch):
                all_results.append(None)
        except Exception as e:
            print(f"Batch embedding error (batch {i}): {e}")
            all_results.extend([None] * len(batch))
    return all_results


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_document(content: str) -> List[Dict[str, Any]]:
    """
    Split stored document content (which may have [PAGE_N] markers) into
    overlapping word-level chunks.  Returns list of dicts:
        {page_number, chunk_index, content}
    """
    # Parse page-marked sections
    parts = re.split(r'\[PAGE_(\d+)\]\n?', content)
    page_sections: List[tuple] = []   # (page_number, text)
    current_page = 1
    for i, part in enumerate(parts):
        if i % 2 == 1:
            try:
                current_page = int(part)
            except ValueError:
                pass
        else:
            text = part.strip()
            if text:
                page_sections.append((current_page, text))

    # Fallback: no markers — treat whole text as page 1
    if not page_sections:
        clean = re.sub(r'\[PAGE_\d+\]\n?', '', content).strip()
        if clean:
            page_sections = [(1, clean)]

    chunks: List[Dict] = []
    idx = 0
    for page_num, text in page_sections:
        words = text.split()
        pos = 0
        while pos < len(words):
            segment = " ".join(words[pos: pos + CHUNK_WORDS]).strip()
            if segment:
                chunks.append({
                    "page_number": page_num,
                    "chunk_index": idx,
                    "content": segment,
                })
                idx += 1
            if pos + CHUNK_WORDS >= len(words):
                break
            pos += CHUNK_WORDS - OVERLAP_WORDS

    return chunks


# ── Milvus vector store ───────────────────────────────────────────────────────

class MilvusVectorStore:
    """Thin wrapper around MilvusClient (Milvus Lite) for document chunks."""

    def __init__(self):
        from pymilvus import MilvusClient
        import os
        db = settings.milvus_db_path
        os.makedirs(os.path.dirname(os.path.abspath(db)), exist_ok=True)
        self.client = MilvusClient(db)
        self._ensure_collection()

    def _ensure_collection(self):
        if not self.client.has_collection(COLLECTION):
            self.client.create_collection(
                collection_name=COLLECTION,
                dimension=EMBED_DIM,
                metric_type="COSINE",
                auto_id=True,
                enable_dynamic_field=True,
            )
            print(f"[Milvus] Created collection '{COLLECTION}' dim={EMBED_DIM}")

    # ── Write ─────────────────────────────────────────────────────────────────

    def insert_chunks(self, doc_id: str, filename: str,
                      chunks: List[Dict[str, Any]]) -> int:
        """Insert pre-embedded chunks. Each chunk must have 'embedding' key."""
        rows = []
        for c in chunks:
            emb = c.get("embedding")
            if not emb or len(emb) != EMBED_DIM:
                continue
            rows.append({
                "vector": emb,
                "doc_id": doc_id,
                "filename": filename,
                "page_number": int(c.get("page_number", 1)),
                "chunk_index": int(c.get("chunk_index", 0)),
                "content": str(c.get("content", ""))[:4096],
            })
        if rows:
            self.client.insert(collection_name=COLLECTION, data=rows)
        return len(rows)

    def delete_by_doc_id(self, doc_id: str):
        try:
            self.client.delete(
                collection_name=COLLECTION,
                filter=f'doc_id == "{doc_id}"',
            )
        except Exception as e:
            print(f"[Milvus] Delete error for doc {doc_id}: {e}")

    def drop_and_recreate(self):
        """Wipe and rebuild the collection (used during full re-index)."""
        try:
            self.client.drop_collection(COLLECTION)
        except Exception:
            pass
        self._ensure_collection()

    # ── Read ──────────────────────────────────────────────────────────────────

    def search(self, query_embedding: List[float],
               limit: int = 8, min_score: float = 0.30) -> List[Dict[str, Any]]:
        """Return top-K chunks sorted by cosine similarity (descending)."""
        if not query_embedding:
            return []
        try:
            raw = self.client.search(
                collection_name=COLLECTION,
                data=[query_embedding],
                limit=limit,
                output_fields=["doc_id", "filename", "page_number",
                                "chunk_index", "content"],
            )
            hits = []
            for hit in raw[0]:
                score = float(hit.get("distance", 0))
                if score < min_score:
                    continue
                entity = hit.get("entity", {})
                hits.append({
                    "doc_id":       entity.get("doc_id", ""),
                    "filename":     entity.get("filename", ""),
                    "page_number":  entity.get("page_number", 1),
                    "chunk_index":  entity.get("chunk_index", 0),
                    "content":      entity.get("content", ""),
                    "score":        round(score, 4),
                })
            return hits
        except Exception as e:
            print(f"[Milvus] Search error: {e}")
            return []

    def get_adjacent_chunks(self, doc_id: str, chunk_index: int,
                            window: int = 1) -> List[Dict[str, Any]]:
        """Return chunks immediately before/after chunk_index for the same document."""
        indices = [i for i in range(chunk_index - window, chunk_index + window + 1)
                   if i >= 0 and i != chunk_index]
        if not indices:
            return []
        try:
            results = self.client.query(
                collection_name=COLLECTION,
                filter=f'doc_id == "{doc_id}" and chunk_index in {indices}',
                output_fields=["doc_id", "filename", "page_number",
                                "chunk_index", "content"],
            )
            return [{
                "doc_id":      r["doc_id"],
                "filename":    r["filename"],
                "page_number": r["page_number"],
                "chunk_index": r["chunk_index"],
                "content":     r["content"],
                "score":       0.0,
            } for r in results]
        except Exception as e:
            print(f"[Milvus] get_adjacent_chunks error: {e}")
            return []

    def count(self) -> int:
        try:
            return int(self.client.get_collection_stats(COLLECTION)
                       .get("row_count", 0))
        except Exception:
            return 0
