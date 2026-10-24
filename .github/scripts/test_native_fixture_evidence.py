"""Synthetic evidence-validator controls, never native qualification tests."""

import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import native_fixture_evidence as evidence
from native_fixture_evidence import EXPECTED, validate_report


class ReportValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = ET.Element(
            "testsuites", name="native-fixtures", tests="2", failures="0", errors="0"
        )
        for binary, name in sorted(EXPECTED):
            suite = ET.SubElement(
                self.root,
                "testsuite",
                name=binary,
                tests="1",
                failures="0",
                errors="0",
                disabled="0",
            )
            ET.SubElement(
                suite,
                "testcase",
                name=name,
                classname=binary,
                timestamp="2026-10-24T00:00:00Z",
            )

    def check(self, root):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xml"
            ET.ElementTree(root).write(path)
            return validate_report(path)

    def test_absent_root_skipped_attribute_is_valid(self):
        self.assertEqual(set(self.check(self.root)), EXPECTED)

    def test_zero_missing_duplicate_or_unexpected_is_refused(self):
        for mutation in ("zero", "missing", "duplicate", "unexpected"):
            with self.subTest(mutation=mutation):
                root = copy.deepcopy(self.root)
                first, second = root.findall("testsuite/testcase")
                if mutation == "zero":
                    root.clear()
                elif mutation == "missing":
                    root.remove(root.findall("testsuite")[1])
                elif mutation == "duplicate":
                    second.attrib.update(first.attrib)
                else:
                    first.set("name", "another_test")
                with self.assertRaises(ValueError):
                    self.check(root)

    def test_failure_skip_retry_and_unknown_child_are_refused(self):
        for tag in (
            "failure",
            "error",
            "skipped",
            "flakyFailure",
            "flakyError",
            "rerunFailure",
            "rerunError",
            "unknown",
        ):
            with self.subTest(tag=tag):
                root = copy.deepcopy(self.root)
                ET.SubElement(root.find("testsuite/testcase"), tag)
                with self.assertRaises(ValueError):
                    self.check(root)

    def test_missing_counters_and_unexpected_nested_results_are_refused(self):
        for key in ("tests", "failures", "errors"):
            root = copy.deepcopy(self.root)
            del root.attrib[key]
            with self.assertRaises(ValueError):
                self.check(root)
        for node in (".", "testsuite"):
            root = copy.deepcopy(self.root)
            ET.SubElement(root.find(node), "unexpected")
            with self.assertRaises(ValueError):
                self.check(root)

    def test_count_identity_and_execution_tampering_is_refused(self):
        for attribute, value in (
            ("tests", "0"),
            ("failures", "1"),
            ("errors", "1"),
            ("skipped", "1"),
            ("disabled", "1"),
        ):
            with self.subTest(attribute=attribute):
                root = copy.deepcopy(self.root)
                root.set(attribute, value)
                with self.assertRaises(ValueError):
                    self.check(root)
        for node, attribute in (
            ("testsuite", "name"),
            ("testsuite/testcase", "timestamp"),
        ):
            root = copy.deepcopy(self.root)
            del root.find(node).attrib[attribute]
            with self.assertRaises(ValueError):
                self.check(root)


class PatchEvidenceTests(unittest.TestCase):
    def test_bind_preserves_final_blank_context_line_and_replay(self):
        config = (
            Path(__file__).resolve().parents[2] / "codex-rs/.config/nextest.toml"
        ).read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, out = root / "repo", root / "evidence"
            repo.mkdir()
            out.mkdir()

            def git(*args):
                return subprocess.check_output(
                    ["git", "-C", str(repo), *args], stderr=subprocess.PIPE
                )

            def commit(message):
                git("add", ".")
                git(
                    "-c",
                    "user.name=Evidence test",
                    "-c",
                    "user.email=evidence-test@example.invalid",
                    "commit",
                    "-qm",
                    message,
                )
                return git("rev-parse", "HEAD").decode().strip()

            git("init", "-q")
            for path in (
                "codex-rs/Cargo.lock",
                "justfile",
                "scripts/run-nextest.py",
                "scripts/just-shell.py",
                "codex-rs/rust-toolchain.toml",
            ):
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("unchanged support file\n")
            target = repo / "codex-rs/.config/nextest.toml"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(config)
            fixture = repo / "fixture.txt"
            fixture.write_bytes(b"before\n\n")
            base = commit("base")
            base_tree = git("rev-parse", "HEAD^{tree}").decode().strip()
            lock = git("rev-parse", "HEAD:codex-rs/Cargo.lock").decode().strip()
            fixture.write_bytes(b"after\n\n")
            head = commit("candidate")
            expected = git("diff", "--binary", "--full-index", base, head)
            self.assertTrue(expected.endswith(b" \n"))
            fixture_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
            with (
                contextlib.chdir(repo),
                patch.dict(os.environ, {"CANDIDATE_SHA": head}),
                patch.multiple(
                    evidence,
                    BASE=base,
                    BASE_TREE=base_tree,
                    LOCK=lock,
                    FIXTURES={"fixture.txt": fixture_hash},
                    CI_FILES=set(),
                ),
            ):
                evidence.bind(out)
            exported = out / "candidate.patch"
            self.assertEqual(exported.read_bytes(), expected)
            source = json.loads((out / "source.json").read_text())
            self.assertEqual(source["head"], head)
            self.assertEqual(source["base_tree"], base_tree)
            self.assertEqual(source["files"]["codex-rs/Cargo.lock"]["blob"], lock)
            self.assertEqual(source["files"]["fixture.txt"]["sha256"], fixture_hash)
            self.assertEqual(
                set(source["files"]),
                {
                    "fixture.txt",
                    "codex-rs/Cargo.lock",
                    "justfile",
                    "scripts/run-nextest.py",
                    "scripts/just-shell.py",
                    "codex-rs/rust-toolchain.toml",
                },
            )
            git("checkout", "-q", "--detach", base)
            git("apply", "--check", str(exported))
            git("apply", str(exported))
            self.assertEqual(fixture.read_bytes(), b"after\n\n")
            self.assertEqual(git("diff", "--binary", "--full-index"), expected)


if __name__ == "__main__":
    unittest.main()
