import os
import pathlib
import re
import time
import shutil
import urllib.request
import urllib.parse
import json as _json

WORKDIR = pathlib.Path(os.environ.get("LEECH_WORKDIR", "workspace")).resolve()
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
_TEXT_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".go", ".rs",
              ".rb", ".php", ".c", ".cc", ".cpp", ".h", ".hpp", ".java", ".kt", ".swift",
              ".cs", ".sh", ".ps1", ".html", ".htm", ".css", ".scss", ".json", ".yaml",
              ".yml", ".toml", ".md", ".sql", ".lua", ".txt", ".cfg", ".ini", ".env"}


def _resolve(path):
    WORKDIR.mkdir(parents=True, exist_ok=True)
    p = (WORKDIR / path).resolve()
    if not str(p).startswith(str(WORKDIR)):
        raise ValueError("path escapes the workspace")
    return p


def read_file(path):
    p = _resolve(path)
    if not p.is_file():
        return "Error: file not found: " + path
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    numbered = "\n".join("%4d | %s" % (i + 1, l) for i, l in enumerate(lines))
    return "File: %s (%d lines)\n\n%s" % (path, len(lines), numbered)


def write_file(path, content):
    import logging
    logging.getLogger("tools").info("write_file: path=%s len=%d", path, len(content))
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return "Wrote %d lines to %s" % (content.count("\n") + 1, path)


def append_file(path, content):
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(content)
    return "Appended to %s" % path


def edit_file(path, old_string, new_string, replace_all=False):
    p = _resolve(path)
    if not p.is_file():
        return "Error: file not found: " + path
    content = p.read_text(encoding="utf-8", errors="replace")
    if old_string == new_string:
        return "Error: old_string and new_string are identical"
    located = old_string
    if old_string not in content:
        located = _fuzzy(content, old_string)
        if located is None:
            return "Error: old_string not found in %s" % path
    count = content.count(located)
    if count > 1 and not replace_all:
        return "Error: old_string matches %d places; add context or set replace_all" % count
    if replace_all:
        content = content.replace(located, new_string)
    else:
        content = content.replace(located, new_string, 1)
    p.write_text(content, encoding="utf-8")
    return "Edited %s (%d occurrence%s)" % (path, count if replace_all else 1,
                                            "s" if (replace_all and count != 1) else "")


def _fuzzy(content, old):
    if not old:
        return None
    lines = content.splitlines(keepends=True)
    old_lines = old.splitlines()
    n = len(old_lines)
    if n == 0 or n > len(lines):
        return None
    def norm(s):
        return "".join(ch for ch in s if ch.isalnum())
    for tf in (str.rstrip, str.strip, norm):
        tgt = [tf(x) for x in old_lines]
        if tf is norm and not any(tgt):
            continue
        hits = []
        for i in range(len(lines) - n + 1):
            if all(tf(lines[i + j].rstrip("\r\n")) == tgt[j] for j in range(n)):
                start = sum(len(x) for x in lines[:i])
                end = start + sum(len(x) for x in lines[i:i + n]) - (
                    len(lines[i + n - 1]) - len(lines[i + n - 1].rstrip("\r\n")))
                hits.append(content[start:end])
        uniq = set(hits)
        if len(uniq) == 1:
            return hits[0]
        if len(uniq) > 1:
            return None
    return None


def append_only(path, content):
    return append_file(path, content)


def delete_file(path):
    p = _resolve(path)
    if p.is_dir():
        import shutil
        shutil.rmtree(p)
        return "Deleted directory %s" % path
    if p.is_file():
        p.unlink()
        return "Deleted %s" % path
    return "Error: not found: " + path


def list_dir(path=".", depth=2):
    base = _resolve(path)
    if not base.exists():
        return "Error: not found: " + path
    out = []
    def walk(d, prefix, level):
        if level > depth:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda e: (e.is_file(), e.name))
        except Exception:
            return
        for e in entries:
            if e.name in (".git", "node_modules", "__pycache__"):
                continue
            out.append(prefix + e.name + ("/" if e.is_dir() else ""))
            if e.is_dir():
                walk(e, prefix + "  ", level + 1)
    walk(base, "", 1)
    return "\n".join(out) if out else "(empty)"


