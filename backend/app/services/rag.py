"""Retrieval-Augmented Generation pipeline.

For a chat turn:
  1. Embed the user query (RETRIEVAL_QUERY task type).
  2. Retrieve top-k matching chunks via pgvector cosine similarity.
  3. Build a numbered context block + citation map.
  4. Call Gemini with system prompt that enforces `[n]` citation style.
  5. Parse citations, drop any out-of-range numbers, resolve to full info.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from app.services.gemini import (
    CHAT_DEFAULT,
    ChatResult,
    Usage,
    get_gemini,
    is_chat_model_allowed,
)
from app.services.supabase_client import get_supabase

TOP_K = 8

CITATION_RE = re.compile(r"\[(\d+)\]")

SYSTEM_PROMPT = """You are a research assistant grounded in the provided source context.

Rules:
- Answer the user's question using ONLY the numbered context blocks below.
- Cite supporting context with bracketed numbers like [1], [3]. Cite at the end of every claim.
- If the context does not contain enough information to answer, reply: "I don't have enough information in the provided sources to answer that."
- Be concise. Use markdown lists when helpful. Do not invent citations.
"""


@dataclass
class RetrievedChunk:
    chunk_id: str
    source_id: str
    source_name: str
    content: str
    metadata: dict[str, Any]
    similarity: float


@dataclass
class Citation:
    number: int
    chunk_id: str
    source_id: str
    source_name: str
    text_excerpt: str
    metadata: dict[str, Any]
    similarity: float

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "chunk_id": self.chunk_id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "text_excerpt": self.text_excerpt,
            "metadata": self.metadata,
            "similarity": self.similarity,
        }


@dataclass
class RagAnswer:
    content: str
    citations: list[Citation]
    source_ids_used: list[str]
    chat_usage: Usage
    embed_usage: Usage


def _build_context(chunks: list[RetrievedChunk]) -> str:
    parts = []
    for i, c in enumerate(chunks, start=1):
        loc = ""
        if "page" in c.metadata:
            loc = f", p.{c.metadata['page']}"
        elif "start" in c.metadata:
            loc = f", t={c.metadata['start']:.0f}s"
        elif "paragraph" in c.metadata:
            loc = f", ¶{c.metadata['paragraph']}"
        parts.append(f"[{i}] ({c.source_name}{loc})\n{c.content}")
    return "\n\n".join(parts)


async def retrieve(
    *,
    notebook_id: str,
    query_vector: list[float],
    source_ids: list[str] | None,
    k: int = TOP_K,
) -> list[RetrievedChunk]:
    """Run the pgvector top-k search via a server-side RPC.

    Requires the `match_notebook_chunks` Postgres function (see migration 005).
    """
    sb = get_supabase()
    payload = {
        "p_notebook_id": notebook_id,
        "p_query": query_vector,
        "p_source_ids": source_ids,  # null = all ready sources
        "p_k": k,
    }
    rows = await asyncio.to_thread(
        lambda: sb.rpc("match_notebook_chunks", payload).execute()
    )
    out: list[RetrievedChunk] = []
    for r in rows.data or []:
        out.append(
            RetrievedChunk(
                chunk_id=r["chunk_id"],
                source_id=r["source_id"],
                source_name=r["source_name"],
                content=r["content"],
                metadata=r.get("metadata") or {},
                similarity=float(r["similarity"]),
            )
        )
    return out


def parse_citations(text: str, chunks: list[RetrievedChunk]) -> list[Citation]:
    """Extract `[n]` citations and resolve to chunk info.

    Out-of-range numbers are silently dropped. Each cited chunk appears once.
    """
    seen: set[int] = set()
    citations: list[Citation] = []
    for m in CITATION_RE.finditer(text):
        n = int(m.group(1))
        if n in seen:
            continue
        if n < 1 or n > len(chunks):
            continue
        seen.add(n)
        c = chunks[n - 1]
        excerpt = c.content[:300] + ("…" if len(c.content) > 300 else "")
        citations.append(
            Citation(
                number=n,
                chunk_id=c.chunk_id,
                source_id=c.source_id,
                source_name=c.source_name,
                text_excerpt=excerpt,
                metadata=c.metadata,
                similarity=c.similarity,
            )
        )
    return citations


async def answer(
    *,
    notebook_id: str,
    user_message: str,
    history: list[dict],
    source_ids: list[str] | None,
    model: str = CHAT_DEFAULT,
) -> RagAnswer:
    if not is_chat_model_allowed(model):
        model = CHAT_DEFAULT

    gemini = get_gemini()

    # 1. Embed query.
    embed = await asyncio.to_thread(gemini.embed_query, user_message)
    if not embed.vectors:
        raise RuntimeError("Failed to embed query")
    qv = embed.vectors[0]

    # 2. Retrieve.
    chunks = await retrieve(
        notebook_id=notebook_id,
        query_vector=qv,
        source_ids=source_ids,
    )

    # 3. Build user message with context.
    if chunks:
        context = _build_context(chunks)
        composed = (
            f"Context:\n{context}\n\n"
            f"---\n"
            f"User question: {user_message}"
        )
    else:
        composed = (
            "Context: (none — the notebook has no ready sources or no matches were found.)\n\n"
            "---\n"
            f"User question: {user_message}"
        )

    # 4. Generate.
    chat = await asyncio.to_thread(
        gemini.generate_chat,
        system_instruction=SYSTEM_PROMPT,
        history=history,
        user_message=composed,
        model=model,
    )

    # 5. Parse citations.
    citations = parse_citations(chat.content, chunks)
    source_ids_used = sorted({c.source_id for c in citations})

    return RagAnswer(
        content=chat.content,
        citations=citations,
        source_ids_used=source_ids_used,
        chat_usage=chat.usage,
        embed_usage=embed.usage,
    )
