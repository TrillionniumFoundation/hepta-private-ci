"""No-model preflight tests. Synthetic receipts never become experiment evidence.

No authored reference or repository subject is executed by these tests. The only
real subprocesses are tiny owned programs testing exit/timeout preservation.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import qwen_development_io_v3 as io
import qwen_development_inputs_v3 as inputs
import qwen_development_execution_v3 as worker
import run_qwen_development_v3 as runner
from cell_experiments import data, protocol_v3 as protocol, repo_execution
from cell_experiments import causal_probe_v3 as probe, causal_training_contract_v3 as contract


def semantic_fixture(record, answer, success):
    result = {"executed": success, "success": success}
    if success:
        result.update(exit_code=0, result={
            "original_passed": True, "control_count": 1, "controls_rejected": 1,
            "observations": [{"control": "original", "passed": True, "calls": ["synthetic-unit-fixture"]},
                             {"control": "wrong-output-unit-fixture", "passed": False, "calls": []}]})
    else:
        result.update(reason="invalid_test_patch", feedback="synthetic format rejection")
    value = {"schema": "hepta.cell-experiments.semantic-receipt.v1",
             "record_id": record["record_id"],
             "input_sha256": hashlib.sha256(record["task"]["input"].encode()).hexdigest(),
             "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
             "verifier": ["repo_patch", "1"],
             "verifier_source_sha256": io.file_hash(Path(repo_execution.__file__)),
             "parameters_sha256": data.digest(record["task"]["verifier"]["parameters"]),
             "result": result, "fixture_actor": "synthetic unit input; never actual execution or model evidence"}
    return {**value, "receipt_sha256": data.digest(value), "success": success}


def ready_fixture(records, parent, successes):
    rows = []
    for record, success in zip(records, successes):
        messages = protocol.require_prepared(record)
        request = {"record_id": record["record_id"], "task": {"input": record["task"]["input"], "messages": messages}}
        # Deliberately distinct from the authored final answer.
        output = {"answer": "synthetic retained student output", "loaded_model_digest": data.digest(parent),
                  "input_sha256": hashlib.sha256(record["task"]["input"].encode()).hexdigest(),
                  "messages_sha256": data.digest(messages), "generation_config_sha256": "3" * 64,
                  "pid": os.getpid(), "input_tokens": 7, "output_tokens": 2,
                  "output_token_ids": [17, 18], "max_new_tokens": 384, "hit_output_limit": False}
        verification = semantic_fixture(record, output["answer"], success)
        step = io.sealed({"number": 0, "request_sha256": data.digest(request), "output": output,
                          "verification": verification, "execution_summary": protocol.execution_summary(verification),
                          "feedback": protocol.feedback(verification), "executed": success,
                          "semantic_measurement": "measured"})
        rows.append({**{key: record[key] for key in ("record_id", "task_id", "source_id", "lineage_id")},
                     "task_digest": data.digest(record), "steps": [step], "success": success,
                     "first_attempt_success": success, "semantic_measurement": "measured"})
    return io.sealed({"schema": "hepta.development-readiness.v3", "model_digest": data.digest(parent),
                      "model_calls": len(rows), "successful_tasks": sum(successes), "rows": rows,
                      "fixture_actor": "synthetic unit input; not qualification evidence"})


class DevelopmentPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(repo_execution.__file__).parents[2] / inputs.QUALIFICATION / "development-old-open.records.jsonl"
        original = [json.loads(line) for line in path.read_text().splitlines()]
        cls.records = []
        for old in original:
            row = protocol.prepare_record(old)
            reference = semantic_fixture(row, row["final_answer"], True)
            row["protocol_reference_receipt"] = reference
            row["verified_outcome"] = {"success": True, "receipt_sha256": reference["receipt_sha256"],
                                       "verifier_name": "repo_patch", "verifier_version": "1"}
            cls.records.append(row)
        cls.parent = {"schema": probe.SCHEMA, "family": probe.FAMILY, "model_id": probe.MODEL_ID,
                      "runtime": {"device": "cuda:0", "dtype": "bfloat16", "max_input_tokens": 4096},
                      "backend_versions": {name: "unit-fixture" for name in ("torch", "transformers", "tokenizers", "safetensors")}}

    def test_B_success_cannot_unlock_A_zero_or_launch_any_work(self):
        records = [self.records[0], self.records[6]]
        readiness = ready_fixture(records, self.parent, [False, True])
        gate = inputs.bound_readiness(records, self.parent, readiness, "3" * 64)
        self.assertEqual(gate["successful_A_tasks"], 0)
        with tempfile.TemporaryDirectory() as temporary, patch.object(runner, "child", side_effect=AssertionError("no child permitted")):
            freeze = {"output": temporary, "status": "NOT_READY"}
            report = runner.run({}, freeze, io.usage())
            self.assertEqual((report["status"], report["fits_started"], report["new_model_calls"], report["new_reference_calls"]),
                             ("NOT_READY", 0, 0, 0))
            self.assertFalse((Path(temporary) / "workers").exists())

    def test_request_binding_survives_rehashed_aggregate_tampering(self):
        records = [self.records[0]]
        for key, changed in (("input_sha256", "4" * 64), ("messages_sha256", "5" * 64),
                             ("loaded_model_digest", "6" * 64), ("generation_config_sha256", "7" * 64)):
            with self.subTest(key=key):
                readiness = ready_fixture(records, self.parent, [True])
                step = readiness["rows"][0]["steps"][0]
                step["output"][key] = changed
                step["receipt_sha256"] = data.digest({k: v for k, v in step.items() if k != "receipt_sha256"})
                readiness["receipt_sha256"] = data.digest({k: v for k, v in readiness.items() if k != "receipt_sha256"})
                with self.assertRaisesRegex(ValueError, "native request"):
                    inputs.bound_readiness(records, self.parent, readiness, "3" * 64)

    def test_positive_counter_does_not_replace_original_and_control_observations(self):
        readiness = ready_fixture([self.records[0]], self.parent, [False])
        readiness["successful_tasks"] = 1
        readiness["receipt_sha256"] = data.digest({k: v for k, v in readiness.items() if k != "receipt_sha256"})
        with self.assertRaisesRegex(ValueError, "counters disagree"):
            inputs.bound_readiness([self.records[0]], self.parent, readiness, "3" * 64)

    def test_retained_raw_output_must_match_the_readiness_aggregate(self):
        record = self.records[0]
        readiness = ready_fixture([record], self.parent, [True])
        step = readiness["rows"][0]["steps"][0]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "0"
            request = {"record_id": record["record_id"],
                       "task": {"input": record["task"]["input"], "messages": protocol.require_prepared(record)}}
            io.write_new(directory / "request-0.json", request)
            io.write_new(directory / "output-0.json", {**step["output"], "answer": "another retained output"})
            io.write_new(directory / "step-0.json", step)
            with self.assertRaisesRegex(ValueError, "retained raw"):
                inputs.bound_readiness([record], self.parent, readiness, "3" * 64, temporary)

    def test_retrieval_never_uses_B_answer_and_retention_excludes_self(self):
        a, b = self.records[:2], copy.deepcopy(self.records[6])
        before = copy.deepcopy(a)
        shown, bindings = inputs.retrieval_panels(a, {"B_exposed": [b], "A_retention": a})
        b["final_answer"] = "UNIQUE_B_REFERENCE_MUST_NEVER_ENTER_MODEL_PROMPT"
        changed, _ = inputs.retrieval_panels(a, {"B_exposed": [b]})
        self.assertEqual(shown["B_exposed"][0]["task"], changed["B_exposed"][0]["task"])
        self.assertNotIn(b["final_answer"], changed["B_exposed"][0]["task"]["input"])
        self.assertEqual(a, before)
        self.assertEqual([row["retrieved_record_id"] for row in bindings["A_retention"]], [a[1]["record_id"], a[0]["record_id"]])
        with self.assertRaisesRegex(ValueError, "self-answer fallback"):
            inputs.retrieval_panels(a[:1], {"A_retention": a[:1]})

    def test_executed_data_cannot_be_relabeled_shadow(self):
        observed = ready_fixture([self.records[0]], self.parent, [True])["rows"][0]
        with tempfile.TemporaryDirectory() as temporary, patch.object(data, "verify_answer", side_effect=AssertionError("reference must not run")):
            with self.assertRaisesRegex(ValueError, "relabeled shadow"):
                inputs.corrected(self.records[0], observed, "shadow", temporary)

    def test_fresh_shadow_and_reused_controlled_form_four_plans_before_fits(self):
        records = copy.deepcopy(self.records[:6])
        readiness = ready_fixture(records, self.parent, [True, False, False, False, False, False])
        gate = inputs.bound_readiness(records, self.parent, readiness, "3" * 64)
        requests = []
        parent = self.parent

        class ScriptedPredictor:
            """Explicit engineering fixture: never a model or claimed capability."""
            model_digest = data.digest(parent)
            generation_digest = "3" * 64

            def __init__(self, *_args):
                self.closed = False

            def predict(self, request):
                requests.append(copy.deepcopy(request))
                return {"answer": "new scripted shadow output", "loaded_model_digest": self.model_digest,
                        "input_sha256": hashlib.sha256(request["task"]["input"].encode()).hexdigest(),
                        "messages_sha256": data.digest(request["task"]["messages"]),
                        "input_tokens": 7, "output_tokens": 3}

            def close(self):
                self.closed = True

        context = {"records": records, "parent": self.parent, "readiness": readiness,
                   "gate": gate, "generation_digest": "3" * 64}
        with tempfile.TemporaryDirectory() as temporary, patch.object(probe, "Predictor", ScriptedPredictor), \
                patch.object(repo_execution, "load_catalog", return_value=None):
            # Loading the catalog is read-only. The fixture isolates it here to
            # guarantee this test cannot accidentally invoke a real subject.
            with patch.object(data, "verify_answer", side_effect=lambda row, answer: semantic_fixture(row, answer, True)) as references, \
                    patch.object(contract.metadata, "version", return_value="unit-fixture"):
                result = worker.collect(context, {"artifact_root": temporary, "readiness_directory": "unit-fixture-only",
                                                  "operation_id": "engineering-fixture"}, Path(temporary))
            self.assertEqual((len(requests), references.call_count, result["new_student_verifier_calls"],
                              result["controlled_new_model_calls"]), (6, 12, 0, 0))
            self.assertTrue(all(set(request) == {"record_id", "task"} and set(request["task"]) == {"input", "messages"}
                                for request in requests))
            plans = io.read(Path(temporary) / "PLANS.json")
            self.assertEqual({name: plan["training"]["steps"] for name, plan in plans.items()},
                             {name: 64 for name in io.FIT_MODES})
            for name in ("shadow", "controlled"):
                corrected = io.read(Path(temporary) / (name + "_correction.records.json"))
                for original, derived in zip(records, corrected):
                    self.assertEqual({k: derived[k] for k in ("task_id", "source_id", "lineage_id", "split")},
                                     {k: original[k] for k in ("task_id", "source_id", "lineage_id", "split")})
                    self.assertTrue(all(event["trainable"] is False for event in derived["trajectory"] if event["actor"] == "student"))
            shadow = io.read(Path(temporary) / "shadow/0/step-0.json")
            self.assertIsNone(shadow["verification"])
            self.assertEqual(shadow["semantic_measurement"], "unmeasured")
            self.assertEqual(io.read(Path(temporary) / "CONTROLLED_REUSE.json")["observations"], gate["controlled_observations"])
            self.assertFalse(list(Path(temporary).rglob("adapter_model.safetensors")))

    def test_nonzero_child_exit_preserves_output_and_never_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "child"
            result = io.launch([sys.executable, "-I", "-B", "-c",
                                "import sys; print('single invocation', flush=True); sys.exit(7)"], path, 5)
            self.assertEqual(result["exit_code"], 7)
            self.assertFalse(result["timed_out"])
            self.assertEqual((path / "stdout.log").read_text(), "single invocation\n")
            with self.assertRaises(FileExistsError):
                io.launch([sys.executable, "-c", "raise AssertionError('must not run')"], path, 5)

    def test_owned_child_timeout_is_bounded_and_preserves_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "timeout"
            result = io.launch([sys.executable, "-I", "-B", "-c",
                                "import time; print('started', flush=True); time.sleep(10)"], path, 0.2)
            self.assertTrue(result["timed_out"])
            self.assertNotEqual(result["exit_code"], 0)
            self.assertIn("started", (path / "stdout.log").read_text())

    def test_cold_regression_checks_manifest_identity_and_retains_negative_change(self):
        evaluation = {"model_digest": "a" * 64, "generation_digest": "b" * 64,
                      "original_panels_digest": "c" * 64, "shown_panels_digest": "d" * 64,
                      "successful_tasks": 1, "rows": [{"panel": "B_exposed", "task_id": "fixture",
                      "success": True, "first_attempt_success": True,
                      "steps": [{"output": {"answer": "scripted one", "output_token_ids": [1]}}]}]}
        primary = {"pid": 101, "manifest": {"sha256": "e" * 64}, "evaluation": evaluation}
        cold = copy.deepcopy(primary)
        cold["pid"] = 102
        cold["evaluation"]["successful_tasks"] = 0
        cold["evaluation"]["rows"][0]["success"] = False
        comparison = runner.cold_comparison(primary, cold)
        self.assertFalse(comparison["business_outcomes_equal"])
        self.assertEqual(comparison["independent_sample_increment"], 0)
        cold["manifest"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "same manifest"):
            runner.cold_comparison(primary, cold)

    def test_file_inventory_detects_changed_and_unexpected_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bound.json").write_text("{\"identity\":1}")
            inventory = {"bound.json": io.file_hash(root / "bound.json")}
            io.verify_inventory(root, inventory, exact=True)
            (root / "bound.json").write_text("{\"identity\":2}")
            with self.assertRaisesRegex(ValueError, "content changed"):
                io.verify_inventory(root, inventory, exact=True)
            (root / "extra.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                io.verify_inventory(root, inventory, exact=True)

    def evaluation_fixture(self, failing_call=None):
        parent = self.parent
        class ScriptedPredictor:
            """Explicit synthetic actor for panel accounting, never a real model."""
            model_digest = data.digest(parent)
            generation_digest = "3" * 64
            generation = SimpleNamespace(to_dict=lambda: {})
            device_report = {"fixture": "no GPU accessed"}
            calls, closed = 0, False

            def predict(self, request):
                self.calls += 1
                if self.calls == failing_call:
                    raise ValueError("deliberate synthetic prediction failure")
                return {"answer": "synthetic panel accounting output",
                        "loaded_model_digest": self.model_digest,
                        "input_sha256": hashlib.sha256(request["task"]["input"].encode()).hexdigest(),
                        "messages_sha256": data.digest(request["task"]["messages"]),
                        "input_tokens": 7, "output_tokens": 3, "hit_output_limit": False}

            def close(self):
                self.closed = True

        panels = {"B_exposed": self.records[6:7], "A_retention": self.records[:2]}
        context = {"parent": parent, "panels": panels, "generation_digest": "3" * 64,
                   "retrieval_bindings": {}, "retrieval_panels": panels}
        cuda = SimpleNamespace(empty_cache=lambda: None, reset_peak_memory_stats=lambda *_: None,
                               max_memory_allocated=lambda *_: 0, max_memory_reserved=lambda *_: 0)
        return context, ScriptedPredictor(), SimpleNamespace(cuda=cuda)

    def test_real_panel_clocks_separate_A_and_B_without_extra_predictions(self):
        from cell_experiments import causal_train_v3 as train
        context, predictor, torch = self.evaluation_fixture()
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(repo_execution, "load_catalog", return_value=None), \
                patch.object(probe, "_libraries", return_value=(torch, None)), \
                patch.object(probe, "check_device", return_value={}), \
                patch.object(train, "load_predictor", return_value=predictor), \
                patch.object(data, "verify_answer", side_effect=lambda row, answer: semantic_fixture(row, answer, True)):
            output = Path(temporary) / "evaluation"
            result = worker.evaluate(context, {"artifact_root": temporary}, self.parent, output, "parent", "primary")
            self.assertEqual((predictor.calls, predictor.closed), (3, True))
            for panel, count in (("B_exposed", 1), ("A_retention", 2)):
                receipt = io.read(output / panel / "MEASUREMENT.json")
                io.verify_receipt(receipt)
                self.assertEqual(receipt, result["panel_measurements"][panel])
                self.assertEqual((receipt["status"], receipt["model_calls"], receipt["student_verifier_calls"],
                                  receipt["input_tokens"], receipt["output_tokens"]),
                                 ("COMPLETE", count, count, 7 * count, 3 * count))
                self.assertEqual(receipt["raw_receipt_read_errors"], [])
                self.assertTrue((output / panel / "STARTED.json").is_file())
                self.assertGreaterEqual(receipt["cost"]["wall_seconds"], 0)
                self.assertGreaterEqual(receipt["cost"]["own_cpu_seconds"], 0)
                self.assertGreaterEqual(receipt["cost"]["completed_child_cpu_seconds"], 0)
                self.assertFalse(receipt["cost"]["includes_model_load_or_close"])
                self.assertTrue(receipt["cost"]["parent_evaluation_cost_must_not_be_added"])
                self.assertIsNone(receipt["cost"]["gpu_active_seconds"])

    def test_failed_panel_preserves_partial_calls_and_excludes_missing_output(self):
        from cell_experiments import causal_train_v3 as train
        context, predictor, torch = self.evaluation_fixture(failing_call=3)
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(repo_execution, "load_catalog", return_value=None), \
                patch.object(probe, "_libraries", return_value=(torch, None)), \
                patch.object(probe, "check_device", return_value={}), \
                patch.object(train, "load_predictor", return_value=predictor), \
                patch.object(data, "verify_answer", side_effect=lambda row, answer: semantic_fixture(row, answer, True)):
            output = Path(temporary) / "evaluation"
            with self.assertRaisesRegex(ValueError, "deliberate synthetic"):
                worker.evaluate(context, {"artifact_root": temporary}, self.parent, output, "parent", "primary")
            receipt = io.read(output / "A_retention/FAILED.json")
            io.verify_receipt(receipt)
            self.assertEqual((predictor.calls, predictor.closed), (3, True))
            self.assertEqual((receipt["status"], receipt["persisted_requests"], receipt["completed_output_receipts"],
                              receipt["calls_without_completed_output_receipt"], receipt["completed_tasks"]),
                             ("FAILED_PRESERVED", 2, 1, 1, 1))
            self.assertIsNone(receipt["model_calls"])
            self.assertIsNone(receipt["input_tokens"])
            self.assertEqual((receipt["input_tokens_measured_subtotal"], receipt["output_tokens_measured_subtotal"]), (7, 3))
            self.assertFalse(receipt["automatic_retry"])
            self.assertTrue((output / "A_retention/STARTED.json").is_file())
            self.assertTrue((output / "B_exposed/MEASUREMENT.json").is_file())
            self.assertFalse((output / "EVALUATION.json").exists())


if __name__ == "__main__":
    unittest.main()