def move_file(path, new_path):
    src = _resolve(path)
    dst = _resolve(new_path)
    if not src.exists():
        return "Error: not found: " + path
    if dst.exists():
        return "Error: destination exists: " + new_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return "Moved %s -> %s" % (path, new_path)


def copy_file(path, new_path):
    import shutil
    src = _resolve(path)
    dst = _resolve(new_path)
    if not src.exists():
        return "Error: not found: " + path
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return "Copied %s -> %s" % (path, new_path)


def make_dir(path):
    p = _resolve(path)
    p.mkdir(parents=True, exist_ok=True)
    return "Created directory %s" % path


def glob_files(pattern, path="."):
    base = _resolve(path)
    out = []
    for p in sorted(base.rglob(pattern)):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        out.append(os.path.relpath(p, WORKDIR).replace("\\", "/"))
    return "\n".join(out) if out else "No files matching %r" % pattern


def run_command(command, timeout=120):
    import subprocess
    WORKDIR.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(command, shell=True, cwd=str(WORKDIR), capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "Error: command timed out after %ds" % timeout
    except Exception as e:
        return "Error: %s" % e
    out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
    out = out.strip() or "(no output)"
    return "exit %d\n%s" % (r.returncode, out[:8000])


def grep_search(pattern, path=".", case_insensitive=False, max_results=200):
    base = _resolve(path)
    try:
        rx = re.compile(pattern, re.IGNORECASE if case_insensitive else 0)
    except re.error:
        rx = re.compile(re.escape(pattern), re.IGNORECASE if case_insensitive else 0)
    hits = []
    targets = [base] if base.is_file() else None
    if targets is None:
        targets = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
            for name in files:
                if pathlib.Path(name).suffix.lower() in _TEXT_EXTS:
                    targets.append(pathlib.Path(root) / name)
    for f in targets:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = os.path.relpath(f, WORKDIR).replace("\\", "/")
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append("%s:%d: %s" % (rel, i, line.strip()[:200]))
                if len(hits) >= max_results:
                    return "\n".join(hits) + "\n... (truncated)"
    return "\n".join(hits) if hits else "No matches for %r" % pattern


def web_search(query, num_results=5):
    """Search the web. Uses Wikipedia + Google scraping."""
    import httpx

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    results = []

    # 1. Wikipedia summary
    try:
        wiki_query = query.replace(" ", "_")
        with httpx.Client(timeout=8, headers=headers, follow_redirects=True) as client:
            r = client.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{wiki_query}")
            if r.status_code == 200:
                data = r.json()
                title = data.get("title", "")
                extract = data.get("extract", "")
                page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
                if title and extract:
                    results.append(f"1. [Wikipedia] {title}\n   {extract[:300]}\n   URL: {page_url}")
    except Exception:
        pass

    # 2. Google search (scrape)
    try:
        with httpx.Client(timeout=10, headers=headers, follow_redirects=True) as client:
            r = client.get("https://www.google.com/search", params={"q": query, "num": num_results, "hl": "en"})
            if r.status_code == 200:
                html = r.text
                title_pattern = re.compile(r'<h3[^>]*>(.*?)</h3>', re.DOTALL)
                link_pattern = re.compile(r'<a[^>]+href="/url\?q=([^&"]+)')

                titles = title_pattern.findall(html)
                links = link_pattern.findall(html)

                for i in range(min(len(titles), len(links), num_results)):
                    title = re.sub(r'<[^>]+>', '', titles[i]).strip()
                    link = urllib.parse.unquote(links[i].split('&')[0])
                    if title and link.startswith('http') and 'google' not in link:
                        results.append(f"{len(results)+1}. {title}\n   URL: {link}")
    except Exception:
        pass

    return "\n\n".join(results) if results else f"No results found for: {query}"


def web_search_with_snippets(query, num_results=3):
    """Search with full snippets for detailed research."""
    import httpx

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    results = []

    # Wikipedia detailed
    try:
        wiki_query = query.replace(" ", "_")
        with httpx.Client(timeout=8, headers=headers, follow_redirects=True) as client:
            r = client.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{wiki_query}")
            if r.status_code == 200:
                data = r.json()
                title = data.get("title", "")
                extract = data.get("extract", "")
                page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
                if title and extract:
                    results.append(f"### [Wikipedia] {title}\n{extract}\nSource: {page_url}")
    except Exception:
        pass

    # Google with snippets
    try:
        with httpx.Client(timeout=10, headers=headers, follow_redirects=True) as client:
            r = client.get("https://www.google.com/search", params={"q": query, "num": num_results, "hl": "en"})
            if r.status_code == 200:
                html = r.text
                title_pattern = re.compile(r'<h3[^>]*>(.*?)</h3>', re.DOTALL)
                link_pattern = re.compile(r'<a[^>]+href="/url\?q=([^&"]+)')
                snippet_pattern = re.compile(r'<div[^>]*>(.*?)</div>', re.DOTALL)

                titles = title_pattern.findall(html)
                links = link_pattern.findall(html)

                for i in range(min(len(titles), len(links), num_results)):
                    title = re.sub(r'<[^>]+>', '', titles[i]).strip()
                    link = urllib.parse.unquote(links[i].split('&')[0])
                    if title and link.startswith('http') and 'google' not in link:
                        results.append(f"### {title}\nSource: {link}")
    except Exception:
        pass

    return "\n\n".join(results) if results else f"No detailed results found for: {query}"


def image_generate(prompt, size="1024x1024"):
    """Generate an image using Pollinations.ai (free, no API key)."""
    try:
        encoded = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
        return f"Image generated: {url}\n\nPrompt: {prompt}\nOpen the URL above to view/download the image."
    except Exception as e:
        return f"Image generation error: {e}"


# ---------------------------------------------------------------------------
# CLI-style tools
# ---------------------------------------------------------------------------

def file_info(path):
    """Like 'stat' / 'ls -la' — show file metadata."""
    p = _resolve(path)
    if not p.exists():
        return "Error: not found: " + path
    stat = p.stat()
    size = stat.st_size
    if size < 1024:
        size_str = f"{size} B"
    elif size < 1024 * 1024:
        size_str = f"{size / 1024:.1f} KB"
    else:
        size_str = f"{size / (1024 * 1024):.1f} MB"
    mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
    ctime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_ctime))
    kind = "dir" if p.is_dir() else "file"
    ext = p.suffix if p.is_file() else ""
    lines = ""
    if p.is_file() and ext in _TEXT_EXTS:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            lines = f"  Lines: {len(text.splitlines())}"
        except Exception:
            pass
    return (
        f"  File: {path}\n"
        f"  Type: {kind}\n"
        f"  Size: {size_str}{lines}\n"
        f"  Modified: {mtime}\n"
        f"  Created: {ctime}"
    )


