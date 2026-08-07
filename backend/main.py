"""
FastAPI orchestrator.
  GET  /                    -> chatbox frontend
  GET  /models              -> model list for the dropdown
  GET  /bank                -> bank status (how many warm accounts ready)
  POST /chat                -> stateful chat (we hold context), streams reply
  POST /v1/chat             -> stateless, simple OpenAI-ish
  POST /v1/chat/completions -> OpenAI-compatible (drop-in for OpenAI SDK clients)

On startup a background loop keeps the account bank topped up so signup stays
out of the hot path.
"""
import asyncio
import json
import logging
import re
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from worker import config, health
from worker.account_pool import POOL
from worker.leech import run_messages
from . import context
from .pool import run_guarded

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("backend")
app = FastAPI(title="WMan")

# ---- API Key Auth -----------------------------------------------------------
API_KEYS_PATH = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
_bearer = HTTPBearer(auto_error=False)

def _load_api_keys() -> dict:
    """Load API keys from config file."""
    if not API_KEYS_PATH.exists():
        return {}
    try:
        data = json.loads(API_KEYS_PATH.read_text(encoding="utf-8"))
        return {k["key"]: k for k in data.get("keys", []) if k.get("active", True)}
    except Exception:
        return {}

_API_KEYS = _load_api_keys()

def _get_client_key(request: Request) -> str | None:
    """Extract API key from request (Bearer header or query param)."""
    # Check Authorization header
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    # Check query param
    return request.query_params.get("api_key")


async def require_api_key(request: Request):
    """Dependency: require valid API key on /v1/ endpoints."""
    key = _get_client_key(request)
    if not key or key not in _API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return _API_KEYS[key]


def _no_auth(request: Request):
    """No auth required (for /chat and / frontend)."""
    return None


# The /v1 endpoints are meant to be hit from other origins ("people build it
# themselves"), so allow cross-origin calls. The bundled frontend is same-origin
# (served from /) or uses the Vite dev proxy, so this only matters for API clients.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"

if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.on_event("startup")
async def _start_prewarmer():
    from worker.free_proxy_pool import start_background_refresh
    POOL.start()
    start_background_refresh()
    log.info("account pool started (target=%d)", POOL.size)


# --- pages / status ----------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    if FRONTEND_INDEX.exists():
        return FRONTEND_INDEX.read_text(encoding="utf-8")
    return """
    <!doctype html>
    <html lang="en">
      <head><meta charset="utf-8"><title>WMan frontend not built</title></head>
      <body style="font-family: system-ui; max-width: 720px; margin: 48px auto; line-height: 1.5;">
        <h1>Frontend build missing</h1>
        <p>Run these commands from <code>leech\\frontend</code>, then restart the backend:</p>
        <pre>npm install
npm run build</pre>
        <p>For live React development, run <code>npm run dev</code> and open
        <code>http://localhost:5173</code>.</p>
      </body>
    </html>
    """


@app.get("/models")
async def models():
    return {"models": config.MODELS, "default": config.DEFAULT_MODEL}


@app.get("/bank")
async def bank_status():
    snap = health.H.snapshot(POOL.ready())
    return {
        "mode": "headless-ws",
        "warm_accounts": POOL.ready(),
        "pool_target": POOL.size,
        "status": snap["status"],
        "reasons": snap["reasons"],
    }


@app.get("/health")
async def health_status():
    """Full watchdog readout: status, why, rates, counters, recent errors."""
    snap = health.H.snapshot(POOL.ready())
    snap["warm_accounts"] = POOL.ready()
    snap["pool_target"] = POOL.size
    return snap


# --- stateful chat (frontend) ------------------------------------------------
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
IMAGE_URL_RE = re.compile(
    r"(https?://[^\s<>()\"]+(?:\.(?:png|jpe?g|webp|gif|avif)(?:\?[^\s<>()\"]*)?"
    r"|/[^\s<>()\"]*(?:image|img|generated|output)[^\s<>()\"]*)"
    r"|data:image/[a-zA-Z+.-]+;base64,[a-zA-Z0-9+/=]+)",
    re.IGNORECASE,
)


