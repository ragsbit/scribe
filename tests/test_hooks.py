"""Run both hooks the way Claude Code does (through run-hook.cmd) in temp folders.

python3 -m unittest discover -s tests
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


def run(hook, project, shared, stdin="{}", budget=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), SCRIBE_SHARED_DIR=str(shared))
    if budget is not None:
        env["SCRIBE_CATALOG_BUDGET"] = str(budget)
    # The wrapper has no shebang (it is also a .cmd file); Claude Code's shell runs it as
    # a shell script, so run it with sh the same way.
    out = subprocess.run(["/bin/sh", str(HOOKS / "run-hook.cmd"), hook], input=stdin, env=env,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out) if out.strip() else None


def note(folder, stem, description="", updated="2026-10-29"):
    folder.mkdir(parents=True, exist_ok=True)
    head = ["---", f"name: {stem}"]
    head += [f"description: {description}"] if description else []
    head += [f"updated: {updated}", "---", "", "Body line."]
    (folder / f"{stem}.md").write_text("\n".join(head), encoding="utf-8")


class SessionStartCatalog(unittest.TestCase):
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
            self.assertIsNone(run("stop", project, shared, stdin='{"stop_hook_active": true}'))


if __name__ == "__main__":
    unittest.main()
