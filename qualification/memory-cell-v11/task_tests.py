"""Real compiler integration checks for bounded repair/abstention behavior."""

import os
import shutil
import tempfile
import unittest

from tasks import Compiler, diagnostic_rule, execute_policy, make_tasks


@unittest.skipUnless(os.environ.get("MEMORY_V11_RUSTC") or shutil.which("rustc"), "requires Rust compiler")
class CompilerTaskTests(unittest.TestCase):
    def test_all_actions_and_unknowns_have_observed_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            compiler = Compiler(os.environ.get("MEMORY_V11_RUSTC", "rustc"), directory)
            tasks = make_tasks(606061, "development", per_family=1, unknown=1)
            results = [execute_policy(task, compiler,
                       lambda text, observed: (diagnostic_rule(observed), {})) for task in tasks]
            self.assertTrue(all(result["success"] for result in results), results)
            self.assertEqual(sum(result["status"] == "executed" for result in results), 4)
            self.assertEqual(sum(result["status"] == "abstained" for result in results), 1)
            self.assertEqual([result["actual_compiler_calls"] for result in results], [2, 2, 2, 2, 1])
            self.assertEqual(sum(step["applied"] for result in results for step in result["trace"]), 4)

    def test_composition_consumes_new_compiler_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            compiler = Compiler(os.environ.get("MEMORY_V11_RUSTC", "rustc"), directory)
            task = make_tasks(606062, "development-pairs", per_family=1, paired=True, unknown=0)[0]
            outcome = execute_policy(task, compiler,
                                     lambda text, observed: (diagnostic_rule(observed), {}), steps=2)
            self.assertTrue(outcome["success"], outcome)
            self.assertEqual(len(outcome["trace"]), 2)
            self.assertNotEqual(outcome["trace"][0]["observed_source_sha256"],
                                outcome["trace"][1]["observed_source_sha256"])
            limited = execute_policy(task, compiler,
                                     lambda text, observed: (diagnostic_rule(observed), {}), steps=1)
            self.assertFalse(limited["success"])

    def test_noop_attempt_does_not_invent_a_compiler_call(self):
        with tempfile.TemporaryDirectory() as directory:
            compiler = Compiler(os.environ.get("MEMORY_V11_RUSTC", "rustc"), directory)
            task = make_tasks(606063, "development-unsupported", per_family=0, unknown=1)[0]
            outcome = execute_policy(task, compiler, lambda text, obs: ("borrow", {}))
            self.assertEqual(outcome["actual_compiler_calls"], 1)
            self.assertEqual(outcome["observation_requests"], 1)
            self.assertFalse(outcome["trace"][0]["applied"])


if __name__ == "__main__":
    unittest.main()
