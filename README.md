# scribe

**Agentic Skill Improve Loop** — Claude Code plugin that reflects on every 10th response and routes new findings to the right place: personal Memory, project Knowledge, Shared notes read in every project, a one-line CLAUDE.md pointer, a repo test, or a skill fix. At session start it lists the notes' titles so Claude knows what exists.

Coding agents forget what they learned when a session ends, so the same trap costs you twice. scribe makes Claude stop every 10 turns, ask what it just learned, and write it where the next session will find it. A mistake that comes back after it was written down gets a failing test, because a test stops a repeat and a note does not.

Made and used every day by [Ragsbit](https://www.youtube.com/@ragsbit), an AI character run by a human.

---

## What it does

Two hooks, one skill:

1. **SessionStart hook** — Resets the turn counter and lists one line per note (title — description): shared notes first, then this project's, within `SCRIBE_CATALOG_BUDGET` characters (default 6000). Whole notes are not injected (until 0.1.2 that grew past 200KB); Claude opens a note when its title fits the task. When the list does not fit, descriptions get shorter, then the project's titles give way to one pointer line (count, where to search, the project's index if it has one). What every session must know goes into CLAUDE.md as one line.
2. **Stop hook** — Counts turns. Every 10th turn, injects a `[SCRIBE] Reflect...` prompt asking Claude whether anything from the last turns should be recorded, and where. If nothing fits → Claude responds `"Nothing to record."` and moves on.
3. **`/scribe-review` skill** — Triggered by the reflect prompt (or invoked manually). Follows the project's own record rules (CLAUDE.md / AGENTS.md) when it has them, searches before writing so an existing note is updated instead of duplicated, checks status statements before bumping `updated:`, and asks before writing unless the user or the project says records need no approval.

---

## Install

In Claude Code:

```
/plugin marketplace add ragsbit/scribe
/plugin install scribe@scribe
/reload-plugins
```

Or add the marketplace to `~/.claude/settings.json` yourself:

```json
{
  "extraKnownMarketplaces": {
    "scribe": {
      "source": {
        "source": "git",
        "url": "https://github.com/ragsbit/scribe.git"
      }
    }
  }
}
```

---

## Routing rules

If the project's CLAUDE.md or AGENTS.md says where records go, that wins; the table gives the defaults.

| Destination | What goes there | Read when |
|---|---|---|
| **Memory** (personal, Claude Code auto-managed) | User corrections of how Claude works, reports or asks; preferences; context not derivable from code | Built into Claude Code |
| **Knowledge** (git-tracked; the project's record folders, default `.scribe/knowledge/`) | Domain pitfalls, time-saving techniques, architectural decisions | Title at session start (`.scribe/knowledge/` only); body when opened |
| **Shared notes** (`~/.claude/scribe/shared/`) | Lessons that hold in other projects too: shell and OS traps, tools, APIs, data vendors, Claude Code behavior; a short note linking to the project record when that is where the full record lives | Title at session start in every project; body when opened |
| **One line in CLAUDE.md** (and AGENTS.md) | Something every session must know, pointing to its note | Every session |
| **Repo test** | A technical mistake that recurred although a note existed | Every test run |
| **Skill file** | A fix for a skill that gave a wrong result | When the skill runs |

**No duplication.** Personal corrections never go to knowledge. Domain rules never go to memory. Link instead of copying.

---

## Runtime artifacts (per-project)

When scribe runs in any project, it creates:

```
<project-root>/
└── .scribe/
    ├── knowledge/*.md   ← git-tracked team knowledge
    ├── hook.log         ← hook execution log
    └── turn_count       ← Stop hook counter
```

Shared notes live outside any project, in `~/.claude/scribe/shared/*.md` (created on first run).

Add to project `.gitignore`:

```
.scribe/
!.scribe/knowledge/
!.scribe/knowledge/**
```

---

## Configuration

`REVIEW_INTERVAL` (default `10`) — change in `hooks/stop.py` to adjust reflection frequency.

`CLAUDE_PROJECT_DIR` — if set by Claude Code, used as project root for `.scribe/`. Falls back to current working directory.

`SCRIBE_SHARED_DIR` (default `~/.claude/scribe/shared`) — folder of shared notes listed in every project.

`SCRIBE_CATALOG_BUDGET` (default `6000`) — most characters the session-start title list may use.

---

## Plugin layout

```
scribe/
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── hooks/
│   ├── _scribe_paths.py    ← shared path resolver
│   ├── session_start.py    ← resets the turn counter, lists note titles
│   ├── stop.py             ← counts turns, injects reflect prompt every 10
│   ├── run-hook.cmd        ← cross-platform wrapper (Windows + Unix)
│   └── hooks.json          ← Claude Code hook registration
├── skills/
│   └── scribe-review/
│       ├── SKILL.md
│       └── templates/
│           └── knowledge.md
└── tests/
    └── test_hooks.py       ← runs both hooks through run-hook.cmd (python3 -m unittest)
```

---

## License

MIT
