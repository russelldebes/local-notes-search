# AGENTS.md

Guidance for AI coding agents (and humans) working on this repo.

## What this is

`local-notes-search` is a local-first CLI for semantic search and RAG over a
folder of Markdown notes (built for an Obsidian vault). Everything runs on the
user's machine — notes never leave it.

- **Language / runtime:** Python ≥ 3.11, managed by [`uv`](https://docs.astral.sh/uv/).
- **Models:** served by a local [Ollama](https://ollama.com) instance.
  `nomic-embed-text` for embeddings, `llama3.2:3b` for RAG answers (configurable).
- **Vector store:** [LanceDB](https://lancedb.com) — embedded, file-based, no server.
- **Change tracking:** plain stdlib `sqlite3` manifest (content hashes). No
  loadable SQLite extensions are used (system Python disables them), so it works
  everywhere — this is *why* we use LanceDB instead of `sqlite-vec`.
- **Output / UX:** `rich` for the terminal REPL.

## Architecture

The flow: notes → chunk → embed → LanceDB; a query is embedded, similarity-
searched, then either shown as ranked passages or fed to the LLM for a cited answer.

| File | Responsibility |
|------|----------------|
| `notes_search/config.py` | Config resolution: defaults ← `config.toml` ← `NOTES_VAULT_PATH` env ← `--vault` flag |
| `notes_search/ollama_client.py` | Ollama wrapper: health check (friendly fix commands), embed, streaming chat |
| `notes_search/chunker.py` | Markdown-aware chunking: strip frontmatter, track heading breadcrumbs, overlapping windows, prepend title+breadcrumb to each chunk |
| `notes_search/store.py` | Persistence: LanceDB vectors + sqlite `files` manifest |
| `notes_search/indexer.py` | Incremental reindex: hash files, (re)embed new/changed, purge deleted |
| `notes_search/rag.py` | RAG system + user prompt construction |
| `notes_search/cli.py` | REPL, slash commands, arg parsing, entry point (`main`) |

## Running & developing

```bash
uv sync                              # install deps
uv run notes-search                  # index changed notes, then REPL
uv run notes-search --reindex-only   # index and exit (no prompt)
uv run notes-search --vault PATH     # override the configured vault
```

REPL commands: `/answer` (default, RAG), `/chunks` (raw passages), `/reindex`,
`/stats`, `/help`, `/quit`.

Syntax-check without the deps installed: `python3 -m py_compile notes_search/*.py`.

## Conventions

- Keep modules single-purpose; the table above is the contract.
- Ollama failures must stay actionable: surface the exact `ollama serve` /
  `ollama pull <model>` command the user should run, never a raw traceback.
- The startup index only requires the embedding model. The chat model is checked
  *lazily*, only when answer mode is actually used — don't block `/chunks`-only
  users on a model they don't need.
- Change detection is by **content hash**, not mtime. Re-embedding a note must
  first delete its old chunks (`store.delete_chunks(path)`) to avoid duplicates.
- Each chunk is prefixed with its note title + heading breadcrumb before
  embedding; this context materially improves retrieval — preserve it.

## Things that will trip you up

- **`config.toml` and `.notes_index/` are gitignored** — they hold the user's
  personal vault path and embedded notes. Never commit them. Only
  `config.example.toml` ships.
- **Ollama server must be running** (`ollama serve`) before embed/chat calls.
- **Environment PATH (this dev machine):** Homebrew lives at `/opt/homebrew/bin`
  but non-interactive shells may not load it. If `uv`/`ollama` are "command not
  found", prepend `export PATH="/opt/homebrew/bin:$PATH"`.
- LanceDB delete uses a SQL filter string — single quotes in paths are escaped by
  doubling (`store._escape`). Don't switch to naive string interpolation.

## Conversation state: stateless by design (for now)

Each query is fully independent — there is **no conversation memory** between
questions. Every question triggers a fresh retrieval, and `chat_stream` sends only
the system prompt + the current question with its retrieved notes (see
`ollama_client.py` / `cli.py::_run_query`). Nothing from prior turns is carried
forward.

Implication: follow-ups that depend on earlier context don't work — e.g. asking
"How tall is he?" after "What about Russell?" won't resolve "he", and the retrieval
step won't find the right note either.

If you add conversational memory later, do it properly: keeping chat history in the
LLM prompt is not enough, because the **retrieval** step still embeds only the
literal words. A query-rewrite step (expand the follow-up into a standalone
question before embedding) is required, plus a `/clear` command to reset context.
Don't ship history-in-prompt alone — follow-ups will *sound* like they work while
retrieval silently fails.

## Not yet built (open ideas)

Conversational memory (with query-rewrite, per above); one-shot `--query "..."`
non-interactive mode; `.txt`/other extensions alongside `.md`; reranking;
configurable `keep_alive`; tests.
