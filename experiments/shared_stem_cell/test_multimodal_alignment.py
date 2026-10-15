"""Deterministic source-disjoint geometric controls, not pretrained-model efficacy."""
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from multimodal_alignment import ContractError, canonical, load_pinned_document, load_pinned_jsonl, predict, sha, train
from multimodal_alignment_evaluator import evaluate


def pin(x):
    return hashlib.sha256(x.encode()).hexdigest()


def feature(modality, input_id, encoder, values):
    return {"modality": modality, "input_sha256": pin(input_id),
            "encoder_sha256": pin(encoder), "values": list(values)}


def study():
    train_rows, predict_rows, target_rows = [], [], []
    for i in range(36):
        angle = 2 * math.pi * (i + 0.17) / 36
        a, b = round(math.cos(angle), 5), round(math.sin(angle), 5)
        base = {"case_id": "train-" + str(i), "group_id": "train-group-" + str(i // 3),
                "scope": "scope_A", "observed_at": i + 1, "split": "train"}
        train_rows.append({**base, "source": feature("image", "train-img-" + str(i), "image-model", (a,b)),
                           "target": feature("text", "train-txt-" + str(i), "text-model", (b,-a))})
    for i in range(10):
        angle = 2 * math.pi * (i + 0.36) / 10
        a, b = round(math.cos(angle), 5), round(math.sin(angle), 5)
        base = {"case_id": "future-" + str(i), "group_id": "future-group-" + str(i),
                "scope": "scope_A", "observed_at": 200+i, "split": "future"}
        source = feature("image", "future-img-" + str(i), "image-model", (a,b))
        target = feature("text", "future-txt-" + str(i), "text-model", (b,-a))
        predict_rows.append({**base, "source": source})
        target_rows.append({**base, "target": target,
                            "source_input_sha256": source["input_sha256"]})
    return train_rows, predict_rows, target_rows


class AlignmentContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        torch.set_num_threads(1)

    def setUp(self):
        self.training, self.future, self.targets = study()
        self.fit = train(self.training, pin("train-file"))
        self.predictions = predict(self.fit, self.future, pin("fitted-artifact"), pin("future-file"))

    def test_fit_is_train_only_and_validates_model_weights(self):
        self.assertEqual(self.fit["train_examples"], 36)
        self.assertEqual(set(self.fit["bridges"]), {"fitted", "rotated_target_control", "unaligned_identity"})
        self.assertEqual((self.fit["source_width"], self.fit["target_width"]), (2, 2))
        self.assertFalse(self.fit["model_admission_verified"])
        self.assertFalse(self.fit["production_accepted"])

    def test_independent_future_geometry_and_negative_control(self):
        report = evaluate(self.predictions, self.targets, pin("predictions"), pin("targets"))
        self.assertGreater(report["arms"]["fitted"]["mean_cosine"], 0.999)
        self.assertLess(report["arms"]["rotated_target_control"]["mean_cosine"], -0.99)
        self.assertLess(abs(report["arms"]["unaligned_identity"]["mean_cosine"]), 0.1)
        self.assertGreater(report["arms"]["fitted"]["within_cohort_retrieval_top1"], 0.95)
        self.assertFalse(report["measured_real_model_capability"])
        self.assertFalse(report["production_accepted"])

    def test_phases_are_explicit_and_misrouting_rejected(self):
        changed = copy.deepcopy(self.training)
        changed[0]["split"] = "future"
        with self.assertRaises(ContractError):
            train(changed, pin("train"))
        changed = copy.deepcopy(self.future)
        changed[0]["split"] = "train"
        with self.assertRaises(ContractError):
            predict(self.fit, changed, pin("fit"), pin("future"))

    def test_predict_rejects_target_bearing_input(self):
        contaminated = copy.deepcopy(self.future)
        contaminated[0]["target"] = self.targets[0]["target"]
        with self.assertRaises(ContractError):
            predict(self.fit, contaminated, pin("fit"), pin("future"))

    def test_predict_rejects_train_group_and_same_source(self):
        for field, value in (("group_id", self.training[0]["group_id"]),
                             ("source.input_sha256", self.training[0]["source"]["input_sha256"])):
            corrupted = copy.deepcopy(self.future)
            if field.startswith("source."):
                corrupted[0]["source"]["input_sha256"] = value
            else:
                corrupted[0][field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                predict(self.fit, corrupted, pin("fit"), pin("future"))

    def test_predict_rejects_temporal_scope_and_encoder_drift(self):
        for field, value in (("observed_at", 36), ("scope", "scope_B"),
                             ("source.encoder_sha256", pin("other-encoder"))):
            corrupted = copy.deepcopy(self.future)
            if field.startswith("source."):
                corrupted[0]["source"]["encoder_sha256"] = value
            else:
                corrupted[0][field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                predict(self.fit, corrupted, pin("fit"), pin("future"))

    def test_fit_rejects_identity_drift_bad_training_and_unbounded_alpha(self):
        for field, value in (("source.encoder_sha256", pin("other-image")),
                             ("target.encoder_sha256", pin("other-text")),
                             ("source.modality", "text")):
            corrupted = copy.deepcopy(self.training)
            role, name = field.split(".")
            corrupted[0][role][name] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                train(corrupted, pin("train"))
        for penalty in (0, -1.0, float("nan"), True, 1000):
            with self.subTest(penalty=penalty), self.assertRaises(ContractError):
                train(self.training, pin("train"), alpha=penalty)

    def test_fit_artifact_tamper_detected(self):
        changed = copy.deepcopy(self.fit)
        changed["bridges"]["fitted"]["rows"][0][0] += 0.5
        with self.assertRaises(ContractError):
            predict(changed, self.future, pin("fit"), pin("future"))

    def test_evaluator_requires_complete_sealed_coverage(self):
        changed = copy.deepcopy(self.predictions)
        changed["predictions"] = changed["predictions"][:-1]
        with self.assertRaises(ContractError):
            evaluate(changed, self.targets, pin("pred"), pin("targets"))
        changed = copy.deepcopy(self.predictions)
        changed["predictions"][1] = changed["predictions"][0]
        with self.assertRaises(ContractError):
            evaluate(changed, self.targets, pin("pred"), pin("targets"))

    def test_evaluator_rejects_laundered_target_and_temporal_reuse(self):
        for field, value in (("target.encoder_sha256", pin("unrelated-stem")),
                             ("observed_at", 2), ("group_id", self.training[0]["group_id"])):
            altered = copy.deepcopy(self.targets)
            if field.startswith("target."):
                altered[0]["target"]["encoder_sha256"] = value
            else:
                altered[0][field] = value
                self.predictions["predictions"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                evaluate(self.predictions, altered, pin("pred"), pin("targets"))
            self.predictions = predict(self.fit, self.future, pin("fit"), pin("future"))

    def test_evaluator_rejects_train_target_reuse(self):
        altered = copy.deepcopy(self.targets)
        altered[0]["target"]["input_sha256"] = self.training[0]["target"]["input_sha256"]
        with self.assertRaises(ContractError):
            evaluate(self.predictions, altered, pin("pred"), pin("targets"))

    def test_evaluator_rejects_nonfinite_and_missing_control(self):
        for corruption in ("nan", "missing"):
            altered = copy.deepcopy(self.predictions)
            if corruption == "nan":
                altered["predictions"][0]["predictions"]["fitted"][0] = float("nan")
            else:
                del altered["predictions"][0]["predictions"]["rotated_target_control"]
            with self.subTest(corruption=corruption), self.assertRaises(ContractError):
                evaluate(altered, self.targets, pin("pred"), pin("targets"))

    def test_train_does_not_accept_too_few_examples_or_cross_scope(self):
        with self.assertRaises(ContractError):
            train(self.training[:7], pin("train"))
        corrupted = copy.deepcopy(self.training)
        corrupted[3]["scope"] = "scope_B"
        with self.assertRaises(ContractError):
            train(corrupted, pin("train"))

    def test_pinned_three_cli_phases_only_use_declared_inputs(self):
        root = Path(__file__).parent
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            paths = {}
            for name, rows in (("train", self.training), ("future", self.future),
                               ("targets", self.targets)):
                path = tmp / (name + ".jsonl")
                path.write_bytes(b"".join(canonical(row) for row in rows))
                paths[name] = (path, sha(path.read_bytes()))
            bridge, predictions, report = (tmp / (name + ".json") for name in ("bridge", "predictions", "report"))
            commands = [
                [sys.executable, str(root / "multimodal_alignment.py"), "fit", "--train", str(paths["train"][0]),
                 "--train-sha256", paths["train"][1], "--output", str(bridge)],
            ]
            for cmd in commands:
                subprocess.run(cmd, check=True, capture_output=True, timeout=40)
            bridge_sha = sha(bridge.read_bytes())
            subprocess.run([sys.executable, str(root / "multimodal_alignment.py"), "predict",
                            "--fit", str(bridge), "--fit-sha256", bridge_sha,
                            "--future-inputs", str(paths["future"][0]),
                            "--future-inputs-sha256", paths["future"][1], "--output", str(predictions)],
                           check=True, capture_output=True, timeout=40)
            pred_sha = sha(predictions.read_bytes())
            subprocess.run([sys.executable, str(root / "multimodal_alignment_evaluator.py"),
                            "--predictions", str(predictions), "--predictions-sha256", pred_sha,
                            "--future-targets", str(paths["targets"][0]),
                            "--future-targets-sha256", paths["targets"][1], "--output", str(report)],
                           check=True, capture_output=True, timeout=40)
            result = load_pinned_document(report, sha(report.read_bytes()))
            self.assertGreater(result["arms"]["fitted"]["mean_cosine"], 0.999)
            with self.assertRaises(ContractError):
                load_pinned_jsonl(paths["train"][0], pin("wrong"))
            with self.assertRaises(ContractError):
                load_pinned_document(bridge, pin("wrong"))


if __name__ == "__main__":
    unittest.main()
