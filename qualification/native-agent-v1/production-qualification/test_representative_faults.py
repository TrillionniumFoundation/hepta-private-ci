"""Exercise actual process fixtures and reject unauthorized recovery transitions."""

import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import representative_faults as faults
from protocol_driver import LaneAbort
from ui_collector import OWNER_SCOPE, UI_CONTRACT, UI_SCHEMA, UiCollector, receive_native_turn


class RepresentativeFaultTests(unittest.TestCase):
    def test_uninjected_eof_does_not_authorize_another_runner(self):
        runner = object.__new__(faults.ControlledRunner)
        runner.args = SimpleNamespace(case="recover_process")
        runner.restarts, runner.report, runner.watcher = 0, {}, None
        runner.child = SimpleNamespace(receive=Mock(side_effect=LaneAbort(str({"_eof": True}))),
            reader_failure=None, process=SimpleNamespace(returncode=-9))
        runner.spawn = Mock()
        with self.assertRaises(LaneAbort):
            runner.receive(time.monotonic() + 2)
        runner.spawn.assert_not_called()

    def test_cancel_reconciliation_rejects_a_lost_cancel_checkpoint(self):
        runner = object.__new__(faults.ControlledRunner)
        runner.args = SimpleNamespace(output=Path("/not-used"))
        runner.command = {"op": "run", "session": "original", "input": "original"}
        evidence = {key: {} for key in ("remote", "job", "binding", "child", "child_sha256",
            "manifest_sha256", "admission_sha256", "admission", "context_policy", "model_admissions")}
        evidence["state"] = {"pending_tool": {"submission_attempted": True, "cancel_requested": False}}
        runner.report = {"before": evidence}
        runner.child = SimpleNamespace(send=Mock())
        with patch.object(faults, "operation_evidence", return_value=evidence):
            with self.assertRaisesRegex(ValueError, "observation-only"):
                runner.reconcile_cancel(time.monotonic() + 2, UiCollector())
        runner.child.send.assert_not_called()

    def test_current_build_gates_run_before_output_creation_or_any_owner(self):
        for failing_gate in ("verify_codex_build", "verify_native_build"):
            with self.subTest(gate=failing_gate), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                args = SimpleNamespace(output=root / "fresh", lane="native", cost_scope="execution-observation",
                    codex_build_evidence=root / "official.json", native_build_evidence=root / "native.json",
                    codex=root / "codex", facade=root / "facade", native=root / "native", timeout=60)
                with patch.object(faults, "verify_codex_build", return_value={}) as official, \
                        patch.object(faults, "verify_native_build", return_value={}) as native, \
                        patch.object(faults, "ControlledRunner") as owner, \
                        patch.object(faults, "ScriptGateway") as gateway:
                    (official if failing_gate == "verify_codex_build" else native).side_effect = ValueError("bad provenance")
                    with self.assertRaisesRegex(ValueError, "bad provenance"):
                        faults.run(args)
                    self.assertFalse(args.output.exists())
                    owner.assert_not_called()
                    gateway.assert_not_called()

    def test_product_total_is_held_before_even_binary_checks(self):
        args = SimpleNamespace(lane="native", cost_scope="product-total")
        with patch.object(faults, "verify_codex_build") as official:
            with self.assertRaisesRegex(ValueError, "common product owner"):
                faults.run(args)
            official.assert_not_called()

    def test_codex_fault_entry_supplies_current_shared_owner_and_actual_collector(self):
        for lane in ("app-server", "facade"):
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                args = SimpleNamespace(output=root / "fresh", lane=lane, case="recover_process",
                    cost_scope="execution-observation", codex_build_evidence=root / "official.json",
                    native_build_evidence=root / "native.json", codex=root / "codex",
                    facade=root / "facade", native=root / "native", timeout=60)
                gateway = Mock(url="http://unused.invalid/v1", records=[{"error": "preserved failed capture"}])
                backend = Mock(ready={"tools": []})
                with patch.object(faults, "verify_codex_build", return_value={}), \
                        patch.object(faults, "verify_native_build", return_value={}), \
                        patch.object(faults, "digest", return_value="0" * 64), \
                        patch.object(faults, "ScriptGateway", return_value=gateway), \
                        patch.object(faults, "ControlledRunner", return_value=backend), \
                        patch.object(faults, "JsonProcess"), \
                        patch.object(faults, "CodexDriver", side_effect=RuntimeError("stop before admission")) as driver:
                    self.assertEqual(faults.run(args), 1)
                self.assertEqual(driver.call_args.kwargs["turn_owner_scope"], OWNER_SCOPE)
                self.assertIsInstance(driver.call_args.kwargs["ui_collector"], UiCollector)
                report = json.loads((args.output / "REPORT.json").read_bytes())
                self.assertFalse(report["passed"])
                self.assertEqual(report["model_requests"], gateway.records)
                self.assertEqual(report["ui_observation"]["actual_text_deltas"], 0)
                self.assertIsNone(report["product_total_cost"])
                self.assertFalse(report["execution_layer_causal_attribution"])
                backend.send.assert_not_called()

    def test_ready_contract_cannot_silently_keep_old_owner_or_final_only_ui(self):
        ready = {"ready": True, "qualification_owner_scope": OWNER_SCOPE, "ui": UI_CONTRACT,
            "context_policy": {"version": faults.POLICY_VERSION}}
        for field in ("qualification_owner_scope", "ui", "context_policy"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "runner.json").write_text("{}")
                wrong = dict(ready)
                wrong.pop(field)
                child = SimpleNamespace(receive=Mock(return_value=wrong), close=Mock())
                with patch.object(faults.ControlledRunner, "spawn", return_value=child):
                    with self.assertRaisesRegex(ValueError, "current owner, policy or streamed UI"):
                        faults.ControlledRunner(SimpleNamespace(output=root), root, {})

    def test_native_delta_is_not_a_terminal_result_or_an_injected_fault(self):
        runner = object.__new__(faults.ControlledRunner)
        runner.restarts, runner.report, runner.watcher = 0, {}, Mock()
        delta = {"event": "ui/text_delta", "schema": UI_SCHEMA, "session": "original",
            "item_id": "message", "content_index": 0, "delta": "原始"}
        runner.child = SimpleNamespace(receive=Mock(return_value=delta))
        self.assertEqual(runner.receive(time.monotonic() + 2), delta)
        runner.watcher.join.assert_not_called()
        self.assertEqual(runner.report, {})

    def test_one_verified_restart_preserves_command_and_consumes_real_same_item_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runner.json").write_text("{\"frozen\":true}")
            runner = object.__new__(faults.ControlledRunner)
            runner.args = SimpleNamespace(case="recover_process", output=root)
            runner.restarts, runner.watcher = 0, None
            runner.command = {"op": "run", "session": "original", "input": "original"}
            runner.raw_command = faults.canonical(runner.command)
            runner.config_digest = faults.digest(root / "runner.json")
            evidence = {key: {} for key in ("remote", "job", "binding", "child", "child_sha256",
                "manifest_sha256", "admission_sha256", "admission", "context_policy", "model_admissions")}
            runner.report = {"injected": True, "before": evidence}
            original = SimpleNamespace(receive=Mock(side_effect=LaneAbort(str({"_eof": True}))),
                reader_failure=None, process=SimpleNamespace(returncode=-9), close=Mock())
            runner.child = original
            runner.ready = {"ready": True, "qualification_owner_scope": OWNER_SCOPE, "ui": UI_CONTRACT}
            delta = {"event": "ui/text_delta", "schema": UI_SCHEMA, "session": "original",
                "item_id": "unchanged-message", "content_index": 0, "delta": "恢复完成"}
            completed = {"event": "ui/item_completed", "schema": UI_SCHEMA, "session": "original",
                "item_id": "unchanged-message", "text": "恢复完成"}
            terminal = {"session": "original", "status": "completed", "answer": "恢复完成"}
            replacement = SimpleNamespace(receive=Mock(side_effect=[runner.ready, delta, completed, terminal,
                LaneAbort(str({"_eof": True}))]), send=Mock())
            runner.spawn = Mock(return_value=replacement)
            ui = UiCollector()
            with patch.object(faults, "operation_evidence", return_value=evidence):
                self.assertEqual(receive_native_turn(runner, "original", time.monotonic() + 2, ui), terminal)
            ui.require_completed(terminal["answer"])
            self.assertEqual(ui.snapshot()["actual_text_deltas"], 1)
            self.assertEqual(set(ui.snapshot()["items"]), {"unchanged-message"})
            self.assertEqual(runner.restarts, 1)
            replacement.send.assert_called_once_with(runner.command)
            runner.spawn.assert_called_once_with()
            original.close.assert_called_once_with()
            with self.assertRaises(LaneAbort):
                runner.receive(time.monotonic() + 2)
            runner.spawn.assert_called_once_with()
            replacement.send.assert_called_once_with(runner.command)

    def test_parent_binding_mismatch_is_rejected_before_touching_runtime_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = {"op": "tool", "session": "original", "input": "original", "call_id": "call-original",
                "name": "hepta_fixture", "arguments": {}, "parent_thread_id": "thread-original", "parent_turn_id": "turn-original"}
            config = {"qualification_owner_scope": OWNER_SCOPE}
            session = root / "sessions" / hashlib.sha256(command["session"].encode()).hexdigest()
            session.mkdir(parents=True)
            (root / "runner.json").write_text(json.dumps(config))
            manifest = {"session": command["session"], "input": command["input"], "policy": {
                "config": {"model_item_bytes": None, **config}, "mode": "tool", "context_policy": {"version": faults.POLICY_VERSION},
                "turn_owner": {"scope": OWNER_SCOPE, "ui": UI_CONTRACT,
                    "parent_codex": {"thread_id": "thread-original", "turn_id": "another-turn"}}}}
            (session / "manifest.json").write_text(json.dumps(manifest))
            with patch.object(faults, "bound_job") as job:
                with self.assertRaisesRegex(ValueError, "parent or UI binding"):
                    faults.operation_evidence(root, command, require_pending=False)
                job.assert_not_called()
            manifest["policy"]["turn_owner"]["parent_codex"]["turn_id"] = command["parent_turn_id"]
            (session / "manifest.json").write_text(json.dumps(manifest))
            # With the actual serde null default, the correct complete config
            # passes and inspection reaches the still-missing original journal.
            with self.assertRaisesRegex(ValueError, "one original tool"):
                faults.operation_evidence(root, command, require_pending=False)

    def test_cancel_consumes_actual_ui_and_rejects_foreign_turn_notifications(self):
        scope = {"thread_id": "thread-original", "turn_id": "turn-original"}
        delta = {"method": "item/agentMessage/delta", "params": {"threadId": scope["thread_id"],
            "turnId": scope["turn_id"], "itemId": "message", "delta": "处理中"}}
        completed = {"method": "item/completed", "params": {"threadId": scope["thread_id"],
            "turnId": scope["turn_id"], "item": {"type": "agentMessage", "id": "message", "text": "处理中"}}}
        interrupted = {"method": "turn/completed", "params": {"threadId": scope["thread_id"],
            "turn": {"id": scope["turn_id"], "status": "interrupted"}}}
        ui = UiCollector()
        client = SimpleNamespace(receive=Mock(side_effect=[delta, completed, interrupted]))
        self.assertEqual(faults.confirm_codex_interrupt(client, scope, time.monotonic() + 2, ui), interrupted)
        self.assertEqual(ui.snapshot()["actual_text_deltas"], 1)
        self.assertTrue(ui.snapshot()["items"]["message"]["completed"])
        wrong = {**delta, "params": {**delta["params"], "turnId": "foreign"}}
        with self.assertRaisesRegex(ValueError, "original Codex turn"):
            faults.confirm_codex_interrupt(SimpleNamespace(receive=Mock(return_value=wrong)),
                scope, time.monotonic() + 2, UiCollector())

    def test_frozen_processes_emit_started_and_preserve_actual_process_lifecycle(self):
        corpus = json.loads((faults.HERE / "corpus.json").read_bytes())
        for case in corpus["cases"]:
            if case["id"] not in ("cancel", "recover_process"):
                continue
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                workspace, _, _ = faults.prepare(case, root)
                process = subprocess.Popen([sys.executable, "-I", "-B", "-S", str(faults.HERE / "workspace_tool.py"),
                    "hepta_fixture", "{}", str(root / "workspace.json")], cwd=workspace,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    self.assertEqual(process.stdout.readline(), b"STARTED\n")
                    self.assertIsNone(process.poll())
                    if case["id"] == "cancel":
                        # This unit test controls only its own Popen object;
                        # remote runtime cancellation is a separate experiment.
                        process.terminate()
                        self.assertNotEqual(process.wait(timeout=3), 0)
                    else:
                        self.assertEqual(process.wait(timeout=5), 0)
                        self.assertEqual((workspace / "done").read_bytes(), b"once\n")
                    self.assertEqual(process.stderr.read(), b"")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=3)
                    process.stdout.close()
                    process.stderr.close()


if __name__ == "__main__":
    unittest.main()
