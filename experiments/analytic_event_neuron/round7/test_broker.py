"""Subprocess and actual filesystem checks; no production integration claim."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .broker import ArtifactWorker, BrokerClient, SOURCE_BYTES
from .task import State, TaskParameters


def keys_recursive(value):
    if isinstance(value, dict):
        return set(value).union(*(keys_recursive(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(keys_recursive(v) for v in value))
    return set()


class BrokerTests(unittest.TestCase):
    def test_subprocess_private_episode_repair_and_independent_terminal_readback(self):
        with tempfile.TemporaryDirectory() as folder, BrokerClient(folder) as broker:
            first = broker.start(102, TaskParameters(corruption_probability=1))
            self.assertTrue(first["ok"])
            forbidden = {"truth", "ordinary_votes", "delayed_corrupt", "seed", "private_record"}
            self.assertFalse(keys_recursive(first) & forbidden)
            self.assertEqual(first["setup_source_bytes"], 4 * SOURCE_BYTES)
            self.assertEqual(State.from_dict(first["state"]).posterior, 0.5)
            self.assertEqual(first["state"]["delayed_vote"], 0)
            seen = []
            for action in ("READ", "WAIT", "REPAIR", "STOP"):
                result = broker.step(action)
                self.assertTrue(result["ok"])
                self.assertFalse(keys_recursive(result) & forbidden)
                if action in ("READ", "WAIT"):
                    self.assertEqual(result["state"]["delayed_vote"], 0)
                seen.extend(o["source_id"] for o in result["info"]["new_observations"])
            self.assertEqual(seen, ["ordinary/0", "delayed/0"])
            artifact = result["artifact"]
            self.assertTrue(artifact["client_readback_verified"])
            self.assertTrue(artifact["server_readback_verified"])
            payload = Path(artifact["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), artifact["sha256"])
            self.assertEqual(json.loads(payload), artifact["output"])
            self.assertEqual(artifact["output"]["observed_source_ids"], seen)

    def test_unknown_private_inspection_is_rejected_and_guard_denial_is_charged(self):
        with tempfile.TemporaryDirectory() as folder, BrokerClient(folder) as broker:
            broker.start(3, TaskParameters(budget=0))
            denied = broker.request({"op": "get_private_episode"})
            self.assertFalse(denied["ok"])
            self.assertNotIn("truth", denied)
            result = broker.step("READ")
            self.assertEqual(result["info"]["executed_action"], "STOP")
            self.assertTrue(result["info"]["guard_fallback"])
            self.assertEqual(result["info"]["new_observations"], [])
            self.assertAlmostEqual(result["cost"], 0.037)

    def test_corrupted_readback_is_an_operational_failure_not_a_free_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = ArtifactWorker(folder)
            worker.handle({"op": "start", "seed": 7})
            (worker.folder / "ordinary_0.json").write_text("tampered")
            response = worker.handle({"op": "step", "action": "READ"})
            self.assertFalse(response["ok"])
            self.assertTrue(response["operational_failure"])
            self.assertFalse(response["retry_allowed"])
            self.assertEqual(response["incurred_budget_debit"], 2)
            self.assertGreater(response["incurred_modeled_cost"], 0)
            with self.assertRaises(ValueError):
                worker.handle({"op": "step", "action": "STOP"})

    def test_failed_repair_and_terminal_writes_preserve_costs_and_invalidate_session(self):
        for action in ("REPAIR", "STOP"):
            with tempfile.TemporaryDirectory() as folder:
                worker = ArtifactWorker(folder)
                worker.handle({"op": "start", "seed": 17,
                               "parameters": TaskParameters(corruption_probability=1).to_dict()})
                if action == "REPAIR":
                    worker.handle({"op": "step", "action": "WAIT"})
                    worker.handle({"op": "step", "action": "WAIT"})
                before = worker.state
                with patch.object(Path, "write_bytes", side_effect=OSError("injected write failure")):
                    failure = worker.handle({"op": "step", "action": action})
                self.assertFalse(failure["ok"])
                self.assertTrue(failure["operational_failure"])
                self.assertFalse(failure["retry_allowed"])
                self.assertEqual(failure["failed_phase"], "repair_write" if action == "REPAIR" else "terminal_write")
                self.assertAlmostEqual(failure["incurred_modeled_cost"], 0.025 if action == "REPAIR" else 0.007)
                self.assertEqual(worker.state.tick, before.tick + 1)
                self.assertTrue(worker.failed)
                with self.assertRaises(ValueError):
                    worker.handle({"op": "step", "action": "STOP"})


if __name__ == "__main__":
    unittest.main()
