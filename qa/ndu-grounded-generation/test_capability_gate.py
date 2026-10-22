"""Post-hoc capability evaluator must fail closed; these fixtures are NOT science."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from capability_gate import EvidenceError, evaluate_capabilities

METHODS = ("base", "static_cells", "learned_router", "best_of_n", "mean_only",
           "risk_actor_critic", "ndu", "ablate_covariance", "ablate_fixed_weights",
           "ablate_crossmodal", "ablate_missing_modality", "ablate_shuffled_pair")


def make_fixtures():
    entries = []
    for n in range(2):
        for method in METHODS:
            entries.append({"task_id": f"t{n}", "method": method, "seed": 23,
                            "actual_wall_seconds": 2.0, "raw_text": "pred", "boxes": [[0.1,0.1,0.2,0.2]],
                            "trajectory": {"actions": [2, 4]},
                            "score": {"source_id": f"source{n}", "quality": 0.8,
                                      "wall_seconds": 2.0, "coverage": 1.0, "severe": 0.0}})
    report = {"schema": "hepta.ndu-grounded-evaluation.v1", "required_methods": list(METHODS),
              "alpha": 0.9, "engineering_pass": True, "experiment_pass": False,
              "selection": {"chosen_risk_weight": 0.0}, "empirical_frontier": ["base:wall_seconds:10.0"],
              "points": [{"method": name, "point_id": f"{name}:wall_seconds:10.0", "episodes": 2,
                          "source_groups": 2, "quality": 0.8, "wall_seconds": 2.0,
                          "coverage": 1.0, "severe": 0.0, "cvar": 0.2} for name in METHODS]}
    protocol = {"schema": "hepta.ndu-grounded-protocol.v1", "task": {
        "independent_free_text_generation": False, "learned_pixel_generation": False},
        "training": {"ndu": {"state_representation_complete": False, "continuous_FBSDE_solved": False}}}
    return report, protocol, entries


class CapabilityTests(unittest.TestCase):
    def test_unmodified_negative_pilot_cannot_be_promoted(self):
        r, p, e = make_fixtures()
        result = evaluate_capabilities(r, p, e)
        self.assertFalse(result["all_scientific_gates_closed"])
        self.assertEqual(result["gates"]["frozen_v1_ledger_consistency"]["status"], "pass")
        self.assertEqual(result["gates"]["actual_control_horizon"]["facts"]["decisions_histogram"], {2: 2})
        self.assertEqual(result["gates"]["repeated_decoding_seeds_and_power"]["status"], "open")
        self.assertEqual(result["gates"]["confirmatory_frontier_advantage"]["status"], "open")

    def test_disagreement_between_report_and_journal_fails_closed(self):
        r, p, e = make_fixtures()
        for field in ("quality", "severe", "coverage", "cvar", "wall_seconds", "source_groups", "episodes"):
            with self.subTest(field=field):
                bad = copy.deepcopy(r)
                bad["points"][0][field] += 0.01
                with self.assertRaisesRegex(EvidenceError, "aggregate/journal mismatch"):
                    evaluate_capabilities(bad, p, e)

    def test_altered_journal_fails_closed(self):
        r, p, e = make_fixtures()
        bad = copy.deepcopy(e)
        bad[0]["actual_wall_seconds"] += 0.1
        with self.assertRaisesRegex(EvidenceError, "measured wall differ"):
            evaluate_capabilities(r, p, bad)
        with self.assertRaisesRegex(EvidenceError, "lacks at least one planned method"):
            evaluate_capabilities(r, p, e[:-1])

    def test_changed_report_does_not_prove_covariance(self):
        r, p, e = make_fixtures()
        r["selection"]["chosen_risk_weight"] = 0.5
        for item in e:
            if item["method"] == "ndu":
                item["raw_text"] = "other"
        result = evaluate_capabilities(r, p, e)
        self.assertEqual(result["gates"]["covariance_causal_identification"]["status"], "open")

    def test_corrupt_provenance_no_silent_pass(self):
        r, p, e = make_fixtures()
        p["task"]["independent_free_text_generation"] = True
        p["task"]["learned_pixel_generation"] = True
        # V1 protocol flags alone are insufficient to prove actual independent generators.
        result = evaluate_capabilities(r, p, e)
        self.assertNotEqual(result["gates"]["independent_text_and_pixel_generation"]["status"], "pass")

    def test_empty_missing_and_duplicate_rows_rejected(self):
        r,p,e = make_fixtures()
        for bad in ([], [dict(e[0])] * 2):
            with self.subTest(bad_len=len(bad)), self.assertRaises(EvidenceError):
                evaluate_capabilities(r,p,bad)

    def test_invalid_bundle_writes_explicit_blocker_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            out=root / "receipt.json"
            proc=subprocess.run([sys.executable,str(Path(__file__).parent / "capability_gate.py"),
                                 "--bundle-root", str(root), "--output", str(out)],
                                capture_output=True,text=True)
            self.assertEqual(proc.returncode,2)
            result=json.loads(out.read_text())
            self.assertFalse(result["all_scientific_gates_closed"])
            self.assertEqual(result["status"],"invalid_evidence")


if __name__ == "__main__":
    unittest.main()
