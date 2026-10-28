"""Focused, synthetic-only checks for the read-only formal evidence summarizer."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("formal_summary", Path(__file__).with_name("formal_summary.py"))
SUMMARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUMMARY)


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


class FormalSummaryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.model_dir = self.root / "model"
        self.model_dir.mkdir()
        self.path = self.root / "REPORT.json"
        self.report = self.fixture()

    def tearDown(self):
        self.temporary.cleanup()

    def capture(self, name, call, body=None, output_tokens=3, total_tokens=None, emit_tool=None):
        body = body or {"model": SUMMARY.MODEL, "input": [{"role": "user", "content": "probe"}],
            "tools": [{"type": "function", "name": "hepta_probe", "parameters": {"type": "object"}}],
            "max_output_tokens": 256}
        original = wire(body)
        effective = dict(body)
        effective["max_output_tokens"] = min(int(body.get("max_output_tokens", 256)), 256)
        effective_raw = wire(effective)
        response_id = f"resp-{name}-{call}"
        item = {"type": "function_call", "call_id": "call-1", "name": "hepta_probe", "arguments": "{}"}
        output = [item] if (call == 1 if emit_tool is None else emit_tool) else []
        usage = {"input_tokens": 5, "output_tokens": output_tokens,
                 "total_tokens": output_tokens + 5 if total_tokens is None else total_tokens,
                 "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}
        events = [{"type": "response.created", "response": {"id": response_id}}]
        if output:
            events.append({"type": "response.output_item.done", "item": item})
        events.append({"type": "response.completed", "response": {"id": response_id, "status": "completed",
            "output": output, "usage": usage}})
        response_raw = b"".join(b"data: " + wire(event) + b"\n\n" for event in events)
        prefix = self.model_dir / f"{name}-model-{call:02}"
        prefix.with_suffix(".request.json").write_bytes(original)
        prefix.with_suffix(".response.sse").write_bytes(response_raw)
        return {"case": name, "call": call, "mode": "replay", "request_bytes": len(original),
            "effective_bytes": len(effective_raw), "request_sha256": sha(original), "effective_sha256": sha(effective_raw),
            "output_token_cap": effective["max_output_tokens"], "response_bytes": len(response_raw),
            "http_status": 200, "started_ns": call * 10, "finished_ns": call * 10 + 1}

    def fixture(self):
        plan = [{"name": "warmup", "task": "sum", "warmup": True}] + [
            {"name": f"{cycle:02}-{task}", "task": task, "warmup": False}
            for cycle in range(3) for task in ("sum", "lines", "digest")]
        rows = []
        for index, case in enumerate(plan):
            rows.append(dict(case, correct=True, correctness_pending_tool_audit=False,
                wall_ms=99 if case["warmup"] else index, answer_matches_exact_stdout_json=True,
                result={"status": "completed", "answer": "{}", "tool_calls": 1, "usage": {"output_tokens": 9999}},
                tool_feedback_audit={"valid": True, "errors": []},
                model_requests=[self.capture(case["name"], call) for call in (1, 2)]))
        return {"schema": "hepta.native.qualification.benchmark.v1", "mode": "replay", "lane": "native",
            "model": SUMMARY.MODEL, "planned_cases": plan, "rows": rows,
            "summary": {"attempted": 9, "planned": 9, "correct": 9, "completed_lane": True,
                "valid_equal_tool_comparison": True, "qualification_passed": True},
            "model_capture_complete": True, "only_shared_tool_inventory": True,
            "model_inventory": [{"file": path.name} for path in sorted(self.model_dir.glob("*.request.json"))],
            "startup_ms": 17, "shutdown_ms": 19, "runtime_helper_sha256": "helper", "executor_sha256": "executor",
            "fixture": {"script_sha256": "script", "data_sha256": "data"}, "case_timeout_seconds": 240,
            "budgets": {"context_bytes": 65536, "output_tokens": 256, "model_calls": 4, "tool_calls": 3},
            "metrics": {"elapsed_seconds": 10,
                "memory": {"pss_peak_complete_sample_bytes": 42 * 1048576, "pss_complete_samples": 10,
                    "pss_incomplete_samples": 2, "rss_peak_sum_bytes": 999 * 1048576, "pss_peak_observed_partial_bytes": 13},
                "sampling": {"samples": 12, "largest_actual_gap_seconds": .3, "stop_timeout": False},
                "cpu": {"cgroup_nonoverlap_observed_seconds": 2, "process_lifecycle_observed_seconds": 1,
                    "cgroup_nonoverlap_paths": ["/parent", "/detached"]},
                "coverage": {"gaps": {}, "global_total_memory_or_cpu_claim_supported": False},
                "cgroups": [{"path": "/parent", "memory_peak_lifetime_bytes": 777777777777}]}}

    def summarize(self):
        self.path.write_bytes(wire(self.report))
        return SUMMARY.summarize(self.path, self.model_dir)

    def test_primary_metrics_denominators_usage_and_read_only(self):
        self.path.write_bytes(wire(self.report))
        before = {str(path): sha(path.read_bytes()) for path in self.root.rglob("*") if path.is_file()}
        result = SUMMARY.summarize(self.path, self.model_dir)
        after = {str(path): sha(path.read_bytes()) for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(result["timing"]["measured_completed_rows_wall_ms"]["median"], 5)
        self.assertEqual(result["timing"]["measured_completed_rows_wall_ms"]["p95_nearest_rank"], 9)
        self.assertEqual(result["cases"]["measured"]["planned"], 9)
        self.assertEqual(result["cases"]["warmup"]["planned"], 1)
        self.assertEqual(result["resources"]["memory"]["primary_peak_mib"], 42)
        self.assertAlmostEqual(result["resources"]["memory"]["pss_complete_fraction"], 10 / 12)
        self.assertNotIn("777777777777", json.dumps(result))
        self.assertEqual(result["resources"]["cpu"]["cgroup_nonoverlap_observed_seconds"], 2)
        self.assertEqual(result["resources"]["cpu"]["process_lifecycle_observed_seconds"], 1)
        self.assertEqual(result["resources"]["cpu"]["per_measured_case_cpu"], "unknown")
        self.assertTrue(result["gates"]["reported_success_and_full_plan_verified"])
        self.assertTrue(result["gates"]["full_capture_budget_evidence_verified"])
        measured = result["model"]["measured_usage"]
        self.assertEqual(measured["tokens"]["output_tokens"]["sum"], 9 * 2 * 3)
        self.assertEqual(measured["kind"], "synthetic_replay_fixture")
        self.assertFalse(measured["captured_provider_primary_usage_complete"])
        self.assertTrue(all(row["captured_generated_tool_calls"] == 1 for row in result["model"]["case_budgets"]))

    def test_completed_wrong_answer_stays_in_latency_and_fails_correctness(self):
        self.report["rows"][4]["correct"] = False
        self.report["rows"][4]["answer_matches_exact_stdout_json"] = False
        self.report["summary"].update(correct=8, qualification_passed=False)
        result = self.summarize()
        self.assertEqual(result["cases"]["measured"]["correct_over_planned"], 8 / 9)
        self.assertEqual(result["cases"]["completed_measured"], 9)
        self.assertEqual(result["cases"]["completed_measured_incorrect"], 1)
        self.assertEqual(result["timing"]["measured_completed_rows_wall_ms"]["n_known"], 9)
        self.assertFalse(result["gates"]["reported_success_and_full_plan_verified"])

    def test_abort_keeps_original_denominator_and_missing_completion_is_unknown(self):
        self.report["rows"] = self.report["rows"][:3]
        self.report["rows"][-1].update(error="timeout", correct=False)
        self.report["summary"].update(attempted=2, correct=1, qualification_passed=False, completed_lane=False)
        result = self.summarize()
        self.assertEqual(result["cases"]["measured"]["correct_over_planned"], 1 / 9)
        self.assertEqual(len(result["cases"]["unrun"]), 7)
        self.assertEqual(result["timing"]["measured_completed_rows_wall_ms"]["n_known"], 1)
        self.assertEqual(result["timing"]["measured_attempted_rows_wall_ms"]["n_known"], 2)
        self.report["rows"][1]["result"].pop("status")
        result = self.summarize()
        self.assertEqual(result["cases"]["completion_status_unknown"], 1)
        self.assertEqual(result["cases"]["measured"]["correct_over_planned"], "unknown")

    def test_missing_captures_never_fall_back_to_result_usage(self):
        self.model_dir.rename(self.root / "unavailable-captures")
        result = self.summarize()
        self.assertEqual(result["model"]["measured_usage"]["tokens"]["output_tokens"]["sum"], "unknown")
        self.assertEqual(result["model"]["calls"][0]["actual_model"], "unknown")
        self.assertEqual(result["gates"]["completed_output_tokens_within_256"], "unknown")
        self.assertEqual(result["gates"]["full_capture_budget_evidence_verified"], "unknown")

    def test_actual_request_effective_transform_and_output_budget(self):
        row = self.report["rows"][1]
        body = {"model": SUMMARY.MODEL, "tools": [{"type": "function", "name": "hepta_probe"}], "max_output_tokens": 512}
        row["model_requests"][0] = self.capture(row["name"], 1, body, output_tokens=257)
        result = self.summarize()
        call = next(call for call in result["model"]["calls"] if call["case"] == row["name"] and call["call"] == 1)
        self.assertEqual(call["actual_max_output_tokens"], 512)
        self.assertFalse(call["requested_cap_within_256"])
        self.assertTrue(call["effective_cap_verified_within_256"])
        self.assertFalse(call["completed_output_tokens_within_256"])
        self.assertFalse(result["gates"]["full_capture_budget_evidence_verified"])
        body.pop("max_output_tokens")
        row["model_requests"][0] = self.capture(row["name"], 1, body)
        result = self.summarize()
        call = next(call for call in result["model"]["calls"] if call["case"] == row["name"] and call["call"] == 1)
        self.assertEqual(call["actual_max_output_tokens"], "unknown")
        self.assertTrue(call["effective_cap_verified_within_256"])
        self.assertTrue(result["gates"]["full_capture_budget_evidence_verified"])

    def test_actual_oversize_wrong_model_and_extra_tool_fail_audit(self):
        row = self.report["rows"][1]
        body = {"model": "different-alias", "max_output_tokens": 256, "input": "x" * 65536,
                "tools": [{"type": "function", "name": "hepta_probe"}, "invalid"]}
        row["model_requests"][0] = self.capture(row["name"], 1, body)
        result = self.summarize()
        for field in ("request_bytes_within_65536", "advertised_model_matches", "actual_only_shared_tool_inventory",
                      "effective_request_bytes_verified_within_65536", "full_capture_budget_evidence_verified"):
            self.assertFalse(result["gates"][field])
        self.assertEqual(result["model"]["provider_weight_or_deployment_pin"], "unknown")

    def test_call_budget_counts_per_response_and_unknown_usage_is_not_zero(self):
        row = self.report["rows"][1]
        for call in (3, 4, 5):
            row["model_requests"].append(self.capture(row["name"], call, emit_tool=True))
        row["result"]["tool_calls"] = 4
        result = self.summarize()
        self.assertFalse(result["gates"]["captured_model_call_budget"])
        self.assertFalse(result["gates"]["executor_tool_call_budget"])
        self.assertFalse(result["gates"]["generated_tool_call_budget"])
        case = next(case for case in result["model"]["case_budgets"] if case["name"] == row["name"])
        self.assertEqual(case["captured_generated_tool_calls"], 4)
        row["model_requests"][0] = self.capture(row["name"], 1, total_tokens=100)
        result = self.summarize()
        self.assertEqual(result["model"]["measured_usage"]["tokens"]["total_tokens"]["sum"], "unknown")
        self.assertGreater(result["model"]["measured_usage"]["tokens"]["total_tokens"]["known_partial_sum"], 0)
        path = self.model_dir / f"{row['name']}-model-02.response.sse"
        path.write_bytes(b"data: {malformed}\n\n")
        result = self.summarize()
        self.assertEqual(result["model"]["measured_usage"]["tokens"]["output_tokens"]["sum"], "unknown")

    def test_overlap_cpu_and_missing_primary_memory_never_substitute_rss(self):
        self.report["metrics"]["cpu"]["cgroup_nonoverlap_paths"] = ["/parent", "/parent/child"]
        self.report["metrics"]["memory"].pop("pss_peak_complete_sample_bytes")
        result = self.summarize()
        self.assertEqual(result["resources"]["cpu"]["cgroup_nonoverlap_observed_seconds"], "unknown")
        self.assertEqual(result["resources"]["memory"]["primary_peak_bytes"], "unknown")
        self.assertEqual(result["resources"]["memory"]["rss_peak_sum_bytes_diagnostic_only"], 999 * 1048576)

    def test_cli_markdown_unknown_matrix_and_input_error_exit(self):
        self.path.write_bytes(wire(self.report))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = SUMMARY.main([str(self.path), "--format", "markdown"])
        self.assertEqual(code, 0)
        self.assertIn("Measured completed rows median", output.getvalue())
        self.assertIn('"six_unique_formal_lanes_present": false', output.getvalue())
        self.path.write_text('{"rows":[],"rows":[]}')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = SUMMARY.main([str(self.path)])
        self.assertEqual(code, 2)
        self.assertIn("duplicate JSON key", output.getvalue())

    def test_full_six_lane_matrix_and_live_usage_have_separate_warmup(self):
        paths = []
        for mode in SUMMARY.MODES:
            for lane in SUMMARY.LANES:
                count = 10 if mode == "replay" else 7
                report = copy.deepcopy(self.report)
                report.update(mode=mode, lane=lane, executor_sha256=f"executor-{lane}")
                report["rows"] = report["rows"][:count]
                report["planned_cases"] = report["planned_cases"][:count]
                report["summary"].update(planned=count - 1, attempted=count - 1, correct=count - 1)
                report["model_inventory"] = []
                model_dir = self.root / f"{mode}-{lane}" / "model"
                model_dir.mkdir(parents=True)
                for row in report["rows"]:
                    for record in row["model_requests"]:
                        record["mode"] = mode
                        prefix = f"{row['name']}-model-{record['call']:02}"
                        for suffix in (".request.json", ".response.sse"):
                            shutil.copyfile(self.model_dir / (prefix + suffix), model_dir / (prefix + suffix))
                        report["model_inventory"].append({"file": prefix + ".request.json"})
                path = model_dir.parent / "REPORT.json"
                path.write_bytes(wire(report))
                paths.append(str(path))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = SUMMARY.main(paths)
        bundle = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(bundle["comparison_checks"]["six_unique_formal_lanes_present"])
        self.assertTrue(all(bundle["comparison_checks"]["same_executor_across_modes"].values()))
        self.assertTrue(all(bundle["comparison_checks"]["same_case_order_per_mode"].values()))
        self.assertEqual(bundle["comparison_checks"]["same_provider_weights"], "unknown")
        for report in bundle["reports"]:
            self.assertTrue(report["gates"]["reported_success_and_full_plan_verified"])
            self.assertTrue(report["gates"]["full_capture_budget_evidence_verified"])
            if report["mode"] == "live":
                self.assertEqual(report["model"]["measured_usage"]["tokens"]["total_tokens"]["sum"], 6 * 2 * 8)
                self.assertEqual(report["model"]["warmup_usage"]["tokens"]["total_tokens"]["sum"], 2 * 8)
                self.assertTrue(report["model"]["measured_usage"]["captured_provider_primary_usage_complete"])


if __name__ == "__main__":
    unittest.main()
