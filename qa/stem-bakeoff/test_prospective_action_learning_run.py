import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from bind_operational_field_labels import bind_labels
from long_document_sources import canonical, sha
from operational_feature_availability import availability_record
from operational_field_plan import field_inputs, source_hashes
from operational_source_regions import ACTION_PREFIX
from prospective_action_learning_run import CONDITIONS, infer_all, prepare_all, verify_inference, verify_preparation
from cell_action_prepare import prepare_action_curve


def write(path, value):
    Path(path).write_bytes(canonical(value))


def fixture(root, *, train_groups=8, empty_calibration=False):
    rows, registry = [], []
    roles = [("train", "scrapy", train_groups), ("tuning", "luigi", 4), ("calibration", "thefuck", 4), ("holdout", "fastapi", 3)]
    for role, project, count in roles:
        for i in range(count):
            tag, group, source = f"{role}_{i}", f"bugsinpy/{project}/{i+1}", f"source-{role}-{i}"
            change = f"diff --git a/value.py b/value.py\n--- a/value.py\n+++ b/value.py\n@@ -1 +1 @@\n-before_{tag}(x)\n+after_{tag}(x)\n"
            prefix = ACTION_PREFIX+change
            text = prefix+"\nACTION\nCOMMAND pytest tests/test_value.py\n"
            start = len(text)
            text += f"TEST SOURCE tests/test_value.py\ndef test_{tag}():\n    assert after_{tag}(1) == 2\n"
            rows.append({"source_id": source, "group_id": group, "repo": project, "split": role,
                "text": text, "text_utf8_sha256": sha(text.encode()), "text_utf8_bytes": len(text.encode()),
                "input_template": "operational_single_action_v1", "input_regions": {"change": [len(ACTION_PREFIX), len(prefix)], "action": [start, len(text)]},
                "source_version": {"fixture": tag}, "labels": {"action_usefulness": None}})
            label = None if (role == "holdout" and i == 0) or (role == "calibration" and empty_calibration) else i % 2
            registry.append({"group_id": group, "repo": project, "split": role,
                "actions": [{"key": tag, "source_id": source, "label": label}]})
    inputs = root/"inputs.json"
    original = {"rows": rows, "selected_tasks": ["action_usefulness"], "all_labels_unobserved": True}
    write(inputs, original)
    data = copy.deepcopy(original)
    data.update(input_dataset_sha256=sha(inputs.read_bytes()), proposal_registry=registry,
                all_proposed_actions_retained=True, post_outcome_candidate_selection=False)
    for row, group in zip(data["rows"], registry):
        row["labels"] = {"action_usefulness": group["actions"][0]["label"]}
        row["outcome_provenance"] = {"fixture": True}
    directory = root/"dataset"
    directory.mkdir()
    dataset = directory/"dataset.json"
    write(dataset, data)
    write(directory/"audit.json", {"fixture": True})
    write(directory/"manifest.json", {"files": {p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size} for p in directory.iterdir()}})
    mapping, _ = field_inputs(original)
    specs = {}
    for name in CONDITIONS:
        parent = root/("parent-"+name)
        parent.mkdir()
        width = 3 if name == "identifier_overlap3" else 770
        values = np.random.default_rng(13).normal(size=(len(rows), width)).astype(np.float32)
        mask, reasons = [True]*len(rows), [None]*len(rows)
        if name == "identifier_overlap3":
            mask[-1], reasons[-1], values[-1] = False, "fixture unavailable field", np.nan
        with (parent/"features.npz").open("wb") as stream: np.savez_compressed(stream, features=values)
        definition = {"schema": "explicit-unit-fixture", "condition": name}
        identity = sha(canonical(definition))
        plan = {"dataset_sha256": sha(inputs.read_bytes()), "source_ids": [r["source_id"] for r in rows],
                "feature_definition": definition, "feature_identity": identity, "source_code_sha256": source_hashes()}
        write(parent/"plan.json", plan)
        write(parent/"source-bindings.json", mapping)
        write(parent/"feature-availability.json", availability_record(plan["source_ids"], mask, reasons))
        report = {"plan": plan, "condition": name, "feature_identity": identity, "feature_shape": list(values.shape),
            "feature_tensor_sha256": sha(values.tobytes()), "feature_archive_sha256": sha((parent/"features.npz").read_bytes()),
            "feature_archive_bytes": (parent/"features.npz").stat().st_size, "retained_global_bytes": values.nbytes,
            "source_record_digests": [sha(canonical(item)) for item in mapping],
            "source_bindings_sha256": sha((parent/"source-bindings.json").read_bytes()),
            "feature_availability_sha256": sha((parent/"feature-availability.json").read_bytes()),
            "available_feature_rows": sum(mask), "unavailable_feature_rows": len(mask)-sum(mask), "encoder_forward_calls": 0}
        write(parent/"report.json", report)
        write(parent/"manifest.json", {p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size} for p in parent.iterdir()})
        alias = root/("alias-"+name)
        bind_labels(inputs, dataset, parent, alias, expected_report_sha256=sha((parent/"report.json").read_bytes()), dataset_sha256=sha(dataset.read_bytes()))
        specs[name] = {"directory": str(alias), "report_sha256": sha((alias/"report.json").read_bytes())}
    config = root/"config.json"
    write(config, {"dataset": str(dataset), "dataset_sha256": sha(dataset.read_bytes()),
                   "input_dataset_sha256": sha(inputs.read_bytes()), "features": specs})
    return config


