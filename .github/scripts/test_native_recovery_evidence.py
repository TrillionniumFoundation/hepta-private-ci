"""Synthetic evidence controls; none of these tests qualify native Rust behavior."""

import contextlib
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import tomllib
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import native_recovery_evidence as evidence


def report(phase):
    expected = evidence.EXPECTED[phase]
    root = ET.Element("testsuites", name="native-recovery", tests=str(len(expected)), failures="0", errors="0")
    for classname in sorted({name for name, _ in expected}):
        names = sorted(name for group, name in expected if group == classname)
        suite = ET.SubElement(root, "testsuite", name=classname, tests=str(len(names)), failures="0", errors="0")
        for name in names:
            ET.SubElement(suite, "testcase", classname=classname, name=name, timestamp="2026-10-24T21:00:00Z")
    return root


class ReportTests(unittest.TestCase):
    def check(self, root, phase):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "junit.xml"
            ET.ElementTree(root).write(path)
            return evidence.validate_report(path, phase)

    def test_exact_five_and_three_reports(self):
        for phase in evidence.EXPECTED:
            self.assertEqual(set(self.check(report(phase), phase)), evidence.EXPECTED[phase])

    def test_missing_duplicate_identity_counts_and_result_tampering(self):
        for phase in evidence.EXPECTED:
            for target, key, value in (
                (".", "name", "native-fixtures"), (".", "tests", "0"),
                (".", "errors", "1"), (".", "failures", "1"), (".", "skipped", "1"),
                ("testsuite", "name", "wrong-owner"), ("testsuite", "tests", "0"),
                ("testsuite", "disabled", "1"), ("testsuite", "errors", None),
                ("testsuite/testcase", "name", "wrong-test"),
                ("testsuite/testcase", "classname", "codex-hepta-memory::lib"),
                ("testsuite/testcase", "timestamp", None),
            ):
                with self.subTest(phase=phase, target=target, key=key):
                    root = report(phase)
                    node = root if target == "." else root.find(target)
                    node.attrib.pop(key, None) if value is None else node.set(key, value)
                    with self.assertRaises(ValueError): self.check(root, phase)
            for tag in ("failure", "error", "skipped", "rerunFailure", "flakyFailure", "unknown"):
                root = report(phase)
                ET.SubElement(root.find("testsuite/testcase"), tag)
                with self.assertRaises(ValueError): self.check(root, phase)
            for mutation in ("missing", "duplicate", "extra-suite", "unknown-suite-child"):
                root = report(phase)
                suite = root.find("testsuite")
                if mutation == "missing": suite.remove(suite[0])
                elif mutation == "duplicate": suite.append(copy.deepcopy(suite[0]))
                elif mutation == "extra-suite": root.append(copy.deepcopy(suite))
                else: ET.SubElement(suite, "system-out")
                with self.assertRaises(ValueError): self.check(root, phase)
        with self.assertRaises(ValueError): self.check(report("owning"), "integration")

    def test_new_profile_does_not_change_existing_profiles(self):
        path = Path(__file__).resolve().parents[2] / "codex-rs/.config/nextest.toml"
        text = path.read_text()
        old = text.split("\n# Isolated recovery qualification;", 1)[0].encode()
        self.assertEqual(evidence.common.hashlib.sha256(old).hexdigest(),
                         "0aeb77fbd48d31636e73c2759b13b45cd6259c48a08dc955f164361e585cc6b7")
        profile = tomllib.loads(text)["profile"]["native-recovery"]
        self.assertEqual((profile["inherits"], profile["retries"]), ("local", 0))
        self.assertEqual(profile["junit"], dict(path="junit.xml", **{
            "report-name": "native-recovery", "store-success-output": True,
            "store-failure-output": True, "report-skipped": "none",
        }))
        override = profile["overrides"][0]
        names = {f"test(={name})" for expected in evidence.EXPECTED.values() for _, name in expected}
        self.assertEqual(set(override["filter"].split(" | ")), names)
        self.assertEqual(override["junit"]["report-skipped"], "all")

    def test_missing_and_malformed_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "junit.xml"
            with self.assertRaises(FileNotFoundError): evidence.validate_report(path, "owning")
            path.write_text("<testsuites>")
            with self.assertRaises(ET.ParseError): evidence.validate_report(path, "owning")


