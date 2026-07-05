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


# -- query rewriting (for conversational follow-ups) ----------------------

REWRITE_SYSTEM_PROMPT = (
    "You rewrite the user's LATEST question into a standalone search query by "
    "replacing pronouns (he/she/it/they/that/this/his/her/their) with the "
    "specific noun they refer to, based on the earlier conversation. Keep the "
    "question otherwise unchanged and keep it phrased as a question. Output ONLY "
    "the rewritten question — no quotes, no explanation, no label. If the latest "
    "question has no pronouns to resolve, output it unchanged.\n"
    "\n"
    "Example 1:\n"
    "Earlier conversation:\nUser: What about Russell?\n"
    "Latest: How tall is he?\nOutput: How tall is Russell?\n"
    "\n"
    "Example 2:\n"
    "Earlier conversation:\nUser: Tell me about the Q3 budget.\n"
    "Latest: Who approved it?\nOutput: Who approved the Q3 budget?"
)


def build_rewrite_prompt(history: list[dict], question: str) -> str:
    """Format prior turns + the new question for the rewrite step.

    Matches the few-shot layout in REWRITE_SYSTEM_PROMPT so the small model
    follows the pattern reliably.
    """
    lines = []
    for msg in history:
        who = "User" if msg.get("role") == "user" else "Assistant"
        lines.append(f"{who}: {msg.get('content', '')}")
    convo = "\n".join(lines)
    return f"Earlier conversation:\n{convo}\n\nLatest: {question}\nOutput:"
