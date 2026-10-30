#!/usr/bin/env python3

import unittest

import run_bazel_with_buildbuddy


class NativeWindowsMsvcToolchainTest(unittest.TestCase):
    def test_keyed_native_msvc_preserves_cache_and_selects_matching_cc_toolchain(
        self,
    ) -> None:
        args = [
            "build",
            "--config=ci-windows",
            "--host_platform=//:local_windows_msvc",
            "--platforms=//:windows_x86_64_msvc",
            "--",
            "//fake:target",
        ]

        self.assertEqual(
            run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                args,
                {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "fork-token"},
            ),
            [
                "build",
                "--config=buildbuddy-generic",
                "--remote_header=x-buildbuddy-api-key=fork-token",
                "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                *args[1:],
            ],
        )

    def test_native_msvc_keeps_target_and_injects_matching_cc_toolchain(self) -> None:
        args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
            [
                "build",
                "--config=ci-windows",
                "--host_platform=//:local_windows_msvc",
                "--platforms=//:windows_x86_64_msvc",
                "--",
                "//fake:target",
            ],
            {"RUNNER_OS": "Windows"},
        )

        self.assertIn("--extra_toolchains=//:local_windows_msvc_cc_toolchain", args)
        self.assertIn("--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0", args)
        self.assertIn("--platforms=//:windows_x86_64_msvc", args)
        self.assertNotIn("--platforms=//:windows_x86_64_gnullvm", args)
        self.assertNotIn("--config=ci-windows-cross", args)
        self.assertEqual(args[args.index("--") + 1 :], ["//fake:target"])

    def test_native_msvc_does_not_duplicate_explicit_toolchain_flags(self) -> None:
        for key in ("", "fork-token"):
            with self.subTest(keyed=bool(key)):
                args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                    [
                        "build",
                        "--host_platform=//:local_windows_msvc",
                        "--platforms=//:windows_x86_64_msvc",
                        "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                        "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                        "//fake:target",
                    ],
                    {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": key},
                )

                self.assertEqual(
                    args.count("--extra_toolchains=//:local_windows_msvc_cc_toolchain"),
                    1,
                )
                self.assertEqual(
                    args.count("--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0"), 1
                )

    def test_trusted_upstream_native_msvc_keeps_its_authenticated_host(self) -> None:
        args = ["test", "--platforms=//:windows_x86_64_msvc", "//fake:target"]
        self.assertEqual(
            run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                args,
                {
                    "RUNNER_OS": "Windows",
                    "BUILDBUDDY_API_KEY": "upstream-token",
                    "GITHUB_ACTIONS": "true",
                    "GITHUB_REPOSITORY": "openai/codex",
                    "GITHUB_EVENT_NAME": "push",
                },
            ),
            [
                "test",
                "--config=buildbuddy-openai",
                "--remote_header=x-buildbuddy-api-key=upstream-token",
                "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                *args[1:],
            ],
        )

    def test_keyed_native_defaults_preserve_caller_precedence_and_payload(self) -> None:
        args = [
            "--output_user_root=build root",
            "run",
            "--platforms",
            "//:windows_x86_64_msvc",
            "--extra_toolchains",
            "//:caller-compiler",
            "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=1",
            "--repo_contents_cache=caller cache",
            "//fake:tool",
            "--",
            "--config=remote",
            "--remote_executor=payload",
            "payload value",
        ]
        self.assertEqual(
            run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                args,
                {
                    "RUNNER_OS": "Windows",
                    "BUILDBUDDY_API_KEY": "fork-token",
                    "BAZEL_REPO_CONTENTS_CACHE": "environment cache",
                },
            ),
            [
                *args[:2],
                "--config=buildbuddy-generic",
                "--remote_header=x-buildbuddy-api-key=fork-token",
                "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                *args[2:],
            ],
        )

    def test_keyed_remote_and_cross_requests_do_not_gain_local_compiler(self) -> None:
        cases = [
            (["--config=ci-windows-cross"], "buildbuddy-generic-rbe"),
            (["--config=ci-linux"], "buildbuddy-generic-rbe"),
            (["--config=ci-macos"], "buildbuddy-generic-rbe"),
            (["--config", "ci-windows-cross"], "buildbuddy-generic"),
            (["--config", "ci-linux"], "buildbuddy-generic"),
            (["--config", "ci-macos"], "buildbuddy-generic"),
            (["--config", "ci-v8"], "buildbuddy-generic"),
            (["--config=remote"], "buildbuddy-generic"),
            (["--config", "remote"], "buildbuddy-generic"),
            (["--config=buildbuddy-generic-rbe"], "buildbuddy-generic"),
            (["--config=buildbuddy-openai-rbe"], "buildbuddy-generic"),
            (["--remote_executor=grpcs://example.invalid"], "buildbuddy-generic"),
            (["--remote_executor", "grpcs://example.invalid"], "buildbuddy-generic"),
            (
                ["--remote_executor=", "--remote_executor=grpcs://example.invalid"],
                "buildbuddy-generic",
            ),
            (
                [
                    "--remote_executor",
                    "",
                    "--remote_executor",
                    "grpcs://example.invalid",
                ],
                "buildbuddy-generic",
            ),
        ]
        for remote_options, selected_config in cases:
            with self.subTest(remote_options=remote_options):
                args = [
                    "build",
                    *remote_options,
                    "--platforms=//:windows_x86_64_msvc",
                    "//fake:target",
                ]
                self.assertEqual(
                    run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                        args,
                        {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "fork-token"},
                    ),
                    [
                        "build",
                        f"--config={selected_config}",
                        "--remote_header=x-buildbuddy-api-key=fork-token",
                        *args[1:],
                    ],
                )

    def test_keyed_empty_remote_executor_keeps_native_compiler_selection(self) -> None:
        for executor_args in (
            ["--remote_executor="],
            ["--remote_executor", ""],
            ["--remote_executor=grpcs://example.invalid", "--remote_executor="],
            ["--remote_executor", "grpcs://example.invalid", "--remote_executor", ""],
        ):
            with self.subTest(executor_args=executor_args):
                args = [
                    "build",
                    "--platforms=//:windows_x86_64_msvc",
                    *executor_args,
                    "//fake:target",
                ]
                self.assertEqual(
                    run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                        args,
                        {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "fork-token"},
                    ),
                    [
                        "build",
                        "--config=buildbuddy-generic",
                        "--remote_header=x-buildbuddy-api-key=fork-token",
                        "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                        "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                        *args[1:],
                    ],
                )

    def test_other_runners_do_not_gain_native_windows_compiler(self) -> None:
        args = ["build", "--platforms=//:windows_x86_64_msvc", "//fake:target"]
        for runner_os in ("Linux", "macOS"):
            for key in ("", "fork-token"):
                with self.subTest(runner_os=runner_os, keyed=bool(key)):
                    remote_args = (
                        [
                            "--config=buildbuddy-generic",
                            "--remote_header=x-buildbuddy-api-key=fork-token",
                        ]
                        if key
                        else []
                    )
                    self.assertEqual(
                        run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                            args, {"RUNNER_OS": runner_os, "BUILDBUDDY_API_KEY": key}
                        ),
                        ["build", *remote_args, *args[1:]],
                    )

    def test_keyed_non_build_commands_and_payload_do_not_select_msvc(self) -> None:
        cases = [
            ["query", "--platforms=//:windows_x86_64_msvc", "//fake:target"],
            ["help", "--platforms=//:windows_x86_64_msvc"],
            ["run", "//fake:tool", "--", "--platforms=//:windows_x86_64_msvc"],
            ["build", "--platforms=//:windows_x86_64_gnullvm", "//fake:target"],
        ]
        for args in cases:
            with self.subTest(args=args):
                self.assertEqual(
                    run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                        args,
                        {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "fork-token"},
                    ),
                    [
                        args[0],
                        "--config=buildbuddy-generic",
                        "--remote_header=x-buildbuddy-api-key=fork-token",
                        *args[1:],
                    ],
                )


if __name__ == "__main__":
    unittest.main()
