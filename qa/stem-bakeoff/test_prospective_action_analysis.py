"""Whole-proposal scoring and fixed contrasts from fabricated sealed predictions."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from bind_operational_field_labels import bind_labels
from cell_learning_models import canonical
from prospective_action_analysis import analyze, score_verified
from prospective_analysis_artifacts import CapturedArtifacts, load_condition, validate_dataset
from prospective_analysis_plan import CONDITIONS, code_hashes, freeze_plan, sha
from test_prospective_analysis_artifacts import prediction_artifacts, seal, write
from test_prospective_analysis_plan import fixture


class ProspectiveAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        _, self.plan, self.dataset, self.matrices = fixture()
        self.plan["code_sha256"] = code_hashes()
        # The wrapper has its own real-fit integration gate; these deliberately
        # fabricated predictions isolate analysis and its independent pin checks.
        self.wrapper = patch("prospective_action_analysis.verify_inference",
            side_effect=lambda root: json.loads((Path(root)/"report.json").read_bytes()))
        self.wrapper.start()
        self.addCleanup(self.wrapper.stop)

    def tearDown(self):
        self.temporary.cleanup()

    def artifacts(self, omitted=()):
        global_root = self.root/"global"
        global_root.mkdir()
        records = [prediction_artifacts(global_root/name, self.plan, self.dataset, self.matrices, name,
            omitted if name == "identifier_hash770" else ()) for name in CONDITIONS]
        barrier = global_root/"preparation-barrier"
        barrier.mkdir()
        write(barrier/"report.json", {"plan": {"input_file_pins": {}}, "conditions": records})
        links = {"preparation_root": str(barrier), "preparation_report_sha256": sha((barrier/"report.json").read_bytes()),
                 "preparation_seal_sha256": seal(barrier)}
        ip = {**links, "dataset_sha256": sha(canonical(self.dataset)), "input_dataset_sha256": self.plan["input_dataset_sha256"]}
        write(global_root/"plan.json", ip)
        write(global_root/"report.json", {"conditions": records, "plan": ip, **links})
        return global_root, seal(global_root), records

    def test_complete_all_arm_analysis_preserves_unknowns_and_all48_groups(self):
        root, global_seal, _ = self.artifacts()
        write(self.root/"dataset.json", self.dataset)
        write(self.root/"plan.json", self.plan)
        # Preparation binds the exact dataset bytes; use the same canonical form.
        (self.root/"dataset.json").write_bytes(canonical(self.dataset))
        result = analyze(self.root/"dataset.json", root, self.root/"plan.json", self.root/"output",
            dataset_sha256=sha((self.root/"dataset.json").read_bytes()),
            analysis_plan_sha256=sha((self.root/"plan.json").read_bytes()), inference_seal_sha256=global_seal,
            inference_report_sha256=sha((root/"report.json").read_bytes()))
        self.assertEqual((result["proposed_holdout_groups"], result["proposed_holdout_actions"]), (48, 96))
        native = result["conditions"]["granite_clean_field770"]["runs"][0]
        self.assertEqual(len(native["variants"]), 15)
        gated, off = (native["variants"][name] for name in ("gated", "gated/parameters_off"))
        self.assertEqual(gated["semantic"]["rows"], 94)
        self.assertEqual(gated["coverage"]["unknown_outcome_feature_rows"], 2)
        self.assertEqual(gated["ranking"]["top_k"]["1"]["known_positive_hit_rate"], 47/48)
        self.assertEqual(gated["ranking"]["top_k"]["1"]["unknown_selections"], 1)
        self.assertEqual((gated["semantic"]["balanced_accuracy"], off["semantic"]["balanced_accuracy"]), (1., .5))
        self.assertTrue(gated["prediction_receipt"]["fresh_process"]["bitwise_equal_logits_and_probabilities"])
        self.assertEqual(native["variants"]["exact"]["semantic"]["coverage"], 0)
        self.assertEqual(len(result["fixed_contrasts"]), 63)
        self.assertTrue(all(c["status"] == "complete" for c in result["fixed_contrasts"]))
        ranking_only = [c for c in result["fixed_contrasts"] if c["definition"]["right"][0] is None]
        self.assertTrue(all(c["result"]["contrasts"]["balanced_accuracy"]["difference"] is None for c in ranking_only))
        common = next(c["result"]["support"] for c in result["fixed_contrasts"]
            if c["definition"]["left"] == ["granite_clean_field770", "gated"]
            and c["definition"]["right"] == ["identifier_hash770", "gated"])
        self.assertEqual(common["common_valid_rows"], 94)
        self.assertFalse(result["holdout_model_selection_performed"])
        self.assertEqual(result["cost"]["new_encoder_calls"], 0)
        self.assertTrue((self.root/"output/seal.json").is_file())

    def test_missing_fixed_seed_never_becomes_zero_or_a_two_seed_comparison(self):
        _, _, records = self.artifacts(omitted={(29, 8)})
        rows, _ = validate_dataset(self.dataset, self.plan)
        loaded = {"unavailable": {}}
        for record in records:
            name = record["name"]
            item = load_condition(CapturedArtifacts(), record, self.plan["conditions"][name], rows, sha(canonical(self.dataset)))
            item.update(preparation_reference={}, inference_reference={})
            loaded[name] = item
        output = self.root/"scores"
        output.mkdir()
        result = score_verified(self.plan, self.dataset, loaded, output)
        missing = [c for c in result["fixed_contrasts"] if c["status"] != "complete"]
        self.assertEqual(len(missing), 9)
        self.assertTrue(all(c["result"] is None for c in missing))
        self.assertTrue(all(c["definition"]["budget"] == 8 for c in missing))
        self.assertTrue(all(m["seeds"] == [29] for c in missing for m in c["missing"]))

    def test_no_valid_outcome_is_unavailable_metrics_but_not_dropped_ranking_groups(self):
        _, _, records = self.artifacts()
        rows, _ = validate_dataset(self.dataset, self.plan)
        record = records[-1]
        native = load_condition(CapturedArtifacts(), record, self.plan["conditions"][record["name"]], rows, sha(canonical(self.dataset)))
        native.update(preparation_reference={}, inference_reference={})
        unknown = copy.deepcopy(self.dataset)
        for row in unknown["rows"]:
            if row["split"] == "holdout": row["labels"]["task"] = None
        for group in unknown["proposal_registry"]:
            if group["split"] == "holdout":
                for action in group["actions"]: action["label"] = None
        loaded = {name: None for name in CONDITIONS}
        loaded.update(granite_clean_field770=native, unavailable={name: {"reason": "fixture unavailable"} for name in CONDITIONS})
        output = self.root/"unknown"
        output.mkdir()
        result = score_verified(self.plan, unknown, loaded, output)
        gated = result["conditions"]["granite_clean_field770"]["runs"][0]["variants"]["gated"]
        self.assertEqual(gated["semantic"]["status"], "unavailable_no_valid_outcome_feature_rows")
        self.assertEqual(gated["ranking"]["proposed_groups"], 48)
        self.assertEqual(gated["ranking"]["top_k"]["1"]["unknown_selections"], 48)
        self.assertEqual(gated["ranking"]["top_k"]["1"]["known_negative_selections"], 0)

    def test_mid_analysis_input_mutation_prevents_completed_report(self):
        root, global_seal, _ = self.artifacts()
        dataset_path = self.root/"dataset.json"
        dataset_path.write_bytes(canonical(self.dataset))
        write(self.root/"plan.json", self.plan)
        original = score_verified
        def mutate(*args):
            result = original(*args)
            dataset_path.write_bytes(dataset_path.read_bytes()+b" ")
            return result
        with patch("prospective_action_analysis.score_verified", side_effect=mutate), self.assertRaisesRegex(ValueError, "pin differs"):
            analyze(dataset_path, root, self.root/"plan.json", self.root/"partial",
                dataset_sha256=sha(dataset_path.read_bytes()), analysis_plan_sha256=sha((self.root/"plan.json").read_bytes()),
                inference_report_sha256=sha((root/"report.json").read_bytes()), inference_seal_sha256=global_seal)
        self.assertFalse((self.root/"partial/report.json").exists())

    def test_actual_tiny_private_fits_cross_the_real_global_barrier_and_analyzer(self):
        from prospective_action_learning_run import infer_all, prepare_all
        from test_prospective_action_learning_run import fixture as learning_fixture
        real = self.root/"real-fixture"
        real.mkdir()
        config_path = learning_fixture(real)
        config = json.loads(config_path.read_bytes())
        input_path, dataset_path = real/"inputs.json", Path(config["dataset"])
        inputs, data = json.loads(input_path.read_bytes()), json.loads(dataset_path.read_bytes())
        # Forty-five source-unavailable proposal groups prove the complete
        # denominator survives a real (small) fitted/inferred condition.
        for i in range(45):
            project = ("ansible", "httpie", "sanic", "cookiecutter", "fastapi")[i % 5]
            data["proposal_registry"].append({"group_id": f"bugsinpy/{project}/empty-{i}",
                "repo": project, "split": "holdout", "actions": []})
        cases = {}
        for group in data["proposal_registry"]:
            before = []
            for action in group["actions"]:
                action.update(recorded_pair_wall_ns=1, physical_command_executions=2, complete_command_observations=2)
                before.append({key: action[key] for key in ("key", "source_id")})
            cases[group["group_id"]] = {"project": group["repo"], "role": group["split"], "actions": before}
        inputs.update(case_bindings=cases, governing_protocol_sha256="e"*64)
        input_path.write_bytes(canonical(inputs))
        data.update(input_dataset_sha256=sha(input_path.read_bytes()), governing_protocol_sha256="e"*64)
        dataset_path.write_bytes(canonical(data))
        write(dataset_path.parent/"manifest.json", {"files": {p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size}
            for p in dataset_path.parent.iterdir() if p.name != "manifest.json"}})
        parents, aliases = {}, {}
        for name in CONDITIONS:
            parent = real/("parent-"+name)
            report = json.loads((parent/"report.json").read_bytes())
            if name == "identifier_overlap3":
                with np.load(parent/"features.npz") as archive: values = archive["features"]
                values[:, 0] = np.clip(values[:, 0], 0, 1)
                np.savez_compressed(parent/"features.npz", features=values)
                report.update(feature_tensor_sha256=sha(values.tobytes()), feature_archive_sha256=sha((parent/"features.npz").read_bytes()),
                              feature_archive_bytes=(parent/"features.npz").stat().st_size)
            report["plan"]["dataset_sha256"] = sha(input_path.read_bytes())
            write(parent/"plan.json", report["plan"]); write(parent/"report.json", report)
            write(parent/"manifest.json", {p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size}
                for p in parent.iterdir() if p.name != "manifest.json"})
            parents[name] = {"directory": str(parent), "report_sha256": sha((parent/"report.json").read_bytes())}
            alias = real/("rebound-"+name)
            bind_labels(input_path, dataset_path, parent, alias, expected_report_sha256=parents[name]["report_sha256"],
                        dataset_sha256=sha(dataset_path.read_bytes()))
            aliases[name] = {"directory": str(alias), "report_sha256": sha((alias/"report.json").read_bytes())}
        freeze_plan(input_path, parents, real/"analysis-plan", expected_inputs_sha256=sha(input_path.read_bytes()))
        config.update(dataset_sha256=sha(dataset_path.read_bytes()), input_dataset_sha256=sha(input_path.read_bytes()), features=aliases)
        write(config_path, config)
        prepare_all(config_path, real/"preparations")
        infer_all(real/"preparations", real/"inferences")
        self.wrapper.stop()
        result = analyze(dataset_path, real/"inferences", real/"analysis-plan/plan.json", real/"analysis",
            dataset_sha256=sha(dataset_path.read_bytes()), analysis_plan_sha256=sha((real/"analysis-plan/plan.json").read_bytes()),
            inference_report_sha256=sha((real/"inferences/report.json").read_bytes()),
            inference_seal_sha256=sha((real/"inferences/seal.json").read_bytes()))
        self.assertEqual(result["proposed_holdout_groups"], 48)
        self.assertEqual(len(result["conditions"]["granite_clean_field770"]["runs"]), 3)
        self.assertEqual(sum(c["status"] == "complete" for c in result["fixed_contrasts"]), 21)
        self.assertTrue(all(run["variants"]["gated"]["prediction_receipt"]["fresh_process"]["bitwise_equal_logits_and_probabilities"]
                            for run in result["conditions"]["granite_clean_field770"]["runs"]))


if __name__ == "__main__":
    unittest.main()
