"""Actual safetensors/runtime consumption of fixture calibration, not model quality."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch
from safetensors.torch import save

from decision_cell_calibration import joint_support_calibration
from test_calibration_frontier import panel

_PATH = Path(__file__).resolve().parents[2] / "hepta-infer-worker-host/python/decision_cell_tensors.py"
_SPEC = importlib.util.spec_from_file_location("frontier_tensor_consumer", _PATH)
_TENSORS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_TENSORS)


def profile():
    actions = ["open_path", "navigate", "copy_text", "notify", "request_evidence", "stop"]
    return {
        "schema": "hepta.decision-cell-runtime-profile.v2",
        "composition": "shared-base/organ-adapter/cell-adapter/typed-heads",
        "projection_schema": "hepta.decision-cell-text-projection.v1",
        "actions": actions,
        "action_semantic_digests": {name: hashlib.sha256(
            b"hepta.decision-cell-action-label.v1\0" + name.encode()).hexdigest() for name in actions},
        "dispositions": ["continue", "stop", "abstain", "request_evidence", "slow_path", "success"],
        "target_count": 4, "maximum_length": 192, "head_width": 4,
        "target_pointer_profile": "candidate-pair-shared-scorer.v1",
        "pooling": "attention-mask-mean-v1", "parameter_values": "none-v1",
        "postcondition_labels": actions,
        "postcondition_semantic_digests": {name: hashlib.sha256(
            b"hepta.decision-cell-postcondition-label.v1\0" + name.encode()).hexdigest() for name in actions},
    }


def consume(calibration, *, saturated_ood=False, exact_boundary=False):
    model = _TENSORS.TypedHeads(8, width=4)
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.action.bias[0] = 1000
        model.ood.bias.copy_(torch.log(torch.tensor([.95, .05])))
        if saturated_ood:
            model.ood.bias.copy_(torch.tensor([1000., 0.]))
    calibration = {**calibration, "temperatures": {
        name: 1. for name in ("action", "target", "disposition", "postcondition", "ood")}}
    if exact_boundary:
        calibration["maximum_ood_probability"] = float(torch.softmax(model.ood.bias.detach(), dim=-1)[1])
    weights = save(model.state_dict())
    weight_hash = hashlib.sha256(weights).hexdigest()
    manifest = {
        "schema": "hepta.decision-cell-head-artifact.v2", "weights_sha256": weight_hash,
        "weights_bytes": len(weights), "base_model": {"snapshot_digest": "a" * 64},
        "runtime_profile": profile(), "head_parameter_count": sum(p.numel() for p in model.parameters()),
        "parameter_group_sha256": _TENSORS.parameter_group_digests(model), "calibration": calibration,
    }
    encoded = json.dumps(manifest, sort_keys=True, allow_nan=False).encode()
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "weights.safetensors").write_bytes(weights)
        (root / "manifest.json").write_bytes(encoded)
        bundle = _TENSORS.HeadTensorBundleV2(
            manifest_path=root / "manifest.json", manifest_sha256=hashlib.sha256(encoded).hexdigest(),
            weights_path=root / "weights.safetensors", weights_sha256=weight_hash,
            expected_base_snapshot="a" * 64, expected_runtime_profile=profile())
        return bundle.probabilities(torch.zeros(2, 8), torch.zeros(2, 4, 8))


class CalibrationTensorFrontierTests(unittest.TestCase):
    def test_frontier_thresholds_survive_saved_artifact_consumption(self):
        p, y = panel(np.ones(8), [.05] * 5 + [.3, 1., 1.],
                     [True] * 6 + [False] * 2, [True] * 5 + [False, True, True])
        result = consume(joint_support_calibration(p, y))
        self.assertEqual(result["supported"].tolist(), [True, True])
        self.assertEqual(result["action"][:, 0].tolist(), [1., 1.])

    def test_infeasible_support_rejects_saturated_tensor_outputs(self):
        p, y = panel([1., 1., 1.], [0., 0., 1.], [True, True, False], [False, False, True])
        result = consume(joint_support_calibration(p, y), saturated_ood=True)
        self.assertEqual(result["supported"].tolist(), [False, False])
        self.assertEqual(result["action"][:, 0].tolist(), [1., 1.])
        self.assertEqual(result["ood"][:, 1].tolist(), [0., 0.])

    def test_saved_exact_ood_boundary_remains_strict(self):
        p, y = panel([1., 1.], [0., 1.], [True, False], [True, True])
        result = consume(joint_support_calibration(p, y), exact_boundary=True)
        self.assertEqual(result["supported"].tolist(), [False, False])


if __name__ == "__main__":
    unittest.main()
