---
name: scribe-garden
description: Monthly upkeep of scribe notes, shared and this project's. Merges duplicates, re-checks status claims against the code, proposes pruning notes that no trigger hit and no session opened in 60 days, and proposes promoting notes whose trigger fired 3+ times (to `enforce: block`, or to a repo test). Use once a month, when the session-start list says the notes were not gardened for a month, or when the user asks to clean up, tidy or prune the notes.
allowed-tools:
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scribe.py" *)
  - Read(~/.claude/scribe/shared/**)
---

# /scribe-garden

## Step 1: Get the report
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scribe.py" --project "${CLAUDE_PROJECT_DIR}" garden
```
(`python` where `python3` is missing.) The report only reads. Its sections: possible duplicates,
status claims to re-check, prune candidates, promote candidates, trigger problems, project map.
It spots status claims by English words ("fixed", "works", "not yet") and versions. When notes are
written in another language too, add that language's words for the same claims:
`garden --status-words 'word|word|word'`.

The numbers come from the hits logs that the PreToolUse hook writes: `.scribe/hits.jsonl` for this
project's notes and `<shared folder>/.hits.jsonl` for shared notes. A trigger match is a hit; a Read
of a note counts as a use. Pruning is judged only once the logs are 60 days old.

## Step 2: Work through the report — read before you propose
1. **Duplicates**: read both notes. Merge only when they say the same thing: keep the clearer name,
   combine the facts (keep every `**Source:**` line and every trigger), set `updated:` to today,
   delete the other file, then grep for its name and fix the links (MAP.md, CLAUDE.md and AGENTS.md
   pointers, Source lines). Notes that are related but different stay apart.
2. **Status claims**: check each listed line against the code or the environment now. Correct what is
   wrong, mark "(unverified)" what you cannot check, and set `updated:`.
3. **Prune candidates**: read each one and propose one of: delete it (a project note stays in git
   history), move a shared note to `<shared folder>/archive/` (no longer listed, still greppable),
   keep it (say why), or fix a trigger that can never fire.
4. **Promote candidates**: a warning note → propose `enforce: block` with a one-line `fix:`. A block note
   that keeps firing → propose a repo test that fails on the pattern, and a CLAUDE.md line if every
   session must know the rule.
5. **Trigger problems**: fix the pattern (single quotes; check it with
   `python3 -c "import re; print(bool(re.search(r'<pattern>', '<the mistake>')))"`).
6. **Notes without triggers** that describe a mistake you can see in a tool input (a command, a path,
   a URL): propose a `triggers:` line (syntax in the scribe-review skill).
7. **Project map**: when missing, draft it from `${CLAUDE_PLUGIN_ROOT}/skills/scribe-review/templates/map.md`;
   add the notes that are not on it; drop lines that name a missing note. Keep it under about 1,500
   characters, since session start cuts the rest.

## Step 3: Ask once, then apply
Show the user one list with one line per change: what, which note, why. Apply what they approve —
or apply directly if the user or the project instructions say records need no approval.

## Step 4: Record the run
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scribe.py" --project "${CLAUDE_PROJECT_DIR}" garden --done
```
This stamps today's date, so the session-start reminder stays away for a month, and drops hit lines
older than a year. Report in one line: merged N, corrected N, pruned N, promoted N.
