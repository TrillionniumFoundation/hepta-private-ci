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

raw_args = sys.argv[1:]
if os.environ.get('BAZEL_PROBE_TRANSPORT_LOG'):
    with Path(os.environ['BAZEL_PROBE_TRANSPORT_LOG']).open('a', encoding='utf-8') as output:
        output.write(json.dumps(raw_args) + '\\n')
if os.environ.get('BAZEL_PROBE_ARGV_LIMIT') and sum(len(arg.encode('utf-16-le')) // 2 + 3 for arg in raw_args) > int(os.environ['BAZEL_PROBE_ARGV_LIMIT']):
    print('recorded native command line exceeded the Windows argument limit')
    sys.exit(126)

patterns = next((arg for arg in raw_args if arg.startswith('--target_pattern_file=')), None)
if patterns:
    native_path = patterns.split('=', 1)[1]
    path = native_path
    mapping = Path(os.environ['BAZEL_PROBE_PATH_MAPPING'])
    if mapping.exists():
        path = json.loads(mapping.read_text(encoding='utf-8')).get(native_path, native_path)
    contents = Path(path).read_bytes().decode('utf-8')
    effective_patterns = [pattern for line in contents.split('\\n')
                          if (pattern := line.split('#', 1)[0].strip(
                              ''.join(chr(value) for value in range(33))))]
    Path(os.environ['BAZEL_PROBE_TARGET_FILE_LOG']).write_text(json.dumps({
        'native_path': native_path,
        'path': path,
        'native_argv': raw_args,
        'contents': contents,
        'effective_patterns': effective_patterns,
        'msys_arg_conv_excl': os.environ.get('MSYS2_ARG_CONV_EXCL'),
    }), encoding='utf-8')
    prefix = [arg for arg in raw_args if arg != patterns]
    if prefix and prefix[-1] == '--':
        prefix.pop()
    sys.argv[1:] = prefix + ['--', *effective_patterns]
with Path(os.environ['BAZEL_PROBE_LOG']).open('a', encoding='utf-8') as output:
    output.write(json.dumps(sys.argv[1:]) + '\\n')
command = next(arg for arg in sys.argv[1:] if not arg.startswith('-'))
if command == 'info':
    print(os.environ['BAZEL_PROBE_TESTLOGS'])
elif command == 'query':
    if os.environ.get('BAZEL_PROBE_QUERY_FILE'):
        sys.stdout.buffer.write(Path(os.environ['BAZEL_PROBE_QUERY_FILE']).read_bytes())
    elif os.environ.get('BAZEL_PROBE_QUERY_CRLF') == '1':
        sys.stdout.buffer.write(b'//codex-rs/fake:library\\r\\n')
    else:
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
        self.path_mapping = self.root / "native-path.json"
        self.target_file_log = self.root / "target-file.json"
        self.temporary_files = self.root / "temporary files"
        self.temporary_files.mkdir()
        self.testlogs = self.root / "testlogs"
        target_log = self.testlogs / "fake" / "target" / "test.log"
        target_log.parent.mkdir(parents=True)
        target_log.write_text("actual failing test diagnostic\n", encoding="utf-8")
        probe = self.root / "probe.py"
        probe.write_text(PROBE, encoding="utf-8")
        if os.name == "nt":
            executable = self.root / "bazel.cmd"
            executable.write_text(
                f'@"{sys.executable}" "{probe}" %*\n', encoding="utf-8"
            )
            git_bash = (
                Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                / "Git/bin/bash.exe"
            )
            self.bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
        else:
            executable = self.root / "bazel"
            executable.write_text(
                f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(probe))} "$@"\n',
                encoding="utf-8",
            )
            executable.chmod(0o755)
            self.bash = shutil.which("bash")
            # Exercise the explicit native-path conversion on Linux as well.
            # The Bazel probe maps this Windows spelling back to the real file.
            cygpath_probe = self.root / "cygpath_probe.py"
            cygpath_probe.write_text(
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "assert sys.argv[1] in ('-m', '-w') and len(sys.argv) == 3\n"
                "if os.environ.get('BAZEL_PROBE_CYGPATH_FAIL') == '1':\n"
                "    sys.exit(23)\n"
                "if sys.argv[1] == '-w':\n"
                "    print(sys.argv[2])\n"
                "    sys.exit(0)\n"
                "native = 'C:/Bazel target patterns/' + Path(sys.argv[2]).name\n"
                "Path(os.environ['BAZEL_PROBE_PATH_MAPPING']).write_text(\n"
                "    json.dumps({native: sys.argv[2]}), encoding='utf-8')\n"
                "print(native)\n",
                encoding="utf-8",
            )
            cygpath = self.root / "cygpath"
            cygpath.write_text(
                f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(cygpath_probe))} "$@"\n',
                encoding="utf-8",
            )
            cygpath.chmod(0o755)
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
            BAZEL_PROBE_PATH_MAPPING=str(self.path_mapping),
            BAZEL_PROBE_TARGET_FILE_LOG=str(self.target_file_log),
            BAZEL_REPO_CONTENTS_CACHE="job scoped cache",
            TMPDIR=self.temporary_files.as_posix(),
            INCLUDE=r"C:\VS\include;C:\SDK\include",
            LIB=r"C:\VS\lib;C:\SDK\lib",
            LIBPATH=r"C:\VS\libpath",
            UniversalCRTSdkDir=r"C:\SDK\ucrt",
            VCToolsInstallDir=r"C:\VS\VC\Tools\MSVC\14.51.36231",
            WindowsSdkDir=r"C:\SDK",
        )
        if os.name != "nt":
            self.env["PATH"] = str(self.root) + os.pathsep + self.env["PATH"]

    def run_wrapper(
        self, *args: str, targets: list[str] | None = None
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        command = [self.bash, str(SCRIPTS / "run-bazel-ci.sh"), *args]
        shell_input = None
        if targets is not None:
            # Avoid putting the oversized fixture in Python's own Windows
            # CreateProcess argv. Bash builds it and invokes the real wrapper
            # through its source builtin, just as CI expands its Bash array.
            command = [self.bash]
            shell_input = (
                "targets=(\n"
                + "\n".join(shlex.quote(target) for target in targets)
                + "\n)\nsource "
                + " ".join(
                    shlex.quote(arg)
                    for arg in [
                        (SCRIPTS / "run-bazel-ci.sh").as_posix(),
                        *args,
                        "--",
                    ]
                )
                + ' "${targets[@]}"\n'
            )
        result = subprocess.run(
            command,
            input=shell_input,
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

    def long_targets(self) -> list[str]:
        targets = [
            f"//codex-rs/fixture/package_{index:04d}:" + "long_clippy_target_" * 4
            for index in range(700)
        ]
        targets.insert(1, "-//codex-rs/fixture:excluded")
        targets.append(targets[0])
        return targets

    def test_long_windows_targets_use_native_file_without_changing_patterns(
        self,
    ) -> None:
        targets = self.long_targets()
        result, calls = self.run_wrapper(
            "--windows-msvc-host-platform",
            "--",
            "build",
            "--config=clippy",
            "--platforms=//:windows_x86_64_msvc",
            targets=targets,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(calls), 1)
        args = calls[0]
        observed = json.loads(self.target_file_log.read_text(encoding="utf-8"))
        self.assertEqual(
            observed["contents"], "".join(target + "\n" for target in targets)
        )
        self.assertEqual(observed["effective_patterns"], targets)
        self.assertIn(
            f"--target_pattern_file={observed['native_path']}", observed["native_argv"]
        )
        self.assertTrue(Path(observed["native_path"]).is_absolute())
        self.assertEqual(observed["msys_arg_conv_excl"], "*")
        self.assertEqual(args[args.index("--") + 1 :], targets)
        for flag in (
            "--config=clippy",
            "--config=ci-windows",
            "--host_platform=//:local_windows_msvc",
            "--platforms=//:windows_x86_64_msvc",
            "--repo_contents_cache=job scoped cache",
        ):
            self.assertIn(flag, args)
        self.assertFalse(Path(observed["path"]).exists())
        self.assertEqual(list(self.temporary_files.iterdir()), [])

    def test_long_windows_target_file_failure_preserves_status_and_diagnostics(
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
            targets=self.long_targets(),
        )
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.assertEqual(len(calls), 2)
        build, info = calls
        self.assertEqual(build[build.index("--") + 1 :], self.long_targets())
        self.assertFalse(any(arg.startswith("--target_pattern_file=") for arg in info))
        for flag in (
            "--config=ci-windows",
            "--host_platform=//:local_windows_msvc",
            "--platforms=//:custom-target",
        ):
            self.assertIn(flag, build)
            self.assertIn(flag, info)
        self.assertIn("undefined symbol: __stack_chk_fail", result.stdout)
        self.assertIn(">>> referenced by native-archive.o", result.stdout)
        self.assertIn("actual failing test diagnostic", result.stdout)
        observed = json.loads(self.target_file_log.read_text(encoding="utf-8"))
        self.assertFalse(Path(observed["path"]).exists())
        self.assertEqual(list(self.temporary_files.iterdir()), [])

    def test_large_linux_targets_keep_the_original_argv(self) -> None:
        self.env["RUNNER_OS"] = "Linux"
        targets = self.long_targets()
        if os.name == "nt":
            # This Linux contract can also run on a Windows test host without
            # overflowing that host's unrelated native process argv limit.
            targets = targets[:140] + [targets[-1]]
        result, calls = self.run_wrapper(
            "--", "build", "--config=clippy", targets=targets
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(calls), 1)
        args = calls[0]
        self.assertEqual(args[args.index("--") + 1 :], targets)
        self.assertTrue("--config=clippy" in args)
        self.assertFalse(any(arg.startswith("--action_env=") for arg in args))
        self.assertFalse(any(arg.startswith("--target_pattern_file=") for arg in args))
        self.assertFalse(self.target_file_log.exists())
        self.assertFalse(self.path_mapping.exists())
        self.assertEqual(list(self.temporary_files.iterdir()), [])

    def test_large_windows_query_keeps_its_command_line_expression(self) -> None:
        # Query has its own query-file option and must not receive the
        # build/test target-pattern-file flag. Stay below the native host
        # limit while exceeding the wrapper's target-file cutover.
        expression = " + ".join(self.long_targets()[:100])
        result, calls = self.run_wrapper("--", "query", targets=[expression])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(calls), 1)
        args = calls[0]
        self.assertEqual(args[args.index("--") + 1 :], [expression])
        self.assertFalse(any(arg.startswith("--target_pattern_file=") for arg in args))
        self.assertFalse(self.target_file_log.exists())
        self.assertFalse(self.path_mapping.exists())
        self.assertEqual(list(self.temporary_files.iterdir()), [])

    def test_windows_patterns_reinterpreted_by_file_syntax_keep_original_argv(
        self,
    ) -> None:
        for pattern in (
            "//fixture:literal#suffix",
            "#comment",
            " //fixture:leading",
            "//fixture:trailing ",
            "\x07//fixture:leading-control",
            "//fixture:trailing-control\x07",
            "",
        ):
            with self.subTest(pattern=pattern):
                self.log.unlink(missing_ok=True)
                targets = self.long_targets()[:100] + [pattern]
                result, calls = self.run_wrapper("--", "build", targets=targets)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(len(calls), 1)
                args = calls[0]
                self.assertEqual(args[args.index("--") + 1 :], targets)
                self.assertFalse(
                    any(arg.startswith("--target_pattern_file=") for arg in args)
                )
                self.assertFalse(self.target_file_log.exists())
                self.assertFalse(self.path_mapping.exists())
                self.assertEqual(list(self.temporary_files.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "Uses the POSIX host's controlled cygpath probe")
    def test_failed_native_path_conversion_cleans_files_before_bazel_runs(self) -> None:
        self.env["BAZEL_PROBE_CYGPATH_FAIL"] = "1"
        targets = self.long_targets()
        shell_input = (
            "targets=(\n"
            + "\n".join(shlex.quote(target) for target in targets)
            + "\n)\nsource "
            + shlex.quote((SCRIPTS / "run-bazel-ci.sh").as_posix())
            + ' -- build -- "${targets[@]}"\n'
        )
        result = subprocess.run(
            [self.bash],
            input=shell_input,
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.target_file_log.exists())
        self.assertEqual(list(self.temporary_files.iterdir()), [])

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

    def test_large_windows_build_preserves_all_targets_without_a_large_native_command(
        self,
    ) -> None:
        targets = [
            f"//long_package_{index:04d}/native_component:clippy_target"
            for index in range(900)
        ]
        targets.extend(["-//excluded:target", "//路径 with spaces:target"])
        arguments = ["--", "build", "--config=clippy", "--", *targets]
        invocation = self.root / "ci-arguments.nul"
        invocation.write_bytes(
            b"\0".join(arg.encode("utf-8") for arg in arguments) + b"\0"
        )
        driver = self.root / "driver.sh"
        driver.write_text(
            "if type mapfile >/dev/null 2>&1; then enable -n mapfile; fi\n"
            "ci_args=()\n"
            'while IFS= read -r -d "" ci_arg; do ci_args+=("$ci_arg"); done < "$1"\n'
            'source "$2" "${ci_args[@]}"\n',
            encoding="utf-8",
        )
        physical = self.root / "physical-arguments.jsonl"
        self.env.update(
            BAZEL_PROBE_TRANSPORT_LOG=str(physical),
            BAZEL_PROBE_ARGV_LIMIT="32767",
        )
        result = subprocess.run(
            [self.bash, str(driver), str(invocation), str(SCRIPTS / "run-bazel-ci.sh")],
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
        self.assertEqual(calls[0][calls[0].index("--") + 1 :], targets)
        self.assertIn("--config=clippy", calls[0])
        native_args = json.loads(physical.read_text(encoding="utf-8").splitlines()[0])
        self.assertLess(
            sum(len(arg.encode("utf-16-le")) // 2 + 3 for arg in native_args), 32767
        )
        pattern_file = next(
            arg.split("=", 1)[1]
            for arg in native_args
            if arg.startswith("--target_pattern_file=")
        )
        self.assertFalse(
            Path(pattern_file).exists(), "retired Bazel must release its target file"
        )

    def test_windows_target_files_preserve_test_and_coverage_failures(self) -> None:
        self.env["BAZEL_PROBE_FAIL"] = "1"
        physical = self.root / "physical-arguments.jsonl"
        self.env["BAZEL_PROBE_TRANSPORT_LOG"] = str(physical)
        targets = self.long_targets() + ["//路径 with spaces:target"]
        for command in ("test", "coverage"):
            with self.subTest(command=command):
                if self.log.exists():
                    self.log.unlink()
                if physical.exists():
                    physical.unlink()
                result, calls = self.run_wrapper(
                    "--", command, "--keep_going", targets=targets
                )
                self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
                self.assertIn(command, calls[0])
                self.assertIn("--keep_going", calls[0])
                self.assertEqual(calls[0][calls[0].index("--") + 1 :], targets)
                native_args = json.loads(
                    physical.read_text(encoding="utf-8").splitlines()[0]
                )
                pattern_file = next(
                    arg.split("=", 1)[1]
                    for arg in native_args
                    if arg.startswith("--target_pattern_file=")
                )
                self.assertFalse(
                    Path(pattern_file).exists(),
                    "failed Bazel must release its target file",
                )

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
        self.assertIn(f"--action_env=PATH={self.env['CODEX_BAZEL_WINDOWS_PATH']}", args)
        self.assertIn(
            f"--host_action_env=PATH={self.env['CODEX_BAZEL_WINDOWS_PATH']}", args
        )
        self.assertFalse(
            any(arg == "--incompatible_strict_action_env=0" for arg in args)
        )
        self.assertEqual(args[args.index("--") + 1 :], ["//fake:target"])
        self.assertFalse(any(arg.startswith("--target_pattern_file=") for arg in args))
        self.assertFalse(self.target_file_log.exists())
        self.assertFalse(self.path_mapping.exists())
        self.assertEqual(list(self.temporary_files.iterdir()), [])

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
        self.env["BAZEL_PROBE_QUERY_CRLF"] = "1"
        result = self.run_argument_lint()
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

    def run_argument_lint(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
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

    def test_windows_argument_lint_preserves_the_entire_large_crlf_query_roster(
        self,
    ) -> None:
        targets = [
            f"//long_package_{index:04d}/native_component:library"
            for index in range(900)
        ]
        targets.append("//路径:library")
        roster = self.root / "query labels.txt"
        roster.write_bytes(("\r\n".join(targets) + "\r\n").encode("utf-8"))
        physical = self.root / "physical-arguments.jsonl"
        self.env.update(
            BAZEL_PROBE_QUERY_FILE=str(roster),
            BAZEL_PROBE_TRANSPORT_LOG=str(physical),
            BAZEL_PROBE_ARGV_LIMIT="32767",
        )
        result = self.run_argument_lint()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(calls), 2)
        build = calls[1]
        self.assertEqual(build[build.index("--") + 1 :], targets)
        native_args = json.loads(physical.read_text(encoding="utf-8").splitlines()[1])
        pattern_file = next(
            arg.split("=", 1)[1]
            for arg in native_args
            if arg.startswith("--target_pattern_file=")
        )
        self.assertFalse(Path(pattern_file).exists())

    def test_authenticated_cross_keeps_linux_build_actions_and_windows_tests(
        self,
    ) -> None:
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
