"""Synthetic, non-pretrained adversarial tests for historical post-seal replay."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
import warnings
from zipfile import ZipFile, ZIP_DEFLATED

from experiments.shared_stem_cell import postseal_historical_audit as a


def raw(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode()


def fixture():
    cohort = [{"case_id": str(i),
               "split": "confirmation" if i < 512 else "evaluation",
               "cell": i % 2} for i in range(1024)]
    lock = {"selected": "residual_corrected", "profile": {"classes": 4},
            "independent_source_families_verified": False}
    p = [[.7, .1, .1, .1] for _ in cohort]
    prob = {"bank": copy.deepcopy(p), "shared": copy.deepcopy(p),
            "linear_distilled": copy.deepcopy(p), "residual_corrected": copy.deepcopy(p)}
    predictions = {"candidate_lock_sha256": a.digest(raw(lock)),
                   "cohort_sha256": a.digest(raw(cohort)),
                   "case_ids": [c["case_id"] for c in cohort],
                   "selected": lock["selected"], "predictions": prob}
    observed, _ = a.score(p[:512], [0] * 512, [i % 2 for i in range(512)], 4)
    bound = {"supported_under_iid": False, "per_cell": [
        {"cell": cell, "cases": 256, "bank_correct": 256, "candidate_correct": 256,
         "gains": 0, "losses": 0, "nonregression_supported_under_iid": False}
        for cell in (0, 1)]}
    confirmation = {"candidate_lock_sha256": a.digest(raw(lock)),
                    "predictions_sha256": a.digest(raw(predictions)),
                    "proposed": "residual_corrected", "chosen": "bank",
                    "new_model_selected_on_confirmation": False,
                    "strictly_smaller": True, "production_accepted": False,
                    "confirmation_ids": [c["case_id"] for c in cohort[:512]],
                    "confirmation_labels": [0] * 512, "bound": bound}
    report = {"schema": "hepta.fresh-confirmation-executed.v1",
              "cohort_sha256": a.digest(raw(cohort)),
              "predictions_sha256": a.digest(raw(predictions)),
              "confirmation_sha256": a.digest(raw(confirmation)),
              "proposed": "residual_corrected", "chosen": "bank",
              "chosen_score": observed,
              "scores": {k: copy.deepcopy(observed) for k in prob},
              "evaluation_ids": [c["case_id"] for c in cohort[512:]],
              "evaluation_labels": [0] * 512,
              "retention_certified": False, "assumptions_verified": False,
              "pretraining_clean": False, "production_accepted": False,
              "encoding": {"active_flops": None, "energy_joules": None}}
    return {"candidate-lock.json": lock, "cohort.json": cohort,
            "predictions.json": predictions, "confirmation.json": confirmation,
            "report.json": report}


def write_fixture(root, records):
    destination = root / a.PREFIX
    destination.mkdir(parents=True)
    for name, payload in records.items():
        (destination / name).write_bytes(raw(payload))


class HistoricalAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.records = fixture()
        write_fixture(self.root, self.records)

    def tearDown(self):
        self.temp.cleanup()

    def rewrite(self, name):
        (self.root / a.PREFIX / name).write_bytes(raw(self.records[name]))

    def test_two_distinct_phases_and_no_production(self):
        receipt = a.audit(self.root)
        self.assertEqual(receipt["cohort_sizes"], {"confirmation": 512, "evaluation": 512})
        self.assertEqual(receipt["scores"]["evaluation"]["bank"]["correct"], 512)
        self.assertEqual(receipt["chosen"], "bank")
        self.assertEqual(
            receipt["descriptive_paired_deltas"]["evaluation"]["shared"],
            [{"cell": 0, "cases": 256, "gains": 0, "losses": 0, "net_correct": 0},
             {"cell": 1, "cases": 256, "gains": 0, "losses": 0, "net_correct": 0}],
        )
        self.assertFalse(receipt["production_accepted"])

    def test_rehashed_wrong_eval_score_still_rejects(self):
        self.records["predictions.json"]["predictions"]["shared"][700] = [.1, .7, .1, .1]
        self.rewrite("predictions.json")
        self.records["report.json"]["predictions_sha256"] = a.digest(
            (self.root / a.PREFIX / "predictions.json").read_bytes())
        self.records["confirmation.json"]["predictions_sha256"] = (
            self.records["report.json"]["predictions_sha256"])
        self.rewrite("confirmation.json")
        self.records["report.json"]["confirmation_sha256"] = a.digest(
            (self.root / a.PREFIX / "confirmation.json").read_bytes())
        self.rewrite("report.json")
        with self.assertRaisesRegex(a.AuditError, "evaluator diverges"):
            a.audit(self.root)

    def test_rehashed_confirmation_cannot_retarget_the_frozen_prediction_pin(self):
        self.records["confirmation.json"]["predictions_sha256"] = "0" * 64
        self.rewrite("confirmation.json")
        # Re-pin the outer report, but retain the original sealed probabilities.
        self.records["report.json"]["confirmation_sha256"] = a.digest(
            (self.root / a.PREFIX / "confirmation.json").read_bytes())
        self.rewrite("report.json")
        with self.assertRaisesRegex(a.AuditError, "frozen candidate"):
            a.audit(self.root)

    def test_claimed_independent_retention_refuses(self):
        for name, value in (("retention_certified", True), ("pretraining_clean", True),
                            ("production_accepted", True)):
            with self.subTest(field=name):
                r = copy.deepcopy(self.records["report.json"])
                r[name] = value
                self.records["report.json"] = r
                self.rewrite("report.json")
                with self.assertRaisesRegex(a.AuditError, "negative historical"):
                    a.audit(self.root)
                self.records["report.json"] = fixture()["report.json"]
                self.rewrite("report.json")

    def test_missing_or_changed_required_obligation_blocks_even_with_rehash(self):
        self.records["confirmation.json"]["bound"]["per_cell"][1]["gains"] = 1
        self.rewrite("confirmation.json")
        self.records["report.json"]["confirmation_sha256"] = a.digest(
            (self.root / a.PREFIX / "confirmation.json").read_bytes())
        self.rewrite("report.json")
        with self.assertRaisesRegex(a.AuditError, "paired gains"):
            a.audit(self.root)

    def test_unsafe_zip_names_duplicates_and_external_zip_pin(self):
        path = self.root / "archive.zip"
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            for name in a.NAMES:
                archive.write(self.root / a.PREFIX / name, a.PREFIX + name)
        good_sha = a.digest(path.read_bytes())
        self.assertEqual(a.audit(path, good_sha)["chosen"], "bank")
        with self.assertRaisesRegex(a.AuditError, "pinned"):
            a.audit(path, "0" * 64)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with ZipFile(path, "a") as archive:
                archive.writestr(a.PREFIX + "candidate-lock.json", b"{}")
        with self.assertRaisesRegex(a.AuditError, "unsafe ZIP"):
            a.audit(path, a.digest(path.read_bytes()))

    def test_invalid_probabilities_and_noncanonical_json(self):
        for value in ([.0, .0, .0, 1.], [.9, .4, .0, .0], [.7, .1, .1, float("nan")]):
            with self.subTest(value=value), self.assertRaises(a.AuditError):
                a.score([value], [0], [0], 4)
        for text in (b'{"a":1,"a":2}', b'{"a":NaN}'):
            with self.subTest(text=text), self.assertRaises(a.AuditError):
                a.strict_json(text)
        with self.assertRaises(a.AuditError):
            a.score([[.7, .1, .1, .1]], [0], [True], 4)


if __name__ == "__main__":
    unittest.main()
