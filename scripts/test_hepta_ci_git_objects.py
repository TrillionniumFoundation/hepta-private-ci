"""Exact-tree dependency reads stay byte-correct without a process per file."""

import io
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from scripts.hepta_ci_dependencies import graph, plan
from scripts.hepta_git_objects import GitTree


class GitObjectPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Dependency fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.put("codex-rs/Cargo.toml", '[workspace]\nmembers=["example"]\n')
        self.put(
            "codex-rs/example/Cargo.toml",
            '[package]\nname="example"\nversion="0.1.0"\n',
        )
        self.put("codex-rs/example/src/lib.rs", 'include!("fragment.rs");\n')
        self.put(
            "codex-rs/example/src/fragment.rs",
            'const DATA: &str = include_str!("../../../docs/input.md");\n',
        )
        self.put("docs/input.md", "original\n")

    def git(self, *arguments):
        return (
            subprocess.check_output(
                ["git", "-C", str(self.root), *arguments], stderr=subprocess.PIPE
            )
            .decode()
            .strip()
        )

    def put(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def test_many_source_files_use_constant_git_processes(self):
        for index in range(128):
            self.put(
                f"codex-rs/example/src/source-{index}.rs",
                f'const INPUT: &str = include_str!("../../../docs/{index}.md");\n',
            )
        revision = self.commit()
        with patch("subprocess.Popen", wraps=subprocess.Popen) as spawn:
            observed = graph(self.root, revision)
        self.assertEqual(observed.owners, {"codex-rs/example": "example"})
        self.assertEqual(observed.opaque_input_consumers, frozenset())
        for index in range(128):
            self.assertIn((f"docs/{index}.md", "example"), observed.external_inputs)
        # One tree listing, one source search, one streaming object reader.
        # This is an algorithmic bound, never a flaky wall-clock gate.
        self.assertLessEqual(spawn.call_count, 3)

    def test_dirty_worktree_cannot_change_committed_graph(self):
        revision = self.commit()
        expected = graph(self.root, revision)
        self.put("codex-rs/example/src/fragment.rs", "not the committed bytes\n")
        self.put("codex-rs/example/Cargo.toml", "invalid local manifest\n")
        self.assertEqual(graph(self.root, revision), expected)

    def test_old_and_new_blob_graphs_stay_independent(self):
        before = self.commit()
        self.put("codex-rs/example/src/fragment.rs", "const VALUE: u8 = 1;\n")
        after = self.commit()
        old, new = graph(self.root, before), graph(self.root, after)
        self.assertIn(("docs/input.md", "example"), old.external_inputs)
        self.assertNotIn(("docs/input.md", "example"), new.external_inputs)
        self.assertEqual(plan(self.root, before, after)["packages"], ["example"])

    def test_newline_in_tracked_source_path_cannot_split_object_requests(self):
        self.put(
            "codex-rs/example/src/line\nbreak.rs",
            'const DATA: &str = include_str!("../../../docs/newline.md");\n',
        )
        observed = graph(self.root, self.commit())
        self.assertIn(("docs/newline.md", "example"), observed.external_inputs)

    def test_non_utf8_rust_source_remains_an_opaque_consumer(self):
        path = self.root / "codex-rs/example/src/fragment.rs"
        path.write_bytes(b"// include!\n\xff\x00")
        observed = graph(self.root, self.commit())
        self.assertEqual(observed.opaque_input_consumers, frozenset({"example"}))

    def test_binary_empty_and_unterminated_blobs_preserve_framing(self):
        for name, contents in (
            ("empty", b""),
            ("binary", b"\x00\xff\nnot a header\n"),
            ("unterminated", b"no newline"),
        ):
            (self.root / name).write_bytes(contents)
        with GitTree(self.root, self.commit()) as tree:
            self.assertEqual(tree.read("empty"), b"")
            self.assertEqual(tree.read("binary"), b"\x00\xff\nnot a header\n")
            self.assertEqual(tree.read("unterminated"), b"no newline")
            self.assertEqual(tree.read("empty"), b"")
        self.assertEqual(tree.process.returncode, 0)

    def test_blob_replacement_cannot_change_exact_tree_bytes(self):
        revision = self.commit()
        original = self.git("rev-parse", f"{revision}:docs/input.md")
        self.put("docs/input.md", "replacement\n")
        other = self.commit()
        replacement = self.git("rev-parse", f"{other}:docs/input.md")
        self.git("replace", original, replacement)
        with GitTree(self.root, revision) as tree:
            self.assertEqual(tree.read("docs/input.md"), b"original\n")

    def test_malformed_duplicate_tree_paths_are_rejected(self):
        revision = self.commit()
        first = self.git("rev-parse", f"{revision}:docs/input.md")
        second = self.git("rev-parse", f"{revision}:codex-rs/example/src/lib.rs")
        tree = (
            subprocess.check_output(
                ["git", "-C", str(self.root), "mktree"],
                input=f"100644 blob {first}\tf\n100644 blob {second}\tf\n".encode(),
            )
            .decode()
            .strip()
        )
        commit = self.git("commit-tree", tree, "-m", "malformed duplicate fixture")
        with self.assertRaisesRegex(ValueError, "duplicate exact-tree path"):
            GitTree(self.root, commit)

    def test_duplicate_directories_with_disjoint_children_are_rejected(self):
        revision = self.commit()
        blob = self.git("rev-parse", f"{revision}:docs/input.md")
        children = []
        for name in ("first", "second"):
            children.append(
                subprocess.check_output(
                    ["git", "-C", str(self.root), "mktree"],
                    input=f"100644 blob {blob}\t{name}\n".encode(),
                )
                .decode()
                .strip()
            )
        tree = (
            subprocess.check_output(
                ["git", "-C", str(self.root), "mktree"],
                input="".join(f"040000 tree {oid}\tdir\n" for oid in children).encode(),
            )
            .decode()
            .strip()
        )
        commit = self.git("commit-tree", tree, "-m", "duplicate directory fixture")
        with self.assertRaisesRegex(ValueError, "duplicate exact-tree path"):
            GitTree(self.root, commit)

    def test_missing_path_rejects_without_disrupting_reader(self):
        with GitTree(self.root, self.commit()) as tree:
            with self.assertRaises(subprocess.CalledProcessError):
                tree.read("does-not-exist")
            self.assertEqual(tree.read("docs/input.md"), b"original\n")

    def test_ref_name_is_rejected_before_git_execution(self):
        with patch("subprocess.Popen") as spawn, self.assertRaises(ValueError):
            GitTree(self.root, "HEAD")
        spawn.assert_not_called()

    def test_malformed_object_responses_fail_closed_and_close_process(self):
        revision = self.commit()
        oid = self.git("rev-parse", f"{revision}:docs/input.md").encode()
        for response in (
            b"f" * 40 + b" blob 0\n\n",
            oid + b" tree 0\n\n",
            oid + b" missing\n",
            oid + b" blob 9\nshort\n",
            oid + b" blob 1\nx!",
        ):
            with self.subTest(response=response):
                tree = GitTree(self.root, revision)
                process = Mock(
                    stdin=io.BytesIO(), stdout=io.BytesIO(response), args=["git"]
                )
                process.wait.return_value = 0
                with patch("subprocess.Popen", return_value=process):
                    with self.assertRaises(ValueError), tree:
                        tree.read("docs/input.md")
                self.assertTrue(process.stdin.closed)
                self.assertTrue(process.stdout.closed)
                process.wait.assert_called_once()

    def test_startup_failure_closes_diagnostic_file(self):
        tree = GitTree(self.root, self.commit())
        with patch("subprocess.Popen", side_effect=OSError("cannot spawn")):
            with self.assertRaisesRegex(OSError, "cannot spawn"), tree:
                self.fail("failed startup cannot enter the reader")
        self.assertTrue(tree.errors.closed)

    def test_write_and_flush_failure_preserve_error_and_reap_child(self):
        revision = self.commit()
        for method in ("write", "flush"):
            with self.subTest(method=method):
                tree = GitTree(self.root, revision)
                process = Mock(stdin=Mock(), stdout=io.BytesIO(), args=["git"])
                getattr(process.stdin, method).side_effect = BrokenPipeError(method)
                process.stdin.close.side_effect = BrokenPipeError("close")
                process.wait.return_value = 1
                with patch("subprocess.Popen", return_value=process):
                    with self.assertRaisesRegex(BrokenPipeError, method), tree:
                        tree.read("docs/input.md")
                self.assertTrue(process.stdout.closed)
                self.assertTrue(tree.errors.closed)
                process.wait.assert_called_once_with(timeout=5)

    def test_nonzero_exit_is_not_a_successful_read_session(self):
        tree = GitTree(self.root, self.commit())
        process = Mock(stdin=io.BytesIO(), stdout=io.BytesIO(), args=["git"])
        process.wait.return_value = 19
        with patch("subprocess.Popen", return_value=process):
            with self.assertRaises(subprocess.CalledProcessError) as caught, tree:
                pass
        self.assertEqual(caught.exception.returncode, 19)
        self.assertTrue(tree.errors.closed)

    def test_stalled_child_is_bounded_without_hiding_existing_error(self):
        revision = self.commit()
        for existing_error in (False, True):
            with self.subTest(existing_error=existing_error):
                tree = GitTree(self.root, revision)
                process = Mock(stdin=io.BytesIO(), stdout=io.BytesIO(), args=["git"])
                process.wait.side_effect = [
                    subprocess.TimeoutExpired(["git"], 5),
                    subprocess.TimeoutExpired(["git"], 5),
                    -9,
                ]
                exception = ValueError if existing_error else subprocess.TimeoutExpired
                with patch("subprocess.Popen", return_value=process):
                    with self.assertRaises(exception), tree:
                        if existing_error:
                            raise ValueError("original parse failure")
                process.terminate.assert_called_once()
                process.kill.assert_called_once()
                self.assertEqual(process.wait.call_count, 3)
                self.assertTrue(tree.errors.closed)


if __name__ == "__main__":
    unittest.main()
