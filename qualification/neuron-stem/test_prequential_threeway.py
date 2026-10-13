"""Model-free, deliberately synthetic L1 tests of the three-way Cell review."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from jina_v5 import sha256_record
from prequential_trial import prediction_precommit
from prequential_threeway_review import (
    future_calibration_metrics, offline_threeway_ood_diagnostic,
    read_journal, review, verify_feature_cache_budget, write_frozen_report,
)
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
        last_postupdate = {}
        for event_order, row in enumerate(self.future):
            key = (row["scope_id"], row["cell_id"])
            first = key not in seen
            seen.add(key)
            frozen = [.3, .7]
            trained = frozen if first else [.99, .01]
            head_before = self.initial[str(key)] if first else last_postupdate[key]
            head_after = sha256_record(["head_after_update", row["case_id"], head_before])
            last_postupdate[key] = head_after
            prec = prediction_precommit(row, trained, head_before, event_order)
            prec["frozen_control_head_digest"] = self.initial[str(key)]
            prec["frozen_control_probabilities"] = frozen
            prec["record_digest"] = sha256_record(prec)
            journal.append(json.dumps(prec, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":")) + "\n")
            self.records.append({
                "event_order": event_order,
                "case_id": row["case_id"], "scope_id": row["scope_id"],
                "cell_id": row["cell_id"], "event_time": row["event_time"],
                "prediction_seal_before_label_update": prec["record_digest"],
                "preupdate_head_digest": head_before,
                "postupdate_head_digest": head_after,
                "frozen_control_head_digest": self.initial[str(key)],
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
            "generation": 1, "feature_manifest_digest": "c" * 64,
            "task_id": "decision",
            "production_promotion_permitted": False,
            "independent_ndu_signature_verified": False,
            "genuine_future_outcomes_authenticated": False,
            "dataset_audit": self.audit,
            "initial_head_digests": self.initial,
            "final_head_digests": {
                str(key): digest for key, digest in last_postupdate.items()},
            "update_steps_per_future_event": 1,
            "frozen_final_head_digests": self.initial.copy(),
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

    def test_feature_cache_receipt_is_bounded_and_never_production_rss(self):
        old = verify_feature_cache_budget(self.trial)
        self.assertFalse(old["receipt_present"])
        self.assertFalse(old["production_rss_qualified"])
        trial = copy.deepcopy(self.trial)
        trial.update({
            "max_feature_cache_bytes": 16384,
            "feature_cache_peak_resident_bytes": 4096,
            "feature_cache_resident_bytes": 2048,
            "feature_cache_retained_cases": 2,
            "feature_cache_evictions": 10,
            "feature_cache_hits": 9,
            "feature_cache_misses": 11,
            "feature_cache_is_not_process_rss": True,
        })
        result = review(
            self.rows, trial, self.journal, self.nochange,
            min_future_groups=30, replicates=1000)
        cache = result["offline_feature_cache_budget_diagnostic"]
        self.assertTrue(cache["budget_consistency_verified"])
        self.assertEqual(cache["peak_retained_tensor_bytes"], 4096)
        self.assertFalse(cache["independently_attested"])
        self.assertFalse(cache["production_rss_qualified"])
        self.assertFalse(result["production_promotion_permitted"])
        invalid = copy.deepcopy(trial)
        invalid["feature_cache_peak_resident_bytes"] = 16385
        with self.assertRaisesRegex(ValueError, "invalid or unbounded"):
            verify_feature_cache_budget(invalid)
        invalid = copy.deepcopy(trial)
        invalid.pop("feature_cache_misses")
        with self.assertRaisesRegex(ValueError, "partial"):
            verify_feature_cache_budget(invalid)
        invalid = copy.deepcopy(trial)
        invalid["feature_cache_is_not_process_rss"] = False
        with self.assertRaisesRegex(ValueError, "invalid or unbounded"):
            verify_feature_cache_budget(invalid)
        invalid = copy.deepcopy(trial)
        invalid["max_feature_cache_bytes"] = True
        with self.assertRaisesRegex(ValueError, "invalid or unbounded"):
            verify_feature_cache_budget(invalid)

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

    def synthetic_threeway_ood_receipts(self):
        # Synthetic inputs exercise the reviewer only, never model performance.
        receipts = []
        for row in self.rows:
            if row["split"] not in ("calibration", "ood"):
                continue
            cell = str((row["scope_id"], row["cell_id"]))
            for arm in ("no_change", "frozen", "trained"):
                if arm == "no_change":
                    model_id, revision, weights, generation = (
                        "no-change", "e" * 40, "f" * 64, 1)
                    probs = [.2, .8] if row["split"] == "calibration" else [.95, .05]
                else:
                    model_id, revision, generation = "jina-v5-text-nano", "d" * 40, 1
                    weights = (self.trial["initial_head_digests"][cell] if
                               arm == "frozen" or row["split"] == "calibration"
                               else self.trial["final_head_digests"][cell])
                    probs = ([.3, .7] if row["split"] == "calibration" else
                             [.9, .1] if arm == "frozen" else [.55, .45])
                receipts.append({
                    "case_id": row["case_id"], "arm": arm,
                    "scope_id": row["scope_id"], "cell_id": row["cell_id"],
                    "split": row["split"], "event_time": row["event_time"],
                    "input_digest": sha256_record(
                        [row["state"], row["question"], row["options"]]),
                    "probabilities": probs, "model_id": model_id,
                    "model_revision": revision, "weights_digest": weights,
                    "generation": generation,
                    **({"feature_manifest_digest": self.trial["feature_manifest_digest"]}
                       if arm != "no_change" else {}),
                    "status": "Succeeded", "production_promotion_permitted": False,
                })
        # Match the original Jina producer's deterministic 2-arm JSONL,
        # not the independently supplied production no-change prediction.
        sidecar = "".join(
            json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n"
            for row in receipts if row["arm"] in ("frozen", "trained")
        ).encode("utf-8")
        self.trial["offline_ood_model_receipts_sha256"] = hashlib.sha256(sidecar).hexdigest()
        return receipts

    def test_threeway_ood_uses_only_prior_calibration_and_never_promotes(self):
        receipts = self.synthetic_threeway_ood_receipts()
        report = review(
            self.rows, self.trial, self.journal, self.nochange,
            ood_receipts=receipts, min_future_groups=30, replicates=1000)
        self.assertTrue(report["offline_ood_threeway_coverage_present"])
        measured = report["offline_ood_threeway_diagnostic"]
        self.assertFalse(measured["independent_prediction_signature_verified"])
        self.assertEqual(measured["frozen_feature_manifest_digest"], "c" * 64)
        self.assertEqual(measured["frozen_stem_cell_generation"], 1)
        self.assertTrue(measured["ood_after_future_window_verified"])
        self.assertEqual(set(measured["results"]),
                         {"trained", "frozen", "no_change"})
        self.assertEqual(measured["results"]["trained"]["ood_false_accept_rate"], 0)
        self.assertEqual(measured["results"]["frozen"]["ood_false_accept_rate"], 1)
        self.assertEqual(measured["results"]["no_change"]["ood_false_accept_rate"], 1)
        self.assertEqual(measured["trained_ood_far_delta_vs_frozen"], -1)
        self.assertFalse(measured["negative_transfer_ood_far_vs_frozen"])
        self.assertFalse(report["ood_threeway_model_evidence_present"])
        self.assertFalse(report["full_quality_and_ood_gate_passed"])
        self.assertFalse(report["production_promotion_permitted"])

    def test_threeway_ood_forgery_partial_coverage_and_weight_drift_fail(self):
        records = self.synthetic_threeway_ood_receipts()
        for change, error in (
                (lambda xs: xs.pop(), "full three-arm"),
                (lambda xs: xs[0].update({"generation": 9}), "weight or generation"),
                (lambda xs: next(row for row in xs if row["arm"] == "trained")
                 .update({"generation": 9}), "weight or generation"),
                (lambda xs: next(row for row in xs if row["arm"] == "frozen")
                 .update({"feature_manifest_digest": "a" * 64}),
                 "weight or generation"),
                (lambda xs: xs[0].update({"input_digest": "0" * 64}), "source/Cell"),
                (lambda xs: xs[0].update({"label": 0}), "smuggle outcome"),
                (lambda xs: xs[0].update({"production_promotion_permitted": True}),
                 "source/Cell")):
            invalid = copy.deepcopy(records)
            change(invalid)
            with self.assertRaisesRegex(ValueError, error):
                offline_threeway_ood_diagnostic(
                    self.rows, self.trial, ("e" * 40, "f" * 64, 1), invalid)
        incomplete = copy.deepcopy(self.trial)
        incomplete.pop("generation")
        with self.assertRaisesRegex(ValueError, "pinned Stem/Cell generation"):
            offline_threeway_ood_diagnostic(
                self.rows, incomplete, ("e" * 40, "f" * 64, 1), records)
        incomplete = copy.deepcopy(self.trial)
        incomplete["feature_manifest_digest"] = "invalid"
        with self.assertRaisesRegex(ValueError, "immutable SHA identity"):
            offline_threeway_ood_diagnostic(
                self.rows, incomplete, ("e" * 40, "f" * 64, 1), records)
        invalid = copy.deepcopy(records)
        next(item for item in invalid if item["split"] == "calibration" and
             item["arm"] == "trained")["probabilities"] = [.99, .01]
        with self.assertRaisesRegex(ValueError, "sidecar byte digest mismatch"):
            offline_threeway_ood_diagnostic(
                self.rows, self.trial, ("e" * 40, "f" * 64, 1), invalid)
        # Even forged trial SHA metadata cannot hide a learned-vs-frozen
        # calibration mismatch; a hash is not a signed producer receipt.
        forged = copy.deepcopy(self.trial)
        forged_sidecar = "".join(
            json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n"
            for row in invalid if row["arm"] in ("frozen", "trained")
        ).encode("utf-8")
        forged["offline_ood_model_receipts_sha256"] = hashlib.sha256(
            forged_sidecar).hexdigest()
        with self.assertRaisesRegex(ValueError, "must share initial state"):
            offline_threeway_ood_diagnostic(
                self.rows, forged, ("e" * 40, "f" * 64, 1), invalid)
        forged.pop("offline_ood_model_receipts_sha256")
        with self.assertRaisesRegex(ValueError, "immutable SHA identity"):
            offline_threeway_ood_diagnostic(
                self.rows, forged, ("e" * 40, "f" * 64, 1), records)

    def test_future_ece_brier_are_descriptive_for_all_three_arms(self):
        summary = self.run_report()
        windows = summary["future_window_calibration_descriptive"]
        self.assertEqual(set(windows), {"future_1", "future_2"})
        for window in windows.values():
            self.assertEqual(set(window), {"no_change", "frozen", "trained"})
            for arm in window.values():
                self.assertEqual(arm["events"], 32)
                self.assertTrue(0 <= arm["accuracy"] <= 1)
                self.assertTrue(0 <= arm["normalized_multiclass_brier"] <= 1)
                self.assertTrue(0 <= arm["ece_15"] <= 1)
                self.assertIn("unattested", arm["outcomes"])
        self.assertLess(windows["future_2"]["trained"]["ece_15"],
                        windows["future_2"]["no_change"]["ece_15"])
        self.assertTrue(summary["ece_15_calculated_for_all_three_controls"])
        self.assertFalse(summary["ood_threeway_model_evidence_present"])
        self.assertFalse(summary["full_quality_and_ood_gate_passed"])
        self.assertFalse(summary["production_promotion_permitted"])

    def test_calibration_refuses_unknown_arms_or_nonnormalized_predictions(self):
        example = {
            "dataset": {"label": 0, "options": ["left", "right"]},
            "trained": [.9, .1], "frozen": [.3, .7], "no_change": [.2, .8],
        }
        stats = future_calibration_metrics([example], "trained")
        self.assertAlmostEqual(stats["normalized_multiclass_brier"], .01)
        with self.assertRaisesRegex(ValueError, "unknown or empty"):
            future_calibration_metrics([example], "unregistered")
        with self.assertRaisesRegex(ValueError, "fixed 15-bin"):
            future_calibration_metrics([example], "trained", bins=2)
        example["trained"] = [.8, .8]
        with self.assertRaisesRegex(ValueError, "probability distribution"):
            future_calibration_metrics([example], "trained")

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

    def test_completed_threeway_report_is_immutable_and_finite(self):
        summary = self.run_report()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "threeway.json"
            write_frozen_report(path, summary)
            original = path.read_bytes()
            self.assertFalse(json.loads(original)["production_promotion_permitted"])
            with self.assertRaises(FileExistsError):
                write_frozen_report(path, {**summary, "production_promotion_permitted": True})
            self.assertEqual(path.read_bytes(), original)
            unfinished = Path(root) / "invalid.json"
            with self.assertRaises(ValueError):
                write_frozen_report(unfinished, {"ece": float("nan")})
            self.assertFalse(unfinished.exists())

    def test_rehashed_duplicate_field_journal_never_passes(self):
        # Without strict decoding, Python's json.loads silently keeps the
        # LAST of two case_id fields; the canonical record digest still
        # verifies, allowing an ambiguously represented precommit.
        lines = self.journal.decode("utf-8").splitlines()
        lines[0] = lines[0].replace(
            '"case_id":', '"case_id":"forged","case_id":', 1)
        content = ("\n".join(lines) + "\n").encode("utf-8")
        forged = copy.deepcopy(self.trial)
        forged["pre_label_prediction_journal_sha256"] = hashlib.sha256(content).hexdigest()
        with self.assertRaisesRegex(ValueError, "malformed immutable prediction journal"):
            review(self.rows, forged, content, self.nochange, replicates=1000)
        with self.assertRaisesRegex(ValueError, "malformed immutable prediction journal"):
            read_journal(self.journal + b"\n")
        with self.assertRaisesRegex(ValueError, "malformed immutable prediction journal"):
            read_journal(b'{"case_id":"x","probabilities":[NaN,1]}\n')

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
        broken_trial = copy.deepcopy(self.trial)
        broken_trial["dataset_audit"] = audit_dataset(broken)
        with self.assertRaisesRegex(ValueError, "same group"):
            review(broken, broken_trial, self.journal, self.nochange,
                   replicates=1000)
        bad = copy.deepcopy(self.trial)
        for entry in bad["held_out_test_retention_after"].values():
            entry["multiclass_brier"] = .4
        result = review(self.rows, bad, self.journal, self.nochange,
                        replicates=1000)
        self.assertFalse(result["quality_three_way_precheck_passed"])
        self.assertFalse(result["production_promotion_permitted"])

    def test_discontinuous_cell_head_update_chain_is_rejected(self):
        bad = copy.deepcopy(self.trial)
        bad["temporal_receipts"][2]["postupdate_head_digest"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "discontinuous Cell Head"):
            review(self.rows, bad, self.journal, self.nochange, replicates=1000)
        bad = copy.deepcopy(self.trial)
        bad["final_head_digests"][str(("S", "cell-A"))] = "0" * 64
        with self.assertRaisesRegex(ValueError, "final Cell Head artifact"):
            review(self.rows, bad, self.journal, self.nochange, replicates=1000)

    def test_historical_only_cell_retains_initial_weights(self):
        dormant_key = str(("S", "cell-C"))
        self.trial["initial_head_digests"][dormant_key] = "1" * 64
        self.trial["final_head_digests"][dormant_key] = "1" * 64
        self.trial["frozen_final_head_digests"][dormant_key] = "1" * 64
        result = self.run_report()
        self.assertTrue(result["sealed_cell_update_chain_consistent"])
        self.assertFalse(result["production_promotion_permitted"])
        bad = copy.deepcopy(self.trial)
        bad["final_head_digests"][dormant_key] = "2" * 64
        with self.assertRaisesRegex(ValueError, "final Cell Head artifact"):
            review(self.rows, bad, self.journal, self.nochange, replicates=1000)

    def test_frozen_head_weights_and_prelabel_probabilities_cannot_drift(self):
        mutated = copy.deepcopy(self.trial)
        mutated["temporal_receipts"][4]["frozen_control_head_digest"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "frozen Head weights"):
            review(self.rows, mutated, self.journal, self.nochange, replicates=1000)
        mutated = copy.deepcopy(self.trial)
        mutated["frozen_final_head_digests"][str(("S", "cell-A"))] = "9" * 64
        with self.assertRaisesRegex(ValueError, "frozen final Head"):
            review(self.rows, mutated, self.journal, self.nochange, replicates=1000)
        journal = [json.loads(line) for line in self.journal.decode().splitlines()]
        journal[4]["frozen_control_probabilities"] = [.99, .01]
        journal[4]["record_digest"] = sha256_record({
            key: value for key, value in journal[4].items() if key != "record_digest"
        })
        content = ("".join(json.dumps(p, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":")) + "\n" for p in journal)).encode()
        changed = copy.deepcopy(self.trial)
        changed["pre_label_prediction_journal_sha256"] = hashlib.sha256(content).hexdigest()
        changed["temporal_receipts"][4]["prediction_seal_before_label_update"] = (
            journal[4]["record_digest"])
        with self.assertRaisesRegex(ValueError, "frozen Head weights"):
            review(self.rows, changed, content, self.nochange, replicates=1000)

    def test_no_optimizer_updates_can_never_prove_cell_learning(self):
        bad = copy.deepcopy(self.trial)
        bad["update_steps_per_future_event"] = 0
        for record in bad["temporal_receipts"]:
            record["local_update_steps_after_prediction"] = 0
        with self.assertRaisesRegex(ValueError, "no-update Cell"):
            review(self.rows, bad, self.journal, self.nochange, replicates=1000)
        bad = copy.deepcopy(self.trial)
        bad["temporal_receipts"][0]["local_update_steps_after_prediction"] = 0
        with self.assertRaisesRegex(ValueError, "local Cell update steps"):
            review(self.rows, bad, self.journal, self.nochange, replicates=1000)

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
