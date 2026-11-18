"""Control tests for local journal/observation rules, not real-runtime proof."""

import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest

from runtime_process_bridge import RuntimeProcessBridge, process_digest, strict_json


PROFILE = {
    "schema": "hepta.cell.runtime-process-bridge.v1",
    "namespace": "bounded-control-test",
    "candidate_sha256": "a" * 64,
    "process": {
        "host": "loopback",
        "executable": "/usr/bin/python3",
        "args": [
            "scripts/hepta_cell_joint_worker.py",
            "--candidate",
            "/fixture/candidate.json",
            "--database",
            "/fixture/cells.sqlite3",
        ],
        "cwd": "/fixture",
        "timeout_seconds": 30,
    },
}
REQUEST = {
    "request_id": "ABC-1",
    "cell_id": "MEM",
    "operation": "infer",
    "payload": {"x": [1, 2]},
}
IDENTITY = {"transport": "unit_test_double", "runtime_binary_sha256": "b" * 64}


class OwnerDouble:
    """Only the local safety contract is tested; no runtime qualification claim."""

    def __init__(self):
        self.calls = []
        self.stdout = b"\xff\x00" + b"a" * 20000
        self.stderr = b"diagnostic\n"
        self.drop_ack = False
        self.running = False
        self.bad_cursor = False
        self.changed_publication = False
        self.status_calls = 0
        self.cancelled = False
        self.bad_binding = False
        self.launch_nonce = "1" * 32

    def status(self):
        self.status_calls += 1
        if self.running:
            return {"job_id": "job-original", "state": "running"}
        code = -15 if self.cancelled else 0
        return {
            "job_id": "job-original",
            "state": "cancelled" if self.cancelled else "succeeded",
            "exit_code": code,
            "timed_out": False,
            "cancelled": self.cancelled,
            "terminal_publication_protocol": 1,
            "terminal_publication_confirmed": True,
            "output_complete": True,
            "output_durable": True,
            "launch_nonce": self.launch_nonce,
            "at_unix_ms": 7 + int(self.changed_publication and self.status_calls > 1),
            "log_bytes": {
                k: {"seen": len(getattr(self, k)), "stored": len(getattr(self, k))}
                for k in ("stdout", "stderr")
            },
            "log_truncated": {"stdout": False, "stderr": False},
            "log_errors": {"stdout": None, "stderr": None},
            "log_synced": {"stdout": True, "stderr": True},
        }

    def __call__(self, tool, arguments):
        self.calls.append((tool, copy.deepcopy(arguments)))
        if tool == "process_start":
            if self.drop_ack:
                raise TimeoutError("acknowledgement lost after possible effect")
            return {
                "job": {
                    "id": "job-original",
                    "host": arguments["host"],
                    "idempotency_key": arguments["idempotency_key"],
                    "request_digest": "c" * 64
                    if self.bad_binding
                    else process_digest(arguments),
                    "executable": arguments["executable"],
                    "args": arguments["args"],
                    "cwd": arguments["cwd"],
                }
            }
        if tool == "process_status":
            return self.status()
        if tool == "process_cancel":
            self.running = False
            self.cancelled = True
            return {"job_id": "job-original", "result": "cancel_requested"}
        if tool == "process_read":
            result = {"job_id": "job-original"}
            for name in ("stdout", "stderr"):
                raw = getattr(self, name)
                offset = arguments[name + "_offset"]
                chunk = raw[offset : offset + arguments["limit"]]
                result[name] = {
                    "offset": offset,
                    "next_offset": offset + len(chunk),
                    "size": len(raw),
                    "eof": offset + len(chunk) == len(raw),
                    "bytes_hex": chunk.hex(),
                }
            if self.bad_cursor:
                result["stdout"]["next_offset"] += 1
            return result
        raise AssertionError(tool)


class BridgeControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "bridge.sqlite3"
        self.owner = OwnerDouble()
        self.bridge = self.open()

    def open(self, profile=None, identity=None):
        return RuntimeProcessBridge(
            profile or PROFILE,
            self.path,
            self.owner,
            transport_identity=identity or IDENTITY,
        )

    def tearDown(self):
        self.bridge.close()
        self.temp.cleanup()

    def starts(self):
        return sum(tool == "process_start" for tool, _ in self.owner.calls)

    def test_lossless_binary_pages_roundtrip_and_no_domain_success(self):
        result = self.bridge.execute(REQUEST)
        self.assertEqual(result["state"], "TERMINAL")
        self.assertEqual(
            bytes.fromhex(result["streams"]["stdout"]["bytes_hex"]), self.owner.stdout
        )
        self.assertEqual(
            bytes.fromhex(result["streams"]["stderr"]["bytes_hex"]), self.owner.stderr
        )
        self.assertFalse(result["domain_success"])
        self.assertFalse(result["actual_runtime_transport"])
        self.assertGreater(
            sum(tool == "process_read" for tool, _ in self.owner.calls), 1
        )

    def test_cold_restart_observes_known_job_without_launch(self):
        self.owner.running = True
        first = self.bridge.execute(REQUEST)
        self.assertEqual(first["state"], "UNKNOWN")
        self.assertEqual(first["job_id"], "job-original")
        self.bridge.close()
        self.bridge = self.open()
        self.owner.running = False
        result = self.bridge.execute(REQUEST)
        self.assertEqual(result["state"], "TERMINAL")
        self.assertEqual(self.starts(), 1)

    def test_lost_ack_is_permanent_no_submit_tombstone(self):
        self.owner.drop_ack = True
        self.assertEqual(self.bridge.execute(REQUEST)["state"], "UNKNOWN")
        self.bridge.close()
        self.bridge = self.open()
        self.owner.drop_ack = False
        result = self.bridge.execute(REQUEST)
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertIsNone(result["job_id"])
        self.assertEqual(self.starts(), 1)

    def test_same_identity_changed_payload_refused_before_effect(self):
        self.bridge.execute(REQUEST)
        changed = {**REQUEST, "payload": {"x": [7]}}
        with self.assertRaises(ValueError):
            self.bridge.execute(changed)
        self.assertEqual(self.starts(), 1)

    def test_same_identity_changed_candidate_refused_after_restart(self):
        self.bridge.execute(REQUEST)
        self.bridge.close()
        self.bridge = self.open({**PROFILE, "candidate_sha256": "d" * 64})
        with self.assertRaises(ValueError):
            self.bridge.execute(REQUEST)
        with self.assertRaises(ValueError):
            self.bridge.observe(REQUEST["request_id"])
        with self.assertRaises(ValueError):
            self.bridge.cancel(REQUEST["request_id"])
        self.assertEqual(self.starts(), 1)

    def test_wrong_owner_binding_never_adopts_job(self):
        self.owner.bad_binding = True
        result = self.bridge.execute(REQUEST)
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertIsNone(result["job_id"])
        self.assertEqual(self.starts(), 1)
        self.bridge.execute(REQUEST)
        self.assertEqual(self.starts(), 1)

    def test_cursor_corruption_never_becomes_complete_output(self):
        self.owner.bad_cursor = True
        result = self.bridge.execute(REQUEST)
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["job_id"], "job-original")
        self.assertNotIn("streams", result)

    def test_changed_publication_never_becomes_complete_output(self):
        self.owner.changed_publication = True
        result = self.bridge.execute(REQUEST)
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertNotIn("streams", result)

    def test_cancel_observes_only_original_identity(self):
        self.owner.running = True
        self.bridge.execute(REQUEST)
        result = self.bridge.cancel(REQUEST["request_id"])
        self.assertEqual(result["runtime_state"], "cancelled")
        self.assertEqual(self.starts(), 1)
        cancels = [args for tool, args in self.owner.calls if tool == "process_cancel"]
        self.assertEqual(cancels, [{"host": "loopback", "job_id": "job-original"}])

    def test_duplicate_json_members_refused(self):
        with self.assertRaises(ValueError):
            strict_json('{"operation":"infer","operation":"train"}')

    def test_cold_nonce_change_keeps_original_terminal(self):
        original = self.bridge.execute(REQUEST)
        self.bridge.close()
        self.bridge = self.open()
        self.owner.launch_nonce = "2" * 32
        changed = self.bridge.observe(REQUEST["request_id"])
        self.assertEqual(changed["state"], "UNKNOWN")
        self.assertEqual(changed["reason"], "original_terminal_observation_changed")
        self.assertNotIn("streams", changed)
        retained = self.bridge.db.execute(
            "SELECT observation FROM terminal_observations WHERE request_id=?",
            (REQUEST["request_id"],),
        ).fetchone()
        self.assertEqual(strict_json(retained[0]), original)
        self.assertEqual(self.starts(), 1)

    def test_cold_same_length_output_change_keeps_original_bytes(self):
        original = self.bridge.execute(REQUEST)
        self.bridge.close()
        self.bridge = self.open()
        self.owner.stdout = b"x" + self.owner.stdout[1:]
        changed = self.bridge.execute(REQUEST)
        self.assertEqual(changed["state"], "UNKNOWN")
        self.assertNotIn("streams", changed)
        retained = self.bridge.db.execute(
            "SELECT observation FROM terminal_observations WHERE request_id=?",
            (REQUEST["request_id"],),
        ).fetchone()
        self.assertEqual(strict_json(retained[0]), original)
        conflict = self.bridge.db.execute(
            "SELECT body FROM events WHERE kind='terminal_conflict' ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(
            bytes.fromhex(strict_json(conflict[0])["streams"]["stdout"]["bytes_hex"]),
            self.owner.stdout,
        )
        self.assertEqual(self.starts(), 1)

    def test_profile_and_transport_inputs_are_frozen_at_construction(self):
        profile, identity = copy.deepcopy(PROFILE), copy.deepcopy(IDENTITY)
        self.bridge.close()
        self.bridge = self.open(profile, identity)
        profile["process"]["args"].append("--changed-after-admission")
        identity["transport"] = "actual_mcp_stdio"
        result = self.bridge.execute(REQUEST)
        starts = [arguments for tool, arguments in self.owner.calls if tool == "process_start"]
        self.assertEqual(starts[0]["args"], PROFILE["process"]["args"])
        self.assertFalse(result["actual_runtime_transport"])

    def test_transport_mutation_does_not_rebind_durable_submission(self):
        original_call = self.owner

        def mutating_call(tool, arguments):
            if tool == "process_start":
                arguments["args"].append("--not-in-durable-intent")
            return original_call(tool, arguments)

        self.bridge.call = mutating_call
        result = self.bridge.execute(REQUEST)
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertIsNone(result["job_id"])
        self.assertEqual(self.starts(), 1)

    def test_legacy_terminal_history_survives_unknown_and_reopen(self):
        original = self.bridge.execute(REQUEST)
        self.owner.running = True
        self.assertEqual(self.bridge.observe(REQUEST["request_id"])["state"], "UNKNOWN")
        # The old schema has only operations/events. Its latest observation may
        # be UNKNOWN even though original terminal bytes remain in its history.
        self.bridge.db.execute("DROP TABLE terminal_observations")
        self.bridge.db.commit()
        self.bridge.close()
        self.bridge = self.open()
        self.owner.running = False
        self.owner.stderr = b"x" + self.owner.stderr[1:]
        result = self.bridge.observe(REQUEST["request_id"])
        self.assertEqual(result["state"], "UNKNOWN")
        retained = self.bridge.db.execute(
            "SELECT observation FROM terminal_observations WHERE request_id=?",
            (REQUEST["request_id"],),
        ).fetchone()
        self.assertEqual(strict_json(retained[0]), original)
        self.assertEqual(self.starts(), 1)

    def test_two_recovery_owners_cannot_replace_each_others_terminal(self):
        self.owner.running = True
        self.assertEqual(self.bridge.execute(REQUEST)["state"], "UNKNOWN")
        ready = threading.Barrier(2)

        def observe(marker):
            owner = OwnerDouble()
            owner.stdout = marker + owner.stdout[1:]
            bridge = RuntimeProcessBridge(
                PROFILE, self.path, owner, transport_identity=IDENTITY
            )
            try:
                ready.wait(timeout=5)
                result = bridge.observe(REQUEST["request_id"])
                self.assertFalse(any(tool == "process_start" for tool, _ in owner.calls))
                return result
            finally:
                bridge.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(observe, (b"x", b"y")))
        self.assertEqual(sorted(result["state"] for result in results), ["TERMINAL", "UNKNOWN"])
        accepted = next(result for result in results if result["state"] == "TERMINAL")
        retained = self.bridge.db.execute(
            "SELECT observation FROM terminal_observations WHERE request_id=?",
            (REQUEST["request_id"],),
        ).fetchone()
        self.assertEqual(strict_json(retained[0]), accepted)
        self.assertEqual(self.starts(), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
