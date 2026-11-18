"""Protocol fixtures plus real repository business checks; never model evidence."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .. import data, repo_execution
from ..coding_sft import write_new
from ..protocol_v3 import prepare_record, verify_reference
from ..repo_interaction_v2 import corrected_record
from ..test_data import record
from ..test_repo_execution import answer
from .onpolicy_feedback import feedback
from .onpolicy_loop import make_freeze, run
from .onpolicy_rollout import attempts, collect_current

CORRECT = answer(
    '    assert subject({"calls": 0}, "calls") == {"calls": 1}\n'
    '    assert subject({"calls": 5}, "calls") == {"calls": 6}'
)


def prepared(number):
    row = record(number)
    row["task"] = {
        "input": "Test subject(state, name): increment a named counter, including zero and nonzero cases.",
        "verifier": {
            "name": "repo_patch",
            "version": "1",
            "parameters": {
                "fixture_id": "A-counter",
                "fixture_sha256": data.digest(repo_execution._CATALOG["A-counter"]),
            },
        },
    }
    row["final_answer"], row["trajectory"] = CORRECT, []
    row.pop("verified_outcome")
    return verify_reference(prepare_record(row))


class ScriptedPredictor:
    """Version-dependent scripted outputs isolate orchestration from numerical tests."""

    generation_digest = "b" * 64

    def __init__(self, manifest, calls, overrides=None):
        self.manifest, self.model_digest = manifest, data.digest(manifest)
        self.calls, self.overrides, self.closed = calls, overrides, False

    def predict(self, request):
        self.calls.append((self.model_digest, copy.deepcopy(request)))
        response = (
            next(self.overrides)
            if self.overrides is not None
            else (CORRECT if self.manifest["generation"] else '{"edits":[')
        )
        return {
            "answer": response,
            "loaded_model_digest": self.model_digest,
            "generation_config_sha256": self.generation_digest,
            "input_sha256": hashlib.sha256(
                request["task"]["input"].encode()
            ).hexdigest(),
            "messages_sha256": data.digest(request["task"]["messages"]),
            "input_tokens": 10,
            "output_tokens": 5,
        }

    def close(self):
        self.closed = True


class FixtureBackend:
    """The fit is a protocol fixture, not optimizer work or a scientific outcome."""

    def __init__(self):
        self.calls, self.fits, self.loads = [], [], []

    def sources(self):
        return {"test_backend": "scripted_protocol_fixture"}

    def verify_model(self, manifest):
        return data.digest(manifest)

    def load(self, manifest, root):
        self.loads.append(data.digest(manifest))
        return ScriptedPredictor(manifest, self.calls)

    def collect(self, records, current, output, mode, maximum):
        if mode == "teacher":
            return {
                "model_digest": data.digest(current),
                "records_digest": data.digest(records),
                "rows": [],
                "model_calls": 0,
                "student_verifier_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "reused_observation_count": 0,
                "complete": True,
            }
        return collect_current(
            records,
            current,
            None,
            output,
            self.load,
            maximum=maximum,
            execute=mode == "controlled",
        )

    def corrections(self, records, collection, mode, round_index, output):
        return (
            copy.deepcopy(records)
            if mode == "teacher"
            else [
                corrected_record(row, observed, mode)
                for row, observed in zip(records, collection["rows"])
            ]
        )

    def make_plan(self, records, current, operation_id, round_index, mode):
        return {
            "previous_model_digest": data.digest(current),
            "training": {"steps": 64},
            "previous_training": {"parameter_after": current["parameter_after"]},
        }

    def fit(self, records, current, plan, output):
        self.fits.append((copy.deepcopy(current), copy.deepcopy(records)))
        candidate = {
            "generation": current["generation"] + 1,
            "parameter_after": data.digest(
                {"protocol_fixture_round": current["generation"] + 1}
            ),
        }
        receipt = {
            "status": "COMPLETE",
            "candidate_model_digest": data.digest(candidate),
            "previous_model_digest": data.digest(current),
            "steps": 64,
            "warm_start": True,
            "warm_start_matched": True,
            "optimizer_resume": False,
            "parameter_before": current["parameter_after"],
            "parameter_after": candidate["parameter_after"],
            "parameter_change": True,
        }
        write_new(
            Path(output) / "PROTOCOL_FIXTURE.json",
            {"model": candidate, "receipt": receipt},
        )
        return candidate, receipt

    def evaluate(self, records, current, output, maximum):
        return self.collect(records, current, output, "controlled", maximum)


class CurrentPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo_execution.load_catalog("open")
        cls.records = [prepared(i) for i in range(1, 7)]
        cls.initial = {
            "generation": 0,
            "parameter_after": data.digest({"protocol_fixture_round": 0}),
        }

    def test_real_ast_rejection_is_stable_and_never_leaks_raw_error(self):
        bad = answer("    assert subject(variable, 'calls') == {'calls': 1}")
        first = data.verify_answer(self.records[0], bad)
        second = copy.deepcopy(first)
        first["result"]["feedback"] = (
            "malformed node or string on line 2: <ast.Name object at 0x123abc>"
        )
        second["result"]["feedback"] = (
            "malformed node or string on line 2: <ast.Name object at 0x987def>"
        )
        before = copy.deepcopy(first)
        self.assertEqual(feedback(first), feedback(second))
        self.assertEqual(
            json.loads(feedback(first))["error_code"], "NON_LITERAL_EXPRESSION"
        )
        self.assertNotIn("0x", feedback(first))
        self.assertEqual(first, before)

    def test_actual_business_retry_uses_only_its_observed_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            predictor = ScriptedPredictor(
                self.initial, [], iter(['{"edits":[', CORRECT])
            )
            observed = attempts(predictor, self.records[0], Path(tmp) / "run")
            self.assertEqual([s["executed"] for s in observed["steps"]], [False, True])
            self.assertEqual(
                [s["verification"]["success"] for s in observed["steps"]], [False, True]
            )
            self.assertEqual(
                predictor.calls[1][1]["task"]["messages"][-1],
                {"role": "tool", "content": observed["steps"][0]["feedback"]},
            )
            self.assertEqual(
                observed["steps"][1]["verification"]["result"]["reason"],
                "business_tests_passed",
            )

    def test_updated_candidate_is_the_next_round_policy_and_is_finally_used(self):
        backend, context = FixtureBackend(), {"records": self.records}
        freeze = make_freeze(
            context,
            self.initial,
            backend,
            operation_id="engineering",
            mode="controlled",
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run(context, self.initial, Path(tmp) / "run", freeze, backend)
            identities = [row["current_model_digest"] for row in result["rounds"]]
            self.assertEqual(backend.loads, [*identities, result["final_model_digest"]])
            self.assertEqual(
                identities[1], result["rounds"][0]["candidate_model_digest"]
            )
            for initial, records in backend.fits:
                self.assertEqual(
                    {
                        e["policy_sha256"]
                        for row in records
                        for e in row["trajectory"]
                        if e["actor"] == "student"
                    },
                    {data.digest(initial)},
                )
                self.assertTrue(
                    all(
                        e["trainable"] is False
                        for row in records
                        for e in row["trajectory"]
                        if e["actor"] == "student"
                    )
                )
            self.assertEqual(result["independent_sample_increment"], 0)

    def test_teacher_does_not_call_student_and_shadow_does_not_execute(self):
        for mode in ("teacher", "shadow"):
            backend, context = FixtureBackend(), {"records": self.records}
            freeze = make_freeze(
                context, self.initial, backend, operation_id="engineering", mode=mode
            )
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                result = run(context, self.initial, Path(tmp) / "run", freeze, backend)
                self.assertEqual(len(backend.fits), 2)
                self.assertEqual(
                    result["student_verifier_calls"], 6
                )  # final evaluation only
                self.assertEqual(result["model_calls"], 6 if mode == "teacher" else 18)

    def test_stale_current_candidate_is_rejected_before_its_actions(self):
        backend, context = FixtureBackend(), {"records": self.records}
        original = backend.load
        backend.load = lambda current, root: original(self.initial, root)
        freeze = make_freeze(
            context,
            self.initial,
            backend,
            operation_id="engineering",
            mode="controlled",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "this round's manifest"):
                run(context, self.initial, Path(tmp) / "run", freeze, backend)
            failure = json.loads((Path(tmp) / "run" / "FAILED.json").read_text())
            self.assertEqual(len(failure["completed_rounds"]), 1)
            self.assertFalse(failure["call_totals_complete"])


if __name__ == "__main__":
    unittest.main()
