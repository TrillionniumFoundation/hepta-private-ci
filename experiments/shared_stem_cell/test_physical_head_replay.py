import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from safetensors.numpy import save

from experiments.shared_stem_cell.physical_head_replay import (
    PreflightError, replay, predict, tensor_set,
)
from experiments.shared_stem_cell.preflight_review import ARMS
from experiments.shared_stem_cell.test_preflight_review import make_study
from experiments.shared_stem_cell.wire import canonical, sha

H = "a" * 64


def tensors(kind, label, width=3, classes=2):
    def zeros(*shape):
        return np.zeros(shape, dtype=np.float32)
    t = {"base.weight": zeros(classes, width),
         "base.bias": np.array([np.log(9.0), 0] if label == 0 else [0, np.log(9.0)], dtype=np.float32)}
    if kind in ("gated", "low_rank"):
        t.update({"down.weight": zeros(2, width), "down.bias": zeros(2),
                  "up.weight": zeros(classes, 2)})
        if kind == "gated":
            t.update({"gate.weight": zeros(classes, width), "gate.bias": zeros(classes)})
    elif kind == "sparse_expert":
        t.update({"router.weight": zeros(2, width), "router.bias": zeros(2)})
        for i in (0, 1):
            t[f"experts.{i}.weight"] = zeros(classes, width)
            t[f"experts.{i}.bias"] = zeros(classes)
    return t


def make_complete_study(root: Path):
    producer = make_study(root)
    plan_path = root / "manifest.json"
    plan = json.loads(plan_path.read_bytes())
    plan["steps"] = 3
    plan_path.write_bytes(canonical(plan))
    source = [json.loads(s) for s in (root / "dataset.jsonl").read_bytes().splitlines()]
    features = np.arange(len(source) * 3, dtype=np.float32).reshape(len(source), 3) / 50
    feat_raw = save({"features": features})
    feature_rows = [{"case_id": r["case_id"], "group": r["group"], "split": r["split"],
                     "cell": r["cell"], "scope": r["scope"], "observed_at": r["observed_at"],
                     "input_sha256": sha(canonical([r["scope"], r["text"]]))} for r in source]
    stem = sha(canonical(plan["model"]))
    fd = producer / "frozen-features"
    fd.mkdir()
    (fd / "features.safetensors").write_bytes(feat_raw)
    fm = {"schema": "hepta.offline-frozen-features.v1", "rows": feature_rows,
          "contains_labels": False, "production_accepted": False,
          "simulated_encoder": False, "file_sha256": sha(feat_raw), "file_bytes": len(feat_raw),
          "shape": list(features.shape), "dtype": "float32", "tensor_bytes": features.nbytes,
          "tensor_sha256": sha(canonical(["torch.float32", list(features.shape)]) + features.tobytes()),
          "binding": {"stem_sha256": stem, "dataset_sha256": plan["dataset"]["sha256"],
                      "manifest_sha256": sha(plan_path.read_bytes()),
                      "producer_source_sha256": H,
                      "feature_profile_sha256": sha(canonical({"width": 3,
                          "representation": "masked_mean_float32", "model": stem,
                          "maximum_tokens": 512}))}}
    (fd / "manifest.json").write_bytes(canonical(fm))
    report_path = producer / "report.json"
    report = json.loads(report_path.read_bytes())
    report["manifest_sha256"] = sha(plan_path.read_bytes())
    report["encoding"]["model_digest"] = stem
    report["frozen_features"] = {"manifest_sha256": sha((fd / "manifest.json").read_bytes()),
                                 "relative_path": "frozen-features", "simulated_encoder": False}
    report["training"] = {}
    for kind in ARMS:
        cost_rows = []
        for cell in (0, 1):
            t = tensors(kind, cell)
            raw = save(t)
            count = sum(v.size for v in t.values())
            param_sha = sha(canonical({key: sha(canonical(["torch.float32", list(t[key].shape)])
                                                + t[key].tobytes(order="C")) for key in sorted(t)}))
            params = {"parameters": count, "parameter_bytes": count * 4, "sha256": param_sha}
            roles = {}
            for role in ("learned", "frozen"):
                rel = f"cell-{cell}/{role}"
                where = producer / "heads" / kind / rel
                where.mkdir(parents=True)
                (where / "weights.safetensors").write_bytes(raw)
                binding = {"logical_cell": str(cell), "stem_sha256": stem,
                           "dataset_sha256": plan["dataset"]["sha256"], "scope": "research"}
                man = {"schema": "hepta.offline-cell-head.v1",
                       "production_accepted": False, "optimizer_state_included": False,
                       "binding": binding, "architecture": {"kind": kind, "width": 3, "classes": 2},
                       "parameters": params, "weights_sha256": sha(raw), "weights_bytes": len(raw)}
                (where / "manifest.json").write_bytes(canonical(man))
                roles[role] = {"relative_path": rel, "binding": binding,
                               "manifest_sha256": sha((where / "manifest.json").read_bytes()),
                               "weights_sha256": sha(raw), "parameter_bytes": count * 4}
            cost_rows.append({"cell": cell, "steps": 3, "parameters": count,
                              "parameter_bytes": count * 4, "sha256": param_sha,
                              "minibatch_sha256": H,
                              "frozen": params, "offline_head_artifacts": roles})
        report["training"][kind] = cost_rows
    report_path.write_bytes(canonical(report))
    return producer


