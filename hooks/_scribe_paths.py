"""Paths for scribe runtime data.

Resolves project root from CLAUDE_PROJECT_DIR (Claude Code hook env),
falling back to current working directory. Per-project artifacts live
under <project_root>/.scribe/. Shared notes, read in every project, live
in SCRIBE_SHARED_DIR (default ~/.claude/scribe/shared). The rules themselves
are in _scribe_core.Dirs, which the import-light PreToolUse hook uses directly.
"""
import os
from pathlib import Path

from _scribe_core import Dirs

DIRS = Dirs()
PROJECT_ROOT = Path(DIRS.project)
ROOT = Path(DIRS.scribe)
KNOWLEDGE_DIR = Path(DIRS.knowledge)
LOG_FILE = ROOT / "hook.log"
TURN_COUNT_FILE = ROOT / "turn_count"

SHARED_DIR = Path(DIRS.shared)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


CATALOG_BUDGET = _int_env("SCRIBE_CATALOG_BUDGET", 6000)  # map + titles at session start
MAP_BUDGET = _int_env("SCRIBE_MAP_BUDGET", 1500)          # the project map's share of it


def ensure_dirs() -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
