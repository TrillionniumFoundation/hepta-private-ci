"""Exercise failure accounting, real HTTP captures and upstream build binding."""

import http.server
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import benchmark_accounting as accounting
import representative_compare as runner
from model_gateway import ModelGateway
from protocol_driver import LaneAbort
from script_gateway import ScriptGateway


def post(url, body):
    request = urllib.request.Request(url + "/responses", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class AccountingTests(unittest.TestCase):
    def test_rejected_request_and_failed_task_keep_all_observed_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            gateway = ScriptGateway("replay", "http://127.0.0.1:1/v1", evidence, model_calls=3)
            gateway.begin_script("failed-task", [])
            try:
                self.assertEqual(post(gateway.url, {"model": "qwen38-flash-next-uc", "input": []})[0], 200)
                self.assertEqual(post(gateway.url, {"model": "different", "input": []})[0], 400)
            finally:
                gateway.close()
            result = accounting.account_model_attempts(evidence, "replay")
            self.assertEqual(result["attempted_requests"], 2)
            self.assertEqual(result["exact_usage_total"], {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
            self.assertEqual(result["attempts"][1]["usage_state"], "verified_not_dispatched")
            self.assertEqual(len(list(evidence.glob("*.request.raw"))), 2)
            report = accounting.summarize([{"lane": "native", "case": "repair", "repeat": 0,
                "status": "failed", "attempt_wall_ms": 1900, "model_accounting": result}])
            totals = report["by_lane_including_failed_tasks"]["native"]
            self.assertEqual(totals["failed_tasks"], 1)
            self.assertEqual(totals["known_usage_subtotal"]["total_tokens"], 15)
            self.assertEqual(totals["attempt_wall_ms"], 1900)

    def test_live_partial_stream_and_missing_final_record_remain_unknown(self):
        class Partial(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b'data: {"type":"response.created","response":{"id":"original"}}\n\n')

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Partial)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                evidence = Path(directory)
                gateway = ModelGateway("live", f"http://127.0.0.1:{server.server_port}/v1", evidence)
                gateway.begin("partial", "sum", "42")
                try:
                    self.assertEqual(post(gateway.url, {"model": "qwen38-flash-next-uc", "input": []})[0], 200)
                finally:
                    gateway.close()
                result = accounting.account_model_attempts(evidence, "live")
                self.assertEqual(result["attempted_requests"], 1)
                self.assertEqual(result["unknown_usage_attempts"], 1)
                self.assertIsNone(result["exact_usage_total"])
                self.assertFalse(result["complete"])
                (evidence / "model_requests.jsonl").unlink()
                result = accounting.account_model_attempts(evidence, "live")
                self.assertEqual(result["unknown_usage_attempts"], 1)
                self.assertIsNone(result["attempts"][0]["usage"])
        finally:
            server.shutdown()
            server.server_close()

    def test_noncompleted_provider_terminal_usage_counts_and_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            started = {"attempt": 1, "dispatch_state": "not_dispatched"}
            final = {"attempt": 1, "dispatch_state": "dispatch_attempted", "response_file": "one.response.sse"}
            (evidence / "model_attempts.jsonl").write_text(json.dumps(started) + "\n")
            (evidence / "model_requests.jsonl").write_text(json.dumps(final) + "\n")
            terminal = {"type": "response.incomplete", "response": {"id": "original", "status": "incomplete",
                "usage": {"input_tokens": 20, "output_tokens": 2, "total_tokens": 22}}}
            wire = "data: " + json.dumps(terminal) + "\n\n"
            (evidence / "one.response.sse").write_text(wire)
            result = accounting.account_model_attempts(evidence, "live")
            self.assertEqual(result["exact_usage_total"]["total_tokens"], 22)
            (evidence / "one.response.sse").write_text(wire + wire)
            result = accounting.account_model_attempts(evidence, "live")
            self.assertIsNone(result["exact_usage_total"])
            self.assertEqual(result["unknown_usage_attempts"], 1)

    def test_initial_provider_differences_are_visible_without_rewriting_task(self):
        rows = []
        tools = [{"type": "function", "name": "read", "description": "Read", "parameters": {"type": "object"}}]
        with tempfile.TemporaryDirectory() as directory:
            for lane, extra in (("native", []), ("app-server", [{"role": "user", "content": "framework environment"}])):
                evidence = Path(directory) / lane
                evidence.mkdir()
                request = {"model": "same-model", "instructions": "same-rules", "tools": tools,
                    "input": extra + [{"role": "user", "content": "same-task"}]}
                (evidence / "one.request.json").write_text(json.dumps(request))
                condition = accounting.initial_conditions(evidence, "same-task", "same-rules", tools)
                self.assertTrue(condition["original_prompt_present"])
                self.assertTrue(condition["tool_descriptors_exact"])
                rows.append({"lane": lane, "case": "edit", "repeat": 0, "status": "passed",
                    "initial_conditions": condition})
        parity = accounting.summarize(rows)["initial_condition_parity"][0]
        self.assertTrue(parity["same_requested_task_policy"])
        self.assertFalse(parity["exact_provider_conditions_equal"])

    def test_old_version_build_is_refused_before_running_any_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "OFFICIAL_BUILD.json"
            path.write_text(json.dumps({"schema": "hepta.codex-build.v2", "release": "0.165.0"}))
            with mock.patch.object(accounting.subprocess, "run") as called:
                with self.assertRaisesRegex(ValueError, "actual pinned 0.166.0"):
                    accounting.verify_codex_build(path, Path("missing"), Path("missing"))
                called.assert_not_called()

    def test_failure_path_retains_original_pending_identity_wall_and_tokens(self):
        class Metrics:
            def __init__(self, **_):
                self.stopped = False

            def start(self):
                return self

            def stop(self):
                self.stopped = True
                return {"observed_failure_window": True}

        class Backend:
            def __init__(self, argv, *_):
                self.config = json.loads(Path(argv[1]).read_bytes())
                self.ready = False

            def send(self, _):
                url = self.config["responses_url"].removesuffix("/responses")
                post(url, {"model": "qwen38-flash-next-uc", "input": []})

            def receive(self, _):
                if not self.ready:
                    self.ready = True
                    return {"ready": True, "tools": [], "qualification_owner_scope": runner.OWNER_SCOPE,
                            "ui": runner.UI_CONTRACT}
                raise LaneAbort("original tool is unknown", {"status": "pending_tool", "job_id": "original-job"})

            def close(self):
                pass

        case = next(c for c in json.loads((HERE / "corpus.json").read_bytes())["cases"] if c["id"] == "mcp_readonly")
        with tempfile.TemporaryDirectory() as directory:
            args = types.SimpleNamespace(output=Path(directory), native=Path("fixture"), mode="replay",
                upstream="http://127.0.0.1:1/v1", group="behavior_matched", timeout=5,
                profiles={"native": {"budgets": runner.BUDGET}}, metrics_interval=0.5,
                identity=runner.identity_contract("replay", {}, "http://127.0.0.1:1/v1"))
            with mock.patch.object(runner, "JsonProcess", Backend), mock.patch.object(runner, "ProcessMetrics", Metrics):
                row = runner.run_case(args, "native", case, 0)
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["result"]["job_id"], "original-job")
            self.assertGreater(row["wall_ms"], 0)
            self.assertGreaterEqual(row["attempt_wall_ms"], row["wall_ms"])
            self.assertTrue(row["metrics"]["observed_failure_window"])
            self.assertEqual(row["model_accounting"]["known_usage_subtotal"]["total_tokens"], 15)
            self.assertIsNone(row["product_total_cost"])
            self.assertFalse(row["execution_layer_causal_attribution"])

    def test_release_lock_fix_changes_only_local_workspace_versions(self):
        builder = HERE.parent / "provenance-0166/build_codex.py"
        if not builder.exists():
            builder = HERE.parent / "provenance/official-0166/build_codex.py"
        spec = importlib.util.spec_from_file_location("build_codex_0166", builder)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "codex-rs/example").mkdir(parents=True)
            (root / "codex-rs/Cargo.toml").write_text('[workspace.package]\nversion = "0.166.0"\n')
            (root / "codex-rs/example/Cargo.toml").write_text('[package]\nname = "example"\nversion.workspace = true\n')
            lock = 'version = 4\n\n[[package]]\nname = "example"\nversion = "0.0.0"\n\n[[package]]\nname = "external"\nversion = "1.2.3"\nsource = "registry+https://example.test/index"\nchecksum = "unchanged"\n'
            (root / "codex-rs/Cargo.lock").write_text(lock)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            changed, patch = module.normalize_local_lock(root)
            self.assertEqual(changed, [{"name": "example", "from": "0.0.0", "to": "0.166.0"}])
            self.assertIn('-version = "0.0.0"', patch)
            self.assertIn('name = "external"\nversion = "1.2.3"', (root / "codex-rs/Cargo.lock").read_text())


if __name__ == "__main__":
    unittest.main()
