"""Dual-root synthetic source identity regressions; never native qualification."""

import contextlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import macos_six_evidence as evidence


class SourceBoundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.control = self.root / "control"
        self.source.mkdir()
        self.control.mkdir()
        for root in [self.source, self.control]:
            self.git(root, "init", "-q")
            self.git(root, "config", "user.name", "Synthetic")
            self.git(root, "config", "user.email", "synthetic@example.invalid")
        self.put(self.source, "codex-rs/.config/nextest.toml", "# original\n")
        self.put(self.source, "codex-rs/Cargo.lock", "# lock\n")
        self.put(self.source, "MODULE.bazel.lock", "{}\n")
        self.commit(self.source)
        base = self.git(self.source, "rev-parse", "HEAD")
        self.put(self.source, "fixture.rs", "// reviewed fixture\n")
        self.commit(self.source)
        head = self.git(self.source, "rev-parse", "HEAD")
        tree = self.git(self.source, "rev-parse", "HEAD^{tree}")
        self.put(
            self.control,
            ".github/scripts/macos_six_nextest.toml",
            "# original\n" + evidence.PROFILE_APPENDIX,
        )
        self.commit(self.control)
        controlbase = self.git(self.control, "rev-parse", "HEAD")
        self.put(self.control, ".github/scripts/new-control.txt", "reviewed control\n")
        self.commit(self.control)
        self.pins = {
            "base_tree": self.git(self.control, "rev-parse", controlbase + "^{tree}"),
            "source_base_tree": self.git(self.source, "rev-parse", base + "^{tree}"),
            "changed_paths": [".github/scripts/new-control.txt"],
            "source_changed_paths": ["fixture.rs"],
            "source_chain": [head],
            "control_sha256": {
                ".github/scripts/new-control.txt": evidence.digest(
                    self.control / ".github/scripts/new-control.txt"
                )
            },
            "lock_blobs": {
                p: self.git(self.source, "rev-parse", "HEAD:" + p)
                for p in ["codex-rs/Cargo.lock", "MODULE.bazel.lock"]
            },
        }
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in [
            ("HERE", self.control / ".github/scripts"),
            ("SOURCE_SHA", head),
            ("SOURCE_TREE", tree),
            ("SOURCE_BASE", base),
            ("BASE", controlbase),
        ]:
            self.stack.enter_context(patch.object(evidence, name, value))
        self.stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "SOURCE_ROOT": str(self.source),
                    "SOURCE_SHA": head,
                    "CANDIDATE_SHA": self.git(self.control, "rev-parse", "HEAD"),
                    "WORKFLOW_SHA": self.git(self.control, "rev-parse", "HEAD"),
                },
            )
        )
        cwd = Path.cwd()
        os.chdir(self.source)
        self.addCleanup(os.chdir, cwd)

    def git(self, root, *args):
        return subprocess.check_output(
            ["git", *args], cwd=root, stderr=subprocess.PIPE, text=True
        ).strip()

    def put(self, root, path, text):
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, root):
        self.git(root, "add", ".")
        self.git(root, "commit", "-qm", "synthetic")

    def test_distinct_roots_success_and_complete_working_inventory(self):
        receipt = evidence.validate_roots(self.pins)
        self.assertEqual(
            set(receipt["source"]),
            {
                "fixture.rs",
                "codex-rs/.config/nextest.toml",
                "codex-rs/Cargo.lock",
                "MODULE.bazel.lock",
            },
        )
        self.assertNotEqual(receipt["control_head"], evidence.SOURCE_SHA)
        self.assertEqual(receipt, evidence.validate_roots(self.pins))

    def test_control_cannot_be_source(self):
        with patch.dict(os.environ, {"SOURCE_ROOT": str(self.control)}):
            with self.assertRaisesRegex(ValueError, "overlap"):
                evidence.validate_roots(self.pins)

    def test_alias_and_nested_roots_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        for path in [alias, self.control / "source"]:
            with (
                self.subTest(path=str(path)),
                patch.dict(os.environ, {"SOURCE_ROOT": str(path)}),
            ):
                with self.assertRaises(ValueError):
                    evidence.source_root()

    def test_wrong_source_input_and_head(self):
        with patch.dict(os.environ, {"SOURCE_SHA": "0" * 40}):
            with self.assertRaisesRegex(ValueError, "immutable source"):
                evidence.validate_roots(self.pins)
        self.git(self.source, "checkout", "--detach", "HEAD^")
        with self.assertRaisesRegex(ValueError, "wrong source head"):
            evidence.validate_roots(self.pins)

    def test_wrong_source_tree_and_ancestry(self):
        with patch.object(evidence, "SOURCE_TREE", "0" * 40):
            with self.assertRaisesRegex(ValueError, "source tree"):
                evidence.validate_roots(self.pins)
        self.pins["source_chain"] = []
        with self.assertRaisesRegex(ValueError, "ancestry"):
            evidence.validate_roots(self.pins)

    def test_wrong_control_head_parent_tree(self):
        with patch.dict(os.environ, {"WORKFLOW_SHA": evidence.SOURCE_SHA}):
            with self.assertRaisesRegex(ValueError, "control head"):
                evidence.validate_roots(self.pins)
        with patch.object(evidence, "BASE", "0" * 40):
            with self.assertRaisesRegex(ValueError, "control parent"):
                evidence.validate_roots(self.pins)
        self.pins["base_tree"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "parent tree"):
            evidence.validate_roots(self.pins)

    def test_launch_from_control_rejected(self):
        os.chdir(self.control)
        with self.assertRaisesRegex(ValueError, "launched from source"):
            evidence.validate_roots(self.pins)

    def test_source_mutation_rejected_even_hidden_from_status(self):
        before = evidence.validate_roots(self.pins)
        self.git(self.source, "update-index", "--assume-unchanged", "fixture.rs")
        self.put(self.source, "fixture.rs", "// substituted\n")
        self.assertEqual(self.git(self.source, "status", "--porcelain=v1"), "")
        with self.assertRaisesRegex(ValueError, "working source blob drift"):
            evidence.validate_roots(self.pins)
        self.assertNotEqual(
            before["source"]["fixture.rs"]["sha256"],
            evidence.digest(self.source / "fixture.rs"),
        )

    def test_each_lock_dirty_and_blob_substitution_rejected(self):
        for path in self.pins["lock_blobs"]:
            with self.subTest(path=path):
                original = (self.source / path).read_text()
                self.put(self.source, path, "drift")
                with self.assertRaisesRegex(ValueError, "dirty source"):
                    evidence.validate_roots(self.pins)
                self.put(self.source, path, original)
                expected = self.pins["lock_blobs"][path]
                self.pins["lock_blobs"][path] = "0" * 40
                with self.assertRaisesRegex(ValueError, "lock drift"):
                    evidence.validate_roots(self.pins)
                self.pins["lock_blobs"][path] = expected

    def test_control_modified_or_untracked_rejected(self):
        self.put(self.control, "unexpected", "not source")
        with self.assertRaisesRegex(ValueError, "dirty control"):
            evidence.validate_roots(self.pins)
        (self.control / "unexpected").unlink()
        self.pins["control_sha256"][".github/scripts/new-control.txt"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "control pin mismatch"):
            evidence.validate_roots(self.pins)

    def test_symlink_and_executable_modes_are_bound(self):
        inventory = evidence.full_worktree_identity(self.source)
        path = self.source / "fixture.rs"
        path.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "executable mode"):
            evidence.full_worktree_identity(self.source)
        path.chmod(0o644)
        path.unlink()
        path.symlink_to(self.control / ".github/scripts/new-control.txt")
        with self.assertRaisesRegex(ValueError, "source type drift"):
            evidence.full_worktree_identity(self.source)
        self.assertEqual(inventory["fixture.rs"]["mode"], "100644")

    def test_native_command_cwd_identity_and_reap_are_mandatory(self):
        record = {
            "exit": 0,
            "timed_out": False,
            "cwd": str(self.source / "codex-rs"),
            "owned_pgid": 42,
            "leader_identity": {
                k: 42 for k in ["pid", "pgid", "sid", "observed_pgid", "observed_sid"]
            },
            "leader_lifecycle": {
                "reaped": True,
                "pid": 42,
                "ownership": "sole-pinned-unreaped-direct-child-zombie",
                "returncode": 0,
                "wait_status": 0,
            },
            "cleanup_observations": [{"state": "sole-terminal-leader"}],
        }
        evidence.validate_native_receipt(record)
        for key, value in [
            ("cwd", str(self.control / "codex-rs")),
            ("exit", 125),
            ("timed_out", True),
            ("owned_pgid", 99),
        ]:
            bad = dict(record, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                evidence.validate_native_receipt(bad)
        for key, value in [
            ("reaped", False),
            ("pid", 99),
            ("returncode", 1),
            ("wait_status", 256),
        ]:
            bad = dict(
                record,
                leader_lifecycle=dict(record["leader_lifecycle"], **{key: value}),
            )
            with self.subTest(key=key), self.assertRaises(ValueError):
                evidence.validate_native_receipt(bad)

    def test_runner_uses_source_cwd_for_exact37_commands(self):
        out = self.root / "runner-evidence"
        out.mkdir()
        (out / "budget.json").write_text("{}")
        roots = evidence.validate_roots(self.pins)
        (out / "source.json").write_text(
            json.dumps(
                {"roots": roots, "budget_sha256": evidence.digest(out / "budget.json")}
            )
        )
        (evidence.HERE / "macos_six_pins.json").write_text("{}")
        with (
            patch.object(evidence, "validate_roots", return_value=roots),
            patch.object(evidence, "shared_deadline", return_value=123456),
            patch.object(evidence, "bounded", return_value=0) as commands,
            patch.object(evidence, "validate_metadata"),
            patch.object(evidence, "validate_list"),
            patch.object(evidence, "validate_report"),
        ):
            evidence.execute(out)
        self.assertEqual(commands.call_count, 37)
        self.assertEqual(
            commands.call_args_list[0].args[0],
            ["cargo", "metadata", "--locked", "--format-version=1"],
        )
        for call in commands.call_args_list:
            self.assertEqual(call.args[2], 123456)
            self.assertEqual(call.args[3], self.source / "codex-rs")
        for call in commands.call_args_list[1:]:
            argv = call.args[0]
            self.assertEqual(argv[argv.index("--color") + 1], "never")
        self.assertEqual(
            sum(c.args[0][:2] == ["just", "test"] for c in commands.call_args_list), 18
        )

    def test_preexecution_root_drift_stops_before_metadata(self):
        out = self.root / "refused-evidence"
        out.mkdir()
        (out / "budget.json").write_text("{}")
        (out / "source.json").write_text(
            json.dumps(
                {
                    "roots": {"source": "original"},
                    "budget_sha256": evidence.digest(out / "budget.json"),
                }
            )
        )
        (evidence.HERE / "macos_six_pins.json").write_text("{}")
        with (
            patch.object(
                evidence, "validate_roots", return_value={"source": "changed"}
            ),
            patch.object(evidence, "bounded") as commands,
        ):
            with self.assertRaisesRegex(ValueError, "pre-execution roots drift"):
                evidence.execute(out)
            commands.assert_not_called()

    def test_original137_plus23_exact160_and37_commands(self):
        self.assertEqual(len(evidence.PHASES), 18)
        self.assertEqual(
            sum(len(evidence.expected(p)) for p in evidence.PHASES[:15]), 137
        )
        self.assertEqual(
            [len(evidence.expected(p)) for p in evidence.PHASES[15:]], [17, 4, 2]
        )
        self.assertEqual(sum(len(evidence.expected(p)) for p in evidence.PHASES), 160)
        self.assertEqual(1 + 2 * len(evidence.PHASES), 37)
        args = evidence.selection("supervisor-integration")
        self.assertIn("--tests", args)
        self.assertNotIn("--lib", args)
        for phase in evidence.PHASES[15:]:
            args = evidence.selection(phase)
            self.assertEqual(args[:2], ["--color", "never"])
            for _, name in evidence.expected(phase):
                self.assertIn("test(=" + name + ")", args[-1])


if __name__ == "__main__":
    unittest.main()
