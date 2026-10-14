"""Evidence retrieval from Supabase pgvector. Returns [] when not configured or on any failure."""
import asyncio
import logging
from functools import lru_cache

from ..core.config import get_settings
from ..core.db import get_supabase

log = logging.getLogger("growthtwin.rag")


@lru_cache
def _embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(get_settings().embed_model)


def embed_query(text: str) -> list[float]:
    return _embedder().encode("query: " + text, normalize_embeddings=True).tolist()


async def retrieve(query: str, crop_id: str | None = None, k: int = 3) -> list[dict]:
    client = get_supabase()
    if client is None:
        return []
    try:
        vec = await asyncio.to_thread(embed_query, query)
        res = await asyncio.to_thread(
            lambda: client.rpc(
                "match_rag_chunks",
                {"query_embedding": vec, "match_count": k, "filter_crop": crop_id},
            ).execute()
        )
        return [
            {"source": r["source"], "page": r.get("page"), "snippet": r["content"][:400],
             "similarity": round(r["similarity"], 3)}
            for r in res.data
            if r["similarity"] >= 0.75
        ]
    except Exception as e:
        log.warning("RAG retrieval failed: %s", e)
        return []
