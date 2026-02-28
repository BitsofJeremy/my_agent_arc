"""RAG memory module — vector search and storage via ChromaDB + Ollama embeddings.

Provides two primary async functions designed to be exposed as agent tools:

    - ``search_memory``  – embed a query and retrieve similar facts from ChromaDB.
    - ``save_to_memory``  – embed a fact and persist it into ChromaDB with metadata.

Embedding is performed locally through the Ollama API using the model specified
in ``settings.ollama_embed_model`` (default: ``nomic-embed-text``).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import ollama

from openclaw.config import get_settings
from openclaw.database import get_memory_collection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------


def _embed(text: str) -> list[float] | None:
    """Return an embedding vector for *text*, or ``None`` on failure.

    Uses the Ollama ``embeddings`` endpoint with the model configured in
    :pydata:`settings.ollama_embed_model`.  If Ollama is unreachable or the
    model is unavailable, the error is logged and ``None`` is returned so
    callers can degrade gracefully.
    """
    settings = get_settings()
    try:
        response = ollama.embeddings(
            model=settings.ollama_embed_model,
            prompt=text,
        )
        embedding: list[float] = response["embedding"]
        return embedding
    except ollama.ResponseError as exc:
        logger.warning("Ollama embedding failed (response error): %s", exc)
    except Exception as exc:  # noqa: BLE001 — network / runtime errors
        logger.warning("Ollama embedding unavailable: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def search_memory(query: str, n_results: int = 5) -> list[dict[str, Any]]:
    """Embed *query* and return the closest facts from long-term memory.

    Parameters
    ----------
    query:
        Natural-language search string.
    n_results:
        Maximum number of results to return (default ``5``).

    Returns
    -------
    list[dict[str, Any]]
        Each dict contains ``id``, ``content``, ``metadata``, and ``distance``.
        Returns an empty list when embedding fails or the collection is empty.
    """
    embedding = _embed(query)
    if embedding is None:
        return []

    collection = get_memory_collection()

    try:
        results = collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ChromaDB query failed: %s", exc)
        return []

    # ChromaDB returns parallel lists keyed by field name.
    ids: list[str] = results.get("ids", [[]])[0]
    documents: list[str | None] = results.get("documents", [[]])[0]
    metadatas: list[dict[str, Any] | None] = results.get("metadatas", [[]])[0]
    distances: list[float] = results.get("distances", [[]])[0]

    return [
        {
            "id": doc_id,
            "content": document,
            "metadata": metadata or {},
            "distance": distance,
        }
        for doc_id, document, metadata, distance in zip(
            ids, documents, metadatas, distances
        )
    ]


async def save_to_memory(fact: str, metadata: dict[str, Any] | None = None) -> str:
    """Embed *fact* and store it in long-term memory.

    Parameters
    ----------
    fact:
        The textual content to remember.
    metadata:
        Optional key-value pairs to attach (e.g. ``{"source": "user"}``).

    Returns
    -------
    str
        A confirmation message including the generated document ID.
    """
    embedding = _embed(fact)
    if embedding is None:
        return "Failed to save memory: embedding service unavailable."

    doc_id = uuid.uuid4().hex
    ts = datetime.now(tz=timezone.utc).isoformat()

    doc_metadata: dict[str, Any] = {"saved_at": ts}
    if metadata:
        doc_metadata.update(metadata)

    collection = get_memory_collection()

    try:
        collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[fact],
            metadatas=[doc_metadata],
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("ChromaDB insert failed: %s", exc)
        return f"Failed to save memory: {exc}"

    logger.info("Saved memory %s (%d chars)", doc_id, len(fact))
    return f"Memory saved (id={doc_id})."