class BindingTests(unittest.TestCase):
    def test_byte_exact_patch_source_drift_commands_and_failed_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, out = root / "repo", root / "evidence"
            repo.mkdir(); out.mkdir()
            def git(*args):
                return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE)
            def commit():
                git("add", ".")
                git("-c", "user.name=Evidence control", "-c", "user.email=test@example.invalid", "commit", "-qm", "control")
                return git("rev-parse", "HEAD").decode().strip()
            git("init", "-q")
            lock = repo / "codex-rs/Cargo.lock"; lock.parent.mkdir()
            lock.write_text("synthetic lock\n")
            (lock.parent / "rustfmt.toml").write_text('edition = "2024"\n')
            fixture = repo / "fixture.txt"; fixture.write_text("before\n\n")
            base = commit(); tree = git("rev-parse", "HEAD^{tree}").decode().strip()
            lock_hash = git("rev-parse", "HEAD:codex-rs/Cargo.lock").decode().strip()
            fixture.write_text("after\n\n"); head = commit()
            with contextlib.chdir(repo), patch.dict(os.environ, CANDIDATE_SHA=head, WORKFLOW_SHA=head), patch.multiple(
                evidence, BASE=base, BASE_TREE=tree, PINS={"fixture.txt": evidence.digest(fixture)},
                CI_FILES=set(), SUPPORT={"codex-rs/Cargo.lock", "codex-rs/rustfmt.toml"},
            ), patch.object(evidence.common, "LOCK", lock_hash):
                evidence.bind(out)
                self.assertIn("codex-rs/rustfmt.toml", json.loads((out / "source.json").read_text())["files"])
                raw = git("diff", "--binary", "--full-index", base, head)
                self.assertTrue(raw.endswith(b" \n"))
                self.assertEqual((out / "candidate.patch").read_bytes(), raw)
                (out / "tools.json").write_text(json.dumps({
                    "versions": evidence.TOOL_VERSIONS, "sha256": evidence.common.TOOL_HASHES,
                }))
                for phase in evidence.EXPECTED:
                    target = out / phase; target.mkdir()
                    ET.ElementTree(report(phase)).write(target / "junit.xml")
                    (target / "command.txt").write_text(evidence.shlex.join(evidence.command(phase)))
                    (target / "native-tests.log").write_text("synthetic log\n")
                    for name in ("test.exit", "tee.exit", "report-copy.exit"): (target / name).write_text("0\n")
                self.assertEqual(set(evidence.verify(out)), set(evidence.EXPECTED))
                for phase in evidence.EXPECTED:
                    for name in ("test.exit", "tee.exit", "report-copy.exit", "command.txt"):
                        path = out / phase / name; original = path.read_bytes(); path.write_text("100\n")
                        with self.assertRaises(ValueError): evidence.verify(out)
                        path.write_bytes(original)
                tools_path = out / "tools.json"; tools_bytes = tools_path.read_bytes()
                tools_path.write_text(json.dumps({"versions": {}, "sha256": {}}))
                with self.assertRaises(ValueError): evidence.verify(out)
                tools_path.write_bytes(tools_bytes)
                source_path = out / "source.json"; source_bytes = source_path.read_bytes()
                receipt = json.loads(source_bytes); receipt["files"] = {}
                source_path.write_text(json.dumps(receipt))
                with self.assertRaises(ValueError): evidence.verify(out)
                source_path.write_bytes(source_bytes)
                missing = out / "integration/report-copy.exit"; saved = missing.read_bytes(); missing.unlink()
                with self.assertRaises(FileNotFoundError): evidence.verify(out)
                missing.write_bytes(saved)
                fixture.write_text("drift\n")
                with self.assertRaises(ValueError): evidence.verify(out)
                git("checkout", "--", "fixture.txt")
                with patch.dict(os.environ, WORKFLOW_SHA="wrong"):
                    with self.assertRaises(ValueError): evidence.bind(out)
                with patch.dict(evidence.PINS, {"fixture.txt": "unreviewed"}):
                    with self.assertRaises(ValueError): evidence.bind(out)
                with patch.object(evidence, "CI_FILES", {"unexpected.py"}):
                    with self.assertRaises(ValueError): evidence.bind(out)
                git("checkout", "-q", "--detach", base)
                git("apply", "--check", str(out / "candidate.patch")); git("apply", str(out / "candidate.patch"))
                self.assertEqual(fixture.read_text(), "after\n\n")
                self.assertEqual(git("diff", "--binary", "--full-index"), raw)

    def test_actual_workflow_loop_keeps_first_report_when_second_compile_fails(self):
        scripts = Path(__file__).resolve().parent
        workflow = (scripts.parent / "workflows/hepta-native-recovery.yml").read_text()
        section = workflow.split("      - name: Five owning-lib and three original integration cases\n")[1]
        shell = textwrap.dedent(section.split("        run: |\n", 1)[1].split("      - name:", 1)[0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); out = root / "evidence"; out.mkdir()
            dest = root / ".github/scripts"; dest.mkdir(parents=True)
            for name in ("native_recovery_evidence.py", "native_fixture_evidence.py"): shutil.copyfile(scripts / name, dest / name)
            original = root / "first.xml"; ET.ElementTree(report("owning")).write(original)
            transient = root / "codex-rs/target/nextest/native-recovery/junit.xml"; transient.parent.mkdir(parents=True)
            binary = root / "bin"; binary.mkdir()
            just = binary / "just"
            just.write_text('#!/bin/sh\necho synthetic compile control\ncase " $* " in *" --lib "*) cp "$CONTROL_REPORT" "$CONTROL_NEXT_REPORT";; *) exit 100;; esac\n')
            just.chmod(0o700)
            env = dict(os.environ, GITHUB_WORKSPACE=str(root), EVIDENCE=str(out),
                       CONTROL_REPORT=str(original), CONTROL_NEXT_REPORT=str(transient), PATH=f"{binary}:{os.environ['PATH']}")
            result = subprocess.run(["bash", "-c", shell], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((out / "owning/junit.xml").read_bytes(), original.read_bytes())
            self.assertFalse((out / "integration/junit.xml").exists())
            self.assertEqual((out / "integration/test.exit").read_text(), "100\n")
            self.assertNotEqual((out / "integration/report-copy.exit").read_text(), "0\n")


if __name__ == "__main__":
    unittest.main()
