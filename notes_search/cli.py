"""Interactive CLI.

Flow on launch:
  1. Load config, connect the store.
  2. Check Ollama is up and required models are pulled (friendly errors).
  3. Auto-reindex any new/changed notes.
  4. Drop into a REPL. Type a question to search.

Modes:
  * answer (default) — RAG: retrieve chunks, stream a synthesized answer.
  * chunks           — show the raw ranked passages with scores + sources.

Slash commands:
  /answer   switch to RAG answer mode
  /chunks   switch to ranked-chunks mode
  /reindex  rescan the vault for changes
  /stats    show how many notes/chunks are indexed
  /help     list commands
  /quit     exit (Ctrl-C or Ctrl-D also work)
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .config import Config, load_config
from .indexer import reindex
from .ollama_client import OllamaClient, OllamaError
from .rag import (
    REWRITE_SYSTEM_PROMPT,
    build_rewrite_prompt,
    build_system_prompt,
    build_user_prompt,
)
from .store import Store

console = Console()

HELP = """\
[bold]Commands[/bold]
  [cyan]/answer[/cyan]   generated answer mode (RAG) — the default
  [cyan]/chunks[/cyan]   show raw ranked passages instead of an answer
  [cyan]/clear[/cyan]    forget the current conversation (start a fresh topic)
  [cyan]/reindex[/cyan]  rescan your vault for new or changed notes
  [cyan]/stats[/cyan]    show how many notes and chunks are indexed
  [cyan]/help[/cyan]     show this help
  [cyan]/quit[/cyan]     exit

In answer mode, follow-up questions remember the conversation, so you can ask
things like "how tall is he?" after asking about someone. Use /clear to reset.
Chunks mode is a plain, stateless search. Type anything else to search."""


def _run_query(
    cfg: Config,
    client: OllamaClient,
    store: Store,
    mode: str,
    question: str,
    history: list[dict],
) -> None:
    # In answer mode, resolve conversational follow-ups ("how tall is he?")
    # into a standalone query BEFORE embedding — otherwise retrieval, which
    # only sees the literal words, would miss the right notes.
    search_query = question
    if mode == "answer" and cfg.history_turns > 0 and history:
        recent = history[-cfg.history_turns * 2:]
        rewritten = client.rewrite_query(
            REWRITE_SYSTEM_PROMPT, build_rewrite_prompt(recent, question)
        )
        if rewritten and rewritten.lower() != question.lower():
            search_query = rewritten
            console.print(f"[dim]↳ interpreting as: {search_query}[/dim]")

    hits = store.search(client.embed_one(search_query), cfg.top_k)
    if not hits:
        console.print("[yellow]No matches. Have you indexed any notes? Try /reindex.[/yellow]")
        return

    if mode == "chunks":
        for i, hit in enumerate(hits, start=1):
            loc = hit.path + (f"  ›  {hit.breadcrumb}" if hit.breadcrumb else "")
            console.print(
                Panel(
                    hit.text,
                    title=f"[bold]{i}. {loc}[/bold]",
                    subtitle=f"score {hit.score:.3f}",
                    border_style="cyan",
                )
            )
        return

    # answer mode (RAG). Feed the standalone query as the question (unambiguous
    # for a small model) plus recent turns for conversational continuity.
    user_prompt = build_user_prompt(search_query, hits)
    recent_history = history[-cfg.history_turns * 2:] if cfg.history_turns > 0 else []
    console.print("[dim]thinking…[/dim]")
    parts: list[str] = []
    system_prompt = build_system_prompt(cfg.conventions)
    for token in client.chat_stream(system_prompt, user_prompt, history=recent_history):
        parts.append(token)
        console.print(token, end="")
    console.print()  # newline after stream
    sources = sorted({h.path for h in hits})
    console.print(f"\n[dim]Sources: {', '.join(sources)}[/dim]")

    # Record the turn (store what the user actually typed, not the rewrite).
    if cfg.history_turns > 0:
        answer = "".join(parts).strip()
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})


def _repl(cfg: Config, client: OllamaClient, store: Store) -> None:
    mode = "answer"
    history: list[dict] = []  # conversation turns for answer mode
    console.print(
        Panel.fit(
            "Ask a question about your notes. [dim]Type /help for commands, /quit to exit.[/dim]",
            title="local-notes-search",
            border_style="green",
        )
    )
    while True:
        try:
            line = console.input(f"\n[bold green]({mode})[/bold green] › ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye[/dim]")
            return

        if not line:
            continue

        if line.startswith("/"):
            cmd = line[1:].split()[0].lower()
            if cmd in ("quit", "exit", "q"):
                console.print("[dim]bye[/dim]")
                return
            elif cmd == "help":
                console.print(HELP)
            elif cmd == "answer":
                mode = "answer"
                console.print("[green]→ answer mode (RAG)[/green]")
            elif cmd == "chunks":
                mode = "chunks"
                console.print("[green]→ chunks mode (raw passages)[/green]")
            elif cmd == "clear":
                history.clear()
                console.print("[green]Conversation cleared.[/green]")
            elif cmd == "reindex":
                _reindex(cfg, client, store, need_chat=False)
            elif cmd == "stats":
                files, chunks = store.stats()
                console.print(f"[cyan]{files} notes, {chunks} chunks indexed.[/cyan]")
            else:
                console.print(f"[yellow]Unknown command: /{cmd}. Try /help.[/yellow]")
            continue

        # RAG (answer) mode needs the chat model; verify lazily so chunks-only
        # users never get blocked on a model they don't use.
        if mode == "answer":
            try:
                client.check_ready(need_chat=True)
            except OllamaError as exc:
                console.print(f"[red]{exc}[/red]")
                continue

        try:
            _run_query(cfg, client, store, mode, line, history)
        except Exception as exc:  # keep the REPL alive on per-query errors
            console.print(f"[red]Query failed: {exc}[/red]")


def _reindex(cfg: Config, client: OllamaClient, store: Store, need_chat: bool) -> None:
    try:
        client.check_ready(need_chat=need_chat)
    except OllamaError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    result = reindex(cfg, client, store, console)
    console.print(
        f"[green]Index up to date.[/green] "
        f"+{result.added} new, ~{result.changed} changed, "
        f"-{result.removed} removed, {result.unchanged} unchanged."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="notes-search",
        description="Semantic search and RAG over your local Markdown notes.",
    )
    parser.add_argument("--vault", help="Path to your notes folder (overrides config).")
    parser.add_argument(
        "--reindex-only",
        action="store_true",
        help="Index changed notes and exit without entering the prompt.",
    )
    args = parser.parse_args()

    try:
        cfg = load_config(vault_override=args.vault)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)

    if not cfg.vault_path.is_dir():
        console.print(f"[red]Vault path is not a directory: {cfg.vault_path}[/red]")
        sys.exit(1)

    client = OllamaClient(cfg.ollama_host, cfg.embed_model, cfg.chat_model)
    store = Store(cfg.index_dir)

    try:
        # Startup index only needs the embedding model.
        _reindex(cfg, client, store, need_chat=False)
        if args.reindex_only:
            return
        _repl(cfg, client, store)
    finally:
        store.close()


if __name__ == "__main__":
    main()
