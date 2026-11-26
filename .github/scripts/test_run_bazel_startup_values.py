#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import run_bazel_with_buildbuddy as wrapper


class BazelStartupValuesTest(unittest.TestCase):
    def test_keyless_unix_preserves_split_startup_values_and_ci_defaults(self) -> None:
        for runner, config in (
            ("Linux", "ci-linux"),
            ("Linux", "ci-v8"),
            ("macOS", "ci-macos"),
        ):
            with self.subTest(runner=runner, config=config):
                self.assertEqual(
                    wrapper.bazel_args_with_remote_config(
                        [
                            "--output_user_root",
                            "/tmp/build root",
                            "build",
                            f"--config={config}",
                            "--disk_cache=/caller/cache",
                            "--",
                            "//app:bin",
                        ],
                        {"RUNNER_OS": runner},
                    ),
                    [
                        "--output_user_root",
                        "/tmp/build root",
                        "build",
                        "--config=ci",
                        "--disk_cache=/caller/cache",
                        "--",
                        "//app:bin",
                    ],
                )

    def test_keyed_options_follow_actual_command_not_startup_value(self) -> None:
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(
                [
                    "--bazelrc",
                    "/tmp/custom rc",
                    "--host_jvm_args",
                    "-Xmx2g",
                    "test",
                    "--config=ci-linux",
                    "--",
                    "//app:test",
                ],
                {"BUILDBUDDY_API_KEY": "fixture-token"},
            ),
            [
                "--bazelrc",
                "/tmp/custom rc",
                "--host_jvm_args",
                "-Xmx2g",
                "test",
                "--config=buildbuddy-generic-rbe",
                "--remote_header=x-buildbuddy-api-key=fixture-token",
                "--config=ci-linux",
                "--",
                "//app:test",
            ],
        )

    def test_explicit_split_output_root_and_cache_choice_are_preserved(self) -> None:
        self.assertEqual(
            wrapper.startup_args(
                [
                    "--output_user_root",
                    "/caller/root",
                    "--experimental_remote_repo_contents_cache",
                    "build",
                ],
                {
                    "GITHUB_ACTIONS": "true",
                    "BAZEL_OUTPUT_USER_ROOT": "/environment/root",
                },
            ),
            [],
        )

    def test_startup_values_named_like_commands_are_not_commands(self) -> None:
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(
                [
                    "--bazelrc",
                    "build",
                    "--host_jvm_args",
                    "test",
                    "run",
                    "--config=ci-linux",
                    "//app:bin",
                    "--",
                    "test",
                ],
                {},
            ),
            [
                "--bazelrc",
                "build",
                "--host_jvm_args",
                "test",
                "run",
                "--config=ci",
                "//app:bin",
                "--",
                "test",
            ],
        )

    def test_windows_cross_abi_configuration_follows_split_startup_value(self) -> None:
        args = wrapper.bazel_args_with_remote_config(
            [
                "--output_base",
                "C:/build root",
                "test",
                "--config=ci-windows-cross",
                "--",
                "//app:test",
            ],
            {"RUNNER_OS": "Windows"},
        )
        self.assertEqual(
            args,
            [
                "--output_base",
                "C:/build root",
                "test",
                "--config=ci-windows",
                "--host_platform=//:local_windows_msvc",
                "--platforms=//:windows_x86_64_gnullvm",
                "--extra_execution_platforms=//:windows_x86_64_msvc",
                "--extra_toolchains=//:windows_gnullvm_tests_on_msvc_host_toolchain",
                "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                "--",
                "//app:test",
            ],
        )

    def test_windows_target_roster_survives_split_startup_value_and_is_removed(
        self,
    ) -> None:
        args = [
            "bazel",
            "--output_base",
            "C:/build root",
            "test",
            "--",
            "//app:test",
            "-//app:skip",
        ]
        with wrapper.windows_target_patterns(args, {"RUNNER_OS": "Windows"}) as (
            command,
            owned,
        ):
            self.assertIsNotNone(owned)
            self.assertEqual(
                owned.read_text(encoding="utf-8"), "//app:test\n-//app:skip\n"
            )
            self.assertEqual(command, [*args[:4], f"--target_pattern_file={owned}"])
        self.assertFalse(owned.exists())

    def test_administrative_command_does_not_gain_build_configuration(self) -> None:
        args = ["--output_user_root", "/tmp/root", "shutdown"]
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(args, {"RUNNER_OS": "Windows"}),
            args,
        )
        self.assertEqual(wrapper.bazel_args_with_remote_config(args, {}), args)

    def test_program_payload_after_separator_is_untouched(self) -> None:
        payload = ["--output_base", "test", "--config=ci-linux"]
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(
                [
                    "--output_base",
                    "/tmp/base",
                    "run",
                    "//app:bin",
                    "--",
                    *payload,
                ],
                {},
            ),
            ["--output_base", "/tmp/base", "run", "//app:bin", "--", *payload],
        )

    def test_startup_value_without_command_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected a Bazel command"):
            wrapper.bazel_command("--output_base", "/tmp/base", env={})

    def test_missing_startup_value_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "missing value for Bazel startup option"
        ):
            wrapper.bazel_command("--output_base", env={})

    def test_separator_without_command_is_not_a_build(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected a Bazel command"):
            wrapper.bazel_command("--", "build", env={})

    def test_equals_startup_syntax_remains_unchanged(self) -> None:
        self.assertEqual(
            wrapper.bazel_command(
                "--output_base=/tmp/base",
                "build",
                "--config=ci-linux",
                "--",
                "//app:bin",
                env={},
            ),
            [
                "bazel",
                "--output_base=/tmp/base",
                "build",
                "--config=ci",
                "--",
                "//app:bin",
            ],
        )

    def test_repeated_unary_options_and_nullary_flags_keep_their_order(self) -> None:
        args = [
            "--batch",
            "--host_jvm_args",
            "-Xmx2g",
            "--host_jvm_args",
            "-Dkey=build",
            "--max_idle_secs",
            "10",
            "--output_base",
            "/tmp/base",
            "build",
            "--config=ci-linux",
        ]
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(args, {}),
            [*args[:-1], "--config=ci"],
        )

    @unittest.skipIf(
        os.name == "nt",
        "POSIX executable fixture; Windows argv logic is covered above",
    )
    def test_real_wrapper_child_receives_roster_and_propagates_failure(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "fake bazel"
            capture = root / "argv.json"
            child.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "args = sys.argv[1:]\n"
                "path = next(Path(a.split('=', 1)[1]) for a in args "
                "if a.startswith('--target_pattern_file='))\n"
                "Path(os.environ['ARGV_CAPTURE']).write_text(json.dumps({"
                "'args': args, 'targets': path.read_text(), 'path': str(path)}))\n"
                "sys.exit(37)\n",
                encoding="utf-8",
            )
            child.chmod(0o755)
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith(
                    ("BAZEL_", "BUILDBUDDY_", "GITHUB_", "CODEX_BAZEL_")
                )
            }
            env.update(
                {
                    "CODEX_BAZEL_BIN": str(child),
                    "RUNNER_OS": "Windows",
                    "ARGV_CAPTURE": str(capture),
                }
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(wrapper.__file__)),
                    "--output_user_root",
                    str(root / "build root"),
                    "test",
                    "--config=ci-windows-cross",
                    "--",
                    "//app:test",
                    "-//app:skip",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 37, result.stderr)
            observed = json.loads(capture.read_text(encoding="utf-8"))
            self.assertEqual(
                observed["args"][:4],
                [
                    "--output_user_root",
                    str(root / "build root"),
                    "test",
                    "--config=ci-windows",
                ],
            )
            self.assertEqual(observed["targets"], "//app:test\n-//app:skip\n")
            self.assertFalse(Path(observed["path"]).exists())


if __name__ == "__main__":
    unittest.main()
