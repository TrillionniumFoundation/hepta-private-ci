"""Model-free, deliberately synthetic L1 tests of the three-way Cell review."""
import copy
import hashlib
import json
import unittest

from jina_v5 import sha256_record
from prequential_trial import prediction_precommit
from prequential_threeway_review import review
from qualified_eval import audit_dataset


class PrequentialThreeWayTests(unittest.TestCase):
    def setUp(self):
        self.rows = []
        for split, day, count in (
                ("train", 1, 4), ("calibration", 2, 4),
                ("test", 3, 4), ("future", 4, 32),
                ("future", 5, 32), ("ood", 6, 4)):
            start = sum(1 for r in self.rows if r["split"] == split)
            for i in range(count):
                ident = f"{split}-{day}-{i}"
                self.rows.append({
                    "case_id": ident, "group_id": ident, "cell_id":
                        "cell-A" if i % 2 == 0 else "cell-B",
                    "task_id": "decision", "scope_id": "S",
                    "split": split, "language": "en",
                    "state": "state " + ident, "question": "choose?",
                    "options": ["yes", "no"], "label": 0,
                    "event_time": f"2026-01-0{day}T00:00:{i:02d}Z",
                    **({"future_window": "future_1" if day == 4 else "future_2"}
                       if split == "future" else {}),
                })
        self.audit = audit_dataset(self.rows)
        self.future = sorted(
            [r for r in self.rows if r["split"] == "future"],
            key=lambda r: (r["event_time"], r["case_id"]))
        self.initial = {
            str(("S", "cell-A")): "a" * 64,
            str(("S", "cell-B")): "b" * 64,
        }
        self.records = []
        journal = []
        self.nochange = []
        seen = set()
        for event_order, row in enumerate(self.future):
            key = (row["scope_id"], row["cell_id"])
            first = key not in seen
            seen.add(key)
            frozen = [.3, .7]
            trained = frozen if first else [.99, .01]
            head_before = self.initial[str(key)] if first else "c" * 64
            prec = prediction_precommit(row, trained, head_before, event_order)
            prec["record_digest"] = sha256_record(prec)
            journal.append(json.dumps(prec, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":")) + "\n")
            self.records.append({
                "event_order": event_order,
                "case_id": row["case_id"], "scope_id": row["scope_id"],
                "cell_id": row["cell_id"], "event_time": row["event_time"],
                "prediction_seal_before_label_update": prec["record_digest"],
                "preupdate_head_digest": head_before,
                "postupdate_head_digest": "d" * 64,
                "trained_probabilities": trained,
                "frozen_same_initialization_probabilities": frozen,
                "outcome_label_revealed_after_prediction": True,
                "local_update_steps_after_prediction": 1,
            })
            self.nochange.append({
                "case_id": row["case_id"], "scope_id": row["scope_id"],
                "model_id": "no-change", "status": "Succeeded",
                "dataset_digest": self.audit["dataset_digest"],
                "model_revision": "e" * 40, "weights_digest": "f" * 64,
                "generation": 1,
                "input_digest": sha256_record(
                    [row["state"], row["question"], row["options"]]),
                "probabilities": [.2, .8],
            })
        self.journal = "".join(journal).encode("utf-8")
        self.trial = {
            "schema": "hepta.jina-v5-cell-prequential-shadow.v1",
            "model": "jina-v5-text-nano", "revision": "d" * 40,
            "task_id": "decision",
            "production_promotion_permitted": False,
            "independent_ndu_signature_verified": False,
            "genuine_future_outcomes_authenticated": False,
            "dataset_audit": self.audit,
            "initial_head_digests": self.initial,
            "pre_label_prediction_journal_sha256":
                hashlib.sha256(self.journal).hexdigest(),
            "pre_label_prediction_journal_event_count": len(self.records),
            "temporal_receipts": self.records,
            "precommitted_max_per_cell_retention_brier_regression": .01,
            "held_out_test_retention_before": {k: {"multiclass_brier": .20}
                                               for k in self.initial},
            "held_out_test_retention_after": {k: {"multiclass_brier": .195}
                                              for k in self.initial},
            "per_cell_retention_regressions": {},
            "no_retention_regression_above_precommitted_tolerance": True,
        }

    def run_report(self, resources=None):
        return review(self.rows, self.trial, self.journal, self.nochange,
                      resources=resources, min_future_groups=30, replicates=1000)

    def test_true_three_way_future_grouping_never_promotes(self):
        result = self.run_report()
        self.assertTrue(result["quality_three_way_precheck_passed"])
        self.assertFalse(result["four_scale_research_resource_precheck_passed"])
        self.assertFalse(result["joint_offline_diagnostic_passed"])
        self.assertFalse(result["production_promotion_permitted"])
        self.assertFalse(result["signed_nochange_owner_receipt_verified"])
        self.assertEqual(result["future_grouped_paired"]["future_1"]
                         ["frozen"]["groups"], 32)
        self.assertEqual(result["future_grouped_paired"]["future_2"]
                         ["no_change"]["groups"], 32)

    def test_missing_unbound_nochange_blocks_comparison(self):
        with self.assertRaisesRegex(ValueError, "coverage"):
            review(self.rows, self.trial, self.journal, self.nochange[:-1],
                   replicates=1000)
        forged = copy.deepcopy(self.nochange)
        forged[0]["input_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "binding"):
            review(self.rows, self.trial, self.journal, forged,
                   replicates=1000)
        forged = copy.deepcopy(self.nochange)
        forged[-1]["generation"] = 2
        with self.assertRaisesRegex(ValueError, "changed"):
            review(self.rows, self.trial, self.journal, forged, replicates=1000)

    def test_prediction_fsynced_digest_and_precommit_evidence_are_required(self):
        with self.assertRaisesRegex(ValueError, "byte digest mismatch"):
            review(self.rows, self.trial, self.journal + b"x", self.nochange,
                   replicates=1000)
        poisoned = copy.deepcopy(self.trial)
        poisoned["temporal_receipts"][0]["trained_probabilities"] = [.9, .1]
        with self.assertRaisesRegex(ValueError, "precommit"):
            review(self.rows, poisoned, self.journal, self.nochange,
                   replicates=1000)
        tampered = json.loads(self.journal.decode("utf-8").splitlines()[0])
        tampered["label"] = 0
        head = json.dumps(tampered, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":")) + "\n"
        rest = "".join(self.journal.decode().splitlines(keepends=True)[1:])
        forged_bytes = (head + rest).encode()
        forged_trial = copy.deepcopy(self.trial)
        forged_trial["pre_label_prediction_journal_sha256"] = (
            hashlib.sha256(forged_bytes).hexdigest())
        with self.assertRaisesRegex(ValueError, "leaked"):
            review(self.rows, forged_trial, forged_bytes, self.nochange,
                   replicates=1000)

    def test_future_window_group_overlap_and_retention_regression(self):
        broken = copy.deepcopy(self.rows)
        one = next(r for r in broken if r.get("future_window") == "future_1")
        two = next(r for r in broken if r.get("future_window") == "future_2")
        two["group_id"] = one["group_id"]
        with self.assertRaisesRegex(ValueError, "same group"):
            review(broken, self.trial, self.journal, self.nochange,
                   replicates=1000)
        bad = copy.deepcopy(self.trial)
        for entry in bad["held_out_test_retention_after"].values():
            entry["multiclass_brier"] = .4
        result = review(self.rows, bad, self.journal, self.nochange,
                        replicates=1000)
        self.assertFalse(result["quality_three_way_precheck_passed"])
        self.assertFalse(result["production_promotion_permitted"])

    def test_research_resource_scale_matrix_is_not_native_proof(self):
        reports = []
        for n in (64, 256, 1024, 4096):
            reports.append({
                "schema": "hepta.neuron-research-paired-resource-gate.v1",
                "candidate_model": "jina-v5-text-nano",
                "candidate_revision": "d" * 40,
                "production_promotion_permitted": False,
                "independent_ndu_signature_verified": False,
                "production_microbatch_qualified": False,
                "production_recovery_qualified": False,
                "research_resource_gate_passed": True,
                "scale": {"logical_cells": n, "active_heads": n,
                          "distinct_ticked_cells": n, "measured_active_cell_coverage": True},
                "metrics": {
                    "candidate_max_stage_p99_ms": 2.,
                    "candidate_rss_bytes": 1024.,
                    "candidate_throughput_rps": 100.,
                },
            })
        diagnostic = self.run_report(reports)
        self.assertTrue(diagnostic["joint_offline_diagnostic_passed"])
        self.assertFalse(diagnostic["production_promotion_permitted"])
        duplicated = copy.deepcopy(reports)
        duplicated[2]["scale"]["logical_cells"] = 64
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.run_report(duplicated)
        forged = copy.deepcopy(reports)
        forged[0]["production_microbatch_qualified"] = True
        with self.assertRaisesRegex(ValueError, "promoted"):
            self.run_report(forged)


if __name__ == "__main__":
    unittest.main()
