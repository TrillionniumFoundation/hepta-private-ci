import copy
import unittest

from .model_heads import fit_heads, head_score, parameter_digest
from .model_protocol import cases, digest


def training_rows():
    rows = []
    for index, case in enumerate(cases("train")):
        for tick in (0, 2, 3):
            rows.append({"case_id": case["goal"]["task_id"], "source_group": case["source_group"],
                         "split": "train", "tick": tick, "feature": [float(tick), float(index % 2)],
                         "feature_operation_id": str(index), "label": bool(index % 2),
                         "label_operation_id": str(index), "evidence_sha256": digest([tick])})
    return rows


class HeadsTests(unittest.TestCase):
    def test_fit_changes_actual_weights_and_binds_training(self):
        rows = training_rows()
        heads = fit_heads(rows, "a" * 64)
        self.assertEqual(len({head["adapter_sha256"] for head in heads}), 3)
        for head in heads:
            self.assertTrue(any(abs(x) > 0.01 for x in head["coefficients"]))
            self.assertLess(head_score(head, [0.0, 0.0], "a" * 64), head_score(head, [0.0, 1.0], "a" * 64))
            self.assertFalse(head["base_weights_updated"])
            self.assertEqual(head["training_data_sha256"], digest(rows))

    def test_confirmation_cannot_be_relabeled_training(self):
        rows = training_rows()
        leaked = cases("confirmation")[0]
        rows[0].update(case_id=leaked["goal"]["task_id"], source_group="train/synthetic-template/0")
        with self.assertRaises(ValueError):
            fit_heads(rows, "a" * 64)
        rows = training_rows()
        rows[0]["split"] = "calibration"
        with self.assertRaises(ValueError):
            fit_heads(rows, "a" * 64)

    def test_missing_labels_and_tampered_weights_fail_closed(self):
        rows = training_rows()
        with self.assertRaises(ValueError):
            fit_heads(rows[:-1], "a" * 64)
        heads = fit_heads(rows, "a" * 64)
        head = copy.deepcopy(heads[0])
        head["bias"] += 1
        with self.assertRaises(ValueError):
            head_score(head, [0, 1], "a" * 64)
        with self.assertRaises(ValueError):
            head_score(heads[0], [0, 1], "b" * 64)

    def test_changed_metadata_does_not_count_as_distinct_fitted_parameters(self):
        original = fit_heads(training_rows(), "a" * 64)[0]
        changed = copy.deepcopy(original)
        changed["seed"] += 1
        changed["adapter_sha256"] = digest({key: value for key, value in changed.items() if key != "adapter_sha256"})
        self.assertNotEqual(original["adapter_sha256"], changed["adapter_sha256"])
        self.assertEqual(parameter_digest(original), parameter_digest(changed))


if __name__ == "__main__":
    unittest.main()