def file_count(path):
    """Like 'wc' — count lines, words, characters."""
    p = _resolve(path)
    if not p.is_file():
        return "Error: not a file: " + path
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = len(text.splitlines())
    words = len(text.split())
    chars = len(text)
    bytes_size = len(text.encode("utf-8"))
    return f"  {lines} lines, {words} words, {chars} chars, {bytes_size} bytes  {path}"


def head_file(path, lines=10):
    """Like 'head -n' — show first N lines."""
    p = _resolve(path)
    if not p.is_file():
        return "Error: not a file: " + path
    text = p.read_text(encoding="utf-8", errors="replace")
    all_lines = text.splitlines()
    n = int(lines)
    shown = all_lines[:n]
    numbered = "\n".join("%4d | %s" % (i + 1, l) for i, l in enumerate(shown))
    total = len(all_lines)
    suffix = f"\n... ({total - n} more lines)" if total > n else ""
    return f"File: {path} (showing {min(n, total)}/{total} lines)\n\n{numbered}{suffix}"


def tail_file(path, lines=10):
    """Like 'tail -n' — show last N lines."""
    p = _resolve(path)
    if not p.is_file():
        return "Error: not a file: " + path
    text = p.read_text(encoding="utf-8", errors="replace")
    all_lines = text.splitlines()
    n = int(lines)
    shown = all_lines[-n:]
    start = max(1, len(all_lines) - n + 1)
    numbered = "\n".join("%4d | %s" % (start + i, l) for i, l in enumerate(shown))
    total = len(all_lines)
    prefix = f"({start - 1} lines omitted)\n" if start > 1 else ""
    return f"File: {path} (showing last {min(n, total)}/{total} lines)\n\n{prefix}{numbered}"


