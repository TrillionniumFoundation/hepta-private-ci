"""Reject malformed native10 receipts without running or importing native owners."""

import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

MODULE = (
    Path(__file__).resolve().parents[2]
    / ".github/scripts/hepta_windows_command_native_contract_v1.py"
)
SPEC = importlib.util.spec_from_file_location("native10_contract", MODULE)
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


class NoDoctype(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError("doctype")


class NativeReceiptControls(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.target = Path(self.directory.name).resolve()
        self.binary = self.target / "command-runner.exe"
        pe = bytearray(134)
        pe[:2], pe[60:64], pe[128:134] = (
            b"MZ",
            (128).to_bytes(4, "little"),
            b"PE\0\0\x64\x86",
        )
        self.binary.write_bytes(pe)
        self.suite = {
            "binary-id": CONTRACT.BINARY,
            "binary-name": "codex-command-runner",
            "package-name": "codex-windows-sandbox",
            "kind": "bin",
            "status": "listed",
            "build-platform": "target",
            "binary-path": str(self.binary),
            "testcases": {
                name: {"ignored": False, "filter-match": {"status": "matches"}}
                for name in CONTRACT.NAMES
            },
        }
        self.value = {"rust-suites": {CONTRACT.BINARY: self.suite}}

    def transcript(self):
        rows = ["Starting 10 tests across 1 binary"]
        rows.extend(
            "PASS [0.001s] (1/10) " + CONTRACT.BINARY + " " + name
            for name in CONTRACT.NAMES
        )
        rows.append("Summary [0.010s] 10 tests run: 10 passed")
        return "\n".join(rows).encode()

    def xml(self):
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite")
        for name in CONTRACT.NAMES:
            ET.SubElement(suite, "testcase", classname=CONTRACT.BINARY, name=name)
        return root

    def test_accepts_exact_discovered_native_binary_and_selected_names(self):
        actual = CONTRACT.listing(self.value, self.target)
        self.assertEqual(actual["selected"], list(CONTRACT.NAMES))
        self.assertEqual(actual["unselected"], 0)

    def test_rejects_wrong_binary_identity(self):
        self.suite["kind"] = "lib"
        with self.assertRaisesRegex(ValueError, "^binary-identity$"):
            CONTRACT.listing(self.value, self.target)

    def test_rejects_missing_selected_case(self):
        del self.suite["testcases"][CONTRACT.NAMES[0]]
        with self.assertRaisesRegex(ValueError, "^selected-roster-or-ignored$"):
            CONTRACT.listing(self.value, self.target)

    def test_rejects_ignored_selected_case(self):
        self.suite["testcases"][CONTRACT.NAMES[0]]["ignored"] = True
        with self.assertRaisesRegex(ValueError, "^selected-roster-or-ignored$"):
            CONTRACT.listing(self.value, self.target)

    def test_rejects_extra_selected_case(self):
        self.suite["testcases"]["foreign"] = {
            "ignored": False,
            "filter-match": {"status": "matches"},
        }
        with self.assertRaisesRegex(ValueError, "^selected-roster-or-ignored$"):
            CONTRACT.listing(self.value, self.target)

    def test_rejects_arm_binary_as_native_x86(self):
        raw = bytearray(self.binary.read_bytes())
        raw[132:134] = b"\x64\xaa"
        self.binary.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "^native-x86-64-binary$"):
            CONTRACT.listing(self.value, self.target)

    def test_accepts_ten_passes_with_separate_unselected_count(self):
        raw = self.transcript() + b", 2 skipped"
        self.assertEqual(
            CONTRACT.transcript(raw, 2),
            {"passed": 10, "failed": 0, "selected_skips": 0, "unselected": 2},
        )
        for slow in (1, 10):
            with self.subTest(slow=slow):
                observed = raw.replace(
                    b"10 passed", f"10 passed ({slow} slow)".encode()
                )
                self.assertEqual(
                    CONTRACT.transcript(observed, 2),
                    {"passed": 10, "failed": 0, "selected_skips": 0, "unselected": 2},
                )

    def test_rejects_duplicate_terminal_or_retry(self):
        raw = self.transcript() + b"\n" + self.transcript().splitlines()[1]
        with self.assertRaisesRegex(
            ValueError, "^terminal-roster-status-or-duplicate$"
        ):
            CONTRACT.transcript(raw, 0)

    def test_rejects_leak_despite_passed_summary(self):
        raw = self.transcript().replace(b"PASS ", b"LEAK ", 1)
        with self.assertRaisesRegex(
            ValueError, "^terminal-roster-status-or-duplicate$"
        ):
            CONTRACT.transcript(raw, 0)

    def test_rejects_unreported_skip_count(self):
        with self.assertRaisesRegex(ValueError, "^summary-counts$"):
            CONTRACT.transcript(self.transcript(), 1)
        for annotation in (
            b" (0 slow)",
            b" (11 slow)",
            b" (-1 slow)",
            b" (01 slow)",
            b" (1 flaky)",
            b" (1 leaky)",
            b" (1 slow, 1 flaky)",
            b" (1 slow, 1 leaky)",
            b" (1 skipped)",
            b" (1 retry)",
            " (1０ slow)".encode("utf-8"),
        ):
            with self.subTest(annotation=annotation):
                observed = self.transcript().replace(
                    b"10 passed", b"10 passed" + annotation
                )
                with self.assertRaisesRegex(ValueError, "^summary-counts$"):
                    CONTRACT.transcript(observed, 0)

    def test_accepts_exact_ten_xml_cases(self):
        self.assertEqual(
            CONTRACT.exact_xml(ET.tostring(self.xml()), NoDoctype),
            {
                "total": 10,
                "passed": 10,
                "skipped": 0,
                "native_qualification_only": True,
            },
        )

    def test_rejects_wrong_xml_identity_skip_retry_and_duplicate(self):
        for mutation, reason in (
            ("foreign", "xml-roster-or-duplicate"),
            ("duplicate", "xml-roster-or-duplicate"),
            ("skipped", "xml-nonpass-or-retry"),
            ("flakyFailure", "xml-nonpass-or-retry"),
        ):
            with self.subTest(mutation=mutation):
                root = self.xml()
                first = next(root.iter("testcase"))
                if mutation == "foreign":
                    first.set("classname", "foreign")
                elif mutation == "duplicate":
                    root[0].append(copy.deepcopy(first))
                else:
                    ET.SubElement(first, mutation)
                with self.assertRaisesRegex(ValueError, "^" + reason + "$"):
                    CONTRACT.exact_xml(ET.tostring(root), NoDoctype)


if __name__ == "__main__":
    unittest.main()
