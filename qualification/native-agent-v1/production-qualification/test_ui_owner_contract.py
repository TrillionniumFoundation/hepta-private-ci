"""Exercise actual driver consumption; no completed text is substituted for a delta."""

from collections import deque
from pathlib import Path
import copy
import json
import time
import unittest

from protocol_driver import CodexDriver, LaneAbort
from ui_collector import OWNER_SCOPE, UI_SCHEMA, UiCollector, receive_native_turn

TOOL = {"name": "hepta_probe", "description": "fixture", "parameters": {"type": "object"}}


def notification(method, **params):
    return {"method": method, "params": {"threadId": "original-thread", "turnId": "original-turn", **params}}


def tool(call_id):
    return {"id": "rpc-" + call_id, **notification("item/tool/call", callId=call_id,
        tool="hepta_probe", arguments={"task": "sum"})}


class Codex:
    def __init__(self, events):
        self.events = copy.deepcopy(events)
        self.messages, self.sent = deque(), []
    def send(self, value):
        self.sent.append(value)
        method = value.get("method")
        if method == "initialize":
            self.messages.append({"id": value["id"], "result": {"userAgent": "fixture"}})
        elif method == "thread/start":
            self.messages.append({"id": value["id"], "result": {"thread": {"id": "original-thread"}}})
        elif method == "turn/start":
            self.messages.append({"id": value["id"], "result": {"turn": {"id": "original-turn"}}})
            self.messages.extend(self.events)
    def receive(self, deadline):
        if time.monotonic() >= deadline or not self.messages:
            raise TimeoutError("fixture has no original response")
        return self.messages.popleft()


class Backend:
    def __init__(self, pending=False):
        self.sent, self.pending = [], pending
    def send(self, value):
        self.sent.append(value)
    def receive(self, deadline):
        return {"session": self.sent[-1]["session"], "status": "pending_tool" if self.pending else "completed",
                "output": json.dumps({"exit_code": 0, "stdout": "original", "stderr": ""}),
                "operation_id": "original-operation"}


class UiOwnerContractTests(unittest.TestCase):
    def test_two_codex_calls_use_one_original_turn_owner_and_real_ui_deltas(self):
        text = "保持同一任务的中文增量。" * 700
        half = len(text) // 2
        events = [tool("original-call-a"), tool("original-call-b"),
                  notification("item/agentMessage/delta", itemId="same-item", delta=text[:half]),
                  notification("item/agentMessage/delta", itemId="same-item", delta=text[half:]),
                  notification("item/completed", item={"type": "agentMessage", "id": "same-item", "text": text}),
                  {"method": "turn/completed", "params": {"threadId": "original-thread", "turn": {"id": "original-turn", "status": "completed"}}}]
        process, backend, ui = Codex(events), Backend(), UiCollector()
        driver = CodexDriver(process, backend, Path("/unused"), TOOL,
            turn_owner_scope=OWNER_SCOPE, ui_collector=ui)
        result = driver.run("same-session", "original input")
        self.assertEqual(result["status"], "completed")
        ui.require_completed(text)
        self.assertEqual(ui.snapshot()["actual_text_deltas"], 2)
        self.assertEqual([row["session"] for row in backend.sent], ["same-session", "same-session"])
        self.assertEqual([row["call_id"] for row in backend.sent], ["original-call-a", "original-call-b"])
        self.assertTrue(all(row["parent_thread_id"] == "original-thread" and row["parent_turn_id"] == "original-turn"
                            for row in backend.sent))

    def test_pending_original_aborts_before_another_shared_owner_call(self):
        process, backend = Codex([tool("unknown-original"), tool("must-not-run")]), Backend(pending=True)
        driver = CodexDriver(process, backend, Path("/unused"), TOOL, turn_owner_scope=OWNER_SCOPE, ui_collector=UiCollector())
        with self.assertRaises(LaneAbort) as raised:
            driver.run("same-session", "original input")
        self.assertEqual(len(backend.sent), 1)
        self.assertEqual(raised.exception.result["backend"]["operation_id"], "original-operation")
        with self.assertRaises(LaneAbort):
            driver.run("replacement", "another input")
        self.assertEqual(len(backend.sent), 1)

    def test_native_consumes_real_deltas_and_requires_same_item_final(self):
        messages = deque([
            {"event": "ui/text_delta", "schema": UI_SCHEMA, "session": "original", "item_id": "item-a", "content_index": 0, "delta": "原始"},
            {"event": "ui/text_delta", "schema": UI_SCHEMA, "session": "original", "item_id": "item-a", "content_index": 0, "delta": "输出"},
            {"event": "ui/item_completed", "schema": UI_SCHEMA, "session": "original", "item_id": "item-a", "text": "原始输出"},
            {"session": "original", "status": "completed", "answer": "原始输出"},
        ])
        class Wire:
            def receive(self, deadline): return messages.popleft()
        ui = UiCollector()
        result = receive_native_turn(Wire(), "original", time.monotonic() + 1, ui)
        ui.require_completed(result["answer"])
        self.assertEqual(ui.deltas, 2)
        self.assertEqual(len(ui.items), 1)
        wrong = UiCollector()
        wrong.delta("item-a", "原始输出")
        wrong.completed("item-b", "原始输出")
        with self.assertRaisesRegex(ValueError, "actual streamed-and-completed"):
            wrong.require_completed("原始输出")
        final_only = UiCollector()
        final_only.completed("item-a", "原始输出")
        with self.assertRaisesRegex(ValueError, "actual streamed-and-completed"):
            final_only.require_completed("原始输出")

    def test_wrong_turn_or_changed_final_text_cannot_pass_ui_capability(self):
        for event in [
            {"method": "item/agentMessage/delta", "params": {"threadId": "other", "turnId": "original-turn", "itemId": "same", "delta": "text"}},
            notification("item/completed", item={"type": "agentMessage", "id": "same", "text": "changed"}),
        ]:
            ui = UiCollector()
            process = Codex([notification("item/agentMessage/delta", itemId="same", delta="original"), event])
            driver = CodexDriver(process, Backend(), Path("/unused"), TOOL, turn_owner_scope=OWNER_SCOPE, ui_collector=ui)
            with self.assertRaises(LaneAbort):
                driver.run("same-session", "original input")
        with self.assertRaisesRegex(ValueError, "UTF-8 byte bound"):
            UiCollector().delta("item", "中" * 11000)


if __name__ == "__main__":
    unittest.main()
