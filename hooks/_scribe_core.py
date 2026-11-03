"""Core shared by the hooks and scripts/scribe.py: where things live, reading
notes, and the hits logs.

Import-light on purpose (no pathlib, no logging): the PreToolUse hook imports
it on every Read.
"""
import json
import os
import re
import time

SKIP = {"INDEX.MD", "LOG.MD", "MAP.MD"}
FOLDED = (">", ">-", ">+", "|", "|-", "|+")
MAP_FILES = (".scribe/knowledge/MAP.md", ".scribe/MAP.md")
GARDEN_EVERY = 31               # days between /scribe-garden runs before a reminder shows
LOG_TAIL = 1_000_000            # bytes read from the end of a big hits log


class Dirs:
    """Where scribe keeps things: the project from CLAUDE_PROJECT_DIR (else the
    current directory), shared notes from SCRIBE_SHARED_DIR (else
    ~/.claude/scribe/shared)."""

    def __init__(self, project=None, shared=None):
        self.project = project or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        self.scribe = os.path.join(self.project, ".scribe")
        self.knowledge = os.path.join(self.scribe, "knowledge")
        self.shared = os.path.expanduser(shared or os.environ.get("SCRIBE_SHARED_DIR")
                                         or os.path.join("~", ".claude", "scribe", "shared"))

    def folder(self, scope):
        return self.shared if scope == "shared" else self.knowledge

    def hits_file(self, scope):
        return (os.path.join(self.shared, ".hits.jsonl") if scope == "shared"
                else os.path.join(self.scribe, "hits.jsonl"))

    def garden_stamp(self, scope):
        return (os.path.join(self.shared, ".garden_last") if scope == "shared"
                else os.path.join(self.scribe, "garden_last"))

    def label(self, path):
        """A short way to show a path: project-relative, ~/..., or as is."""
        for base, prefix in ((self.project, ""), (os.path.expanduser("~"), "~/")):
            rel = os.path.relpath(path, base) if _under(path, base) else None
            if rel:
                return prefix + rel.replace(os.sep, "/")
        return path


def _under(path, base):
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(base)]) \
            == os.path.abspath(base)
    except ValueError:  # different drives on Windows
        return False


# ---------------------------------------------------------------- notes

def unquote(value):
    """A one-line YAML scalar: 'single' ('' is a quote), "double" (only \\" and
    \\\\ unescape), or plain, kept whole (notes' descriptions keep their " #").
    A quoted scalar may end in a # comment. Text after a closing quote that is
    not a comment means the value was never quoted, and it is kept whole."""
    v = value.strip()
    q = v[:1]
    if q in ("'", '"') and len(v) >= 2:
        i = 1
        while i < len(v):
            if q == '"' and v[i] == "\\":
                i += 2
                continue
            if v[i] == q:
                if q == "'" and v[i + 1:i + 2] == "'":
                    i += 2
                    continue
                rest = v[i + 1:].strip()
                if rest and not rest.startswith("#"):
                    return v
                inner = v[1:i]
                return inner.replace("''", "'") if q == "'" else re.sub(r'\\(["\\])', r"\1", inner)
            i += 1
    return v


def parse(text):
    """(meta, body lines). meta maps top-level front matter keys to strings;
    an indented line only continues a folded value (> or |) and is skipped
    otherwise. So a note from before 0.5 still reads: its `triggers:` block is
    skipped, and its `enforce:` and `fix:` keys are kept but nothing uses them."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, lines
    meta, folded = {}, None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            break
        if not line.strip():
            continue
        if line[:1] in (" ", "\t"):
            if folded:
                meta[folded] = (meta[folded] + " " + line.strip()).strip()
            continue
        folded = None
        if line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if value in FOLDED:
            meta[key], folded = "", key
        else:
            meta[key] = unquote(value)
    else:
        return {}, lines
    return meta, lines[i + 1:]


def read_note(path):
    with open(path, encoding="utf-8") as f:
        return parse(f.read())


def note_files(folder):
    """File names of the notes in a folder (not INDEX, LOG or MAP)."""
    try:
        with os.scandir(folder) as entries:
            return sorted(e.name for e in entries if e.name.endswith(".md")
                          and e.name.upper() not in SKIP and e.is_file())
    except OSError:
        return []


def read_map(project):
    """(relative path, text without front matter) of the project map, or None."""
    for rel in MAP_FILES:
        path = os.path.join(project, *rel.split("/"))
        if os.path.isfile(path):
            try:
                _, body = read_note(path)
            except (OSError, UnicodeDecodeError):
                return None
            return rel, "\n".join(body).strip()
    return None


# ---------------------------------------------------------------- hits

def now_iso(seconds_ago=0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


def days_since(iso):
    import calendar  # only the session-start and garden paths need it
    try:
        then = calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None
    return (time.time() - then) / 86400


def ensure_log(dirs, scope):
    """Start a hits log with a `start` line, so /scribe-garden knows since when
    the Reads of a note were counted."""
    path = dirs.hits_file(scope)
    if os.path.exists(path):
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": now_iso(), "kind": "start"}) + "\n")
    except OSError:
        pass


def append_hit(dirs, scope, event):
    ensure_log(dirs, scope)
    try:
        with open(dirs.hits_file(scope), "a", encoding="utf-8") as f:
            f.write(json.dumps(dict({"t": now_iso()}, **event), ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_hits(dirs, scope):
    """Events of one hits log, oldest first (only the last LOG_TAIL bytes)."""
    path = dirs.hits_file(scope)
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - LOG_TAIL))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    lines = data.splitlines()
    if size > LOG_TAIL and lines:
        lines = lines[1:]  # the first line is cut
    events = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            events.append(e)
    return events


def count(events, kinds=("read",), days=None):
    """{stem: number of events} of these kinds (by default a Read of the note),
    within `days`."""
    since = now_iso(days * 86400) if days is not None else ""
    out = {}
    for e in events:
        if e.get("kind") in kinds and str(e.get("t", "")) >= since:
            out[e.get("note")] = out.get(e.get("note"), 0) + 1
    return out


def garden_due(dirs, has_notes):
    """Days since /scribe-garden last ran — or since hits logging began, when
    it never ran — once that reaches GARDEN_EVERY; else None."""
    worst = None
    for scope in ("shared", "project"):
        if not has_notes.get(scope):
            continue
        try:
            with open(dirs.garden_stamp(scope), encoding="utf-8") as f:
                since = days_since(f.read().strip())
        except OSError:
            events = read_hits(dirs, scope)[:1]
            since = days_since(events[0].get("t")) if events else None
        if since is not None and since >= GARDEN_EVERY and (worst is None or since > worst):
            worst = since
    return int(worst) if worst is not None else None
