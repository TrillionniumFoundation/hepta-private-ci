"""Mechanics-only gates for externally supplied frozen-vector cohorts."""
import json
import unittest

from associative_shadow_gate import admit, compare, cosine_neighbor, read_jsonl


def rows():
    data = []
    for split, count, clock in (("train", 12, 10), ("future", 4, 100)):
        for kind in ("semantic", "procedural"):
            for index in range(count):
                signal = (index + 1 + (20 if split == "future" else 0))/40
                data.append({
                    "split": split, "identity": f"{split}:{kind}:{index}",
                    "scope": "scope", "family": f"{split}:{kind}:{index}",
                    "root": f"root:{split}:{kind}:{index}", "kind": kind,
                    "encoder_identity": "frozen-encoder-test",
                    "observed_at": clock + index,
                    "cue": [float(kind == "semantic"), float(kind == "procedural"),
                            signal, 0.5],
                    "value": [0.0, 0.0, signal,
                              signal if kind == "semantic" else -signal],
                })
    return data


def cohort(value):
    return admit(value, scope="scope", encoder_identity="frozen-encoder-test",
                 train_through=30, future_after=70,
                 admission_digest="self-attested-test-cut")


class ShadowGateTests(unittest.TestCase):
    def test_real_tensor_optimization_and_vector_controls(self):
        result = compare(cohort(rows()), steps=32)
        self.assertEqual(result["train_count"], 24)
        self.assertEqual(result["future_count"], 8)
        self.assertIn("typed_cosine_neighbor", result["mean_squared_error"])
        self.assertFalse(result["strong_text_rag_executed"])
        self.assertFalse(result["superiority_claim"])

    def test_source_root_leak_fails(self):
        value = rows()
        value[-1]["root"] = value[0]["root"]
        with self.assertRaisesRegex(ValueError, "leakage"):
            cohort(value)

    def test_family_leak_fails(self):
        value = rows()
        value[-1]["family"] = value[0]["family"]
        with self.assertRaisesRegex(ValueError, "leakage"):
            cohort(value)

    def test_training_cannot_see_future(self):
        value = rows()
        value[0]["observed_at"] = 200
        with self.assertRaisesRegex(ValueError, "training observation"):
            cohort(value)

    def test_future_cannot_enter_past(self):
        value = rows()
        value[-1]["observed_at"] = 10
        with self.assertRaisesRegex(ValueError, "outside declared window"):
            cohort(value)

    def test_exact_duplicate_example_fails(self):
        value = rows()
        for field in ("cue", "value", "kind"):
            value[-1][field] = value[0][field]
        with self.assertRaisesRegex(ValueError, "repeated training"):
            cohort(value)

    def test_encoder_mismatch_fails(self):
        value = rows()
        value[-1]["encoder_identity"] = "other"
        with self.assertRaisesRegex(ValueError, "incompatible"):
            cohort(value)

    def test_nonfinite_vector_fails(self):
        value = rows()
        value[-1]["cue"][1] = float("nan")
        with self.assertRaisesRegex(ValueError, "invalid vector"):
            cohort(value)

    def test_duplicate_json_keys_fail(self):
        item = json.dumps(rows()[0])
        item = item.replace('"split":', '"split":"train","split":', 1)
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            read_jsonl((item + "\n" + json.dumps(rows()[1])).encode(),
                       scope="scope", encoder_identity="frozen-encoder-test",
                       train_through=30, future_after=70,
                       admission_digest="self-attested-test-cut")

    def test_typed_neighbor_has_no_cross_kind(self):
        value = cohort(rows())
        example = next(r for r in value.future if r.kind == "procedural")
        self.assertEqual(len(cosine_neighbor(value.train, example, typed=True)), 4)


if __name__ == "__main__":
    unittest.main()
