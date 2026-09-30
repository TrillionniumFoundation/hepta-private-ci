from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/channel_matrix_source_provenance.py"
spec = importlib.util.spec_from_file_location("channel_matrix_source_provenance_test", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class SourceProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkout"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "fixture")
        self.git("config", "user.email", "fixture@example.test")
        self.source = self.root / "codex-rs/hepta-matrix-sdk/src/lib.rs"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("pub fn source() {}\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "source")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.roots = ("codex-rs/hepta-matrix-sdk",)

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout

    def build(self):
        with mock.patch.object(module, "SOURCE_ROOTS", self.roots):
            return module.build(self.root, self.head, "source-head")

    def validate(self, row):
        return module.validate_receipt(
            row,
            expected_stage="source-head",
            expected_sha=self.head,
            expected_tree=row["checkoutTree"],
        )

    def test_tracked_inputs_have_complete_reproducible_provenance(self) -> None:
        row = self.build()
        self.assertTrue(row["valid"])
        self.assertEqual(row["scan"]["defaultCommand"], ["git", "ls-files", "-z"])
        self.assertEqual(row["scan"]["perFileGitProcesses"], 0)
        self.assertTrue(row["scan"]["cleanBefore"]["clean"])
        self.assertTrue(row["scan"]["cleanAfter"]["clean"])
        self.assertTrue(row["scan"]["cleanBefore"]["workspaceStatus"]["empty"])
        item = row["files"][0]
        self.assertEqual(item["repoRelativePath"], "codex-rs/hepta-matrix-sdk/src/lib.rs")
        self.assertEqual(item["absolutePath"], str(self.source))
        self.assertTrue(item["tracked"])
        self.assertTrue(item["gitLsFilesErrorUnmatch"])
        self.assertEqual(item["trackedCheck"]["exitStatus"], 0)
        self.assertEqual(item["trackedCheck"]["verificationMode"], "batched_stage0_index")
        self.assertEqual(item["trackedCheck"]["batchCommand"], row["scan"]["indexCommand"])
        self.assertEqual(
            item["trackedCheck"]["command"],
            [
                "git",
                "ls-files",
                "--error-unmatch",
                "--",
                "codex-rs/hepta-matrix-sdk/src/lib.rs",
            ],
        )
        self.assertEqual(item["introducedAtCommit"], self.head)
        self.assertEqual(item["sourceClass"], "tracked_repository_source")
        self.assertFalse(item["classification"]["generated"])
        self.assertEqual(
            item["gitBlob"],
            self.git(
                "rev-parse",
                f"{self.head}:codex-rs/hepta-matrix-sdk/src/lib.rs",
            ).strip(),
        )
        self.assertEqual(row["sourceInventorySha256"], module.aggregate(row["files"]))
        self.validate(row)

    def test_introduction_history_survives_later_modification(self) -> None:
        first = self.head
        self.source.write_text("pub fn source() { let _ = 1; }\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "modify")
        self.head = self.git("rev-parse", "HEAD").strip()
        row = self.build()
        self.assertTrue(row["valid"])
        self.assertEqual(row["files"][0]["introducedAtCommit"], first)
        self.validate(row)

    def test_provenance_tampering_fails_closed(self) -> None:
        row = self.build()
        row["files"][0]["absolutePath"] = "/tmp/not-the-checkout/source"
        with self.assertRaisesRegex(ValueError, "unverifiable"):
            self.validate(row)

    def test_untracked_closure_input_fails_closed_and_is_named(self) -> None:
        hidden = self.source.with_name("hidden.rs")
        hidden.write_text("untracked\n", encoding="utf-8")
        row = self.build()
        self.assertFalse(row["valid"])
        self.assertIn(
            "codex-rs/hepta-matrix-sdk/src/hidden.rs",
            row["scan"]["cleanBefore"]["untrackedClosureInputs"],
        )
        self.assertFalse(row["claims"]["trackedSourceOnly"])

    def test_dirty_tracked_bytes_fail_closed(self) -> None:
        self.source.write_text("pub fn changed() {}\n", encoding="utf-8")
        row = self.build()
        self.assertFalse(row["valid"])
        self.assertIn(
            "codex-rs/hepta-matrix-sdk/src/lib.rs",
            row["scan"]["cleanBefore"]["unstaged"],
        )

    def test_full_history_binds_file_added_on_merged_side_branch(self) -> None:
        self.git("checkout", "-qb", "feature")
        merged = self.source.with_name("merged.rs")
        merged.write_text("pub fn merged() {}\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "add merged source")
        introduced = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "master")
        self.source.write_text("pub fn source() { let _ = 2; }\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "advance first parent")
        self.git("merge", "--no-ff", "-qm", "merge feature", "feature")
        self.head = self.git("rev-parse", "HEAD").strip()

        row = self.build()

        self.assertTrue(row["valid"], row["errors"])
        by_path = {item["repoRelativePath"]: item for item in row["files"]}
        self.assertEqual(
            by_path["codex-rs/hepta-matrix-sdk/src/merged.rs"]["introducedAtCommit"],
            introduced,
        )
        self.assertIn("--full-history", row["scan"]["introductionHistoryCommand"])
        self.assertIn("HEAD", row["scan"]["introductionHistoryCommand"])
        self.assertEqual(row["scan"]["missingIntroductionPaths"], [])
        self.validate(row)

    def test_git_process_count_is_constant_in_closure_size(self) -> None:
        generated = self.source.parent / "generated"
        generated.mkdir()
        for index in range(128):
            (generated / f"fixture_{index:03}.rs").write_text(
                f"pub const VALUE_{index}: usize = {index};\n",
                encoding="utf-8",
            )
        self.git("add", ".")
        self.git("commit", "-qm", "many tracked inputs")
        self.head = self.git("rev-parse", "HEAD").strip()

        calls: list[tuple[str, ...]] = []
        original_git = module.git

        def counted(root: Path, *arguments: str, **kwargs):
            calls.append(arguments)
            return original_git(root, *arguments, **kwargs)

        with mock.patch.object(module, "SOURCE_ROOTS", self.roots), mock.patch.object(
            module, "git", side_effect=counted
        ):
            row = module.build(self.root, self.head, "source-head")

        self.assertTrue(row["valid"], row["errors"])
        self.assertEqual(len(row["files"]), 129)
        self.assertEqual(row["scan"]["perFileGitProcesses"], 0)
        self.assertLessEqual(len(calls), 18)
        self.validate(row)


if __name__ == "__main__":
    unittest.main()
