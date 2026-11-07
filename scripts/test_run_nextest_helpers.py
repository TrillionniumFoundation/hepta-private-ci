"""Runtime fixture receipts and CLI boundaries; no model or network execution."""

import copy
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "run_nextest_helpers_under_test", Path(__file__).with_name("run-nextest.py")
)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class RuntimeHelperTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="nextest-runtime-helpers-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "Cargo.toml").write_text("[workspace]\nmembers = []\n")
        self.consumer = self.package("consumer", [])
        self.consumer["features"] = {"negative": [], "default": []}
        self.owner = self.package("helper-owner", ["fixture-helper"])
        self.unrelated = self.package("unrelated", [])
        self.metadata = {
            "workspace_root": str(self.root),
            "workspace_members": [
                p["id"] for p in (self.consumer, self.owner, self.unrelated)
            ],
            "workspace_default_members": [self.consumer["id"]],
            "packages": [self.consumer, self.owner, self.unrelated],
        }
        self.executable = self.root / "artifact-with-no-assumed-layout"
        self.executable.write_text("real artifact placeholder for receipt validation\n")
        self.executable.chmod(0o700)
        self.target = self.owner["targets"][0]
        self.expected = {(self.owner["id"], "fixture-helper"): self.target}
        self.declared_helpers = copy.deepcopy(RUNNER.RUNTIME_TEST_HELPERS)
        helper_map = patch.dict(
            RUNNER.RUNTIME_TEST_HELPERS,
            {"consumer": (("helper-owner", "fixture-helper"),)},
            clear=True,
        )
        helper_map.start()
        self.addCleanup(helper_map.stop)

    def package(self, name, bins):
        root = self.root / name
        root.mkdir()
        manifest = root / "Cargo.toml"
        manifest.write_text(f'[package]\nname="{name}"\nversion="1.0.0"\n')
        return {
            "id": f"path+file://{root}#{name}@1.0.0",
            "name": name,
            "version": "1.0.0",
            "manifest_path": str(manifest),
            "features": {},
            "targets": [
                {
                    "name": binary,
                    "kind": ["bin"],
                    "src_path": str(root / f"{binary}.rs"),
                }
                for binary in bins
            ],
        }

    def receipt(self, **changes):
        message = {
            "reason": "compiler-artifact",
            "package_id": self.owner["id"],
            "target": copy.deepcopy(self.target),
            "profile": {"test": False},
            "executable": str(self.executable),
        }
        message.update(changes)
        return message

    def output(self, *messages, finished=True):
        if not messages:
            messages = (self.receipt(),)
        return "\n".join(
            json.dumps(item)
            for item in (
                *messages,
                {
                    "reason": "build-finished",
                    "success": finished,
                },
            )
        )

    def prepare(self, args, output=None, environment=None, status=0):
        result = subprocess.CompletedProcess(
            ["cargo", "build"],
            status,
            stdout=self.output() if output is None else output,
        )
        with patch.object(RUNNER.subprocess, "run", return_value=result) as build:
            env = RUNNER.runtime_helper_environment(
                args,
                self.metadata,
                environment={} if environment is None else environment,
            )
        return env, build

    def test_exec_server_receives_repo_bwrap_for_scoped_and_workspace_runs(self):
        consumer = self.package("codex-exec-server", [])
        owner = self.package("codex-bwrap", ["bwrap"])
        windows = self.package(
            "codex-windows-sandbox",
            [
                "codex-command-runner",
                "codex-windows-sandbox-setup",
            ],
        )
        packages = [consumer, owner, windows]
        self.metadata = {
            "workspace_root": str(self.root),
            "workspace_members": [package["id"] for package in packages],
            "workspace_default_members": [consumer["id"]],
            "packages": packages,
        }
        existing = {
            f"CARGO_BIN_EXE_{name}": str(self.executable)
            for name in ("codex-command-runner", "codex-windows-sandbox-setup")
        }
        output = self.output(
            self.receipt(
                package_id=owner["id"],
                target=owner["targets"][0],
            )
        )
        with patch.dict(RUNNER.RUNTIME_TEST_HELPERS, self.declared_helpers, clear=True):
            for arguments in (
                ["-p", "codex-exec-server", "--locked"],
                ["--workspace", "--locked"],
            ):
                with self.subTest(arguments=arguments):
                    env, build = self.prepare(
                        arguments, output=output, environment=existing
                    )
                    self.assertEqual(
                        env, {**existing, "CARGO_BIN_EXE_bwrap": str(self.executable)}
                    )
                    build.assert_called_once()
                    command = build.call_args.args[0]
                    self.assertIn(owner["id"], command)
                    self.assertEqual(
                        [
                            command[index + 1]
                            for index, value in enumerate(command)
                            if value == "--bin"
                        ],
                        ["bwrap"],
                    )

    def test_exact_artifact_path_is_exposed_without_changing_test_arguments(self):
        args = [
            "-p",
            "consumer",
            "--locked",
            "--offline",
            "--retries",
            "0",
            "--",
            "--exact",
        ]
        command = ["cargo", "nextest", "run", "--no-fail-fast", *args]
        result = subprocess.CompletedProcess([], 0, stdout=self.output())
        with patch.object(RUNNER.subprocess, "run", return_value=result) as build:
            with patch.object(RUNNER.subprocess, "call", return_value=100) as nextest:
                self.assertEqual(
                    RUNNER.run_nextest_command(command, args, self.metadata), 100
                )
        self.assertEqual(nextest.call_args.args[0], command)
        env = nextest.call_args.kwargs["env"]
        self.assertEqual(env["CARGO_BIN_EXE_fixture-helper"], str(self.executable))
        self.assertEqual(env["CARGO_BIN_EXE_fixture_helper"], str(self.executable))
        built = build.call_args.args[0]
        self.assertIn("--locked", built)
        self.assertIn("--offline", built)
        self.assertNotIn("--retries", built)
        self.assertEqual(built[built.index("--profile") + 1], "test")
        self.assertIn(self.consumer["id"], built)
        self.assertIn(self.owner["id"], built)
        self.assertNotIn(self.unrelated["id"], built)

    def test_cargo_profile_target_features_and_config_are_forwarded_separately(self):
        args = [
            "--package=consumer",
            "--profile",
            "local",
            "--cargo-profile=qualification",
            "--target",
            "aarch64-unknown-linux-gnu",
            "--target-dir",
            str(self.root / "out"),
            "--features",
            "consumer/negative",
            "--no-default-features",
            "--all-features",
            "--build-jobs",
            "-1",
            "--config",
            "build.incremental=false",
            "--frozen",
        ]
        _, build = self.prepare(args)
        built = build.call_args.args[0]
        for pair in (
            ["--profile", "qualification"],
            ["--target", "aarch64-unknown-linux-gnu"],
            ["--target-dir", str(self.root / "out")],
            ["--jobs", "-1"],
            ["--config", "build.incremental=false"],
        ):
            self.assertIn(pair, [built[i : i + 2] for i in range(len(built) - 1)])
        self.assertNotIn("local", built)
        self.assertIn("--no-default-features", built)
        self.assertNotIn("--all-features", built)
        features = built[built.index("--features") + 1].split(",")
        self.assertEqual(features, ["consumer/default", "consumer/negative"])
        self.assertIn("--frozen", built)

    def test_adding_helper_owner_does_not_expand_bare_or_all_feature_selection(self):
        self.owner["features"] = {"negative": [], "helper-only": []}
        for feature_args, expected in (
            (["--features", "negative"], {"consumer/negative"}),
            (["--all-features"], {"consumer/default", "consumer/negative"}),
        ):
            with self.subTest(feature_args=feature_args):
                _, build = self.prepare(["-p", "consumer", *feature_args])
                args = build.call_args.args[0]
                self.assertEqual(
                    set(args[args.index("--features") + 1].split(",")), expected
                )
                self.assertNotIn("--all-features", args)
        with self.assertRaisesRegex(RUNNER.RuntimeHelperError, "originally selected"):
            self.prepare(["-p", "consumer", "--features", "helper-owner/helper-only"])

    def test_release_does_not_add_test_profile(self):
        _, build = self.prepare(["-pconsumer", "--release"])
        self.assertIn("--release", build.call_args.args[0])
        self.assertNotIn("--profile", build.call_args.args[0])

    def test_short_test_threads_are_not_cargo_build_jobs(self):
        for args in (["-j", "1"], ["-j1"], ["-j", "-1"]):
            with self.subTest(args=args):
                _, build = self.prepare(["-p", "consumer", *args])
                self.assertNotIn("--jobs", build.call_args.args[0])
                self.assertNotIn("-j", build.call_args.args[0])

    def test_workspace_and_manifest_selection_respect_excluded_consumers(self):
        env, build = self.prepare(["--workspace", "--exclude", "consumer"])
        self.assertIsNone(env)
        build.assert_not_called()
        env, build = self.prepare(["--manifest-path", self.consumer["manifest_path"]])
        self.assertIn("CARGO_BIN_EXE_fixture-helper", env)
        self.assertIn(self.consumer["manifest_path"], build.call_args.args[0])
        env, build = self.prepare(["--manifest-path", str(self.root / "Cargo.toml")])
        self.assertIn("CARGO_BIN_EXE_fixture-helper", env)
        env, build = self.prepare(["-p", "unrelated"])
        self.assertIsNone(env)
        build.assert_not_called()

    def test_excluding_helper_tests_keeps_the_consumers_runtime_dependency(self):
        env, build = self.prepare(["--workspace", "--exclude=helper-owner"])
        self.assertIn(self.owner["id"], build.call_args.args[0])
        self.assertIn("CARGO_BIN_EXE_fixture-helper", env)

    def test_cargo_explicit_value_wins_and_invalid_value_blocks_nextest_fallback(self):
        supplied = {
            "CARGO_BIN_EXE_fixture-helper": str(self.executable),
            "NEXTEST_BIN_EXE_fixture-helper": "/unusable/lower-priority",
            "UNRELATED": "kept",
        }
        before = supplied.copy()
        env, build = self.prepare(["-p", "consumer"], environment=supplied)
        self.assertEqual(env, before)
        self.assertEqual(supplied, before)
        build.assert_not_called()
        supplied["CARGO_BIN_EXE_fixture-helper"] = "/missing/higher-priority"
        supplied["NEXTEST_BIN_EXE_fixture-helper"] = str(self.executable)
        with patch.object(RUNNER.subprocess, "run") as build:
            with self.assertRaisesRegex(
                RUNNER.RuntimeHelperError, "CARGO_BIN_EXE_fixture-helper"
            ):
                RUNNER.runtime_helper_environment(
                    ["-p", "consumer"], self.metadata, supplied
                )
            build.assert_not_called()

    def test_underscore_explicit_key_is_preserved_without_inventing_higher_precedence_key(
        self,
    ):
        supplied = {"CARGO_BIN_EXE_fixture_helper": str(self.executable)}
        env, build = self.prepare(["-p", "consumer"], environment=supplied)
        self.assertEqual(env, supplied)
        self.assertNotIn("CARGO_BIN_EXE_fixture-helper", env)
        build.assert_not_called()

    @unittest.skipIf(
        os.name == "nt", "Windows executable access does not use Unix mode bits"
    )
    def test_existing_unix_file_without_execute_permission_is_rejected(self):
        self.executable.chmod(0o600)
        with self.assertRaisesRegex(RUNNER.RuntimeHelperError, "not executable"):
            self.prepare(
                ["-p", "consumer"],
                environment={"CARGO_BIN_EXE_fixture-helper": str(self.executable)},
            )

    def test_wrong_package_name_kind_source_or_test_harness_never_supplies_helper(self):
        variants = [
            self.receipt(package_id=self.unrelated["id"]),
            self.receipt(target={**self.target, "name": "different-helper"}),
            self.receipt(target={**self.target, "kind": ["lib"]}),
            self.receipt(target={**self.target, "src_path": "/different/source.rs"}),
            self.receipt(profile={"test": True}),
            self.receipt(profile={}),
        ]
        for message in variants:
            with self.subTest(message=message):
                with self.assertRaises(RUNNER.RuntimeHelperError):
                    RUNNER.helper_artifacts(self.output(message), self.expected)

    def test_missing_relative_or_nonexistent_artifacts_are_rejected(self):
        for value in (
            None,
            "target/debug/fixture-helper",
            str(self.root / "missing"),
            str(self.root),
        ):
            with self.subTest(executable=value):
                with self.assertRaises(RUNNER.RuntimeHelperError):
                    RUNNER.helper_artifacts(
                        self.output(self.receipt(executable=value)), self.expected
                    )
        with self.assertRaisesRegex(RUNNER.RuntimeHelperError, "missing or ambiguous"):
            RUNNER.helper_artifacts(
                json.dumps({"reason": "build-finished", "success": True}), self.expected
            )

    def test_multiple_target_executables_are_rejected_instead_of_selecting_first(self):
        another = self.root / "another-real-artifact"
        another.write_text("different target\n")
        another.chmod(0o700)
        with self.assertRaisesRegex(RUNNER.RuntimeHelperError, "ambiguous"):
            RUNNER.helper_artifacts(
                self.output(self.receipt(), self.receipt(executable=str(another))),
                self.expected,
            )

    def test_failed_build_and_missing_completion_never_launch_tests(self):
        with patch.object(
            RUNNER.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 17, stdout=self.output()),
        ):
            with patch.object(RUNNER.subprocess, "call") as nextest:
                self.assertEqual(
                    RUNNER.run_nextest_command(
                        ["cargo", "nextest", "run"], ["-p", "consumer"], self.metadata
                    ),
                    17,
                )
                nextest.assert_not_called()
        for output in (
            json.dumps(self.receipt()),
            self.output(finished=False),
            "not artifact JSON",
        ):
            with self.subTest(output=output):
                with self.assertRaises(RUNNER.RuntimeHelperError):
                    RUNNER.helper_artifacts(output, self.expected)

    def test_unsupported_source_build_inputs_fail_only_if_new_helpers_are_needed(self):
        for args in (
            ["-p", "consumer", "--future-build-option"],
            ["-p", "consumer", "--release", "--cargo-profile", "dev"],
            ["-p", "consumer", "--target", "one", "--target", "two"],
        ):
            with self.subTest(args=args):
                with patch.object(RUNNER.subprocess, "run") as build:
                    with self.assertRaises(RUNNER.RuntimeHelperError):
                        RUNNER.runtime_helper_environment(args, self.metadata, {})
                    build.assert_not_called()
                env, build = self.prepare(
                    args,
                    environment={"CARGO_BIN_EXE_fixture-helper": str(self.executable)},
                )
                self.assertEqual(
                    env["CARGO_BIN_EXE_fixture-helper"], str(self.executable)
                )
                build.assert_not_called()

    def test_reused_builds_and_opaque_package_selection_keep_original_pass_through(
        self,
    ):
        for args in (
            ["-p", "cons*"],
            ["-p", "unknown"],
            ["-p", "consumer", "--archive-file", "archive.tar.zst"],
            ["-p", "consumer", "--cargo-metadata", "original.json"],
            ["--workspace", "--exclude", "unrelated*"],
        ):
            with self.subTest(args=args):
                env, build = self.prepare(args)
                self.assertIsNone(env)
                build.assert_not_called()
                command = ["cargo", "nextest", "run", *args]
                with patch.object(
                    RUNNER.subprocess, "call", return_value=42
                ) as nextest:
                    self.assertEqual(
                        RUNNER.run_nextest_command(command, args, self.metadata), 42
                    )
                    self.assertEqual(nextest.call_args.args[0], command)

    def test_compiler_errors_and_non_json_diagnostics_are_retained(self):
        diagnostic = json.dumps(
            {
                "reason": "compiler-message",
                "message": {
                    "rendered": "error[E0001]: original compiler diagnosis\n",
                },
            }
        )
        for status, output in ((12, diagnostic), (0, "original non-JSON diagnostic\n")):
            with self.subTest(status=status):
                stderr = io.StringIO()
                with patch.object(
                    RUNNER.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], status, stdout=output),
                ):
                    with patch.object(RUNNER.subprocess, "call") as nextest:
                        with contextlib.redirect_stderr(stderr):
                            result = RUNNER.run_nextest_command(
                                ["cargo", "nextest", "run"],
                                ["-p", "consumer"],
                                self.metadata,
                            )
                        nextest.assert_not_called()
                self.assertEqual(result, status if status else 2)
                self.assertIn("original", stderr.getvalue())

    def test_package_ids_and_version_selectors_bind_the_declared_owner(self):
        for selector in (self.consumer["id"], "consumer@1.0.0"):
            with self.subTest(selector=selector):
                env, _ = self.prepare(["-p", selector])
                self.assertEqual(
                    env["CARGO_BIN_EXE_fixture-helper"], str(self.executable)
                )

    def test_arguments_after_separator_do_not_change_build_scope(self):
        env, build = self.prepare(
            ["-p", "consumer", "--", "--target", "not-a-build-target"]
        )
        self.assertIn("CARGO_BIN_EXE_fixture-helper", env)
        self.assertNotIn("not-a-build-target", build.call_args.args[0])

    def test_malformed_manifest_and_help_are_left_to_nextest_without_building(self):
        for args in (["--manifest-path"], ["--manifest-path", "--offline"], ["--help"]):
            with self.subTest(args=args):
                env, build = self.prepare(args)
                self.assertIsNone(env)
                build.assert_not_called()


