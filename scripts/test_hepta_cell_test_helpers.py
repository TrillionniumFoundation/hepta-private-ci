#!/usr/bin/env python3
"""Exercise read-only helper verification with real Git and synthetic file copies."""

import contextlib
import hashlib
import io
import json
import os
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

    def verify(
        self,
        output=None,
        packages=("codex-app-server",),
        *,
        extra=(),
        root=None,
        environment=None,
    ):
        root = root or self.root
        command = [
            sys.executable,
            str(root / "scripts" / SCRIPT.name),
            "--verify-only",
            "--output-dir",
            str(output or self.output),
        ]
        for package in packages:
            command.extend(["--package", package])
        command.extend(extra)
        if environment is None and "--transported" in extra:
            environment = {
                key: value
                for key, value in os.environ.items()
                if key
                not in {
                    prefix + name
                    for prefix in ("CARGO_BIN_EXE_", "NEXTEST_BIN_EXE_")
                    for name in ("hepta-joint-propose", "hepta_joint_propose")
                }
            }
        result = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, report["exit_code"])
        return report

    def prepare_joint_transport(self):
        namespace = runpy.run_path(str(self.script))
        target, profile = "aarch64-unknown-linux-gnu", "ci"
        compiler = self.workspace / "target" / target / profile / "hepta-joint-propose"
        compiler.parent.mkdir(parents=True)
        content = b"synthetic Joint helper bytes; never executed\n"
        compiler.write_bytes(content)
        compiler.chmod(0o755)
        pinned = self.output / "bin" / "hepta-joint-propose"
        pinned.write_bytes(content)
        pinned.chmod(0o555)
        package = "codex-hepta-infer-worker-host"
        self.manifest.update(
            target=target,
            cargo_profile=profile,
            output_dir=str(self.output),
            selected_packages=[package],
            artifacts={
                "hepta-joint-propose": {
                    "package": package,
                    "package_id": "synthetic-joint-helper",
                    "compiler_executable": str(compiler),
                    "executable": str(pinned),
                    "profile": {"test": False},
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            },
            builds=[
                {
                    "package": package,
                    "binaries": ["hepta-joint-propose"],
                    "command": namespace["build_command"](package, target, profile),
                    "complete": True,
                    "cargo_finished": True,
                    "exit_code": 0,
                }
            ],
        )
        self.environment = {
            prefix + name: str(pinned)
            for prefix in ("CARGO_BIN_EXE_", "NEXTEST_BIN_EXE_")
            for name in ("hepta-joint-propose", "hepta_joint_propose")
        }
        self.save_evidence()
        moved = self.output.parent / "downloaded-joint"
        shutil.copytree(self.output, moved)
        clone = self.root.parent / "consumer-repo"
        subprocess.run(
            [
                "git",
                "clone",
                "--quiet",
                "--local",
                "--no-hardlinks",
                str(self.root),
                str(clone),
            ],
            check=True,
            capture_output=True,
        )
        (clone / "codex-rs").mkdir()
        flags = ("--transported", "--target", target, "--cargo-profile", profile)
        return moved, clone, flags

    def test_transport_requires_same_source_target_profile_and_preserves_originals(
        self,
    ):
        moved, clone, flags = self.prepare_joint_transport()
        before = {p.name: p.read_bytes() for p in moved.glob("*.json")}
        report = self.verify(
            moved,
            ("codex-hepta-infer-worker-host",),
            extra=flags,
            root=clone,
        )
        self.assertTrue(report["complete"], report)
        self.assertEqual(report["source_before"], report["source_after"])
        self.assertEqual(report["source_before"]["head"], self.head)
        self.assertEqual(
            report["runtime_environment"],
            {
                key: str(moved / "bin" / "hepta-joint-propose")
                for key in self.environment
            },
        )
        self.assertEqual(before, {p.name: p.read_bytes() for p in moved.glob("*.json")})
        for wrong in (
            (
                "--transported",
                "--target",
                "x86_64-unknown-linux-gnu",
                "--cargo-profile",
                "ci",
            ),
            (
                "--transported",
                "--target",
                "aarch64-unknown-linux-gnu",
                "--cargo-profile",
                "release",
            ),
        ):
            with self.subTest(flags=wrong):
                self.assertFalse(
                    self.verify(
                        moved,
                        ("codex-hepta-infer-worker-host",),
                        extra=wrong,
                        root=clone,
                    )["complete"]
                )
        (clone / "source.txt").write_text("changed consumer source\n")
        self.assertFalse(
            self.verify(
                moved,
                ("codex-hepta-infer-worker-host",),
                extra=flags,
                root=clone,
            )["complete"]
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(clone),
                "-c",
                "user.name=Transport regression",
                "-c",
                "user.email=transport@example.invalid",
                "commit",
                "-qam",
                "Different source",
            ],
            check=True,
            capture_output=True,
        )
        self.assertFalse(
            self.verify(
                moved,
                ("codex-hepta-infer-worker-host",),
                extra=flags,
                root=clone,
            )["complete"]
        )

    def test_transported_tamper_and_original_alias_drift_are_rejected(self):
        moved, clone, flags = self.prepare_joint_transport()
        pinned = moved / "bin" / "hepta-joint-propose"
        original = pinned.read_bytes()
        pinned.chmod(0o755)
        pinned.write_bytes(b"X" + original[1:])
        pinned.chmod(0o555)
        self.assertFalse(
            self.verify(
                moved,
                ("codex-hepta-infer-worker-host",),
                extra=flags,
                root=clone,
            )["complete"]
        )
        pinned.chmod(0o755)
        pinned.write_bytes(original)
        pinned.chmod(0o555)
        environment = dict(self.environment)
        environment["NEXTEST_BIN_EXE_hepta_joint_propose"] = str(pinned)
        (moved / "env.json").write_text(json.dumps(environment))
        self.assertFalse(
            self.verify(
                moved,
                ("codex-hepta-infer-worker-host",),
                extra=flags,
                root=clone,
            )["complete"]
        )

    def test_transported_runtime_requires_every_alias_to_match(self):
        moved, clone, flags = self.prepare_joint_transport()
        runtime = {
            key: str(moved / "bin" / "hepta-joint-propose") for key in self.environment
        }
        environment = {**os.environ, **runtime}
        report = self.verify(
            moved,
            ("codex-hepta-infer-worker-host",),
            extra=(*flags, "--require-runtime-env"),
            root=clone,
            environment=environment,
        )
        self.assertTrue(report["complete"], report)
        for missing in (True, False):
            changed = dict(environment)
            key = "CARGO_BIN_EXE_hepta_joint_propose"
            if missing:
                del changed[key]
            else:
                changed[key] = str(self.output / "bin" / "hepta-joint-propose")
            with self.subTest(missing=missing):
                self.assertFalse(
                    self.verify(
                        moved,
                        ("codex-hepta-infer-worker-host",),
                        extra=(*flags, "--require-runtime-env"),
                        root=clone,
                        environment=changed,
                    )["complete"]
                )

    def test_build_uses_explicit_target_profile_and_requires_them_at_verification(self):
        output = self.output.parent / "target-profile-build"
        namespace = runpy.run_path(str(self.script))
        expected = [
            "cargo",
            "build",
            "--locked",
            "--message-format=json-render-diagnostics",
            "-p",
            "codex-app-server",
            "--target",
            "aarch64-unknown-linux-gnu",
            "--profile",
            "ci",
            "--bin",
            "codex-app-server",
            "--bin",
            "exec-server",
        ]
        real_run = subprocess.run

        def cargo_build(command, **kwargs):
            if command[0] != "cargo":
                return real_run(command, **kwargs)
            self.assertEqual(command, expected)
            for binary, artifact in self.manifest["artifacts"].items():
                kwargs["stdout"].write(
                    (
                        json.dumps(
                            {
                                "reason": "compiler-artifact",
                                "package_id": artifact["package_id"],
                                "target": {"name": binary, "kind": ["bin"]},
                                "executable": artifact["compiler_executable"],
                                "profile": artifact["profile"],
                            }
                        )
                        + "\n"
                    ).encode()
                )
            kwargs["stdout"].write(b'{"reason":"build-finished","success":true}\n')
            return subprocess.CompletedProcess(command, 0)

        flags = ["--target", "aarch64-unknown-linux-gnu", "--cargo-profile", "ci"]
        arguments = [
            str(self.script),
            "--output-dir",
            str(output),
            "--package",
            "codex-app-server",
            *flags,
        ]
        with (
            mock.patch.object(sys, "argv", arguments),
            mock.patch.object(subprocess, "run", side_effect=cargo_build),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(namespace["main"](), 0)
        self.assertTrue(self.verify(output, extra=flags)["complete"])
        self.assertFalse(self.verify(output)["complete"])

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
