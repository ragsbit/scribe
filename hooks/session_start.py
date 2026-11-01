"""SessionStart hook — reset turn_count, then list note titles (catalog), v0.2.0.

Memory: handled by Claude Code auto-memory (personal).
Knowledge: whole notes are not injected (until 0.1.2 that grew past 200KB and
front-loaded every session). Instead the hook lists one line per note: shared
notes (all projects, SHARED_DIR) first, then this project's notes, within
CATALOG_BUDGET characters. Claude opens a note with Read when its title fits the
task. When the list does not fit, descriptions get shorter, then the project's
titles give way to one pointer line (count + where to search).
"""
import json
import logging
import sys
from pathlib import Path

from _scribe_paths import (CATALOG_BUDGET, KNOWLEDGE_DIR, LOG_FILE, PROJECT_ROOT,
                           SHARED_DIR, TURN_COUNT_FILE, ensure_dirs)

ensure_dirs()
logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows pipes default to the local code page
except Exception:
    pass

INDEX_FILES = ("docs/INDEX.md", ".scribe/knowledge/INDEX.md")
SKIP = {"INDEX.MD", "LOG.MD"}
FOLDED = (">", ">-", "|", "|-")
# (shared description width, project description width); 0 = title only,
# None = one pointer line instead of the project's titles. Tried in order.
LEVELS = [(150, 150), (150, 60), (60, 60), (60, 0), (150, None), (60, None), (0, None)]


def _parse(text: str) -> tuple:
    """Top-level front matter keys and the body lines."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, lines
    meta, folded = {}, None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            break
        if line[:1] in (" ", "\t"):
            if folded:
                meta[folded] = (meta[folded] + " " + line.strip()).strip()
            continue
        folded = None
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if value in FOLDED:
            meta[key], folded = "", key
        else:
            meta[key] = value.strip("\"'")
    else:
        return {}, lines
    return meta, lines[i + 1:]


def read_notes(folder: Path) -> list:
    notes = []
    if not folder.is_dir():
        return notes
    for f in folder.glob("*.md"):
        if f.name.upper() in SKIP:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta, body = _parse(text)
        first = next((s.strip().lstrip("#").strip() for s in body
                      if s.strip() and not s.strip().startswith("```")), "")
        desc = meta.get("description") or meta.get("title") or first
        notes.append({
            "name": meta.get("name") or f.stem,
            "desc": " ".join(desc.split()),
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
    head = ("## scribe notes (titles only)\n"
            "Open a note with Read when its title fits the task; a title missing here can still "
            "be found with grep. A note's status claims (\"fixed\", \"works\", a version) date from "
            "its `updated:`; check them against the code before acting on them.")
    index = next((p for p in INDEX_FILES if (PROJECT_ROOT / p).is_file()), None)
    pointer = (f"This project (`.scribe/knowledge`): {len(project)} notes, too many to list. "
               f"Search: grep -ril <word> .scribe/knowledge"
               + (f", or read the index `{index}`." if index else "."))

    def assemble(s_width, p_width, s_notes, tail=""):
        parts = [head]
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


def main() -> None:
    try:
        sys.stdin.read()
    except Exception:
        pass

    try:
        TURN_COUNT_FILE.write_text("0", encoding="utf-8")
    except Exception:
        pass

    try:
        shared, project = read_notes(SHARED_DIR), read_notes(KNOWLEDGE_DIR)
        text, level = build_catalog(shared, project, CATALOG_BUDGET)
    except Exception as e:  # a broken note must never break the session start
        logging.error("session_start: catalog failed: %s", e)
        sys.exit(0)

    if not text:
        logging.info("session_start: no notes to list")
        sys.exit(0)
    logging.info("session_start: catalog %d chars, level %s, shared %d, project %d",
                 len(text), level, len(shared), len(project))
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
