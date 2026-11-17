"""Synthetic mechanical fixtures only; zero model or verifier execution."""
import copy
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("diagnostic_tested", HERE / "qwen_research_diagnostic_v1.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hepta-research-diag-unit-")
        self.root = Path(self.temp.name).resolve()
        self.reader = d.Reader(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, relative, value, raw=False):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if raw else d.canonical(value) + b"\n")
        return path

    def test_link_escape_changed_bytes_and_duplicate_json_fail_closed(self):
        path = self.save("original.json", {"x": 1})
        self.reader.read(path)
        (self.root / "link").symlink_to(path)
        for value in ("link", "../elsewhere"):
            with self.assertRaises(ValueError):
                self.reader.read(value)
        with self.assertRaises(ValueError):
            d.parse(b'{"x":1,"x":2}')
        path.write_bytes(b'{"x":2}')
        with self.assertRaises(ValueError):
            self.reader.recheck()

    def test_zero_baseline_and_missing_outcome_are_not_perfect_retention(self):
        result = d.paired_metrics({"a": False, "b": False}, {"a": True, "b": False})
        self.assertEqual(result["after_success_rate"], 0.5)
        self.assertIsNone(result["retained_fraction_of_previous_successes"])
        self.assertIsNone(d.paired_metrics({"a": True}, {"a": None})["after_success_rate"])
        self.assertEqual(d.paired_metrics({"a": True}, {"a": False})["retained_fraction_of_previous_successes"], 0)

    def test_failed_slot_not_replaced_and_union_is_not_routing(self):
        arms = {name: {"status": "AVAILABLE", "A_first_successes": ["a"]} for name in d.SLOTS}
        self.assertFalse(d.fixed_union(arms)["union_exceeds_best"])
        arms["trajectory"] = {"status": "UNAVAILABLE"}
        arms[d.SEPARATE] = {"status": "AVAILABLE", "A_first_successes": ["a", "b", "c"]}
        result = d.fixed_union(arms)
        self.assertIsNone(result["union_successes"])
        self.assertEqual(result["unavailable_slots"], ["trajectory"])
        arms["trajectory"] = {"status": "AVAILABLE", "A_first_successes": ["b"]}
        result = d.fixed_union(arms)
        self.assertTrue(result["union_exceeds_best"])
        self.assertFalse(result["circuit_experiment_qualified"])
        self.assertFalse(result["full_system_cost_matched"])

    def test_cold_requires_same_manifest_and_actual_primary_binding(self):
        primary = {"manifest": {"path": "fixture", "sha256": "a" * 64, "model_digest": "b" * 64}, "pid": 101}
        cold = {"manifest": copy.deepcopy(primary["manifest"]), "pid": 102,
                "cold_manifest_exactly_matches_primary": True}
        job = {"primary_manifest": copy.deepcopy(primary["manifest"]), "primary_pid": 101,
               "primary_result_sha256": "c" * 64}
        d.cold_identity(primary, cold, job, "c" * 64)
        for changed in ({"pid": 101}, {"manifest": {**cold["manifest"], "sha256": "d" * 64}}):
            with self.assertRaises(ValueError):
                d.cold_identity(primary, {**cold, **changed}, job, "c" * 64)
        with self.assertRaises(ValueError):
            d.cold_identity(primary, cold, job, "d" * 64)

    def test_template_changed_baseline_or_source_rejected(self):
        value = {"schema": "hepta.research-sft-diagnostic-freeze.v1", "status": "FROZEN_PRE_FIT",
                 "rule_version": "research-diagnostic-v1", **d.SCOPE,
                 "fixed_slots": list(d.SLOTS), "separate_arm": d.SEPARATE, "rules": copy.deepcopy(d.RULES),
                 "baseline_bindings": dict(d.BASELINE),
                 "diagnostic_source": {"filename": "qwen_research_diagnostic_v1.py", "sha256": "a" * 64},
                 "slot_admission": "complete_primary_fit_and_evaluation_plus_exact_cold_identity",
                 "source_growth_options": {"readiness": None, "updates_per_source": 64},
                 "cost_matching": "not_claimed_from_panel_measurements"}
        d.validate_rules(value, "a" * 64)
        for field, changed in (("status", "TEMPLATE_NOT_RUNNABLE"),
                               ("fixed_slots", list(reversed(d.SLOTS))),
                               ("baseline_bindings", {"RESULT.json": "f" * 64})):
            altered = copy.deepcopy(value)
            altered[field] = changed
            with self.assertRaises(ValueError):
                d.validate_rules(altered, "a" * 64)
        with self.assertRaises(ValueError):
            d.validate_rules(value, "b" * 64)

    def attempt_fixture(self):
        record = {"record_id": "fixture-A", "task_id": "fixture-task", "source_id": "fixture-source",
                  "lineage_id": "fixture-lineage", "task": {"input": "fixture input",
                  "messages": [{"role": "user", "content": "fixture input"}]}}
        request = {"record_id": record["record_id"], "task": copy.deepcopy(record["task"])}
        output = {"answer": "fixture without verified success", "loaded_model_digest": "a" * 64,
                  "input_sha256": d.hashlib.sha256(record["task"]["input"].encode()).hexdigest(),
                  "messages_sha256": d.digest(record["task"]["messages"]), "generation_config_sha256": "b" * 64,
                  "pid": 101, "input_tokens": 9, "output_tokens": 1, "output_token_ids": [1], "max_new_tokens": 384}
        step = {"number": 0, "request_sha256": d.digest(request), "output": output,
                "verification": {"fixture": True, "success": False}, "execution_summary": {"fixture": True},
                "semantic_measurement": "measured", "feedback": "fixture feedback", "executed": False}
        step["receipt_sha256"] = d.digest(step)
        row = {key: record[key] for key in ("record_id", "task_id", "source_id", "lineage_id")}
        row.update(steps=[step], success=False, first_attempt_success=False,
                   semantic_measurement="measured", attempts_are_independent_tasks=False)
        for name, item in (("request-0.json", request), ("output-0.json", output),
                           ("step-0.json", step), ("RESULT.json", row)):
            self.save("attempt/" + name, item)
        class ProtocolFixture:
            require_prepared = staticmethod(lambda item: copy.deepcopy(item["task"]["messages"]))
            feedback = staticmethod(lambda _: "fixture feedback")
            execution_summary = staticmethod(lambda _: {"fixture": True})
        return record, row, ProtocolFixture

    def test_resealed_wrong_model_cannot_be_bound_execution(self):
        record, row, protocol = self.attempt_fixture()
        semantic = lambda *_: {"business_success": False, "verifier_executed": False}
        actual = d.attempt_row(self.reader, record, row, self.root / "attempt",
                               "a" * 64, "b" * 64, semantic, protocol, pid=101)
        self.assertFalse(actual["first"])
        tampered = copy.deepcopy(row)
        step = tampered["steps"][0]
        step["output"]["loaded_model_digest"] = "c" * 64
        step.pop("receipt_sha256")
        step["receipt_sha256"] = d.digest(step)
        for name, item in (("output-0.json", step["output"]), ("step-0.json", step), ("RESULT.json", tampered)):
            self.save("attempt/" + name, item)
        with self.assertRaises(ValueError):
            d.attempt_row(d.Reader(self.root), record, tampered, self.root / "attempt",
                          "a" * 64, "b" * 64, semantic, protocol, pid=101)

    def test_missing_business_evidence_stays_unavailable(self):
        record, row, protocol = self.attempt_fixture()
        unknown = lambda *_: {"business_success": None, "verifier_executed": False}
        with self.assertRaises(ValueError):
            d.attempt_row(self.reader, record, row, self.root / "attempt",
                          "a" * 64, "b" * 64, unknown, protocol, pid=101)

    def test_partial_cost_uses_real_readonly_runner_and_no_reference_double_count(self):
        source = Path(os.environ["HEPTA_RESEARCH_TEST_SOURCE"]).resolve()
        helpers = Path(os.environ["HEPTA_RESEARCH_TEST_HELPERS"]).resolve()
        sys.path.insert(0, str(source))
        runner = importlib.import_module("run_research_sft_v1")
        runner.configure(helpers)
        base = "run/workers/trajectory-primary"
        request = {"fixture": True}
        output = {"input_tokens": 12, "output_tokens": 4, "answer": "fixture"}
        step = {"request_sha256": d.digest(request), "output": output, "verification": None}
        step["receipt_sha256"] = d.digest(step)
        for name, item in (("request-0.json", request), ("output-0.json", output), ("step-0.json", step)):
            self.save(base + "/evaluation/A_retention/0/" + name, item)
        self.save(base + "/evaluation/A_retention/1/request-0.json", request)
        self.save(base + "/evaluation/A_retention/1/output-0.json", b'{"input_tokens":', raw=True)
        self.save(base + "/evaluation/A_retention/STARTED.json", {"fixture": True})
        reference = {"record_id": "fixture", "answer_sha256": "a" * 64, "success": False, "receipt_sha256": "b" * 64}
        self.save(base + "/research-model/references/0/REFERENCE_REQUEST.json", reference)
        self.save(base + "/research-model/references/0/REFERENCE.json", reference)
        self.save(base + "/research-model/REFERENCE_RECHECKS.json", [reference])
        durable = {"step": 1, "loss": 1.5, "input_tokens": 3, "supervised_tokens": 1, "padded_positions": 1536}
        self.save(base + "/research-model/STEPS.jsonl", d.canonical(durable) + b'\n{"loss":', raw=True)
        result = d.cost_ledger(self.reader, self.root / "run", False, runner.raw_ledger, [])
        self.assertIsNone(result["model_calls"])
        self.assertIsNone(result["input_tokens"])
        self.assertEqual(result["input_tokens_measured_subtotal"], 12)
        self.assertEqual(result["output_tokens_measured_subtotal"], 4)
        self.assertEqual(result["authored_reference_receipts"], 1)
        self.assertIsNone(result["reference_calls"])
        self.assertFalse(result["reference_batch_summaries_counted_again"])
        self.assertEqual(result["completed_training_step_receipts"], 1)
        self.assertIsNone(result["training_steps"])
        self.assertIsNone(result["actual_panel_measurements"][0]["cost"])
        self.assertIsNone(result["gpu_active_seconds"])
        self.assertIsNone(result["energy_joules"])
        self.assertGreaterEqual(len(result["measurement_errors"]), 2)
        self.assertTrue(all(x.get("sha256") for x in result["measurement_errors"]))

    def test_import_does_not_load_model_libraries(self):
        self.assertFalse(any(name.split(".")[0] in ("torch", "transformers", "peft") for name in sys.modules))

    def test_missing_or_changed_adapter_bytes_cannot_become_available(self):
        directory = self.root / "run/workers/final_answer-primary/research-model"
        adapter = directory / "adapter"
        parent = {"model_id": "synthetic-fixture-never-loaded", "runtime": {}, "backend_versions": {}}
        plan = {"source_inventory": {"fixture": "only"}, "reference_admission": {"parent_successful_A_tasks": 0}}
        config = {"peft_type": "LORA", "task_type": "CAUSAL_LM", "r": 4, "lora_alpha": 8,
                  "lora_dropout": 0.0, "bias": "none", "inference_mode": True,
                  "target_modules": ["q_proj", "v_proj"]}
        relative = adapter.relative_to(self.root).as_posix()
        path = self.save(relative + "/adapter_config.json", config)
        config_bytes = path.read_bytes()
        model = {"schema": "hepta.research-authored-sft-model.v1",
                 "family": "hepta-qwen25-coder-research-authored-sft-v1", **d.SCOPE,
                 "model_id": parent["model_id"], "base_manifest": parent, "parent_model_digest": d.digest(parent),
                 "runtime": {}, "backend_versions": {}, "training_plan_digest": d.digest(plan),
                 "research_source_inventory": plan["source_inventory"],
                 "reference_admission_digest": d.digest(plan["reference_admission"]),
                 "parent_successful_A_tasks": 0, "adapter_directory": relative,
                 "adapter_files": [{"path": "adapter_config.json", "bytes": len(config_bytes),
                                    "sha256": d.hashlib.sha256(config_bytes).hexdigest()},
                                   {"path": "adapter_model.safetensors", "bytes": 7, "sha256": "a" * 64}]}
        with self.assertRaisesRegex(ValueError, "regular evidence file missing"):
            d.adapter_identity(self.reader, directory, model, parent, plan, {}, [])
        self.save(relative + "/adapter_model.safetensors", b"fixture", raw=True)
        with self.assertRaisesRegex(ValueError, "file SHA differs"):
            d.adapter_identity(d.Reader(self.root), directory, model, parent, plan, {}, [])

if __name__ == "__main__":
    unittest.main(verbosity=2)