def checked(root):
    p = root / "producer"
    return replay(root / "manifest.json", p, sha((p / "report.json").read_bytes()))


class PhysicalReplayTests(unittest.TestCase):
    def test_independent_numpy_replay_actual_artifact_formulas(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_complete_study(root)
            result = checked(root)
            self.assertEqual(result["checked_prediction_vectors"], 32)
            self.assertEqual(result["physical_head_checkpoint_count"], 16)
            self.assertLess(result["max_prediction_probability_abs_error"], 1e-6)
            self.assertFalse(result["production_accepted"])
            self.assertFalse(result["independent_future_ndu_verified"])

    def test_random_real_head_formulas_produce_normalized_distributions(self):
        rng = np.random.default_rng(20261014)
        for kind in ARMS:
            with self.subTest(kind=kind):
                t = tensors(kind, 0)
                for key in t:
                    t[key] = rng.normal(0, .05, size=t[key].shape).astype(np.float32)
                x = rng.normal(size=(7, 3)).astype(np.float32)
                output = predict(x, tensor_set(save(t), kind, width=3, classes=2), kind)
                self.assertEqual(output.shape, (7, 2))
                self.assertTrue(np.allclose(output.sum(axis=1), 1, atol=1e-6))

    def test_changed_weight_rehashed_at_each_layer_rejected_by_forward(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = make_complete_study(root)
            wpath = p / "heads" / "gated" / "cell-0" / "learned" / "weights.safetensors"
            t = tensors("gated", 0)
            t["base.bias"][:] = [0.0, np.log(9.0)]  # predicts other class for cell 0
            raw = save(t)
            wpath.write_bytes(raw)
            mpath = wpath.parent / "manifest.json"
            m = json.loads(mpath.read_bytes())
            changed_param_sha = sha(canonical({key: sha(canonical(["torch.float32", list(t[key].shape)])
                                                        + t[key].tobytes(order="C")) for key in sorted(t)}))
            m["weights_sha256"], m["weights_bytes"] = sha(raw), len(raw)
            m["parameters"]["sha256"] = changed_param_sha
            mpath.write_bytes(canonical(m))
            rpath = p / "report.json"
            r = json.loads(rpath.read_bytes())
            r["training"]["gated"][0]["sha256"] = changed_param_sha
            receipt = r["training"]["gated"][0]["offline_head_artifacts"]["learned"]
            receipt["weights_sha256"] = sha(raw)
            receipt["manifest_sha256"] = sha(mpath.read_bytes())
            rpath.write_bytes(canonical(r))
            with self.assertRaisesRegex(PreflightError, "logits disagree"):
                checked(root)

    def test_missing_checkpoint_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = make_complete_study(root)
            (p / "heads" / "linear" / "cell-1" / "frozen" / "weights.safetensors").unlink()
            with self.assertRaisesRegex(PreflightError, "physical file missing"):
                checked(root)

    def test_rehashed_feature_row_swap_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = make_complete_study(root)
            mpath = p / "frozen-features" / "manifest.json"
            m = json.loads(mpath.read_bytes())
            m["rows"][4], m["rows"][5] = m["rows"][5], m["rows"][4]
            mpath.write_bytes(canonical(m))
            rpath = p / "report.json"
            r = json.loads(rpath.read_bytes())
            r["frozen_features"]["manifest_sha256"] = sha(mpath.read_bytes())
            rpath.write_bytes(canonical(r))
            with self.assertRaisesRegex(PreflightError, "row drift"):
                checked(root)

    def test_rehashed_wrong_feature_profile_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = make_complete_study(root)
            mpath = p / "frozen-features" / "manifest.json"
            m = json.loads(mpath.read_bytes())
            m["binding"]["feature_profile_sha256"] = "c" * 64
            mpath.write_bytes(canonical(m))
            rpath = p / "report.json"
            r = json.loads(rpath.read_bytes())
            r["frozen_features"]["manifest_sha256"] = sha(mpath.read_bytes())
            rpath.write_bytes(canonical(r))
            with self.assertRaisesRegex(PreflightError, "content/binding changed"):
                checked(root)

    def test_unfair_head_steps_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = make_complete_study(root)
            path = p / "report.json"
            r = json.loads(path.read_bytes())
            r["training"]["linear"][1]["steps"] = 10
            path.write_bytes(canonical(r))
            with self.assertRaisesRegex(PreflightError, "unfair"):
                checked(root)

    def test_fake_checkpoint_parameter_count_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = make_complete_study(root)
            path = p / "report.json"
            r = json.loads(path.read_bytes())
            r["training"]["linear"][1]["parameters"] += 7
            path.write_bytes(canonical(r))
            with self.assertRaisesRegex(PreflightError, "parameter"):
                checked(root)


if __name__ == "__main__":
    unittest.main()
