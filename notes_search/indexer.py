"""Incremental indexing: detect changed notes and (re)embed them."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from .chunker import chunk_note
from .config import Config
from .ollama_client import OllamaClient
from .store import Store


@dataclass
class IndexResult:
    added: int
    changed: int
    removed: int
    unchanged: int


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _scan_vault(vault: Path) -> dict[str, Path]:
    """Map relative-path-string -> absolute Path for every .md file."""
    found: dict[str, Path] = {}
    for p in vault.rglob("*.md"):
        if p.is_file():
            found[str(p.relative_to(vault))] = p
    return found


def reindex(cfg: Config, client: OllamaClient, store: Store, console: Console) -> IndexResult:
    """Bring the index in sync with the vault. Returns a summary of changes."""
    vault = cfg.vault_path
    if not vault.is_dir():
        raise FileNotFoundError(f"Vault path is not a directory: {vault}")

    # Guard against an incompatible embedding-model swap. Vectors from a
    # different model live in a different space, so a change means the whole
    # index must be rebuilt — otherwise search silently returns wrong results.
    stored_model = store.get_meta("embed_model")
    if stored_model is None:
        store.set_meta("embed_model", cfg.embed_model)
    elif stored_model != cfg.embed_model:
        console.print(
            f"[yellow]Embedding model changed "
            f"({stored_model} → {cfg.embed_model}). Rebuilding the index from "
            f"scratch so search stays correct…[/yellow]"
        )
        store.reset_index()
        store.set_meta("embed_model", cfg.embed_model)

    current = _scan_vault(vault)
    known = store.known_hashes()

    # Notes deleted from disk since last run.
    removed = [rel for rel in known if rel not in current]
    for rel in removed:
        store.delete_chunks(rel)
        store.forget_file(rel)

    # Decide which notes need (re)embedding.
    to_embed: list[tuple[str, Path, str, str]] = []  # rel, abs, content, hash
    unchanged = 0
    added = changed = 0
    for rel, abs_path in current.items():
        try:
            content = abs_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            console.print(f"[yellow]Skipping {rel}: {exc}[/yellow]")
            continue
        h = _hash(content)
        if rel not in known:
            added += 1
            to_embed.append((rel, abs_path, content, h))
        elif known[rel] != h:
            changed += 1
            to_embed.append((rel, abs_path, content, h))
        else:
            unchanged += 1

    if to_embed:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total} notes"),
            console=console,
        ) as progress:
            task = progress.add_task("Embedding notes", total=len(to_embed))
            for rel, abs_path, content, h in to_embed:
                title = abs_path.stem
                chunks = chunk_note(title, content, cfg.max_chars, cfg.overlap_chars)
                # Replace any existing chunks for this note (handles edits).
                store.delete_chunks(rel)
                if chunks:
                    vectors = client.embed([c.text for c in chunks])
                    rows = [
                        {
                            "path": rel,
                            "breadcrumb": c.breadcrumb,
                            "chunk_index": c.chunk_index,
                            "text": c.text,
                            "vector": vec,
                        }
                        for c, vec in zip(chunks, vectors)
                    ]
                    store.add_chunks(rows)
                store.record_file(rel, h, abs_path.stat().st_mtime, len(chunks))
                progress.advance(task)

    return IndexResult(added=added, changed=changed, removed=len(removed), unchanged=unchanged)
