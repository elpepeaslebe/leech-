"""
Tool-aware streaming layer — NATIVE FILE EDIT.

Supports multiple edit formats that models naturally output:
  1. <tool>JSON</tool> — explicit tool calls
  2. ```filepath\ncontent``` — code blocks with file paths (auto-write)
  3. <<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE — diff-style edits
  4. [EDIT: path]\nold\n---\nnew — simple edit blocks

All formats get auto-detected and applied. The model doesn't need to
learn any special syntax — just output code or edits naturally.
"""
import asyncio
import json
import re
import os

from .tools import TOOLS

# ---------------------------------------------------------------------------
# Patterns for native edit detection
# ---------------------------------------------------------------------------

# Explicit tool call: <tool>{"name":"write_file","args":{...}}</tool>
_TOOL_TAG = re.compile(r"<tool>\s*(\{.*?\})\s*</tool>", re.DOTALL)

# Code block with file path: ```path/to/file.py\ncontent```
# The first line after ``` is treated as the file path if it looks like a path
_CODE_BLOCK = re.compile(
    r"```([^\s\n]*)\s*\n(.*?)```",
    re.DOTALL
)

# Diff-style: <<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE
_DIFF_EDIT = re.compile(
    r"<<<<<<<\s*SEARCH\s*\n(.*?)=======\s*\n(.*?)>>>>>>>",
    re.DOTALL
)

# Simple edit: [EDIT: path]\nold\n---\nnew
_SIMPLE_EDIT = re.compile(
    r"\[EDIT:\s*(.+?)\]\s*\n(.*?)---\s*\n(.*)",
    re.DOTALL
)

# Write block: [FILE: path]\ncontent
_WRITE_BLOCK = re.compile(
    r"\[FILE:\s*(.+?)\]\s*\n(.*)",
    re.DOTALL
)

_MAX_TOOL_STEPS = 8
_MAX_PARALLEL_TOOLS = 6
_WORKDIR = None


def _get_workdir():
    global _WORKDIR
    if _WORKDIR is None:
        from .tools import WORKDIR
        _WORKDIR = WORKDIR
    return _WORKDIR


# ---------------------------------------------------------------------------
# Tool docs — tells the model about native edit formats
# ---------------------------------------------------------------------------
TOOL_DOCS = (
    "You are a powerful coding agent with FULL file system access. You can read, write, edit, "
    "and manage files just like official AI assistants (Claude, GPT). You have REAL tools that "
    "execute on disk.\n\n"
    "## How to use tools\n"
    "Output a tool call in this format:\n"
    '<tool>{"name":"tool_name","args":{...}}</tool>\n\n'
    "Or use NATIVE formats (auto-detected):\n"
    "1. CODE BLOCKS: ```path/to/file.py\n<content>\n``` (overwrites file)\n"
    "2. EDIT BLOCKS: [EDIT: path]\nold\n---\nnew\n"
    "3. DIFF STYLE: <<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE\n\n"
    "## Available Tools (28 total)\n\n"
    "### File Operations\n"
    "read_file(path) - Read file content with line numbers\n"
    "write_file(path, content) - Write/create file\n"
    "append_file(path, content) - Append to file\n"
    "edit_file(path, old_string, new_string, replace_all?) - Edit file\n"
    "delete_file(path) - Delete file or directory\n"
    "move_file(path, new_path) - Move/rename file\n"
    "copy_file(path, new_path) - Copy file/directory\n"
    "make_dir(path) - Create directory\n"
    "touch_file(path) - Create empty file or update timestamp\n\n"
    "### View & Inspect\n"
    "list_dir(path?, depth?) - List directory contents\n"
    "tree_view(path?, depth?) - Directory tree visualization\n"
    "file_info(path) - File metadata (size, dates, type)\n"
    "file_count(path) - Count lines, words, characters\n"
    "head_file(path, lines?) - Show first N lines\n"
    "tail_file(path, lines?) - Show last N lines\n"
    "read_lines(path, start?, end?) - Read specific line range\n"
    "word_count(path) - Count words per line\n\n"
    "### Search & Find\n"
    "glob_files(pattern, path?) - Find files by pattern\n"
    "find_files(name?, ext?, path?) - Find files by name/extension\n"
    "grep_search(pattern, path?) - Search file contents (regex)\n"
    "diff_files(path1, path2) - Compare two files\n\n"
    "### Edit Helpers\n"
    "search_replace(path, old, new) - Simple string replace\n"
    "replace_in_file(path, pattern, replacement) - Regex replace\n"
    "sort_file(path, reverse?, unique?) - Sort file lines\n"
    "unique_lines(path) - Remove duplicate lines\n\n"
    "### System\n"
    "run_command(command, timeout?) - Execute shell command\n\n"
    "### External\n"
    "web_search(query) - Search the web (quick results)\n"
    "web_search_detailed(query) - Search with full snippets (research)\n"
    "image_generate(prompt) - Generate image URL\n\n"
    "## Rules\n"
    "- You CAN access and edit files. Never say you cannot.\n"
    "- Use tools to fulfill requests. Read files before editing.\n"
    "- You can combine multiple tool calls in one message.\n"
    "- When done, reply in plain text with a short summary."
)

