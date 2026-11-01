"""Core shared by the hooks and scripts/scribe.py: where things live, reading
notes and their triggers, the trigger cache, and the hits logs.

Import-light on purpose (no pathlib, no logging): the PreToolUse hook imports
it on every tool call.
"""
import json
import os
import re
import time

SKIP = {"INDEX.MD", "LOG.MD", "MAP.MD"}
FOLDED = (">", ">-", ">+", "|", "|-", "|+")
MAP_FILES = (".scribe/knowledge/MAP.md", ".scribe/MAP.md")
FIRED = ("warn", "block")       # hit kinds that mean a trigger matched a tool call
RANK_DAYS = 30                  # hits this recent move a note up the session-start list
GARDEN_EVERY = 31               # days between /scribe-garden runs before a reminder shows
CACHE_VERSION = 1
SUBJECT_CAP = 100_000           # characters of one input string a trigger looks at
LOG_TAIL = 1_000_000            # bytes read from the end of a big hits log

SIMPLE_TOOLS = re.compile(r"[A-Za-z0-9_\-|, ]*")
FIELD_KEY = re.compile(r"(.+)\.([A-Za-z_][A-Za-z0-9_]*)")


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

def unquote(value, comments=False):
    """A one-line YAML scalar: 'single' ('' is a quote), "double" (only \\" and
    \\\\ unescape, so a regex such as "\\s" survives), or plain. A quoted scalar
    may end in a # comment; a plain one only when `comments` is set (notes'
    descriptions keep their " #"). Text after a closing quote that is not a
    comment means the value was never quoted, and it is kept whole."""
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
    return re.split(r"\s#", v, maxsplit=1)[0].rstrip() if comments else v


def parse(text):
    """(meta, body lines). meta maps top-level front matter keys to strings;
    `triggers:` maps to its indented lines, raw, for parse_triggers()."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, lines
    meta, folded, block = {}, None, None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            break
        if not line.strip():
            continue
        if line[:1] in (" ", "\t"):
            if block is not None:
                block.append(line)
            elif folded:
                meta[folded] = (meta[folded] + " " + line.strip()).strip()
            continue
        folded = block = None
        if line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "triggers" and not value:
            block = meta[key] = []
        elif value in FOLDED:
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


def how_to_apply(body):
    for line in body:
        if "How to apply:" in line:
            return line.split("How to apply:", 1)[1].strip(" *")
    return ""


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


# ---------------------------------------------------------------- triggers

def parse_triggers(raw):
    """[(key, pattern)] from the lines under `triggers:` — `Tool: pattern`, or
    `Tool:` followed by `- pattern` items. # comments are allowed."""
    pairs, current = [], None
    for line in raw if isinstance(raw, list) else []:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s == "-" or s.startswith("- "):
            item = s[1:].strip()
            if current is not None and not item.startswith("#"):
                pairs.append((current, unquote(item, comments=True)))
            continue
        colon = re.search(r":(?=\s|$)", s)  # a key such as (?:Edit|Write) has its own ':'
        if not colon:
            continue
        key, value = unquote(s[:colon.start()]), s[colon.end():].strip()
        if not value or value.startswith("#"):
            current = key
        else:
            pairs.append((key, unquote(value, comments=True)))
            current = None
    return pairs


def enforce_of(meta):
    """'block', 'warn' or '' (not set: a warning that suggests the block when it repeats)."""
    word = (str(meta.get("enforce") or "").lower().split() or [""])[0]
    return word if word in ("warn", "block") else ""


def split_key(key):
    """'Edit.new_string' -> ('Edit', 'new_string'); 'Bash' -> ('Bash', None)."""
    m = FIELD_KEY.fullmatch(key)
    return (m.group(1), m.group(2)) if m else (key, None)


def tool_matches(tool_key, tool_name):
    """The same rules as a hook matcher: '*' or '' is every tool; only letters,
    digits, _ - | , and spaces means exact names; anything else is a regex
    searched in the tool name."""
    if tool_key in ("", "*"):
        return True
    if SIMPLE_TOOLS.fullmatch(tool_key):
        return tool_name in {t.strip() for t in re.split(r"[|,]", tool_key)}
    return re.search(tool_key, tool_name) is not None


