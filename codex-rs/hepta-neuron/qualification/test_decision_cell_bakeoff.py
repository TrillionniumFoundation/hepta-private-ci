from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import sys
from pathlib import Path

import numpy as np
import torch

MODULE_PATH = Path(__file__).with_name("decision_cell_bakeoff.py")
SPEC = importlib.util.spec_from_file_location("decision_cell_bakeoff", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
bakeoff = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bakeoff
SPEC.loader.exec_module(bakeoff)


class DecisionCellBakeoffTests(unittest.TestCase):
    def test_disposition_order_matches_runtime_contract(self) -> None:
        self.assertEqual(
            bakeoff.DISPOSITIONS,
            ["continue", "stop", "abstain", "request_evidence", "slow_path", "success"],
        )
        rows = bakeoff.build_dataset()
        self.assertTrue(any(row.disposition == 1 for row in rows))
        self.assertTrue(any(row.disposition == 5 for row in rows))

    def test_dataset_is_deterministic_and_split_isolated(self) -> None:
        first = bakeoff.build_dataset()
        second = bakeoff.build_dataset()
        first_bytes = bakeoff.canonical_json([row.as_dict() for row in first])
        second_bytes = bakeoff.canonical_json([row.as_dict() for row in second])
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(len(first), 552)
        self.assertEqual(len({row.example_id for row in first}), len(first))
        self.assertTrue(all(len(row.candidates) == bakeoff.TARGET_COUNT for row in first))
        groups: dict[str, set[str]] = {}
        for row in first:
            groups.setdefault(row.split, set()).add(row.source_group)
        for left, left_groups in groups.items():
            for right, right_groups in groups.items():
                if left != right:
                    self.assertTrue(left_groups.isdisjoint(right_groups))

    def test_action_and_disposition_are_separate_heads(self) -> None:
        rows = bakeoff.build_dataset()
        request_evidence = [
            row
            for row in rows
            if row.split == "test" and row.disposition == bakeoff.DISPOSITIONS.index("request_evidence")
        ]
        self.assertTrue(request_evidence)
        self.assertTrue(all(row.target == -1 for row in request_evidence))
        self.assertTrue(
            all(row.action == bakeoff.ACTIONS.index("request_evidence") for row in request_evidence)
        )
        slow_path = [
            row
            for row in rows
            if row.split == "test" and row.disposition == bakeoff.DISPOSITIONS.index("slow_path")
        ]
        self.assertTrue(slow_path)
        self.assertTrue(all(row.action == bakeoff.ACTIONS.index("stop") for row in slow_path))

    def test_prepopulated_snapshot_completeness_is_explicit(self) -> None:
        spec = bakeoff.MODEL_SPECS["laya-multilingual"]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.assertEqual(
                bakeoff.missing_snapshot_paths(root, spec),
                list(bakeoff.required_snapshot_paths(spec)),
            )
            for relative in bakeoff.required_snapshot_paths(spec):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
            self.assertEqual(bakeoff.missing_snapshot_paths(root, spec), [])

    def test_each_backend_declares_its_exact_snapshot_format(self) -> None:
        expected = {
            "laya-multilingual": {"model.safetensors", "encoder/config.json", "tokenizer/tokenizer.json"},
            "lfm25-encoder-230m": {"model.safetensors", "modeling_lfm2_bidirectional.py", "tokenizer.json"},
            "lfm25-encoder-350m": {"model.safetensors", "modeling_lfm2_bidirectional.py", "tokenizer.json"},
            "mdeberta-v3-base": {"pytorch_model.bin", "spm.model", "tokenizer_config.json"},
        }
        for name, required in expected.items():
            declared = set(bakeoff.required_snapshot_paths(bakeoff.MODEL_SPECS[name]))
            self.assertTrue(required.issubset(declared), name)
        self.assertNotIn(
            "model.safetensors",
            bakeoff.required_snapshot_paths(bakeoff.MODEL_SPECS["mdeberta-v3-base"]),
        )
        self.assertNotIn(
            "tokenizer.json",
            bakeoff.required_snapshot_paths(bakeoff.MODEL_SPECS["mdeberta-v3-base"]),
        )

    def test_checkpoint_allowlist_is_exact_and_backbone_drift_still_fails(self) -> None:
        allowed = ["pretraining.head.bias", "pretraining.head.weight"]
        report = bakeoff.validate_checkpoint_loading_info(
            {"unexpected_keys": list(reversed(allowed))},
            allowed_unexpected_keys=allowed,
        )
        self.assertEqual(report["discarded_pretraining_only_keys"], allowed)
        self.assertTrue(report["exact_backbone_loaded"])
        with self.assertRaisesRegex(RuntimeError, "checkpoint load drift"):
            bakeoff.validate_checkpoint_loading_info(
                {"unexpected_keys": allowed + ["encoder.layer.0.weight"]},
                allowed_unexpected_keys=allowed,
            )
        with self.assertRaisesRegex(RuntimeError, "checkpoint load drift"):
            bakeoff.validate_checkpoint_loading_info(
                {"unexpected_keys": [allowed[0]]},
                allowed_unexpected_keys=allowed,
            )
        with self.assertRaisesRegex(RuntimeError, "checkpoint load drift"):
            bakeoff.validate_checkpoint_loading_info(
                {"missing_keys": ["encoder.layer.0.weight"], "unexpected_keys": allowed},
                allowed_unexpected_keys=allowed,
            )

    def test_mdeberta_keeps_sentencepiece_and_exact_pretraining_head_allowlist(self) -> None:
        spec = bakeoff.MODEL_SPECS["mdeberta-v3-base"]
        self.assertFalse(spec["tokenizer_use_fast"])
        self.assertEqual(
            sorted(spec["allowed_unexpected_keys"]),
            sorted(set(spec["allowed_unexpected_keys"])),
        )
        self.assertIn("mask_predictions.classifier.weight", spec["allowed_unexpected_keys"])
        self.assertIn("lm_predictions.lm_head.dense.weight", spec["allowed_unexpected_keys"])

    def test_calibration_thresholds_enforce_declared_error_floor_when_feasible(self) -> None:
        ood_scores = np.asarray([0.01, 0.02, 0.03, 0.97, 0.98, 0.99])
        labels = np.asarray([0, 0, 0, 1, 1, 1])
        _, metrics = bakeoff.select_ood_threshold(ood_scores, labels)
        self.assertLessEqual(metrics["calibration_ood_false_acceptance"], 0.05)
        confidence = np.asarray([0.99, 0.95, 0.80, 0.40])
        correct = np.asarray([True, True, True, False])
        _, confidence_metrics = bakeoff.select_confidence_threshold(confidence, correct)
        self.assertLessEqual(confidence_metrics["calibration_confidence_error"], 0.05)

    def test_target_pointer_is_candidate_permutation_equivariant(self) -> None:
        torch.manual_seed(7)
        model = bakeoff.TypedHeads(hidden_size=8, width=4).eval()
        state = torch.randn(2, 8)
        candidates = torch.randn(2, bakeoff.TARGET_COUNT, 8)
        original = model(state, candidates)["target"]
        order = torch.tensor([1, 0, 3, 2])
        permuted = model(state, candidates[:, order])["target"]
        self.assertTrue(torch.allclose(permuted, original[:, order]))

    def test_head_artifact_is_content_addressed_and_nonactivating(self) -> None:
        model = bakeoff.TypedHeads(hidden_size=8, width=4)
        metadata = {
            "dataset_sha256": "1" * 64,
            "source": {"commit": "2" * 40, "tree": "3" * 40},
            "script_sha256": "4" * 64,
            "base_model": {"snapshot_digest": "5" * 64},
            "training": {"best_epoch": 1},
            "calibration": {"minimum_confidence": 0.5},
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _, first = bakeoff.save_head_artifact(root, "test-model", model, metadata)
            _, second = bakeoff.save_head_artifact(root, "test-model", model, metadata)
            self.assertEqual(first["weights_sha256"], second["weights_sha256"])
            self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])
            manifest = json.loads(Path(first["manifest_path"]).read_text())
            self.assertFalse(manifest["production_activation"])
            self.assertFalse(manifest["operator_acceptance"])
            self.assertFalse(manifest["selected"])
            self.assertFalse(manifest["release"])
            self.assertEqual(
                manifest["runtime_profile"],
                {
                    "schema": "hepta.decision-cell-runtime-profile.v2",
                    "composition": "shared-base/organ-adapter/cell-adapter/typed-heads",
                    "projection_schema": bakeoff.PROJECTION_SCHEMA,
                    "actions": bakeoff.ACTIONS,
                    "action_semantic_digests": bakeoff.ACTION_SEMANTIC_DIGESTS,
                    "dispositions": bakeoff.DISPOSITIONS,
                    "target_count": bakeoff.TARGET_COUNT,
                    "maximum_length": bakeoff.MAX_LENGTH,
                    "head_width": 4,
                    "target_pointer_profile": bakeoff.TARGET_POINTER_PROFILE,
                    "pooling": "attention-mask-mean-v1",
                    "parameter_values": "none-v1",
                    "postcondition_labels": bakeoff.ACTIONS,
                    "postcondition_semantic_digests": bakeoff.POSTCONDITION_SEMANTIC_DIGESTS,
                },
            )

    def test_supply_chain_gate_distinguishes_remote_code_and_license(self) -> None:
        receipt = {
            "base_model": {
                "revision": "a" * 40,
                "observed_hub_sha": "a" * 40,
                "snapshot_matches_pinned_revision": True,
                "upstream_identity": {"revision": "a" * 40,
                    "verified_files_sha256": "d" * 64,
                    "snapshot_matches_pinned_revision": True},
                "snapshot_digest": "d" * 64,
                "license_profile": "apache-2.0",
                "trust_remote_code": False,
            }
        }
        import hashlib
        from snapshot_identity import canonical
        files = [{"path": "config.json", "bytes": 12, "sha256": "c" * 64}]
        receipt["base_model"]["files"] = files
        receipt["base_model"]["snapshot_digest"] = hashlib.sha256(canonical(files) + b"\n").hexdigest()
        receipt["base_model"]["upstream_identity"].update({
            "verified_files_sha256": hashlib.sha256(canonical(files)).hexdigest(),
            "verified_file_count": 1})
        self.assertTrue(all(bakeoff.supply_chain_admission(receipt).values()))
        receipt["base_model"]["trust_remote_code"] = True
        self.assertFalse(
            bakeoff.supply_chain_admission(receipt)["no_unreviewed_remote_code"]
        )

    def test_synthetic_time_tags_never_become_calendar_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path, _ = bakeoff.write_dataset(bakeoff.build_dataset(), Path(raw))
            dataset = json.loads(path.read_text())
            self.assertFalse(dataset["genuine_temporal_holdout"])
            self.assertFalse(dataset["prospective_future_window_evidence"])
            self.assertTrue(dataset["separate_tuning_calibration"])
        rows = bakeoff.build_dataset()
        tuning = {row.example_id for row in rows if row.split == "tuning"}
        calibration = {row.example_id for row in rows if row.split == "calibration"}
        self.assertTrue(tuning)
        self.assertTrue(calibration)
        self.assertTrue(tuning.isdisjoint(calibration))

    def test_offline_snapshot_does_not_fabricate_observed_hub_revision(self) -> None:
        from unittest.mock import patch
        spec = bakeoff.MODEL_SPECS["laya-multilingual"]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / spec["repo"].replace("/", "--") / spec["revision"]
            for name in bakeoff.required_snapshot_paths(spec):
                file = target / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b"fixture-only")
            with patch.dict("os.environ", {"HEPTA_BAKEOFF_OFFLINE": "1"}):
                _, metadata = bakeoff.model_snapshot(spec, root)
            self.assertIsNone(metadata["observed_hub_sha"])
            self.assertFalse(metadata["hub_revision_verified_this_run"])
            self.assertFalse(bakeoff.supply_chain_admission({"base_model": metadata})["exact_revision_bound"])

    def test_each_adapter_is_executed_and_its_digest_is_independent(self) -> None:
        torch.manual_seed(31)
        model = bakeoff.TypedHeads(8, 4).eval()
        value = torch.randn(2, 8)
        targets = torch.randn(2, bakeoff.TARGET_COUNT, 8)
        before = bakeoff.parameter_group_digests(model)
        first = model(value, targets)["action"]
        with torch.no_grad():
            model.cell_adapter[0].weight.add_(0.1)
        after = bakeoff.parameter_group_digests(model)
        second = model(value, targets)["action"]
        self.assertNotEqual(before["cell_adapter"], after["cell_adapter"])
        self.assertEqual(before["organ_adapter"], after["organ_adapter"])
        self.assertEqual(before["heads"], after["heads"])
        self.assertFalse(torch.allclose(first, second))
        with torch.no_grad():
            model.organ_adapter[0].bias.add_(0.2)
        self.assertFalse(torch.allclose(second, model(value, targets)["action"]))

    def test_nonfinite_metrics_are_never_canonical_evidence(self) -> None:
        with self.assertRaises(ValueError):
            bakeoff.canonical_json({"accuracy": float("nan")})

    def test_receipt_verification_rehashes_trained_weights(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _, dataset = bakeoff.write_dataset(bakeoff.build_dataset(), root / "dataset")
            model = bakeoff.TypedHeads(8, 4)
            metadata = {"dataset_sha256": dataset, "source": {"commit": "a" * 40, "tree": "b" * 40},
                        "script_sha256": "c" * 64, "base_model": {"snapshot_digest": "d" * 64},
                        "calibration": {"minimum_confidence": 0.5}}
            _, head = bakeoff.save_head_artifact(root, "unit-fixture", model, metadata)
            embedding = bakeoff.save_embeddings(root, "unit-fixture", ["sample"],
                np.zeros((1, 8)), np.zeros((1, bakeoff.TARGET_COUNT, 8)))
            value = {"schema": bakeoff.SCHEMA, **metadata, "head_artifact": head,
                     "embedding_artifact": embedding, "production_activation": False,
                     "operator_acceptance": False, "selected": False, "release": False}
            (root / "receipts").mkdir()
            receipt = root / "receipts" / "fixture.json"
            receipt.write_bytes(bakeoff.canonical_json(value))
            bakeoff.verified_receipt(receipt)
            with Path(head["weights_path"]).open("ab") as file:
                file.write(b"corrupt")
            with self.assertRaisesRegex(RuntimeError, "content digest mismatch"):
                bakeoff.verified_receipt(receipt)


if __name__ == "__main__":
    unittest.main()
