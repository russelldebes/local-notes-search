"""Thin wrapper around the Ollama HTTP API.

Centralises:
  * a health check that prints friendly, copy-pasteable fix commands,
  * embedding a batch of texts,
  * streaming a chat completion for RAG.
"""

from __future__ import annotations

from collections.abc import Iterator

import ollama


class OllamaError(RuntimeError):
    """Raised with a human-friendly, actionable message."""


class OllamaClient:
    def __init__(self, host: str, embed_model: str, chat_model: str):
        self.host = host
        self.embed_model = embed_model
        self.chat_model = chat_model
        self._client = ollama.Client(host=host)

    # -- health -----------------------------------------------------------

    def check_ready(self, need_chat: bool) -> None:
        """Verify the server is up and required models are pulled.

        Raises OllamaError with exact terminal commands to run on failure.
        `need_chat` is False for chunks-only mode (no chat model required).
        """
        try:
            installed = {m.model for m in self._client.list().models}
        except Exception:
            raise OllamaError(
                "Can't reach Ollama at "
                f"{self.host}.\n\n"
                "Start it in another terminal, then re-run this tool:\n\n"
                "    ollama serve\n"
            )

        required = [self.embed_model] + ([self.chat_model] if need_chat else [])
        missing = [m for m in required if not _has_model(installed, m)]
        if missing:
            pulls = "\n".join(f"    ollama pull {m}" for m in missing)
            raise OllamaError(
                f"Ollama is running, but these models aren't pulled yet: "
                f"{', '.join(missing)}.\n\n"
                f"Pull them, then re-run this tool:\n\n{pulls}\n"
            )

    # -- embeddings -------------------------------------------------------

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, returning one vector per input."""
        resp = self._client.embed(model=self.embed_model, input=texts)
        return list(resp.embeddings)

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    # -- chat (RAG) -------------------------------------------------------

    def chat_stream(self, system: str, user: str) -> Iterator[str]:
        """Stream a chat response token-by-token."""
        stream = self._client.chat(
            model=self.chat_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Low temperature keeps factual recall grounded and consistent
            # rather than creative — this is retrieval, not brainstorming.
            options={"temperature": 0.2},
            stream=True,
        )
        for part in stream:
            chunk = part.get("message", {}).get("content", "")
            if chunk:
                yield chunk


def _has_model(installed: set[str], wanted: str) -> bool:
    """Match a model name, tolerating the implicit ':latest' tag."""
    if wanted in installed:
        return True
    if ":" not in wanted and f"{wanted}:latest" in installed:
        return True
    return False
