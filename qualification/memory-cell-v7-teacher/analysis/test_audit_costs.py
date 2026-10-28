"""Synthetic evidence only: accounting, deduplication, and binding fault checks."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import audit_costs as audit


def write_json(path, value):
    path.write_bytes(audit.canonical(value) + b"\n")


def usage(input_tokens, output_tokens):
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens}


def make_fixture(root):
    (root / "teacher").mkdir(parents=True)
    (root / "holdout").mkdir()
    freeze = b'{"synthetic_test":true}\n'
    (root / "teacher" / "FREEZE.json").write_bytes(freeze)
    # status, result usage, terminal usage, event, repetitions, trailing delimiter
    specs = [
        ("completed", usage(10, 2), usage(10, 2), "response.completed", 1, True),
        ("unknown_or_invalid", usage(11, 3), usage(11, 3), "response.completed", 1, True),
        ("unknown_or_invalid", None, usage(12, 4), "response.failed", 1, True),
        ("unknown_or_invalid", None, None, None, 0, True),
        ("unknown_or_invalid", usage(13, 5), usage(13, 5), "response.completed", 2, True),
        ("unknown_or_invalid", usage(14, 6), usage(15, 7), "response.completed", 1, True),
        ("unknown_or_invalid", None, usage(16, 8), "response.incomplete", 1, True),
        ("unknown_or_invalid", None, usage(17, 9), "response.completed", 1, False),
    ]
    for run_name, selected in (("teacher-held-v1", specs),
                               ("public-training-smoke-v1", [("completed", usage(1, 1), usage(1, 1), "response.completed", 1, True)])):
        run_dir = root / "evidence" / run_name
        run_dir.mkdir(parents=True)
        requests = [{"utterance": "synthetic cost fixture " + str(index),
                     "series_name": "synthetic", "date": "2020-01"} for index in range(len(selected))]
        input_raw = b"".join(audit.canonical(request) + b"\n" for request in requests)
        input_path = root / "holdout" / "requests.jsonl" if run_name == "teacher-held-v1" else root / "smoke-inputs.jsonl"
        input_path.write_bytes(input_raw)
        run = {"run_id": "synthetic-" + run_name, "requests": len(selected),
               "input_sha256": audit.sha(input_raw), "freeze_sha256": audit.sha(freeze),
               "prompt_sha256": audit.sha(b"synthetic audit fixture"),
               "model": "synthetic-model", "endpoint": "https://invalid.example.test"}
        write_json(run_dir / "RUN.json", run)
        results = []
        for index, (status, result_usage, terminal_usage, event, repeats, delimiter) in enumerate(selected):
            request = requests[index]
            case = run_dir / f"case-{index:04d}"
            case.mkdir()
            body = audit.canonical({"model": run["model"], "instructions": "synthetic audit fixture",
                "input": [{"role": "user", "content": [{"type": "input_text", "text": audit.canonical(request).decode()}]}]})
            operation = "hepta-route-" + audit.sha(audit.canonical({"run_id": run["run_id"],
                "input_sha256": run["input_sha256"], "freeze_sha256": run["freeze_sha256"],
                "index": index, "body_sha256": audit.sha(body)}))
            (case / "request.body.json").write_bytes(body)
            admission = {"operation_id": operation, "index": index,
                "request_sha256": audit.sha(audit.canonical(request)), "body_sha256": audit.sha(body),
                "submission_attempted": True, "automatic_retry_allowed": False,
                "endpoint": run["endpoint"], "model": run["model"]}
            write_json(case / "admission.json", admission)
            provider = "synthetic-response-" + run_name + "-" + str(index) if event else None
            raw = b""
            if event:
                created = {"type": "response.created", "response": {"id": provider}}
                terminal = {"type": event, "response": {"id": provider,
                    "status": event.split(".")[-1], "usage": terminal_usage}}
                raw = b"data: " + audit.canonical(created) + b"\n\n"
                raw += (b"data: " + audit.canonical(terminal) + b"\n\n") * repeats
                if not delimiter:
                    raw = raw[:-2]
                (case / "response.sse").write_bytes(raw)
            result = {"operation_id": operation, "index": index,
                "request_sha256": admission["request_sha256"], "body_sha256": admission["body_sha256"],
                "status": status, "usage": result_usage, "provider_response_id": provider,
                "response_bytes": len(raw), "automatic_retries": 0}
            if event:
                result["response_sha256"] = audit.sha(raw)
            write_json(case / "result.json", result)
            results.append(result)
        (run_dir / "results.jsonl").write_bytes(b"".join(audit.canonical(result) + b"\n" for result in results))
        done = [result for result in results if result["status"] == "completed"]
        sums = audit.token_sum(result["usage"] for result in done)
        write_json(run_dir / "SUMMARY.json", {"completed": len(done),
            "usage": {key: {"known_sum": value, "known_requests": len(done)} for key, value in sums.items()}})


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def run_audit(self):
        output = self.root / "fresh-audit"
        with contextlib.redirect_stdout(io.StringIO()):
            code = audit.audit(self.root, output, Path("smoke-inputs.jsonl"))
        summary = json.loads((output / "COST_AUDIT.json").read_text())
        rows = [json.loads(line) for line in (output / "CASE_COSTS.jsonl").read_text().splitlines()]
        return code, summary, rows

    def test_all_status_usage_duplicates_conflicts_and_unknowns(self):
        code, report, rows = self.run_audit()
        self.assertEqual(code, 0)
        combined = report["combined"]
        self.assertEqual(combined["all_result_usage_including_invalid"]["recorded_token_sum"], usage(49, 17))
        self.assertEqual(combined["all_recorded_usage_deduplicated"]["recorded_token_sum"], usage(63, 23))
        self.assertEqual(combined["additional_terminal_usage_absent_from_results"]["recorded_token_sum"], usage(28, 12))
        self.assertEqual(combined["cases_without_resolved_usage"], 3)
        self.assertEqual(combined["sse_duplicate_terminal_events"], 1)
        self.assertIsNone(combined["total_provider_cost"])
        self.assertFalse(combined["missing_usage_assumed_zero"])
        held_rows = {row["index"]: row for row in rows if row["run"] == "teacher-held-v1"}
        self.assertEqual(held_rows[1]["classification"], "recorded_usage")
        self.assertEqual(held_rows[2]["recorded_tokens"], usage(12, 4))
        self.assertEqual(held_rows[3]["classification"], "unknown_usage")
        self.assertEqual(held_rows[5]["classification"], "conflicting_usage")
        self.assertEqual(held_rows[7]["classification"], "usage_only_in_undispatched_frame")
        self.assertTrue(report["original_sources_unchanged"])

    def test_response_hash_tampering_is_detected(self):
        path = self.root / "evidence/teacher-held-v1/case-0000/response.sse"
        path.write_bytes(path.read_bytes() + b"\n")
        code, report, rows = self.run_audit()
        self.assertEqual(code, 1)
        self.assertFalse(report["available_binding_checks_pass"])
        self.assertEqual(rows[0]["binding_checks"]["response_sha256"], "fail")

    def test_request_fingerprint_tampering_is_detected(self):
        path = self.root / "evidence/teacher-held-v1/case-0000/admission.json"
        admission = json.loads(path.read_bytes())
        admission["request_sha256"] = "0" * 64
        write_json(path, admission)
        code, _, rows = self.run_audit()
        self.assertEqual(code, 1)
        self.assertEqual(rows[0]["binding_checks"]["admission_request_sha256"], "fail")

    def test_operation_identity_tampering_is_detected(self):
        path = self.root / "evidence/teacher-held-v1/case-0000/admission.json"
        admission = json.loads(path.read_bytes())
        admission["operation_id"] = "unbound-operation"
        write_json(path, admission)
        code, _, rows = self.run_audit()
        self.assertEqual(code, 1)
        self.assertEqual(rows[0]["binding_checks"]["admission_operation_id"], "fail")

    def test_body_tampering_is_detected_without_emitting_text(self):
        path = self.root / "evidence/teacher-held-v1/case-0000/request.body.json"
        body = json.loads(path.read_bytes())
        body["instructions"] = "synthetic modified text that must not appear in audit output"
        path.write_bytes(audit.canonical(body))
        code, _, rows = self.run_audit()
        self.assertEqual(code, 1)
        self.assertEqual(rows[0]["binding_checks"]["admission_body_sha256"], "fail")
        self.assertEqual(rows[0]["binding_checks"]["prompt_sha256_matches_run"], "fail")
        self.assertNotIn(body["instructions"], (self.root / "fresh-audit/COST_AUDIT.json").read_text())

    def test_existing_output_cannot_be_overwritten(self):
        (self.root / "fresh-audit").mkdir()
        with self.assertRaisesRegex(ValueError, "new, nonexistent"):
            self.run_audit()

    def test_duplicate_json_key_and_inconsistent_usage_are_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            audit.decode(b'{"input_tokens":1,"input_tokens":2}')
        self.assertIsNone(audit.token_view({"input_tokens": 1, "output_tokens": 2, "total_tokens": 4})[0])
        self.assertIsNone(audit.token_view({"input_tokens": True, "output_tokens": 2})[0])

    def test_failed_terminal_in_crlf_stream_has_usage(self):
        event = {"type": "response.failed", "response": {"id": "failed-id", "usage": usage(4, 5)}}
        parsed = audit.sse_observations(b"data: " + audit.canonical(event) + b"\r\n\r\n")
        self.assertEqual(parsed["observations"][0]["tokens"], usage(4, 5))
        self.assertEqual(parsed["dispatched_terminal_events"], 1)

    def test_partial_usage_and_cached_components_are_retained_without_double_counting(self):
        metadata = audit.usage_metadata({"input_tokens": 20, "output_tokens": None,
            "input_tokens_details": {"cached_tokens": 18}})
        self.assertEqual(metadata["partial_token_counters"]["input_tokens"], 20)
        self.assertIsNone(metadata["partial_token_counters"]["output_tokens"])
        self.assertEqual(metadata["detail_counters"]["cached_input_tokens"], 18)
        self.assertEqual(audit.token_sum([usage(20, 3)]), usage(20, 3))
        invalid = audit.usage_metadata({"input_tokens": 20, "output_tokens": 3,
            "input_tokens_details": {"cached_tokens": 21}})
        self.assertIn("invalid_cached_input_tokens", invalid["detail_counter_errors"])


if __name__ == "__main__":
    unittest.main()
