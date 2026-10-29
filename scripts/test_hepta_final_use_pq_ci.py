"""Cheap runner controls using synthetic build records, never native test evidence."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import hepta_final_use_pq_ci as pq


class FinalUsePqRunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.root = self.base / "source"
        self.target = self.base / "fresh-target"
        self.root.mkdir()
        self.target.mkdir()
        self.executable = self.target / "codex"
        self.executable.write_bytes(
            b"\x7fELFsynthetic parser fixture, not executable Rust"
        )
        self.executable.chmod(0o700)
        self.source = "a" * 40
        self.identity = {
            "commit": self.source,
            "tree": "b" * 40,
            "parents": [],
            "dirty": False,
        }
        self.artifact = {
            "reason": "compiler-artifact",
            "fresh": False,
            "package_id": "path+"
            + (self.root / "codex-rs/cli").as_uri()
            + "#codex-cli@0.0.0",
            "target": {
                "kind": ["bin"],
                "name": "codex",
                "src_path": str(self.root / "codex-rs/cli/src/main.rs"),
            },
            "executable": str(self.executable),
        }
        self.log = self.base / "build.log"
        self.write_log([self.artifact, {"reason": "build-finished", "success": True}])
        self.record_path = self.base / "build.json"
        self.record = {
            "status": "passed",
            "command": pq.BUILD_COMMAND,
            "command_exit_code": 0,
            "source_sha": self.source,
            "tested_sha": self.source,
            "working_directory": str(self.root),
            "before": self.identity,
            "after": self.identity,
            "log_file": self.log.name,
            "log_sha256": pq.digest(self.log),
        }
        self.record_path.write_text(json.dumps(self.record))

    def write_log(self, rows):
        self.log.write_text(
            "Compiler diagnostic without a JSON artifact\n"
            + "".join(json.dumps(row) + "\n" for row in rows)
        )

    def test_actual_pr_event_rejects_fork_wrong_branch_and_target_context(self):
        event = {
            "pull_request": {
                "head": {
                    "sha": self.source,
                    "ref": pq.BRANCH,
                    "repo": {"full_name": "owner/repository"},
                }
            }
        }
        event_path = self.base / "event.json"
        event_path.write_text(json.dumps(event))
        env = {
            "GITHUB_EVENT_PATH": str(event_path),
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REPOSITORY": "owner/repository",
            "GITHUB_SHA": "c" * 40,
        }
        with mock.patch.dict(os.environ, env):
            self.assertEqual(pq.pr_source(), self.source)
        for branch, repository, event_name in (
            (pq.BRANCH + "-different", "owner/repository", "pull_request"),
            (pq.BRANCH, "fork/repository", "pull_request"),
            (pq.BRANCH, "owner/repository", "pull_request_target"),
        ):
            event["pull_request"]["head"].update(
                ref=branch, repo={"full_name": repository}
            )
            event_path.write_text(json.dumps(event))
            with (
                self.subTest(
                    branch=branch, repository=repository, event_name=event_name
                ),
                mock.patch.dict(os.environ, dict(env, GITHUB_EVENT_NAME=event_name)),
                self.assertRaises(ValueError),
            ):
                pq.pr_source()

    def test_selected_ref_and_closed_phase_reject_wrong_or_missing_identity(self):
        pq.selection("native", self.source, self.source)
        pq.selection("lock-artifact", self.source, self.source)
        for phase, source, workflow in (
            ("off", self.source, self.source),
            ("Native", self.source, self.source),
            ("", self.source, self.source),
            ("native", "main", self.source),
            ("native", self.source, "b" * 40),
            ("native", "A" * 40, "A" * 40),
        ):
            with (
                self.subTest(phase=phase, source=source, workflow=workflow),
                self.assertRaises(ValueError),
            ):
                pq.selection(phase, source, workflow)

    def test_actual_artifact_selection_ignores_unrelated_compiler_records(self):
        unrelated = copy.deepcopy(self.artifact)
        unrelated["target"]["name"] = "other"
        self.write_log(
            [unrelated, self.artifact, {"reason": "build-finished", "success": True}]
        )
        self.assertEqual(
            pq.select_codex(self.log, self.root, self.target), self.executable
        )

    def test_stale_wrong_package_source_kind_or_target_cannot_supply_codex(self):
        changes = (
            ("fresh", True),
            ("package_id", "registry+somewhere#codex-cli@0.0.0"),
            ("executable", "codex"),
            ("executable", str(self.root / "codex")),
            (
                "target",
                {
                    "name": "codex",
                    "kind": ["lib"],
                    "src_path": self.artifact["target"]["src_path"],
                },
            ),
            (
                "target",
                {
                    "name": "codex",
                    "kind": ["bin"],
                    "src_path": "/other/cli/src/main.rs",
                },
            ),
        )
        for field, value in changes:
            row = copy.deepcopy(self.artifact)
            row[field] = value
            self.write_log([row, {"reason": "build-finished", "success": True}])
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                pq.select_codex(self.log, self.root, self.target)

    def test_ambiguous_or_unsuccessful_build_is_not_an_executable_binding(self):
        for rows in (
            [self.artifact],
            [self.artifact, {"reason": "build-finished", "success": False}],
            [
                self.artifact,
                self.artifact,
                {"reason": "build-finished", "success": True},
            ],
            [{"reason": "build-finished", "success": True}],
        ):
            self.write_log(rows)
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                pq.select_codex(self.log, self.root, self.target)

    def test_symlink_escape_and_non_elf_artifacts_are_refused(self):
        outside = self.base / "outside"
        outside.write_bytes(self.executable.read_bytes())
        outside.chmod(0o700)
        self.executable.unlink()
        self.executable.symlink_to(outside)
        with self.assertRaises(ValueError):
            pq.select_codex(self.log, self.root, self.target)
        self.executable.unlink()
        self.executable.write_bytes(b"#!/bin/sh\nexit 0\n")
        self.executable.chmod(0o700)
        with self.assertRaises(ValueError):
            pq.select_codex(self.log, self.root, self.target)

    def test_build_record_binds_real_log_and_unchanged_source(self):
        with (
            mock.patch.object(pq.owner, "identity", return_value=self.identity),
            mock.patch.dict(os.environ, {"SOURCE_SHA": self.source}),
        ):
            binding = pq.build_binding(self.record_path, self.root, self.target)
        self.assertEqual(binding["executable"], str(self.executable))
        self.assertEqual(binding["sha256"], pq.digest(self.executable))

    def test_wrong_source_command_workdir_and_log_cannot_relabel_a_build(self):
        for field, value in (
            ("source_sha", "c" * 40),
            ("tested_sha", "c" * 40),
            ("status", "running"),
            ("command_exit_code", 1),
            ("command", ["cargo", "check"]),
            ("working_directory", str(self.base)),
            ("after", dict(self.identity, dirty=True)),
            ("log_file", "../build.log"),
            ("log_sha256", "0" * 64),
        ):
            record = dict(self.record)
            record[field] = value
            self.record_path.write_text(json.dumps(record))
            with (
                self.subTest(field=field),
                mock.patch.object(pq.owner, "identity", return_value=self.identity),
                mock.patch.dict(os.environ, {"SOURCE_SHA": self.source}),
                self.assertRaises(ValueError),
            ):
                pq.build_binding(self.record_path, self.root, self.target)

    def test_lock_artifact_rejects_dirty_original_before_creating_a_worktree(self):
        with (
            mock.patch.object(
                pq.owner, "identity", return_value=dict(self.identity, dirty=True)
            ),
            mock.patch.object(pq.owner, "git") as git,
            self.assertRaises(ValueError),
        ):
            pq.lock_artifact(self.root, self.base / "proposal")
        git.assert_not_called()

    def test_lock_only_guard_reads_raw_non_lock_bytes_and_index(self):
        tracked = self.root / "source.rs"
        tracked.write_text("original")
        (self.root / pq.LOCK).write_text("lock-before")

        def git(*args, **kwargs):
            if args == ("ls-files", "-z"):
                return "source.rs\0MODULE.bazel.lock\0"
            return ""

        with mock.patch.object(pq.owner, "git", side_effect=git):
            before = pq.tracked_inputs(self.root)
            (self.root / pq.LOCK).write_text("real-tool-proposed-lock")
            pq.require_lock_only(self.root, before)
            tracked.write_text("changed same-path source")
            with self.assertRaisesRegex(ValueError, "another tracked"):
                pq.require_lock_only(self.root, before)
        for marker in ("index", "untracked", "hidden"):

            def metadata(*args, **kwargs):
                if marker == "index" and args[0] == "diff":
                    return "MODULE.bazel.lock"
                if marker == "untracked" and "--others" in args:
                    return "extra.py"
                if marker == "hidden" and "-v" in args:
                    return "S source.rs"
                return ""

            with (
                self.subTest(marker=marker),
                mock.patch.object(pq, "tracked_inputs", return_value=before),
                mock.patch.object(pq.owner, "git", side_effect=metadata),
                self.assertRaises(ValueError),
            ):
                pq.require_lock_only(self.root, before)

    def test_native_dispatches_each_exact_host_case_with_nonzero_minimum(self):
        binding = {
            "source": self.identity,
            "executable": str(self.executable),
            "sha256": pq.digest(self.executable),
        }
        output = self.base / "native"
        output.mkdir()
        with (
            mock.patch.object(pq, "build_binding", return_value=binding),
            mock.patch.object(pq.owner, "run", return_value=0) as run,
            mock.patch.dict(
                os.environ, {"CARGO_TARGET_DIR": str(self.target)}, clear=True
            ),
        ):
            self.assertEqual(pq.native(self.root, output, self.record_path), 0)
        calls = run.call_args_list
        self.assertEqual(len(calls), 8)
        for call, selector in zip(calls[2:], pq.HOST_CASES, strict=True):
            self.assertEqual(call.kwargs["minimum_tests"], 1)
            command = call.args[1]
            self.assertEqual(command[command.index("-E") + 1], f"test(={selector})")
        self.assertFalse(
            json.loads((output / "result.json").read_text())["whole_pipeline_pq"]
        )

    def test_one_failed_case_cannot_be_hidden_by_remaining_passes(self):
        binding = {
            "source": self.identity,
            "executable": str(self.executable),
            "sha256": pq.digest(self.executable),
        }
        output = self.base / "native"
        output.mkdir()
        with (
            mock.patch.object(pq, "build_binding", return_value=binding),
            mock.patch.object(
                pq.owner, "run", side_effect=[0, 0, 1, 0, 0, 0, 0, 0]
            ) as run,
            mock.patch.dict(
                os.environ, {"CARGO_TARGET_DIR": str(self.target)}, clear=True
            ),
        ):
            self.assertEqual(pq.native(self.root, output, self.record_path), 1)
        self.assertEqual(run.call_count, 8)
        self.assertEqual(
            json.loads((output / "result.json").read_text())["status"], "failed"
        )

    def test_changed_codex_between_compile_and_host_use_is_refused(self):
        binding = {
            "source": self.identity,
            "executable": str(self.executable),
            "sha256": pq.digest(self.executable),
        }
        output = self.base / "native"
        output.mkdir()

        def mutate(*args, **kwargs):
            self.executable.write_bytes(b"replaced")
            return 0

        with (
            mock.patch.object(pq, "build_binding", return_value=binding),
            mock.patch.object(pq.owner, "run", side_effect=mutate) as run,
            mock.patch.dict(
                os.environ, {"CARGO_TARGET_DIR": str(self.target)}, clear=True
            ),
            self.assertRaisesRegex(ValueError, "changed during"),
        ):
            pq.native(self.root, output, self.record_path)
        self.assertEqual(run.call_count, 1)
        self.assertFalse((output / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
