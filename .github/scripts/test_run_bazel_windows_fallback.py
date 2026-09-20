#!/usr/bin/env python3

import unittest
from pathlib import Path

import run_bazel_with_buildbuddy as wrapper


class WindowsLocalFallbackTest(unittest.TestCase):
    def test_keyless_windows_invocation_selects_local_ci_config(self) -> None:
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(
                ["build", "--", "//codex-rs/cli:codex"], {"RUNNER_OS": "Windows"}
            ),
            ["build", "--config=ci-windows", "--", "//codex-rs/cli:codex"],
        )

    def test_keyless_cross_fallback_splits_msvc_exec_from_gnullvm_target(self) -> None:
        for command in ("build", "test", "cquery", "aquery", "info"):
            with self.subTest(command=command):
                self.assertEqual(
                    wrapper.bazel_args_with_remote_config(
                        [command, "--config=ci-windows-cross", "--", "target"],
                        {"RUNNER_OS": "Windows"},
                    ),
                    [
                        command,
                        "--config=ci-windows",
                        "--host_platform=//:local_windows_msvc",
                        "--platforms=//:windows_x86_64_gnullvm",
                        "--extra_execution_platforms=//:windows_x86_64_msvc",
                        "--extra_toolchains=//:windows_gnullvm_tests_on_msvc_host_toolchain",
                        "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                        "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                        "--",
                        "target",
                    ],
                )

    def test_repository_declares_the_required_split_abi_contract(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        build = (repository_root / "BUILD.bazel").read_text(encoding="utf-8")
        module = (repository_root / "MODULE.bazel").read_text(encoding="utf-8")

        self.assertIn('name = "local_windows_msvc"', build)
        self.assertIn('@llvm//constraints/windows/abi:msvc', build)
        self.assertIn('name = "windows_x86_64_gnullvm"', build)
        self.assertIn('@llvm//constraints/windows/abi:gnullvm', build)
        self.assertIn(
            'name = "windows_gnullvm_tests_on_msvc_host_toolchain"', build
        )
        self.assertIn(
            'toolchain_type = "@bazel_tools//tools/test:default_test_toolchain_type"',
            build,
        )
        self.assertIn('exec_triple = "x86_64-pc-windows-msvc"', module)
        self.assertIn('target_triple = "x86_64-pc-windows-gnullvm"', module)

    def test_clippy_does_not_hide_required_local_platform_config(self) -> None:
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(
                ["build", "--config=clippy", "--config=ci-windows-cross", "//..."],
                {"RUNNER_OS": "Windows"},
            ),
            [
                "build",
                "--config=ci-windows",
                "--host_platform=//:local_windows_msvc",
                "--platforms=//:windows_x86_64_gnullvm",
                "--extra_execution_platforms=//:windows_x86_64_msvc",
                "--extra_toolchains=//:windows_gnullvm_tests_on_msvc_host_toolchain",
                "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                "--config=clippy",
                "//...",
            ],
        )

    def test_defaults_precede_explicit_caches_and_preserve_startup_options(self) -> None:
        args = [
            "--output_user_root=build root",
            "build",
            "--config=ci-windows-cross",
            "--repo_contents_cache=job cache",
            "--repository_cache=download cache",
            "--",
            "//...",
        ]
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(args, {"RUNNER_OS": "Windows"}),
            [
                args[0],
                "build",
                "--config=ci-windows",
                "--host_platform=//:local_windows_msvc",
                "--platforms=//:windows_x86_64_gnullvm",
                "--extra_execution_platforms=//:windows_x86_64_msvc",
                "--extra_toolchains=//:windows_gnullvm_tests_on_msvc_host_toolchain",
                "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                *args[3:],
            ],
        )

    def test_explicit_host_and_target_platforms_are_preserved(self) -> None:
        for platforms in (
            ["--host_platform=//:custom-host", "--platforms=//:custom-target"],
            ["--host_platform", "//:custom-host", "--platforms", "//:custom-target"],
        ):
            with self.subTest(platforms=platforms):
                self.assertEqual(
                    wrapper.bazel_args_with_remote_config(
                        ["build", "--config=ci-windows-cross", *platforms, "//..."],
                        {"RUNNER_OS": "Windows"},
                    ),
                    [
                        "build",
                        "--config=ci-windows",
                        "--extra_execution_platforms=//:windows_x86_64_msvc",
                        "--extra_toolchains=//:windows_gnullvm_tests_on_msvc_host_toolchain",
                        "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                        "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                        *platforms,
                        "//...",
                    ],
                )

    def test_explicit_local_split_support_is_not_duplicated(self) -> None:
        support = [
            "--extra_execution_platforms=//:custom,//:windows_x86_64_msvc",
            "--extra_toolchains=//:windows_gnullvm_tests_on_msvc_host_toolchain",
            "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
            "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
        ]
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(
                ["test", "--config=ci-windows-cross", *support, "//..."],
                {"RUNNER_OS": "Windows"},
            ),
            [
                "test",
                "--config=ci-windows",
                "--host_platform=//:local_windows_msvc",
                "--platforms=//:windows_x86_64_gnullvm",
                *support,
                "//...",
            ],
        )

    def test_explicit_compiler_and_detection_setting_take_precedence(self) -> None:
        for options in (
            [
                "--extra_toolchains=//:custom-msvc-compiler",
                "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=1",
            ],
            [
                "--extra_toolchains",
                "//:custom-msvc-compiler",
                "--repo_env",
                "BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=1",
            ],
        ):
            with self.subTest(options=options):
                self.assertEqual(
                    wrapper.bazel_args_with_remote_config(
                        ["build", "--config=ci-windows-cross", *options, "//..."],
                        {"RUNNER_OS": "Windows"},
                    ),
                    [
                        "build",
                        "--config=ci-windows",
                        "--host_platform=//:local_windows_msvc",
                        "--platforms=//:windows_x86_64_gnullvm",
                        "--extra_execution_platforms=//:windows_x86_64_msvc",
                        "--extra_toolchains=//:windows_gnullvm_tests_on_msvc_host_toolchain",
                        "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                        "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                        *options,
                        "//...",
                    ],
                )

    def test_explicit_msvc_host_is_not_silently_reinterpreted(self) -> None:
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(
                ["build", "--host_platform=//:local_windows_msvc", "//..."],
                {"RUNNER_OS": "Windows"},
            ),
            [
                "build",
                "--config=ci-windows",
                "--host_platform=//:local_windows_msvc",
                "//...",
            ],
        )

    def test_existing_local_config_is_not_duplicated(self) -> None:
        args = ["build", "--config=ci-windows", "--config=ci-windows-cross", "//..."]
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(args, {"RUNNER_OS": "Windows"}),
            [
                "build",
                "--host_platform=//:local_windows_msvc",
                "--platforms=//:windows_x86_64_gnullvm",
                "--extra_execution_platforms=//:windows_x86_64_msvc",
                "--extra_toolchains=//:windows_gnullvm_tests_on_msvc_host_toolchain",
                "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                "--config=ci-windows",
                "//...",
            ],
        )

    def test_target_discovery_does_not_inject_build_configuration(self) -> None:
        args = ["query", "--output=label", 'kind("rust_test rule", //codex-rs/...)']
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(args, {"RUNNER_OS": "Windows"}),
            args,
        )

    def test_non_build_commands_do_not_gain_ci_flags(self) -> None:
        for command in ("query", "version", "help", "shutdown", "clean"):
            with self.subTest(command=command):
                self.assertEqual(
                    wrapper.bazel_args_with_remote_config(
                        [command], {"RUNNER_OS": "Windows"}
                    ),
                    [command],
                )

    def test_arguments_after_separator_are_neither_interpreted_nor_removed(self) -> None:
        payload = [
            "--config=ci-windows-cross",
            "--platforms=//:payload",
            "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
            "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
            "spaced value",
        ]
        args = ["run", "--config=ci-windows-cross", "//:tool", "--", *payload]
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(args, {"RUNNER_OS": "Windows"}),
            [
                "run",
                "--config=ci-windows",
                "--host_platform=//:local_windows_msvc",
                "--platforms=//:windows_x86_64_gnullvm",
                "--extra_execution_platforms=//:windows_x86_64_msvc",
                "--extra_toolchains=//:windows_gnullvm_tests_on_msvc_host_toolchain",
                "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                "//:tool",
                "--",
                *payload,
            ],
        )

    def test_non_windows_local_invocation_stays_native(self) -> None:
        args = ["build", "--config=ci-linux", "--", "//..."]
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(args, {"RUNNER_OS": "Linux"}),
            ["build", "--", "//..."],
        )

    def test_non_windows_cross_request_does_not_enable_local_msvc(self) -> None:
        args = ["build", "--config=ci-windows-cross", "--", "//..."]
        for runner_os in ("Linux", "macOS"):
            with self.subTest(runner_os=runner_os):
                self.assertEqual(
                    wrapper.bazel_args_with_remote_config(args, {"RUNNER_OS": runner_os}),
                    ["build", "--", "//..."],
                )

    def test_authenticated_cross_request_remains_rbe(self) -> None:
        args = ["build", "--config=ci-windows-cross", "//codex-rs/cli:codex"]
        self.assertEqual(
            wrapper.bazel_args_with_remote_config(
                args, {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "fork-token"}
            ),
            [
                "build",
                "--config=buildbuddy-generic-rbe",
                "--remote_header=x-buildbuddy-api-key=fork-token",
                "--config=ci-windows-cross",
                "//codex-rs/cli:codex",
            ],
        )


if __name__ == "__main__":
    unittest.main()
