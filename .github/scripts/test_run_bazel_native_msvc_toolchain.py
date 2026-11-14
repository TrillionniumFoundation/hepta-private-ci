#!/usr/bin/env python3

import unittest

import run_bazel_with_buildbuddy


class NativeWindowsMsvcToolchainTest(unittest.TestCase):
    def test_authenticated_native_msvc_cache_keeps_matching_local_compiler(
        self,
    ) -> None:
        for repository, config in (
            ("contributor/codex", "buildbuddy-generic"),
            ("openai/codex", "buildbuddy-openai"),
        ):
            with self.subTest(repository=repository):
                args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                    [
                        "test",
                        "--config=ci-windows",
                        "--host_platform=//:local_windows_msvc",
                        "--platforms=//:windows_x86_64_msvc",
                        "--",
                        "//fake:target",
                    ],
                    {
                        "RUNNER_OS": "Windows",
                        "BUILDBUDDY_API_KEY": "test-token",
                        "GITHUB_ACTIONS": "true",
                        "GITHUB_REPOSITORY": repository,
                        "GITHUB_EVENT_NAME": "push",
                    },
                )

                options = args[: args.index("--")]
                self.assertIn(f"--config={config}", options)
                self.assertIn(
                    "--remote_header=x-buildbuddy-api-key=test-token", options
                )
                self.assertIn(
                    "--extra_toolchains=//:local_windows_msvc_cc_toolchain", options
                )
                self.assertIn("--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0", options)
                self.assertIn("--platforms=//:windows_x86_64_msvc", options)
                self.assertNotIn(f"--config={config}-rbe", options)
                self.assertNotIn("--platforms=//:windows_x86_64_gnullvm", options)
                self.assertEqual(args[args.index("--") + 1 :], ["//fake:target"])

    def test_authenticated_cross_keeps_remote_execution_toolchain_selection(
        self,
    ) -> None:
        args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
            [
                "build",
                "--config=ci-windows-cross",
                "--host_platform=//:rbe",
                "--platforms=//:windows_x86_64_gnullvm",
                "--",
                "//fake:target",
            ],
            {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "test-token"},
        )

        self.assertIn("--config=buildbuddy-generic-rbe", args)
        self.assertIn("--config=ci-windows-cross", args)
        self.assertIn("--host_platform=//:rbe", args)
        self.assertIn("--platforms=//:windows_x86_64_gnullvm", args)
        self.assertNotIn("--extra_toolchains=//:local_windows_msvc_cc_toolchain", args)
        self.assertNotIn("--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0", args)

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
