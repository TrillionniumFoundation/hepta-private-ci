"""Synthetic, diagnostic-only tests: no model invocation or deployment evidence."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from hepta_neuron_model_trials import (ARMS, InvalidTrial, compare, load_inputs,
                                      metrics, parameter_budget, sha_file, write_new)


def fixture(root, family="decisions"):
    rows = []
    for idx, split in enumerate(("train", "calibration", "holdout", "future_1", "future_2")):
        for language in (("en", "zh", "cross") if family == "multilingual" else ("en",)):
            row = {"id": f"{split}-{language}", "split": split,
                   "source_group": f"{split}-{language}", "observed_at_ms": (idx + 1) * 1000,
                   "language": language, "domain": "test", "is_ood": idx >= 2,
                   "state": "fixture-only", "question": {
                       "type": "choice", "instructions": "Which?", "criteria": {"yes": "Yes", "no": "No"}},
                   "gold": "yes"}
            if family == "heads":
                row.update({"features_q24": [0] * 512, "target_q24": [0] * 512})
            rows.append(row)
    dataset = root / "dataset.jsonl"
    dataset.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
    manifest = {"schema": "hepta.neuron.model-trial.v1", "family": family,
                "source_sha": "a" * 40, "dataset_sha256": sha_file(dataset),
                "host_profile_digest": "1" * 64,
                "parameter_cap": 262656 if family == "heads" else 425000000,
                "max_len": 512, "head": {"input_dimension": 512, "state_width": 256, "encoder_digest": "d" * 64}}
    if family != "heads":
        manifest["models"] = {a: {"model_id": {
            "laya": "convaiinnovations/laya",
            "typed": "convaiinnovations/laya-typed-decisions",
            "multilingual": "convaiinnovations/laya-multilingual"}[a],
            "revision": ("b" if a == "laya" else "c") * 40,
            "weights_sha256": ("2" if a == "laya" else "3") * 64,
            "artifact_tree_sha256": ("4" if a == "laya" else "5") * 64}
            for a in ARMS[family]}
    mpath = root / "manifest.json"
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest, rows, dataset, mpath


def packet(manifest, rows, arm, damaged=False):
    family = manifest["family"]
    records = []
    for row in rows:
        if row["split"] not in ("holdout", "future_1", "future_2"):
            continue
        r = {"id": row["id"], "split": row["split"], "latency_ms": 2.0}
        if family == "heads":
            r["prediction_q24"] = [1 if damaged and row["split"] == "future_2" else 0] * 512
        else:
            r["probabilities"] = ([.2, .8] if damaged and row["split"] == "future_2" else [.9, .1])
        records.append(r)
    result = {"schema": manifest["schema"], "family": family, "arm": arm,
              "source_sha": manifest["source_sha"], "dataset_sha256": manifest["dataset_sha256"],
              "host_profile_digest": manifest["host_profile_digest"], "device": "cpu",
              "parameters": (parameter_budget(512, 256)[0][arm] if family == "heads" else 420000000),
              "observations": records}
    if family == "heads":
        result["runtime"] = {"head_profile_sha256": hashlib.sha256(
            json.dumps(manifest["head"], sort_keys=True).encode()).hexdigest()}
    if family != "heads":
        model = manifest["models"][arm]
        result.update({"model_id": model["model_id"], "model_revision": model["revision"],
                       "weights_sha256": model["weights_sha256"],
                       "runtime": {"artifact_tree_sha256": model["artifact_tree_sha256"]}})
    return result


class TrialTests(unittest.TestCase):
    def test_arms_enforce_real_budget_and_cohort_completeness(self):
        counts, widths = parameter_budget(512, 256)
        self.assertEqual(counts["linear"], 262656)
        self.assertEqual((widths["mlp"], widths["swiglu"]), (255, 170))
        self.assertTrue(all(0.99 * 262656 <= v <= 262656 for v in counts.values()))
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            for family in ARMS:
                manifest, rows, dataset, mpath = fixture(root, family)
                actual, actual_rows = load_inputs(mpath, dataset)
                self.assertEqual((actual, actual_rows), (manifest, rows))

    def test_paired_windows_and_negative_transfer_remain_untrusted(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            manifest, rows, dataset, mpath = fixture(root)
            files = {}
            for arm in ARMS["decisions"]:
                out = root / f"{arm}.json"
                write_new(out, packet(manifest, rows, arm, damaged=arm == "typed"))
                files[arm] = out
            result = compare(manifest, rows, files, sha_file(files["laya"]))
            self.assertEqual(result["results"]["laya"]["holdout"]["accuracy"], 1)
            self.assertEqual(result["negative_transfer"]["typed"]["future_2"]["negative_transfer_rate"], 1)
            self.assertFalse(result["promotion_authorized"])
            self.assertFalse(result["ndu_selection_authorized"])
            with self.assertRaisesRegex(InvalidTrial, "baseline receipt changed"):
                compare(manifest, rows, files, "e" * 64)
            bad = packet(manifest, rows, "typed")
            bad["model_revision"] = "f" * 40
            write_new(root / "tampered.json", bad)
            with self.assertRaisesRegex(InvalidTrial, "identity, bytes or revision"):
                compare(manifest, rows, {"laya": files["laya"], "typed": root / "tampered.json"},
                        sha_file(files["laya"]))

    def test_multilingual_windows_and_head_packet(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            for family in ("multilingual", "heads"):
                manifest, rows, dataset, mpath = fixture(root, family)
                files = {}
                for arm in ARMS[family]:
                    out = root / f"{family}-{arm}.json"
                    write_new(out, packet(manifest, rows, arm, damaged=arm != ARMS[family][0]))
                    files[arm] = out
                result = compare(manifest, rows, files, sha_file(files[ARMS[family][0]]))
                self.assertIn("future_2", result["results"][ARMS[family][-1]])
                self.assertFalse(result["production_evidence_verified"])

    def test_fail_closed_on_data_leakage_ood_and_nonfinite_outputs(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            manifest, rows, dataset, mpath = fixture(root)
            rows[2]["source_group"] = rows[0]["source_group"]
            dataset.write_text("".join(json.dumps(x) + "\n" for x in rows))
            manifest["dataset_sha256"] = sha_file(dataset)
            mpath.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(InvalidTrial, "leaked"):
                load_inputs(mpath, dataset)
            manifest, rows, dataset, mpath = fixture(root)
            for row in rows:
                row["is_ood"] = False
            dataset.write_text("".join(json.dumps(x) + "\n" for x in rows))
            manifest["dataset_sha256"] = sha_file(dataset)
            mpath.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(InvalidTrial, "OOD cases"):
                load_inputs(mpath, dataset)
            p = packet(manifest, rows, "laya")
            p["observations"][0]["probabilities"][0] = float("nan")
            with self.assertRaisesRegex(InvalidTrial, "invalid probabilities"):
                metrics(rows, p["observations"], "decisions")

    def test_no_overwrite_existing_diagnostic_receipt(self):
        with tempfile.TemporaryDirectory() as path:
            out = Path(path) / "receipt.json"
            write_new(out, {"production_evidence_verified": False})
            with self.assertRaises(FileExistsError):
                write_new(out, {"production_evidence_verified": True})


if __name__ == "__main__":
    unittest.main()
