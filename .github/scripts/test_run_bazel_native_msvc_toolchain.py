#!/usr/bin/env python3

import unittest

import run_bazel_with_buildbuddy


class NativeWindowsMsvcToolchainTest(unittest.TestCase):
    def test_authenticated_native_msvc_uses_local_abi_with_remote_cache(self) -> None:
        for remote_name, repository in (
            ("buildbuddy-generic", "TrillionniumFoundation/hepta-private-ci"),
            ("buildbuddy-openai", "openai/codex"),
        ):
            for command in (
                "build",
                "test",
                "run",
                "coverage",
                "cquery",
                "aquery",
                "info",
            ):
                with self.subTest(remote_name=remote_name, command=command):
                    args = [
                        command,
                        "--config=ci-windows",
                        "--host_platform=//:local_windows_msvc",
                        "--platforms=//:windows_x86_64_msvc",
                        "--",
                        "//fake:target",
                    ]
                    original_args = args.copy()
                    result = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                        args,
                        {
                            "RUNNER_OS": "Windows",
                            "GITHUB_ACTIONS": "true",
                            "GITHUB_REPOSITORY": repository,
                            "GITHUB_EVENT_NAME": "push",
                            "BUILDBUDDY_API_KEY": "test-token",
                        },
                    )
                    self.assertEqual(
                        result,
                        [
                            command,
                            f"--config={remote_name}",
                            "--remote_header=x-buildbuddy-api-key=test-token",
                            "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                            "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                            *original_args[1:],
                        ],
                    )
                    self.assertEqual(args, original_args)

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
