#!/usr/bin/env python3

import unittest

import run_bazel_with_buildbuddy


class NativeWindowsMsvcToolchainTest(unittest.TestCase):
    def test_keyed_native_msvc_uses_matching_cc_and_preserves_remote_cache(
        self,
    ) -> None:
        args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
            [
                "--output_user_root=C:/bazel-cache",
                "test",
                "--config=ci-windows",
                "--host_platform=//:local_windows_msvc",
                "--platforms=//:windows_x86_64_msvc",
                "--",
                "//fake:target",
            ],
            {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "test-only-token"},
        )

        self.assertEqual(args[:2], ["--output_user_root=C:/bazel-cache", "test"])
        self.assertIn("--config=buildbuddy-generic", args)
        self.assertIn("--remote_header=x-buildbuddy-api-key=test-only-token", args)
        self.assertIn("--extra_toolchains=//:local_windows_msvc_cc_toolchain", args)
        self.assertIn("--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0", args)
        self.assertEqual(args[args.index("--") + 1 :], ["//fake:target"])

    def test_keyed_native_defaults_precede_explicit_compiler_override(self) -> None:
        args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
            [
                "build",
                "--platforms",
                "//:windows_x86_64_msvc",
                "--extra_toolchains=//:explicit-compiler",
                "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=1",
                "//fake:target",
            ],
            {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "test-only-token"},
        )

        self.assertLess(
            args.index("--extra_toolchains=//:local_windows_msvc_cc_toolchain"),
            args.index("--extra_toolchains=//:explicit-compiler"),
        )
        self.assertLess(
            args.index("--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0"),
            args.index("--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=1"),
        )

    def test_keyed_cross_query_and_payload_do_not_select_native_cc(self) -> None:
        cases = [
            ["build", "--config=ci-windows-cross", "//fake:target"],
            ["query", "--platforms=//:windows_x86_64_msvc", "//fake:target"],
            ["run", "//fake:target", "--", "--platforms=//:windows_x86_64_msvc"],
        ]
        for original in cases:
            with self.subTest(original=original):
                args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                    original,
                    {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "test-only-token"},
                )
                self.assertNotIn(
                    "--extra_toolchains=//:local_windows_msvc_cc_toolchain", args
                )
                if "--config=ci-windows-cross" in original:
                    self.assertIn("--config=buildbuddy-generic-rbe", args)

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


if __name__ == "__main__":
    unittest.main()
