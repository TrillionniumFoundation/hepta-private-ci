"""Presence-contract regressions using real tiny Heads, never semantic evidence."""

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import torch

from cell_head_training import HeadTrainingConfigV1, TrainedCellHeadV1, _state_digest
from feature_bundle import FeatureBundleError, FeatureBundleV1, FeatureIdentityV1
from native_latent import LightCellHead
import research_presence_guard as guard


IDENTITY = FeatureIdentityV1("a" * 64, "b" * 40, "c" * 64,
                             scope_id="presence-contract-fixture")


def make_head(*, confident_negative=False):
    config = HeadTrainingConfigV1(task_count=2, adapter_rank=2, state_width=2)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(71)
        module = LightCellHead(3, state_width=2, adapter_rank=2, task_count=2)
    with torch.no_grad():
        module.up.weight.zero_()
        module.task_head.weight.copy_(torch.tensor([[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]]))
        module.task_head.bias.copy_(torch.tensor([20.0, -20.0]) if confident_negative else torch.zeros(2))
        if confident_negative:
            module.task_head.weight.zero_()
    report = {"schema": "hepta.trained-cell-task-head.v1", "config": asdict(config),
        "feature_identity": asdict(IDENTITY), "feature_width": 3,
        "trained_tensor_sha256": _state_digest(module), "temperature": 0.5,
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False,
        "fixture_purpose": "deterministic execution contract; no training or quality evidence"}
    return TrainedCellHeadV1(module, IDENTITY, report)


def make_bundle(missing=None, *, identity=IDENTITY, token_views=False, width=3):
    missing = [[False, False, True, True, True]] * 3 if missing is None else missing
    count = len(missing)
    features = torch.arange(count * width, dtype=torch.float32).reshape(count, width) / 7
    features[:, 0] = torch.tensor([2.0, 0.0, -1.0, 0.5][:count])
    extras = {}
    if token_views:
        valid = torch.ones((count, 2), dtype=torch.bool)
        modalities = torch.tensor([[0, 1]] * count)
        for row, mask in enumerate(missing):
            for column in (0, 1):
                if mask[column]:
                    valid[row, column] = False
                    modalities[row, column] = -1
        extras = {"token_features": torch.arange(count * 2 * 2, dtype=torch.float32).reshape(count, 2, 2),
                  "token_valid": valid, "modality_ids": modalities}
    return FeatureBundleV1.from_tensors(global_features=features,
        source_record_digests=tuple(hashlib.sha256(f"presence-row-{i}".encode()).hexdigest() for i in range(count)),
        identity=identity, missing_mask=torch.tensor(missing), **extras)


