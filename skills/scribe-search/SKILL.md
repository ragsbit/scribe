---
name: scribe-search
description: Search what scribe notes already say before acting or answering — shared notes (~/.claude/scribe/shared/), this project's notes (.scribe/knowledge/ and the record folders its CLAUDE.md names) and the project map. Searches spelling variants together (the user's language and English, spacing, transliteration, abbreviations), reads the top 3, and re-checks their status claims against the code, fixing a note that turned out wrong. Use when a task touches something the notes may cover, when a session-start title is not enough to decide, or when the user asks whether something was already learned or decided ("did we", "last time", "what do the notes say").
argument-hint: <topic>
allowed-tools:
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scribe.py" *)
  - Read(~/.claude/scribe/shared/**)
---

# /scribe-search

Topic: $ARGUMENTS

## Step 1: Spell the topic several ways
Notes are written by different sessions, often in more than one language. Make 3–8 search words:
- the same thing in every language the notes use: the user's language and English
  (deploy / release / ship, and the user's word for it)
- transliterations both ways: a name written in the user's script and in Latin letters
  (GitHub, Claude, Kubernetes as the user's language spells them)
- abbreviations and full names (k8s / kubernetes, PR / pull request)
- word stems (deploy, not deployment; the bare word, not an inflected form)

The script ignores case, spaces, hyphens and underscores and normalises Unicode, so
`test server` also finds `test-server` and `TestServer`, in any script.

## Step 2: Rank the notes
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scribe.py" --project "${CLAUDE_PROJECT_DIR}" search <word> <word> ...
```
- Add `--dir <folder>` for each record folder the project's CLAUDE.md or AGENTS.md names besides `.scribe/knowledge/`.
- Use `python` where `python3` is missing (Windows).
- If the script cannot run: `grep -rilE "<word>|<word>" ~/.claude/scribe/shared .scribe/knowledge --include="*.md"`.

Names weigh most, then descriptions and triggers, then body lines; a note that matches more of the
words, or that the project map points to for them, ranks higher.

## Step 3: Read the top 3
Read the top three notes in full; read more only when scores tie. Drop a note that clearly does not fit.

## Step 4: Re-check status claims
A note's claims — "fixed", "works", "not supported yet", a version, a count — were true on its
`updated:` date, not necessarily today. For each claim the task depends on, check it now against
the code or the environment: read the file, run the command, or `git log --since=<updated>` on the
files the note names.
- Still true → use it.
- Wrong → fix that line in the note, set `updated:` to today, and say so in one line.
- Cannot check → say "(unverified)" wherever you rely on it.

## Step 5: Answer
Answer from the notes and name each note you used by its path. If no note covers the topic, say so
plainly. When the answer is found later in the session, it may deserve a note (/scribe-review).