EFFORT_PROMPTS = {
    "low":    "\n\n[EFFORT: LOW] Fast and concise. Edit files directly, no explanation.",
    "medium": "\n\n[EFFORT: MEDIUM] Balanced. Show key changes, explain briefly.",
    "high":   "\n\n[EFFORT: HIGH] Think carefully. Consider edge cases. Explain your approach.",
}

THINKING_PROMPT = (
    "\n\n## Thinking Mode\n"
    "When thinking mode is enabled, show your reasoning process inside <thinking> tags:\n"
    "<thinking>\n"
    "Your step-by-step reasoning here...\n"
    "</thinking>\n\n"
    "Then provide your final answer or action outside the tags.\n"
    "This helps users understand your thought process."
)

# OpenAI-compatible tool calling format
OPENAI_TOOL_PROMPT = (
    "\n\n## OpenAI Tool Calling Format\n"
    "When the client sends tools in OpenAI format, you can call them by outputting:\n"
    '<tool>{"name":"tool_name","args":{...}}</tool>\n\n'
    "Available tools are listed above. Use the exact tool names and argument formats.\n"
    "You can make multiple tool calls in one response."
)


# ---------------------------------------------------------------------------
# Parse native edit formats
# ---------------------------------------------------------------------------

def _parse_native_edits(text: str) -> list[dict]:
    """Detect all edit formats in the model output."""
    edits = []
    seen_files = set()

    # 1. Explicit <tool> tags
    for m in _TOOL_TAG.finditer(text):
        raw = m.group(1)
        obj = _try_parse_json(raw)
        if obj and obj.get("name") in TOOLS:
            edits.append({
                "type": "tool",
                "name": obj["name"],
                "args": obj.get("args") or {},
                "span": m.span(),
            })

    # 2. Code blocks with file paths
    for m in _CODE_BLOCK.finditer(text):
        lang = m.group(1) or ""
        content = m.group(2).strip()
        if not content:
            continue

        # Check if lang looks like a file path
        if _looks_like_path(lang) and lang not in seen_files:
            seen_files.add(lang)
            edits.append({
                "type": "write",
                "name": "write_file",
                "args": {"path": lang, "content": content + "\n"},
                "span": m.span(),
            })
        elif _looks_like_path(content.split("\n")[0]):
            # First line might be the file path
            first_line = content.split("\n")[0].strip()
            rest = "\n".join(content.split("\n")[1:]).strip()
            if first_line and rest and _looks_like_path(first_line) and first_line not in seen_files:
                seen_files.add(first_line)
                edits.append({
                    "type": "write",
                    "name": "write_file",
                    "args": {"path": first_line, "content": rest + "\n"},
                    "span": m.span(),
                })

    # 3. Diff-style edits
    for m in _DIFF_EDIT.finditer(text):
        old = m.group(1).strip()
        new = m.group(2).strip()
        if old and new:
            # Try to find which file this edit is for from surrounding context
            path = _find_nearest_path(text, m.start())
            if path:
                edits.append({
                    "type": "edit",
                    "name": "edit_file",
                    "args": {"path": path, "old_string": old, "new_string": new},
                    "span": m.span(),
                })

    # 4. Simple edit blocks
    for m in _SIMPLE_EDIT.finditer(text):
        path = m.group(1).strip()
        old = m.group(2).strip()
        new = m.group(3).strip()
        if path and old and new:
            edits.append({
                "type": "edit",
                "name": "edit_file",
                "args": {"path": path, "old_string": old, "new_string": new},
                "span": m.span(),
            })

    # 5. Write blocks
    for m in _WRITE_BLOCK.finditer(text):
        path = m.group(1).strip()
        content = m.group(2).strip()
        if path and content and path not in seen_files:
            seen_files.add(path)
            edits.append({
                "type": "write",
                "name": "write_file",
                "args": {"path": path, "content": content + "\n"},
                "span": m.span(),
            })

    return edits


def _looks_like_path(s: str) -> bool:
    """Check if a string looks like a file path."""
    if not s or len(s) > 200:
        return False
    # Must contain a dot (extension) or slash
    if "." not in s and "/" not in s and "\\" not in s:
        return False
    # Must not contain too many spaces (likely prose, not a path)
    if s.count(" ") > 3:
        return False
    # Must not start with common prose words
    if s.lower().startswith(("the ", "a ", "an ", "this ", "here ", "you ", "i ", "we ")):
        return False
    return True


