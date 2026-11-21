import copy
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

from evaluation import Invalid, OwnerContext, RECOMMEND, STOP, canonical, decode, digest, evaluate, read_pinned, t_critical
from fixtures import FIXED_TEST_TIME, fixture_documents, rebind_protocol, write_fixture


class DecisionTests(unittest.TestCase):
    def result(self, mutate=None, rebind=False):
        docs = fixture_documents()
        if mutate:
            mutate(docs)
        if rebind:
            rebind_protocol(docs)
        with tempfile.TemporaryDirectory() as d:
            name, sha = write_fixture(d, docs)
            return evaluate(OwnerContext(d, name, sha), FIXED_TEST_TIME)

    def stopped(self, result, reason):
        self.assertEqual(result["decision"], STOP)
        self.assertIsNone(result["selected_candidate"])
        self.assertFalse(result["production_eligible"])
        self.assertIn(reason, json.dumps(result))

    def test_complete_evidence_can_recommend_only_research_candidate(self):
        r = self.result()
        self.assertEqual(r["decision"], RECOMMEND)
        self.assertEqual(r["selected_candidate"], "EDIT")
        self.assertEqual(r["statistical_units"], 5)
        self.assertEqual(r["sample_count"], 10)
        self.assertEqual(r["confidence"]["simultaneous_comparisons"], 4)
        self.assertFalse(r["production_eligible"])
        self.assertFalse(r["external_holdout_custody_verified"])

    def test_missing_exchange_produces_sensitivity_and_stop(self):
        r = self.result(lambda d: d["protocol"].update(exchange_rates=None), True)
        self.stopped(r, "missing fixed horizon or resource-to-utility conversion")
        self.assertIsNotNone(r["candidate_results"][0]["break_even_utility_per_resource_unit_if_all_other_costs_zero"]["CPU_second"])
        self.assertIn("ORIGINAL", r["pareto_candidates"])
        self.assertIn("EDIT", r["pareto_candidates"])

    def test_zero_horizon_rejected(self):
        self.stopped(self.result(lambda d: d["protocol"].update(horizon_episodes=0), True), "horizon")

    def test_expensive_candidates_stop_even_with_gain(self):
        def mutate(d):
            for c in d["costs"]["records"].values():
                c["resources"]["CPU_second"] = 1e6
        self.stopped(self.result(mutate), "conservative net value not positive")

    def test_unknown_cost_not_zero(self):
        def mutate(d):
            for c in d["costs"]["records"].values():
                c["unmeasured_components"] = ["future_editor_inference"]
        r = self.result(mutate)
        self.stopped(r, "unknown cost components")
        self.assertIsNone(r["candidate_results"][0]["net_value_lower"])

    def test_wrong_cost_utility_unit(self):
        def mutate(d):
            d["protocol"]["exchange_rates"]["CPU_second"]["utility_unit"] = "USD"
        self.stopped(self.result(mutate, True), "cost/benefit utility unit mismatch")

    def test_sunk_cost_not_future_cost(self):
        self.stopped(self.result(lambda d: d["costs"].update(scope="already_spent_training")), "sunk")

    def test_unit_must_be_fit_not_world(self):
        def mutate(d):
            d["protocol"]["statistics"]["unit"] = "world"
        self.stopped(self.result(mutate, True), "not independent model units")

    def test_repeated_training_seed_is_not_another_model(self):
        def mutate(d):
            d["originals"]["units"][1]["training_seed"] = 11
        self.stopped(self.result(mutate, True), "training provenance")

    def test_training_receipt_must_bind_checkpoint(self):
        def mutate(d):
            d["training:synthetic_fit_11"]["checkpoint_sha256"] = "0"*64
        self.stopped(self.result(mutate), "training provenance")

    def test_unknown_boolean_cannot_override(self):
        self.stopped(self.result(lambda d: d["protocol"].update(independent=True), True), "exact fields")

    def test_untrusted_clock_source(self):
        self.stopped(self.result(lambda d: d["clock"].update(source="candidate_says_now")), "clock")

    def test_stale_clock(self):
        self.stopped(self.result(lambda d: d["clock"].update(observed_utc_ms=FIXED_TEST_TIME-70000)), "clock stale")

    def test_future_clock(self):
        self.stopped(self.result(lambda d: d["clock"].update(observed_utc_ms=FIXED_TEST_TIME+1)), "clock stale or future")

    def test_excess_clock_uncertainty(self):
        self.stopped(self.result(lambda d: d["clock"].update(uncertainty_ms=1001)), "uncertainty")

    def test_train_only_rows_fail(self):
        def mutate(d):
            d["samples"]["samples"][0]["split"] = "TRAIN"
        self.stopped(self.result(mutate), "TRAIN/SELECTION")

    def test_previously_exposed_confirmation_fails(self):
        def mutate(d):
            sid = d["samples"]["samples"][0]["sample_id"]
            d["exposures"]["events"] = [{"sample_id": sid, "phase": "PRIOR_CONFIRMATION", "observed_ms": FIXED_TEST_TIME-9000}]
        self.stopped(self.result(mutate), "previously exposed")

    def test_fake_content_hash_fails(self):
        def mutate(d):
            d["samples"]["samples"][0]["content"]["draw"] = 55
        self.stopped(self.result(mutate), "actual canonical content")

    def test_label_availability_requires_receipt(self):
        def mutate(d):
            d["labels"]["records"][0]["available_ms"] -= 1
        self.stopped(self.result(mutate), "matching receipt")

    def test_immature_label_fails(self):
        def mutate(d):
            d["samples"]["samples"][0]["label_available_ms"] = FIXED_TEST_TIME+1
        self.stopped(self.result(mutate), "label immature")

    def test_sample_before_freeze_fails(self):
        def mutate(d):
            d["samples"]["samples"][0]["source_ms"] = FIXED_TEST_TIME-9000
        self.stopped(self.result(mutate), "predates frozen")

    def test_missing_outcome_cannot_be_silently_dropped(self):
        self.stopped(self.result(lambda d: d["outcomes"]["records"].pop()), "missing/extra outcome")

    def test_changed_candidate_identity_fails(self):
        def mutate(d):
            d["outcomes"]["records"][1]["model_sha256"] = "f"*64
        self.stopped(self.result(mutate), "model identity")

    def test_unknown_utility_cannot_be_positive(self):
        def mutate(d):
            d["outcomes"]["records"][1]["utility"] = None
        self.stopped(self.result(mutate), "finite number")

    def test_oracle_only_cannot_be_recommended(self):
        def mutate(d):
            for c in d["protocol"]["candidates"]:
                c["kind"] = "oracle_diagnostic"
        self.stopped(self.result(mutate, True), "oracle rescue")

    def test_authentication_detects_post_pin_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            name, sha = write_fixture(d)
            (Path(d)/"samples.json").write_bytes(b"{}")
            with self.assertRaisesRegex(Invalid, "SHA mismatch"):
                OwnerContext(d, name, sha)

    def test_owner_is_out_of_band(self):
        with tempfile.TemporaryDirectory() as d:
            name, sha = write_fixture(d)
            with self.assertRaisesRegex(Invalid, "SHA mismatch"):
                OwnerContext(d, name, "0"*64)

    def test_duplicate_json_keys_and_nonfinite_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e1000}', b'{"a":'+b'9'*400+b'}'):
            with self.assertRaises(Invalid):
                decode(raw)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO contract")
    def test_fifo_is_rejected_without_waiting_for_writer(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkfifo(Path(d)/"fifo")
            with self.assertRaisesRegex(Invalid, "regular file"):
                read_pinned(Path(d), {"path": "fifo", "sha256": "0"*64})

    def test_student_t_reference_quantiles(self):
        self.assertAlmostEqual(t_critical(.975, 4), 2.7764451051977987, places=10)
        self.assertAlmostEqual(t_critical(.975, 1), 12.706204736432095, places=9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
