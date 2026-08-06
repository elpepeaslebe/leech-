# Leech

An OpenAI-compatible gateway over **use.ai** free web models with a file-editing
agent and 28 CLI-style tools. It signs up throwaway accounts on demand (kept warm
in a pool) and streams replies over use.ai's WebSocket, so any current model is
reachable through a plain HTTP API.

## Features

- **28 tools**: file ops, search, edit, directory, system, web
- **Native file edit**: model can output code blocks, `[EDIT:]` blocks, or
  `<<<<<<< SEARCH` diffs — all auto-detected and applied
- **Effort control**: low/medium/high — injected as system prompt
- **Parallel tool execution**: multiple tools per message
- **API key auth** on `/v1/*` and `/agent` endpoints
- **OpenAI tool calling support**: `tools` parameter accepted
- **Auto account pool**: creates accounts via free HTTP proxies

## Models

GPT-5.6 (Sol/Terra/Luna), GPT-5.5, Claude Opus 4.6–4.8, Sonnet 5/4.6,
Gemini 3.1 Pro/3 Pro, DeepSeek V4/R1, Grok 4/4.3, Qwen, Kimi, Llama, GLM.
See `worker/config.py` for the full list.

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/versus4/leech.git
cd leech
pip install -r requirements.txt
```

### 2. Create your API key

```bash
# Linux/Mac
cp config/api_keys.example.json config/api_keys.json

# Windows
copy config\api_keys.example.json config\api_keys.json
```

Edit `config/api_keys.json` and replace the placeholder with your own key:
```json
{
  "keys": [
    {
      "key": "leech-sk-YOUR_SECRET_KEY_HERE",
      "name": "Your Name",
      "created": "2026-01-01",
      "active": true
    }
  ]
}
```

**Use any string you want as the API key** — it's just a password for your instance.

### 3. Start the backend

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

On first run, the backend automatically signs up accounts and fills the pool.
If your IP is blocked by use.ai, run the proxy fetcher first:

```bash
python -m worker.proxy_sources 500
```

### 4. (Optional) Start the frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs on `http://localhost:5173` and proxies API calls to the backend.

## API

All `/v1/*` and `/agent` endpoints require an API key via:
- Header: `Authorization: Bearer leech-sk-YOUR_KEY`
- Query param: `?api_key=leech-sk-YOUR_KEY`

### Agent — run a file task

```bash
curl -X POST localhost:8000/agent \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer leech-sk-YOUR_KEY' \
  -d '{"message": "read config.py", "model": "gpt-5-6-sol"}'
```

### Chat — OpenAI-compatible

```bash
curl -X POST localhost:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer leech-sk-YOUR_KEY' \
  -d '{"model": "gpt-5-6-sol", "messages": [{"role": "user", "content": "hi"}]}'
```

### Other endpoints

| endpoint | method | description |
|----------|--------|-------------|
| `/health` | GET | backend status + pool size |
| `/models` | GET | available models |
| `/bank` | GET | warm account count |
| `/chat` | POST | stateful chat (frontend, no auth) |
| `/v1/chat` | POST | stateless chat (no auth needed) |

### Effort control

Add `"effort": "low"` | `"medium"` | `"high"` to any request body.

## Tools (28)

### File Operations
| tool | description |
|------|-------------|
| `read_file` | read file with line numbers |
| `write_file` | create/overwrite file |
| `append_file` | add to end of file |
| `edit_file` | replace exact text (fuzzy) |
| `delete_file` | delete file or folder |
| `move_file` | move/rename |
| `copy_file` | copy file/folder |
| `make_dir` | create directory |

### View
| tool | description |
|------|-------------|
| `list_dir` | directory tree |
| `file_info` | file metadata |
| `read_lines` | read specific lines |
| `search_in_file` | find in file |
| `count_lines` | line/word count |
| `head_file` / `tail_file` | first/last N lines |

### Search
| tool | description |
|------|-------------|
| `grep_search` | regex content search |
| `glob_files` | find by name pattern |
| `find_files` | find by extension |
| `search_files` | combined name+content |

### Edit
| tool | description |
|------|-------------|
| `replace_in_file` | sed-style replace |
| `insert_in_file` | insert at line |
| `patch_file` | apply line ranges |
| `format_code` | reformat with black |

### Directory
| tool | description |
|------|-------------|
| `tree_view` | full tree with sizes |
| `disk_usage` | folder sizes |

### System
| tool | description |
|------|-------------|
| `run_command` | shell command with output |

### Web / Image
| tool | description |
|------|-------------|
| `web_search` | search the web |
| `image_gen` | generate image |

## Layout

```
backend/      FastAPI app + endpoints
worker/       use.ai gateway, account pool, agent, tools, config
frontend/     optional chat UI (Vite)
config/       API keys (gitignored)
```

## Sensitive Data

The following are **gitignored** and never committed:

- `config/api_keys.json` — your API keys
- `proxy_cache.json` — cached proxies
- `proxies.txt` — live proxy list
- `bank/` — account database
- `tor_data/` — Tor configuration

Use `config/api_keys.example.json` as a template.

## License

MIT — see [LICENSE](LICENSE).
