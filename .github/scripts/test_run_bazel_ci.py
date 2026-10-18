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
    encoded = Path(patterns.split('=', 1)[1]).read_bytes().decode('latin-1')
    lines = encoded.split('\\n')
    targets = []
    java_trim = ''.join(chr(code) for code in range(0x21))
    for line in lines:
        internal = line.split('#', 1)[0].strip(java_trim)
        if internal:
            targets.append(internal.encode('latin-1').decode('utf-8'))
    sys.argv[1:] = [arg for arg in raw_args if arg != patterns] + ['--', *targets]

with Path(os.environ['BAZEL_PROBE_LOG']).open('a', encoding='utf-8') as output:
    output.write(json.dumps(sys.argv[1:]) + '\\n')
command = next(arg for arg in sys.argv[1:] if not arg.startswith('-'))
if command == 'info':
    print(os.environ['BAZEL_PROBE_TESTLOGS'])
elif command == 'query':
    if os.environ.get('BAZEL_PROBE_QUERY_FAIL') == '1':
        print('//codex-rs/fake:partial-output')
        sys.exit(37)
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
    def install_python_boundary_recorder(self) -> tuple[Path, Path]:
        scripts = self.root / "recorded scripts"
        scripts.mkdir(exist_ok=True)
        shell = scripts / "run-bazel-ci.sh"
        shell.write_bytes((SCRIPTS / "run-bazel-ci.sh").read_bytes())
        boundary_log = self.root / "python-boundary.jsonl"
        self.env["BAZEL_BOUNDARY_LOG"] = str(boundary_log)
        entry = scripts / "run_bazel_with_buildbuddy.py"
        entry.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, runpy, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "record = {'args': args}\n"
            "if len(args) == 2 and args[0] == '--wrapper-args-file':\n"
            "    record['payload'] = Path(args[1]).read_bytes().decode('utf-8')\n"
            "with Path(os.environ['BAZEL_BOUNDARY_LOG']).open('a', encoding='utf-8') as output:\n"
            "    output.write(json.dumps(record) + '\\n')\n"
            "if sum(len(arg.encode('utf-16-le')) // 2 + 3 for arg in args) > 32767:\n"
            "    raise SystemExit(126)\n"
            "if os.environ.get('BAZEL_BOUNDARY_FAIL'):\n"
            "    raise SystemExit(int(os.environ['BAZEL_BOUNDARY_FAIL']))\n"
            f"runpy.run_path({str(SCRIPTS / 'run_bazel_with_buildbuddy.py')!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        if os.name != "nt":
            entry.chmod(0o755)
        return shell, boundary_log

    def test_wrapper_argument_file_is_removed_after_python_entry_failure(self) -> None:
        shell, boundary_log = self.install_python_boundary_recorder()
        self.env["BAZEL_BOUNDARY_FAIL"] = "37"
        result = subprocess.run(
            [self.bash, str(shell), "--", "build", "--", "//fake:target"],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        records = [
            json.loads(line)
            for line in boundary_log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["args"][0], "--wrapper-args-file")
        self.assertEqual(len(records[0]["args"]), 2)
        self.assertFalse(Path(records[0]["args"][1]).exists())
        self.assertFalse(
            self.log.exists(), "Python entry failure must not launch fake Bazel"
        )

    def workflow_script(self, step_name: str) -> str:
        text = (SCRIPTS.parent / "workflows/bazel.yml").read_text(encoding="utf-8")
        section = text.split(f"      - name: {step_name}\n", 1)[1].split(
            "\n      - name:", 1
        )[0]
        code = section.split("        run: |\n", 1)[1]
        # The source block is a Windows Git Bash job. Supply only its exact
        # mapfile call on macOS Bash 3.2, without changing the extracted body.
        portable_mapfile = """if ! type mapfile >/dev/null 2>&1; then
  mapfile() {
    if [[ $# -ne 2 || "$1" != "-t" || "$2" != "bazel_targets" ]]; then
      return 2
    fi
    bazel_targets=()
    local target
    while IFS= read -r target || [[ -n "$target" ]]; do
      bazel_targets+=("$target")
    done
    return 0
  }
fi
"""
        return (
            portable_mapfile
            + "\n".join(
                line[10:] if line.startswith("          ") else line
                for line in code.splitlines()
            )
            + "\n"
        )

    def test_all_windows_label_consumers_preserve_complete_crlf_rosters(self) -> None:
        targets = [f"//pkg_{index}:unit-tests-bin" for index in range(12)] + [
            "//路径:unit-tests-bin"
        ]
        roster = self.root / "query labels.txt"
        roster.write_bytes(("\r\n".join(targets) + "\r\n").encode("utf-8"))
        self.env.update(
            BAZEL_PROBE_QUERY_FILE=str(roster),
            GITHUB_SHA="fixture-sha",
            BAZEL_TEST_SHARD="1",
            BAZEL_TEST_SHARD_COUNT="1",
        )
        invocations = {
            "clippy": self.workflow_script("bazel build --config=clippy lint targets"),
            "shard": self.workflow_script("bazel test shard"),
            "argument_lint": "./.github/scripts/run-argument-comment-lint-bazel.sh --config=argument-comment-lint\n",
        }
        for name, code in invocations.items():
            with self.subTest(consumer=name):
                if self.log.exists():
                    self.log.unlink()
                script = self.root / f"{name}.sh"
                script.write_text(code, encoding="utf-8")
                result = subprocess.run(
                    [
                        self.bash,
                        "--noprofile",
                        "--norc",
                        "-e",
                        "-o",
                        "pipefail",
                        str(script),
                    ],
                    cwd=SCRIPTS.parent.parent,
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
                expected = (
                    ["//codex-rs/...", "-//codex-rs/v8-poc:all", *targets]
                    if name == "clippy"
                    else sorted(targets)
                    if name == "shard"
                    else targets
                )
                self.assertEqual(calls[1][calls[1].index("--") + 1 :], expected)
                # Every consumer must fail before build on a partial query.
                self.log.unlink()
                self.env["BAZEL_PROBE_QUERY_FAIL"] = "1"
                failed = subprocess.run(
                    [
                        self.bash,
                        "--noprofile",
                        "--norc",
                        "-e",
                        "-o",
                        "pipefail",
                        str(script),
                    ],
                    cwd=SCRIPTS.parent.parent,
                    env=self.env,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                del self.env["BAZEL_PROBE_QUERY_FAIL"]
                self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
                calls = [
                    json.loads(line)
                    for line in self.log.read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(len(calls), 1, "partial query must never reach build")
                # Empty successful discovery has consumer-specific policy:
                # Clippy retains its fixed patterns; other consumers reject it.
                self.log.unlink()
                roster.write_bytes(b"")
                empty = subprocess.run(
                    [
                        self.bash,
                        "--noprofile",
                        "--norc",
                        "-e",
                        "-o",
                        "pipefail",
                        str(script),
                    ],
                    cwd=SCRIPTS.parent.parent,
                    env=self.env,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                empty_calls = [
                    json.loads(line)
                    for line in self.log.read_text(encoding="utf-8").splitlines()
                ]
                if name == "clippy":
                    self.assertEqual(empty.returncode, 0, empty.stdout + empty.stderr)
                    self.assertEqual(len(empty_calls), 2)
                    self.assertEqual(
                        empty_calls[1][empty_calls[1].index("--") + 1 :],
                        ["//codex-rs/...", "-//codex-rs/v8-poc:all"],
                    )
                else:
                    self.assertNotEqual(
                        empty.returncode, 0, empty.stdout + empty.stderr
                    )
                    self.assertEqual(len(empty_calls), 1)
                roster.write_bytes(("\r\n".join(targets) + "\r\n").encode("utf-8"))

    def test_query_normalizes_only_explicit_windows_labels_and_keeps_failure(
        self,
    ) -> None:
        roster = self.root / "query raw bytes"
        original = b"//pkg:first\r\n//pkg:second\r\n"
        roster.write_bytes(original)
        self.env["BAZEL_PROBE_QUERY_FILE"] = str(roster)
        cases = [
            ("Windows", ["--output=label"], original.replace(b"\r\n", b"\n")),
            ("Windows", ["--output", "label"], original.replace(b"\r\n", b"\n")),
            ("Windows", ["--output=proto"], original),
            ("Windows", ["--output=label", "--output=proto"], original),
            ("Windows", [], original),
            ("Linux", ["--output=label"], original),
        ]
        for runner_os, flags, expected in cases:
            with self.subTest(runner_os=runner_os, flags=flags):
                self.env["RUNNER_OS"] = runner_os
                result = subprocess.run(
                    [
                        self.bash,
                        str(SCRIPTS / "run-bazel-query-ci.sh"),
                        *flags,
                        "--",
                        "//fake/...",
                    ],
                    env=self.env,
                    check=False,
                    capture_output=True,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
        self.env.update(RUNNER_OS="Windows", BAZEL_PROBE_QUERY_FAIL="1")
        result = subprocess.run(
            [
                self.bash,
                str(SCRIPTS / "run-bazel-query-ci.sh"),
                "--output=label",
                "--",
                "//fake/...",
            ],
            env=self.env,
            check=False,
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(result.stdout, b"")

    def test_query_without_options_preserves_expression_and_raw_output(self) -> None:
        roster = self.root / "query raw bytes"
        original = b"//pkg:first\r\n\x00trailing\r\n"
        roster.write_bytes(original)
        expression = 'kind("rust_library", //pkg/...)'
        self.env["BAZEL_PROBE_QUERY_FILE"] = str(roster)
        for runner_os in ("Linux", "macOS", "Windows"):
            with self.subTest(runner_os=runner_os):
                self.env["RUNNER_OS"] = runner_os
                if self.log.exists():
                    self.log.unlink()
                result = subprocess.run(
                    [
                        self.bash,
                        str(SCRIPTS / "run-bazel-query-ci.sh"),
                        "--",
                        expression,
                    ],
                    env=self.env,
                    check=False,
                    capture_output=True,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, original)
                calls = [
                    json.loads(line)
                    for line in self.log.read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(len(calls), 1)
                self.assertEqual(
                    calls[0][calls[0].index("query") + 1 :],
                    ["--repo_contents_cache=job scoped cache", expression],
                )

    def test_query_cleanup_failure_preserves_failure_status_and_withholds_roster(
        self,
    ) -> None:
        driver = self.root / "query cleanup failure.sh"
        # Git/bin/bash.exe prepends Git's tools to PATH before starting Bash.
        # Install the fault in that shell so its real rm cannot shadow it.
        driver.write_text(
            "rm() {\n"
            '  printf "%s\\n" "$@" > "$BAZEL_PROBE_RM_LOG"\n'
            "  return 23\n"
            "}\n"
            'source "$@"\n',
            encoding="utf-8",
            newline="\n",
        )
        cleanup_log = self.root / "cleanup-path.txt"
        self.env["BAZEL_PROBE_RM_LOG"] = str(cleanup_log)
        for query_failure, expected_status in ((False, 23), (True, 37)):
            with self.subTest(query_failure=query_failure):
                if query_failure:
                    self.env["BAZEL_PROBE_QUERY_FAIL"] = "1"
                else:
                    self.env.pop("BAZEL_PROBE_QUERY_FAIL", None)
                owned = None
                try:
                    result = subprocess.run(
                        [
                            self.bash,
                            str(driver),
                            str(SCRIPTS / "run-bazel-query-ci.sh"),
                            "--output=label",
                            "--",
                            "//fake/...",
                        ],
                        env=self.env,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    self.assertEqual(
                        result.returncode,
                        expected_status,
                        result.stdout + result.stderr,
                    )
                    self.assertEqual(result.stdout, "")
                    self.assertIn(
                        "Failed to remove Bazel query label file", result.stderr
                    )
                    rm_args = cleanup_log.read_text(encoding="utf-8").splitlines()
                    self.assertEqual(rm_args[0], "-f")
                    self.assertEqual(len(rm_args), 2)
                    owned = Path(rm_args[1])
                    if os.name == "nt" and not owned.exists():
                        converted = subprocess.run(
                            [self.bash, "-c", 'cygpath -w "$1"', "fixture", rm_args[1]],
                            env=self.env,
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )
                        owned = Path(converted.stdout.strip())
                    self.assertTrue(
                        owned.exists(),
                        "fake cleanup failure must retain its owned file",
                    )
                finally:
                    if owned is not None:
                        owned.unlink()

    def test_large_windows_build_records_both_native_transport_boundaries(
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
        shell, boundary_log = self.install_python_boundary_recorder()
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
            [self.bash, str(driver), str(invocation), str(shell)],
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
        entries = [
            json.loads(line)
            for line in boundary_log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["args"][0], "--wrapper-args-file")
        self.assertEqual(len(entries[0]["args"]), 2)
        self.assertTrue(entries[0]["payload"].endswith("\0"))
        decoded = entries[0]["payload"][:-1].split("\0")
        self.assertEqual(decoded[decoded.index("--") + 1 :], targets)
        self.assertFalse(Path(entries[0]["args"][1]).exists())
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

    def run_clippy_target_list(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                self.bash,
                str(SCRIPTS.parent.parent / "scripts/list-bazel-clippy-targets.sh"),
                *args,
            ],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_clippy_target_list_preserves_platform_applicable_helpers(self) -> None:
        unit = "//codex-rs/core:core-unit-tests-bin"
        binary_unit = "//codex-rs/cli:codex-bin-unit-tests-bin"
        native = "//codex-rs/core:core-all-test-bin"
        cross = "//codex-rs/core:core-all-test-windows-cross-bin"
        other = "//codex-rs/fake:other-manual-test"
        unix_only = "//codex-rs/hepta-agentd:hepta-agentd-cognitive-product-qualification-test-bin"
        writer = "//codex-rs/hepta-agentd:hepta-agentd-cognitive-write-qualification-test-bin"
        roster = self.root / "manual-query.txt"
        for newline in ("\n", "\r\n"):
            roster.write_bytes(
                (
                    newline.join(
                        [unit, binary_unit, native, cross, other, unix_only, writer]
                    )
                    + newline
                ).encode()
            )
            self.env["BAZEL_PROBE_QUERY_FILE"] = str(roster)
            cases = [
                ("Linux", [], [unit, binary_unit, native, other, unix_only, writer]),
                ("macOS", [], [unit, binary_unit, native, other, unix_only, writer]),
                ("Windows", [], [unit, binary_unit, native, cross, other, writer]),
                (
                    "Windows",
                    ["--windows-cross-compile"],
                    [unit, binary_unit, cross, other],
                ),
                (
                    "Windows",
                    ["--windows-msvc"],
                    [unit, binary_unit, native, other, writer],
                ),
            ]
            for runner_os, args, helpers in cases:
                with self.subTest(runner_os=runner_os, args=args, newline=newline):
                    self.env["RUNNER_OS"] = runner_os
                    result = self.run_clippy_target_list(*args)
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                    self.assertEqual(
                        result.stdout.splitlines(),
                        ["//codex-rs/...", "-//codex-rs/v8-poc:all", *helpers],
                    )

    def test_clippy_target_list_query_failure_emits_no_partial_roster(self) -> None:
        self.env["BAZEL_PROBE_QUERY_FAIL"] = "1"
        result = self.run_clippy_target_list("--windows-msvc")
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_clippy_target_list_rejects_conflicting_platform_modes(self) -> None:
        for args in (
            ["--windows-msvc", "--windows-cross-compile"],
            ["--windows-cross-compile", "--windows-msvc"],
        ):
            with self.subTest(args=args):
                result = self.run_clippy_target_list(*args)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("mutually exclusive", result.stderr)
        self.assertFalse(self.log.exists())

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
        targets = ["//fake:target", "-//excluded:target", "//路径 with spaces:target"]
        for command in ("test", "coverage"):
            with self.subTest(command=command):
                if self.log.exists():
                    self.log.unlink()
                if physical.exists():
                    physical.unlink()
                result, calls = self.run_wrapper(
                    "--", command, "--keep_going", "--", *targets
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

    def test_macos_ci_serializes_bazel_9_cache_uploads_without_waivers(self) -> None:
        # Bazel 9.0.0 can race a late-discovered C++ input with background
        # upload of an action's stdout/stderr (bazelbuild/bazel#30693).
        # Keep the actual target matrix, remote cache/RBE and all safety gates.
        bazelrc = (SCRIPTS.parent.parent / ".bazelrc").read_text(encoding="utf-8")
        configs = [
            line
            for line in bazelrc.splitlines()
            if line and not line.lstrip().startswith("#")
        ]
        self.assertIn("common:ci-macos --noremote_cache_async", configs)
        self.assertEqual(
            sum(line.endswith("--noremote_cache_async") for line in configs), 1
        )
        for global_prefix in (
            "common ",
            "common:ci ",
            "common:ci-linux ",
            "common:ci-windows ",
            "common:ci-windows-cross ",
        ):
            self.assertNotIn(global_prefix + "--noremote_cache_async", configs)
        self.assertIn(
            "common:ci-macos --strategy=TestRunner=darwin-sandbox,local", configs
        )
        self.assertIn("common:ci-macos --config=ci-bazel", configs)

    def test_v8_canary_retries_bazel_37_once_for_both_macos_abis(self) -> None:
        # The source-head V8 canary must not silently treat the first Bazel
        # JVM crash as a passing build or exclude the Intel macOS variant.
        workflow = (SCRIPTS.parent / "workflows" / "v8-canary.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'if [[ ${bazel_status} -ne 37 || "${RUNNER_OS}" != "macOS" ]]; then',
            workflow,
        )
        self.assertIn("aarch64-apple-darwin|x86_64-apple-darwin) ;;", workflow)
        self.assertIn('*) exit "${bazel_status}" ;;', workflow)
        self.assertIn(
            'echo "Bazel exited 37 on macOS ${TARGET}; '
            'shutting down and retrying the identical V8 build once."',
            workflow,
        )
        self.assertEqual(workflow.count("\n          run_v8_bazel\n"), 2)
        self.assertIn("            shutdown || true", workflow)

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
