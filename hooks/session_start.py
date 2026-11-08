"""SessionStart hook — update this session's turn count, then put the project
map and the note titles (catalog) in front of the session, v0.5.1.

Turn count (_scribe_turns): a new conversation (startup, /clear) starts it
over; a resume keeps it; a compaction keeps it and asks for a review at the
next Stop. Until 0.5.0 every SessionStart, compactions included, reset one
counter shared by all sessions of the project, so long sessions rarely
reached ten turns.

Memory: handled by Claude Code auto-memory (personal).
Knowledge: whole notes are not injected (until 0.1.2 that grew past 200KB and
front-loaded every session). Within CATALOG_BUDGET characters the hook puts:
1. the project map (.scribe/knowledge/MAP.md: key facts, then situation →
   search words → note), cut to MAP_BUDGET;
2. one line per note: shared notes (all projects, SHARED_DIR) first, then this
   project's, newest first. When the list does not fit, descriptions get
   shorter, then the project's titles give way to one pointer line (count +
   where to search);
3. a line when /scribe-garden is due.
It also starts the hits logs, so /scribe-garden knows since when Reads of notes
were counted.
"""
import json
import logging
import sys
from pathlib import Path

import _scribe_core as core
import _scribe_turns as turns
from _scribe_paths import (CATALOG_BUDGET, DIRS, KNOWLEDGE_DIR, LEGACY_TURN_COUNT_FILE, LOG_FILE,
                           MAP_BUDGET, PROJECT_ROOT, SHARED_DIR, TURNS_DIR, ensure_dirs)

ensure_dirs()
logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows pipes default to the local code page
except Exception:
    pass

INDEX_FILES = ("docs/INDEX.md", ".scribe/knowledge/INDEX.md")
# (shared description width, project description width); 0 = title only,
# None = one pointer line instead of the project's titles. Tried in order.
LEVELS = [(150, 150), (150, 60), (60, 60), (60, 0), (150, None), (60, None), (0, None)]
HEAD = ("## scribe notes (titles only)\n"
        "Open a note with Read when its title fits the task; a title missing here can still "
        "be found with grep or /scribe-search. A note's status claims (\"fixed\", \"works\", a version) date from "
        "its `updated:`; check them against the code before acting on them.")


def read_notes(folder: Path) -> list:
    notes = []
    if not folder.is_dir():
        return notes
    for f in folder.glob("*.md"):
        if f.name.upper() in core.SKIP:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta, body = core.parse(text)
        first = next((s.strip().lstrip("#").strip() for s in body
                      if s.strip() and not s.strip().startswith("```")), "")
        desc = meta.get("description") or meta.get("title") or first
        notes.append({
            "name": str(meta.get("name") or f.stem),
            "desc": " ".join(str(desc).split()),
            "updated": str(meta.get("updated") or meta.get("date") or ""),
            "mtime": f.stat().st_mtime,
        })
    notes.sort(key=lambda n: (n["updated"], n["mtime"]), reverse=True)
    return notes


def _line(note: dict, width: int) -> str:
    desc = note["desc"]
    if not width or not desc or desc == note["name"]:
        return f"- {note['name']}"
    if len(desc) > width:
        desc = desc[:width - 1].rstrip() + "…"
    return f"- {note['name']} — {desc}"


def _label(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def build_catalog(shared: list, project: list, budget: int) -> tuple:
    """(text, level) — ("", None) when there is no note at all."""
    if not shared and not project:
        return "", None
    index = next((p for p in INDEX_FILES if (PROJECT_ROOT / p).is_file()), None)
    pointer = (f"This project (`.scribe/knowledge`): {len(project)} notes, too many to list. "
               f"Search: grep -ril <word> .scribe/knowledge"
               + (f", or read the index `{index}`." if index else "."))

    def assemble(s_width, p_width, s_notes, tail=""):
        parts = [HEAD]
        if s_notes:
            parts.append("\n".join([f"Shared, all projects (`{_label(SHARED_DIR)}`, {len(shared)}):"]
                                   + [_line(n, s_width) for n in s_notes]) + tail)
        elif tail:
            parts.append(tail.strip())
        if project:
            parts.append(pointer if p_width is None else
                         "\n".join([f"This project (`.scribe/knowledge`, {len(project)}):"]
                                   + [_line(n, p_width) for n in project]))
        return "\n\n".join(parts)

    for level, (s_width, p_width) in enumerate(LEVELS):
        text = assemble(s_width, p_width, shared)
        if len(text) <= budget:
            return text, level
    keep = list(shared)
    while keep:
        keep.pop()
        tail = f"\n… {len(shared) - len(keep)} older shared notes not listed (`{_label(SHARED_DIR)}`)."
        text = assemble(0, None, keep, tail)
        if len(text) <= budget:
            return text, len(LEVELS)
    return assemble(0, None, [], f"\n{len(shared)} shared notes in `{_label(SHARED_DIR)}`."), len(LEVELS)


def map_section(budget: int) -> str:
    """The project map under a heading, cut at a line end to fit `budget`."""
    found = core.read_map(str(PROJECT_ROOT))
    if not found or not found[1]:
        return ""
    rel, text = found
    title = f"## scribe project map (`{rel}`)\n"
    if len(title) + len(text) > budget:
        more = f"\n… (cut; read `{rel}` for the rest)"
        room = max(0, budget - len(title) - len(more))
        cut = text[:room + 1]
        text = (cut[:cut.rfind("\n")] if "\n" in cut else cut[:room]).rstrip() + more
    return title + text


def extra_lines(has_notes: dict) -> list:
    lines = []
    due = core.garden_due(DIRS, has_notes)
    if due is not None:
        lines.append(f"scribe: notes not gardened for {due} days. /scribe-garden merges duplicates, "
                     "re-checks status claims, and proposes notes to prune.")
    return lines


def main() -> None:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    session_id, source = data.get("session_id"), data.get("source")
    try:
        done = turns.on_session_start(TURNS_DIR, session_id, source)
        logging.info("session_start: session=%s source=%s, turn count %s",
                     str(session_id or "?")[:8], source or "?", done)
        turns.prune(TURNS_DIR)
        LEGACY_TURN_COUNT_FILE.unlink(missing_ok=True)
    except Exception as e:
        logging.error("session_start: turn count failed: %s", e)

    try:
        for scope in ("shared", "project"):
            core.ensure_log(DIRS, scope)
        shared = read_notes(SHARED_DIR)
        project = read_notes(KNOWLEDGE_DIR)
        map_text = map_section(min(MAP_BUDGET, CATALOG_BUDGET // 2))
        extras = extra_lines({"shared": bool(shared), "project": bool(project)})
        used = sum(len(p) + 2 for p in [map_text] + extras if p)
        catalog, level = build_catalog(shared, project, CATALOG_BUDGET - used)
        text = "\n\n".join(p for p in [map_text, catalog] + extras if p)
    except Exception as e:  # a broken note must never break the session start
        logging.error("session_start: catalog failed: %s", e)
        sys.exit(0)

    if not text:
        logging.info("session_start: no notes to list")
        sys.exit(0)
    logging.info("session_start: %d chars (map %d), level %s, shared %d, project %d",
                 len(text), len(map_text), level, len(shared), len(project))
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
