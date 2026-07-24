import os
import pathlib
import re

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


TOOLS = {
    "read_file": read_file,
    "write_file": write_file,
    "append_file": append_file,
    "edit_file": edit_file,
    "delete_file": delete_file,
    "list_dir": list_dir,
    "grep_search": grep_search,
    "move_file": move_file,
    "copy_file": copy_file,
    "make_dir": make_dir,
    "glob_files": glob_files,
    "run_command": run_command,
}