@unittest.skipUnless(
    shutil.which("cargo") and shutil.which("cargo-nextest"),
    "requires Cargo and nextest",
)
class RealCrossPackageHelperTests(unittest.TestCase):
    def test_missing_metadata_fails_then_scoped_and_workspace_runs_launch_the_real_helper(
        self,
    ):
        with tempfile.TemporaryDirectory(prefix="nextest-cross-package-") as directory:
            root = Path(directory)
            (root / "consumer/tests").mkdir(parents=True)
            (root / "consumer/src").mkdir()
            (root / "server/src").mkdir(parents=True)
            (root / "Cargo.toml").write_text(
                '[workspace]\nresolver="3"\nmembers=["consumer", "server"]\n'
            )
            (root / "consumer/Cargo.toml").write_text(
                '[package]\nname="nextest-helper-consumer"\nversion="0.1.0"\nedition="2024"\n'
                "[features]\nnegative=[]\n"
            )
            (root / "consumer/src/lib.rs").write_text("// Integration-test consumer.\n")
            (root / "consumer/tests/helper.rs").write_text(
                "#[test]\nfn launches_declared_helper() {\n"
                ' assert!(!cfg!(feature="negative"));\n'
                ' let path=std::env::var("CARGO_BIN_EXE_nextest-runtime-fixture")'
                '.expect("declared helper metadata missing");\n'
                ' let output=std::process::Command::new(path).output().expect("real helper spawn");\n'
                " assert!(output.status.success());\n"
                ' assert_eq!(output.stdout, b"fixture-ok\\n");\n}\n'
            )
            (root / "server/Cargo.toml").write_text(
                '[package]\nname="nextest-helper-owner"\nversion="0.1.0"\nedition="2024"\n'
                '[[bin]]\nname="nextest-runtime-fixture"\npath="src/main.rs"\n'
            )
            (root / "server/src/main.rs").write_text(
                'fn main() { println!("fixture-ok"); }\n'
            )
            (root / "Cargo.lock").write_text(
                'version = 4\n\n[[package]]\nname="nextest-helper-consumer"\nversion="0.1.0"\n'
                '\n[[package]]\nname="nextest-helper-owner"\nversion="0.1.0"\n'
            )
            environment = os.environ.copy()
            for key in RUNNER.helper_env_keys("nextest-runtime-fixture"):
                environment.pop(key, None)
            environment.update(
                {
                    "CARGO_TARGET_DIR": str(root / "artifacts"),
                    "NEXTEST_PROFILE": "default",
                    "HEPTA_NEXTTEST_FULL_METADATA": "0",
                    "CARGO_NET_OFFLINE": "true",
                }
            )
            scoped = [
                "-p",
                "nextest-helper-consumer",
                "--locked",
                "--offline",
                "--retries",
                "0",
            ]
            baseline = subprocess.run(
                ["cargo", "nextest", "run", "--no-fail-fast", *scoped],
                cwd=root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=120,
            )
            self.assertNotEqual(baseline.returncode, 0, baseline.stdout)
            self.assertIn("declared helper metadata missing", baseline.stdout)
            runner = Path(__file__).with_name("run-nextest.py")
            launcher = (
                "import importlib.util,sys;"
                f"s=importlib.util.spec_from_file_location('fixture_runner',{str(runner)!r});"
                "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                "m.RUNTIME_TEST_HELPERS={'nextest-helper-consumer':"
                "(('nextest-helper-owner','nextest-runtime-fixture'),)};"
                "raise SystemExit(m.run(sys.argv[1:]))"
            )
            for arguments, successful in (
                (scoped, True),
                (["--workspace", "--locked", "--offline", "--retries", "0"], True),
                ([*scoped, "--features", "negative"], False),
            ):
                with self.subTest(arguments=arguments):
                    result = subprocess.run(
                        [sys.executable, "-c", launcher, *arguments],
                        cwd=root,
                        env=environment,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        check=False,
                        timeout=120,
                    )
                    self.assertEqual(result.returncode == 0, successful, result.stdout)
                    self.assertIn(
                        "Runtime helper nextest-runtime-fixture:", result.stdout
                    )
                    self.assertIn("1 test run:", result.stdout)
                    self.assertIn(
                        "1 passed" if successful else "1 failed", result.stdout
                    )


if __name__ == "__main__":
    unittest.main()
