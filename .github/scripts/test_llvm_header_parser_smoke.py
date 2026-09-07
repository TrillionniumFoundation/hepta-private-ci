#!/usr/bin/env python3

from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import llvm_header_parser_smoke as smoke


class HeaderParserBuildTest(unittest.TestCase):
    def test_build_query_and_info_use_the_same_native_msvc_configuration(self) -> None:
        env = {
            "RUNNER_OS": "Windows",
            "BUILDBUDDY_API_KEY": "main-build-token",
            "CODEX_BAZEL_BIN": "fake-bazel",
            "BAZEL_OUTPUT_USER_ROOT": "D:/output root",
            "BAZEL_REPO_CONTENTS_CACHE": "D:/repo cache",
        }
        original = env.copy()
        executable = "bazel-out/msvc/bin/external/llvm+/header-parser.exe"
        outputs = [
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0, stdout=f"{executable}\n"),
            subprocess.CompletedProcess([], 0, stdout="D:/execroot/_main\n"),
        ]
        with patch.object(smoke.subprocess, "run", side_effect=outputs) as run:
            result = smoke.build_msvc_header_parser(env)

        settings = [
            "--config=ci-windows",
            "--host_platform=//:local_windows_msvc",
            "--extra_execution_platforms=//:windows_x86_64_msvc",
            "--extra_toolchains=//:windows_gnullvm_tests_on_msvc_host_toolchain",
            "--extra_toolchains=//:local_windows_msvc_cc_toolchain",
            "--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0",
            "--platforms=//:windows_x86_64_msvc",
            "--compilation_mode=opt",
        ]
        expected = [
            [
                "fake-bazel",
                "--output_user_root=D:/output root",
                command,
                *settings,
                *tail,
                "--repo_contents_cache=D:/repo cache",
            ]
            for command, tail in (
                ("build", ["@llvm//tools/internal:header-parser"]),
                ("cquery", ["--output=files", "@llvm//tools/internal:header-parser"]),
                ("info", ["execution_root"]),
            )
        ]
        self.assertEqual([call.args[0] for call in run.call_args_list], expected)
        self.assertEqual(result, Path("D:/execroot/_main") / executable)
        self.assertEqual(env, original)
        local_env = {**original, "BUILDBUDDY_API_KEY": ""}
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["env"], local_env)
            self.assertEqual(call.kwargs["cwd"], Path(smoke.__file__).resolve().parents[2])
            self.assertTrue(call.kwargs["check"])

    def test_missing_or_ambiguous_executable_fails_before_execution(self) -> None:
        for files in ("", "first.exe\nsecond.exe\n"):
            with self.subTest(files=files):
                outputs = [
                    subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 0, stdout=files),
                ]
                with patch.object(smoke.subprocess, "run", side_effect=outputs) as run:
                    with self.assertRaisesRegex(RuntimeError, "exactly one"):
                        smoke.build_msvc_header_parser({})
                self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
