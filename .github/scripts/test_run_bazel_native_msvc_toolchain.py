#!/usr/bin/env python3

import unittest

import run_bazel_with_buildbuddy


class NativeWindowsMsvcToolchainTest(unittest.TestCase):
    def test_authenticated_native_msvc_keeps_cache_and_matching_compiler(self) -> None:
        for command in ("build", "test", "cquery", "aquery"):
            with self.subTest(command=command):
                self.assertEqual(
                    run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                        [
                            command,
                            "--config=ci-windows",
                            "--host_platform=//:local_windows_msvc",
                            "--platforms=//:windows_x86_64_msvc",
                            "--",
                            "//fake:target",
                        ],
                        {
                            "RUNNER_OS": "Windows",
                            "BUILDBUDDY_API_KEY": "test-only-token",
                        },
                    ),
                    [
                        command,
                        "--config=buildbuddy-generic",
                        "--remote_header=x-buildbuddy-api-key=test-only-token",
                        "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                        "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                        "--config=ci-windows",
                        "--host_platform=//:local_windows_msvc",
                        "--platforms=//:windows_x86_64_msvc",
                        "--",
                        "//fake:target",
                    ],
                )

    def test_authenticated_native_msvc_keeps_explicit_compiler_precedence(self) -> None:
        args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
            [
                "run",
                "--config=ci-windows",
                "--platforms",
                "//:windows_x86_64_msvc",
                "--extra_toolchains=//:caller-msvc-compiler",
                "//fake:target",
                "--",
                "--config=ci-windows-cross",
                "--platforms=//:windows_x86_64_gnullvm",
            ],
            {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "test-only-token"},
        )
        self.assertLess(
            args.index("--extra_toolchains=//:local_windows_msvc_cc_toolchain"),
            args.index("--extra_toolchains=//:caller-msvc-compiler"),
        )
        self.assertEqual(
            args[args.index("--") + 1 :],
            ["--config=ci-windows-cross", "--platforms=//:windows_x86_64_gnullvm"],
        )
        self.assertIn("--config=buildbuddy-generic", args)
        self.assertNotIn("--config=buildbuddy-generic-rbe", args)

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
