"""RAG service — embeddings via Ollama + vector storage via ChromaDB."""

import chromadb
import httpx
from loguru import logger

from config import config

# Ollama embedding config
OLLAMA_BASE_URL = config.llm.ollama_base_url
EMBED_MODEL = "nomic-embed-text"

# ChromaDB persistent client — stores vectors on disk
_chroma_client: chromadb.ClientAPI | None = None

MEMORIES_COLLECTION = "user_memories"
HISTORY_COLLECTION = "conversation_history"


def _get_chroma() -> chromadb.ClientAPI:
    global _chroma_client
    if _chroma_client is None:
        from pathlib import Path

        chroma_dir = str(Path(config.db_path).parent / "chroma_data")
        _chroma_client = chromadb.PersistentClient(path=chroma_dir)
        logger.info(f"ChromaDB initialized at {chroma_dir}")
    return _chroma_client


def _get_collection(name: str) -> chromadb.Collection:
    return _get_chroma().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


async def get_embedding(text: str) -> list[float]:
    """Get embedding vector from Ollama nomic-embed-text."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/embed",
            json={"model": EMBED_MODEL, "input": text},
        )
        response.raise_for_status()
        data = response.json()
        return data["embeddings"][0]


async def store_memory(user_id: int, memory_id: int, content: str, category: str):
    """Embed and store a user memory in ChromaDB."""
    embedding = await get_embedding(content)
    collection = _get_collection(MEMORIES_COLLECTION)
    doc_id = f"user_{user_id}_mem_{memory_id}"
    collection.upsert(
        ids=[doc_id],
        embeddings=[embedding],
        documents=[content],
        metadatas=[{"user_id": user_id, "memory_id": memory_id, "category": category}],
    )


async def delete_memory(user_id: int, memory_id: int):
    """Remove a memory from ChromaDB."""
    collection = _get_collection(MEMORIES_COLLECTION)
    doc_id = f"user_{user_id}_mem_{memory_id}"
    try:
        collection.delete(ids=[doc_id])
    except Exception:
        pass


async def retrieve_relevant_memories(
    user_id: int, query: str, top_k: int = 10
) -> list[dict]:
    """Retrieve the most relevant memories for a user given a query."""
    collection = _get_collection(MEMORIES_COLLECTION)

    # Check if collection has any documents for this user
    try:
        count = collection.count()
        if count == 0:
            return []
    except Exception:
        return []

    embedding = await get_embedding(query)
    results = collection.query(
        query_embeddings=[embedding],
        n_results=top_k,
        where={"user_id": user_id},
    )

    memories = []
    if results and results["documents"]:
        for i, doc in enumerate(results["documents"][0]):
            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 0
            memories.append(
                {
                    "content": doc,
                    "category": metadata.get("category", "general"),
                    "relevance": round(1 - distance, 3),  # cosine: 1 = identical
                }
            )

    return memories


async def store_conversation_message(
    user_id: int, conv_id: int, message_id: int, role: str, content: str
):
    """Embed and store a conversation message for semantic search."""
    if not content or len(content.strip()) < 5:
        return
    embedding = await get_embedding(content[:2000])  # Limit to avoid huge embeddings
    collection = _get_collection(HISTORY_COLLECTION)
    doc_id = f"user_{user_id}_conv_{conv_id}_msg_{message_id}"
    collection.upsert(
        ids=[doc_id],
        embeddings=[embedding],
        documents=[content[:2000]],
        metadatas={"user_id": user_id, "conversation_id": conv_id, "role": role},
    )


async def search_conversation_history(
    user_id: int, query: str, top_k: int = 10
) -> list[dict]:
    """Semantic search over past conversation messages."""
    collection = _get_collection(HISTORY_COLLECTION)

    try:
        count = collection.count()
        if count == 0:
            return []
    except Exception:
        return []

    embedding = await get_embedding(query)
    results = collection.query(
        query_embeddings=[embedding],
        n_results=top_k,
        where={"user_id": user_id},
    )

    messages = []
    if results and results["documents"]:
        for i, doc in enumerate(results["documents"][0]):
            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 0
            messages.append(
                {
                    "content": doc,
                    "role": metadata.get("role", "unknown"),
                    "conversation_id": metadata.get("conversation_id"),
                    "relevance": round(1 - distance, 3),
                }
            )

    return messages