class PresenceGuardTests(unittest.TestCase):
    def setUp(self):
        self.head = make_head()

    def observe_forwards(self, head):
        calls = []
        handle = head._head.register_forward_pre_hook(
            lambda _module, arguments: calls.append((arguments[0].clone(), arguments[1].clone())))
        self.addCleanup(handle.remove)
        return calls

    def assert_rejected_row(self, row, names):
        self.assertEqual(row["status"], "REJECTED_MISSING_REQUIRED_MODALITY")
        self.assertEqual(row["missing_required_modalities"], names)
        for key in ("prediction", "task_logits", "task_probabilities"):
            self.assertIsNone(row[key])
        self.assertFalse(row["accepted"])

    def test_all_valid_preserves_existing_numerical_predictions_and_confidence(self):
        bundle = make_bundle()
        original = self.head.predict_task(bundle)
        calls = self.observe_forwards(self.head)
        state_before = {name: tensor.clone() for name, tensor in self.head._head.state_dict().items()}
        report_before = self.head.report
        source_before = bundle.bundle_digest
        result = guard.predict_text_image_required(self.head, bundle)
        self.assertEqual(len(calls), 1)
        self.assertTrue(torch.equal(torch.tensor([row["task_logits"] for row in result["rows"]]), original["task_logits"]))
        self.assertTrue(torch.equal(torch.tensor([row["task_probabilities"] for row in result["rows"]]), original["task_probabilities"]))
        self.assertEqual([row["accepted"] for row in result["rows"]], original["accepted"].tolist())
        self.assertEqual([row["prediction"] for row in result["rows"]], original["task_probabilities"].argmax(1).tolist())
        self.assertEqual(result["rows"][1]["status"], "ABSTAINED_LOW_CONFIDENCE")
        self.assertEqual(result["scored_feature_bundle_sha256"], source_before)
        self.assertEqual(result["parent_feature_bundle_sha256"], source_before)
        self.assertEqual(result["parent_source_record_digests"], list(bundle.source_record_digests))
        self.assertEqual(result["head_tensor_sha256"], _state_digest(self.head._head))
        self.assertEqual(self.head.report, report_before)
        for name, tensor in self.head._head.state_dict().items():
            self.assertTrue(torch.equal(tensor, state_before[name]))
        bundle.verify_integrity()

    def test_mixed_batch_excludes_invalid_rows_before_real_head_forward(self):
        bundle = make_bundle([[True, False, True, True, True], [False, False, True, True, True],
                              [False, True, True, True, True], [False, False, True, True, True]], token_views=True)
        views = bundle.snapshot()
        expected_bundle = FeatureBundleV1.from_tensors(
            **{key: value[[1, 3]] for key, value in views.items()}, identity=IDENTITY,
            source_record_digests=tuple(bundle.source_record_digests[i] for i in (1, 3)))
        expected = self.head.predict_task(expected_bundle)
        calls = self.observe_forwards(self.head)
        with patch.object(self.head, "predict_task", wraps=self.head.predict_task) as predict:
            result = guard.predict_text_image_required(self.head, bundle)
        self.assertEqual(predict.call_count, 1)
        consumed = predict.call_args.args[0]
        self.assertEqual(consumed.bundle_digest, expected_bundle.bundle_digest)
        self.assertEqual(consumed.source_record_digests, expected_bundle.source_record_digests)
        for name, value in expected_bundle.snapshot().items():
            self.assertTrue(torch.equal(value, consumed.snapshot()[name]))
        self.assertEqual(len(calls), 1)
        self.assertTrue(torch.equal(calls[0][0], views["global_features"][[1, 3]]))
        self.assertEqual(result["scored_row_indices"], [1, 3])
        self.assertEqual(result["scored_feature_bundle_sha256"], expected_bundle.bundle_digest)
        self.assert_rejected_row(result["rows"][0], ["text"])
        self.assert_rejected_row(result["rows"][2], ["image"])
        for offset, row in enumerate((1, 3)):
            self.assertEqual(result["rows"][row]["task_logits"], expected["task_logits"][offset].tolist())
        self.assertEqual([row["row_index"] for row in result["rows"]], [0, 1, 2, 3])
        self.assertEqual([row["source_record_digest"] for row in result["rows"]], list(bundle.source_record_digests))
        for name, value in views.items():
            self.assertTrue(torch.equal(bundle.snapshot()[name], value))

    def test_all_missing_rejects_even_confident_negative_head_without_any_call(self):
        head = make_head(confident_negative=True)
        bundle = make_bundle([[True, False, True, True, True], [False, True, True, True, True],
                              [True, True, False, True, True]])
        original = head.predict_task(bundle)
        self.assertTrue(bool(original["accepted"].all()))
        self.assertEqual(original["task_probabilities"].argmax(1).tolist(), [0, 0, 0])
        calls = self.observe_forwards(head)
        with patch.object(head, "predict_task", wraps=head.predict_task) as predict:
            result = guard.predict_text_image_required(head, bundle)
        self.assertEqual(predict.call_count, 0)
        self.assertEqual(calls, [])
        self.assertEqual(result["head_prediction_calls"], 0)
        self.assertEqual(result["scored_rows"], 0)
        self.assertEqual(result["rejected_missing_rows"], 3)
        self.assertIsNone(result["scored_feature_bundle_sha256"])
        for row, missing in zip(result["rows"], (["text"], ["image"], ["text", "image"])):
            self.assert_rejected_row(row, missing)

    def test_gate_uses_declared_presence_not_zero_values_or_other_modalities(self):
        bundle = make_bundle([[False, False, True, True, True], [False, True, False, False, False]])
        views = bundle.snapshot()
        views["global_features"][0].zero_()
        views["global_features"][1].fill_(17)
        bundle = FeatureBundleV1.from_tensors(**views, identity=IDENTITY,
                                             source_record_digests=bundle.source_record_digests)
        calls = self.observe_forwards(self.head)
        result = guard.predict_text_image_required(self.head, bundle)
        self.assertEqual(result["scored_row_indices"], [0])
        self.assertTrue(torch.equal(calls[0][0], torch.zeros((1, 3))))
        self.assertIsNotNone(result["rows"][0]["task_logits"])
        self.assert_rejected_row(result["rows"][1], ["image"])

    def test_changed_pairs_with_both_modalities_present_are_not_presence_failures(self):
        bundle = make_bundle()
        views = bundle.snapshot()
        views["global_features"] = views["global_features"][[2, 0, 1]]
        changed_pairs = FeatureBundleV1.from_tensors(**views, identity=IDENTITY,
                                                   source_record_digests=bundle.source_record_digests)
        result = guard.predict_text_image_required(self.head, changed_pairs)
        self.assertEqual(result["scored_row_indices"], [0, 1, 2])
        self.assertEqual(result["rejected_missing_rows"], 0)
        self.assertFalse(result["incorrect_pair_detection_claimed"])
        for row in result["rows"]:
            self.assertEqual(row["missing_required_modalities"], [])
            self.assertIsNotNone(row["task_logits"])

    def test_each_feature_identity_component_is_checked_before_forward(self):
        calls = self.observe_forwards(self.head)
        for field, value in (("encoder_sha256", "d" * 64), ("checkpoint_revision", "d" * 40),
                ("preprocess_sha256", "d" * 64), ("generation", 2), ("scope_id", "foreign"),
                ("purpose", "another-purpose"), ("revocation_epoch", 1)):
            with self.subTest(field=field):
                bundle = make_bundle(identity=replace(IDENTITY, **{field: value}))
                with self.assertRaises(FeatureBundleError):
                    guard.predict_text_image_required(self.head, bundle)
                self.assertEqual(calls, [])

    def test_mask_global_and_source_tampering_are_rejected_before_forward(self):
        calls = self.observe_forwards(self.head)
        for kind in ("mask", "global", "sources"):
            with self.subTest(kind=kind):
                bundle = make_bundle()
                if kind == "mask":
                    bundle._tensors["missing_mask"][0, 0] = True
                elif kind == "global":
                    bundle._tensors["global_features"][0, 0] += 1
                else:
                    bundle._sources = ("e" * 64, *bundle.source_record_digests[1:])
                with self.assertRaises(FeatureBundleError):
                    guard.predict_text_image_required(self.head, bundle)
                self.assertEqual(calls, [])

    def test_wrong_types_and_width_reject_instead_of_scoring(self):
        calls = self.observe_forwards(self.head)
        for head, bundle in ((self.head._head, make_bundle()), (self.head, object()),
                              (self.head, make_bundle(width=2))):
            with self.subTest(head_type=type(head), bundle_type=type(bundle)):
                with self.assertRaises(guard.PresenceGuardError):
                    guard.predict_text_image_required(head, bundle)
        self.assertEqual(calls, [])

    def test_head_parameter_or_posture_drift_is_rejected_even_for_missing_rows(self):
        bundle = make_bundle([[True, False, True, True, True]])
        for kind in ("weights", "authority", "production", "training", "gradient-enabled", "temperature"):
            with self.subTest(kind=kind):
                head = make_head()
                calls = self.observe_forwards(head)
                if kind == "weights":
                    with torch.no_grad():
                        head._head.task_head.bias[0] += 1
                elif kind == "authority":
                    head._report["authority"] = "ALLOW"
                elif kind == "production":
                    head._report["production_activation_allowed"] = True
                elif kind == "training":
                    head._head.train()
                elif kind == "gradient-enabled":
                    head._head.task_head.weight.requires_grad_(True)
                else:
                    head._report["temperature"] = 0.1
                with self.assertRaises(guard.PresenceGuardError):
                    guard.predict_text_image_required(head, bundle)
                self.assertEqual(calls, [])

    def test_confidence_never_grants_task_or_action_authority_and_receipt_is_bound(self):
        bundle = make_bundle()
        result = guard.predict_text_image_required(self.head, bundle)
        self.assertTrue(any(row["accepted"] for row in result["rows"]))
        self.assertFalse(result["task_admission_allowed"])
        self.assertFalse(result["action_execution_allowed"])
        self.assertFalse(result["production_activation_allowed"])
        self.assertEqual(result["mode"], "SHADOW_ONLY")
        for item in (result, *result["rows"]):
            self.assertEqual(item["authority"], "DENY_ALL")
            self.assertFalse(item["task_admission_allowed"])
            self.assertFalse(item["action_execution_allowed"])
            self.assertFalse({"action_logits", "value", "uncertainty", "grant", "token"}.intersection(item))
        self.assertEqual(result["guard_source_sha256"], hashlib.sha256(Path(guard.__file__).read_bytes()).hexdigest())
        contract = json.dumps(result["contract"], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(result["contract_sha256"], hashlib.sha256(contract).hexdigest())
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)

    def test_task_output_or_head_mutation_during_forward_does_not_yield_receipt(self):
        for kind in ("source", "head"):
            with self.subTest(kind=kind):
                head, bundle = make_head(), make_bundle()
                def mutate(_module, _inputs, _result):
                    if kind == "source":
                        bundle._tensors["missing_mask"][0, 0] = True
                    else:
                        with torch.no_grad():
                            head._head.task_head.bias[0] += 1
                handle = head._head.register_forward_hook(mutate)
                try:
                    with self.assertRaises((FeatureBundleError, guard.PresenceGuardError)):
                        guard.predict_text_image_required(head, bundle)
                finally:
                    handle.remove()


if __name__ == "__main__":
    unittest.main()
