"""Synthetic protocol controls only; no independent tasks or model results."""

import copy
import tempfile
import unittest
from pathlib import Path

import prospective_b as b


def plan():
    tasks = [
        {
            "id": "fixture-B",
            "source_group": "fixture-new",
            "content": "a" * 64,
            "provenance": "b" * 64,
            "prior_model_exposure": False,
        }
    ]
    p = {
        "schema": "hepta.prospective-b.v1",
        "run_id": "synthetic-only",
        "source_closure": "c" * 64,
        "runtime": "d" * 64,
        "protocol": "e" * 64,
        "information": "f" * 64,
        "panel": b.digest(tasks),
        "custody_review": "1" * 64,
        "historical_run_modified": False,
        "tasks": tasks,
        "development_source_groups": ["fixture-old"],
        "maximum_attempts": 2,
        "selection": "report_all_no_adoption",
        "cost_interpretation": "shared_caps_not_equal_actual_cost",
        "caps": dict.fromkeys(b.COSTS, 100),
    }
    p["arms"] = {
        a: {
            "model": str(i) * 64,
            "information": p["information"],
            "protocol": p["protocol"],
        }
        for i, a in enumerate(("initial", "candidate", "matched_control"), 2)
    }
    return p


def receipts(p):
    return [
        {
            "arm": a,
            "task": "fixture-B",
            "run_id": p["run_id"],
            "plan": b.digest(p),
            "model": v["model"],
            "panel": p["panel"],
            "protocol": p["protocol"],
            "attempts": 1,
            "status": "task_failure",
            "executed": True,
            "original_receipt": "9" * 64,
            "cost": dict.fromkeys(b.COSTS, 1),
        }
        for a, v in p["arms"].items()
    ]


class Controls(unittest.TestCase):
    def test_create_once_and_external_digest(self):
        p = plan()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "freeze.json"
            self.assertEqual(b.freeze(p, path), b.digest(p))
            with self.assertRaises(FileExistsError):
                b.freeze(p, path)
        f = {"plan": p, "sha256": b.digest(p)}
        with self.assertRaises(ValueError):
            b.review(f, "0" * 64, receipts(p))

    def test_source_lineage_and_information_rejected(self):
        for mutation in (
            lambda p: p["tasks"][0].update(source_group="fixture-old"),
            lambda p: p["tasks"][0].update(prior_model_exposure=True),
            lambda p: p["arms"]["candidate"].update(information="0" * 64),
            lambda p: p.update(historical_run_modified=True),
            lambda p: p.update(custody_review=""),
        ):
            p = plan()
            mutation(p)
            with self.assertRaises(ValueError):
                b.validate(p)

    def test_missing_and_unknown_are_not_zero(self):
        p = plan()
        f = {"plan": p, "sha256": b.digest(p)}
        r = receipts(p)
        r[0]["cost"]["model_calls"] = None
        got = b.review(f, f["sha256"], r[:-1])
        self.assertFalse(got["complete"])
        self.assertFalse(got["within_shared_caps"])
        self.assertIsNone(got["costs"]["initial"]["model_calls"])
        self.assertEqual(got["missing"], [("matched_control", "fixture-B")])

    def test_actual_cost_not_caps(self):
        p = plan()
        f = {"plan": p, "sha256": b.digest(p)}
        r = receipts(p)
        r[0]["cost"]["input_tokens"] = 2
        got = b.review(f, f["sha256"], r)
        self.assertTrue(got["complete"])
        self.assertTrue(got["within_shared_caps"])
        self.assertFalse(got["equal_measured_cost_vector"])
        self.assertFalse(got["independence_established"])
        self.assertFalse(got["adoption_eligible"])
        self.assertEqual(got["successes"], dict.fromkeys(p["arms"], 0))

    def test_duplicates_wrong_identity_and_unexecuted_success(self):
        p = plan()
        f = {"plan": p, "sha256": b.digest(p)}
        r = receipts(p)
        with self.assertRaises(ValueError):
            b.review(f, f["sha256"], r + r[:1])
        for change in (
            {"model": "0" * 64},
            {"run_id": "historical"},
            {"status": "success", "executed": False},
            {"attempts": 3},
        ):
            q = copy.deepcopy(r)
            q[0].update(change)
            with self.assertRaises(ValueError):
                b.review(f, f["sha256"], q)

    def test_budget_excess_and_incomplete_retained(self):
        p = plan()
        f = {"plan": p, "sha256": b.digest(p)}
        r = receipts(p)
        r[0]["cost"]["model_calls"] = 101
        self.assertFalse(b.review(f, f["sha256"], r)["within_shared_caps"])
        r[0]["status"] = "incomplete"
        self.assertFalse(b.review(f, f["sha256"], r)["complete"])


if __name__ == "__main__":
    unittest.main()
