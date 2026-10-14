"""Negative source/physical accounting gates; records are synthetic mechanisms."""
import copy
import hashlib
import unittest
from ndu_p0p6_receipts import (ARMS, SCALES, ReceiptError, freeze_models,
                              meter_scale, phase_blockers)


def h(s): return hashlib.sha256(str(s).encode()).hexdigest()


def frozen_panel():
    return {name: dict(weights_sha256=h(name), tokenizer_sha256=h(name+"token"),
                       preprocessor_sha256=h(name+"pre"), checkpoint_revision=h(name)[:40],
                       dataset_sha256=h("train"), reader_sha256=h("reader"),
                       objective_sha256=h("objective"), head_initial_sha256=h("head"),
                       train_budget=1000000, license_review_id="independently-pending",
                       feature_width=256, pooling_sha256=h(name+"pool"),
                       normalization_sha256=h(name+"norm"), quantization_sha256=h(name+"quant"),
                       runtime_sha256=h(name+"runtime"), bridge_sha256=h(name+"bridge"))
            for name in ARMS}


def synthetic_costs(arm="granite97"):
    return [dict(arm=arm, cells=n, concurrency=min(n, 64), scope_sha256=h("scope"),
                 source_sha256=h("input"), model_sha256=h(arm), head_sha256=h("head"),
                 physical_encoder_forwards=n, cpu_ns=n*10000, wall_ns=n*9000,
                 peak_rss_bytes=1234567, latencies_ns=list(range(1,n+1)),
                 energy_joules=None) for n in SCALES]


class ReceiptsTests(unittest.TestCase):
    def test_complete_four_model_identities_not_real_execution(self):
        report = freeze_models(frozen_panel())
        self.assertEqual(len(report["declared_models"]), 4)
        self.assertFalse(report["physical_weights_verified"])
        self.assertFalse(report["production_accepted"])

    def test_changed_reader_and_initial_head_are_rejected(self):
        for field in ("reader_sha256", "dataset_sha256", "objective_sha256", "head_initial_sha256", "train_budget", "feature_width"):
            panel = frozen_panel()
            panel["granite97"][field] = (1 if field == "train_budget" else 384) if field in ("train_budget", "feature_width") else h("drift")
            with self.subTest(field=field), self.assertRaisesRegex(ReceiptError, "changed Reader/task"):
                freeze_models(panel)

    def test_alias_weights_and_missing_arms_rejected(self):
        panel = frozen_panel()
        del panel["laya421"]
        with self.assertRaisesRegex(ReceiptError, "all four"):
            freeze_models(panel)
        panel = frozen_panel()
        panel["granite97"]["weights_sha256"] = panel["laya421"]["weights_sha256"]
        panel["granite97"]["tokenizer_sha256"] = panel["laya421"]["tokenizer_sha256"]
        with self.assertRaisesRegex(ReceiptError, "aliases"):
            freeze_models(panel)

    def test_all_four_scales_with_true_request_percentiles(self):
        result = meter_scale(synthetic_costs(), arm="granite97")
        self.assertEqual([v["logical_cells"] for v in result["observations"]], list(SCALES))
        self.assertEqual(result["observations"][0]["p99_ns"], 64)
        self.assertIsNone(result["observations"][0]["energy_joules"])
        self.assertFalse(result["host_attestation_verified"])

    def test_missing_and_fabricated_samples_rejected(self):
        records = synthetic_costs()[:-1]
        with self.assertRaises(ReceiptError):
            meter_scale(records, arm="granite97")
        records = synthetic_costs()
        records[0]["latencies_ns"] = [1]
        with self.assertRaisesRegex(ReceiptError, "latency census"):
            meter_scale(records, arm="granite97")
        records = synthetic_costs()
        records[2]["physical_encoder_forwards"] = 0
        with self.assertRaisesRegex(ReceiptError, "cost"):
            meter_scale(records, arm="granite97")
        records = synthetic_costs()
        records[1]["model_sha256"] = h("drift")
        with self.assertRaisesRegex(ReceiptError, "between physical scales"):
            meter_scale(records, arm="granite97")
        records = synthetic_costs()
        records[0]["energy_joules"] = True
        with self.assertRaisesRegex(ReceiptError, "energy"):
            meter_scale(records, arm="granite97")
        records = synthetic_costs()
        records[0]["energy_joules"] = float("nan")
        with self.assertRaisesRegex(ReceiptError, "energy"):
            meter_scale(records, arm="granite97")

    def test_mechanism_cannot_self_promote_p0_to_p6(self):
        empty = phase_blockers({})
        self.assertEqual(set(empty["phases"]), {"P0", "P1", "P2", "P3", "P4", "P5", "P6"})
        self.assertFalse(empty["all_stages_independently_passed"])
        all_self_reported = {x: True for phase in empty["phases"].values()
                             for x in phase["missing_or_unverified_fields"]}
        done = phase_blockers(all_self_reported)
        self.assertTrue(all(v["mechanism_reported_complete"] for v in done["phases"].values()))
        self.assertFalse(done["all_stages_independently_passed"])
        self.assertFalse(done["production_accepted"])
        with self.assertRaisesRegex(ReceiptError, "unknown"):
            phase_blockers({"production_approved": True})
        with self.assertRaisesRegex(ReceiptError, "boolean"):
            phase_blockers({"finite_tree_exact_oracle": "passed"})


if __name__ == "__main__":
    unittest.main()
