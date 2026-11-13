"""Synthetic fixtures only; do not treat tests as real Encoder evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

SCRIPT = Path(__file__).resolve().parents[1] / "hepta-stem-public-artifact-audit.py"
SPEC = importlib.util.spec_from_file_location("stem_public_audit", SCRIPT)
assert SPEC and SPEC.loader
LIB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIB)

ROOT = "hepta-public-study/"
MODEL = "research/synthetic-fixture"
REV = "a" * 40


def raw_json(obj):
    return (json.dumps(obj, sort_keys=True) + "\n").encode()


def archive_files(*, score_corrupt=False, production=False):
    records = [
        {"case_id": "t0", "split": "train", "label": 0},
        {"case_id": "c0", "split": "calibration", "label": 1},
        {"case_id": "h0", "split": "holdout", "label": 0},
        {"case_id": "h1", "split": "holdout", "label": 1},
    ]
    dataset = b"".join(raw_json(x) for x in records)
    predictions = {"predictions": [
        {"arm": "gated", "case_id": "h0", "split": "holdout",
         "probabilities": [0.8, 0.2]},
        {"arm": "gated", "case_id": "h1", "split": "holdout",
         "probabilities": [0.1, 0.9]},
    ]}
    files = {
        "model-source.json": raw_json(
            {"model_id": MODEL, "revision": REV, "production_accepted": False}
        ),
        "acquisition.json": raw_json({
            "model_id": MODEL, "model_revision": REV,
            "independent_evaluation": False, "production_accepted": False,
        }),
        "dataset.jsonl": dataset,
        "execution/predictions.json": raw_json(predictions),
        "execution/controls.json": raw_json({"holdout_case_ids": ["h0", "h1"]}),
        "execution/head-batch.json": raw_json({"gated": {}}),
        "execution/frozen-features/features.safetensors": b"synthetic tensor",
    }
    files["manifest.json"] = raw_json({
        "dataset": {"sha256": hashlib.sha256(dataset).hexdigest()},
        "classes": 2,
    })
    files["execution/frozen-features/manifest.json"] = raw_json({
        "simulated_encoder": False,
        "file_sha256": hashlib.sha256(
            files["execution/frozen-features/features.safetensors"]
        ).hexdigest(),
    })
    report = {
        "mode": "local_pretrained",
        "independent_evaluation": False,
        "production_accepted": production,
        "laya_comparison_completed": False,
        "encoding": {"simulated_encoder": False, "encoder_forward_calls": 1},
        "process_lifetime_peak_rss_bytes": None,
        "scores": [{
            "arm": "gated", "cases": 2,
            "accuracy": 0.5 if score_corrupt else 1.0,
            "brier": 0.05,
            "independent_evaluation": False,
        }],
    }
    for key, name in (
        ("manifest_sha256", "manifest.json"),
        ("predictions_sha256", "execution/predictions.json"),
        ("controls_sha256", "execution/controls.json"),
        ("head_batch_sha256", "execution/head-batch.json"),
    ):
        report[key] = hashlib.sha256(files[name]).hexdigest()
    files["execution/report.json"] = raw_json(report)
    return files


def write_zip(path, files, extra=None):
    with ZipFile(path, "w", ZIP_DEFLATED) as target:
        for name, content in files.items():
            target.writestr(ROOT + name, content)
        if extra:
            target.writestr(extra, b"bad")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PublicReceiptTests(unittest.TestCase):
    def test_self_consistent_fixture_never_produces_e0_or_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "public.zip"
            sha = write_zip(path, archive_files())
            result = LIB.audit(path, sha, MODEL, REV)
            self.assertEqual(result["status"],
                             "PUBLIC_RESEARCH_ARCHIVE_SELF_CONSISTENT_NOT_E0")
            self.assertEqual(result["scores_recomputed"]["gated"]["correct"], 2)
            self.assertFalse(result["target_host_e0_verified"])
            self.assertFalse(result["production_promotion_permitted"])

    def test_tamper_score_or_source_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "public.zip"
            sha = write_zip(path, archive_files(score_corrupt=True))
            with self.assertRaisesRegex(ValueError, "reported score"):
                LIB.audit(path, sha, MODEL, REV)
            sha = write_zip(path, archive_files())
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                LIB.audit(path, "f" * 64, MODEL, REV)
            with self.assertRaisesRegex(ValueError, "identity"):
                LIB.audit(path, sha, "research/other", REV)

    def test_legitimate_actions_sibling_evidence_is_not_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "public.zip"
            sha = write_zip(path, archive_files(),
                            "hepta-replay-input/producer/report.json")
            report = LIB.audit(path, sha, MODEL, REV)
            self.assertFalse(report["target_host_e0_verified"])

    def test_public_parent_no_change_is_recomputed_not_assumed_deployed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "public.zip"
            files = archive_files()
            control = {
                "holdout_case_ids": ["h0", "h1"],
                "split": {"predictions": {
                    "parent_no_change": [[1.0, 0.0], [0.0, 1.0]],
                }},
            }
            files["execution/controls.json"] = raw_json(control)
            report = json.loads(files["execution/report.json"])
            report["controls_sha256"] = hashlib.sha256(
                files["execution/controls.json"]
            ).hexdigest()
            report["control_scores"] = {
                "split": {"scores": {"parent_no_change": {
                    "cases": 2, "correct": 2, "accuracy": 1.0, "brier": 0.0,
                }}},
            }
            files["execution/report.json"] = raw_json(report)
            sha = write_zip(path, files)
            result = LIB.audit(path, sha, MODEL, REV)
            paired = result["paired_to_public_parent_no_change_research_only"]
            self.assertAlmostEqual(paired["gated"]["brier_delta"], 0.05)
            self.assertFalse(
                paired["gated"]["parent_is_deployed_hepta_no_change"]
            )
            report["control_scores"]["split"]["scores"]["parent_no_change"][
                "accuracy"
            ] = 0.5
            files["execution/report.json"] = raw_json(report)
            sha = write_zip(path, files)
            with self.assertRaisesRegex(ValueError, "public control reported score"):
                LIB.audit(path, sha, MODEL, REV)

    def test_production_claim_and_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "public.zip"
            sha = write_zip(path, archive_files(production=True))
            with self.assertRaisesRegex(ValueError, "research/production boundary"):
                LIB.audit(path, sha, MODEL, REV)
            sha = write_zip(path, archive_files(), ROOT + "../escape")
            with self.assertRaisesRegex(ValueError, "unsafe or duplicate"):
                LIB.audit(path, sha, MODEL, REV)


if __name__ == "__main__":
    unittest.main()
