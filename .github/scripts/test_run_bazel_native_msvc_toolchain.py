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

    def test_cached_native_msvc_preserves_cache_and_matching_native_abi(self) -> None:
        requested = [
            "--output_user_root=build root",
            "test",
            "--config=ci-windows",
            "--host_platform=//:local_windows_msvc",
            "--platforms",
            "//:windows_x86_64_msvc",
            "--",
            "//fake:target with spaces",
        ]
        actual = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
            requested,
            {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "test-placeholder"},
        )
        self.assertEqual(
            actual,
            [
                requested[0],
                "test",
                "--config=buildbuddy-generic",
                "--remote_header=x-buildbuddy-api-key=test-placeholder",
                "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
                "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
                *requested[2:],
            ],
        )

    def test_cached_native_abi_does_not_leak_into_rbe_or_target_payload(self) -> None:
        requests = [
            [
                "build",
                "--config=ci-windows-cross",
                "--platforms=//:windows_x86_64_msvc",
                "--",
                "//fake:target",
            ],
            ["run", "//fake:tool", "--", "--platforms=//:windows_x86_64_msvc"],
        ]
        for requested in requests:
            with self.subTest(requested=requested):
                actual = run_bazel_with_buildbuddy.bazel_args_with_remote_config(
                    requested,
                    {"RUNNER_OS": "Windows", "BUILDBUDDY_API_KEY": "test-placeholder"},
                )
                config = (
                    "--config=buildbuddy-generic-rbe"
                    if "--config=ci-windows-cross" in requested
                    else "--config=buildbuddy-generic"
                )
                self.assertEqual(
                    actual,
                    [
                        requested[0],
                        config,
                        "--remote_header=x-buildbuddy-api-key=test-placeholder",
                        *requested[1:],
                    ],
                )


if __name__ == "__main__":
    unittest.main()
