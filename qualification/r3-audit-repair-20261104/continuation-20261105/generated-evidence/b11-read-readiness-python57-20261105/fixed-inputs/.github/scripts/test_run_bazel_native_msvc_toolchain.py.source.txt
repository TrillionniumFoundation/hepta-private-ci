#!/usr/bin/env python3

import unittest

import run_bazel_with_buildbuddy


class NativeWindowsMsvcToolchainTest(unittest.TestCase):
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
        args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
            [
                "build",
                "--host_platform=//:local_windows_msvc",
                "--platforms=//:windows_x86_64_msvc",
                "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                "//fake:target",
            ],
            {"RUNNER_OS": "Windows"},
        )

        self.assertEqual(
            args.count("--extra_toolchains=//:local_windows_msvc_cc_toolchain"), 1
        )
        self.assertEqual(
            args.count("--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0"), 1
        )

    def test_cache_only_native_msvc_keeps_abi_and_remote_cache(self) -> None:
        for command in ("build", "test", "aquery", "cquery", "info"):
            with self.subTest(command=command):
                args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                    [
                        "--output_user_root=build root",
                        command,
                        "--config=ci-windows",
                        "--host_platform=//:local_windows_msvc",
                        "--platforms",
                        "//:windows_x86_64_msvc",
                        "--",
                        "//fake:target",
                    ],
                    {
                        "RUNNER_OS": "Windows",
                        "BUILDBUDDY_API_KEY": "test-key",
                        "BAZEL_REPOSITORY_CACHE": "download cache",
                    },
                )
                self.assertIn(
                    "--extra_toolchains=//:local_windows_msvc_cc_toolchain", args
                )
                self.assertIn("--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0", args)
                self.assertIn("--config=buildbuddy-generic", args)
                self.assertIn("--remote_header=x-buildbuddy-api-key=test-key", args)
                self.assertNotIn("--config=buildbuddy-generic-rbe", args)
                self.assertEqual(args[0], "--output_user_root=build root")
                self.assertEqual(
                    args[args.index("--platforms") + 1], "//:windows_x86_64_msvc"
                )
                self.assertIn(
                    "--repository_cache=download cache", args[: args.index("--")]
                )
                self.assertEqual(args[args.index("--") + 1 :], ["//fake:target"])

    def test_authenticated_rbe_keeps_remote_compiler_selection(self) -> None:
        for runner, ci_config in (
            ("Windows", "ci-windows-cross"),
            ("Linux", "ci-linux"),
            ("macOS", "ci-macos"),
        ):
            with self.subTest(runner=runner):
                args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                    ["build", f"--config={ci_config}", "--", "//fake:target"],
                    {"RUNNER_OS": runner, "BUILDBUDDY_API_KEY": "test-key"},
                )
                self.assertEqual(
                    args,
                    [
                        "build",
                        "--config=buildbuddy-generic-rbe",
                        "--remote_header=x-buildbuddy-api-key=test-key",
                        f"--config={ci_config}",
                        "--",
                        "//fake:target",
                    ],
                )

    def test_non_windows_cache_only_keeps_native_arguments(self) -> None:
        for runner in ("Linux", "macOS"):
            with self.subTest(runner=runner):
                args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                    ["build", "--config=clippy", "--", "//fake:target"],
                    {"RUNNER_OS": runner, "BUILDBUDDY_API_KEY": "test-key"},
                )
                self.assertEqual(
                    args,
                    [
                        "build",
                        "--config=buildbuddy-generic",
                        "--remote_header=x-buildbuddy-api-key=test-key",
                        "--config=clippy",
                        "--",
                        "//fake:target",
                    ],
                )


if __name__ == "__main__":
    unittest.main()
