"""Exercise the workflow collector with native Windows wrapper result shapes."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/hepta-memory-lifecycle-windows-diagnostic.yml"
CASE = "local_lifecycle::tests::indeterminate_crash_window_replays_as_terminal_and_releases"


class MemoryLifecycleCollectorTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hepta-memory-collector-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.git("init", "-q")
        self.git("config", "user.name", "collector-test")
        self.git("config", "user.email", "collector-test@example.invalid")
        self.source = self.root / "source.rs"
        self.source.write_bytes(b"// original source\n")
        self.git("add", "source.rs")
        self.git("commit", "-qm", "source")
        self.output = self.root / "evidence"
        self.output.mkdir()
        self.base = self.root / "bazel"
        self.target = (
            self.base
            / "execroot/_main/bazel-out/windows_x86_64_msvc-fastbuild/testlogs"
            / "codex-rs/ext/hepta-memory/hepta-memory-unit-tests"
        )
        self.target.mkdir(parents=True)
        self.wrapper = (
            f"\nrunning 1 test\ntest {CASE} ... ok\n\n"
            "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; "
            "99 filtered out; finished in 0.10s\n\n"
        ).encode()
        self.primary = (
            b"Executing tests from the native Windows target\n" + self.wrapper
        )
        (self.target / "test.log").write_bytes(self.primary)
        (self.target / "test.xml.log").write_bytes(self.wrapper)
        self.write_xml()
        (self.output / "identity.json").write_text(
            json.dumps(
                {
                    "expected_source_sha": self.git("rev-parse", "HEAD"),
                    "source_files": [
                        {
                            "path": "source.rs",
                            "sha256": hashlib.sha256(
                                self.source.read_bytes()
                            ).hexdigest(),
                        }
                    ],
                }
            )
        )
        self.write_execution()

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.root, text=True, stderr=subprocess.PIPE
        ).strip()

    def write_xml(self, count=1, child=""):
        (self.target / "test.xml").write_text(
            f'<testsuites><testsuite tests="{count}" failures="0" errors="0">'
            + f'<testcase name="windows-wrapper">{child}</testcase>' * count
            + "<system-out>"
            + escape(self.primary.decode())
            + "</system-out></testsuite></testsuites>"
        )

    def write_execution(self, bazel=0, tee=0):
        (self.output / "execution-result.json").write_text(
            json.dumps({"bazel_exit_code": bazel, "tee_exit_code": tee})
        )

    def collect(self):
        block = WORKFLOW.read_text().split(
            "      - name: Preserve raw results and require exactly one original test\n",
            1,
        )[1]
        code = block.split("          python - <<'PY'\n", 1)[1].split(
            "\n          PY\n", 1
        )[0]
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(code)],
            cwd=self.root,
            env={
                **os.environ,
                "EVIDENCE_DIR": str(self.output),
                "BAZEL_OUTPUT_BASE": str(self.base),
                "MEMORY_CASE": CASE,
            },
            capture_output=True,
            text=True,
            timeout=15,
        )
        report = json.loads((self.output / "diagnostic-result.json").read_text())
        return result, report

    def test_native_wrapper_copy_is_retained_without_counting_a_second_run(self):
        result, report = self.collect()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(report["executed_cases"], [CASE])
        self.assertTrue(report["wrapper_output_copy"]["matches_primary_suffix"])
        copies = list((self.output / "raw").rglob("test.xml.log"))
        self.assertEqual([path.read_bytes() for path in copies], [self.wrapper])

    def test_original_single_log_shape_still_passes(self):
        (self.target / "test.xml.log").unlink()
        result, report = self.collect()
        self.assertEqual(result.returncode, 0, report)

    def test_altered_or_empty_wrapper_copy_is_rejected(self):
        for contents in (b"different execution\n", b""):
            with self.subTest(contents=contents):
                (self.target / "test.xml.log").write_bytes(contents)
                result, report = self.collect()
                self.assertNotEqual(result.returncode, 0, report)

    def test_additional_or_retried_log_is_rejected(self):
        for name in ("extra.log", "attempt_2/test.log", "attempt_2/test.xml.log"):
            with self.subTest(name=name):
                path = self.target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(self.primary)
                result, report = self.collect()
                self.assertNotEqual(result.returncode, 0, report)
                path.unlink()

    def test_missing_primary_or_xml_is_rejected(self):
        for name in ("test.log", "test.xml"):
            with self.subTest(name=name):
                path = self.target / name
                original = path.read_bytes()
                path.unlink()
                result, report = self.collect()
                self.assertNotEqual(result.returncode, 0, report)
                path.write_bytes(original)

    def test_duplicate_native_cases_are_rejected(self):
        self.write_xml(count=2)
        result, report = self.collect()
        self.assertNotEqual(result.returncode, 0, report)

    def test_failed_or_skipped_native_case_is_rejected(self):
        for child in ("<failure/>", "<error/>", "<skipped/>"):
            with self.subTest(child=child):
                self.write_xml(child=child)
                result, report = self.collect()
                self.assertNotEqual(result.returncode, 0, report)

    def test_failed_invocation_or_incomplete_log_capture_is_rejected(self):
        for bazel, tee in ((1, 0), (0, 1)):
            with self.subTest(bazel=bazel, tee=tee):
                self.write_execution(bazel, tee)
                result, report = self.collect()
                self.assertNotEqual(result.returncode, 0, report)

    def test_changed_source_is_rejected(self):
        self.source.write_bytes(b"// changed source\n")
        result, report = self.collect()
        self.assertNotEqual(result.returncode, 0, report)


if __name__ == "__main__":
    unittest.main()