def check_trigger(key, pattern):
    """None when a trigger can be used, else why not."""
    if not pattern:
        return "empty pattern"
    tool_key, _ = split_key(key)
    try:
        if not SIMPLE_TOOLS.fullmatch(tool_key) and tool_key != "*":
            re.compile(tool_key)
        re.compile(pattern)
    except re.error as e:
        return f"does not compile: {e}"
    return None


def subjects(tool_input, field=None):
    """The strings a trigger is matched against: every string in the tool input
    except `description` (Claude's own words about the call), or only `field`."""
    if not isinstance(tool_input, dict):
        return []
    if field is not None:
        todo = [tool_input.get(field)]
    else:
        todo = [v for k, v in tool_input.items() if k != "description"]
    out = []
    while todo:
        v = todo.pop()
        if isinstance(v, str):
            out.append(v[:SUBJECT_CAP])
        elif isinstance(v, dict):
            todo.extend(v.values())
        elif isinstance(v, list):
            todo.extend(v)
    return out


def signature(dirs):
    """[scope, file, mtime_ns, size] for every note: the trigger cache is
    rebuilt when any of it changes."""
    sig = []
    for scope in ("shared", "project"):
        folder = dirs.folder(scope)
        for name in note_files(folder):
            try:
                st = os.stat(os.path.join(folder, name))
            except OSError:
                continue
            sig.append([scope, name, st.st_mtime_ns, st.st_size])
    return sig


def build_triggers(dirs):
    """(notes that carry usable triggers, problems [scope, stem, key, why])."""
    notes, problems = [], []
    for scope in ("shared", "project"):
        folder = dirs.folder(scope)
        for name in note_files(folder):
            path = os.path.join(folder, name)
            try:
                meta, body = read_note(path)
            except (OSError, UnicodeDecodeError):
                continue
            if "triggers" not in meta:
                continue
            stem, good = name[:-3], []
            pairs = parse_triggers(meta["triggers"])
            if not pairs:
                problems.append([scope, stem, "triggers", "no `Tool: 'pattern'` line under it"])
            for key, pattern in pairs:
                why = check_trigger(key, pattern)
                if why:
                    problems.append([scope, stem, key, why])
                else:
                    good.append([key, pattern])
            if not good:
                continue
            notes.append({
                "scope": scope, "stem": stem, "path": path,
                "name": str(meta.get("name") or stem),
                "desc": " ".join(str(meta.get("description") or "").split()),
                "fix": " ".join(str(meta.get("fix") or how_to_apply(body)).split()),
                "enforce": enforce_of(meta),
                "triggers": good,
            })
    return notes, problems


def load_triggers(dirs, rebuild=False):
    """{"notes": [...], "problems": [...]} from the cache in .scribe/, rebuilt
    when a note changed."""
    sig = signature(dirs)
    path = os.path.join(dirs.scribe, "triggers.json")
    if not rebuild:
        try:
            with open(path, encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("v") == CACHE_VERSION and cache.get("sig") == sig:
                return cache
        except (OSError, ValueError, AttributeError):
            pass
    notes, problems = build_triggers(dirs)
    cache = {"v": CACHE_VERSION, "sig": sig, "notes": notes, "problems": problems}
    try:
        os.makedirs(dirs.scribe, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass
    return cache


def match(notes, tool_name, tool_input):
    """[(note, key, pattern)]: each note with a trigger that matches this call."""
    found = []
    for note in notes:
        for key, pattern in note["triggers"]:
            tool_key, field = split_key(key)
            try:
                if tool_matches(tool_key, tool_name) and any(
                        re.search(pattern, s) for s in subjects(tool_input, field)):
                    found.append((note, key, pattern))
                    break
            except re.error:
                continue
    return found


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
    a note could have been hit."""
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


def count(events, kinds=FIRED, days=None, session=None):
    """{stem: number of events} of these kinds, within `days`, in `session`."""
    since = now_iso(days * 86400) if days is not None else ""
    out = {}
    for e in events:
        if e.get("kind") in kinds and str(e.get("t", "")) >= since \
                and (session is None or e.get("session") == session):
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
