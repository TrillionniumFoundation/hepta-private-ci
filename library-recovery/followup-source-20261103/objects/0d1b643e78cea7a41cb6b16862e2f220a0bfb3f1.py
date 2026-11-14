"""Adversarial test matrix for v5 paired cost/quality non-promotion gate."""
import copy
import json
import unittest

from cost_parity_gate import audit_paired_rows, COST_BY_ACTION

ARMS = ("supervised|static", "supervised|ndu_contextual",
        "ndu_risk|static", "ndu_risk|ndu_contextual")


def raw_of(bit):
    return {"text": f"symbol:{bit}", "audio": (bit, -bit, bit, -bit),
            "image": ((bit, bit), (bit, bit)),
            "video": (((bit, bit), (bit, bit)), ((bit, bit), (bit, bit)))}


def fixture(seed=17, n=32):
    rows = []
    roster = tuple(f"{seed}/test/{i:06d}" for i in range(n))
    for source in roster:
        for arm in ARMS:
            dynamic = arm.endswith("ndu_contextual")
            # This mimics a toy improvement that incurs unmatched costs.
            action, raw = ("QUERY", raw_of(0)) if dynamic else ("EMIT", raw_of(1))
            rows.append({"seed": seed, "source": source, "arm": arm,
                         "input_digest": "a"*64, "raw": raw, "truth": 0,
                         "action": action, "cost_units": COST_BY_ACTION[action],
                         "loss": 0 if dynamic else 4,
                         "wrong": 0 if dynamic else 4, "mismatch": 0})
    return rows, {seed: roster}


class CostParityGateTests(unittest.TestCase):
    def _audit(self, rows, roster):
        return audit_paired_rows(rows, seeds=tuple(roster),
                                 expected_sources=roster)

    def test_a_cost_cap_is_not_realized_cost_or_physical_gain(self):
        rows, roster = fixture()
        report = self._audit(rows, roster)
        self.assertEqual(report["four_arm_decoded_rows"], 128)
        self.assertEqual(report["source_groups"], 32)
        row = report["effects_by_seed_training"]["17:supervised"]
        self.assertEqual(row["mean_external_loss_gain_static_minus_dynamic"], 4)
        self.assertEqual(row["mean_executed_toy_cost_dynamic_minus_static"], 3)
        self.assertFalse(row["realized_cost_matched_at_declared_tolerance"])
        self.assertFalse(report["all_cost_matched_quality_gates"])
        self.assertFalse(report["real_encoder_decoder_observed"])
        self.assertFalse(report["physical_meter_attested"])
        self.assertFalse(report["production_blockers_closed"])
        self.assertFalse(report["selection_or_final_use_authority"])

    def test_rejects_missing_duplicate_and_unknown_source_arm(self):
        rows, roster = fixture()
        for bad in (rows[:-1], rows + [rows[0]],
                    [dict(rows[0], arm="secret_arm")] + rows[1:],
                    [dict(rows[0], source="17/train/000000")] + rows[1:]):
            with self.subTest(len=len(bad)):
                with self.assertRaises(ValueError):
                    self._audit(bad, roster)

    def test_rejects_inconsistent_source_binding_or_truth(self):
        rows, roster = fixture()
        for alteration in (dict(rows[1], input_digest="1"*64),
                           dict(rows[1], truth=1)):
            bad = rows.copy()
            bad[1] = alteration
            with self.assertRaises(ValueError):
                self._audit(bad, roster)

    def test_rejects_forged_cost_and_false_score(self):
        rows, roster = fixture()
        for alteration in (dict(rows[1], cost_units=4),
                           dict(rows[0], loss=0),
                           dict(rows[0], wrong=0),
                           dict(rows[0], action="ELEVATE"),
                           dict(rows[1], cost_units=True)):
            bad = rows.copy()
            bad[1 if alteration.get("arm") == rows[1]["arm"] else 0] = alteration
            with self.assertRaises(ValueError):
                self._audit(bad, roster)

    def test_rejects_malformed_four_modal_content(self):
        rows, roster = fixture()
        corrupt = copy.deepcopy(rows[0]); corrupt["raw"].pop("video")
        rows[0] = corrupt
        with self.assertRaises(ValueError):
            self._audit(rows, roster)

    def test_fail_closed_on_float_nan_boolean_and_unsupported_census(self):
        rows, roster = fixture()
        for config in ({"alpha": float("nan")}, {"alpha": .99},
                       {"cost_tolerance": float("inf")},
                       {"cost_tolerance": 2}, {"min_sources": True},
                       {"min_sources": 31}):
            with self.assertRaises(ValueError):
                audit_paired_rows(rows, seeds=(17,), expected_sources=roster, **config)
        with self.assertRaises(ValueError):
            self._audit(rows, {17: roster[17][:-1]})
        with self.assertRaises(ValueError):
            audit_paired_rows(rows, seeds=(17, 29), expected_sources=roster)

    def test_fake_superiority_is_diagnostic_not_production_authority(self):
        rows, roster = fixture(n=256)
        # More groups narrow the bound but still cannot prove actual decoder costs.
        report = self._audit(rows, roster)
        self.assertFalse(report["at_least_one_modality_refinement_executed"])
        self.assertFalse(report["externally_signed_independent_truth"])
        self.assertFalse(report["longitudinal_future_window_admitted"])

    def test_frozen_development_report_cannot_claim_cost_parity(self):
        from pathlib import Path
        report_path = Path(__file__).with_name("development-report.json")
        if not report_path.is_file():
            self.skipTest("frozen upstream v5 report is available only in repository")
        frozen = json.loads(report_path.read_text())
        self.assertEqual([x["seed"] for x in frozen["seeds"]], [17, 29, 43])
        for seed in frozen["seeds"]:
            for training in ("supervised", "ndu_risk"):
                s = seed["arms"][f"{training}|static"]
                d = seed["arms"][f"{training}|ndu_contextual"]
                # All held-out real *modeled* costs differ by > 0.05.
                self.assertGreater(abs(s["mean_cost_units"] - d["mean_cost_units"]), .05)
                self.assertEqual(d["refine_rate"], 0)
            if seed["seed"] == 29:
                self.assertGreater(
                    seed["arms"]["supervised|ndu_contextual"]["mean_loss"],
                    seed["arms"]["supervised|static"]["mean_loss"])

    def test_actual_v5_small_paired_execution_if_available(self):
        try:
            import factorial  # noqa: F401
        except ImportError:
            self.skipTest("standalone local gate tests; integrated v5 only in repo")
        from cost_parity_gate import execute_frozen_development_audit
        report = execute_frozen_development_audit((17,), ntrain=96,
                                                 ndev=64, ntest=32, steps=4)
        self.assertEqual(report["source_groups"], 32)
        self.assertEqual(report["four_arm_decoded_rows"], 128)
        self.assertFalse(report["production_blockers_closed"])


if __name__ == "__main__":
    unittest.main()