def _find_nearest_path(text: str, pos: int) -> str | None:
    """Look backwards from pos to find a file path mentioned in the text."""
    # Look at the 500 chars before the edit
    prefix = text[max(0, pos - 500):pos]
    # Common patterns: "in file.py", "editing file.py", "### file.py"
    patterns = [
        r"(?:in|editing|file|path):\s*([^\s\"']+?\.[a-zA-Z]{1,10})",
        r"###?\s+([^\s\"']+?\.[a-zA-Z]{1,10})",
        r"`([^\s\"']+?\.[a-zA-Z]{1,10})`",
        r"([^\s\"'/\\]+?\.[a-zA-Z]{1,10})",
    ]
    for pat in patterns:
        matches = list(re.finditer(pat, prefix))
        if matches:
            return matches[-1].group(1)
    return None


def _try_parse_json(raw: str) -> dict | None:
    """Parse JSON with common repair strategies."""
    raw = raw.strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    try:
        fixed = re.sub(r",\s*}", "}", raw)
        fixed = re.sub(r",\s*]", "]", fixed)
        obj = json.loads(fixed)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    return None


def _has_tool_prompt(messages: list) -> bool:
    """Check if tool docs are already in the conversation."""
    for m in messages:
        content = m.get("content") or ""
        if "coding agent" in content and ("tool" in content.lower() or "file system" in content.lower()):
            return True
    return False


def _build_system_prompt(effort: str = "medium", has_openai_tools: bool = False,
                         thinking: bool = False) -> str:
    prompt = TOOL_DOCS
    if has_openai_tools:
        prompt += OPENAI_TOOL_PROMPT
    if thinking:
        prompt += THINKING_PROMPT
    eff = (effort or "medium").lower()
    if eff in EFFORT_PROMPTS:
        prompt += EFFORT_PROMPTS[eff]
    return prompt


def _inject_tool_prompt(messages: list, effort: str = "medium",
                        has_openai_tools: bool = False, thinking: bool = False) -> list:
    convo = list(messages) if messages else []
    if not convo:
        convo.append({"role": "user", "content": ""})

    if not _has_tool_prompt(convo):
        convo.insert(0, {"role": "system", "content": _build_system_prompt(effort, has_openai_tools, thinking)})

    return convo


async def _execute_tool_call(tc: dict) -> dict:
    """Execute a single tool call."""
    name = tc["name"]
    args = tc["args"]
    try:
        result = TOOLS[name](**args)
    except Exception as e:
        result = f"Error: {e}"
    return {"name": name, "args": args, "result": result}


async def _execute_tools_parallel(tool_calls: list[dict]) -> list[dict]:
    """Execute multiple tool calls in parallel."""
    if len(tool_calls) == 1:
        return [_execute_tool_call(tool_calls[0])]

    tasks = [_execute_tool_call(tc) for tc in tool_calls[:_MAX_PARALLEL_TOOLS]]
    return await asyncio.gather(*tasks)


def _strip_edits_from_text(text: str, edits: list[dict]) -> str:
    """Remove edit blocks from the displayed text, keep prose."""
    if not edits:
        return text
    # Sort by start position descending so we can remove from end
    spans = sorted([e["span"] for e in edits if e.get("span")], key=lambda s: s[0], reverse=True)
    result = text
    for start, end in spans:
        result = result[:start] + result[end:]
    return result.strip()


async def stream_with_tools(model: str, messages: list, account=None,
                            effort: str = "medium", agentic: bool = True,
                            has_openai_tools: bool = False, thinking: bool = False):
    """Async generator: yields tool-aware events.

    NATIVE FILE EDIT: detects code blocks, diff edits, and tool tags
    automatically. The model just outputs code naturally.
    """
    from . import leech

    convo = _inject_tool_prompt(messages, effort, has_openai_tools, thinking)

    for _step in range(_MAX_TOOL_STEPS):
        acc = ""

        # Stream one model turn
        async for delta in leech.stream_messages(model, convo, acct=account,
                                                 agentic=agentic):
            acc += delta
            yield {"type": "token", "token": delta}

        # Parse ALL edit formats
        edits = _parse_native_edits(acc)

        if not edits:
            yield {"type": "done"}
            return

        # Add assistant response to conversation
        convo.append({"role": "assistant", "content": acc})

        # Execute ALL edits in parallel
        for edit in edits:
            name = edit["name"]
            args = edit["args"]

            yield {"type": "tool_call", "name": name, "args": args}

            # Execute the tool
            try:
                result = TOOLS[name](**args)
            except Exception as e:
                result = f"Error: {e}"

            yield {"type": "tool_result", "name": name, "result": result}
            convo.append({"role": "user", "content": f"Tool result: [{name}]\n{result}"})

    yield {"type": "token", "token": "\n\n[Stopped after max tool steps]"}
    yield {"type": "done"}


async def complete_with_tools(model: str, messages: list, account=None,
                              effort: str = "medium", agentic: bool = True,
                              has_openai_tools: bool = False, thinking: bool = False) -> str:
    """Buffered variant: collect the full text reply."""
    parts = []
    async for event in stream_with_tools(model, messages, account=account,
                                         effort=effort, agentic=agentic,
                                         has_openai_tools=has_openai_tools,
                                         thinking=thinking):
        if event["type"] == "token":
            parts.append(event["token"])
    return "".join(parts).strip()