class ProspectiveLearningDriverTests(unittest.TestCase):
    def test_all_three_seal_before_label_free_inference_including_unknowns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = fixture(root)
            prepared = prepare_all(config, root/"prepared")
            self.assertEqual(verify_preparation(root/"prepared"), prepared)
            self.assertEqual([r["status"] for r in prepared["conditions"]], ["complete"]*3)
            count = prepared["conditions"][0]["counts"]["by_role"]["holdout"]
            self.assertEqual((count["proposed_actions"], count["feature_available_actions"], count["valid_outcome_actions"]), (3, 2, 2))
            inferred = infer_all(root/"prepared", root/"inference")
            self.assertEqual(verify_inference(root/"inference"), inferred)
            self.assertEqual([r["rows"] for r in inferred["conditions"]], [2, 3, 3])
            self.assertFalse(inferred["plan"]["query_outcomes_used_or_emitted"])
            for record in inferred["conditions"]:
                child = json.loads((Path(record["inference_dir"])/"report.json").read_bytes())
                self.assertNotIn("labels", child)
                self.assertIn("source-holdout-0", child["source_ids"])
                self.assertEqual(len(child["runs"]), 3)
                for run in child["runs"]:
                    self.assertTrue(run["arms"]["linear"]["fresh_process"]["bitwise_equal_logits_and_probabilities"])
            extra = root/"prepared/preparations/identifier_hash770/unsealed-extra"
            extra.write_bytes(b"changed")
            with self.assertRaises(ValueError): infer_all(root/"prepared", root/"bad-inference")
            self.assertFalse((root/"bad-inference").exists())

    def test_empty_labelled_role_remains_explicit_and_does_not_fit_or_infer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = fixture(root, empty_calibration=True)
            with patch("prospective_action_learning_run.prepare_action_curve", side_effect=AssertionError("no fit")):
                report = prepare_all(config, root/"prepared")
            self.assertEqual([r["reason"] for r in report["conditions"]], ["empty_available_labelled_role"]*3)
            with patch("prospective_action_learning_run.predict_action_rows", side_effect=AssertionError("no prediction")):
                result = infer_all(root/"prepared", root/"inference")
            self.assertEqual([r["inference_dir"] for r in result["conditions"]], [None]*3)
            self.assertEqual(verify_inference(root/"inference"), result)

    def test_mutated_configuration_during_preparation_cannot_close_global_barrier(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = fixture(root, train_groups=2)
            def changed(*args, **kwargs):
                result = prepare_action_curve(*args, **kwargs)
                config.write_bytes(config.read_bytes()+b" ")
                return result
            with patch("prospective_action_learning_run.prepare_action_curve", side_effect=changed), self.assertRaisesRegex(ValueError, "changed"):
                prepare_all(config, root/"prepared")
            self.assertFalse((root/"prepared/seal.json").exists())
            with self.assertRaises(FileNotFoundError): infer_all(root/"prepared", root/"inference")
            self.assertFalse((root/"inference").exists())


if __name__ == "__main__":
    unittest.main()
