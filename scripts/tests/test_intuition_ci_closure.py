"""Synthetic evidence regression tests, not production execution receipts."""

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import intuition_qualify_exact as q
import intuition_accept_exact as a
import intuition_ci_exact as ci

CONTEXT = {
    "runId": "fixture-run",
    "runAttempt": "1",
    "repository": "fixture/repo",
    "workflowSha": "f" * 40,
}


def commit(tree, parents=(), message="fixture"):
    raw = (
        f"tree {tree}\n"
        + "".join(f"parent {p}\n" for p in parents)
        + "author Test <test@example.invalid> 1 +0000\n"
        + "committer Test <test@example.invalid> 1 +0000\n\n"
        + message
        + "\n"
    ).encode()
    return hashlib.sha1(
        b"commit " + str(len(raw)).encode() + b"\0" + raw
    ).hexdigest(), raw


BASE, BASE_RAW = commit("b" * 40, message="base fixture")
SOURCE, SOURCE_RAW = commit("c" * 40, (BASE,), "source fixture")
MERGE, MERGE_RAW = commit("d" * 40, (BASE, SOURCE), "merge fixture")


def bundle(path, mode="qualification", merge=False):
    path.mkdir()
    rows = []
    for name, argv in q.COMMANDS if mode == "qualification" else q.INDEPENDENT_COMMANDS:
        log = path / (name + ".log")
        log.write_text("test result: ok. 1 passed; 0 failed;\n")
        row = {
            "name": name,
            "argv": argv,
            "cwd": "codex-rs",
            "status": "passed",
            "exitCode": 0,
            "log": log.name,
            "logSha256": q.sha256(log),
        }
        if name == "release-binaries":
            binary = path / "release--fixture"
            binary.write_bytes(b"unit-test fixture, not a release binary")
            row["binaries"] = [
                {"name": "fixture", "artifact": binary.name, "sha256": q.sha256(binary)}
            ]
        rows.append(row)
    (path / "toolchain.txt").write_text("unit-test compiler fixture only\n")
    record = {
        "schema": q.SCHEMA,
        "sourceSha": SOURCE,
        "testedSha": MERGE if merge else SOURCE,
        "testedTree": "d" * 40 if merge else "c" * 40,
        "baseSha": BASE if merge else None,
        "testedParents": [BASE, SOURCE] if merge else [BASE],
        "testedCommitObjectBase64": base64.b64encode(
            MERGE_RAW if merge else SOURCE_RAW
        ).decode(),
        "lane": "synthetic-merge" if merge else "source-head",
        "mode": mode,
        **CONTEXT,
        "jobId": mode,
        "status": "passed",
        "worktreeUnchanged": True,
        "cargoLockSha256": "e" * 64,
        "toolchainLogSha256": q.sha256(path / "toolchain.txt"),
        "commands": rows,
        "workflowRef": "fixture.yml@refs/fixture",
        "runner": {
            key: "fixture"
            for key in ("RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion")
        },
        "buildEnvironment": dict(ci.BUILD_ENV),
    }
    q.write_json(path / "command-record.json", record)
    q.write_json(path / "IMPLEMENTATION_MAP.json", {"productionImplementation": False})
    q.write_json(
        path / "CURRENT_STATE.json",
        {
            "testedCommit": record["testedSha"],
            "testedTree": record["testedTree"],
            "executionStatus": "passed",
        },
    )
    q.write_json(path / "ci-resources.json", {"fixtureOnly": True})
    for name in ("execution-dossier.md", "TECHNICAL_STATUS.md"):
        (path / name).write_text("Synthetic unit-test fixture.\n")
    q.seal(path)
    return record


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.standard = self.root / "standard"
        self.independent = self.root / "independent"
        self.merge = self.root / "merge"
        bundle(self.standard)
        bundle(self.independent, "independent")
        bundle(self.merge, merge=True)

    def tearDown(self):
        self.temp.cleanup()

    def change(self, key, value, path=None):
        path = path or self.standard
        record = a.strict_json(path / "command-record.json")
        record[key] = value
        q.write_json(path / "command-record.json", record)
        q.seal(path)

    def identity(self):
        record = a.verify_bundle(self.standard, "qualification", SOURCE, CONTEXT)
        a.verify_ci_identity(self.standard, record, CONTEXT)

    def test_matching_source_and_independent(self):
        a.verify_pair(self.standard, self.independent, SOURCE, CONTEXT)
        self.identity()

    def test_valid_merge_object_and_tree(self):
        self.assertEqual(
            a.verify_merge(self.merge, SOURCE, BASE, "d" * 40, CONTEXT)["testedSha"],
            MERGE,
        )

    def test_wrong_recomputed_merge_tree(self):
        with self.assertRaises(ValueError):
            a.verify_merge(self.merge, SOURCE, BASE, "1" * 40, CONTEXT)

    def test_wrong_base_even_after_rehash(self):
        self.change("baseSha", "1" * 40, self.merge)
        with self.assertRaises(ValueError):
            a.verify_merge(self.merge, SOURCE, BASE, "d" * 40, CONTEXT)

    def test_wrong_parent_binding_even_after_rehash(self):
        self.change("testedParents", [SOURCE, "1" * 40], self.merge)
        with self.assertRaises(ValueError):
            a.verify_merge(self.merge, SOURCE, BASE, "d" * 40, CONTEXT)

    def test_changed_commit_object_even_after_rehash(self):
        self.change(
            "testedCommitObjectBase64",
            base64.b64encode(SOURCE_RAW + b"changed").decode(),
        )
        with self.assertRaises(ValueError):
            self.identity()

    def test_changed_workflow_sha(self):
        self.change("workflowSha", "1" * 40)
        with self.assertRaises(ValueError):
            self.identity()

    def test_missing_runner_image(self):
        self.change("runner", {})
        with self.assertRaises(ValueError):
            self.identity()

    def test_incremental_build_not_qualified(self):
        self.change("buildEnvironment", {**ci.BUILD_ENV, "CARGO_INCREMENTAL": "1"})
        with self.assertRaises(ValueError):
            self.identity()

    def test_missing_retained_binary(self):
        (self.standard / "release--fixture").unlink()
        q.seal(self.standard)
        with self.assertRaises(ValueError):
            self.identity()

    def test_binary_tampering(self):
        (self.standard / "release--fixture").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            self.identity()

    def test_state_drift_even_after_rehash(self):
        q.write_json(self.standard / "CURRENT_STATE.json", {"testedCommit": "1" * 40})
        q.seal(self.standard)
        with self.assertRaises(ValueError):
            self.identity()

    def test_manifest_symlink_rejected(self):
        manifest = self.standard / "artifact-manifest.json"
        outside = self.root / "outside"
        outside.write_bytes(manifest.read_bytes())
        manifest.unlink()
        manifest.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.identity()

    def test_duplicate_json_key_rejected(self):
        (self.standard / "artifact-manifest.json").write_text(
            '{"schema":"a","schema":"b"}'
        )
        with self.assertRaises(ValueError):
            self.identity()

    def test_boolean_exit_code_rejected(self):
        record = a.strict_json(self.standard / "command-record.json")
        record["commands"][0]["exitCode"] = False
        self.change("commands", record["commands"])
        with self.assertRaises(ValueError):
            self.identity()

    def test_infrastructure_invalid_is_not_success(self):
        self.change("status", "infrastructure_invalid")
        with self.assertRaises(ValueError):
            self.identity()

    def test_enospc_is_infrastructure_failure(self):
        log = self.root / "compile.log"
        log.write_text("error: No space left on device (os error 28)\n" + "x\n" * 10000)
        self.assertEqual(
            ci.classify(
                {"status": "failed", "exitCode": 101, "log": log.name}, self.root
            ),
            "infrastructure_invalid",
        )

    def test_assertion_failure_not_infrastructure_failure(self):
        (self.root / "test.log").write_text("assertion failed: left != right\n")
        self.assertEqual(
            ci.classify(
                {"status": "failed", "exitCode": 101, "log": "test.log"}, self.root
            ),
            "test_or_build_failed",
        )

    def test_timeout_missing_tool_and_interrupt_are_not_success(self):
        for code in (124, 127, 130):
            with self.subTest(code=code):
                self.assertEqual(
                    ci.classify({"status": "failed", "exitCode": code}, self.root),
                    "infrastructure_invalid",
                )

    def test_positive_log_diagnostic_does_not_reclassify_success(self):
        self.assertEqual(
            ci.classify({"status": "passed", "exitCode": 0}, self.root), "passed"
        )

    def test_required_merge_cannot_be_silently_skipped(self):
        output = self.root / "rejected"
        code = a.main(
            [
                "--source-commit",
                SOURCE,
                "--qualification",
                str(self.standard),
                "--independent",
                str(self.independent),
                "--require-merge",
                "--output",
                str(output),
            ]
        )
        self.assertEqual(code, 1)
        self.assertEqual(a.strict_json(output / "rejected.json")["status"], "failed")

    def test_end_to_end_agreement_with_merge_and_no_promotion(self):
        output = self.root / "agreement"
        env = {
            "GITHUB_RUN_ID": CONTEXT["runId"],
            "GITHUB_RUN_ATTEMPT": CONTEXT["runAttempt"],
            "GITHUB_REPOSITORY": CONTEXT["repository"],
            "GITHUB_WORKFLOW_SHA": CONTEXT["workflowSha"],
        }
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(a, "git", return_value="d" * 40),
        ):
            code = a.main(
                [
                    "--source-commit",
                    SOURCE,
                    "--qualification",
                    str(self.standard),
                    "--independent",
                    str(self.independent),
                    "--require-merge",
                    "--merge",
                    str(self.merge),
                    "--base-commit",
                    BASE,
                    "--output",
                    str(output),
                ]
            )
        self.assertEqual(code, 0)
        state = a.strict_json(output / "CURRENT_STATE.json")
        self.assertTrue(state["mergeTreeVerified"])
        self.assertFalse(state["is_production_implemented"])
        self.assertEqual(state["promotion"], "not_authorized")

    def test_retain_actual_binary_bytes(self):
        target = self.root / "target"
        target.mkdir()
        binary = target / "example"
        binary.write_bytes(b"actual fixture bytes")
        output = self.root / "binary-evidence"
        output.mkdir()
        (output / "release.log").write_text(
            json.dumps(
                {
                    "reason": "compiler-artifact",
                    "executable": str(binary),
                    "target": {"name": "example", "kind": ["bin"]},
                }
            )
            + "\n"
        )
        row = {
            "name": "release-binaries",
            "status": "passed",
            "log": "release.log",
            "binaries": [{"name": "example", "sha256": q.sha256(binary)}],
        }
        ci.retain_binaries({"commands": [row]}, output, target)
        self.assertEqual(
            (output / row["binaries"][0]["artifact"]).read_bytes(), binary.read_bytes()
        )

    def test_retain_refuses_binary_outside_target(self):
        output = self.root / "bad-binary-evidence"
        output.mkdir()
        binary = self.root / "unrelated"
        binary.write_bytes(b"must not be exported")
        (output / "release.log").write_text(
            json.dumps(
                {
                    "reason": "compiler-artifact",
                    "executable": str(binary),
                    "target": {"name": "example", "kind": ["bin"]},
                }
            )
            + "\n"
        )
        row = {
            "name": "release-binaries",
            "status": "passed",
            "log": "release.log",
            "binaries": [{"name": "example", "sha256": q.sha256(binary)}],
        }
        with self.assertRaises(ValueError):
            ci.retain_binaries({"commands": [row]}, output, self.root / "target")

    def test_real_git_commit_object_verification(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "tracked").write_text("real Git object fixture\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            check=True,
        )
        head = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
        raw = subprocess.check_output(
            ["git", "-C", str(repo), "cat-file", "commit", head]
        )
        self.assertEqual(
            hashlib.sha1(b"commit " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
            head,
        )


if __name__ == "__main__":
    unittest.main()
