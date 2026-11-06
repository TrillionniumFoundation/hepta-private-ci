"""Executable callback binding tests with scripted providers, never real LLM evidence."""
import functools
import json
from pathlib import Path
import sys
import tempfile
import unittest
from .ledger import complete_events
from .policy import PolicyBindingError, policy_binding
from .tasks import method_digest, run_episode
from .test_tasks import SETTINGS

FROZEN_CHOICE = "STOP"
MUTABLE_CHOICE = ["STOP"]


def stop_policy(task, history, settings, remaining, request_model):
    return "STOP"


def acquire_policy(task, history, settings, remaining, request_model):
    return "read"


def probing_policy(task, history, settings, remaining, request_model):
    request_model({"instruction": "Offline fixture internal call"})
    settings["deadline_seconds"] = 0  # Callback receives a copy, not the execution contract.
    return "STOP"


def immutable_global_policy(task, history, settings, remaining, request_model):
    return FROZEN_CHOICE


def mutable_global_policy(task, history, settings, remaining, request_model):
    return MUTABLE_CHOICE[0]


class PolicyTests(unittest.TestCase):
    def test_distinct_callbacks_cannot_share_a_frozen_method_digest(self):
        settings = {**SETTINGS, "policy_binding": policy_binding(stop_policy)}
        first = method_digest("full", settings, stop_policy)
        with self.assertRaises(PolicyBindingError):
            method_digest("full", settings, acquire_policy)
        changed = {**settings, "policy_binding": policy_binding(acquire_policy)}
        self.assertNotEqual(first, method_digest("full", changed, acquire_policy))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"ledger.jsonl"
            with self.assertRaises(PolicyBindingError):
                run_episode({}, "full", {}, settings, path, "0"*64, first, policy=acquire_policy)
            self.assertFalse(path.exists())

    def test_full_requires_actual_callback_even_when_no_tools_are_allowed(self):
        settings = {**SETTINGS, "max_tools": 0, "policy_binding": policy_binding(stop_policy)}
        with self.assertRaises(PolicyBindingError):
            method_digest("full", settings)
        with self.assertRaises(PolicyBindingError):
            method_digest("full", SETTINGS, stop_policy)
        with self.assertRaises(PolicyBindingError):
            method_digest("direct_stop", SETTINGS, stop_policy)

    def test_closures_lambdas_partial_and_mutable_globals_are_rejected(self):
        choice = "STOP"
        def closure(task, history, settings, remaining, request_model):
            return choice
        for candidate in (closure, lambda *args: "STOP", functools.partial(stop_policy), mutable_global_policy):
            with self.subTest(candidate=type(candidate).__name__):
                with self.assertRaises(PolicyBindingError):
                    policy_binding(candidate)

    def test_actual_runtime_code_must_still_match_the_full_source_file(self):
        original = stop_policy.__code__
        try:
            stop_policy.__code__ = acquire_policy.__code__
            with self.assertRaises(PolicyBindingError):
                policy_binding(stop_policy)
        finally:
            stop_policy.__code__ = original
        self.assertEqual(policy_binding(stop_policy)["qualname"], "stop_policy")

    def test_immutable_globals_are_rechecked_instead_of_trusting_a_declared_hash(self):
        global FROZEN_CHOICE
        settings = {**SETTINGS, "policy_binding": policy_binding(immutable_global_policy)}
        original = FROZEN_CHOICE
        try:
            FROZEN_CHOICE = "read"
            with self.assertRaises(PolicyBindingError):
                method_digest("full", settings, immutable_global_policy)
        finally:
            FROZEN_CHOICE = original

    def test_a_bound_full_callback_runs_with_all_internal_model_calls_metered(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory)/"ledger.jsonl"
            task = {"id": "bound-full-fixture", "prompt": "Return 1", "expected_answer": 1,
                    "tools": {}, "planning_model": {"hypotheses": []}}
            code = "import json;print(json.dumps({'model_id':'fixture','revision':'test-v1','text':'{\"answer\":1}','usage':{'input_tokens':1,'output_tokens':1}}))"
            provider = {"kind": "local", "identity": {"kind": "offline_fixture", "model_id": "fixture", "revision": "test-v1"},
                        "argv": [sys.executable, "-c", code]}
            settings = {**SETTINGS, "max_tools": 0, "policy_binding": policy_binding(probing_policy)}
            method = method_digest("full", settings, probing_policy)
            record = run_episode(task, "full", provider, settings, ledger, "0"*64, method, policy=probing_policy)
            self.assertEqual(record["terminal"], "delivered")
            self.assertEqual(record["quality"], 1.)
            self.assertEqual(record["scientific_status"], "NOT_LLM_EVIDENCE")
            self.assertEqual(record["contract"]["deadline_seconds"], SETTINGS["deadline_seconds"])
            events = complete_events([json.loads(line) for line in ledger.read_text().splitlines()])
            self.assertEqual([e["kind"] for e in events], ["model", "model", "verifier", "host_envelope"])
            self.assertEqual(len(record["request_ids"]), 4)


if __name__ == "__main__":
    unittest.main()
