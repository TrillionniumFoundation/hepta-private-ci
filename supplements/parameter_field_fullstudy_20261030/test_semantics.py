"""Small synthetic checks. Never open study RAW, checkpoints, or endpoint arrays."""

from copy import deepcopy
import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]
spec = importlib.util.spec_from_file_location("postseal_supplement_20261030", HERE / "postseal_supplement.py")
supp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supp)


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = value if isinstance(value, bytes) else (json.dumps(value, sort_keys=True) + "\n").encode()
    path.write_bytes(payload)
    return {"path": str(path), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def fixture(base, drop_job=False, incomplete_restore=False):
    """All RAW-like files below are tiny invented metadata, never scientific data."""
    root, source, ops = base / "raw", base / "source", base / "ops"
    for p in (root, source, ops):
        p.mkdir()
    root.with_name(root.name + "_cas").mkdir()
    protocol = SOURCE / supp.PREFIX / "PROTOCOL.json"
    put(source / supp.PREFIX / "PROTOCOL.json", protocol.read_bytes())  # Source text only.
    items, operations_sha = {}, "e" * 64

    def raw(name, value):
        item = put(root / name, value)
        items[name] = item
        return item

    def relative(name):
        return {**items[name], "path": name}

    science_names, jobs = supp.required_seals()
    for phase in supp.PHASES:
        for seed in supp.SEEDS if phase in ("A", "B", "R") else (None,):
            token = f"{phase}-seed-{seed}" if seed is not None else f"{phase}-all"
            science = f"stage_{phase}/seed-{seed}/COMPLETE.json" if seed is not None else f"stage_{phase}/COMPLETE.json"
            raw(science, {"complete": True, "synthetic": True})
            raw(f"operations/{token}.COMPLETE.json", {"complete": True, "post_execution_storage_check": True,
                "attempt_id": supp.ATTEMPT, "phase": phase, "seed": seed, "scientific_source_bytes_unchanged": True,
                "scientific_protocol_sha256": supp.PROTOCOL_SHA, "operational_amendment_sha256": operations_sha,
                "scientific_complete": relative(science)})
        if phase in ("A", "B", "C"):
            raw(jobs[phase + "_endpoint"], {"complete": True, "synthetic": True})
    job_results = {job: {"complete": True, "exit_code": 0, "completion": relative(name)} for job, name in jobs.items()}
    if drop_job:
        del job_results["R-43"]
    raw("controller/EXECUTION.json", {"complete": True, "oom_admission_paused": False, "jobs": job_results})
    report_inputs = put(ops / "analysis/REPORT_INPUTS.json", {"synthetic_metadata": True})
    aggregate = {"execution_kind": "aggregate_analysis", "allowed_phases": ["ANALYSIS"], "attempt_id": supp.ATTEMPT,
        "analysis_id": "toy01", "protocol_sha256": supp.PROTOCOL_SHA,
        "report_module": "experiments.parameter_field_fullstudy_20261029.report_results",
        "operational_amendment_sha256": operations_sha, "output_relative": "aggregate_results",
        "required_scientific_seals": {str(root / name): items[name]["sha256"] for name in science_names},
        "report_inputs": report_inputs}
    aggregate_desc = put(ops / "analysis/FREEZE.json", aggregate)
    raw("aggregate_results/RESULTS.json", {"status": "COMPLETE", "synthetic": True})
    raw("aggregate_results/REPORT.md", b"Synthetic fixture; no efficacy values.\n")
    common = {"complete": True, "post_execution_storage_check": True,
        "source_freeze_sha256": aggregate_desc["sha256"], "report_inputs_sha256": report_inputs["sha256"],
        "operational_amendment_sha256": operations_sha, "scheduled_gradient_microsteps": 0,
        "endpoint_scoring_performed": False, "refitting_performed": False}
    worker = raw("analysis_operations/toy01/WORKER_COMPLETE.json", common)
    raw("analysis_operations/toy01/COMPLETE.json", {**common, "worker_receipt": worker,
        "outputs": [items["aggregate_results/RESULTS.json"], items["aggregate_results/REPORT.md"]]})
    finalizer = {"execution_kind": "evidence_finalization", "allowed_phases": ["FINALIZE"], "attempt_id": supp.ATTEMPT,
        "protocol_sha256": supp.PROTOCOL_SHA, "operational_amendment_sha256": operations_sha, "registered_commit": "c" * 40,
        "actual_aggregate_source_freeze": aggregate_desc, "source_files": supp.FROZEN_SOURCES,
        "required_scientific_seals": {item["path"]: item["sha256"] for item in items.values()},
        "artifacts": {item["path"]: item["sha256"] for item in items.values()}}
    finalizer_desc = put(ops / "final/FREEZE.json", finalizer)
    binding = {"attempt_id": supp.ATTEMPT, "source_freeze_sha256": finalizer_desc["sha256"],
        "operational_amendment_sha256": operations_sha, "registered_commit": "c" * 40}
    entries = {name: {"bytes": item["bytes"], "sha256": item["sha256"], "storage": "direct", "blob": None}
               for name, item in items.items()}
    manifest = {"schema": "hepta.fullstudy.cas-container-manifest.1", "attempt_id": supp.ATTEMPT,
        "root": str(root), "cas_root": str(root.with_name(root.name + "_cas")), "binding": binding,
        "all_raw_root_artifacts_and_failures_included": True, "logical_paths": entries,
        "logical_artifact_count": len(entries), "logical_artifact_bytes": sum(x["bytes"] for x in entries.values())}
    manifest_desc = put(root / "evidence_v2/toy/MANIFEST.json", manifest)
    verified = {"schema": "hepta.fullstudy.cas-literal-verification.1", "archive_verification_complete": True,
        "temporary_directory_removed_after_success": True, "manifest": {**manifest_desc, "path": "evidence_v2/toy/MANIFEST.json"},
        "binding": binding, "logical_files_restored": len(entries), "logical_bytes_restored": manifest["logical_artifact_bytes"],
        "logical_paths_verified": sorted(entries)[:-1] if incomplete_restore else sorted(entries)}
    verified_desc = put(root / "evidence_v2/toy/VERIFIED.json", verified)
    pipeline = {"schema": supp.PIPELINE_SCHEMA, "complete": True, "execution_episode": supp.EPISODE,
        "artifacts": {"verified": verified_desc, "manifest": manifest_desc,
                      "aggregate_results": items["aggregate_results/RESULTS.json"], "finalizer_freeze": finalizer_desc}}
    pipeline_desc = put(ops / "pipeline/COMPLETE.json", pipeline)
    implementation = (HERE / "postseal_supplement.py").read_bytes()
    plan = {"schema": supp.PLAN_SCHEMA, "status": "PRE_ENDPOINT", "execution_episode": supp.EPISODE,
        "attempt_id": supp.ATTEMPT, "protocol_sha256": supp.PROTOCOL_SHA,
        "new_implementation_not_recovered_old_bytes": True, "scientific_payloads_opened_during_preparation": False,
        "execution_context": {"raw_root": str(root), "source_root": str(source), "operations_root": str(ops)},
        "implementation": {"bytes": len(implementation), "sha256": hashlib.sha256(implementation).hexdigest()},
        "frozen_sources": supp.FROZEN_SOURCES, "original_phase_freezes": supp.PHASE_FREEZES}
    plan_desc = put(base / "plan/PLAN.json", plan)
    args = SimpleNamespace(raw_root=str(root), source_root=str(source), plan=plan_desc["path"], expected_plan_sha256=plan_desc["sha256"],
        pipeline_complete=pipeline_desc["path"], expected_pipeline_sha256=pipeline_desc["sha256"],
        verified=verified_desc["path"], expected_verified_sha256=verified_desc["sha256"],
        manifest=manifest_desc["path"], expected_manifest_sha256=manifest_desc["sha256"],
        finalizer_freeze=finalizer_desc["path"], expected_finalizer_sha256=finalizer_desc["sha256"])
    return args, base / "supplement_output"


class SyntheticGateTests(unittest.TestCase):
    def test_full_public_gate_is_stdlib_only(self):
        original_import = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name.split(".")[0] in ("numpy", "torch"):
                raise AssertionError("Scientific runtime imported before gate")
            return original_import(name, *args, **kwargs)
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            args, output = fixture(Path(tmp))
            # This synthetic gate fixture tests the metadata interface, not source restoration.
            with patch.object(supp, "verify_original_sources", return_value=98), patch("builtins.__import__", side_effect=guarded):
                unused, store, unused_protocol, receipt = supp.gate(args, supp.Inputs(), output)
            self.assertTrue(store.admitted)
            self.assertEqual((receipt["controller_jobs"], receipt["completion_seals"]), (14, 30))
            self.assertFalse(output.exists())

    def test_missing_job_and_incomplete_literal_population_rejected(self):
        for config, message in (({"drop_job": True}, "Fourteen-job"), ({"incomplete_restore": True}, "Literal restore population")):
            with self.subTest(config=config), tempfile.TemporaryDirectory(dir=HERE) as tmp:
                args, output = fixture(Path(tmp), **config)
                with patch.object(supp, "verify_original_sources") as original, self.assertRaisesRegex(ValueError, message):
                    supp.gate(args, supp.Inputs(), output)
                original.assert_not_called()
                self.assertFalse(output.exists())

    def test_exact_pipeline_descriptor_and_external_freeze_hash_required(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            args, output = fixture(Path(tmp))
            value = json.loads(Path(args.pipeline_complete).read_text())
            value["notes"] = {"old_descriptor": value["artifacts"]["verified"]}
            value["artifacts"]["verified"] = {**value["artifacts"]["verified"], "sha256": "0" * 64}
            args.expected_pipeline_sha256 = put(Path(args.pipeline_complete), value)["sha256"]
            with self.assertRaisesRegex(ValueError, "does not bind actual verified"):
                supp.gate(args, supp.Inputs(), output)
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            args, output = fixture(Path(tmp))
            args.expected_finalizer_sha256 = "0" * 64
            with self.assertRaisesRegex(ValueError, "Input hash"):
                supp.gate(args, supp.Inputs(), output)

    def test_scientific_access_is_explicitly_closed(self):
        store = supp.SealedRaw(Path("/unopened"), {}, supp.Inputs())
        with self.assertRaisesRegex(ValueError, "Scientific payload read blocked"):
            store.read_json("stage_A/seed-17/bank/BANK.json")
        with self.assertRaisesRegex(ValueError, "Array read blocked"):
            with store.npz("not-opened.npz", None):
                pass


class FiniteSemanticsTests(unittest.TestCase):
    def test_changed_best_sets_can_have_common_optimum(self):
        value = supp.witness_regrets([2, 2, 0, 0], [0, 2, 2, 0])
        self.assertEqual(value["common_best_actions"], [1])
        self.assertEqual(value["shared_deterministic_action_minimax_regret"], 0)
        self.assertEqual(value["equal_state_mixture_minimum_average_regret"], 0)

    def test_disjoint_best_sets_have_distinct_deterministic_regret_metrics(self):
        value = supp.witness_regrets([2, 0, 0, 0], [0, 2, 0, 0])
        self.assertEqual(value["common_best_actions"], [])
        self.assertEqual(value["shared_deterministic_action_minimax_regret"], 2)
        self.assertEqual(value["equal_state_mixture_minimum_average_regret"], 1)
        self.assertFalse(value["all_field_policy_lower_bound"])

    def test_equal_dynamics_uses_semantic_outputs_not_container_identity(self):
        row = {"action_values": [1.] * 4, "branches": [{"action": a, "value": 1.,
            "first": {"dynamics": "same", "components": {"parameters": "p"}},
            "terminal": {"dynamics": "end"}} for a in range(4)]}
        outputs = {a: {"output_sha256": ["x", "y"], "conditions": ["clean", "clean"],
            "source_ids": [["a", "b"], ["c", "d"]], "artifact": {"sha256": str(a)}} for a in range(4)}
        groups, issues = supp.equal_dynamics_checks(row, outputs)
        self.assertEqual(len(groups), 1)
        self.assertEqual(issues, [])
        changed = deepcopy(row)
        changed["branches"][1]["terminal"]["dynamics"] = "different"
        self.assertTrue(any("terminal_dynamics" in x["kind"] for x in supp.equal_dynamics_checks(changed, outputs)[1]))
        outputs[3]["source_ids"].reverse()
        self.assertTrue(any("row_identities" in x["kind"] for x in supp.equal_dynamics_checks(row, outputs)[1]))

    def test_exact_frozen_gated_choice_and_ungated_regret_are_separate(self):
        import numpy as np  # Toy arrays only; no Torch or scientific module import.
        choose = supp.frozen_choose(SOURCE, supp.Inputs(), np)
        head = {"mean": np.zeros(1), "scale": np.ones(1), "coefficients": np.zeros((1, 4)),
                "intercept": np.asarray([.8, .2, 0, -.1]), "baseline": 2, "threshold": 1.,
                "fit_max_standardized_norm": .5}
        result = supp.selection_metrics(head, np.asarray([1.]), [.6, .1, 0, -.1], choose)
        self.assertEqual(result["choice"]["chosen_action"], 2)
        self.assertEqual(result["gated_selection_regret"], .6)
        self.assertEqual(result["rowwise_ungated_selection_regret"], 0)
        self.assertTrue(result["choice"]["outside_fit_norm"])
        head["threshold"] = 0
        result = supp.selection_metrics(head, np.asarray([1.]), [.6, .1, 0, -.1], choose)
        self.assertTrue(result["choice"]["override"])  # Outside-fit norm does not force fallback.
        head["intercept"] = np.asarray([.8, .8, 0, -.1])
        result = supp.selection_metrics(head, np.asarray([0.]), [.6, .6, 0, -.1], choose)
        self.assertTrue(result["exact_max_score_tie"])
        self.assertEqual(result["choice"]["chosen_action"], 2)


if __name__ == "__main__":
    unittest.main()
