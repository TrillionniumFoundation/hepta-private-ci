import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from teacher_native_observation import MAX_BYTES, MAX_EVENTS, observe_native

NONCE = "hepta-nonce-20260929-fixture"


def stream():
    return [{"type": "thread.started", "thread_id": "thread-fixture"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": NONCE}},
            {"type": "turn.completed", "usage": {"input_tokens": 12, "cached_input_tokens": 0, "output_tokens": 8}}]


def encoded(events):
    return b"".join(json.dumps(event).encode() + b"\n" for event in events)


class NativeTeacherTests(unittest.TestCase):
    def observe(self, events=None, **kwargs):
        args = dict(events=events if isinstance(events, bytes) else encoded(stream() if events is None else events),
                    final=(NONCE + "\n").encode(), diagnostics=b"", requested_model="gpt-6-luna",
                    nonce=NONCE, exit_code=0)
        args.update(kwargs)
        return observe_native(**args)

    def rejected(self, events=None, **kwargs):
        result = self.observe(events, **kwargs)
        self.assertFalse(result["connectivity_verified"])
        self.assertFalse(result["retry_authorized"])
        self.assertFalse(result["remote_nonexecution_proven"])
        return result

    def test_closed_nonce_turn_is_connectivity_without_identity_or_rights(self):
        result = self.observe()
        self.assertTrue(result["connectivity_verified"])
        self.assertTrue(result["turn_completed"])
        self.assertEqual(result["status"], "native_connected_identity_unobserved")
        self.assertEqual(result["thread_id"], "thread-fixture")
        self.assertEqual((result["transport_observed_model"], result["transport_observed_provider"]), (None, None))
        self.assertFalse(any(result[key] for key in ("provider_qualified", "tool_isolation_verified",
            "training_rights_verified", "training_data_admitted", "production_activation")))

    def test_requested_model_and_model_self_description_are_not_identity(self):
        self.assertIsNone(self.observe(requested_model="different-model")["transport_observed_model"])
        events = stream()
        events[2]["item"]["text"] = NONCE + " I am gpt-6-luna"
        self.rejected(events)

    def test_stream_and_final_file_both_bind_exact_nonce(self):
        for final in (b"different", b" " + NONCE.encode(), NONCE.encode() + b"\n\n"):
            with self.subTest(final=final):
                self.rejected(final=final)
        events = stream()
        events[2]["item"]["text"] = "different"
        self.rejected(events)

    def test_every_truncated_prefix_is_unresolved(self):
        for end in range(4):
            with self.subTest(end=end):
                result = self.rejected(stream()[:end])
                self.assertEqual(result["thread_id"], "thread-fixture" if end else None)

    def test_nonzero_exit_preserves_terminal_truth_but_never_authorizes_retry(self):
        for code in (None, -9, 1, 124, 130):
            with self.subTest(code=code):
                result = self.rejected(exit_code=code)
                self.assertTrue(result["turn_completed"])
                self.assertTrue(result["nonce_matched"])
                self.assertEqual(result["status"], "native_local_exit_not_success")

    def test_duplicate_out_of_order_and_post_terminal_events_reject(self):
        original = stream()
        variants = [original + [original[-1]], original + [original[0]],
                    [original[1], original[0], *original[2:]],
                    [original[0], original[0], *original[1:]],
                    [original[0], original[2], original[1], original[3]],
                    [*original[:3], original[2], original[3]]]
        for events in variants:
            with self.subTest(events=events):
                self.rejected(events)

    def test_additional_messages_reject_even_when_both_match(self):
        events = stream()
        second = copy.deepcopy(events[2])
        second["item"]["id"] = "item_1"
        events.insert(3, second)
        self.rejected(events)

    def test_reasoning_lifecycle_does_not_publish_reasoning(self):
        events = stream()
        reasoning = {"id": "reasoning_0", "type": "reasoning", "text": "private fixture text"}
        events[2:2] = [{"type": "item.started", "item": reasoning},
                       {"type": "item.updated", "item": reasoning},
                       {"type": "item.completed", "item": reasoning}]
        result = self.observe(events)
        self.assertTrue(result["connectivity_verified"])
        self.assertNotIn("private fixture text", json.dumps(result))
        self.rejected(events[:4] + events[5:])

    def test_unstarted_updates_and_changed_item_types_reject(self):
        events = stream()
        events.insert(2, {"type": "item.updated", "item": copy.deepcopy(events[2]["item"])})
        self.rejected(events)
        events[2]["type"] = "item.started"
        events[2]["item"]["type"] = "reasoning"
        self.rejected(events)

    def test_tools_and_unknown_event_types_never_pass_nonce_only_profile(self):
        for kind in ("command_execution", "file_change", "mcp_tool_call", "web_search", "future_tool"):
            events = stream()
            events.insert(2, {"type": "item.completed", "item": {"id": "tool_0", "type": kind}})
            result = self.rejected(events)
            self.assertEqual(result["status"], "native_non_nonce_activity_observed")
        events = stream()
        events.insert(2, {"type": "future.event"})
        self.rejected(events)

    def test_explicit_errors_and_unexpected_success_fields_reject(self):
        for kind in ("turn.failed", "error"):
            events = stream()
            events.insert(2, {"type": kind, "error": {"message": "fixture error"}})
            self.rejected(events)
        for index in range(4):
            events = stream()
            events[index]["error"] = {"message": "contradiction"}
            self.rejected(events)
        events = stream()
        events[2]["item"]["isError"] = True
        self.rejected(events)

    def test_pre_turn_error_retains_later_terminal_and_nonce_observations(self):
        events = stream()
        events.insert(1, {"type": "item.completed", "item": {
            "id": "error_0", "type": "error", "message": "fixture startup dependency unavailable"}})
        result = self.rejected(events)
        self.assertEqual(result["status"], "native_error_reconcile_before_retry")
        self.assertTrue(result["terminal_event_observed"])
        self.assertTrue(result["nonce_reply_observed"])
        self.assertTrue(result["final_nonce_matched"])
        self.assertFalse(result["turn_completed"])
        self.assertEqual(result["thread_id"], "thread-fixture")

    def test_typed_bounded_usage_and_local_exit(self):
        for value in (None, True, -1, 1.5, "12", 10**10):
            events = stream()
            events[-1]["usage"]["input_tokens"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.observe(events)
        events = stream()
        events[-1]["usage"]["cached_input_tokens"] = 13
        with self.assertRaises(ValueError):
            self.observe(events)
        for value in (True, 1.5, "0", 256):
            with self.subTest(exit_code=value), self.assertRaises(ValueError):
                self.observe(exit_code=value)

    def test_duplicate_json_invalid_shape_and_capacity_reject(self):
        for raw in (b'{"type":"thread.started","type":"turn.started"}', b'null', b'[]', b'NaN',
                    b'{}\n' * (MAX_EVENTS + 1), b'x' * (MAX_BYTES + 1)):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                self.observe(events=raw)
        for field in ("final", "diagnostics"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.observe(**{field: b'x' * (MAX_BYTES + 1)})

    def test_cli_retains_private_immutable_receipt_and_nonzero_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in (("events", encoded(stream())), ("final", NONCE.encode()), ("diagnostics", b"")):
                (root / name).write_bytes(data)
            command = [sys.executable, str(Path(__file__).with_name("teacher_native_observation.py")),
                "--requested-model", "gpt-6-luna", "--nonce", NONCE, "--exit-code", "0"]
            for name in ("events", "final", "diagnostics", "output"):
                command.extend(["--" + name, str(root / name)])
            child = subprocess.run(command, capture_output=True, timeout=10)
            self.assertEqual(child.returncode, 0, child.stderr.decode())
            original = (root / "output").read_bytes()
            if os.name == "posix":
                self.assertEqual((root / "output").stat().st_mode & 0o777, 0o600)
            self.assertNotEqual(subprocess.run(command, capture_output=True, timeout=10).returncode, 0)
            self.assertEqual((root / "output").read_bytes(), original)
            (root / "output").unlink()
            (root / "events").write_bytes(encoded(stream()[:-1]))
            self.assertEqual(subprocess.run(command, capture_output=True, timeout=10).returncode, 2)
            self.assertFalse(json.loads((root / "output").read_bytes())["connectivity_verified"])


if __name__ == "__main__":
    unittest.main()
