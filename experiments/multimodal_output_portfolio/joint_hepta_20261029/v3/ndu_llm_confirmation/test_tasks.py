"""Actual local SQLite/file execution with explicitly scripted, non-LLM controllers."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from .tasks import _tool, method_digest, public_task, run_episode, select_action
from .transport import digest
from .ledger import complete_events

SETTINGS = {"deadline_seconds": 3., "call_timeout_seconds": 1., "reserve_model_seconds": .2,
            "max_tools": 2, "fixed_budget": 1, "currency_to_score": 1., "time_price": 0.}


def xor_task():
    return {"tools": {n: {"kind": "file", "predicted_seconds": .01, "predicted_currency": .01} for n in ("a", "b")},
            "planning_model": {"hypotheses": [{"weight": .25, "answer": a ^ b,
                "signals": {"a": digest(str(a)), "b": digest(str(b))}} for a in (0, 1) for b in (0, 1)]}}


class TaskTests(unittest.TestCase):
    def test_planner_finds_complementary_queries_that_myopic_voi_rejects(self):
        task = xor_task()
        self.assertEqual(select_action("one_step_voi", task, [], SETTINGS, 2), "STOP")
        self.assertEqual(select_action("strong_planner", task, [], SETTINGS, 2), "a")
        history = [{"action": "a", "status": "ok", "result": {"signal": digest("0")}}]
        self.assertEqual(select_action("strong_planner", task, history, SETTINGS, 2), "b")
        self.assertEqual(select_action("fixed_budget", task, history, SETTINGS, 2), "STOP")
        self.assertEqual(select_action("direct_stop", task, [], SETTINGS, 2), "STOP")
        self.assertEqual(select_action("strong_planner", task, [], SETTINGS, .201), "STOP")

    def test_model_misspecification_and_unknown_cost_do_not_use_oracle(self):
        task = xor_task()
        history = [{"action": "a", "status": "ok", "result": {"signal": "unpredicted"}}]
        self.assertEqual(select_action("strong_planner", task, history, SETTINGS, 2), "STOP")
        task["tools"]["a"]["predicted_currency"] = None
        with self.assertRaises(ValueError):
            select_action("strong_planner", task, [], SETTINGS, 2)

    def test_file_hash_and_sqlite_read_only_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"sample.sqlite"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE x (n INTEGER)")
                db.executemany("INSERT INTO x VALUES (?)", [(2,), (3,), (5,)])
            task = {"tools": {"sql": {"kind": "sqlite", "path": str(path),
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "query": "SELECT sum(n) FROM x"}}}
            self.assertEqual(_tool(task, "sql")["value"], [[10]])
            task["tools"]["sql"]["query"] = "DELETE FROM x"
            with self.assertRaises(sqlite3.DatabaseError):
                _tool(task, "sql")
            task["tools"]["sql"]["sha256"] = "0"*64
            with self.assertRaises(ValueError):
                _tool(task, "sql")

    def test_endpoint_ready_episode_retains_model_tool_verifier_and_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"fact.txt"
            path.write_text("ten\n", encoding="utf-8")
            task = {"id": "local-fixture", "prompt": "Return the word from the file", "expected_answer": "ten",
                    "tools": {"read": {"kind": "file", "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "predicted_seconds": .01, "predicted_currency": .01}}, "planning_model": {"hypotheses": [
                        {"weight": .5, "answer": word, "signals": {"read": digest(word)}} for word in ("ten", "two")]}}
            identity = {"kind": "offline_fixture", "model_id": "fixture", "revision": "test-v1"}
            code = "import json,sys;p=json.load(sys.stdin);v=p['history'][-1]['result']['value'];print(json.dumps({'model_id':'fixture','revision':'test-v1','text':json.dumps({'answer':v}),'usage':{'input_tokens':1,'output_tokens':1}}))"
            provider = {"kind": "local", "identity": identity, "argv": [sys.executable, "-c", code]}
            ledger = str(Path(directory)/"ledger.jsonl")
            record = run_episode(task, "strong_planner", provider, SETTINGS, ledger, "0"*64,
                                 method_digest("strong_planner", SETTINGS))
            self.assertEqual(record["terminal"], "delivered")
            self.assertEqual(record["answer"], "ten")
            self.assertEqual(record["quality"], 1.)
            self.assertEqual(record["scientific_status"], "NOT_LLM_EVIDENCE")
            events = complete_events([json.loads(s) for s in Path(ledger).read_text().splitlines()])
            self.assertEqual([e["kind"] for e in events], ["tool", "model", "verifier", "host_envelope"])
            self.assertGreaterEqual(record["wall_seconds"], sum(e["wall_seconds"] for e in events if e["kind"] != "host_envelope"))
            self.assertTrue(all(e["actual_amount"] is None for e in events))
            self.assertNotIn("expected_answer", public_task(task))
            self.assertNotIn("path", public_task(task)["tools"]["read"])
            with self.assertRaises(ValueError):
                run_episode(task, "strong_planner", provider, {**SETTINGS, "fixed_budget": 2}, ledger,
                            "0"*64, method_digest("strong_planner", SETTINGS))

    def test_timeout_and_cancellation_deliver_no_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            task = {"id": "slow", "prompt": "q", "expected_answer": 1, "tools": {}, "planning_model": {"hypotheses": []}}
            provider = {"kind": "local", "identity": {"kind": "offline_fixture", "model_id": "fixture", "revision": "test-v1"},
                        "argv": [sys.executable, "-c", "import time;time.sleep(1)"]}
            settings = {**SETTINGS, "deadline_seconds": .12, "max_tools": 0}
            ledger = str(Path(directory)/"ledger.jsonl")
            record = run_episode(task, "direct_stop", provider, settings, ledger, "0"*64, method_digest("direct_stop", settings))
            self.assertEqual(record["quality"], 0.)
            self.assertIsNone(record["delivery_at_seconds"])
            self.assertEqual(len(record["request_ids"]), 2)
            record = run_episode(task, "direct_stop", provider, settings, ledger, "0"*64,
                                 method_digest("direct_stop", settings), cancelled=lambda: True)
            self.assertEqual(record["terminal"], "cancelled")
            self.assertEqual(record["quality"], 0.)


if __name__ == "__main__":
    unittest.main()
