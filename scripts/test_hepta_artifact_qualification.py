"""Evidence adversaries: missing execution, substituted identities and stale bytes fail."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

import hepta_artifact_qualification as q
from hepta_artifact_qualification import (
    FAMILIES, GATES, PACKAGE, canonical, execution_evidence, gate_success,
    run_gate, source_binding,
)


def fixtures():
    names = [f"{family}::tests::case" for family in FAMILIES]
    inventory = {"test-count": len(names), "rust-suites": {
        PACKAGE: {"package-name": PACKAGE, "status": "listed",
                  "testcases": {name: {"ignored": False} for name in names}}
    }}
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", {"name": PACKAGE, "tests": str(len(names))})
    for name in names:
        ET.SubElement(suite, "testcase", {"name": name, "classname": PACKAGE})
    return inventory, root


def git(root, *args, input=None):
    return subprocess.check_output(["git", *args], cwd=root, input=input,
                                   text=True, stderr=subprocess.DEVNULL).strip()


def repo_fixture(root):
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    for path in q.SEALED_PATHS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n")
    source_path = q.SOURCE_ROOT + "/src/lib.rs"
    target = root / source_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("pub fn sample() {}\n")
    git(root, "add", ".")
    tree = git(root, "write-tree")
    blob = git(root, "rev-parse", f"{tree}:{source_path}")
    subtree = git(root, "rev-parse", f"{tree}:{q.SOURCE_ROOT}")
    mapping = {"module": "learning.artifacts", "sourceObjects": [
        {"path": q.SOURCE_ROOT, "object": subtree},
        {"path": source_path, "object": blob}], "operations": [
        {"operation": "sample", "nativeSymbol": "sample", "sourcePath": source_path,
         "sourceBlob": blob, "tests": []}]}
    (root / q.MAP).write_bytes(canonical(mapping))
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    base = git(root, "rev-parse", "HEAD")
    git(root, "commit", "--allow-empty", "-qm", "source")
    return base, git(root, "rev-parse", "HEAD")


class EvidenceTests(unittest.TestCase):
    def test_complete_execution(self):
        inventory, root = fixtures()
        result = execution_evidence(inventory, ET.tostring(root))
        self.assertEqual(result["passed"], len(FAMILIES))
        self.assertEqual(set(result["families"]), set(FAMILIES))
        self.assertTrue(all(row["binaryId"] == PACKAGE for row in result["testIdentities"]))

    def test_absent_duplicate_and_extra_cases(self):
        for mutation in ("remove", "duplicate", "extra"):
            with self.subTest(mutation=mutation):
                inventory, root = fixtures()
                suite = root[0]
                if mutation == "remove":
                    suite.remove(suite[0])
                elif mutation == "duplicate":
                    suite.append(copy.deepcopy(suite[0]))
                else:
                    ET.SubElement(suite, "testcase", {"name": "forged", "classname": PACKAGE})
                with self.assertRaises(ValueError):
                    execution_evidence(inventory, ET.tostring(root))

    def test_nonpass_outcomes(self):
        for tag in ("failure", "error", "skipped", "flakyFailure", "rerunFailure", "unknown"):
            with self.subTest(tag=tag):
                inventory, root = fixtures()
                ET.SubElement(root[0][0], tag)
                with self.assertRaises(ValueError):
                    execution_evidence(inventory, ET.tostring(root))

    def test_missing_family_even_when_inventory_matches(self):
        inventory, root = fixtures()
        del inventory["rust-suites"][PACKAGE]["testcases"][root[0][0].get("name")]
        inventory["test-count"] -= 1
        root[0].remove(root[0][0])
        root[0].set("tests", str(inventory["test-count"]))
        with self.assertRaises(ValueError):
            execution_evidence(inventory, ET.tostring(root))

    def test_empty_wrong_package_unlisted_count_drift(self):
        for mutation in ("empty", "package", "unlisted", "count", "boolean"):
            with self.subTest(mutation=mutation):
                inventory, root = fixtures()
                suite = inventory["rust-suites"][PACKAGE]
                if mutation == "empty":
                    suite["testcases"] = {}
                    inventory["test-count"] = 0
                elif mutation == "package":
                    suite["package-name"] = "another-crate"
                elif mutation == "unlisted":
                    suite["status"] = "skipped"
                elif mutation == "boolean":
                    inventory["test-count"] = True
                else:
                    inventory["test-count"] += 1
                with self.assertRaises(ValueError):
                    execution_evidence(inventory, ET.tostring(root))

    def test_reject_dtd_and_summary_failure(self):
        inventory, root = fixtures()
        for xml in (b'<!DOCTYPE testsuites><testsuites/>',
                    '<!DOCTYPE testsuites><testsuites/>'.encode('utf-16')):
            with self.assertRaises(ValueError):
                execution_evidence(inventory, xml)
        root[0].set("failures", "1")
        with self.assertRaises(ValueError):
            execution_evidence(inventory, ET.tostring(root))

    def test_gate_set_and_status_are_closed(self):
        good = {name: {"status": "completed", "exitCode": 0} for name in GATES}
        self.assertTrue(gate_success(good))
        for status, code in (("skipped", 0), ("not_started", 0), ("completed", 1), ("completed", False)):
            with self.subTest(status=status, code=code):
                bad = copy.deepcopy(good)
                bad["tests"] = {"status": status, "exitCode": code}
                self.assertFalse(gate_success(bad))
        bad = copy.deepcopy(good)
        del bad["build"]
        self.assertFalse(gate_success(bad))
        good["extra"] = {"status": "completed", "exitCode": 0}
        self.assertFalse(gate_success(good))

    def test_canonical_key_order(self):
        self.assertEqual(canonical({"b": 1, "a": 2}), canonical({"a": 2, "b": 1}))

    def test_gate_failure_does_not_prevent_next_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            failed = run_gate(root, root, "bad", [sys.executable, "-c", "raise SystemExit(7)"], 3)
            passed = run_gate(root, root, "good", [sys.executable, "-c", "print('executed')"], 3)
            self.assertEqual((failed["exitCode"], passed["exitCode"]), (7, 0))
            self.assertEqual((root / "good.stdout").read_text(), "executed\n")

    def test_timeout_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_gate(root, root, "timeout", [sys.executable, "-c", "import time; time.sleep(20)"], 1)
            self.assertEqual((result["status"], result["exitCode"]), ("timed_out", 124))

    def test_existing_gate_output_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test.stdout").write_text("old")
            with self.assertRaises(FileExistsError):
                run_gate(root, root, "test", [sys.executable, "-c", "pass"], 3)

    def test_source_identity_and_seals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, source = repo_fixture(root)
            value = source_binding(root, source, base, "exact-head")
            self.assertEqual(value["testedCommit"], source)
            for wrong_source, wrong_lane in ((base, "exact-head"), (source, "synthetic-merge")):
                with self.assertRaises(ValueError):
                    source_binding(root, wrong_source, base, wrong_lane)
            (root / "justfile").write_text("dirty")
            with self.assertRaises(ValueError):
                source_binding(root, source, base, "exact-head")

    def test_suite_and_classname_substitution(self):
        for field in ("suite", "class", "missing-class"):
            inventory, root = fixtures()
            if field == "suite":
                root[0].set("name", PACKAGE + "::different")
            elif field == "class":
                root[0][0].set("classname", "attacker")
            else:
                del root[0][0].attrib["classname"]
            with self.subTest(field=field), self.assertRaises(ValueError):
                execution_evidence(inventory, ET.tostring(root))

    def test_cross_binary_test_substitution_preserving_global_names(self):
        inventory, root = fixtures()
        second = PACKAGE + "::integration"
        inventory["rust-suites"][second] = {"package-name": PACKAGE, "status": "listed",
                                          "testcases": {"integration_case": {"ignored": False}}}
        inventory["test-count"] += 1
        suite = ET.SubElement(root, "testsuite", {"name": second, "tests": "1"})
        ET.SubElement(suite, "testcase", {"name": "integration_case", "classname": second})
        execution_evidence(inventory, ET.tostring(root))
        old = root[0][0].get("name")
        root[0][0].set("name", "integration_case")
        suite[0].set("name", old)
        with self.assertRaises(ValueError):
            execution_evidence(inventory, ET.tostring(root))

    def test_duplicate_junit_suite(self):
        inventory, root = fixtures()
        root.append(copy.deepcopy(root[0]))
        with self.assertRaises(ValueError):
            execution_evidence(inventory, ET.tostring(root))

    def test_summary_count_mismatch(self):
        inventory, root = fixtures()
        root.set("tests", "0")
        with self.assertRaises(ValueError):
            execution_evidence(inventory, ET.tostring(root))

    def test_hidden_testcase(self):
        inventory, root = fixtures()
        metadata = ET.SubElement(root[0], "properties")
        metadata.append(copy.deepcopy(root[0][0]))
        with self.assertRaises(ValueError):
            execution_evidence(inventory, ET.tostring(root))

    def test_duplicate_json_keys_and_nonfinite_values(self):
        for data in ('{"qualified":false,"qualified":true}', '{"value":NaN}', '{"x":Infinity}'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                q.strict_json(data)

    def test_untracked_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, source = repo_fixture(root)
            (root / "injected.rs").write_text("untracked")
            with self.assertRaises(ValueError):
                source_binding(root, source, base, "exact-head")

    def test_merge_tree_must_match_not_just_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, source = repo_fixture(root)
            tree = git(root, "rev-parse", "HEAD^{tree}")
            candidate = git(root, "commit-tree", tree, "-p", base, "-p", source, input="valid merge\n")
            git(root, "checkout", "--detach", candidate)
            source_binding(root, source, base, "synthetic-merge")
            (root / "justfile").write_text("injected into a fake merge")
            git(root, "add", ".")
            changed = git(root, "write-tree")
            forged = git(root, "commit-tree", changed, "-p", base, "-p", source, input="fake merge\n")
            git(root, "reset", "--hard", forged)
            with self.assertRaises(ValueError):
                source_binding(root, source, base, "synthetic-merge")

    def test_empty_source_map_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, _ = repo_fixture(root)
            (root / q.MAP).write_text('{"module":"learning.artifacts","operations":[],"sourceObjects":[]}')
            git(root, "add", ".")
            git(root, "commit", "-qm", "unseal")
            with self.assertRaises(ValueError):
                source_binding(root, git(root, "rev-parse", "HEAD"), base, "exact-head")

    def test_trace_cannot_borrow_another_module_or_binary(self):
        mapping = {"operations": [{"operation": "append", "nativeSymbol": "append",
                    "sourcePath": q.SOURCE_ROOT + "/src/registry.rs", "sourceBlob": "a" * 40,
                    "tests": [q.SOURCE_ROOT + "/src/registry_tests.rs::same_name"]}]}
        for binary, name in ((PACKAGE, "storage::tests::same_name"),
                             (PACKAGE + "::other", "registry::tests::same_name")):
            trace = q.traceability(mapping, {"testIdentities": [{"binaryId": binary, "testName": name}]})
            self.assertEqual(trace[0]["mappingStatus"], "unmapped_or_not_executed")
        trace = q.traceability(mapping, {"testIdentities": [{"binaryId": PACKAGE, "testName": "registry::tests::same_name"}]})
        self.assertEqual(trace[0]["mappingStatus"], "declared_tests_executed")

    def test_stale_map_does_not_skip_gates_or_emit_success(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as evidence:
            root, out = Path(tmp), Path(evidence) / "result"
            base, _ = repo_fixture(root)
            mapping = json.loads((root / q.MAP).read_text())
            mapping["sourceObjects"][0]["object"] = "f" * 40
            (root / q.MAP).write_bytes(canonical(mapping))
            git(root, "add", ".")
            git(root, "commit", "-qm", "stale map")
            source = git(root, "rev-parse", "HEAD")
            visited = []
            def failed_gate(root, out, name, argv, timeout):
                visited.append(name)
                for suffix in ("stdout", "stderr"):
                    (out / f"{name}.{suffix}").write_text("not executed: fixture")
                return {"status": "not_started", "exitCode": 127}
            with mock.patch.object(q, "run_gate", failed_gate):
                self.assertEqual(q.qualify(root, out, source, base, "exact-head"), 1)
            self.assertEqual(visited, list(GATES))
            receipt = json.loads((out / "qualification.json").read_text())
            self.assertFalse(receipt["qualified"])
            self.assertFalse(receipt["completion"]["moduleComplete"])
            self.assertTrue(any("stale" in error for error in receipt["errors"]))

    def test_bundle_integrity_and_external_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            inventory, xml = fixtures()
            (out / "junit.xml").write_bytes(ET.tostring(xml))
            gates = {}
            for name in GATES:
                (out / f"{name}.stdout").write_bytes(canonical(inventory) if name == "inventory" else b"fixture\n")
                (out / f"{name}.stderr").write_bytes(b"")
                gates[name] = {"status": "completed", "exitCode": 0,
                               "stdoutSha256": q.digest(out / f"{name}.stdout"),
                               "stderrSha256": q.digest(out / f"{name}.stderr")}
            expected = {"sourceCommit": "1" * 40, "baseCommit": "2" * 40,
                        "testedCommit": "1" * 40, "testedTree": "3" * 40, "lane": "exact-head",
                        "sourceObjects": {q.SOURCE_ROOT: "4" * 40},
                        "runner": {key: "fixture" for key in q.RUNNER_KEYS}}
            receipt = {"schema": "hepta.learning-artifacts.qualification.v2", **expected,
                       "qualified": True, "errors": [], "gates": gates,
                       "execution": execution_evidence(inventory, ET.tostring(xml)),
                       "completion": {"nativeCandidateQualified": True, "moduleComplete": False},
                       "claimBoundary": {key: False for key in ("productionImplementation", "productExecutionProved", "independentAcceptance", "activation", "release")}}
            def save(value):
                data = canonical(value)
                (out / "qualification.json").write_bytes(data)
                (out / "qualification.sha256").write_text(hashlib.sha256(data).hexdigest() + "\n")
            save(receipt)
            self.assertTrue(q.verify_bundle(out, expected)["qualified"])
            wrong = copy.deepcopy(expected)
            wrong["sourceCommit"] = "9" * 40
            with self.assertRaises(ValueError):
                q.verify_bundle(out, wrong)
            forged = copy.deepcopy(receipt)
            forged["claimBoundary"]["activation"] = True
            save(forged)
            with self.assertRaises(ValueError):
                q.verify_bundle(out, expected)
            save(receipt)
            (out / "tests.stdout").write_text("replaced")
            with self.assertRaises(ValueError):
                q.verify_bundle(out, expected)

    def test_missing_workflow_identity_is_not_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                q.verify_bundle(Path(tmp), {})

    def test_output_limit_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(q, "MAX_OUTPUT", 8192):
            root = Path(tmp)
            value = run_gate(root, root, "limit", [sys.executable, "-c", "import sys; sys.stdout.write('x'*100000); sys.stdout.flush()"], 3)
            self.assertEqual((value["status"], value["exitCode"]), ("output_limit", 125))
            self.assertLessEqual((root / "limit.stdout").stat().st_size + (root / "limit.stderr").stat().st_size, 8192)


if __name__ == "__main__":
    unittest.main()
