"""Saved-provider counterexamples; no actor, network or model execution."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .github_observations import RULE, SCHEMA, _read, evaluate_saved, strict_json


def fixture():
    row = dict(
        repository="owner/repo", head_sha="a" * 40, run_id=10, run_attempt=1, job_id=20
    )
    return dict(schema=SCHEMA, label_rule=RULE, roster=[row])


def envelope(plan, index, *, status="queued", conclusion=None, jobs=None):
    row = plan["roster"][0]
    if jobs is None:
        jobs = [
            dict(
                id=row["job_id"],
                run_id=row["run_id"],
                status=status,
                conclusion=conclusion,
                steps=None,
            )
        ]
    for job in jobs:
        job.setdefault("head_sha", row["head_sha"])
        job.setdefault("run_attempt", row["run_attempt"] or 1)
        job.setdefault(
            "url",
            f"https://api.github.com/repos/{row['repository']}/actions/jobs/{job['id']}",
        )
    raw = json.dumps(dict(jobs=jobs))
    return {k: v for k, v in row.items() if k != "job_id"} | dict(
        observation_index=index,
        payload=raw,
        payload_sha256=hashlib.sha256(raw.encode()).hexdigest(),
    )


class GitHubObservationTests(unittest.TestCase):
    def test_known_and_unknown_labels_preserve_planned_roster(self):
        plan = fixture()
        pending = envelope(plan, 1)
        before = deepcopy((plan, pending))
        result = evaluate_saved(plan, [pending])
        self.assertEqual(
            (
                result["planned_jobs"],
                result["known_provider_labels"],
                result["unknown_provider_labels"],
            ),
            (1, 0, 1),
        )
        self.assertEqual((plan, pending), before)
        self.assertFalse(result["provider_authentication_established"])
        for conclusion, expected in (
            ("success", False),
            ("failure", True),
            ("timed_out", True),
            ("cancelled", None),
            ("skipped", None),
        ):
            with self.subTest(conclusion=conclusion):
                result = evaluate_saved(
                    plan,
                    [
                        pending,
                        envelope(plan, 2, status="completed", conclusion=conclusion),
                    ],
                )
                self.assertIs(result["rows"][0]["provider_target_error"], expected)
                self.assertEqual(
                    result["rows"][0]["terminal_receipt"]["conclusion"], conclusion
                )
                self.assertEqual(result["new_independent_real_tasks"], 0)

    def test_names_and_step_conclusions_are_not_features(self):
        plan = fixture()
        jobs = [
            dict(
                id=20,
                run_id=10,
                name="label-bearing task",
                status="in_progress",
                conclusion=None,
                steps=[
                    dict(name="fault label", status="completed", conclusion="failure")
                ],
            )
        ]
        changed = deepcopy(jobs)
        changed[0]["name"] = "different task"
        changed[0]["steps"][0].update(name="different", conclusion="success")
        a = evaluate_saved(plan, [envelope(plan, 1, jobs=jobs)])
        b = evaluate_saved(plan, [envelope(plan, 1, jobs=changed)])
        self.assertEqual(
            a["rows"][0]["observations"][0]["features"],
            b["rows"][0]["observations"][0]["features"],
        )

    def test_initial_terminal_or_missing_job_refuses(self):
        plan = fixture()
        for first in (
            envelope(plan, 1, status="completed", conclusion="success"),
            envelope(plan, 1, jobs=[]),
        ):
            with self.assertRaises(ValueError):
                evaluate_saved(plan, [first])

    def test_changed_envelope_source_or_attempt_refuses(self):
        plan = fixture()
        for patch in (
            dict(repository="other/repo"),
            dict(head_sha="b" * 40),
            dict(run_id=99),
            dict(run_attempt=2),
            dict(observation_index=True),
        ):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                evaluate_saved(plan, [envelope(plan, 1) | patch])

    def test_payload_run_head_attempt_and_repository_refuse(self):
        plan = fixture()
        for patch in (
            dict(id=True),
            dict(run_id=99),
            dict(head_sha="b" * 40),
            dict(run_attempt=True),
            dict(url="https://api.github.com/repos/wrong/repo/actions/jobs/20"),
        ):
            job = (
                dict(id=20, run_id=10, status="queued", conclusion=None, steps=None)
                | patch
            )
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                evaluate_saved(plan, [envelope(plan, 1, jobs=[job])])

    def test_duplicate_reopened_or_contradictory_records_refuse(self):
        plan = fixture()
        first = envelope(plan, 1)
        terminal = envelope(plan, 2, status="completed", conclusion="success")
        for observations in (
            [first, first],
            [first, terminal, envelope(plan, 3)],
            [
                first,
                terminal,
                envelope(plan, 3, status="completed", conclusion="failure"),
            ],
        ):
            with self.assertRaises(ValueError):
                evaluate_saved(plan, observations)
        duplicate = deepcopy(plan)
        duplicate["roster"].append(deepcopy(duplicate["roster"][0]))
        with self.assertRaises(ValueError):
            evaluate_saved(duplicate, [first])

    def test_byte_hash_duplicate_keys_and_nonfinite_json_refuse(self):
        plan = fixture()
        for raw, rehash in (
            ('{"jobs":[],"jobs":[]}', True),
            ('{"jobs":[],"extra":1e999}', True),
            ('{"jobs":[]}', False),
        ):
            first = envelope(plan, 1)
            first["payload"] = raw
            if rehash:
                first["payload_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
            with self.assertRaises(ValueError):
                evaluate_saved(plan, [first])

    def test_later_page_omission_preserves_unknown_and_unknown_attempt(self):
        plan = fixture()
        plan["roster"][0]["run_attempt"] = None
        result = evaluate_saved(plan, [envelope(plan, 1), envelope(plan, 2, jobs=[])])
        self.assertEqual(
            (result["planned_jobs"], result["unknown_provider_labels"]), (1, 1)
        )
        self.assertFalse(result["rows"][0]["attempt_identity_verified"])
        self.assertIsNone(result["rows"][0]["identity"]["run_attempt"])
        self.assertEqual(result["signed_journal_labels_created"], 0)

    def test_missing_full_provider_metadata_refuses(self):
        plan = fixture()
        for name in ("head_sha", "run_attempt", "url"):
            first = envelope(plan, 1)
            payload = json.loads(first["payload"])
            payload["jobs"][0].pop(name)
            first["payload"] = json.dumps(payload)
            first["payload_sha256"] = hashlib.sha256(
                first["payload"].encode()
            ).hexdigest()
            with self.subTest(name=name), self.assertRaises(ValueError):
                evaluate_saved(plan, [first])

    def test_bounded_read_checks_actual_bytes_and_json_chars(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_bytes(b"123")
            with self.assertRaises(ValueError):
                _read(path, 2)
            self.assertEqual(_read(path, 3), "123")
        with self.assertRaises(ValueError):
            strict_json(" " * 1_000_001)


if __name__ == "__main__":
    unittest.main()
