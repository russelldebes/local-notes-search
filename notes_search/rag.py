"""Build the RAG prompt from retrieved chunks."""

from __future__ import annotations

from .store import SearchHit

SYSTEM_PROMPT = (
    "You answer questions using the user's personal notes, shown below the "
    "question. Treat the notes as true and authoritative. State any relevant "
    "fact you find, directly and concisely. If the notes truly contain nothing "
    "relevant, say you don't have a note on that. Do not add commentary about "
    "the notes themselves, and do not list filenames — the app shows sources "
    "separately."
)


def build_user_prompt(question: str, hits: list[SearchHit]) -> str:
    """Assemble the retrieved note excerpts + question into a user message."""
    blocks = []
    for i, hit in enumerate(hits, start=1):
        location = hit.path
        if hit.breadcrumb:
            location += f" ({hit.breadcrumb})"
        blocks.append(f"[Note {i} — {location}]\n{hit.text}")
    notes = "\n\n---\n\n".join(blocks)
    return (
        f"Notes:\n\n{notes}\n\n"
        f"---\n\nQuestion: {question}"
    )
