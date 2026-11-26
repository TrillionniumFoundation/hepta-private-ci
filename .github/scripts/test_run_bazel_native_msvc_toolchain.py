#!/usr/bin/env python3

import unittest

import run_bazel_with_buildbuddy


class NativeWindowsMsvcToolchainTest(unittest.TestCase):
    def test_native_msvc_keeps_target_and_injects_matching_cc_toolchain(self) -> None:
        for auth_env, remote_args in (
            ({}, []),
            (
                {"BUILDBUDDY_API_KEY": "test-key"},
                [
                    "--config=buildbuddy-generic",
                    "--remote_header=x-buildbuddy-api-key=test-key",
                ],
            ),
            (
                {
                    "BUILDBUDDY_API_KEY": "test-key",
                    "GITHUB_ACTIONS": "true",
                    "GITHUB_REPOSITORY": "openai/codex",
                    "GITHUB_EVENT_NAME": "push",
                },
                [
                    "--config=buildbuddy-openai",
                    "--remote_header=x-buildbuddy-api-key=test-key",
                ],
            ),
        ):
            for command in ("build", "test"):
                with self.subTest(auth_env=auth_env, command=command):
                    args = [
                        command,
                        "--config=ci-windows",
                        "--host_platform=//:local_windows_msvc",
                        "--platforms=//:windows_x86_64_msvc",
                        "--",
                        "//fake:target",
                    ]
                    self.assertEqual(
                        run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                            args, {"RUNNER_OS": "Windows", **auth_env}
                        ),
                        [
                            command,
                            *remote_args,
                            "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                            "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                            *args[1:],
                        ],
                    )

    def test_native_msvc_does_not_duplicate_explicit_toolchain_flags(self) -> None:
        support = [
            "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
            "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
        ]
        for auth_env, remote_args in (
            ({}, []),
            (
                {"BUILDBUDDY_API_KEY": "test-key"},
                [
                    "--config=buildbuddy-generic",
                    "--remote_header=x-buildbuddy-api-key=test-key",
                ],
            ),
        ):
            with self.subTest(auth_env=auth_env):
                args = [
                    "build",
                    "--config=ci-windows",
                    "--host_platform=//:local_windows_msvc",
                    "--platforms=//:windows_x86_64_msvc",
                    *support,
                    "//fake:target",
                ]
                self.assertEqual(
                    run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                        args, {"RUNNER_OS": "Windows", **auth_env}
                    ),
                    ["build", *remote_args, *args[1:]],
                )

    def test_keyed_native_msvc_defaults_preserve_later_caller_overrides(self) -> None:
        args = [
            "--output_user_root=build root",
            "build",
            "--config=ci-windows",
            "--host_platform=//:local_windows_msvc",
            "--platforms",
            "//:windows_x86_64_msvc",
            "--extra_toolchains=//:custom-msvc-compiler",
            "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=1",
            "--repository_cache=caller cache",
            "--",
            "//fake:target",
        ]
        self.assertEqual(
            run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                args, {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "test-key"}
            ),
            [
                args[0],
                "build",
                "--config=buildbuddy-generic",
                "--remote_header=x-buildbuddy-api-key=test-key",
                "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                *args[2:],
            ],
        )

    def test_keyed_rbe_keeps_its_execution_configuration(self) -> None:
        for config in ("ci-linux", "ci-macos", "ci-v8", "ci-windows-cross"):
            with self.subTest(config=config):
                args = [
                    "build",
                    f"--config={config}",
                    "--platforms=//:windows_x86_64_msvc",
                    "--",
                    "//fake:target",
                ]
                self.assertEqual(
                    run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                        args,
                        {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "test-key"},
                    ),
                    [
                        "build",
                        "--config=buildbuddy-generic-rbe",
                        "--remote_header=x-buildbuddy-api-key=test-key",
                        *args[1:],
                    ],
                )

    def test_keyed_msvc_fallback_respects_runner_command_and_separator(self) -> None:
        for runner_os, args in (
            ("Linux", ["build", "--platforms=//:windows_x86_64_msvc", "//fake:target"]),
            (
                "Windows",
                ["query", "--platforms=//:windows_x86_64_msvc", "//fake:target"],
            ),
            (
                "Windows",
                [
                    "run",
                    "--config=ci-windows",
                    "//fake:tool",
                    "--",
                    "--platforms=//:windows_x86_64_msvc",
                ],
            ),
        ):
            with self.subTest(runner_os=runner_os, args=args):
                self.assertEqual(
                    run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                        args,
                        {"RUNNER_OS": runner_os, "BUILDBUDDY_API_KEY": "test-key"},
                    ),
                    [
                        args[0],
                        "--config=buildbuddy-generic",
                        "--remote_header=x-buildbuddy-api-key=test-key",
                        *args[1:],
                    ],
                )


if __name__ == "__main__":
    unittest.main()
