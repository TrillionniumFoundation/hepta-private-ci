#!/usr/bin/env python3
"""Exercise the real discovery wrappers with a recording process, not Bazel analysis."""

import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import bazel_clippy_target_records as records
import run_bazel_with_buildbuddy as wrapper
import test_run_bazel_ci as original


SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[1]
RETAINED_ROLES = json.loads(
    (SCRIPTS / "fixtures/clippy-discovery-role-records.json").read_text(
        encoding="utf-8"
    )
)
NATIVE_MANUAL = set(RETAINED_ROLES["manual_native_labels"])
CROSS = set(RETAINED_ROLES["cross_labels"])
UNIX = RETAINED_ROLES["unix_only_label"]
UNIT = "//codex-rs/discovery-probe:unit-tests-bin"
PROBE = """import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with Path(os.environ['BAZEL_PROBE_LOG']).open('a', encoding='utf-8') as output:
    output.write(json.dumps(args) + '\\n')
command = next(arg for arg in args if not arg.startswith('-'))
records = Path(os.environ['CLIPPY_DISCOVERY_RECORDS']).read_bytes()
if command == 'query':
    for line in records.decode('utf-8').splitlines():
        print(line.split('\\t')[-1])
elif command == 'cquery':
    sys.stdout.buffer.write(records)
else:
    print('unexpected recording-process command', file=sys.stderr)
    sys.exit(2)
if os.environ.get('CLIPPY_DISCOVERY_FAIL') == '1':
    print('recorded query diagnostic before failure', file=sys.stderr)
    sys.exit(37)
"""


class ClippyTargetDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        # Retain the existing physical Windows/Linux process transport fixture.
        # It creates a real probe launcher and selects Bash without changing any
        # process-global environment. No real Bazel executable is invoked.
        original.RunBazelCiIntegrationTest.setUp(self)
        self.records = self.root / "configured target records.txt"
        self.env.pop("CLIPPY_DISCOVERY_FAIL", None)
        self.env["CLIPPY_DISCOVERY_RECORDS"] = str(self.records)
        (self.root / "probe.py").write_text(PROBE, encoding="utf-8")

    def write_records(self, compatible: set[str]) -> None:
        labels = NATIVE_MANUAL | CROSS | {UNIX, UNIT}
        self.records.write_text(
            "".join(
                ("compatible" if label in compatible else "incompatible")
                + "\t"
                + label
                + "\n"
                for label in sorted(labels)
            ),
            encoding="utf-8",
        )

    def run_selector(
        self, *args: str, runner: str | None = "Windows", keyed: bool = False
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        env = self.env.copy()
        env.pop("RUNNER_OS", None)
        if runner is not None:
            env["RUNNER_OS"] = runner
        if keyed:
            env["BUILDBUDDY_API_KEY"] = "RECORDING_PROCESS_ONLY_NOT_A_CREDENTIAL"
        result = subprocess.run(
            [self.bash, str(ROOT / "scripts/list-bazel-clippy-targets.sh"), *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        calls = (
            [
                json.loads(line)
                for line in self.log.read_text(encoding="utf-8").splitlines()
            ]
            if self.log.exists()
            else []
        )
        return result, calls

    def test_native_windows_preserves_native_manual_and_rejects_foreign_requests(
        self,
    ) -> None:
        self.write_records(NATIVE_MANUAL | {UNIT})
        result, calls = self.run_selector()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "//codex-rs/...",
                "-//codex-rs/v8-poc:all",
                *sorted(NATIVE_MANUAL | {UNIT}),
            ],
        )
        self.assertEqual(len(calls), 1)
        # These supplied records contain all retained GNU helpers and the
        # distinct Unix qualification helper; no name-based filter is valid.
        self.assertEqual(result.stderr.count("platform-incompatible:"), len(CROSS) + 1)

    def test_windows_cross_preserves_the_retained_cross_helpers(self) -> None:
        self.write_records(CROSS | {UNIT})
        for keyed in (False, True):
            with self.subTest(keyed=keyed):
                result, calls = self.run_selector(
                    "--windows-cross-compile", keyed=keyed
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(set(result.stdout.splitlines()[2:]), CROSS | {UNIT})
                call = calls[-1]
                if keyed:
                    self.assertIn("--config=ci-windows-cross", call)
                    self.assertIn("--host_platform=//:rbe", call)
                else:
                    self.assertIn("--platforms=//:windows_x86_64_gnullvm", call)
                    self.assertIn("--host_platform=//:local_windows_msvc", call)

    def test_windows_text_roster_survives_original_bash_and_pattern_guard(self) -> None:
        compatible = sorted(NATIVE_MANUAL | {UNIT})
        buffer = io.BytesIO()
        windows_stdout = io.TextIOWrapper(buffer, encoding="utf-8", newline="\r\n")
        try:
            with (
                patch.object(
                    records.sys,
                    "stdin",
                    io.StringIO(
                        "".join(f"compatible\t{label}\r\n" for label in compatible)
                    ),
                ),
                patch.object(records.sys, "stdout", windows_stdout),
            ):
                records.main()
                windows_stdout.flush()
            roster = self.root / "native Windows roster.txt"
            roster.write_bytes(buffer.getvalue())
        finally:
            windows_stdout.detach()

        # Keep the workflow's literal Bash read loop, including its CR handling.
        transport = subprocess.run(
            [
                self.bash,
                "-c",
                'bazel_target_lines="$(cat "$1")"\n'
                "bazel_targets=()\n"
                "while IFS= read -r target; do\n"
                '  bazel_targets+=("${target}")\n'
                'done <<< "${bazel_target_lines}"\n'
                'printf "%s\\0" "${bazel_targets[@]}"\n',
                "original-clippy-workflow-transport",
                str(roster),
            ],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(transport.returncode, 0, transport.stderr)
        self.assertTrue(transport.stdout.endswith(b"\0"))
        targets = [arg.decode("utf-8") for arg in transport.stdout[:-1].split(b"\0")]
        with wrapper.windows_target_patterns(
            ["bazel", "build", "--config=clippy", "--", *targets],
            {"RUNNER_OS": "Windows"},
        ) as (_, pattern_file):
            self.assertIsNotNone(pattern_file)
            self.assertEqual(
                pattern_file.read_bytes(),
                "".join(f"{label}\n" for label in compatible).encode("utf-8"),
            )

    def test_ci_roles_reuse_the_existing_build_configuration(self) -> None:
        for runner in ("Windows", "Linux", "macOS"):
            for keyed in (False, True):
                with self.subTest(runner=runner, keyed=keyed):
                    compatible = NATIVE_MANUAL | {UNIT}
                    if runner != "Windows":
                        compatible.add(UNIX)
                    self.write_records(compatible)
                    result, calls = self.run_selector(runner=runner, keyed=keyed)
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                    self.assertEqual(set(result.stdout.splitlines()[2:]), compatible)
                    call = calls[-1]
                    self.assertIn("cquery", call)
                    self.assertIn("--config=clippy", call)
                    self.assertIn("--repo_contents_cache=job scoped cache", call)
                    if runner == "Windows":
                        self.assertIn("--config=ci-windows", call)
                        self.assertIn("--platforms=//:windows_x86_64_msvc", call)
                        self.assertIn("--host_platform=//:local_windows_msvc", call)
                    elif runner == "macOS":
                        self.assertIn("--config=ci-macos", call)
                    elif keyed:
                        self.assertIn("--config=ci-linux", call)
                    else:
                        self.assertNotIn("--config=ci-linux", call)
                    if keyed:
                        suffix = "-rbe" if runner != "Windows" else ""
                        self.assertIn(f"--config=buildbuddy-generic{suffix}", call)
                    expression = call[-1]
                    self.assertTrue(
                        expression.startswith(
                            'config(kind("rust_test rule", attr(tags, "manual", '
                        )
                    )
                    self.assertTrue(expression.endswith(", target)"))
                    self.assertFalse(any("skip_incompatible" in arg for arg in call))

    def test_local_default_keeps_the_local_build_platform(self) -> None:
        self.write_records(NATIVE_MANUAL | {UNIT, UNIX})
        result, calls = self.run_selector(runner=None)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(
            any(
                arg.startswith(("--config=ci-", "--platforms=", "--host_platform="))
                for arg in calls[-1]
            )
        )

    def test_query_failure_preserves_exit_and_emits_no_partial_roster(self) -> None:
        self.write_records({UNIT})
        self.env["CLIPPY_DISCOVERY_FAIL"] = "1"
        result, _ = self.run_selector()
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("recorded query diagnostic before failure", result.stderr)

    def test_invalid_records_fail_without_partial_stdout(self) -> None:
        records = [
            "",
            "compatible\t//codex-rs/x:a\nunknown\t//codex-rs/x:b\n",
            "compatible\t//codex-rs/x:a\ncompatible\t//codex-rs/x:a\n",
            "compatible\t@foreign//codex-rs/x:a\n",
            "compatible\t//codex-rs/v8-poc:x\n",
            "incompatible\t//codex-rs/x:a\n",
            "compatible\t//other/x:a\n",
            "compatible\t//codex-rs/x:space here\n",
        ]
        for record in records:
            with self.subTest(record=record):
                self.records.write_text(record, encoding="utf-8")
                result, _ = self.run_selector()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")

    def test_provider_status_drives_selection_without_name_heuristics(self) -> None:
        self.records.write_text(
            "compatible\t//codex-rs/discovery-probe:still-test-bin\n"
            "compatible\t//codex-rs/discovery-probe:still-windows-cross-bin\n"
            "incompatible\t//codex-rs/discovery-probe:innocent-unit-tests-bin\n",
            encoding="utf-8",
        )
        result, _ = self.run_selector()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            set(result.stdout.splitlines()[2:]),
            {
                "//codex-rs/discovery-probe:still-test-bin",
                "//codex-rs/discovery-probe:still-windows-cross-bin",
            },
        )

    def test_canonical_main_labels_and_crlf_records(self) -> None:
        self.records.write_bytes(
            b"compatible\t@@//codex-rs/discovery-probe:unit-tests-bin\r\n"
        )
        result, _ = self.run_selector()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines()[2:],
            ["//codex-rs/discovery-probe:unit-tests-bin"],
        )

    def test_unknown_runner_and_non_windows_cross_intent_fail_before_query(
        self,
    ) -> None:
        self.write_records({UNIT})
        for runner, args in (
            ("unknown", ()),
            ("Linux", ("--windows-cross-compile",)),
            (None, ("--windows-cross-compile",)),
        ):
            with self.subTest(runner=runner, args=args):
                result, calls = self.run_selector(*args, runner=runner)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(calls, [])

    def test_machine_output_mode_rejects_a_build_command(self) -> None:
        result = subprocess.run(
            [
                self.bash,
                str(SCRIPTS / "run-bazel-ci.sh"),
                "--configured-query",
                "--",
                "build",
                "--",
                "//codex-rs/discovery-probe:target",
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
