#!/usr/bin/env python3
"""Exercise read-only helper verification with real Git and synthetic file copies."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().with_name("hepta_cell_test_helpers.py")


class PinnedHelperVerificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        self.root = base / "repo"
        self.root.mkdir()
        scripts = self.root / "scripts"
        scripts.mkdir()
        self.script = scripts / SCRIPT.name
        shutil.copyfile(SCRIPT, self.script)
        (self.root / ".gitignore").write_text("codex-rs/target/\n", encoding="utf-8")
        (self.root / "source.txt").write_text("prepared source\n", encoding="utf-8")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-qm", "synthetic helper verification source")
        self.head = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")
        self.workspace = self.root / "codex-rs"
        compiler_dir = self.workspace / "target" / "debug"
        compiler_dir.mkdir(parents=True)
        self.output = base / "attempt"
        pinned_dir = self.output / "bin"
        pinned_dir.mkdir(parents=True)
        binaries = ["codex-app-server", "exec-server"]
        artifacts = {}
        self.environment = {}
        for binary in binaries:
            # These fixture bytes are never executed and do not claim a Cargo build.
            content = f"#!/bin/sh\n# synthetic {binary}\nexit 0\n".encode()
            compiler = compiler_dir / binary
            compiler.write_bytes(content)
            compiler.chmod(0o755)
            pinned = pinned_dir / binary
            shutil.copyfile(compiler, pinned)
            pinned.chmod(0o555)
            artifacts[binary] = {
                "package": "codex-app-server",
                "package_id": "synthetic-codex-app-server",
                "compiler_executable": str(compiler),
                "executable": str(pinned),
                "profile": {"test": False},
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
            for name in {binary, binary.replace("-", "_")}:
                self.environment[f"CARGO_BIN_EXE_{name}"] = str(pinned)
                self.environment[f"NEXTEST_BIN_EXE_{name}"] = str(pinned)
        self.manifest = {
            "schema_version": 1,
            "source_sha": self.head,
            "source_sha_after": self.head,
            "source_status_before": "",
            "source_status_after": "",
            "workspace": str(self.workspace),
            "selected_packages": ["codex-app-server"],
            "complete": True,
            "exit_code": 0,
            "artifacts": artifacts,
            "builds": [
                {
                    "package": "codex-app-server",
                    "binaries": binaries,
                    "command": [
                        "cargo",
                        "build",
                        "--locked",
                        "--message-format=json-render-diagnostics",
                        "-p",
                        "codex-app-server",
                        "--bin",
                        "codex-app-server",
                        "--bin",
                        "exec-server",
                    ],
                    "complete": True,
                    "cargo_finished": True,
                    "exit_code": 0,
                }
            ],
        }
        self.save_evidence()

    def git(self, *arguments):
        return subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=Helper verifier regression",
                "-c",
                "user.email=helper-verifier@example.invalid",
                "-c",
                "commit.gpgsign=false",
                *arguments,
            ],
            cwd=self.root,
            text=True,
        ).strip()

    def save_evidence(self):
        (self.output / "manifest.json").write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )
        (self.output / "env.json").write_text(
            json.dumps(self.environment), encoding="utf-8"
        )

    def verify(self, output=None, packages=("codex-app-server",)):
        command = [
            sys.executable,
            str(self.script),
            "--verify-only",
            "--output-dir",
            str(output or self.output),
        ]
        for package in packages:
            command.extend(["--package", package])
        result = subprocess.run(
            command,
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, report["exit_code"])
        return report

    def test_pinned_copies_survive_cargo_path_rewrites_without_evidence_writes(self):
        for artifact in self.manifest["artifacts"].values():
            Path(artifact["compiler_executable"]).write_bytes(b"later Cargo relink\n")
        evidence = [path for path in self.output.rglob("*") if path.is_file()]
        before = {
            str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in evidence
        }
        report = self.verify()
        self.assertTrue(report["complete"])
        self.assertEqual(report["exit_code"], 0)
        self.assertEqual(
            report["source_before"],
            {"head": self.head, "tree": self.tree, "status": ""},
        )
        self.assertEqual(report["source_after"], report["source_before"])
        self.assertEqual(set(report["artifacts"]), {"codex-app-server", "exec-server"})
        self.assertTrue(
            all(artifact["match"] for artifact in report["artifacts"].values())
        )
        self.assertEqual(
            before,
            {
                str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in evidence
            },
        )

    def test_build_exports_both_prefixes_and_verifies_the_exact_copies(self):
        output = self.output.parent / "built-attempt"
        real_run = subprocess.run

        def cargo_build(command, **kwargs):
            if command[0] != "cargo":
                return real_run(command, **kwargs)
            self.assertEqual(command, self.manifest["builds"][0]["command"])
            self.assertEqual(kwargs["cwd"], self.workspace)
            # Supply controlled Cargo metadata for these synthetic file copies;
            # the real builder still pins, hashes and exports each executable.
            for binary, artifact in self.manifest["artifacts"].items():
                message = {
                    "reason": "compiler-artifact",
                    "package_id": artifact["package_id"],
                    "target": {"name": binary, "kind": ["bin"]},
                    "executable": artifact["compiler_executable"],
                    "profile": artifact["profile"],
                }
                kwargs["stdout"].write((json.dumps(message) + "\n").encode())
            kwargs["stdout"].write(b'{"reason":"build-finished","success":true}\n')
            return subprocess.CompletedProcess(command, 0)

        namespace = runpy.run_path(str(self.script))
        arguments = [
            str(self.script),
            "--output-dir",
            str(output),
            "--package",
            "codex-app-server",
        ]
        with (
            mock.patch.object(sys, "argv", arguments),
            mock.patch.object(subprocess, "run", side_effect=cargo_build),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(namespace["main"](), 0)
        self.assertEqual(
            json.loads((output / "env.json").read_text(encoding="utf-8")),
            {
                key: str(output / "bin" / Path(value).name)
                for key, value in self.environment.items()
            },
        )
        report = self.verify(output)
        self.assertTrue(report["complete"], report)
        self.assertEqual(report["exit_code"], 0)

    def test_environment_requires_both_prefixes_and_every_binary_alias(self):
        original = self.environment.copy()
        cases = []
        for prefix in ("CARGO_BIN_EXE", "NEXTEST_BIN_EXE"):
            cases.append(
                (
                    prefix,
                    {
                        key: value
                        for key, value in original.items()
                        if not key.startswith(prefix + "_")
                    },
                )
            )
        for missing in original:
            cases.append(
                (
                    missing,
                    {key: value for key, value in original.items() if key != missing},
                )
            )
        for missing, environment in cases:
            with self.subTest(missing=missing):
                self.environment = environment
                self.save_evidence()
                before = (self.output / "env.json").read_bytes()
                report = self.verify()
                self.assertFalse(report["complete"])
                self.assertIn("environment differs", report["error"])
                self.assertEqual((self.output / "env.json").read_bytes(), before)

    def test_environment_rejects_extra_keys_even_with_an_existing_pinned_path(self):
        original = self.environment.copy()
        pinned = self.manifest["artifacts"]["codex-app-server"]["executable"]
        for extra in (
            "CARGO_BIN_EXE_unprepared-helper",
            "NEXTEST_BIN_EXE_unprepared_helper",
            "UNRELATED_HELPER_SETTING",
        ):
            with self.subTest(extra=extra):
                self.environment = {**original, extra: pinned}
                self.save_evidence()
                before = (self.output / "env.json").read_bytes()
                report = self.verify()
                self.assertFalse(report["complete"])
                self.assertIn("environment differs", report["error"])
                self.assertEqual((self.output / "env.json").read_bytes(), before)

    def test_clean_different_source_commit_is_rejected(self):
        self.git("commit", "--allow-empty", "-qm", "different source")
        report = self.verify()
        self.assertFalse(report["complete"])
        self.assertIn("HEAD differs", report["error"])
        self.assertNotEqual(report["source_before"]["head"], self.head)

    def test_dirty_source_is_rejected(self):
        (self.root / "source.txt").write_text("changed source\n", encoding="utf-8")
        report = self.verify()
        self.assertFalse(report["complete"])
        self.assertIn("not clean", report["error"])

    def test_changed_pinned_copy_is_rejected_and_observed(self):
        pinned = Path(self.manifest["artifacts"]["codex-app-server"]["executable"])
        pinned.chmod(0o755)
        pinned.write_bytes(b"modified copy\n")
        pinned.chmod(0o555)
        report = self.verify()
        self.assertFalse(report["complete"])
        self.assertIn("content differs", report["error"])
        self.assertEqual(
            report["artifacts"]["codex-app-server"]["bytes"], len(b"modified copy\n")
        )
        self.assertFalse(report["artifacts"]["codex-app-server"]["match"])

    def test_empty_and_partial_artifact_sets_cannot_pass(self):
        original = self.manifest["artifacts"]
        for artifacts in [{}, {"exec-server": original["exec-server"]}]:
            with self.subTest(artifacts=list(artifacts)):
                self.manifest["artifacts"] = artifacts
                self.save_evidence()
                report = self.verify()
                self.assertFalse(report["complete"])
                self.assertIn("artifact set differs", report["error"])
        self.manifest.update(selected_packages=[], builds=[], artifacts={})
        self.environment = {}
        self.save_evidence()
        report = self.verify()
        self.assertFalse(report["complete"])
        self.assertIn("selection is empty", report["error"])

    def test_environment_cannot_redirect_to_mutable_cargo_path(self):
        artifact = self.manifest["artifacts"]["codex-app-server"]
        original = self.environment.copy()
        for key in (
            "CARGO_BIN_EXE_codex-app-server",
            "NEXTEST_BIN_EXE_codex_app_server",
        ):
            with self.subTest(key=key):
                self.environment = {**original, key: artifact["compiler_executable"]}
                self.save_evidence()
                report = self.verify()
                self.assertFalse(report["complete"])
                self.assertIn("environment differs", report["error"])

    def test_complete_subset_does_not_qualify_as_default_full_helper_set(self):
        report = self.verify(packages=())
        self.assertFalse(report["complete"])
        self.assertIn("packages differ", report["error"])

    def test_missing_attempt_is_not_created(self):
        missing = self.output.parent / "missing-attempt"
        report = self.verify(missing)
        self.assertFalse(report["complete"])
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
