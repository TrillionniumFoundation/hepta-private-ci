"""Model-free fast-forward integration tests for the LoCoMo publisher formatter.

Uses a local bare Git repository only; never obtains Qwen weights or labels.
The production workflow's actual shell performs its own blob/AST checks.
"""

import ast
from pathlib import Path
import subprocess
import tempfile
import unittest

BRANCH = "codex/memory-cell-evidence-20261008"
SOURCE = "scripts/memory_cell/locomo_publisher_support_reader.py"
TEST = "scripts/memory_cell/test_locomo_publisher_support_reader.py"


def git(cwd, *args, check=True):
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=False, capture_output=True, text=True
    )
    if check and result.returncode:
        raise AssertionError((args, result.stderr, result.stdout))
    return result.stdout.strip() if check else result


class FormatFastForwardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        git(self.root, "init", "--bare", "-q", str(self.remote))
        self.author = self.root / "author"
        git(self.root, "clone", "-q", str(self.remote), str(self.author))
        git(self.author, "config", "user.name", "Test")
        git(self.author, "config", "user.email", "test@example.com")
        git(self.author, "checkout", "-q", "-b", BRANCH)
        for name in (SOURCE, TEST):
            path = self.author / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("value=1\n", encoding="utf-8")
        (self.author / "stem.txt").write_text("old\n", encoding="utf-8")
        git(self.author, "add", ".")
        git(self.author, "commit", "-qm", "original source")
        git(self.author, "push", "-q", "-u", "origin", BRANCH)
        self.original = git(self.author, "rev-parse", "HEAD")
        self.formatter = self.root / "formatter"
        git(self.root, "clone", "-q", str(self.remote), str(self.formatter))
        git(self.formatter, "checkout", "-q", BRANCH)
        git(self.formatter, "config", "user.name", "Formatter")
        git(self.formatter, "config", "user.email", "fmt@example.com")
        for name in (SOURCE, TEST):
            (self.formatter / name).write_text("value = 1\n", encoding="utf-8")
        self.patch = self.root / "format.patch"
        self.patch.write_text(git(self.formatter, "diff", "--binary", "--", SOURCE, TEST) + "\n")
        self.assertTrue(self.patch.stat().st_size > 0)

    def reconcile(self):
        git(self.formatter, "fetch", "-q", "origin", "refs/heads/" + BRANCH)
        current = git(self.formatter, "rev-parse", "FETCH_HEAD")
        for path in (SOURCE, TEST):
            before = git(self.formatter, "rev-parse", self.original + ":" + path)
            now = git(self.formatter, "rev-parse", current + ":" + path)
            if before != now:
                raise ValueError("concurrent target edit refused: " + path)
        git(self.formatter, "reset", "-q", "--hard", current)
        git(self.formatter, "apply", "--check", str(self.patch))
        git(self.formatter, "apply", str(self.patch))
        for path in (SOURCE, TEST):
            before = git(self.formatter, "show", "HEAD:" + path)
            after = (self.formatter / path).read_text(encoding="utf-8")
            if ast.dump(ast.parse(before)) != ast.dump(ast.parse(after)):
                raise ValueError("AST changed")
        git(self.formatter, "diff", "--check")
        git(self.formatter, "add", "--", SOURCE, TEST)
        git(self.formatter, "commit", "-qm", "safe formatted sources")
        git(self.formatter, "push", "-q", "origin", "HEAD:refs/heads/" + BRANCH)

    def test_parallel_unrelated_stem_push_is_preserved(self):
        (self.author / "stem.txt").write_text("concurrent Stem work\n")
        git(self.author, "add", "stem.txt")
        git(self.author, "commit", "-qm", "unrelated Stem change")
        git(self.author, "push", "-q", "origin", BRANCH)
        self.reconcile()
        git(self.author, "pull", "-q", "--ff-only")
        self.assertEqual((self.author / "stem.txt").read_text(), "concurrent Stem work\n")
        self.assertEqual((self.author / SOURCE).read_text(), "value = 1\n")
        self.assertEqual((self.author / TEST).read_text(), "value = 1\n")

    def test_parallel_target_edit_is_rejected_without_push(self):
        (self.author / SOURCE).write_text("value=2\n")
        git(self.author, "add", SOURCE)
        git(self.author, "commit", "-qm", "parallel publisher edit")
        git(self.author, "push", "-q", "origin", BRANCH)
        with self.assertRaisesRegex(ValueError, "concurrent target edit refused"):
            self.reconcile()
        git(self.author, "pull", "-q", "--ff-only")
        self.assertEqual((self.author / SOURCE).read_text(), "value=2\n")
        self.assertEqual((self.author / TEST).read_text(), "value=1\n")

    def test_checked_in_workflow_retains_source_and_ast_guards(self):
        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/hepta-memory-locomo-publisher-astfmt.yml"
        )
        if not workflow.is_file():
            self.skipTest("workflow file is only present in the repository checkout")
        source = workflow.read_text(encoding="utf-8")
        for needed in (
            "git diff --binary --", "git apply --check",
            'original_blob="$(git rev-parse "$EXPECTED_HEAD:$path")"',
            'current_blob="$(git rev-parse "$current:$path")"',
            "if ast.dump(ast.parse(before)) != ast.dump(ast.parse(after)):",
            'git push origin "HEAD:refs/heads/$TARGET_BRANCH"',
            'for attempt in 1 2 3 4 5; do',
        ):
            self.assertIn(needed, source)
        self.assertNotIn("git push --force", source)


if __name__ == "__main__":
    unittest.main()