def _sse_payload(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _sse(token: str) -> str:
    return _sse_payload({"type": "token", "token": token})


def _extract_image(reply: str) -> dict | None:
    markdown = MARKDOWN_IMAGE_RE.search(reply)
    if markdown:
        caption = (reply[:markdown.start()] + reply[markdown.end():]).strip()
        return {
            "url": markdown.group(2),
            "alt": markdown.group(1) or "Generated image",
            "caption": caption,
        }

    direct_url = IMAGE_URL_RE.search(reply)
    if direct_url:
        caption = (reply[:direct_url.start()] + reply[direct_url.end():]).strip()
        return {
            "url": direct_url.group(1),
            "alt": "Generated image",
            "caption": caption,
        }

    return None


async def _stream_text(text: str):
    for i in range(0, len(text), 8):
        yield _sse(text[i:i + 8])
        await asyncio.sleep(0.01)
    yield "data: [DONE]\n\n"


async def _stream_reply(reply: str):
    image = _extract_image(reply)
    if not image:
        async for chunk in _stream_text(reply):
            yield chunk
        return

    caption = image.get("caption") or ""
    if caption:
        for i in range(0, len(caption), 8):
            yield _sse(caption[i:i + 8])
            await asyncio.sleep(0.01)
    yield _sse_payload({"type": "image", "image": image})
    yield "data: [DONE]\n\n"


def _stream_tool_event(event: dict) -> str | None:
    """Convert a tool_stream event to an SSE string, or None to skip."""
    kind = event.get("type")
    if kind == "token":
        return _sse(event["token"])
    elif kind == "tool_call":
        return _sse_payload({"type": "tool_call", "name": event["name"], "args": event["args"]})
    elif kind == "tool_result":
        return _sse_payload({"type": "tool_result", "name": event["name"], "result": event["result"]})
    return None


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    message = body.get("message", "")
    model = body.get("model", "default")
    effort = body.get("effort", "medium")
    thinking = body.get("thinking", False)
    session_id = body.get("sessionId") or str(uuid.uuid4())

    messages = context.build_messages(session_id, message)   # role-tagged history + new turn
    context.append(session_id, "user", message)

    async def gen():
        from worker.tool_stream import stream_with_tools
        parts: list[str] = []
        try:
            async for event in stream_with_tools(model, messages, effort=effort, thinking=thinking):
                sse = _stream_tool_event(event)
                if sse:
                    yield sse
                if event["type"] == "token":
                    parts.append(event["token"])
        except Exception as exc:
            log.warning("chat stream failed: %s: %s", type(exc).__name__, exc)
            if not parts:
                yield _sse(f"Backend error contacting the model runner ({type(exc).__name__}).")
        reply = "".join(parts).strip()
        context.append(session_id, "assistant", reply)   # full reply -> multi-turn memory
        image = _extract_image(reply)
        if image:
            yield _sse_payload({"type": "image", "image": image})
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# --- stateless: simple -------------------------------------------------------
@app.post("/v1/chat")
async def v1_chat(req: Request, _key=Depends(require_api_key)):
    body = await req.json()
    model = body.get("model", "default")
    reply = await run_guarded(lambda: run_messages(model, body.get("messages", [])))
    return JSONResponse({
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": reply}}],
    })


@app.post("/agent")
async def agent_run(req: Request, _key=Depends(require_api_key)):
    from worker.tool_stream import complete_with_tools
    body = await req.json()
    message = body.get("message") or body.get("prompt") or ""
    model = body.get("model", "default")
    effort = body.get("effort", "medium")
    thinking = body.get("thinking", False)
    messages = [{"role": "user", "content": message}]
    result = await run_guarded(lambda: complete_with_tools(model, messages, effort=effort, thinking=thinking))
    return JSONResponse({"text": result, "events": []})


# --- stateless: OpenAI-compatible -------------------------------------------
def _openai_block(reply: str, model: str) -> dict:
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:24],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": reply},
            "finish_reason": "stop",
        }],
    }


@app.post("/v1/chat/completions")
async def openai_completions(req: Request, _key=Depends(require_api_key)):
    body = await req.json()
    model = body.get("model", "default")
    stream = bool(body.get("stream", False))
    msgs = body.get("messages", [])
    has_tools = bool(body.get("tools"))
    effort = body.get("effort", "medium")
    thinking = body.get("thinking", False)

    if stream:
        from worker.tool_stream import stream_with_tools
        cid = "chatcmpl-" + uuid.uuid4().hex[:24]
        created = int(time.time())

        async def gen():
            base = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model}
            async for event in stream_with_tools(model, msgs, effort=effort, has_openai_tools=has_tools, thinking=thinking):
                if event["type"] == "token":
                    chunk = {**base, "choices": [{"index": 0, "delta": {"content": event["token"]},
                                                  "finish_reason": None}]}
                    yield f"data: {json.dumps(chunk)}\n\n"
                elif event["type"] == "tool_call" and has_tools:
                    tc_chunk = {
                        **base,
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "tool_calls": [{
                                    "index": 0,
                                    "id": "call_" + uuid.uuid4().hex[:16],
                                    "type": "function",
                                    "function": {
                                        "name": event["name"],
                                        "arguments": json.dumps(event["args"]),
                                    }
                                }]
                            },
                            "finish_reason": None,
                        }]
                    }
                    yield f"data: {json.dumps(tc_chunk)}\n\n"
                elif event["type"] == "tool_result" and has_tools:
                    result_chunk = {
                        **base,
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "role": "tool",
                                "tool_call_id": "call_" + uuid.uuid4().hex[:16],
                                "content": event["result"],
                            },
                            "finish_reason": None,
                        }]
                    }
                    yield f"data: {json.dumps(result_chunk)}\n\n"
            done = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            yield f"data: {json.dumps(done)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    from worker.tool_stream import complete_with_tools
    reply = await run_guarded(lambda: complete_with_tools(model, msgs, effort=effort, has_openai_tools=has_tools, thinking=thinking))
    return JSONResponse(_openai_block(reply, model))