def read_lines(path, start=1, end=None):
    """Read specific line range: read_lines(file, 10, 20) shows lines 10-20."""
    p = _resolve(path)
    if not p.is_file():
        return "Error: not a file: " + path
    text = p.read_text(encoding="utf-8", errors="replace")
    all_lines = text.splitlines()
    s = max(1, int(start))
    e = int(end) if end else len(all_lines)
    shown = all_lines[s - 1:e]
    numbered = "\n".join("%4d | %s" % (s + i, l) for i, l in enumerate(shown))
    return f"File: {path} (lines {s}-{min(e, len(all_lines))}/{len(all_lines)})\n\n{numbered}"


def diff_files(path1, path2):
    """Like 'diff' — compare two files."""
    import difflib
    p1 = _resolve(path1)
    p2 = _resolve(path2)
    if not p1.is_file():
        return "Error: not found: " + path1
    if not p2.is_file():
        return "Error: not found: " + path2
    t1 = p1.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    t2 = p2.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    diff = list(difflib.unified_diff(t1, t2, fromfile=path1, tofile=path2, lineterm=""))
    if not diff:
        return "Files are identical"
    return "".join(diff[:200]) + ("\n... (truncated)" if len(diff) > 200 else "")


def replace_in_file(path, pattern, replacement, count=0):
    """Like 'sed s/old/new/g' — regex replace in file."""
    p = _resolve(path)
    if not p.is_file():
        return "Error: not found: " + path
    content = p.read_text(encoding="utf-8", errors="replace")
    try:
        rx = re.compile(pattern)
    except re.error:
        return f"Error: invalid regex: {pattern}"
    new_content, n = rx.subn(replacement, content, count=int(count))
    if n == 0:
        return f"No matches for pattern: {pattern}"
    p.write_text(new_content, encoding="utf-8")
    return f"Replaced {n} occurrence{'s' if n != 1 else ''} in {path}"


def sort_file(path, reverse=False, unique=False):
    """Like 'sort' — sort lines in a file."""
    p = _resolve(path)
    if not p.is_file():
        return "Error: not a file: " + path
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    lines.sort(reverse=bool(reverse))
    if unique:
        lines = list(dict.fromkeys(lines))  # preserve order, remove dupes
    new_text = "\n".join(lines) + "\n"
    p.write_text(new_text, encoding="utf-8")
    return f"Sorted {len(lines)} lines in {path}" + (" (reversed)" if reverse else "") + (" (unique)" if unique else "")


def unique_lines(path):
    """Like 'uniq' — remove duplicate lines, preserve order."""
    p = _resolve(path)
    if not p.is_file():
        return "Error: not a file: " + path
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    seen = set()
    out = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    new_text = "\n".join(out) + "\n"
    p.write_text(new_text, encoding="utf-8")
    removed = len(lines) - len(out)
    return f"Removed {removed} duplicate lines in {path} ({len(out)} unique remain)"


