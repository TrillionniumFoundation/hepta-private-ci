"""Failure-injection checks for benchmark evidence, not agent task-success tests."""
import copy
import json
import queue
import time
import unittest
from collections import deque
from pathlib import Path
from unittest import mock

from model_gateway import ModelGateway
from protocol_driver import CodexDriver, JsonProcess, LaneAbort


class ReplayBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.case = {"name": "case-1", "calls": 2, "task": "sum", "answer": '{"sum":576}'}
        self.result = {"exit_code": 0, "stdout": self.case["answer"] + "\n", "stderr": ""}
        self.feedback = {"type": "function_call_output", "call_id": "call_case-1", "output": json.dumps(self.result)}

    def body(self, feedback=None):
        return {"input": [{"type": "message", "role": "user", "content": []}, feedback or self.feedback]}

    def test_native_and_codex_exact_real_tool_feedback_are_accepted(self):
        ModelGateway.validate_replay_feedback(self.case, self.body())
        feedback = dict(self.feedback, output=[{"type": "input_text", "text": json.dumps(self.result)}])
        ModelGateway.validate_replay_feedback(self.case, self.body(feedback))

    def test_bad_tool_results_cannot_receive_correct_replay_answer(self):
        mutations = [
            {"exit_code": False}, {"exit_code": 0.0}, {"exit_code": 1},
            {"stdout": '{"sum":575}\n'}, {"stdout": self.case["answer"]},
            {"stderr": "failed"}, {"extra": "unverified"},
        ]
        gateway = object.__new__(ModelGateway)
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                bad = dict(self.result, **mutation)
                feedback = dict(self.feedback, output=json.dumps(bad))
                with self.assertRaises(ValueError):
                    gateway.replay(self.case, self.body(feedback))

    def test_wrong_missing_and_duplicate_call_feedback_are_rejected(self):
        bodies = [
            self.body(dict(self.feedback, call_id="another-operation")),
            {"input": []}, {"input": [self.feedback, self.feedback]},
            self.body(dict(self.feedback, output=None)),
            self.body(dict(self.feedback, output=[{"type": "input_text", "text": json.dumps(self.result)}] * 2)),
            self.body(dict(self.feedback, output=[{"type": "input_image", "text": json.dumps(self.result)}])),
        ]
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(ValueError):
                ModelGateway.validate_replay_feedback(self.case, body)

    def test_stream_item_added_does_not_duplicate_arguments_or_text(self):
        gateway = object.__new__(ModelGateway)
        for call in (1, 2):
            with self.subTest(call=call):
                raw, completed = gateway.replay(dict(self.case, calls=call), self.body())
                events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith(b"data: ")]
                added = next(event["item"] for event in events if event["type"] == "response.output_item.added")
                if call == 1:
                    self.assertEqual(added["arguments"], "")
                    deltas = "".join(event["delta"] for event in events if event["type"] == "response.function_call_arguments.delta")
                    self.assertEqual(deltas, completed["output"][0]["arguments"])
                else:
                    self.assertEqual(added["content"], [])
                    deltas = "".join(event["delta"] for event in events if event["type"] == "response.output_text.delta")
                    self.assertEqual(deltas, self.case["answer"])


TOOL = {"name": "hepta_probe", "description": "fixture", "parameters": {"type": "object"}}


def notification(method, thread="thread-1", turn="turn-1", **params):
    return {"method": method, "params": {"threadId": thread, "turnId": turn, **params}}


def tool_request(thread="thread-1", turn="turn-1", call_id="call-1"):
    return {"id": "server-request-" + call_id, **notification("item/tool/call", thread, turn,
            callId=call_id, tool="hepta_probe", arguments={"task": "sum"})}


def successful_events(thread="thread-1", turn="turn-1", usage=None):
    return [
        notification("thread/tokenUsage/updated", thread, turn, tokenUsage=usage or {"total": {"totalTokens": 30}}),
        notification("item/completed", thread, turn, item={"type": "agentMessage", "text": '{"sum":576}'}),
        {"method": "turn/completed", "params": {"threadId": thread, "turn": {"id": turn, "status": "completed", "error": None}}},
    ]


class FakeBackend:
    def __init__(self, override=None):
        self.sent = []
        self.override = override or {}

    def send(self, value):
        self.sent.append(value)

    def receive(self, deadline):
        return {"session": self.sent[-1]["session"], "status": "completed",
                "output": json.dumps({"exit_code": 0, "stdout": '{"sum":576}\n', "stderr": ""}), **self.override}


class FakeCodex:
    def __init__(self, cases, early_tool=False):
        self.cases = deque(cases)
        self.messages = deque()
        self.sent = []
        self.turn_number = 0
        self.early_tool = early_tool

    def send(self, value):
        self.sent.append(value)
        method = value.get("method")
        if method == "initialize":
            self.messages.append({"id": value["id"], "result": {"userAgent": "fixture"}})
        elif method == "thread/start":
            self.turn_number += 1
            self.messages.append({"id": value["id"], "result": {"thread": {"id": f"thread-{self.turn_number}"}}})
        elif method == "turn/start":
            events = self.cases.popleft()
            if self.early_tool:
                self.messages.append(events.pop(0))
            self.messages.append({"id": value["id"], "result": {"turn": {"id": f"turn-{self.turn_number}"}}})
            self.messages.extend(events)

    def receive(self, deadline):
        if time.monotonic() >= deadline:
            raise TimeoutError("expired")
        if not self.messages:
            raise TimeoutError("no fixture response")
        return self.messages.popleft()


