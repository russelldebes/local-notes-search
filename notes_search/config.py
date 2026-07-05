"""Configuration loading.

Resolution order (later wins):
  1. Built-in defaults below.
  2. `config.toml` in the repo root, if present.
  3. The `NOTES_VAULT_PATH` environment variable (vault path only).
  4. Command-line flags passed by the CLI.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Repo root = parent of the `notes_search` package directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = REPO_ROOT / "config.toml"


@dataclass
class Config:
    vault_path: Path
    index_dir: Path
    max_chars: int = 1000
    overlap_chars: int = 150
    ollama_host: str = "http://localhost:11434"
    embed_model: str = "nomic-embed-text"
    chat_model: str = "qwen2.5:7b"
    top_k: int = 6
    # How many recent Q&A turns to remember in answer mode. 0 disables
    # conversational memory (each question stays fully independent).
    history_turns: int = 6


def _expand(path: str) -> Path:
    return Path(path).expanduser()


def load_config(vault_override: str | None = None) -> Config:
    """Build a Config from config.toml + env + an optional CLI override.

    Raises FileNotFoundError-style ValueError if no vault path can be found,
    so the CLI can print friendly setup guidance.
    """
    data: dict = {}
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("rb") as fh:
            data = tomllib.load(fh)

    vault = data.get("vault", {})
    index = data.get("index", {})
    chunking = data.get("chunking", {})
    ollama = data.get("ollama", {})
    search = data.get("search", {})
    chat = data.get("chat", {})

    # Vault path: CLI flag > env var > config file.
    vault_raw = vault_override or os.environ.get("NOTES_VAULT_PATH") or vault.get("path")
    if not vault_raw:
        raise ValueError(
            "No vault path configured. Copy config.example.toml to config.toml and "
            "set [vault] path, set the NOTES_VAULT_PATH env var, or pass --vault PATH."
        )

    index_dir_raw = index.get("dir", ".notes_index")
    index_dir = _expand(index_dir_raw)
    if not index_dir.is_absolute():
        index_dir = REPO_ROOT / index_dir_raw

    return Config(
        vault_path=_expand(vault_raw),
        index_dir=index_dir,
        max_chars=int(chunking.get("max_chars", 1000)),
        overlap_chars=int(chunking.get("overlap_chars", 150)),
        ollama_host=ollama.get("host", "http://localhost:11434"),
        embed_model=ollama.get("embed_model", "nomic-embed-text"),
        chat_model=ollama.get("chat_model", "qwen2.5:7b"),
        top_k=int(search.get("top_k", 6)),
        history_turns=int(chat.get("history_turns", 6)),
    )
