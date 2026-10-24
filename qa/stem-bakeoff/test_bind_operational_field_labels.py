"""Label attachment cannot rebind changed predictor content or source versions."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from bind_operational_field_labels import bind_labels
from export_operational_fields import export_baseline
from long_document_sources import canonical, sha
from operational_feature_availability import load_available_features
from operational_field_plan import create_plan, write_json
from test_operational_field_plan import fixture


def label_fixture(root):
    inputs, tokenizer, acquisition, _, _, _ = fixture(root)
    data = json.loads(inputs.read_bytes())
    data.update({"selected_tasks": ["SECRET_OUTCOME"], "all_labels_unobserved": True})
    for row in data["rows"]: row["labels"] = {"SECRET_OUTCOME": None}
    inputs.write_bytes(canonical(data))
    plan = root / "input-plan"
    create_plan(inputs, tokenizer, acquisition, plan, dataset_sha256=sha(inputs.read_bytes()))
    features = root / "features"
    original = export_baseline(inputs, plan, features, expected_plan_sha256=sha((plan / "plan.json").read_bytes()),
                               kind="identifier_hash770")
    labelled = copy.deepcopy(data)
    labelled.update({"input_dataset_sha256": sha(inputs.read_bytes()), "all_proposed_actions_retained": True,
                     "post_outcome_candidate_selection": False})
    for i, row in enumerate(labelled["rows"]):
        row["labels"], row["outcome_provenance"] = {"SECRET_OUTCOME": i}, {"receipt": str(i)}
    dataset = root / "labelled.json"
    dataset.write_bytes(canonical(labelled))
    return inputs, dataset, features, original, sha((features / "report.json").read_bytes())


class LabelBindingTests(unittest.TestCase):
    def test_consistently_resealed_but_wrong_source_origin_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs, _, features, _, _ = label_fixture(root)
            bindings = json.loads((features / "source-bindings.json").read_bytes())
            bindings[0]["source_version"] = "sha256:" + "0" * 64
            (features / "source-bindings.json").write_bytes(canonical(bindings))
            report = json.loads((features / "report.json").read_bytes())
            report["source_record_digests"] = [sha(canonical(row)) for row in bindings]
            report["source_bindings_sha256"] = sha((features / "source-bindings.json").read_bytes())
            (features / "report.json").write_bytes(canonical(report))
            manifest = json.loads((features / "manifest.json").read_bytes())
            for name in ("source-bindings.json", "report.json"):
                manifest[name] = {"sha256": sha((features / name).read_bytes()), "bytes": (features / name).stat().st_size}
            (features / "manifest.json").write_bytes(canonical(manifest))
            with self.assertRaisesRegex(ValueError, "source text/version"):
                load_available_features(features, inputs, expected_report_sha256=sha((features / "report.json").read_bytes()))

    def test_empty_identifier_rows_retain_full_order_without_entering_loaded_examples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset, tokenizer, acquisition, _, _, _ = fixture(root)
            data = json.loads(dataset.read_bytes())
            row = data["rows"][0]
            old = row["text"]
            new = old.replace("-old_name(value)\n+new_name(value)", "-return False\n+return True")
            delta = len(new) - len(old)
            row["text"], row["text_utf8_sha256"], row["text_utf8_bytes"] = new, sha(new.encode()), len(new.encode())
            row["input_regions"]["change"][1] += delta
            row["input_regions"]["action"] = [value + delta for value in row["input_regions"]["action"]]
            dataset.write_bytes(canonical(data))
            plan_root = root / "new-plan"
            create_plan(dataset, tokenizer, acquisition, plan_root, dataset_sha256=sha(dataset.read_bytes()))
            pin = sha((plan_root / "plan.json").read_bytes())
            for kind in ("identifier_hash770", "identifier_overlap3"):
                output = root / kind
                report = export_baseline(dataset, plan_root, output, expected_plan_sha256=pin, kind=kind)
                self.assertEqual((report["available_feature_rows"], report["unavailable_feature_rows"]), (1, 1))
                values, indices, _, availability = load_available_features(output, dataset,
                    expected_report_sha256=sha((output / "report.json").read_bytes()))
                self.assertTrue(np.isfinite(values).all())
                np.testing.assert_array_equal(indices, [1])
                self.assertEqual(availability["source_ids"], [r["source_id"] for r in data["rows"]])
                with self.assertRaises(ValueError): values.setflags(write=True)

    def test_label_attachment_keeps_exact_payload_identity_and_zero_new_forward_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs, dataset, features, original, pin = label_fixture(root)
            report = bind_labels(inputs, dataset, features, root / "alias",
                                 expected_report_sha256=pin, dataset_sha256=sha(dataset.read_bytes()))
            self.assertEqual(report["feature_identity"], original["feature_identity"])
            self.assertEqual(report["encoder_forward_calls"], 0)
            self.assertEqual((root / "alias/features.npz").read_bytes(), (features / "features.npz").read_bytes())
            loaded, indices, _, _ = load_available_features(root / "alias", dataset,
                expected_report_sha256=sha((root / "alias/report.json").read_bytes()))
            self.assertEqual((loaded.shape, indices.tolist()), ((2, 770), [0, 1]))

    def test_same_text_with_changed_version_or_role_is_not_a_label_only_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs, dataset, features, _, pin = label_fixture(root)
            data = json.loads(dataset.read_bytes())
            for field, value in (("source_version", {"new": "revision"}), ("repo", "different-project")):
                changed = copy.deepcopy(data)
                changed["rows"][0][field] = value
                dataset.write_bytes(canonical(changed))
                with self.assertRaisesRegex(ValueError, "only permitted"):
                    bind_labels(inputs, dataset, features, root / field, expected_report_sha256=pin,
                                dataset_sha256=sha(dataset.read_bytes()))

    def test_mutation_after_capture_cannot_produce_a_completed_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs, dataset, features, _, pin = label_fixture(root)
            def mutate(path, value):
                write_json(path, value)
                if Path(path).name == "label-binding.json": dataset.write_bytes(dataset.read_bytes() + b" ")
            with patch("bind_operational_field_labels.write_json", side_effect=mutate), self.assertRaisesRegex(ValueError, "changed"):
                bind_labels(inputs, dataset, features, root / "alias", expected_report_sha256=pin,
                            dataset_sha256=sha(dataset.read_bytes()))
            self.assertFalse((root / "alias/report.json").exists())


if __name__ == "__main__":
    unittest.main()
