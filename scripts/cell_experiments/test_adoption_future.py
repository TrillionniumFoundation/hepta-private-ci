"""Cold D task controls with explicit model fixtures; no independent evidence."""

import copy
import subprocess
import sys
import unittest
from unittest.mock import patch

from cell_experiments import adoption as a
from cell_experiments import test_adoption as fixtures
from cell_experiments.test_data import record


class AdoptionFutureTests(unittest.TestCase):
    setUp = fixtures.AdoptionTests.setUp
    child = fixtures.AdoptionTests.child

    def add_d(self):
        task = record(4, "confirmation")
        metadata = {k: task[k] for k in ("task_id", "source_id")}
        metadata["task_digest"] = a.digest(task)
        self.request["plan"]["d_tasks"] = [metadata]
        self.request["d_tasks"] = [dict(**metadata, record=task)]
        for name in ("training", "evaluation"):
            self.request[name]["plan_digest"] = a.digest(self.request["plan"])

    def test_actual_new_process_runs_d_after_replay_and_counts_each_call(self):
        self.add_d()
        run = subprocess.run
        code = (
            "import sys; from unittest.mock import patch; "
            "from cell_experiments import adoption as a; "
            "from cell_experiments.test_adoption import Predictor; "
            "p=patch.object(a,'load_predictor',side_effect=lambda m,r: Predictor(m)); "
            "p.start(); print(a.canonical(a.recover(a.read_json(sys.argv[1]),sys.argv[2])).decode())"
        )
        for adopted in (True, False):
            self.request["evaluation"]["rows"][1]["success"] = adopted
            output = self.root / str(adopted)
            with (
                patch.object(
                    a, "load_predictor", side_effect=lambda m, r: fixtures.Predictor(m)
                ),
                patch.object(
                    a.subprocess,
                    "run",
                    side_effect=lambda command, **kw: run(
                        [sys.executable, "-c", code, command[4], command[6]], **kw
                    ),
                ),
            ):
                result = a.execute(self.request, output)
            self.assertEqual(
                result["status"], "ADOPTED" if adopted else "NO_UPDATE", result
            )
            self.assertEqual([r["task_id"] for r in result["D"]], ["task-4"])
            phases = result["execution_costs"]["phases"]
            self.assertEqual(
                {k: v["model_calls"] for k, v in phases.items()},
                {"hot_C": 1, "cold_C_replay": 1, "cold_D": 1},
            )
            self.assertEqual(sum(v["input_tokens"] for v in phases.values()), 21)
            self.assertFalse(
                result["costs_complete"] or result["hepta_final_use_accepted"]
            )
            with patch.object(a, "load_predictor") as loader:
                self.assertEqual(a.execute(self.request, output), result)
                spec = a.read_json(output / "COLD_REQUEST.json")
                with self.assertRaises(a.EvidenceError):
                    a.recover(spec, a.digest(spec))
                for fault in ("strip_d", "replace_record"):
                    changed = copy.deepcopy(spec)
                    if fault == "strip_d":
                        del changed["d_tasks"], changed["replay_expected"]
                    changed["record"] = self.request["d_tasks"][0]["record"]
                    with self.assertRaises(a.EvidenceError):
                        a.recover(changed, a.digest(changed))
            loader.assert_not_called()

    def test_changed_or_overlapping_d_rejected_before_c(self):
        self.add_d()
        original = copy.deepcopy(self.request)
        for fault in ("record", "source", "missing"):
            self.request = copy.deepcopy(original)
            if fault == "record":
                self.request["d_tasks"][0]["record"]["task"]["input"] += " changed"
            elif fault == "missing":
                del self.request["d_tasks"]
            else:
                self.request["plan"]["train_sources"].append("source-4")
                for name in ("training", "evaluation"):
                    self.request[name]["plan_digest"] = a.digest(self.request["plan"])
            with patch.object(a, "load_predictor") as loader:
                result = a.execute(self.request, self.root / fault)
            loader.assert_not_called()
            self.assertIn(result["status"], ("FAILED", "BLOCKED"), result)

    def test_renaming_a_c_or_d_task_cannot_make_another_cold_task(self):
        for origin in ("c_tasks", "d_tasks"):
            with self.subTest(origin=origin):
                self.add_d()
                task = record(5, "confirmation")
                task["task"] = copy.deepcopy(self.request[origin][0]["record"]["task"])
                frozen = dict(
                    task_id=task["task_id"],
                    source_id=task["source_id"],
                    task_digest=a.digest(task),
                )
                self.request["plan"]["d_tasks"].append(frozen)
                self.request["d_tasks"].append(dict(**frozen, record=task))
                for name in ("training", "evaluation"):
                    self.request[name]["plan_digest"] = a.digest(self.request["plan"])
                with (
                    patch.object(
                        a,
                        "load_predictor",
                        side_effect=lambda m, r: fixtures.Predictor(m),
                    ) as loader,
                    patch.object(a.subprocess, "run", side_effect=self.child),
                ):
                    result = a.execute(self.request, self.root / origin)
                self.assertEqual(result["status"], "BLOCKED", result)
                loader.assert_not_called()

    def test_distinct_d_score_with_the_same_prompt_remains_admissible(self):
        self.add_d()
        task = self.request["d_tasks"][0]
        c_input = self.request["c_tasks"][0]["record"]["task"]["input"]
        task["record"]["task"]["input"] = c_input
        self.rebind_c_and_d()
        a.validate(self.request)

    def rebind_c_and_d(self):
        for panel in ("c_tasks", "d_tasks"):
            task = self.request[panel][0]
            task["task_digest"] = a.digest(task["record"])
            self.request["plan"][panel][0]["task_digest"] = task["task_digest"]
        for name in ("training", "evaluation"):
            self.request[name]["plan_digest"] = a.digest(self.request["plan"])

    def test_chat_identity_follows_the_selected_generation_protocol(self):
        self.add_d()
        candidate = self.request["candidate"]
        candidate["runtime"] = {**candidate["runtime"], "message_protocol": "native_chat_v2"}
        candidate_digest = a.digest(candidate)
        self.request["training"]["candidate_model_digest"] = candidate_digest
        candidate_row = self.request["evaluation"]["rows"][1]
        candidate_row["loaded_model_digest"] = candidate_digest
        c = self.request["c_tasks"][0]["record"]["task"]
        d = self.request["d_tasks"][0]["record"]["task"]
        d["input"], d["verifier"] = c["input"], copy.deepcopy(c["verifier"])
        original = {"role": "user", "content": c["input"]}
        d["messages"] = [original]
        self.rebind_c_and_d()
        with self.assertRaisesRegex(a.EvidenceError, "D repeats"):
            a.validate(self.request)

        assistant = {"role": "assistant", "content": "attempt one"}
        c["messages"] = [original, assistant, {"role": "tool", "content": "failed"}]
        d["messages"] = [
            original,
            assistant,
            {"role": "user", "content": "Tool observation:\nfailed"},
        ]
        self.rebind_c_and_d()
        with self.assertRaisesRegex(a.EvidenceError, "D repeats"):
            a.validate(self.request)

        d["messages"][-1]["content"] = "Tool observation:\npassed"
        self.rebind_c_and_d()
        a.validate(self.request)
        candidate_row["success"] = False
        with self.assertRaisesRegex(a.EvidenceError, "unsupported legacy chat history"):
            a.validate(self.request)

        candidate_row["success"] = True
        d["messages"] = [{"role": "user", "content": "unbound task"}]
        self.rebind_c_and_d()
        with patch.object(a, "load_predictor") as loader:
            report = a.execute(self.request, self.root / "malformed-native")
        self.assertEqual(report["status"], "FAILED", report)
        loader.assert_not_called()

    def test_changed_replay_never_dispatches_d(self):
        self.add_d()
        calls = []

        class Divergent(fixtures.Predictor):
            def predict(inner, task):
                calls.append(task["task_id"])
                result = super().predict(task)
                if len(calls) > 1:
                    result["answer"] = "changed replay"
                return result

        with (
            patch.object(a, "load_predictor", side_effect=lambda m, r: Divergent(m)),
            patch.object(a.subprocess, "run", side_effect=self.child),
        ):
            result = a.execute(self.request, self.root / "divergent")
        self.assertEqual(result["status"], "FAILED", result)
        self.assertEqual(calls, ["task-3", "task-3"])

    def test_missing_d_original_cannot_replay_success(self):
        self.add_d()
        output = self.root / "missing-d"
        with (
            patch.object(
                a, "load_predictor", side_effect=lambda m, r: fixtures.Predictor(m)
            ),
            patch.object(a.subprocess, "run", side_effect=self.child),
        ):
            self.assertEqual(a.execute(self.request, output)["status"], "ADOPTED")
        (output / "D_RECEIPTS.json").unlink()
        with patch.object(a, "load_predictor") as loader:
            self.assertEqual(a.execute(self.request, output)["status"], "INCOMPLETE")
        loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
