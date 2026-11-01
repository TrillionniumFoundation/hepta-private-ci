"""Local contract tests use seed 101; registered final seeds remain untouched."""

import argparse
import json
import unittest
from collections import UserDict
from pathlib import Path

import numpy as np

from language_data import SEEDS, digest, execute, generate, parse_key
from language_models import Baseline, batch_inputs


class LanguageContracts(unittest.TestCase):
    def test_tokenizer_mapping_batches_and_plain_features(self):
        inputs = UserDict(input_ids=np.arange(12).reshape(4, 3), attention_mask=np.ones((4, 3)))
        self.assertNotIsInstance(inputs, dict)
        index = np.array([3, 1])
        actual = batch_inputs(inputs, index)
        for key in inputs:
            np.testing.assert_array_equal(actual[key], inputs[key][index])
        np.testing.assert_array_equal(batch_inputs(inputs["input_ids"], slice(1, 3)), inputs["input_ids"][1:3])

    def test_generation_and_template_separation(self):
        data = generate(101, "facts")
        self.assertNotIn(101, SEEDS)
        self.assertEqual(data, generate(101, "facts"))
        self.assertNotEqual(digest(data), digest(generate(102, "facts")))
        groups = [{r["query"] for r in data[k]} for k in ("train", "validation", "test")]
        self.assertFalse(groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])

    def test_exact_memory_cannot_read_future_or_unknown(self):
        data = generate(101, "facts")
        old = [r for r in data["sources"] if r["phase"] == 0]
        baseline = Baseline("exact_kv").fit(data["train"], old, None, 101)
        before = baseline.predict([r["query"] for r in data["test"]])
        self.assertEqual(before.tolist(), [r["label"] if r["phase"] == 0 else -1 for r in data["test"]])
        baseline.fit(data["train"], data["sources"], None, 101)
        self.assertEqual(baseline.predict([r["query"] for r in data["test"]]).tolist(), [r["label"] for r in data["test"]])
        self.assertEqual(baseline.predict([r["query"] for r in data["unknown"]]).tolist(), [-1] * len(data["unknown"]))

    def test_source_text_controls_labels(self):
        data = generate(101, "facts")
        source = dict(data["sources"][0])
        source["text"] = source["text"].replace(f"value {source['label']}", f"value {(source['label'] + 1) % 8}")
        baseline = Baseline("exact_kv").fit(data["train"], [source], None, 101)
        self.assertEqual(baseline.predict([source["text"]]).tolist(), [(source["label"] + 1) % 8])
        self.assertIsNone(parse_key("case amber marker harbor"))

    def test_real_numpy_updates_and_independent_executor(self):
        rows = [{"query": f"case item{i} marker", "label": i % 8} for i in range(16)]
        features = np.eye(16)
        for kind in ("feature_nearest", "feature_ridge", "fast_weights"):
            model = Baseline(kind).fit(rows, [], features, 101)
            self.assertEqual(model.predict([r["query"] for r in rows], features).tolist(), [r["label"] for r in rows])
        self.assertEqual([execute(i, 7, -3) for i in range(8)], [4, 10, -21, -3, 7, 7, -3, 10])
        self.assertIsNone(execute(-1, 2, 3))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LanguageContracts)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if args.output:
        args.output.write_text(json.dumps({"tests_run": result.testsRun, "successful": result.wasSuccessful(),
            "failures": [str(x) for x in result.failures], "errors": [str(x) for x in result.errors],
            "pretrained_lora_executed": False, "final_registered_seeds_evaluated": False}, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