def touch_file(path):
    """Like 'touch' — create empty file or update timestamp."""
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        p.touch()
        return f"Updated timestamp: {path}"
    p.write_text("", encoding="utf-8")
    return f"Created: {path}"


def tree_view(path=".", depth=3, show_files=True):
    """Like 'tree' — directory tree visualization."""
    base = _resolve(path)
    if not base.exists():
        return "Error: not found: " + path
    out = [path or "."]
    def walk(d, prefix, level):
        if level > depth:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda e: (e.is_file(), e.name))
        except Exception:
            return
        dirs = [e for e in entries if e.is_dir() and e.name not in _SKIP_DIRS]
        files = [e for e in entries if e.is_file()] if show_files else []
        for i, e in enumerate(dirs + files):
            is_last = (i == len(dirs) + len(files) - 1)
            connector = "+-- " if is_last else "|-- "
            name = e.name + ("/" if e.is_dir() else "")
            out.append(prefix + connector + name)
            if e.is_dir():
                extension = "    " if is_last else "|   "
                walk(e, prefix + extension, level + 1)
    walk(base, "", 1)
    return "\n".join(out)


def find_files(name=None, ext=None, path=".", min_size=None, max_size=None):
    """Like 'find' — find files by name, extension, or size."""
    base = _resolve(path)
    if not base.exists():
        return "Error: not found: " + path
    hits = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            fp = pathlib.Path(root) / fname
            rel = os.path.relpath(fp, WORKDIR).replace("\\", "/")
            if name and name.lower() not in fname.lower():
                continue
            if ext and not fname.endswith(ext):
                continue
            if min_size and fp.stat().st_size < min_size:
                continue
            if max_size and fp.stat().st_size > max_size:
                continue
            hits.append(rel)
            if len(hits) >= 200:
                hits.append("... (truncated at 200)")
                return "\n".join(hits)
    return "\n".join(hits) if hits else "No files found"


def word_count(path):
    """Like 'wc -w' — count words per line."""
    p = _resolve(path)
    if not p.is_file():
        return "Error: not a file: " + path
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines, 1):
        wc = len(line.split())
        out.append(f"%5d %4d | %s" % (wc, i, line.rstrip()[:80]))
    total_words = sum(len(l.split()) for l in lines)
    total_lines = len(lines)
    summary = f"\n  {total_lines} lines, {total_words} words total"
    return "\n".join(out) + summary


def search_replace(path, old, new):
    """Simple string replace (no regex). Like sed but literal."""
    p = _resolve(path)
    if not p.is_file():
        return "Error: not found: " + path
    content = p.read_text(encoding="utf-8", errors="replace")
    if old not in content:
        return f"String not found: {old}"
    count = content.count(old)
    new_content = content.replace(old, new)
    p.write_text(new_content, encoding="utf-8")
    return f"Replaced {count} occurrence{'s' if count != 1 else ''} of '{old}' in {path}"


TOOLS = {
    # File operations
    "read_file": read_file,
    "write_file": write_file,
    "append_file": append_file,
    "edit_file": edit_file,
    "delete_file": delete_file,
    "move_file": move_file,
    "copy_file": copy_file,
    "make_dir": make_dir,
    "touch_file": touch_file,
    # Directory
    "list_dir": list_dir,
    "tree_view": tree_view,
    "glob_files": glob_files,
    "find_files": find_files,
    # Search
    "grep_search": grep_search,
    "search_replace": search_replace,
    # CLI-style
    "file_info": file_info,
    "file_count": file_count,
    "head_file": head_file,
    "tail_file": tail_file,
    "read_lines": read_lines,
    "diff_files": diff_files,
    "replace_in_file": replace_in_file,
    "sort_file": sort_file,
    "unique_lines": unique_lines,
    "word_count": word_count,
    # System
    "run_command": run_command,
    # External
    "web_search": web_search,
    "web_search_detailed": web_search_with_snippets,
    "image_generate": image_generate,
}
