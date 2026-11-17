"""Engineering fixtures only. No actual model, authored verifier or research fit.

The old suite supplies synthetic builders; its tests are not discovered or run.
One real-parent compatibility case only reads retained evidence and runtime files.
"""
import copy
import hashlib
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import research_sft_contract_v1 as contract
import research_sft_execution_v1 as worker
import run_research_sft_v1 as runner
import test_qwen_development_v3 as legacy
from cell_experiments import data, repo_execution
from cell_experiments import causal_probe_v3 as probe, causal_training_contract_v3 as native

h = contract.helpers()
io, inputs = h.io, h.inputs

class ResearchBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        legacy.DevelopmentPreflightTests.setUpClass()
        cls.original = copy.deepcopy(legacy.DevelopmentPreflightTests.records)
        cls.parent = copy.deepcopy(legacy.DevelopmentPreflightTests.parent)
        cls.parent["backend_versions"] = probe._versions()

    def context(self):
        records = copy.deepcopy(self.original)
        ready = legacy.ready_fixture(records, self.parent, [False] * len(records))
        gate = inputs.bound_readiness(records, self.parent, ready, "3" * 64)
        operation = io.sealed({
            "schema": "hepta.qwen-readiness-operation-result.v3", "status": "COMPLETE",
            "new_C": False, "training_started": False, "model_digest": data.digest(self.parent),
            "successful_A_tasks": 0, "fixture_actor": "synthetic engineering baseline only"})
        return {"records": records, "parent": copy.deepcopy(self.parent), "readiness": ready,
                "gate": gate, "generation_digest": "3" * 64, "parent_operation": operation,
                "panels": {"B_exposed": records[6:], "A_retention": records[:6]}}

    def directory(self):
        path = Path(os.environ["RESEARCH_ENGINEERING_OUTPUT"]) / self._testMethodName
        path.mkdir(parents=True, exist_ok=False)
        return path

    def test_zero_baseline_is_new_research_only_and_native_gate_remains_closed(self):
        context = self.context()
        for mode in ("final_answer", "trajectory"):
            plan = contract.make_plan(context["records"][:6], context, mode, "fixture/" + mode)
            contract.validate_plan(context["records"][:6], context, plan)
            self.assertEqual(plan["reference_admission"]["parent_successful_A_tasks"], 0)
            self.assertNotIn("readiness_witness", plan)
            self.assertEqual(plan["training"], contract.TRAINING)
            self.assertIsNone(plan["candidate_selected"])
            self.assertFalse(plan["proof_of_useful_work_eligible"])
        with self.assertRaisesRegex(ValueError, "no recorded real business success"):
            native.readiness_witness(context["records"][:6], context["parent"], context["readiness"])
        for key, value in (("successful_A_tasks", 1), ("status", "PARTIAL")):
            changed = copy.deepcopy(context)
            changed["parent_operation"][key] = value
            changed["parent_operation"] = io.sealed({
                k: v for k, v in changed["parent_operation"].items() if k != "receipt_sha256"})
            with self.assertRaises(ValueError):
                contract.reference_admission(changed["records"][:6], changed, "trajectory")

    def test_target_authorization_and_original_control_evidence_cannot_be_forged_by_counter(self):
        context = self.context()
        for variant in ("target", "authorization", "reference", "student", "split"):
            records = copy.deepcopy(context["records"][:6])
            if variant == "target":
                records[0]["final_answer"] += "\n# changed"
            elif variant == "authorization":
                records[0]["authorization"]["training_allowed"] = False
            elif variant == "reference":
                bad = legacy.semantic_fixture(records[0], records[0]["final_answer"], False)
                records[0]["protocol_reference_receipt"] = bad
                records[0]["verified_outcome"]["receipt_sha256"] = bad["receipt_sha256"]
            elif variant == "student":
                records[0]["trajectory"].append({"actor": "student", "content": "not a teacher", "trainable": True})
            else:
                records[0]["split"] = "selection"
            with self.subTest(variant=variant), self.assertRaises((ValueError, KeyError)):
                contract.make_plan(records, context, "trajectory", "fixture/bad")

    def test_zero_baseline_retrieval_still_uses_only_other_authored_A(self):
        context = self.context()
        a = context["records"][:6]
        shown, bindings = inputs.retrieval_panels(a, context["panels"])
        self.assertEqual(set(shown), {"B_exposed", "A_retention"})
        self.assertEqual(sum(map(len, shown.values())), 9)
        a_by_id = {row["record_id"]: row for row in a}
        for original, binding in zip(a, bindings["A_retention"]):
            chosen = a_by_id[binding["retrieved_record_id"]]
            self.assertNotEqual(chosen["task_id"], original["task_id"])
            self.assertNotEqual(chosen["lineage_id"], original["lineage_id"])
        changed = copy.deepcopy(context["panels"])
        for row in changed["B_exposed"]:
            row["final_answer"] = "UNIQUE_B_ANSWER_FORBIDDEN_IN_PROMPT"
        changed_shown, _ = inputs.retrieval_panels(a, changed)
        self.assertEqual([row["task"] for row in shown["B_exposed"]],
                         [row["task"] for row in changed_shown["B_exposed"]])
        self.assertEqual(context["gate"]["successful_A_tasks"], 0)

    def test_collection_freezes_four_plans_with_failed_controlled_and_unexecuted_shadow(self):
        context, output = self.context(), self.directory()
        requests = []
        parent = context["parent"]
        class ScriptedPredictor:
            model_digest = data.digest(parent)
            generation_digest = "3" * 64
            def __init__(self, *_args):
                pass
            def predict(self, request):
                requests.append(copy.deepcopy(request))
                return {"answer": "synthetic fresh shadow", "loaded_model_digest": self.model_digest,
                        "input_sha256": hashlib.sha256(request["task"]["input"].encode()).hexdigest(),
                        "messages_sha256": data.digest(request["task"]["messages"]),
                        "input_tokens": 7, "output_tokens": 3}
            def close(self):
                pass
        with patch.object(probe, "Predictor", ScriptedPredictor), \
                patch.object(repo_execution, "load_catalog", return_value=None), \
                patch.object(data, "verify_answer", side_effect=lambda row, answer: legacy.semantic_fixture(row, answer, True)) as references:
            result = worker.collect(context, {"artifact_root": str(io.WORKSPACE_ROOT),
                "readiness_directory": "engineering-fixture", "operation_id": "fixture/four-plans"}, output)
        self.assertEqual((len(requests), references.call_count), (6, 12))
        self.assertEqual(result["status"], "RESEARCH_PLANS_FROZEN")
        self.assertEqual(result["controlled_new_model_calls"], 0)
        plans = io.read(output / "PLANS.json")
        self.assertEqual(set(plans), set(io.FIT_MODES))
        self.assertEqual(result["plans_digest"], io.digest(plans))
        for arm, mode in io.FIT_MODES.items():
            records = io.read(output / (arm + ".records.json"))
            contract.validate_plan(records, context, plans[arm])
            self.assertEqual(plans[arm]["mode"], mode)
            self.assertEqual(plans[arm]["reference_admission"]["parent_successful_A_tasks"], 0)
            self.assertTrue(all(event.get("trainable") is False for row in records
                                for event in row["trajectory"] if event["actor"] == "student"))
        shadow = io.read(output / "shadow/0/step-0.json")
        self.assertIsNone(shadow["verification"])
        self.assertFalse(shadow["executed"])
        self.assertEqual(io.read(output / "CONTROLLED_REUSE.json")["observations"],
                         context["gate"]["controlled_observations"])
        self.assertTrue(all(row["success"] is False for row in context["gate"]["controlled_observations"]))
        with patch.object(data, "verify_answer", side_effect=AssertionError("reject before verifier")):
            with self.assertRaisesRegex(ValueError, "relabeled shadow"):
                worker.corrected(context["records"][0], context["gate"]["controlled_observations"][0],
                                 "shadow", output / "forbidden")
        self.assertFalse(list(output.rglob("adapter_model.safetensors")))

    def test_mid_reference_failure_preserves_first_call_and_unknown_tail_in_trainer_entry(self):
        import research_sft_train_v1 as train
        context, output = self.context(), self.directory()
        plan = contract.make_plan(context["records"][:6], context, "trajectory", "fixture/reference-failure")
        count = 0
        def reference(row, answer):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError("synthetic second verifier interruption")
            return legacy.semantic_fixture(row, answer, True)
        target = output / "workers/final_answer-primary/research-model"
        with patch.object(probe, "verify_model", return_value=io.digest(context["parent"])), \
                patch.object(repo_execution, "load_catalog", return_value=None), \
                patch.object(data, "verify_answer", side_effect=reference), \
                patch.object(probe, "_libraries", side_effect=AssertionError("model libraries must not load")):
            with self.assertRaisesRegex(RuntimeError, "second verifier"):
                train.train(context["records"][:6], context["parent"], io.WORKSPACE_ROOT,
                            plan, target, context)
        self.assertEqual(count, 2)
        self.assertTrue((target / "references/0/REFERENCE.json").is_file())
        self.assertTrue((target / "references/1/REFERENCE_REQUEST.json").is_file())
        self.assertTrue((target / "references/1/REFERENCE_FAILED.json").is_file())
        self.assertFalse((target / "references/1/REFERENCE.json").exists())
        self.assertFalse((target / "REFERENCE_RECHECKS.json").exists())
        ledger = runner.raw_ledger(output, [], operation_complete=False)
        self.assertEqual(ledger["authored_reference_receipts"], 1)
        self.assertEqual(ledger["authored_reference_request_files"], 2)
        self.assertIsNone(ledger["reference_calls"])
        self.assertIsNone(ledger["model_calls"])
        self.assertIsNone(ledger["input_tokens_measured_subtotal"])
        self.assertTrue(ledger["measurement_gaps"])
        self.assertEqual(runner.fit_counts(output)["fit_attempts_started"], 1)
        self.assertEqual(runner.fit_counts(output)["fits_completed"], 0)

    def test_partial_ledger_survives_corrupt_tail_without_double_counting_reference_batch(self):
        output = self.directory()
        d = output / "workers/parent-primary/evaluation/B_exposed/0"
        request = {"record_id": "fixture", "task": {"input": "fixture", "messages": []}}
        raw = {"answer": "fixture", "input_tokens": 7, "output_tokens": 2}
        io.write_new(d / "request-0.json", request)
        io.write_new(d / "output-0.json", raw)
        io.write_new(d / "step-0.json", io.sealed({"request_sha256": io.digest(request),
                                                  "output": raw, "verification": None}))
        io.write_new(d / "request-1.json", request)
        (d / "output-1.json").write_bytes(b'{"output_tokens":')
        reference = legacy.semantic_fixture(self.original[0], self.original[0]["final_answer"], True)
        ref = output / "workers/trajectory-primary/research-model/references/0"
        io.write_new(ref / "REFERENCE_REQUEST.json", {"record_id": reference["record_id"],
                                                       "answer_sha256": reference["answer_sha256"]})
        io.write_new(ref / "REFERENCE.json", reference)
        io.write_new(ref.parent.parent / "REFERENCE_RECHECKS.json", [reference])
        step = {"step": 1, "input_tokens": 6, "supervised_tokens": 2,
                "padded_positions": 1536, "loss": 1.3}
        (ref.parent.parent / "STEPS.jsonl").write_bytes(io.canonical(step) + b'\n{"step":2')
        ledger = runner.raw_ledger(output, [], operation_complete=False)
        self.assertEqual(ledger["completed_output_receipts"], 1)
        self.assertEqual(ledger["output_tokens_measured_subtotal"], 2)
        self.assertEqual(ledger["input_tokens_measured_subtotal"], 7)
        self.assertEqual(ledger["authored_reference_receipts"], 1)
        self.assertEqual(ledger["completed_training_step_receipts"], 1)
        self.assertEqual(ledger["padded_training_positions_measured_subtotal"], 1536)
        self.assertFalse(ledger["reference_batch_summaries_counted_again"])
        self.assertIsNone(ledger["model_calls"])
        self.assertIsNone(ledger["training_steps"])
        self.assertGreaterEqual(len(ledger["measurement_errors"]), 2)
        self.assertTrue(all(row["sha256"] and row["bytes"] for row in ledger["measurement_errors"]))

    def test_empty_ledger_and_excess_intents_cannot_become_zero_cost_success(self):
        output = self.directory()
        empty = runner.raw_ledger(output, [], operation_complete=True)
        self.assertTrue(empty["global_totals_unknown"])
        self.assertIsNone(empty["model_calls"])
        self.assertIsNone(empty["output_tokens_measured_subtotal"])
        for index in range(io.BUDGET["maximum_model_calls"] + 1):
            io.write_new(output / "workers/fixture" / str(index) / "request-0.json", {"fixture": True})
        ledger = runner.raw_ledger(output, [], operation_complete=False)
        self.assertEqual(ledger["budget_violations"][0]["counter"], "request_intents")

    def test_research_model_rejected_natively_and_adapter_bytes_stay_bound(self):
        output = self.directory()
        adapter = output / "adapter"
        io.write_new(adapter / "adapter_config.json", {
            "peft_type": "LORA", "task_type": "CAUSAL_LM", "r": 4, "lora_alpha": 8,
            "lora_dropout": 0.0, "bias": "none", "inference_mode": True,
            "target_modules": ["q_proj", "v_proj"]})
        (adapter / "adapter_model.safetensors").write_bytes(b"engineering identity fixture, not a model")
        parent = copy.deepcopy(self.parent)
        manifest = {
            "schema": contract.MODEL_SCHEMA, "family": contract.FAMILY, "model_id": probe.MODEL_ID,
            "profile": contract.PROFILE, "admission_policy": contract.ADMISSION,
            "research_source_inventory": contract.sources(), "base_manifest": parent,
            "parent_model_digest": io.digest(parent), "runtime": parent["runtime"],
            "backend_versions": parent["backend_versions"], "peft_version": contract.metadata.version("peft"),
            "adapter_directory": adapter.relative_to(io.WORKSPACE_ROOT).as_posix(),
            "adapter_files": probe._inventory(adapter), **contract.SCOPE}
        with self.assertRaisesRegex(ValueError, "unsupported candidate"):
            native.verify_candidate(manifest, io.WORKSPACE_ROOT)
        with patch.object(probe, "verify_model", return_value=io.digest(parent)):
            self.assertEqual(contract.verify_model(manifest, io.WORKSPACE_ROOT), io.digest(manifest))
            with self.assertRaisesRegex(ValueError, "scope"):
                contract.verify_model({**manifest, "native_cell_adoption": True}, io.WORKSPACE_ROOT)
            (adapter / "adapter_model.safetensors").write_bytes(b"changed fixture")
            with self.assertRaisesRegex(ValueError, "adapter files"):
                contract.verify_model(manifest, io.WORKSPACE_ROOT)

    def test_cold_keeps_deterioration_and_requires_exact_identity(self):
        report = {"model_digest": "m", "generation_digest": "g", "original_panels_digest": "o",
                  "shown_panels_digest": "s", "successful_tasks": 1,
                  "rows": [{"panel": "A_retention", "task_id": "fixture", "success": True,
                      "first_attempt_success": True, "steps": [
                          {"output": {"answer": "a", "output_token_ids": [1]}}]}]}
        primary = {"manifest": {"path": "same", "sha256": "x"}, "pid": 1, "evaluation": report}
        cold = copy.deepcopy(primary)
        cold["pid"] = 2
        cold["evaluation"]["successful_tasks"] = 0
        cold["evaluation"]["rows"][0]["success"] = False
        cold["evaluation"]["rows"][0]["first_attempt_success"] = False
        comparison = runner.cold_comparison(primary, cold)
        self.assertFalse(comparison["business_outcomes_equal"])
        self.assertEqual(comparison["cold_successful_tasks"], 0)
        self.assertIsNone(comparison["candidate_selected"])
        cold["manifest"]["sha256"] = "other"
        with self.assertRaisesRegex(ValueError, "same manifest"):
            runner.cold_comparison(primary, cold)

    def test_diagnostic_rules_are_prefit_bound_and_extensions_preserve_required_fields(self):
        output = self.directory()
        source = output / "qwen_research_diagnostic_v1.py"
        source.write_text("# engineering identity fixture; never executed\n")
        rule = {
            "schema": "hepta.research-sft-diagnostic-freeze.v1", "status": "FROZEN_PRE_FIT",
            "research_only": True, "new_C": False, "scientific_confirmation_qualified": False,
            "native_cell_adoption": False, "proof_of_useful_work_eligible": False, "circuit_qualified": False,
            "candidate_selected": None, "fixed_slots": ["final_answer", "trajectory", "controlled_correction"],
            "separate_arm": "shadow_correction", "rule_version": "research-diagnostic-v1",
            "diagnostic_source": {"filename": source.name, "sha256": io.file_hash(source)},
            "rules": {"first_last_separate": True, "zero_baseline_retention": None,
                "failed_slot_replacement": False, "missing_evidence": "unavailable",
                "partial_cost": "unknown_totals_with_measured_subtotals",
                "panel_cost_scope": "actual_panel_only_excludes_load_close",
                "cost_scopes_additive": False, "union_not_routing": True,
                "new_independent_samples": 0, "new_teachers": 0, "new_users": 0,
                "slot_admission": "complete_primary_fit_and_evaluation_plus_exact_cold_identity"}}
        path = output / "RULES.json"
        io.write_new(path, rule)
        self.assertEqual(contract.diagnostic_guard(path, io.file_hash(path)), rule)
        changed = copy.deepcopy(rule)
        changed["rules"]["failed_slot_replacement"] = True
        io.write_new(output / "BAD_RULES.json", changed)
        with self.assertRaisesRegex(ValueError, "rules"):
            contract.diagnostic_guard(output / "BAD_RULES.json", io.file_hash(output / "BAD_RULES.json"))
        source.write_text("# changed fixture\n")
        with self.assertRaisesRegex(ValueError, "source bytes"):
            contract.diagnostic_guard(path, io.file_hash(path))

    def test_workspace_runtime_separation_and_exact_scope_types(self):
        output = self.directory()
        with self.assertRaisesRegex(ValueError, "runtime root"):
            io.runtime_guard(io.WORKSPACE_ROOT, {})
        with self.assertRaisesRegex(ValueError, "workspace"):
            io.workspace_guard(io.RUNTIME_ROOT, output)
        link = output / "source-link"
        link.symlink_to(io.WORKSPACE_ROOT / "candidate-qwen-03", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "nonsymlink"):
            io.workspace_guard(io.WORKSPACE_ROOT, link)
        for key, value in (("new_C", 0), ("new_users", False), ("candidate_selected", "none")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                contract.scope_guard({**contract.SCOPE, key: value})

    def test_real_parent03_zero_baseline_loads_read_only_with_pinned_runtime(self):
        with patch.object(data, "verify_answer", side_effect=AssertionError("no verifier execution")), \
                patch.object(probe, "Predictor", side_effect=AssertionError("no model load")):
            context = contract.load_context(io.WORKSPACE_ROOT, io.WORKSPACE_ROOT / "candidate-qwen-03",
                                            io.WORKSPACE_ROOT / "probe-qwen-parent-03")
            io.runtime_guard(io.RUNTIME_ROOT, context["runtime"])
        self.assertEqual(context["gate"]["successful_A_tasks"], 0)
        self.assertEqual(len(context["records"]), 9)
        self.assertEqual(context["parent_operation_sha256"], contract.PARENT03_RESULT_SHA)
        self.assertEqual(io.digest(context["parent"]), contract.PARENT_MODEL_DIGEST)
        self.assertEqual(sum(map(len, context["retrieval_panels"].values())), 9)
        self.assertEqual(len(context["research_admission"]["references"]), 6)
        io.write_new(self.directory() / "READ_ONLY_PARENT_COMPATIBILITY.json", {
            "parent_result_sha256": context["parent_operation_sha256"],
            "parent_model_digest": io.digest(context["parent"]), "parent_A_successes": 0,
            "records": 9, "new_model_calls": 0, "new_reference_calls": 0,
            "synthetic_baseline_used": False, "qualification_changed": False,
            "pinned_runtime_guard_passed": True, **contract.SCOPE})
