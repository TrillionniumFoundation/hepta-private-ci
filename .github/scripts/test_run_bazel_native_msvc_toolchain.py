#!/usr/bin/env python3

import unittest

import run_bazel_with_buildbuddy


class NativeWindowsMsvcToolchainTest(unittest.TestCase):
    def test_cache_only_native_msvc_registers_matching_cc_for_both_hosts(self) -> None:
        original = [
            "test",
            "--config=ci-windows",
            "--host_platform=//:local_windows_msvc",
            "--platforms=//:windows_x86_64_msvc",
            "--",
            "//fake:target",
        ]
        for trusted_upstream in (False, True):
            env = {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "test-token"}
            host = "generic"
            if trusted_upstream:
                env.update(
                    GITHUB_ACTIONS="true",
                    GITHUB_REPOSITORY="openai/codex",
                    GITHUB_EVENT_NAME="push",
                )
                host = "openai"
            with self.subTest(host=host):
                args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                    original, env
                )
                self.assertEqual(
                    args,
                    [
                        "test",
                        f"--config=buildbuddy-{host}",
                        "--remote_header=x-buildbuddy-api-key=test-token",
                        "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                        "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                        *original[1:],
                    ],
                )

    def test_cache_only_native_msvc_preserves_explicit_compiler_precedence(
        self,
    ) -> None:
        env = {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "test-token"}
        explicit = [
            "build",
            "--platforms",
            "//:windows_x86_64_msvc",
            "--extra_toolchains=//custom:compiler",
            "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=1",
        ]
        args = run_bazel_with_buildbuddy.bazel_args_with_remote_config(explicit, env)
        self.assertEqual(args[-4:], explicit[-4:])
        self.assertLess(
            args.index("--extra_toolchains=//:local_windows_msvc_cc_toolchain"),
            args.index("--extra_toolchains=//custom:compiler"),
        )
        self.assertLess(
            args.index("--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0"),
            args.index("--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=1"),
        )
        matching = [
            "build",
            "--platforms=//:windows_x86_64_msvc",
            "--extra_toolchains",
            "//custom:compiler,//:local_windows_msvc_cc_toolchain",
            "--repo_env",
            "BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
        ]
        actual = run_bazel_with_buildbuddy.bazel_args_with_remote_config(matching, env)
        self.assertEqual(
            actual,
            [
                "build",
                "--config=buildbuddy-generic",
                "--remote_header=x-buildbuddy-api-key=test-token",
                *matching[1:],
            ],
        )

    def test_cache_credentials_do_not_change_unrelated_action_compilers(self) -> None:
        for runner, original in [
            ("Linux", ["build", "--platforms=//:windows_x86_64_msvc"]),
            ("Windows", ["query", "--platforms=//:windows_x86_64_msvc"]),
            ("Windows", ["run", "--", "--platforms=//:windows_x86_64_msvc"]),
            ("Windows", ["build", "--platforms=//:windows_x86_64_gnullvm"]),
        ]:
            with self.subTest(runner=runner, original=original):
                actual = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                    original,
                    {"RUNNER_OS": runner, "BUILDBUDDY_API_KEY": "test-token"},
                )
                self.assertEqual(
                    actual,
                    [
                        original[0],
                        "--config=buildbuddy-generic",
                        "--remote_header=x-buildbuddy-api-key=test-token",
                        *original[1:],
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
