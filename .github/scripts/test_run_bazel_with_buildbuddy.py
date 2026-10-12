#!/usr/bin/env python3

import json
import contextlib
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import run_bazel_with_buildbuddy


class RunBazelWithBuildBuddyTest(unittest.TestCase):
    def test_raw_target_patterns_still_reject_embedded_and_trailing_line_breaks(
        self,
    ) -> None:
        for target in ["//bad\rtarget", "//bad\ntarget", "//bad:target\r"]:
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, "cannot contain line breaks"):
                    with run_bazel_with_buildbuddy.windows_target_patterns(
                        ["bazel", "build", "--", target], {"RUNNER_OS": "Windows"}
                    ):
                        self.fail("invalid target must not reach native Bazel")

    def test_explicit_pattern_file_is_not_replaced_or_deleted_by_transport(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            pattern_file = Path(directory) / "caller targets.txt"
            pattern_file.write_text("//caller:original\n", encoding="utf-8")
            args = [
                "bazel",
                "build",
                f"--target_pattern_file={pattern_file}",
                "--",
                "//caller:extra",
            ]
            with run_bazel_with_buildbuddy.windows_target_patterns(
                args, {"RUNNER_OS": "Windows"}
            ) as (command, owned):
                self.assertEqual(command, args)
                self.assertIsNone(owned)
            self.assertEqual(
                pattern_file.read_text(encoding="utf-8"), "//caller:original\n"
            )

    def test_wrapper_argument_file_round_trip_preserves_all_option_bytes(self) -> None:
        arguments = [
            "build",
            "",
            '--define=quoted "value"',
            r"C:\a b\c\\",
            "//路径:target",
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "arguments with spaces.nul"
            path.write_bytes(
                b"\0".join(value.encode("utf-8") for value in arguments) + b"\0"
            )
            self.assertEqual(
                run_bazel_with_buildbuddy.invocation_args(
                    ["--wrapper-args-file", str(path)]
                ),
                arguments,
            )
            for encoded in (b"build", b"", b"\xff\0"):
                path.write_bytes(encoded)
                with self.subTest(encoded=encoded), self.assertRaises(ValueError):
                    run_bazel_with_buildbuddy.invocation_args(
                        ["--wrapper-args-file", str(path)]
                    )
            with self.assertRaises(ValueError):
                run_bazel_with_buildbuddy.invocation_args(
                    ["--wrapper-args-file", str(path), "extra"]
                )

    def test_target_file_rejects_patterns_the_pinned_reader_would_change(self) -> None:
        lossy = [
            "",
            " ",
            "#comment",
            "//pkg:target#suffix",
            " //pkg:t",
            "//pkg:t\t",
            "\x1f//pkg:t",
            "//pkg:t\0suffix",
        ]
        for target in lossy:
            with (
                self.subTest(target=target),
                self.assertRaisesRegex(ValueError, "losslessly"),
            ):
                with run_bazel_with_buildbuddy.windows_target_patterns(
                    ["bazel", "build", "--", target], {"RUNNER_OS": "Windows"}
                ):
                    self.fail("lossy pattern must not reach Bazel")
        targets = [
            "//路径 with spaces:target",
            "-//excluded:target",
            "//pkg:nonbreaking\u00a0",
        ]
        with run_bazel_with_buildbuddy.windows_target_patterns(
            ["bazel", "build", "--", *targets], {"RUNNER_OS": "Windows"}
        ) as (_, path):
            internal = path.read_bytes().decode("latin-1")
            java_trim = "".join(chr(code) for code in range(0x21))
            parsed = [
                line.split("#", 1)[0].strip(java_trim) for line in internal.split("\n")
            ]
            actual = [line.encode("latin-1").decode("utf-8") for line in parsed if line]
            self.assertEqual(actual, targets)
        self.assertFalse(path.exists())

    def test_target_file_cleanup_covers_write_and_close_errors(self) -> None:
        for phase in ("write", "close"):
            with self.subTest(phase=phase), TemporaryDirectory() as directory:
                output = run_bazel_with_buildbuddy.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=directory, delete=False
                )
                path = Path(output.name)
                manager = mock.MagicMock()
                manager.__enter__.return_value = output

                def close_output(*unused):
                    output.close()
                    if phase == "close":
                        raise OSError("fixture close failure")

                manager.__exit__.side_effect = close_output
                writer = (
                    mock.patch.object(
                        output,
                        "writelines",
                        side_effect=OSError("fixture write failure"),
                    )
                    if phase == "write"
                    else contextlib.nullcontext()
                )
                with (
                    writer,
                    mock.patch.object(
                        run_bazel_with_buildbuddy,
                        "NamedTemporaryFile",
                        return_value=manager,
                    ),
                ):
                    with self.assertRaisesRegex(OSError, f"fixture {phase} failure"):
                        with run_bazel_with_buildbuddy.windows_target_patterns(
                            ["bazel", "build", "--", "//pkg:t"],
                            {"RUNNER_OS": "Windows"},
                        ):
                            self.fail("preparation failure must not launch Bazel")
                self.assertFalse(path.exists())

    def test_target_file_cleanup_preserves_child_failure_and_reports_unlink_error(
        self,
    ) -> None:
        diagnostics = io.StringIO()
        path = None
        try:
            with (
                contextlib.redirect_stderr(diagnostics),
                mock.patch.object(
                    Path, "unlink", side_effect=OSError("fixture unlink failure")
                ),
            ):
                with self.assertRaises(SystemExit) as failure:
                    with run_bazel_with_buildbuddy.windows_target_patterns(
                        ["bazel", "test", "--", "//pkg:t"], {"RUNNER_OS": "Windows"}
                    ) as (_, path):
                        raise SystemExit(37)
                self.assertEqual(failure.exception.code, 37)
            self.assertIn("fixture unlink failure", diagnostics.getvalue())
        finally:
            if path is not None:
                path.unlink()

    def test_target_file_cleanup_failure_after_success_is_not_hidden(self) -> None:
        path = None
        try:
            with mock.patch.object(
                Path, "unlink", side_effect=OSError("fixture unlink failure")
            ):
                with self.assertRaisesRegex(OSError, "fixture unlink failure"):
                    with run_bazel_with_buildbuddy.windows_target_patterns(
                        ["bazel", "build", "--", "//pkg:t"], {"RUNNER_OS": "Windows"}
                    ) as (_, path):
                        raise SystemExit(0)
        finally:
            if path is not None:
                path.unlink()

    def test_target_file_cleanup_covers_child_launch_error(self) -> None:
        path = None
        with self.assertRaisesRegex(OSError, "fixture launch failure"):
            with run_bazel_with_buildbuddy.windows_target_patterns(
                ["bazel", "build", "--", "//pkg:t"], {"RUNNER_OS": "Windows"}
            ) as (_, path):
                raise OSError("fixture launch failure")
        self.assertFalse(path.exists())

    def github_env(
        self,
        temp_dir: str,
        *,
        repository: str = "openai/codex",
        fork: bool = False,
        event_name: str = "pull_request",
    ) -> dict[str, str]:
        event_path = Path(temp_dir) / "event.json"
        event_path.write_text(
            json.dumps({"pull_request": {"head": {"repo": {"fork": fork}}}}),
            encoding="utf-8",
        )
        return {
            "BUILDBUDDY_API_KEY": "token",
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": event_name,
            "GITHUB_EVENT_PATH": str(event_path),
            "GITHUB_REPOSITORY": repository,
        }

    def test_keyless_invocation_drops_remote_ci_configuration(self) -> None:
        self.assertIsNone(
            run_bazel_with_buildbuddy.remote_config(
                ["build", "--config=ci-linux", "//codex-rs/cli:codex"],
                {},
            )
        )
        self.assertEqual(
            run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                ["build", "--config=ci-linux", "--", "//codex-rs/cli:codex"],
                {},
            ),
            ["build", "--", "//codex-rs/cli:codex"],
        )

    def test_program_arguments_after_separator_do_not_select_or_lose_rbe(self) -> None:
        args = ["run", "//codex-rs/cli:codex", "--", "--config=remote"]

        self.assertEqual(
            run_bazel_with_buildbuddy.bazel_args_with_remote_config(args, {}),
            args,
        )
        self.assertEqual(
            run_bazel_with_buildbuddy.remote_config(
                args, {"BUILDBUDDY_API_KEY": "fork-token"}
            ),
            "buildbuddy-generic",
        )

    def test_upstream_push_selects_openai_rbe_before_target_separator(self) -> None:
        with TemporaryDirectory() as temp_dir:
            env = self.github_env(temp_dir, event_name="push")

            self.assertEqual(
                run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                    ["build", "--config=ci-linux", "--", "//codex-rs/cli:codex"],
                    env,
                ),
                [
                    "build",
                    "--config=buildbuddy-openai-rbe",
                    "--remote_header=x-buildbuddy-api-key=token",
                    "--config=ci-linux",
                    "--",
                    "//codex-rs/cli:codex",
                ],
            )

    def test_windows_cross_ci_configuration_follows_remote_configuration(self) -> None:
        env = {"BUILDBUDDY_API_KEY": "fork-token"}

        self.assertEqual(
            run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                ["build", "--config=ci-windows-cross", "//codex-rs/cli:codex"],
                env,
            ),
            [
                "build",
                "--config=buildbuddy-generic-rbe",
                "--remote_header=x-buildbuddy-api-key=fork-token",
                "--config=ci-windows-cross",
                "//codex-rs/cli:codex",
            ],
        )

    def test_query_remote_configuration_is_inserted_before_expression(self) -> None:
        expression = 'kind("rust_library rule", //codex-rs/...)'
        env = {"BUILDBUDDY_API_KEY": "fork-token"}

        for command in ("query", "cquery", "aquery"):
            with self.subTest(command=command):
                self.assertEqual(
                    run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                        [
                            command,
                            "--config=ci-windows-cross",
                            "--output=label",
                            expression,
                        ],
                        env,
                    ),
                    [
                        command,
                        "--config=buildbuddy-generic-rbe",
                        "--remote_header=x-buildbuddy-api-key=fork-token",
                        "--config=ci-windows-cross",
                        "--output=label",
                        expression,
                    ],
                )

    def test_same_repository_pull_request_selects_openai_host(self) -> None:
        with TemporaryDirectory() as temp_dir:
            self.assertEqual(
                run_bazel_with_buildbuddy.remote_config(
                    ["build", "--config=ci-v8"], self.github_env(temp_dir)
                ),
                "buildbuddy-openai-rbe",
            )

    def test_fork_pull_request_cannot_select_openai_host(self) -> None:
        with TemporaryDirectory() as temp_dir:
            env = self.github_env(temp_dir, fork=True)

            self.assertEqual(
                run_bazel_with_buildbuddy.remote_config(
                    ["build", "--config=ci-v8"], env
                ),
                "buildbuddy-generic-rbe",
            )

    def test_run_in_fork_repository_cannot_select_openai_host(self) -> None:
        with TemporaryDirectory() as temp_dir:
            env = self.github_env(temp_dir, repository="contributor/codex")

            self.assertEqual(
                run_bazel_with_buildbuddy.remote_config(
                    ["build", "--config=ci-v8"], env
                ),
                "buildbuddy-generic-rbe",
            )

    def test_pull_request_without_readable_event_payload_fails_closed(self) -> None:
        for event_path in (None, "missing-event.json"):
            env = {
                "BUILDBUDDY_API_KEY": "token",
                "GITHUB_ACTIONS": "true",
                "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_REPOSITORY": "openai/codex",
            }
            if event_path is not None:
                env["GITHUB_EVENT_PATH"] = event_path

            with self.subTest(event_path=event_path):
                self.assertEqual(
                    run_bazel_with_buildbuddy.remote_config(["build"], env),
                    "buildbuddy-generic",
                )

    def test_bazel_command_uses_configured_binary_locally(self) -> None:
        self.assertEqual(
            run_bazel_with_buildbuddy.bazel_command(
                "info",
                "execution_root",
                env={"CODEX_BAZEL_BIN": "fake-bazel"},
            ),
            ["fake-bazel", "info", "execution_root"],
        )

    def test_bazel_command_normalizes_github_actions_startup_options(self) -> None:
        env = {
            "BAZEL_OUTPUT_USER_ROOT": "/tmp/bazel-output",
            "GITHUB_ACTIONS": "true",
        }

        self.assertEqual(
            run_bazel_with_buildbuddy.bazel_command("build", "//codex-rs/...", env=env),
            [
                "bazel",
                "--output_user_root=/tmp/bazel-output",
                "--noexperimental_remote_repo_contents_cache",
                "build",
                "//codex-rs/...",
            ],
        )
        self.assertEqual(
            run_bazel_with_buildbuddy.bazel_command(
                "--experimental_remote_repo_contents_cache",
                "build",
                "//codex-rs/...",
                env=env,
            ),
            [
                "bazel",
                "--output_user_root=/tmp/bazel-output",
                "--experimental_remote_repo_contents_cache",
                "build",
                "//codex-rs/...",
            ],
        )

    def test_bazel_command_uses_configured_local_caches(self) -> None:
        env = {
            "BAZEL_REPO_CONTENTS_CACHE": "/tmp/bazel-repo-contents",
            "BAZEL_REPOSITORY_CACHE": "/tmp/bazel-repository",
        }

        self.assertEqual(
            run_bazel_with_buildbuddy.bazel_command(
                "build",
                "--config=local",
                "//codex-rs/...",
                env=env,
            ),
            [
                "bazel",
                "build",
                "--config=local",
                "//codex-rs/...",
                "--repo_contents_cache=/tmp/bazel-repo-contents",
                "--repository_cache=/tmp/bazel-repository",
            ],
        )

    def test_bazel_command_adds_local_caches_before_separator(self) -> None:
        self.assertEqual(
            run_bazel_with_buildbuddy.bazel_command(
                "build",
                "//codex-rs/...",
                "--",
                "--program-arg",
                env={"BAZEL_REPOSITORY_CACHE": "/tmp/bazel-repository"},
            ),
            [
                "bazel",
                "build",
                "//codex-rs/...",
                "--repository_cache=/tmp/bazel-repository",
                "--",
                "--program-arg",
            ],
        )

    def test_main_preserves_spaced_argument_and_child_exit_status(self) -> None:
        spaced_arg = (
            r"--test_env=PATH=C:\Program Files\PowerShell\7;C:\Program Files\Git\bin"
        )
        child_code = (
            f"import sys; sys.exit(37 if sys.argv[1] == {spaced_arg!r} else 91)"
        )
        env = os.environ.copy()
        env["CODEX_BAZEL_BIN"] = sys.executable
        env.pop("BAZEL_OUTPUT_USER_ROOT", None)
        env.pop("BUILDBUDDY_API_KEY", None)
        env.pop("GITHUB_ACTIONS", None)

        result = subprocess.run(
            [
                sys.executable,
                str(Path(run_bazel_with_buildbuddy.__file__)),
                "-c",
                child_code,
                spaced_arg,
            ],
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 37, result.stderr)


if __name__ == "__main__":
    unittest.main()
