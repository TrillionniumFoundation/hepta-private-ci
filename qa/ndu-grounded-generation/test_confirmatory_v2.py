"""Synthetic contract checks; NOT a model run or a new held-out cohort."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from confirmatory_v2 import (METHODS, COST_KEYS, ConfirmatoryError, assess,
                            episode_roster, fractional_cvar, registration_check)


def fixture(n=12, seeds=(3, 5, 7), case="strong"):
    reg = {"schema": "hepta.ndu-confirmatory-registration.v2", "methods": list(METHODS),
           "seeds": list(seeds), "test_sources": n, "alpha": .05, "cvar_alpha": .9,
           "bootstrap_samples": 64, "bootstrap_seed": 20261023,
           "selected_dev_risk_weight": .5,
           "margins": {"quality_gain": .01, "cvar_delta": 0., "severe_delta": .02,
                       "wall_ratio": 1.05, "coverage_delta": -.01,
                       "covariance_cvar_gain": .01, "cell_quality_gain": .01}}
    sources = []
    for ix in range(n+4):
        identifier = f"fresh:{ix}" if ix < n else f"fresh:extra:{ix}"
        k = hashlib.sha256(identifier.encode()).hexdigest()
        sources.append({"source_id": identifier, "task_id": f"v2task:{ix}",
                        "image_sha256": k,
                        "decoded_rgb_sha256": hashlib.sha256((identifier+"RGB").encode()).hexdigest(),
                        "dhash64": hashlib.sha256((identifier+"Dhash").encode()).hexdigest()[:16]})
    candidate = {"schema": "hepta.grounded-cohort.v1", "splits": {
        "train": {"count": 2, "sources": sources[n:n+2]},
        "dev": {"count": 1, "sources": sources[n+2:n+3]},
        "calibration": {"count": 1, "sources": sources[n+3:n+4]},
        "test": {"count": n, "sources": sources[:n]}}}
    old = "outside:history:999"
    history = [{"schema": "hepta.ndu.historical-exclusions.v1", "source_sample": {"images": [{
        "source_id": old, "image_sha256": hashlib.sha256(old.encode()).hexdigest(),
        "decoded_rgb_sha256": hashlib.sha256((old+"rgb").encode()).hexdigest(),
        "dhash64": hashlib.sha256((old+"dhash").encode()).hexdigest()[:16]}]}}]
    digest = hashlib.sha256(json.dumps(candidate).encode()).hexdigest()
    reg["cohort_manifest_sha256"] = digest
    firewall = (candidate, history, digest)
    entries = []
    for source in range(n):
        for seed in seeds:
            for method in METHODS:
                q = (.95 if method == "ndu" else
                     .75 if method.startswith("ablate_") else
                     .8 if method in ("best_of_n", "mean_only") else .7)
                if case == "negative" and method == "ndu": q = .7
                entries.append({"source_id": f"fresh:{source}", "seed": seed,
                                "method": method, "quality": q, "severe": 0,
                                "coverage": 1, "wall_seconds": 1.5,
                                "control_checkpoints": 10 if method == "ndu" else 0,
                                "cost_parts": {k: .1 for k in COST_KEYS}})
    return reg, firewall, entries


class ConfirmatoryTests(unittest.TestCase):
    def audit(self, reg, cohort_triplet, entries):
        candidate, history, digest = cohort_triplet
        return assess(reg, candidate, history, digest, entries,
                      minimum_sources=8, minimum_bootstraps=64)

    def test_positive_synthetic_conditional_acceptance_cannot_promote_model(self):
        r, f, e = fixture()
        out = self.audit(r, f, e)
        self.assertTrue(out["all_preregistered_statistical_contrasts_pass"])
        self.assertFalse(out["model_promotion_authorized"])
        self.assertFalse(out["independent_language_and_pixel_generation_verified"])
        self.assertEqual(out["family_size"], 15)
        self.assertEqual(out["full_episode_denominator"], 12*3*len(METHODS))
        self.assertAlmostEqual(out["points"]["ndu"]["quality"], .95)

    def test_negative_true_quality_loss_fails_inference(self):
        r, f, e = fixture(case="negative")
        out = self.audit(r, f, e)
        self.assertFalse(out["all_preregistered_statistical_contrasts_pass"])
        self.assertFalse(out["contrasts"]["best_of_n"]["quality_gain"]["pass"])

    def test_no_zero_lambda_or_fabricated_firewall(self):
        r, f, e = fixture()
        r["selected_dev_risk_weight"] = 0.
        with self.assertRaisesRegex(ConfirmatoryError, "nonzero"):
            self.audit(r, f, e)
        r["selected_dev_risk_weight"] = .5
        f[0]["splits"]["test"]["sources"][0]["source_id"] = "outside:history:999"
        with self.assertRaisesRegex(ConfirmatoryError, "firewall"):
            self.audit(r, f, e)

    def test_missing_source_seed_and_ablations_fail_closed(self):
        r, f, e = fixture()
        for bad in (e[:-1], e[1:], e+[e[0]]):
            with self.subTest(length=len(bad)), self.assertRaises(ConfirmatoryError):
                self.audit(r, f, bad)
        bad=copy.deepcopy(e)
        bad[0]["seed"] = 9
        with self.assertRaisesRegex(ConfirmatoryError, "seed"):
            self.audit(r, f, bad)

    def test_partial_and_overbudget_results_cannot_be_discarded(self):
        r, f, e = fixture()
        bad=copy.deepcopy(e)
        bad[0]["coverage"] = 0
        bad[0]["severe"] = 1
        with self.assertRaisesRegex(ConfirmatoryError, "zero quality"):
            self.audit(r, f, bad)
        bad[0]["quality"] = 0
        bad[0]["wall_seconds"] = 99.0  # retain cost, even for failed arm
        out=self.audit(r, f, bad)
        self.assertEqual(out["full_episode_denominator"], len(bad))
        self.assertGreater(out["points"]["base"]["wall"], 1.5)

    def test_short_or_fictitious_checkpoint_count_rejected(self):
        r, f, e = fixture()
        for n in (0, 7, 17):
            bad=copy.deepcopy(e)
            next(row for row in bad if row["method"] == "ndu")["control_checkpoints"] = n
            with self.subTest(n=n), self.assertRaisesRegex(ConfirmatoryError, "8-16"):
                self.audit(r, f, bad)

    def test_cost_receipt_fail_closed(self):
        r, f, e = fixture()
        for problem in ("missing", "overrun", "nan"):
            bad=copy.deepcopy(e)
            if problem == "missing": del bad[0]["cost_parts"]["encoder"]
            if problem == "overrun": bad[0]["cost_parts"]["encoder"] = 10
            if problem == "nan": bad[0]["wall_seconds"] = float("nan")
            with self.subTest(problem=problem), self.assertRaises(ConfirmatoryError):
                self.audit(r, f, bad)

    def test_exact_protocol_and_method_roster_required(self):
        r, f, e = fixture()
        r["methods"] = ["ndu", "best_of_n", "mean_only"]
        with self.assertRaisesRegex(ConfirmatoryError, "roster"):
            self.audit(r, f, e)
        r, f, e=fixture()
        r["margins"]["quality_gain"] = -.1
        with self.assertRaisesRegex(ConfirmatoryError, "directional"):
            self.audit(r, f, e)

    def test_source_cluster_cvar_uses_fractional_mass(self):
        self.assertAlmostEqual(fractional_cvar([0,0,0,1], .9), 1.0)
        self.assertAlmostEqual(fractional_cvar([0,0,0,1,1,0,0,0,0,0], .8), 1.0)

    def test_external_registration_sha_rejects_posttest_edit(self):
        r, f, e=fixture()
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)
            registration=p/"registration.json"
            registration.write_text(json.dumps(r))
            pin=hashlib.sha256(registration.read_bytes()).hexdigest()
            (p/"candidate.json").write_text(json.dumps(f[0]))
            (p/"history.json").write_text(json.dumps(f[1][0]))
            (p/"episodes.jsonl").write_text("\n".join(map(json.dumps,e))+"\n")
            registration.write_text(json.dumps({**r,"selected_dev_risk_weight":1.0}))
            cmd=[sys.executable,str(Path(__file__).parent/"confirmatory_v2.py"),
                 "--registration",str(registration), "--registered-sha256",pin,
                 "--cohort-manifest",str(p/"candidate.json"),
                 "--historical",str(p/"history.json"),
                 "--episodes",str(p/"episodes.jsonl"), "--output",str(p/"result.json")]
            proc=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(proc.returncode,2)
            self.assertEqual(json.loads((p/"result.json").read_text())["status"],"invalid_or_incomplete_evidence")


if __name__ == "__main__":
    unittest.main()