class DriverBoundaryTests(unittest.TestCase):
    def driver(self, events, backend=None, early_tool=False):
        self.process = FakeCodex([copy.deepcopy(events)], early_tool=early_tool)
        self.backend = backend or FakeBackend()
        return CodexDriver(self.process, self.backend, Path("/fixture"), TOOL)

    def test_completed_turn_preserves_call_and_reply_session(self):
        driver = self.driver([tool_request()] + successful_events())
        result = driver.run("measured-case", "sum the fixture")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["tool_calls"], 1)
        self.assertEqual(self.backend.sent[0]["session"], "measured-case:call-1")
        self.assertEqual(self.backend.sent[0]["call_id"], "call-1")
        self.assertIn({"id": "server-request-call-1", "result": {"contentItems": [{"type": "inputText", "text": json.dumps({"exit_code": 0, "stdout": '{"sum":576}\n', "stderr": ""})}], "success": True}}, self.process.sent)

    def test_early_tool_request_waits_for_original_turn_identity(self):
        driver = self.driver([tool_request()] + successful_events(), early_tool=True)
        self.assertEqual(driver.run("case", "sum")["status"], "completed")
        self.assertEqual(len(self.backend.sent), 1)

    def test_wrong_tool_scope_never_reaches_backend(self):
        for thread, turn in [("other-thread", "turn-1"), ("thread-1", "other-turn")]:
            with self.subTest(thread=thread, turn=turn):
                driver = self.driver([tool_request(thread, turn)])
                with self.assertRaises(LaneAbort):
                    driver.run("case", "sum")
                self.assertEqual(self.backend.sent, [])

    def test_answer_usage_and_completion_must_belong_to_current_turn(self):
        wrong_events = [
            notification("item/completed", "other", "turn-1", item={"type": "agentMessage", "text": "fake success"}),
            notification("thread/tokenUsage/updated", "thread-1", "other", tokenUsage={"total": {"totalTokens": 0}}),
            {"method": "turn/completed", "params": {"threadId": "other", "turn": {"id": "turn-1", "status": "completed"}}},
        ]
        for event in wrong_events:
            with self.subTest(method=event["method"]):
                driver = self.driver([event] + successful_events())
                with self.assertRaises(LaneAbort):
                    driver.run("case", "sum")

    def test_pending_tool_aborts_lane_instead_of_reusing_unread_events(self):
        driver = self.driver([tool_request()] + successful_events(), FakeBackend({"status": "pending_tool"}))
        with self.assertRaises(LaneAbort) as context:
            driver.run("case", "sum")
        self.assertEqual(context.exception.result["status"], "pending_tool")
        self.assertTrue(context.exception.result["requires_process_reset"])
        self.assertTrue(any(message.get("method") == "turn/interrupt" for message in self.process.sent))
        self.assertFalse(any("result" in message for message in self.process.sent))
        sent_count = len(self.process.sent)
        with self.assertRaises(LaneAbort):
            driver.run("next-case", "sum")
        self.assertEqual(len(self.process.sent), sent_count)

    def test_mismatched_backend_session_does_not_answer_original_tool(self):
        driver = self.driver([tool_request()] + successful_events(), FakeBackend({"session": "wrong:call-1"}))
        with self.assertRaises(LaneAbort):
            driver.run("case", "sum")
        self.assertFalse(any("result" in message for message in self.process.sent))

    def test_duplicate_call_cannot_execute_twice(self):
        driver = self.driver([tool_request(), tool_request()] + successful_events())
        with self.assertRaises(LaneAbort):
            driver.run("case", "sum")
        self.assertEqual(len(self.backend.sent), 1)

    def test_late_successful_turn_usage_cannot_pollute_next_measurement(self):
        late = notification("thread/tokenUsage/updated", tokenUsage={"total": {"totalTokens": 999}})
        process = FakeCodex([successful_events(), [late] + successful_events("thread-2", "turn-2")])
        driver = CodexDriver(process, FakeBackend(), Path("/fixture"), TOOL)
        driver.run("first", "sum")
        second = driver.run("second", "sum")
        self.assertEqual(second["usage"]["total"]["totalTokens"], 30)
        self.assertEqual(second["ignored_late_notifications"], 1)

    def test_expired_deadline_cannot_consume_already_queued_response(self):
        process = object.__new__(JsonProcess)
        process.messages = queue.Queue()
        process.messages.put({"status": "completed"})
        process.reader_failure = None
        with self.assertRaises(TimeoutError):
            process.receive(time.monotonic() - 1)
        self.assertEqual(process.messages.qsize(), 1)

    def test_deadline_is_rechecked_after_queue_wakeup(self):
        process = object.__new__(JsonProcess)
        process.messages = queue.Queue()
        process.messages.put({"status": "completed"})
        process.reader_failure = None
        with mock.patch("protocol_driver.time.monotonic", side_effect=[0.0, 2.0]):
            with self.assertRaises(TimeoutError):
                process.receive(1.0)


if __name__ == "__main__":
    unittest.main()
