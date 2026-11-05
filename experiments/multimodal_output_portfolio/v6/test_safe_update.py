"""Contract fixtures, not new model efficacy evidence."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .measured_cost import CostMeter, Tariff
from .safe_update import _writer, assess, digest, file_digest, load_active, rollback, select


def fixture(candidate="c" * 64, baseline="b" * 64, *, gain=1.0):
    meter = CostMeter()
    with meter.stage("decode"):
        sum(range(100))
    cost = meter.finish()
    protocol = {"schema": "hepta.v6.safe-update.v1", "candidate_id": candidate,
        "baseline_id": baseline, "gamma": 2.0, "minimum_effect": 0.0, "alpha": .05,
        "draws": 1, "return_bounds": [0.0, 1.0],
        "source_census": {"seed-17-clean": [f"source-{i}" for i in range(64)]},
        "source_content_sha256": {f"source-{i}": [digest({"raw_fixture": i})] for i in range(64)},
        "training_and_selection_sources": ["train-source"],
        "training_and_selection_content_sha256": [digest({"raw_fixture": "train"})], "tariff": {},
        "candidate_extra_training_cost": 0.0, "amortization_deployments": 1000,
        "evidence_role": "prospective_confirmation", "candidate_frozen_at": "2026-01-01T00:00:00Z",
        "protocol_frozen_at": "2026-01-02T00:00:00Z", "budget": {"work": 64},
        "required_cost_stages": ["decode"], "max_wall_seconds": 1000,
        "max_owned_bytes": 1024}
    evidence = {"candidate_id": candidate, "checks": {k: True for k in
        ("state_coverage", "belief_calibration", "advantage_calibration", "unknown_rejection",
         "recovery", "same_training_budget")}, "fixture_only": True}
    rows = [{"endpoint": "seed-17-clean", "source_id": source,
        "candidate_id": candidate, "baseline_id": baseline,
        "candidate_information_id": digest({"observation": source}),
        "baseline_information_id": digest({"observation": source}),
        "candidate_budget": {"work": 64}, "baseline_budget": {"work": 64},
        "collected_at": "2026-01-03T00:00:00Z", "qualification_evidence": evidence,
        "qualification_evidence_sha256": digest(evidence), "draws": [{
            "baseline": {"utility": 0.0, "work": 1, "cost": cost, "cost_sha256": digest(cost)},
            "candidate": {"utility": gain, "work": 1, "cost": cost, "cost_sha256": digest(cost)}}]}
        for source in protocol["source_census"]["seed-17-clean"]]
    return protocol, deepcopy(rows)


class MeasuredCostTests(unittest.TestCase):
    def test_failed_work_residency_and_unmeasured_energy(self):
        meter = CostMeter()
        meter.retain("candidate:1", 4096)
        with self.assertRaises(RuntimeError), meter.stage("candidate"):
            raise RuntimeError("real failed action")
        meter.count("recomputations")
        meter.charge_service(.3)
        receipt = meter.finish()
        self.assertTrue(receipt["stages"][0]["failed"])
        self.assertGreater(receipt["physical"]["resident_byte_seconds"], 0)
        self.assertEqual(receipt["physical"]["peak_owned_bytes"], 4096)
        self.assertIsNone(receipt["physical"]["joules"])
        self.assertGreaterEqual(Tariff(cpu_second=1).amount(receipt), .3)
        with self.assertRaises(ValueError):
            Tariff(joule=1).amount(receipt)
        with self.assertRaises(ValueError):
            meter.finish()

    def test_overlapping_attribution_is_rejected(self):
        meter = CostMeter()
        with meter.stage("execute"):
            with self.assertRaises(ValueError), meter.stage("control"):
                pass
        receipt = meter.finish()
        self.assertEqual(len(receipt["stages"]), 1)

    def test_bad_telemetry_does_not_destroy_meter_and_bad_peak_is_rejected(self):
        meter = CostMeter()
        meter.retain("candidate", 12)
        with self.assertRaises(ValueError):
            meter.finish(joules=float("nan"))
        receipt = meter.finish()
        receipt["physical"]["peak_owned_bytes"] = -1
        with self.assertRaises(ValueError):
            Tariff().amount(receipt)


class AdmissionTests(unittest.TestCase):
    def test_clear_fixture_improvement_and_negative_no_update(self):
        protocol, rows = fixture()
        self.assertEqual(assess(protocol, rows)["decision"], "eligible")
        protocol, rows = fixture(gain=0)
        self.assertEqual(assess(protocol, rows)["decision"], "no-update")

    def test_historical_missing_scope_and_cost_amortization(self):
        protocol, rows = fixture()
        protocol["evidence_role"] = "historical_development"
        self.assertIn("development_or_historical_evidence", assess(protocol, rows)["reasons"])
        protocol["required_cost_stages"].append("candidate")
        self.assertIn("incomplete_cost_scope", assess(protocol, rows)["reasons"])
        protocol["return_bounds"] = [-1, 1]
        protocol["candidate_extra_training_cost"] = 1000
        self.assertIn("robust_net_benefit_not_established", assess(protocol, rows)["reasons"])

    def test_no_partial_panel_leakage_or_unequal_information(self):
        protocol, rows = fixture()
        with self.assertRaises(ValueError):
            assess(protocol, rows[:-1])
        with self.assertRaises(ValueError):
            assess(protocol, rows + [rows[0]])
        rows[0]["candidate_information_id"] = "extra-hidden-label"
        with self.assertRaises(ValueError):
            assess(protocol, rows)
        protocol, rows = fixture()
        protocol["training_and_selection_sources"].append("source-0")
        with self.assertRaises(ValueError):
            assess(protocol, rows)

    def test_tampered_cost_and_nonfinite_threshold_rejected(self):
        protocol, rows = fixture()
        rows[0]["draws"][0]["candidate"]["cost"]["service_cost"] = .1
        with self.assertRaises(ValueError):
            assess(protocol, rows)

    def test_exclusion_schema_and_resource_budget_cannot_bypass_gate(self):
        protocol, rows = fixture()
        protocol["training_and_selection_sources"] = "source-0"
        with self.assertRaises(ValueError):
            assess(protocol, rows)
        protocol, rows = fixture()
        protocol["budget"] = {}
        with self.assertRaises(ValueError):
            assess(protocol, rows)
        protocol, rows = fixture()
        for row in rows:
            row["draws"][0]["candidate"]["work"] = 65
        self.assertIn("resource_budget_exceeded", assess(protocol, rows)["reasons"])
        protocol, rows = fixture()
        protocol["max_wall_seconds"] = float("nan")
        with self.assertRaises(ValueError):
            assess(protocol, rows)

    def test_tail_risk_is_not_ce_of_paired_differences(self):
        protocol, rows = fixture()
        protocol["gamma"] = 2
        protocol["draws"] = 2
        for row in rows:
            first = row["draws"][0]
            first["baseline"]["utility"] = .5
            first["candidate"]["utility"] = 0
            second = deepcopy(first)
            second["candidate"]["utility"] = 1
            row["draws"].append(second)
        result = assess(protocol, rows)
        self.assertLess(result["endpoints"]["seed-17-clean"]["paired_test_mean"], 0)

    def test_large_common_reward_cannot_turn_margin_tie_into_improvement(self):
        protocol, rows = fixture()
        protocol.update(gamma=5e-16, minimum_effect=2, return_bounds=[1e16, 1e16 + 2])
        for row in rows:
            row["draws"][0]["baseline"]["utility"] = 1e16
            row["draws"][0]["candidate"]["utility"] = 1e16 + 2
        result = assess(protocol, rows)
        self.assertEqual(result["endpoints"]["seed-17-clean"]["paired_test_mean"], 0)
        self.assertEqual(result["decision"], "no-update")

    def test_atomic_no_update_stale_writer_and_verified_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline, candidate = root / "baseline.json", root / "candidate.json"
            baseline.write_text('{"weights": [0]}')
            candidate.write_text('{"weights": [1]}')
            state = {"revision": 0, "artifact": str(baseline),
                     "artifact_sha256": file_digest(baseline), "previous": None}
            active = root / "ACTIVE.json"
            active.write_text(json.dumps(state))
            before = active.read_bytes()
            protocol, rows = fixture(file_digest(candidate), file_digest(baseline), gain=0)
            report = select(root, candidate, protocol, rows, expected_active_digest=digest(state))
            self.assertEqual(report["decision"], "no-update")
            self.assertEqual(active.read_bytes(), before)
            protocol, rows = fixture(file_digest(candidate), file_digest(baseline))
            repeated = select(root, candidate, protocol, rows, expected_active_digest=digest(state))
            self.assertIn("confirmation_source_already_consumed", repeated["reasons"])
            protocol["source_census"]["seed-17-clean"] = ["fresh-" + s for s in protocol["source_census"]["seed-17-clean"]]
            protocol["source_content_sha256"] = {"fresh-" + s: h for s, h in protocol["source_content_sha256"].items()}
            for row in rows:
                row["source_id"] = "fresh-" + row["source_id"]
            renamed = select(root, candidate, protocol, rows, expected_active_digest=digest(state))
            self.assertIn("confirmation_source_already_consumed", renamed["reasons"])
            protocol["source_content_sha256"] = {s: [digest({"new_raw_fixture": s})]
                                                 for s in protocol["source_content_sha256"]}
            for row in rows:
                row["candidate_information_id"] = row["baseline_information_id"] = digest({"new_observation": row["source_id"]})
            report = select(root, candidate, protocol, rows, expected_active_digest=digest(state))
            self.assertEqual(load_active(root)[1], candidate.read_bytes())
            with self.assertRaises(ValueError):
                select(root, candidate, protocol, rows, expected_active_digest=digest(state))
            restored = rollback(root, expected_active_digest=report["active_digest"])
            self.assertEqual(restored["revision"], 2)
            self.assertEqual(load_active(root)[1], baseline.read_bytes())
            baseline.write_text("tampered")
            self.assertNotEqual(load_active(root)[1], baseline.read_bytes())
            Path(restored["artifact"]).write_text("tampered retained copy")
            with self.assertRaises(ValueError):
                load_active(root)

    @unittest.skipIf(os.name == "nt", "Process-death flock test is POSIX-specific")
    def test_dead_writer_releases_lock_without_deleting_shared_inode(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = ("from experiments.multimodal_output_portfolio.v6.safe_update import _writer\n"
                      "import sys,time\nwith _writer(sys.argv[1]):\n"
                      " print('locked',flush=True)\n time.sleep(30)\n")
            process = subprocess.Popen([sys.executable, "-c", source, temporary], stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), "locked")
                with self.assertRaises(BlockingIOError), _writer(temporary):
                    pass
                process.terminate()
                process.wait(timeout=5)
                with _writer(temporary):
                    self.assertTrue((Path(temporary) / "WRITER.lock").is_file())
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
