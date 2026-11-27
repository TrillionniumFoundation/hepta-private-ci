"""Handmade metadata/opaque bytes only: no dataset, model, compiler or training."""

import base64
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


SPEC = importlib.util.spec_from_file_location("codec_d1_analyze", Path(__file__).with_name("analyze.py"))
analyze = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyze)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.roots = [Path(self.tmp.name) / str(i) for i in range(4)]
        self.plan = {"model_seeds": list(analyze.SEEDS), "systems": list(analyze.SYSTEMS),
            "learning_rates": [.001, .003, .01], "batch_size": 64,
            "cpu_seconds_per_system": 10, "operator_units_per_system": 12_000_000_000,
            "data_profile": {"seeds": {"train": 304797655}}, "diagnostic_analysis": {
                "path": "training_diagnostics/codec-d1/analyze.py",
                "sha256": analyze._sha(Path(analyze.__file__).read_bytes())}}
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        output = analyze._encoded({"caption": "handmade", "png_sha256": analyze._sha(png),
            "png_base64": base64.b64encode(png).decode(), "choices": {"text": 0, "image": 0}})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            for i in range(72):
                archive.writestr(f"{i:03d}.png", png)
                archive.writestr(f"{i:03d}.json", output)
            archive.writestr("rng.json", analyze._encoded({"handmade_state": [1, 2], "batches": []}))
            archive.writestr("manifest.json", b"{}")
        self.selections = []
        for i, root in enumerate(self.roots):
            root.mkdir()
            cached = i in (1, 2)
            evidence = {**self.write(root, "trace.zip", buf.getvalue()), "rows": 72}
            model = self.write(root, "model.npz", b"opaque hand model bytes; not an actual NPZ")
            library = self.write(root, "build/libjoint.so", b"opaque nonexecutable library bytes")
            artifacts = {}
            for role in ("pool", "fit", "monitor"):
                manifest = {"hand_role": role}
                metadata = {"split": "train", "training_diagnostic": {
                    "parent_split": "train", "role": role, "parent_manifest": {"hand_parent": True}}}
                artifacts[role] = {"manifest": manifest, "files": [
                    self.write(root, role + ".npz", b"opaque hand tensor bytes"),
                    self.write(root, role + ".metadata.json", analyze._encoded(metadata))]}
            cost = {"prepare_cpu_ns": 2, "cpu_ns": 72 if cached else 144,
                "prepare": {"consumed_units": 3, "totals": {}}, "operator_totals": {"output_bytes": 99}}
            raw = [{"repeat": r, "rows": 72, "mode": "full", "observe": False,
                "budget_violations": 0, "output_evidence": evidence,
                "per_row_cost": {"cpu_ns": [1 if cached else 2] * 72, "work_units": [5] * 72},
                "cost": cost} for r in range(3)]
            candidates = []
            for system in analyze.SYSTEMS:
                for seed in analyze.SEEDS:
                    for lr in self.plan["learning_rates"]:
                        name = f"{system}-{seed}-{lr}"
                        checkpoints = [{"step": step, "loss": .2, "mean_prefix_loss": .3,
                            "model_digest": "model", "content_digest": "content", "moments_digest": "clock-moments",
                            "draws_sha256": "draw", "rng_state": {"state": seed}, "idx": [0], "full_mask": [True]}
                            for step in (1, 32)]
                        prefix = {"candidate": name, "checkpoints": checkpoints, "terminal_updates": 33,
                                  "complete": True, "incomplete_terminal_state": None}
                        candidates.append({"system": system, "seed": seed, "learning_rate": lr, "name": name,
                            "updates": 33, "prefix_checkpoints": checkpoints, "prefix_equivalence_complete": True,
                            "prefix_artifact": self.write(root, name + ".json", analyze._encoded(prefix)),
                            "model_file": model["file"], "model_sha256": model["sha256"], "model_digest": "model"})
            selected = [{**copy.deepcopy(row), "mode": "full", "reference_full_cpu_ns": 2,
                "updates": 35 if cached else 33, "refinement_updates": 2 if cached else 0}
                for row in candidates if row["learning_rate"] == .003]
            report = {"mode": "full", "budget_violations": 0, "output_evidence": evidence, "cost": cost,
                "per_row_cost": {"work_units": [5] * 72}, "decoder_corruption_score_drop": .1,
                "means": {"task_utility": .5 + .01 * cached, "joint_success": .3, "greedy_joint_success": .3,
                          "cpu_net_utility": .4}}
            selection = {"plan": self.plan, "plan_sha256": "plan", "source_commit": "source",
                "sources": {"hand.py": "sourcehash"}, "freeze_sha256": "freeze", "execution_commit": "source",
                "experiment_id": "codec-train-d1", "test_opened": False, "qualification_eligible": False,
                "training_diagnostic": {"schema": "hepta.codec-train-build.v1", "build_index": i,
                    "codec_variant": analyze.ORDER[i], "qualification_eligible": False,
                    "reference_binding": None, "prefix_equivalence_complete": True},
                "common": {"reference_full_cpu_ns": 2, "observed_reference_full_cpu_ns": 1 if cached else 2,
                    "cpu_seconds": 1, "training_diagnostic": {"schema": "hepta.codec-train-inputs.v1",
                        "parent": {"hand_parent": True}, "artifacts": artifacts,
                        "actual_constructor_calls": ["train"], "official_held_out_constructed": False},
                    "bases": {str(seed): {**model, "digest": "base-digest"} for seed in analyze.SEEDS},
                    "calibration_identity": {"inputs_sha256": "inputs"},
                    "calibrations": {str(seed): {"raw_repeats": {"full": raw}} for seed in analyze.SEEDS}},
                "native_library": library["file"], "native_library_sha256": library["sha256"],
                "datasets": {"train": artifacts["fit"]["manifest"], "validation": artifacts["monitor"]["manifest"]},
                "all_validation_candidates": candidates, "selected": selected,
                "budgets": {s: {"total_cap": 12_000_000_000, "consumed_units": 100, "remaining_units": 11_999_999_900} for s in analyze.SYSTEMS},
                "system_cost": {s: {"cpu_seconds": 4 if cached else 5} for s in analyze.SYSTEMS},
                "validation_measures": {s: {str(seed): report for seed in analyze.SEEDS} for s in analyze.SYSTEMS},
                "selection_ready": True}
            if i:
                receipt = {"schema": "hepta.codec-train-reference.v1", "experiment_id": "codec-train-d1",
                    "reference_full_cpu_ns": 2, "first_selection_path": str(self.roots[0] / "selection.json"),
                    "first_selection_sha256": analyze._sha((self.roots[0] / "selection.json").read_bytes()),
                    "plan_sha256": "plan", "source_commit": "source", "freeze_sha256": "freeze"}
                selection["training_diagnostic"]["reference_binding"] = {"receipt": receipt, "sha256": "receipt"}
            self.save(i, selection)
            self.selections.append(selection)

    @staticmethod
    def write(root, name, payload):
        path = root / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(payload)
        return {"file": name, "sha256": analyze._sha(payload), "bytes": len(payload)}

    def save(self, i, selection):
        slot = selection["training_diagnostic"]
        effective = {**self.plan, "output_codec_profile": slot["codec_variant"],
            "diagnostic_build_index": i, "diagnostic_reference": slot["reference_binding"]}
        slot.update(effective_plan=effective, effective_plan_sha256=analyze._sha(analyze._encoded(effective)))
        self.write(self.roots[i], "selection.json", analyze._encoded(selection))

    def test_complete_handmade_audit_and_fixed_pair_direction(self):
        report = analyze.describe_builds(self.roots)
        self.assertTrue(report["audit"]["prefix_complete"])
        self.assertEqual([(r["rowwise_index"], r["cached_index"]) for r in report["pairs"]], [(0, 1), (3, 2)])
        self.assertTrue(all(report["engineering_directions"].values()))
        self.assertEqual(report["pairs"][1]["methods"]["ndu"]["across_seeds"]["selected_updates"]["values"], [2, 2, 2])
        self.assertEqual(report["builds"][0]["methods"]["ndu"]["search_updates"], 297)
        self.assertFalse(report["qualification_eligible"])
        self.assertTrue(report["missing_riskfield"])
        json.dumps(report, allow_nan=False)

    def test_incremental_audit_checks_each_completed_slot_before_next_build(self):
        for count in range(1, 5):
            with self.subTest(count=count):
                self.assertEqual(analyze.audit_builds(self.roots[:count])["calibration_traces_compared"], 9 * count)
        with self.assertRaisesRegex(ValueError, "all four"):
            analyze.describe_builds(self.roots[:3])

    def test_actual_zip_identity_ignores_only_manifest_metadata(self):
        selection = self.selections[3]
        evidence = selection["common"]["calibrations"]["11"]["raw_repeats"]["full"][0]["output_evidence"]
        with zipfile.ZipFile(self.roots[3] / evidence["file"]) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        for changed_output in (False, True):
            members["manifest.json"] = analyze._encoded({"metadata_differs": True})
            if changed_output:
                output = json.loads(members["000.json"])
                output["caption"] = "different actual generated output"
                members["000.json"] = analyze._encoded(output)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as archive:
                for name, value in members.items():
                    archive.writestr(name, value)
            evidence.update(self.write(self.roots[3], evidence["file"], buf.getvalue()))
            self.save(3, selection)
            if changed_output:
                with self.assertRaisesRegex(ValueError, "PNG/JSON/RNG identity"):
                    analyze.audit_builds(self.roots)
            else:
                self.assertTrue(analyze.audit_builds(self.roots)["prefix_complete"])

    def test_available_prefix_mismatch_hard_and_missing32_soft(self):
        selected = self.selections[2]
        row = selected["all_validation_candidates"][0]
        row.update(updates=1, prefix_checkpoints=row["prefix_checkpoints"][:1], prefix_equivalence_complete=False)
        terminal = {key: row["prefix_checkpoints"][0][key] for key in
                    ("model_digest", "moments_digest", "rng_state", "draws_sha256")}
        terminal["updates"] = 1
        row["prefix_artifact"] = self.write(self.roots[2], row["prefix_artifact"]["file"], analyze._encoded({
            "candidate": row["name"], "checkpoints": row["prefix_checkpoints"], "terminal_updates": 1,
            "complete": False, "incomplete_terminal_state": terminal}))
        selected["training_diagnostic"]["prefix_equivalence_complete"] = False
        self.save(2, selected)
        self.assertFalse(analyze.audit_builds(self.roots)["prefix_complete"])
        row["prefix_checkpoints"][0]["moments_digest"] = "changed"
        terminal["moments_digest"] = "changed"
        row["prefix_artifact"] = self.write(self.roots[2], row["prefix_artifact"]["file"], analyze._encoded({
            "candidate": row["name"], "checkpoints": row["prefix_checkpoints"], "terminal_updates": 1,
            "complete": False, "incomplete_terminal_state": terminal}))
        self.save(2, selected)
        with self.assertRaisesRegex(ValueError, "available prefix"):
            analyze.audit_builds(self.roots)

    def test_capability_cap_reference_frozen_and_artifact_failures(self):
        for mutation, message in ((lambda s: s.update(test_opened=True), "identity"),
            (lambda s: s["system_cost"]["ndu"].update(cpu_seconds=10.01), "CPU cap"),
            (lambda s: s["common"].update(reference_full_cpu_ns=1), "fixed first"),
            (lambda s: s.update(source_commit="different"), "frozen binding"),
            (lambda s: s["common"]["training_diagnostic"].update(actual_constructor_calls=["test"]), "capability")):
            with self.subTest(message=message):
                selection = copy.deepcopy(self.selections[3])
                mutation(selection)
                self.save(3, selection)
                with self.assertRaisesRegex(ValueError, message):
                    analyze.audit_builds(self.roots)
        self.save(3, self.selections[3])
        (self.roots[3] / "model.npz").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "artifact hash"):
            analyze.audit_builds(self.roots)


if __name__ == "__main__":
    unittest.main()
