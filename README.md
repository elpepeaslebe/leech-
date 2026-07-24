# leech

A small OpenAI-compatible gateway over the **use.ai** free web models, plus a
minimal file-editing **agent** that works reliably even on models that struggle
with tool calls.

It signs up throwaway accounts on demand (kept warm in a pool) and streams
replies over use.ai's WebSocket, so any of the current models are reachable
through a plain HTTP API.

## Models

The current use.ai catalog — GPT-5.6 (Sol / Terra / Luna), GPT-5.5, Claude Opus
4.6–4.8, Sonnet 5 / 4.6, Gemini 3.1 Pro / 3 Pro, DeepSeek V4 / R1, Grok 4 / 4.3,
Qwen, Kimi, Llama, GLM. See `worker/config.py` for the full list. Default:
`gpt-5-6-sol`.

## The agent's tools

The agent runs in a `workspace/` folder (override with `LEECH_WORKDIR`) and has
six file tools:

| tool | what it does |
|------|--------------|
| `read_file`   | read a file (with line numbers) |
| `write_file`  | create or overwrite a file |
| `append_file` | add to the end of a file |
| `edit_file`   | replace exact text (fuzzy-tolerant) |
| `delete_file` | delete a file or folder |
| `list_dir`    | list the workspace as a tree |
| `grep_search` | search file contents (regex), returns `file:line` matches |
| `move_file`   | move or rename a file/folder |
| `copy_file`   | copy a file/folder |
| `make_dir`    | create a directory |
| `glob_files`  | find files by name pattern (`**/*.py`) |
| `run_command` | run a shell command in the workspace, capture output |

Common phrasings run **deterministically** — the app performs the action itself
without the model emitting a tool call, so they work on every model:

- `read config.py`
- `create note.txt with 'hello'`
- `list files`
- `in config.py the port should be 8080`
- `in config.py replace HOST with localhost`
- `append the line beta to notes.txt`
- `delete old.log`
- `search for TODO in the project`
- `rename a.py to b.py`
- `make a directory src`
- `find files named config.json`
- `run npm test`

Freeform edits (`change the greeting to say Bob`) are applied by reading the
file, having the model rewrite it in one shot, and writing the result back —
which is far more reliable on the free gateway than asking the model to hand-write
a tool call. Anything else falls back to a normal tool loop (with JSON repair and
code-block harvesting as safety nets).

## Run it

```bash
pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

## API

**Agent** — run a file task:

```bash
curl -X POST localhost:8000/agent \
  -H 'content-type: application/json' \
  -d '{"message": "in config.py the port should be 8080", "model": "gpt-5-6-sol"}'
```

Returns `{"text": "...", "events": [{"type": "tool", "name": "edit_file", ...}]}`.

**Chat** — OpenAI-compatible, drop-in for existing SDK clients:

```bash
curl -X POST localhost:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model": "gpt-5-6-sol", "messages": [{"role": "user", "content": "hi"}]}'
```

Other endpoints: `GET /models`, `GET /health`, `GET /bank` (warm-account count),
`POST /chat` (stateful), `POST /v1/chat` (stateless).

## Layout

```
backend/   FastAPI app + endpoints
worker/    use.ai gateway (direct.py), account pool, agent, tools, config
frontend/  optional chat UI (Vite)
```

## License

MIT — see [LICENSE](LICENSE).
