#!/usr/bin/env python3
"""Exercise the shell and Python wrappers together with a recording Bazel process."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


SCRIPTS = Path(__file__).resolve().parent
PROBE = """import json
import os
import sys
from pathlib import Path

with Path(os.environ['BAZEL_PROBE_LOG']).open('a', encoding='utf-8') as output:
    output.write(json.dumps(sys.argv[1:]) + '\\n')
command = next(arg for arg in sys.argv[1:] if not arg.startswith('-'))
if command == 'info':
    print(os.environ['BAZEL_PROBE_TESTLOGS'])
elif command == 'query':
    print('//codex-rs/fake:library')
elif os.environ.get('BAZEL_PROBE_FAIL') == '1':
    print('ERROR: fake/BUILD.bazel:1:1: Linking //fake:target failed: (Exit 37)')
    print('error: linking with rust-lld failed: exit code: 37')
    print('  = note: rust-lld: warning: ignoring unknown argument')
    print('          rust-lld: error: undefined symbol: __stack_chk_fail')
    print('          >>> referenced by native-archive.o')
    print('FAIL: //fake:target')
    sys.exit(37)
"""


class RunBazelCiIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory(prefix="bazel wrapper ")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.log = self.root / "arguments.jsonl"
        self.testlogs = self.root / "testlogs"
        target_log = self.testlogs / "fake" / "target" / "test.log"
        target_log.parent.mkdir(parents=True)
        target_log.write_text("actual failing test diagnostic\n", encoding="utf-8")
        probe = self.root / "probe.py"
        probe.write_text(PROBE, encoding="utf-8")
        if os.name == "nt":
            executable = self.root / "bazel.cmd"
            executable.write_text(f'@"{sys.executable}" "{probe}" %*\n', encoding="utf-8")
            git_bash = (
                Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                / "Git/bin/bash.exe"
            )
            self.bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
        else:
            executable = self.root / "bazel"
            executable.write_text(
                f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(probe))} \"$@\"\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            self.bash = shutil.which("bash")
        self.assertIsNotNone(self.bash, "Bash is required to exercise the CI wrapper")
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("BAZEL_", "BUILDBUDDY_", "CODEX_BAZEL_", "GITHUB_"))
        }
        self.env.update(
            RUNNER_OS="Windows",
            CODEX_BAZEL_BIN=str(executable),
            CODEX_BAZEL_WINDOWS_PATH=r"C:\Program Files\PowerShell\7;C:\Program Files\Git\bin",
            BAZEL_PROBE_LOG=str(self.log),
            BAZEL_PROBE_TESTLOGS=str(self.testlogs),
            BAZEL_REPO_CONTENTS_CACHE="job scoped cache",
            INCLUDE=r"C:\VS\include;C:\SDK\include",
            LIB=r"C:\VS\lib;C:\SDK\lib",
            LIBPATH=r"C:\VS\libpath",
            UniversalCRTSdkDir=r"C:\SDK\ucrt",
            VCToolsInstallDir=r"C:\VS\VC\Tools\MSVC\14.51.36231",
            WindowsSdkDir=r"C:\SDK",
        )

    def run_wrapper(
        self, *args: str
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        result = subprocess.run(
            [self.bash, str(SCRIPTS / "run-bazel-ci.sh"), *args],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertTrue(self.log.exists(), result.stdout + result.stderr)
        calls = [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
        ]
        return result, calls

    def test_keyless_cross_uses_msvc_exec_and_gnullvm_target(self) -> None:
        result, calls = self.run_wrapper(
            "--windows-cross-compile",
            "--",
            "build",
            "--config=clippy",
            "--",
            "//fake:target",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(calls), 1)
        args = calls[0]
        self.assertIn("--host_platform=//:local_windows_msvc", args)
        self.assertIn("--platforms=//:windows_x86_64_gnullvm", args)
        self.assertIn("--extra_toolchains=//:local_windows_msvc_cc_toolchain", args)
        self.assertIn("--repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=0", args)
        self.assertIn("--jobs=8", args)
        self.assertIn(f"--test_env=PATH={self.env['CODEX_BAZEL_WINDOWS_PATH']}", args)
        self.assertNotIn("--config=ci-windows-cross", args)
        self.assertNotIn("--platforms=//:windows_x86_64_msvc", args)
        self.assertFalse(any("remote_header" in arg for arg in args))
        self.assertLess(
            args.index("--config=ci-windows"),
            args.index("--repo_contents_cache=job scoped cache"),
        )
        self.assertEqual(args[args.index("--") + 1 :], ["//fake:target"])

    def test_native_windows_forwards_required_msvc_environment(self) -> None:
        result, calls = self.run_wrapper(
            "--windows-msvc-host-platform",
            "--",
            "build",
            "--",
            "//fake:target",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(calls), 1)
        args = calls[0]
        for name in (
            "INCLUDE",
            "LIB",
            "LIBPATH",
            "UniversalCRTSdkDir",
            "VCToolsInstallDir",
            "WindowsSdkDir",
        ):
            self.assertIn(f"--action_env={name}", args)
            self.assertIn(f"--host_action_env={name}", args)
        self.assertIn(
            f"--action_env=PATH={self.env['CODEX_BAZEL_WINDOWS_PATH']}", args
        )
        self.assertIn(
            f"--host_action_env=PATH={self.env['CODEX_BAZEL_WINDOWS_PATH']}", args
        )
        self.assertFalse(
            any(arg == "--incompatible_strict_action_env=0" for arg in args)
        )

    def test_native_windows_rejects_missing_required_msvc_environment(self) -> None:
        del self.env["LIB"]
        result = subprocess.run(
            [
                self.bash,
                str(SCRIPTS / "run-bazel-ci.sh"),
                "--windows-msvc-host-platform",
                "--",
                "build",
                "--",
                "//fake:target",
            ],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "Missing required native Windows toolchain environment: LIB",
            result.stderr,
        )
        self.assertFalse(
            self.log.exists(),
            "Bazel must not run without the MSVC library environment",
        )

    def test_windows_argument_lint_uses_the_shared_split_abi_wrapper(self) -> None:
        result = subprocess.run(
            [
                self.bash,
                str(SCRIPTS / "run-argument-comment-lint-bazel.sh"),
                "--config=argument-comment-lint",
                "--platforms=//:local_windows",
            ],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(calls), 2)
        query, build = calls
        self.assertIn("query", query)
        self.assertNotIn("--host_platform=//:local_windows_msvc", query)
        self.assertIn("build", build)
        self.assertIn("--config=argument-comment-lint", build)
        self.assertIn("--host_platform=//:local_windows_msvc", build)
        self.assertIn("--platforms=//:windows_x86_64_gnullvm", build)
        self.assertNotIn("--platforms=//:local_windows", build)
        self.assertIn("--skip_incompatible_explicit_targets", build)
        self.assertEqual(build[build.index("--") + 1 :], ["//codex-rs/fake:library"])

    def test_authenticated_cross_keeps_linux_build_actions_and_windows_tests(self) -> None:
        self.env["BUILDBUDDY_API_KEY"] = "test-only-token"
        result, calls = self.run_wrapper(
            "--windows-cross-compile", "--", "build", "--", "//fake:target"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        args = calls[0]
        self.assertIn("--config=buildbuddy-generic-rbe", args)
        self.assertIn("--config=ci-windows-cross", args)
        self.assertIn("--host_platform=//:rbe", args)
        self.assertIn("--action_env=PATH=/usr/bin:/bin", args)
        self.assertIn(f"--test_env=PATH={self.env['CODEX_BAZEL_WINDOWS_PATH']}", args)
        self.assertNotIn("--host_platform=//:local_windows", args)
        self.assertNotIn("--jobs=8", args)

    def test_failure_preserves_status_linker_diagnostics_and_test_log_configuration(
        self,
    ) -> None:
        self.env["BAZEL_PROBE_FAIL"] = "1"
        result, calls = self.run_wrapper(
            "--windows-cross-compile",
            "--print-failed-action-summary",
            "--print-failed-test-logs",
            "--",
            "test",
            "--platforms=//:custom-target",
            "--",
            "//fake:target",
        )
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.assertEqual(len(calls), 2)
        build, info = calls
        for flag in (
            "--config=ci-windows",
            "--host_platform=//:local_windows_msvc",
            "--platforms=//:custom-target",
        ):
            self.assertIn(flag, build)
            self.assertIn(flag, info)
        self.assertIn("info", info)
        self.assertNotIn("--jobs=8", info)
        self.assertFalse(any(arg.startswith("--test_env=") for arg in info))
        summary = result.stdout.split("Bazel failed action diagnostics:", 1)[1]
        self.assertIn("undefined symbol: __stack_chk_fail", summary)
        self.assertIn(">>> referenced by native-archive.o", summary)
        self.assertIn("actual failing test diagnostic", result.stdout)


if __name__ == "__main__":
    unittest.main()
