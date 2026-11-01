"""Run the hooks the way Claude Code does (through run-hook.cmd), and the
scripts/scribe.py command line, in temp folders.

python3 -m unittest discover -s tests
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"


def run(hook, project, shared, stdin="{}", budget=None, env_extra=None, raw=False):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), SCRIBE_SHARED_DIR=str(shared))
    if budget is not None:
        env["SCRIBE_CATALOG_BUDGET"] = str(budget)
    env.update(env_extra or {})
    # The wrapper has no shebang (it is also a .cmd file); Claude Code's shell runs it as
    # a shell script, so run it with sh the same way.
    proc = subprocess.run(["/bin/sh", str(HOOKS / "run-hook.cmd"), hook], input=stdin, env=env,
                          capture_output=True, text=True, check=True)
    if raw:
        return proc
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def call(project, shared, tool, tool_input, session="sess-0001", **kw):
    """One PreToolUse event."""
    payload = json.dumps({"session_id": session, "hook_event_name": "PreToolUse",
                          "tool_name": tool, "tool_input": tool_input})
    return run("pre-tool-use", project, shared, stdin=payload, **kw)


def note(folder, stem, description="", updated="2026-10-29", extra=(), body="Body line."):
    folder.mkdir(parents=True, exist_ok=True)
    head = ["---", f"name: {stem}"]
    head += [f"description: {description}"] if description else []
    head += [f"updated: {updated}", *extra, "---", "", body]
    (folder / f"{stem}.md").write_text("\n".join(head), encoding="utf-8")


def zsh_note(folder, enforce=None, pattern=r"echo\s+="):
    """The note from 2026-11-01: its title was in the session-start list, and the agent
    still ran `echo =====` twice (zsh reads `=====` as a command path)."""
    extra = ["triggers:", f"  Bash: '{pattern}'   # a word that starts with = after echo",
             "fix: \"Quote it: echo '====='\""]
    extra += [f"enforce: {enforce}"] if enforce else []
    note(folder, "zsh-is-the-mac-shell",
         "The Bash tool on a Mac runs zsh: `echo =====` fails with \"= not found\".",
         updated="2026-11-01", extra=extra)


def iso(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def write_log(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def read_log(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class Folders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.project, self.shared = base / "proj", base / "shared"
        self.knowledge = self.project / ".scribe" / "knowledge"
        self.project.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def context(self, **kw):
        out = run("session-start", self.project, self.shared, **kw)
        return out and out["hookSpecificOutput"]["additionalContext"]

    def call(self, tool, tool_input, **kw):
        return call(self.project, self.shared, tool, tool_input, **kw)

    def warning(self, tool, tool_input, **kw):
        out = self.call(tool, tool_input, **kw)
        self.assertIsNotNone(out, f"no warning for {tool} {tool_input}")
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
        return out["hookSpecificOutput"]["additionalContext"]


class SessionStartCatalog(Folders):
    def test_lists_shared_first_then_project(self):
        note(self.shared, "zsh-traps", "zsh is the Mac shell")
        note(self.knowledge, "deploy-gate", "deploy only through the gate")
        text = self.context()
        self.assertIn("- zsh-traps — zsh is the Mac shell", text)
        self.assertIn("- deploy-gate — deploy only through the gate", text)
        self.assertLess(text.index("zsh-traps"), text.index("deploy-gate"))

    def test_newest_first(self):
        note(self.shared, "old", "old", updated="2026-01-01")
        note(self.shared, "new", "new", updated="2026-10-29")
        text = self.context()
        self.assertLess(text.index("- new"), text.index("- old"))

    def test_no_output_without_notes_and_counter_reset(self):
        self.assertIsNone(run("session-start", self.project, self.shared))
        self.assertEqual((self.project / ".scribe" / "turn_count").read_text(), "0")
        self.assertTrue(self.shared.is_dir())

    def test_large_project_folds_to_pointer_within_budget(self):
        note(self.shared, "zsh-traps", "zsh is the Mac shell")
        for i in range(600):
            note(self.knowledge, f"long-note-name-for-folding-{i:04d}", "x" * 120)
        (self.project / "docs").mkdir()
        (self.project / "docs" / "INDEX.md").write_text("index", encoding="utf-8")
        text = self.context(budget=6000)
        self.assertLessEqual(len(text), 6000)
        self.assertIn("- zsh-traps — zsh is the Mac shell", text)
        self.assertIn("600 notes, too many to list", text)
        self.assertIn("docs/INDEX.md", text)
        self.assertNotIn("long-note-name-for-folding-0000", text)

    def test_tiny_budget_still_fits(self):
        for i in range(50):
            note(self.shared, f"shared-note-{i:02d}", "y" * 100)
        text = self.context(budget=400)
        self.assertLessEqual(len(text), 400)
        self.assertIn("older shared notes not listed", text)

    def test_title_folded_and_heading_fallbacks(self):
        self.knowledge.mkdir(parents=True)
        (self.knowledge / "a.md").write_text("---\ntitle: Title only\ntags: [x]\n---\n\nBody",
                                             encoding="utf-8")
        (self.knowledge / "b.md").write_text("---\nname: b\ndescription: >-\n  folded\n  text\n---\nBody",
                                             encoding="utf-8")
        (self.knowledge / "c.md").write_text("# Heading only\n\nBody", encoding="utf-8")
        (self.knowledge / "INDEX.md").write_text("# index", encoding="utf-8")
        (self.knowledge / "log.md").write_text("# log", encoding="utf-8")
        text = self.context()
        self.assertIn("- a — Title only", text)
        self.assertIn("- b — folded text", text)
        self.assertIn("- c — Heading only", text)
        self.assertNotIn("- INDEX", text)
        self.assertNotIn("- log", text)
        self.assertIn("found with grep", text)
        self.assertIn("`updated:`", text)

    def test_description_quoting(self):
        """A description that starts with a quote but goes on stays whole; a quoted one loses
        its quotes, and a comment after them."""
        self.shared.mkdir()
        (self.shared / "q.md").write_text(
            '---\nname: q\ndescription: "Hedge the crash" is a recurring ask\n---\nBody', encoding="utf-8")
        (self.shared / "r.md").write_text(
            "---\nname: r\ndescription: 'it''s quoted'   # comment\n---\nBody", encoding="utf-8")
        text = self.context()
        self.assertIn('- q — "Hedge the crash" is a recurring ask', text)
        self.assertIn("- r — it's quoted", text)


class SessionStartMapAndRanking(Folders):
    MAP = ("---\nname: map\nupdated: 2026-11-01\n---\n\n## Key facts\n- Ships only with `make release`\n\n"
           "## Situation → search words → note\n- before a release → `release|deploy|ship` → deploy-gate\n")

    def test_project_map_comes_first(self):
        note(self.shared, "zsh-traps", "zsh is the Mac shell")
        note(self.knowledge, "deploy-gate", "deploy only through the gate")
        (self.knowledge / "MAP.md").write_text(self.MAP, encoding="utf-8")
        text = self.context()
        self.assertTrue(text.startswith("## scribe project map (`.scribe/knowledge/MAP.md`)\n## Key facts"))
        self.assertIn("- before a release → `release|deploy|ship` → deploy-gate", text)
        self.assertLess(text.index("Key facts"), text.index("## scribe notes"))
        self.assertNotIn("name: map", text)
        self.assertNotIn("- map", text)  # the map is not listed as a note

    def test_long_map_is_cut_and_everything_fits(self):
        self.knowledge.mkdir(parents=True)
        lines = "\n".join(f"- situation {i} → `word{i}` → note-{i}" for i in range(300))
        (self.knowledge / "MAP.md").write_text(f"---\nname: map\n---\n{lines}\n", encoding="utf-8")
        for i in range(40):
            note(self.shared, f"shared-note-{i:02d}", "z" * 120)
        text = self.context(budget=3000)
        self.assertLessEqual(len(text), 3000)
        self.assertIn("… (cut; read `.scribe/knowledge/MAP.md` for the rest)", text)
        self.assertNotIn("situation 299", text)
        self.assertIn("## scribe notes", text)

    def test_notes_hit_recently_come_first(self):
        now = time.time()
        note(self.shared, "old-but-hit", "a", updated="2026-01-01")
        note(self.shared, "newest", "b", updated="2026-10-30")
        note(self.shared, "hit-long-ago", "c", updated="2026-01-02")
        write_log(self.shared / ".hits.jsonl", [{"t": iso(now - 400 * 86400), "kind": "start"}]
                  + [{"t": iso(now - 3600), "note": "old-but-hit", "kind": "warn"}] * 2
                  + [{"t": iso(now - 40 * 86400), "note": "hit-long-ago", "kind": "block"}] * 5
                  + [{"t": iso(now - 60), "note": "newest", "kind": "read"}] * 9)
        text = self.context()
        self.assertIn("- old-but-hit [2 hits] — a", text)
        self.assertLess(text.index("- old-but-hit"), text.index("- newest — b"))
        self.assertLess(text.index("- newest"), text.index("- hit-long-ago — c"))  # hits over 30 days old
        self.assertIn("[N hits]", text)

    def test_garden_reminder_after_a_month(self):
        note(self.shared, "a", "x")
        write_log(self.shared / ".hits.jsonl", [{"t": iso(time.time() - 40 * 86400), "kind": "start"}])
        self.assertIn("notes not gardened for 40 days. /scribe-garden", self.context())
        (self.shared / ".garden_last").write_text(iso(time.time() - 86400), encoding="utf-8")
        self.assertNotIn("not gardened", self.context())

    def test_fresh_install_starts_both_hit_logs_quietly(self):
        note(self.shared, "a", "x")
        note(self.knowledge, "b", "y")
        text = self.context()
        self.assertNotIn("not gardened", text)
        self.assertNotIn("[N hits]", text)  # no note has triggers
        for log in (self.shared / ".hits.jsonl", self.project / ".scribe" / "hits.jsonl"):
            self.assertEqual(read_log(log)[0]["kind"], "start")


class PreToolUseTriggers(Folders):
    def test_no_triggers_no_output(self):
        note(self.shared, "plain", "a note without triggers")
        self.assertIsNone(self.call("Bash", {"command": "echo ====="}))
        self.assertIsNone(call(self.project, self.shared, "Bash", {"command": "ls"}, session=""))

    def test_zsh_echo_equals_is_caught_on_the_call(self):
        zsh_note(self.shared)
        text = self.warning("Bash", {"command": "echo =====", "description": "print a rule"})
        self.assertIn("scribe note `zsh-is-the-mac-shell` (shared,", text)
        self.assertIn("matches this Bash call (trigger Bash: `echo\\s+=`)", text)
        self.assertIn('`echo =====` fails with "= not found"', text)
        self.assertIn("Fix: Quote it: echo '====='", text)
        self.warning("Bash", {"command": "cd /tmp && echo ===== && ls"})
        for fine in ("echo '====='", 'echo "====="', "printf '%s\\n' '====='"):
            self.assertIsNone(self.call("Bash", {"command": fine, "description": "echo = sign"}), fine)

    def test_block_denies_with_the_fix(self):
        zsh_note(self.shared, enforce="block")
        out = self.call("Bash", {"command": "echo ====="})["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        reason = out["permissionDecisionReason"]
        self.assertTrue(reason.startswith("Blocked by scribe note `zsh-is-the-mac-shell`"), reason)
        self.assertIn("Fix: Quote it: echo '====='", reason)
        self.assertIn("Rewrite the call.", reason)
        self.assertNotIn("additionalContext", out)

    def test_repeat_suggests_block_unless_warn_was_chosen(self):
        zsh_note(self.shared)
        first = self.warning("Bash", {"command": "echo ====="})
        self.assertNotIn("enforce: block` is for", first)
        second = self.warning("Bash", {"command": "echo ====="})
        self.assertIn("This trigger fired once before", second)
        self.assertIn("1 in this session", second)
        self.assertIn("`enforce: block` is for", second)
        third = self.warning("Bash", {"command": "echo ====="}, session="other-session")
        self.assertIn("fired 2 times before", third)
        self.assertIn("0 in this session", third)
        zsh_note(self.shared, enforce="warn")  # the user chose a warning: no more suggestions
        self.assertNotIn("enforce: block", self.warning("Bash", {"command": "echo ====="}))

    def test_hits_go_to_the_log_of_the_notes_side(self):
        zsh_note(self.shared)
        note(self.knowledge, "no-env-writes", "never write .env",
             extra=["triggers:", "  Write|Edit:", "    - '(^|/)\\.env$'", "    - 'secrets/'"])
        self.warning("Bash", {"command": "echo ====="}, session="abcdefgh-1234")
        self.warning("Write", {"file_path": "/repo/.env", "content": "A=1"})
        self.warning("Edit", {"file_path": "/repo/secrets/key", "old_string": "a", "new_string": "b"})
        self.assertIsNone(self.call("Write", {"file_path": "/repo/.env.example", "content": "A="}))
        shared_log = read_log(self.shared / ".hits.jsonl")
        project_log = read_log(self.project / ".scribe" / "hits.jsonl")
        self.assertEqual(shared_log[0]["kind"], "start")
        self.assertEqual([(e["note"], e["kind"], e["session"]) for e in shared_log[1:]],
                         [("zsh-is-the-mac-shell", "warn", "abcdefgh")])
        self.assertEqual([(e["note"], e["tool"]) for e in project_log[1:]],
                         [("no-env-writes", "Write"), ("no-env-writes", "Edit")])

    def test_tool_keys_and_fields(self):
        note(self.knowledge, "aware-datetimes", "use datetime.now(UTC)",
             extra=["triggers:", "  Edit.new_string: 'utcnow\\('",
                    "  mcp__.*__navigate: 'reddit\\.com'", "  Bash|PowerShell: 'rm -rf /'"])
        self.assertIsNone(self.call("Edit", {"file_path": "a.py", "old_string": "datetime.utcnow()",
                                             "new_string": "datetime.now(UTC)"}))  # the fix itself
        self.warning("Edit", {"file_path": "a.py", "old_string": "x", "new_string": "datetime.utcnow()"})
        self.warning("mcp__Claude_Browser__navigate", {"url": "https://www.reddit.com/r/x"})
        self.assertIsNone(self.call("mcp__Claude_Browser__find", {"query": "reddit.com"}))
        self.warning("PowerShell", {"command": "rm -rf /"})
        note(self.knowledge, "exact-names", "x", extra=["triggers:", "  Edit: 'zzz'"])
        self.assertIsNone(self.call("NotebookEdit", {"new_source": "zzz"}))  # exact, like hook matchers
        note(self.knowledge, "any-tool", "x", extra=["triggers:", "  '*': 'qqq-marker'"])
        self.warning("Grep", {"pattern": "qqq-marker"})

    def test_cache_follows_note_edits(self):
        zsh_note(self.shared)
        self.warning("Bash", {"command": "echo ====="})
        self.assertTrue((self.project / ".scribe" / "triggers.json").is_file())
        zsh_note(self.shared, pattern=r"printf\s+=")
        self.assertIsNone(self.call("Bash", {"command": "echo ====="}))
        self.warning("Bash", {"command": "printf ====="})
        (self.shared / "zsh-is-the-mac-shell.md").unlink()
        self.assertIsNone(self.call("Bash", {"command": "printf ====="}))

    def test_bad_pattern_is_skipped_and_named_at_session_start(self):
        note(self.shared, "broken", "bad regex", extra=["triggers:", "  Bash: 'echo ('"])
        zsh_note(self.shared)
        self.warning("Bash", {"command": "echo ====="})
        text = self.context()
        self.assertIn("scribe: skipped 1 trigger(s) that do not parse or compile: broken (Bash)", text)

    def test_reading_a_note_is_logged(self):
        note(self.shared, "plain", "x")
        note(self.knowledge, "local", "y")
        self.assertIsNone(self.call("Read", {"file_path": str(self.shared / "plain.md")}))
        self.call("Read", {"file_path": str(self.knowledge / "local.md")})
        self.call("Read", {"file_path": str(self.project / "README.md")})
        self.call("Read", {"file_path": str(self.knowledge / "MAP.md")})
        self.assertEqual([(e["note"], e["kind"]) for e in read_log(self.shared / ".hits.jsonl")[1:]],
                         [("plain", "read")])
        self.assertEqual([e["note"] for e in read_log(self.project / ".scribe" / "hits.jsonl")[1:]],
                         ["local"])

    def test_stays_import_light(self):
        """It runs before every tool call, so it must not import logging or pathlib (~8 ms)."""
        zsh_note(self.shared)
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo ====="}})
        proc = run("pre-tool-use", self.project, self.shared, stdin=payload, raw=True,
                   env_extra={"PYTHONPROFILEIMPORTTIME": "1"})
        imported = {line.rsplit("|", 1)[-1].strip() for line in proc.stderr.splitlines()}
        self.assertIn("_scribe_core", imported)
        self.assertFalse(imported & {"logging", "pathlib", "calendar"}, imported)

    def test_broken_input_never_blocks(self):
        zsh_note(self.shared)
        for stdin in ("", "not json", '{"tool_name": "Bash", "tool_input": "echo ====="}'):
            self.assertIsNone(run("pre-tool-use", self.project, self.shared, stdin=stdin))


class StopPrompt(unittest.TestCase):
    def test_every_tenth_turn_and_names_shared_folder(self):
        with tempfile.TemporaryDirectory() as t:
            project, shared = Path(t) / "proj", Path(t) / "shared"
            project.mkdir()
            run("session-start", project, shared)
            outs = [run("stop", project, shared, stdin='{"session_id": "t"}') for _ in range(20)]
            self.assertEqual([i + 1 for i, o in enumerate(outs) if o], [10, 20])
            self.assertEqual(outs[9]["decision"], "block")
            self.assertIn(str(shared), outs[9]["reason"])
            self.assertIn("→ TRIGGER:", outs[9]["reason"])
            self.assertNotIn("fired in this session", outs[9]["reason"])
            self.assertIsNone(run("stop", project, shared, stdin='{"stop_hook_active": true}'))

    def test_lists_the_triggers_that_fired_this_session(self):
        with tempfile.TemporaryDirectory() as t:
            project, shared = Path(t) / "proj", Path(t) / "shared"
            project.mkdir()
            zsh_note(shared)
            run("session-start", project, shared)
            for session in ("abcdefgh-1", "abcdefgh-1", "zzzzzzzz-2"):
                call(project, shared, "Bash", {"command": "echo ====="}, session=session)
            stop = '{"session_id": "abcdefgh-1"}'
            reason = [run("stop", project, shared, stdin=stop) for _ in range(10)][-1]["reason"]
            self.assertIn("Triggers that fired in this session: zsh-is-the-mac-shell (shared) 2× warn.",
                          reason)
            self.assertIn("propose `enforce: block`", reason)


class ScribeCli(Folders):
    def cli(self, *args):
        env = dict(os.environ, SCRIBE_SHARED_DIR=str(self.shared))
        env.pop("CLAUDE_PROJECT_DIR", None)
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "scribe.py"), "--project",
                               str(self.project), *args], env=env, capture_output=True, text=True,
                              check=True).stdout

    def test_search_ranks_spelling_variants(self):
        note(self.shared, "zsh-is-the-mac-shell", "The Mac Bash tool runs zsh; echo ===== fails")
        note(self.knowledge, "test-server-login", "Der Prüf-Server ist nur hinter dem VPN erreichbar")
        note(self.knowledge, "unrelated", "nothing to see")
        nfd = "Pru\u0308f server"  # macOS hands out decomposed (NFD) text; notes are NFC
        out = self.cli("search", nfd, "test server", "staging")
        self.assertIn("1. test-server-login — project", out)
        self.assertIn(f"matched: {nfd}, test server", out)
        self.assertNotIn("unrelated", out)
        self.assertIn("1. zsh-is-the-mac-shell — shared", self.cli("search", "zsh", "shells", "SHELL"))
        self.assertIn("No note matches any of: kubernetes, k8s", self.cli("search", "kubernetes", "k8s"))

    def test_search_follows_the_project_map(self):
        note(self.knowledge, "a-note", "alpha")
        note(self.knowledge, "b-note", "beta")
        (self.knowledge / "MAP.md").write_text("- before a release → `release` → b-note\n",
                                               encoding="utf-8")
        out = self.cli("search", "release")
        self.assertIn("1. b-note", out)
        self.assertNotIn("a-note", out)

    def test_search_reads_extra_record_folders(self):
        docs = self.project / "docs" / "decisions"
        note(docs, "why-postgres", "we chose postgres over mysql")
        self.assertIn("1. why-postgres — docs", self.cli("search", "--dir", "docs", "postgres"))

    def test_garden_report_and_done(self):
        now = time.time()
        today = iso(now)[:10]
        zsh_note(self.shared)
        note(self.shared, "zsh-mac-shell-traps", "zsh traps", updated="2026-01-01",
             extra=["triggers:", "  Bash: 'echo\\s+='"])
        note(self.knowledge, "stale-claim", "the export works", updated="2026-01-01",
             body="Fixed in v1.2.0 and still fine.")
        note(self.knowledge, "used-old", "old but read", updated="2026-01-01")
        note(self.knowledge, "fresh", "new note", updated=today)
        note(self.knowledge, "bad-trigger", "x", updated=today, extra=["triggers:", "  Bash: '('"])
        (self.knowledge / "MAP.md").write_text("- releases → `release` → fresh, gone-note\n",
                                               encoding="utf-8")
        write_log(self.shared / ".hits.jsonl", [{"t": iso(now - 400 * 86400), "kind": "start"},
                                                {"t": iso(now - 380 * 86400), "note": "x", "kind": "warn"}]
                  + [{"t": iso(now - 3600), "note": "zsh-is-the-mac-shell", "kind": "warn"}] * 4)
        write_log(self.project / ".scribe" / "hits.jsonl",
                  [{"t": iso(now - 90 * 86400), "kind": "start"},
                   {"t": iso(now - 86400), "note": "used-old", "kind": "read"}])
        out = self.cli("garden")
        dup = out.split("## 1.")[1].split("## 2.")[0]
        self.assertIn("shared/zsh-is-the-mac-shell ↔ shared/zsh-mac-shell-traps: same trigger", dup)
        claims = out.split("## 2.")[1].split("## 3.")[0]
        self.assertIn("project/stale-claim (2026-01-01): Fixed in v1.2.0 and still fine.", claims)
        prune = out.split("## 3.")[1].split("## 4.")[0]
        self.assertIn("project/stale-claim", prune)
        self.assertNotIn("used-old", prune)
        self.assertNotIn("fresh", prune)
        self.assertIn("shared/zsh-mac-shell-traps (updated 2026-01-01) — its trigger never fired", prune)
        promote = out.split("## 4.")[1].split("## 5.")[0]
        self.assertIn("shared/zsh-is-the-mac-shell: 4 hits (warn) → `enforce: block`", promote)
        self.assertIn("project/bad-trigger `Bash`: does not compile", out.split("## 5.")[1])
        mapped = out.split("## 6.")[1]
        self.assertIn("names `gone-note`, which is not a note", mapped)
        self.assertIn("Not on the map: bad-trigger, stale-claim, used-old", mapped)
        self.assertFalse((self.project / ".scribe" / "triggers.json").exists())  # the report only reads

        self.assertIn("dropped 1 hit lines", self.cli("garden", "--done"))
        log = read_log(self.shared / ".hits.jsonl")
        self.assertEqual(log[0]["kind"], "start")
        self.assertEqual(len(log), 5)
        self.assertTrue((self.shared / ".garden_last").is_file())
        self.assertTrue((self.project / ".scribe" / "garden_last").is_file())

    def test_garden_status_words_in_another_language(self):
        note(self.knowledge, "export", "Export nach CSV", updated="2026-01-01", body="Ist seit 2.1 behoben.")
        self.assertIn("- none", self.cli("garden").split("## 2.")[1].split("## 3.")[0])
        claims = self.cli("garden", "--status-words", "behoben|funktioniert").split("## 2.")[1]
        self.assertIn("project/export (2026-01-01): Ist seit 2.1 behoben.", claims)

    def test_garden_waits_for_sixty_days_of_hits(self):
        note(self.knowledge, "old", "x", updated="2026-01-01")
        write_log(self.project / ".scribe" / "hits.jsonl", [{"t": iso(time.time() - 10 * 86400),
                                                             "kind": "start"}])
        self.assertIn("project: not judged yet; hits are logged since", self.cli("garden"))


if __name__ == "__main__":
    unittest.main()
