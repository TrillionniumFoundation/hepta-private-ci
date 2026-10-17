"""Standalone diagnostic archive verifier tests. No model weights or network."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from hepta_neuron_model_trials import InvalidTrial, sha_file
from hepta_neuron_physical_receipt_verify import ARMS, FILES, URL_BASE, verify_receipts

SHA = "c" * 40
RUN = 12345


def dump(path, data):
    path.write_text(json.dumps(data, sort_keys=True, ensure_ascii=False) + "\n")


def fixture(root):
    catalog = ROOT / "qualification/neuron-model-trials/upstream-weights.lock.json"
    locked = json.loads(catalog.read_text())
    bundle = root / "receipts"
    bundle.mkdir()
    observations = {}
    materialization = {}
    forward = {}
    for arm in ARMS:
        record = locked["variants"][arm]
        tree = ("1" if arm == "laya" else "2" if arm == "typed" else "3") * 64
        parameters = 321908995 if arm == "multilingual" else 421293827
        mat = {
            "schema": "hepta.neuron.weight-materialization.v1",
            "arm": arm,
            "model_id": record["model_id"],
            "catalog_revision": locked["revision"],
            "catalog_sha256": sha_file(catalog),
            "local_weight_bytes_verified": True,
            "tensor_inventory_verified": True,
            "network_permission_used": True,
            "physical_artifact_tree_sha256": tree,
            "relative_file_sha256": {
                name: "4" * 64 for name in record["required_files"]
            },
            "independently_attested_host": False,
            "production_evidence_verified": False,
            "ndu_selection_authorized": False,
            "promotion_authorized": False,
        }
        mat["relative_file_sha256"]["model.safetensors"] = record["weights_sha256"]
        forward_ob = {
            "id": "synthetic-no-label-control-1",
            "split": "holdout",
            "input_tokens": 39,
            "latency_ms": 15.5,
            "probabilities": [0.9, 0.1],
        }
        f = {
            "schema": "hepta.neuron.physical-forward-smoke.v1",
            "arm": arm,
            "model_id": record["model_id"],
            "repository": locked["repository"],
            "source_revision": locked["revision"],
            "source_catalog_sha256": sha_file(catalog),
            "weights_sha256": record["weights_sha256"],
            "physical_artifact_tree_sha256": tree,
            "model_forward_executed": True,
            "synthetic_question_only": True,
            "target_host_independently_attested": False,
            "actual_hepta_data_used": False,
            "ndu_net_gain_verified": False,
            "ndu_selection_authorized": False,
            "production_evidence_verified": False,
            "promotion_authorized": False,
            "installed_sdk_python_sha256": "5" * 64,
            "device": "cpu",
            "parameters": parameters,
            "runtime": {
                "artifact_tree_sha256": tree,
                "sdk_tree_sha256": "5" * 64,
                "effective_context": 512,
                "effective_head_budget": 192,
                "torch": "2.5.1+cpu",
            },
            "synthetic_observation": forward_ob,
        }
        observations[arm] = {
            "artifact_tree_sha256": tree,
            "weights_sha256": record["weights_sha256"],
            "model_forward_executed": True,
            "device": "cpu",
            "num_parameters": parameters,
            "latency_ms_single_sample": 15.5,
            "input_tokens": 39,
        }
        materialization[arm] = mat
        forward[arm] = f
    for arm in ARMS:
        dump(bundle / f"hepta-{arm}-materialization.json", materialization[arm])
        dump(bundle / f"hepta-{arm}-physical-smoke.json", forward[arm])
    manifest = {
        "schema": "hepta.neuron.physical-smoke-three-arm-diagnostic.v1",
        "source": "untrusted GitHub Actions metadata; no independently signed host evidence",
        "run_id": RUN,
        "run_url": URL_BASE + str(RUN),
        "source_commit": SHA,
        "artifact_id": 111,
        "artifact_sha256": "6" * 64,
        "actual_hepta_data_used": False,
        "production_evidence_verified": False,
        "ndu_selection_authorized": False,
        "promotion_authorized": False,
        "limitations": ["synthetic only", "not production"],
        "observations": observations,
        "files": {
            name: {
                "bytes": (bundle / name).stat().st_size,
                "sha256": sha_file(bundle / name),
            }
            for name in FILES
        },
    }
    dump(bundle / "manifest.json", manifest)
    return bundle, catalog


class PhysicalReceiptVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle, self.catalog = fixture(Path(self.tmp.name))

    def verify(self, **kw):
        return verify_receipts(
            self.bundle,
            self.catalog,
            expected_run_id=RUN,
            expected_source_sha=SHA,
            **kw,
        )

    def mutate(self, name, fn):
        p = self.bundle / name
        data = json.loads(p.read_text())
        fn(data)
        dump(p, data)
        if name != "manifest.json":
            mf = self.bundle / "manifest.json"
            m = json.loads(mf.read_text())
            m["files"][name] = {"bytes": p.stat().st_size, "sha256": sha_file(p)}
            dump(mf, m)

    def test_three_arm_replay_is_diagnostic_without_promoting(self):
        result = self.verify(
            expected_manifest_sha256=sha_file(self.bundle / "manifest.json")
        )
        self.assertTrue(result["all_six_receipts_match_archive_manifest"])
        self.assertFalse(result["promotion_authorized"])
        self.assertFalse(result["production_evidence_verified"])

    def test_tamper_after_manifest_is_denied(self):
        p = self.bundle / "hepta-laya-physical-smoke.json"
        with p.open("ab") as stream:
            stream.write(b" ")
        with self.assertRaises(InvalidTrial):
            self.verify()

    def test_self_consistent_fake_promotion_is_denied(self):
        self.mutate(
            "hepta-typed-physical-smoke.json",
            lambda d: d.update(promotion_authorized=True),
        )
        with self.assertRaises(InvalidTrial):
            self.verify()

    def test_wrong_publisher_weight_denied_even_when_file_reindexed(self):
        self.mutate(
            "hepta-multilingual-materialization.json",
            lambda d: d["relative_file_sha256"].update({"model.safetensors": "e" * 64}),
        )
        with self.assertRaises(InvalidTrial):
            self.verify()

    def test_nan_probabilities_and_inconsistent_report_denied(self):
        self.mutate(
            "hepta-laya-physical-smoke.json",
            lambda d: d["synthetic_observation"].update(probabilities=[1.0, 1e999]),
        )
        with self.assertRaises(InvalidTrial):
            self.verify()

    def test_false_manifest_source_sha_denied(self):
        with self.assertRaises(InvalidTrial):
            verify_receipts(
                self.bundle,
                self.catalog,
                expected_run_id=RUN,
                expected_source_sha="a" * 40,
            )

    def test_synthetic_receipt_symlink_denied(self):
        p = self.bundle / "hepta-typed-physical-smoke.json"
        q = self.bundle.parent / "typed-receipt.json"
        p.rename(q)
        p.symlink_to(q)
        with self.assertRaises(InvalidTrial):
            self.verify()

    def test_one_extra_receipt_denied(self):
        (self.bundle / "another.json").write_text("{}")
        with self.assertRaises(InvalidTrial):
            self.verify()

    def test_missing_external_manifest_pin_is_explicit_diagnostic(self):
        result = self.verify()
        self.assertFalse(result["expected_manifest_sha256_was_supplied"])
        self.assertTrue(result["source_artifact_not_independently_attested"])


if __name__ == "__main__":
    unittest.main()
