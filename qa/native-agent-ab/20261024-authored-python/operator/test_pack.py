"""Preparation regressions for information separation and scoring identities."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import assignment
import pack


class PackContractTests(unittest.TestCase):
    def valid_observations(self, task, candidate_sha="a" * 64):
        observations = []
        for case in pack.load_cases(task):
            observations.append({"schema": "hepta.native-ab.observation.v1", "task_id": task["task_id"],
                                 "slug": task["slug"], "case_id": case["case_id"],
                                 "input_sha256": case["input_sha256"], "candidate_sha256": candidate_sha,
                                 "observed": case["expected"]})
        return observations

    def raw(self, records):
        return b"".join(pack.canonical(record) + b"\n" for record in records)

    def test_materialize_copies_only_two_public_files_and_never_reuses(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "fresh"
            task = pack.task_record("stream_frames")
            receipt = pack.materialize(task, destination)
            self.assertEqual({p.name for p in destination.iterdir()}, {"TASK.md", "repair_target.py"})
            self.assertFalse(receipt["os_sandbox_established"])
            with self.assertRaises(ValueError):
                pack.materialize(task, destination)

    def test_inputs_have_no_expected_or_reference_fields(self):
        for task in pack.read_index()["tasks"]:
            for request in pack.requests_for(task):
                self.assertEqual(set(request), {"schema", "task_id", "slug", "case_id", "input_sha256", "input"})
                self.assertEqual(pack.digest(pack.canonical(request["input"])), request["input_sha256"])

    def test_boolean_integer_confusion_cannot_pass(self):
        task = pack.task_record("state_window")
        records = self.valid_observations(task)
        self.assertTrue(pack.judge(task, self.raw(records), "a" * 64)["success"])
        records[0]["observed"][0] = 1
        grade = pack.judge(task, self.raw(records), "a" * 64)
        self.assertEqual(grade["functional_status"], "fail")
        self.assertFalse(grade["success"])

    def test_changed_input_identity_rejected(self):
        task = pack.task_record("state_window")
        records = self.valid_observations(task)
        records[0]["input_sha256"] = "b" * 64
        self.assertEqual(pack.judge(task, self.raw(records), "a" * 64)["functional_status"], "grading_error")

    def test_wrong_source_or_response_order_rejected(self):
        task = pack.task_record("state_window")
        records = self.valid_observations(task)
        self.assertEqual(pack.judge(task, self.raw(records), "b" * 64)["functional_status"], "grading_error")
        records[0], records[1] = records[1], records[0]
        self.assertEqual(pack.judge(task, self.raw(records), "a" * 64)["functional_status"], "grading_error")

    def test_missing_extra_and_malformed_output_rejected(self):
        task = pack.task_record("state_window")
        records = self.valid_observations(task)
        for data in (self.raw(records[:-1]), self.raw(records + [records[-1]]), b"debug text\n"):
            self.assertEqual(pack.judge(task, data, "a" * 64)["functional_status"], "grading_error")

    def test_perfect_functional_observations_are_not_attestation(self):
        task = pack.task_record("state_schedule")
        grade = pack.judge(task, self.raw(self.valid_observations(task)), "a" * 64)
        self.assertTrue(grade["success"])
        self.assertFalse(grade["execution_or_isolation_attested"])

    def test_assignment_is_sequential_and_alternates_pair_order(self):
        attempts = assignment.assignment()["attempts"]
        self.assertEqual([a["ordinal"] for a in attempts], list(range(1, 17)))
        for index in range(8):
            pair = attempts[2 * index:2 * index + 2]
            self.assertEqual(pair[0]["task_id"], pair[1]["task_id"])
            self.assertEqual([a["arm"] for a in pair], ["native", "codex"] if index % 2 == 0 else ["codex", "native"])
        for family in {a["family_id"] for a in attempts}:
            self.assertEqual(sum(a["arm"] == "native" for a in attempts if a["family_id"] == family), 2)
            self.assertEqual(sum(a["arm"] == "codex" for a in attempts if a["family_id"] == family), 2)

    def test_authored_effect_fixture_does_not_hide_duplicate_invocations(self):
        fixture = pack.ROOT / "controller" / "effect_fixture.py"
        with tempfile.TemporaryDirectory() as root:
            for attempt in ("physical-1", "physical-2"):
                request = {"schema": "hepta.native-ab.controller-effect-request.v1", "run_id": "preparation-only",
                           "request_id": "request-1", "effect_id": "effect-1", "invocation_id": attempt,
                           "mode": "acknowledge"}
                result = subprocess.run([sys.executable, "-I", "-B", str(fixture)], input=pack.canonical(request),
                                        capture_output=True, cwd=root, env={"LC_ALL": "C.UTF-8"}, timeout=2)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(json.loads(result.stdout)["owner_receipt_durability_attested"])
            records = [json.loads(line) for line in (Path(root) / "effects.jsonl").read_bytes().splitlines()]
            self.assertEqual(len(records), 2)
            self.assertEqual({r["effect_id"] for r in records}, {"effect-1"})
            self.assertEqual({r["invocation_id"] for r in records}, {"physical-1", "physical-2"})


if __name__ == "__main__":
    unittest.main()
