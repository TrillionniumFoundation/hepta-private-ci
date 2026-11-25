#!/usr/bin/env python3
"""Real Git identity and nextest-output regressions for the diagnostic runner."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).with_name("hepta-learning-artifacts-qualification.py")
SPEC = importlib.util.spec_from_file_location("learning_artifact_qualification", SOURCE)
assert SPEC is not None and SPEC.loader is not None
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


class CheckoutIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.patch = mock.patch.object(qualification, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.event_patch = mock.patch.dict(
            os.environ, {"GITHUB_EVENT_NAME": "pull_request"}
        )
        self.event_patch.start()
        self.addCleanup(self.event_patch.stop)
        self.git("init", "-q")
        self.git("config", "core.hooksPath", "/dev/null")
        self.git("config", "user.name", "Qualification fixture")
        self.git("config", "user.email", "fixture@invalid.example")
        (self.root / "payload.txt").write_text("base bytes\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Fixture base")
        self.base = self.git("rev-parse", "HEAD")
        (self.root / "source.txt").write_text("source bytes\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Fixture source")
        self.source = self.git("rev-parse", "HEAD")

    def git(self, *args: str) -> str:
        return subprocess.check_output(
            ["git", *args], cwd=self.root, text=True, stderr=subprocess.PIPE
        ).strip()

    def identity(self, lane: str = "source") -> dict:
        return qualification.materialize_candidate(self.source, self.base, lane)

    def test_source_checkout_identity_is_accepted(self) -> None:
        qualification.verify_checkout_identity(self.identity(), self.source)

    def test_another_commit_with_identical_tree_is_rejected(self) -> None:
        identity = self.identity()
        self.git("commit", "--allow-empty", "-qm", "Same tree, different commit")
        self.assertEqual(
            self.git("rev-parse", "HEAD^{tree}"), identity["candidateTree"]
        )
        with self.assertRaisesRegex(ValueError, "checkout commit"):
            qualification.verify_checkout_identity(identity, self.source)

    def test_dirty_tracked_source_is_rejected(self) -> None:
        identity = self.identity()
        (self.root / "payload.txt").write_text("changed bytes\n")
        with self.assertRaisesRegex(ValueError, "dirty tracked"):
            qualification.verify_checkout_identity(identity, self.source)

    def test_altered_parent_list_is_rejected(self) -> None:
        identity = self.identity()
        identity["parents"] = []
        with self.assertRaisesRegex(ValueError, "candidate parents"):
            qualification.verify_checkout_identity(identity, self.source)

    def test_source_tree_mismatch_is_rejected(self) -> None:
        identity = self.identity()
        identity["sourceTree"] = self.git("rev-parse", f"{self.base}^{{tree}}")
        with self.assertRaisesRegex(ValueError, "source tree"):
            qualification.verify_checkout_identity(identity, self.source)

    def test_ordered_merge_identity_is_accepted(self) -> None:
        identity = self.identity("merge")
        self.assertEqual(identity["parents"], [self.base, self.source])
        qualification.verify_checkout_identity(identity, self.source)

    def test_ordered_parents_do_not_authorize_a_different_merge_tree(self) -> None:
        identity = self.identity("merge")
        other_tree = self.git("rev-parse", f"{self.base}^{{tree}}")
        candidate = self.git(
            "commit-tree",
            other_tree,
            "-p",
            self.base,
            "-p",
            self.source,
            "-m",
            "Fixture with correct parents but wrong tree",
        )
        self.git("checkout", "--detach", candidate)
        identity.update(candidate=candidate, candidateTree=other_tree)
        with self.assertRaisesRegex(ValueError, "actual ordered merge"):
            qualification.verify_checkout_identity(identity, self.source)

    def test_changed_merge_parent_order_is_rejected(self) -> None:
        identity = self.identity("merge")
        identity["parents"] = [self.source, self.base]
        with self.assertRaisesRegex(ValueError, "candidate parents"):
            qualification.verify_checkout_identity(identity, self.source)

    def test_replace_refs_do_not_change_selected_git_identity(self) -> None:
        source_tree = self.git("rev-parse", "HEAD^{tree}")
        self.git("replace", self.source, self.base)
        identity = self.identity()
        self.assertEqual(identity["candidateTree"], source_tree)
        self.assertEqual(identity["sourceTree"], source_tree)
        qualification.verify_checkout_identity(identity, self.source)


class NextestOutputTests(unittest.TestCase):
    def test_counter_and_legacy_pass_lines_bind_the_same_test(self) -> None:
        legacy = "PASS [   0.032s] codex-app-server tests::completed\n"
        counter = "PASS [   0.032s] (   1/7539) codex-app-server tests::completed\n"
        expected = [{"binary": "codex-app-server", "function": "tests::completed"}]
        self.assertEqual(qualification.passed_tests(legacy), expected)
        self.assertEqual(qualification.passed_tests(counter), expected)
        self.assertEqual(qualification.passed_tests(legacy + counter), expected)

    def test_failed_skipped_and_malformed_lines_are_not_passes(self) -> None:
        text = (
            "FAIL [0.032s] (1/3) package tests::failed\n"
            "SKIP [0.032s] package tests::skipped\n"
            "PASS [0.032s] (unknown/3) package tests::unknown\n"
            "PASS [0.032s] package tests::one extra-token\n"
        )
        self.assertEqual(qualification.passed_tests(text), [])


class TraceabilityIdentityTests(unittest.TestCase):
    def test_declared_regression_requires_its_exact_binary_and_test_name(self) -> None:
        test_case = {
            "source": "codex-rs/hepta-learning-artifacts/src/storage_tests.rs",
            "function": "seals_receipt",
            "binaryId": qualification.CRATE,
            "testName": "storage::tests::seals_receipt",
        }
        declaration = {
            "cases": [
                {
                    "id": "ART-03",
                    "module": "learning.artifacts",
                    "tests": [test_case],
                }
            ]
        }
        rows = [
            {"binary": "different-binary", "function": test_case["testName"]},
            {"binary": qualification.CRATE, "function": "other::seals_receipt"},
        ]
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        trace = root / "qualification/lane-e/TEST_TRACEABILITY.json"
        trace.parent.mkdir(parents=True)
        trace.write_text(json.dumps(declaration))
        result = {"name": "owner-regression", "status": "passed", "passedTests": rows}
        with (
            mock.patch.object(qualification, "ROOT", root),
            mock.patch.object(qualification, "git", return_value="fixture-source-oid"),
        ):
            self.assertEqual(
                qualification.traceability([result])[0]["execution"], "unproven"
            )
            rows.append(
                {"binary": qualification.CRATE, "function": test_case["testName"]}
            )
            self.assertEqual(
                qualification.traceability([result])[0]["execution"], "passed"
            )


class QueueIdentityTests(unittest.TestCase):
    git = CheckoutIdentityTests.git

    def setUp(self) -> None:
        CheckoutIdentityTests.setUp(self)
        self.head_ref = "refs/heads/gh-readonly-queue/main/fixture"
        self.base_ref = "refs/heads/main"
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.queue = self.git(
            "commit-tree",
            tree,
            "-p",
            self.base,
            "-p",
            self.source,
            "-m",
            "Queue fixture",
        )
        self.git("update-ref", self.head_ref, self.queue)
        self.git("update-ref", self.base_ref, self.base)
        self.git("checkout", "--detach", self.queue)
        self.event_path = self.root / "queue-event.json"
        self.event = {
            "action": "checks_requested",
            "merge_group": {
                "head_sha": self.queue,
                "base_sha": self.base,
                "head_ref": self.head_ref,
                "base_ref": self.base_ref,
            },
        }
        self.write_event(self.event)
        environment = mock.patch.dict(
            os.environ,
            {
                "GITHUB_EVENT_NAME": "merge_group",
                "GITHUB_EVENT_PATH": str(self.event_path),
                "GITHUB_SHA": self.queue,
                "GITHUB_REF": self.head_ref,
            },
        )
        environment.start()
        self.addCleanup(environment.stop)

    def write_event(self, value: object) -> None:
        self.event_path.write_text(json.dumps(value))

    def identity(self) -> dict:
        return qualification.materialize_candidate(self.queue, self.base, "queue")

    def object_files(self) -> dict:
        objects = self.root / ".git/objects"
        return {
            str(path.relative_to(objects)): path.read_bytes()
            for path in objects.rglob("*")
            if path.is_file()
        }

    def test_queue_uses_exact_event_commit_without_creating_objects(self) -> None:
        before = self.object_files()
        identity = self.identity()
        qualification.verify_checkout_identity(identity, self.queue)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.queue)
        self.assertEqual(identity["candidate"], self.queue)
        self.assertEqual(identity["candidateTree"], identity["sourceTree"])
        self.assertEqual(identity["parents"], [self.base, self.source])
        self.assertEqual(
            identity["queueEvent"],
            {
                "eventName": "merge_group",
                "action": "checks_requested",
                "headSha": self.queue,
                "baseSha": self.base,
                "headRef": self.head_ref,
                "baseRef": self.base_ref,
                "eventSha256": qualification.digest(self.event_path.read_bytes()),
            },
        )
        self.assertEqual(self.object_files(), before)

    def test_queue_base_can_be_an_ancestor_without_an_invented_parent_pair(
        self,
    ) -> None:
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.queue = self.git(
            "commit-tree", tree, "-p", self.source, "-m", "Linear queue fixture"
        )
        self.git("update-ref", self.head_ref, self.queue)
        self.git("checkout", "--detach", self.queue)
        self.event["merge_group"]["head_sha"] = self.queue
        self.write_event(self.event)
        with mock.patch.dict(os.environ, {"GITHUB_SHA": self.queue}):
            before = self.object_files()
            identity = self.identity()
            self.assertEqual(identity["parents"], [self.source])
            qualification.verify_checkout_identity(identity, self.queue)
            self.assertEqual(self.object_files(), before)

    def test_queue_event_fields_and_runner_identity_are_bound(self) -> None:
        cases = [
            ("head_sha", ""),
            ("head_sha", None),
            ("head_sha", 1),
            ("head_sha", "0" * 40),
            ("head_sha", self.source),
            ("base_sha", ""),
            ("base_sha", "0" * 40),
            ("base_sha", self.source),
            ("head_ref", "refs/heads/another-queue"),
            ("base_ref", "main"),
            ("base_ref", "refs/heads/invalid..ref"),
        ]
        before = self.object_files()
        for key, value in cases:
            with self.subTest(field=key, value=value):
                changed = copy.deepcopy(self.event)
                changed["merge_group"][key] = value
                self.write_event(changed)
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    self.identity()
        for malformed in (
            [],
            {"action": "destroyed", "merge_group": self.event["merge_group"]},
            {"action": "checks_requested", "merge_group": None},
        ):
            with self.subTest(event=malformed):
                self.write_event(malformed)
                with self.assertRaises(ValueError):
                    self.identity()
        self.write_event(self.event)
        for environment in (
            {"GITHUB_SHA": self.source},
            {"GITHUB_REF": "refs/heads/another-queue"},
            {"GITHUB_EVENT_NAME": "pull_request"},
            {"GITHUB_EVENT_PATH": ""},
        ):
            with self.subTest(environment=environment):
                with mock.patch.dict(os.environ, environment):
                    with self.assertRaises(ValueError):
                        self.identity()
        with mock.patch.object(qualification, "MAX_EVENT", 8):
            with self.assertRaisesRegex(ValueError, "byte limit"):
                self.identity()
        self.event_path.write_text("{")
        with self.assertRaises(json.JSONDecodeError):
            self.identity()
        self.write_event(self.event)
        self.assertEqual(self.object_files(), before)
        qualification.verify_checkout_identity(self.identity(), self.queue)

    def test_queue_rejects_missing_or_nonancestor_base(self) -> None:
        tree = self.git("rev-parse", "HEAD^{tree}")
        unrelated = self.git("commit-tree", tree, "-m", "Unrelated base")
        before = self.object_files()
        for base in (unrelated, "1" * 40):
            with self.subTest(base=base):
                changed = copy.deepcopy(self.event)
                changed["merge_group"]["base_sha"] = base
                self.write_event(changed)
                with self.assertRaises(subprocess.CalledProcessError):
                    qualification.materialize_candidate(self.queue, base, "queue")
        self.assertEqual(self.object_files(), before)

    def test_queue_and_pr_lanes_cannot_be_relabelled(self) -> None:
        identity = self.identity()
        before = self.object_files()
        for lane in ("source", "merge"):
            with self.subTest(lane=lane):
                with self.assertRaisesRegex(ValueError, "require the queue lane"):
                    qualification.materialize_candidate(self.queue, self.base, lane)
                changed = copy.deepcopy(identity)
                changed["lane"] = lane
                changed.pop("queueEvent")
                with self.assertRaisesRegex(ValueError, "require the queue lane"):
                    qualification.verify_checkout_identity(changed, self.queue)
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_NAME": "pull_request"}):
            with self.assertRaisesRegex(ValueError, "requires a merge_group"):
                self.identity()
            with self.assertRaisesRegex(ValueError, "requires a merge_group"):
                qualification.verify_checkout_identity(identity, self.queue)
            changed = copy.deepcopy(identity)
            changed["lane"] = "source"
            with self.assertRaisesRegex(ValueError, "outside the queue lane"):
                qualification.verify_checkout_identity(changed, self.queue)
            changed.pop("queueEvent")
            qualification.verify_checkout_identity(changed, self.queue)
        self.assertEqual(self.object_files(), before)

    def test_queue_identity_and_event_remain_bound_after_execution(self) -> None:
        identity = self.identity()
        missing = copy.deepcopy(identity)
        missing.pop("queueEvent")
        with self.assertRaisesRegex(ValueError, "queue event identity"):
            qualification.verify_checkout_identity(missing, self.queue)
        mutations = (
            ("candidate", self.source),
            ("sourceTree", self.git("rev-parse", f"{self.base}^{{tree}}")),
            ("candidateTree", self.git("rev-parse", f"{self.base}^{{tree}}")),
            ("parents", list(reversed(identity["parents"]))),
            ("queueEvent", dict(identity["queueEvent"], baseRef="refs/heads/other")),
        )
        for key, value in mutations:
            with self.subTest(field=key):
                changed = copy.deepcopy(identity)
                changed[key] = value
                with self.assertRaises(ValueError):
                    qualification.verify_checkout_identity(changed, self.queue)
        changed = copy.deepcopy(self.event)
        changed["additional_fixture_metadata"] = True
        self.write_event(changed)
        with self.assertRaisesRegex(ValueError, "queue event identity"):
            qualification.verify_checkout_identity(identity, self.queue)
        self.write_event(self.event)
        (self.root / "payload.txt").write_text("changed tracked bytes\n")
        with self.assertRaisesRegex(ValueError, "dirty tracked"):
            qualification.verify_checkout_identity(identity, self.queue)
        self.git("checkout", "--", "payload.txt")
        self.git("commit", "--allow-empty", "-qm", "Same queue tree, different commit")
        self.assertEqual(
            self.git("rev-parse", "HEAD^{tree}"), identity["candidateTree"]
        )
        with self.assertRaisesRegex(ValueError, "checkout commit"):
            qualification.verify_checkout_identity(identity, self.queue)


class DiagnosticStepReceiptTests(unittest.TestCase):
    """Synthetic log fixtures test receipt rejection, never native qualification."""

    git = CheckoutIdentityTests.git
    identity = CheckoutIdentityTests.identity

    def setUp(self) -> None:
        CheckoutIdentityTests.setUp(self)
        self.directory = self.root / "synthetic-diagnostic-logs"
        self.directory.mkdir()
        self.trace = [
            {"requirement": f"ART-{index:02d}", "execution": "passed"}
            for index in range(1, 14)
        ]
        self.bindings = [{"path": "fixture", "gitObject": self.source}]
        for name, value in (
            ("traceability", self.trace),
            ("source_bindings", self.bindings),
        ):
            patch = mock.patch.object(qualification, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def report(self) -> dict:
        steps = []
        for name, argv in qualification.STEPS:
            text = (
                "PASS [0.001s] synthetic-fixture tests::synthetic\n"
                if argv[:2] == ["just", "test"]
                else "synthetic successful command log\n"
            )
            data = text.encode()
            (self.directory / f"{name}.log").write_bytes(data)
            steps.append(
                {
                    "name": name,
                    "argv": argv,
                    "log": f"{name}.log",
                    "logSha256": qualification.digest(data),
                    "logTruncated": False,
                    "status": "passed",
                    "exitCode": 0,
                    "passedTests": qualification.passed_tests(text),
                }
            )
        return {
            "schema": "hepta.learning-artifacts.qualification.v1",
            "identity": self.identity(),
            "steps": steps,
            "trackedSourceUnchanged": True,
            "nativeTraceability": self.trace,
            "sourceBindings": self.bindings,
            "activation": False,
            "independentAcceptance": False,
            "release": False,
        }

    def verify(self, report: dict) -> None:
        report = copy.deepcopy(report)
        report["reportSha256"] = qualification.digest(qualification.canonical(report))
        qualification.verify_report(report, self.directory, self.source)

    def test_self_test_is_required_once_in_the_recorded_step_order(self) -> None:
        report = self.report()
        self.verify(report)
        index = next(
            index
            for index, row in enumerate(report["steps"])
            if row["name"] == "lane-e-self-test"
        )
        changed = copy.deepcopy(report)
        changed["steps"].pop(index)
        with self.assertRaisesRegex(ValueError, "missing, duplicate or reordered"):
            self.verify(changed)
        changed = copy.deepcopy(report)
        changed["steps"].insert(index, copy.deepcopy(changed["steps"][index]))
        with self.assertRaisesRegex(ValueError, "missing, duplicate or reordered"):
            self.verify(changed)
        changed = copy.deepcopy(report)
        changed["steps"][index], changed["steps"][index + 1] = (
            changed["steps"][index + 1],
            changed["steps"][index],
        )
        with self.assertRaisesRegex(ValueError, "missing, duplicate or reordered"):
            self.verify(changed)

    def test_failed_or_tampered_self_test_cannot_qualify(self) -> None:
        report = self.report()
        self.verify(report)
        index = next(
            index
            for index, row in enumerate(report["steps"])
            if row["name"] == "lane-e-self-test"
        )
        mutations = (
            ("status", "failed"),
            ("exitCode", 1),
            ("logTruncated", True),
            ("argv", ["python3", "../scripts/hepta-lane-e-closure.py", "verify"]),
            ("logSha256", "0" * 64),
        )
        for key, value in mutations:
            with self.subTest(field=key):
                changed = copy.deepcopy(report)
                changed["steps"][index][key] = value
                with self.assertRaises(ValueError):
                    self.verify(changed)
        path = self.directory / report["steps"][index]["log"]
        path.write_bytes(b"changed synthetic self-test log\n")
        with self.assertRaisesRegex(ValueError, "log integrity"):
            self.verify(report)


if __name__ == "__main__":
    unittest.main()
