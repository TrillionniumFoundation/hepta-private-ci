"""Controlled real-subprocess replays, not pretrained or human review evidence."""

import copy
from functools import lru_cache
import hashlib
import json
import tempfile
from pathlib import Path
import subprocess
import sys
import unittest

from factorial_evidence_gate import sha
from memory_trial_program_replay import audit, SCHEMA, SPEC
from memory_trial_independent_score import _answer, COMMITMENT_SCHEME, commit_identifier
from test_memory_trial_admission import fixture


@lru_cache(maxsize=1)
def _base_fixture():
    plan, raw, _ = fixture()
    worker = Path(__file__).with_name("event_probe.py")
    identity = hashlib.sha256(worker.read_bytes()).hexdigest()
    plan["program_worker_sha256"] = identity
    tests = [
        dict(
            values=[4, 2, 1, 3],
            modes={"mode_correct": "sort", "mode_other": "reverse"},
            target=[1, 2, 3, 4],
        ),
        dict(
            values=[3, 1, 2],
            modes={"mode_correct": "sort", "mode_other": "reverse"},
            target=[1, 2, 3],
        ),
    ]
    for case in plan["cases"]:
        if case["task"] == "program":
            case["program_manifest_sha256"] = sha(tests)
    specification = dict(
        schema=SPEC, worker_sha256=identity, cases=[dict(id="case-3", tests=tests)]
    )
    traces = []
    for row in raw:
        if row["id"] != "case-3":
            continue
        row["answer"] = "mode_correct [E1]"
        entries = []
        for recipe in tests:
            request = dict(
                operation="execute", recipe=recipe, supplied=_answer(row["answer"])
            )
            process = subprocess.run(
                [sys.executable, "-I", "-S", str(worker)],
                input=json.dumps(request, sort_keys=True),
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            entries.append(
                dict(
                    request=request,
                    stdout=process.stdout,
                    stderr=process.stderr,
                    exit_code=process.returncode,
                )
            )
        trace = {key: row[key] for key in ("id", "arm", "condition", "reader")}
        trace["tests"] = entries
        row.update(
            tool_trace_sha256=sha(trace),
            program_exit_code=0,
            program_test_count=2,
            program_tests_passed=2,
        )
        traces.append(trace)
    receipts = dict(
        schema=SCHEMA, plan_sha256=sha(plan), original_sha256=sha(raw), traces=traces
    )
    return plan, raw, specification, receipts


def fixture_traces():
    # One real subprocess-generation fixture, isolated per mutation test.
    return copy.deepcopy(_base_fixture())


class ProgramReplayTests(unittest.TestCase):
    def test_actual_subprocess_replays_all_original_program_rows(self):
        args = fixture_traces()
        report = audit(*args)
        self.assertEqual(report["complete_program_model_calls"], 40)
        self.assertEqual(report["independently_reexecuted_tests"], 80)
        self.assertEqual(report["reproduced_passing_tests"], 80)
        self.assertFalse(report["production_qualified"])
        self.assertFalse(report["general_real_project_program_success_proven"])

    def test_full_cli_replays_before_reading_gold(self):
        plan, originals, specification, receipts = fixture_traces()
        labels = []
        plan["answer_commitment_scheme"] = COMMITMENT_SCHEME
        for i, case in enumerate(plan["cases"]):
            expected = (
                "mode_correct" if case["task"] == "program" else f"site_unseen_{i}"
            )
            nonce = hashlib.sha256(f"synthetic-salt-{i}".encode()).hexdigest()
            case["answer_sha256"] = commit_identifier(expected, nonce)
            labels.append({"id": case["id"], "expected": expected, "nonce": nonce})
        receipts["plan_sha256"] = sha(plan)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = dict(
                plan=plan,
                original=originals,
                spec=specification,
                receipts=receipts,
                labels=labels,
            )
            argv = [
                sys.executable,
                str(Path(__file__).with_name("memory_trial_independent_score.py")),
            ]
            for name, value in inputs.items():
                path = root / f"{name}.json"
                path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
                option = "program-" + name if name in ("spec", "receipts") else name
                argv.extend(
                    [
                        "--" + option,
                        str(path),
                        "--" + option + "-sha256",
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    ]
                )
            argv += [
                "--scored",
                str(root / "scored.json"),
                "--report",
                str(root / "report.json"),
            ]
            proc = subprocess.run(argv, text=True, capture_output=True, timeout=45)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads((root / "report.json").read_text())
            self.assertTrue(report["program_execution_independently_replayed"])
            self.assertEqual(
                report["controlled_program_replay"]["independently_reexecuted_tests"],
                80,
            )
            self.assertEqual(report["recomputed_strict_successes"], 40)
            self.assertFalse(report["general_project_program_skill_qualified"])
            self.assertFalse(report["production_qualified"])

    def test_missing_original_process_output_rejected(self):
        p, r, s, rec = fixture_traces()
        rec["traces"][0]["tests"][0]["stdout"] = '{"succeeded":true}'
        with self.assertRaisesRegex(ValueError, "program hash cannot replace"):
            audit(p, r, s, rec)

    def test_witness_digest_not_enough_for_forged_execution(self):
        p, r, s, rec = fixture_traces()
        rec["traces"][0]["tests"][0]["stdout"] = "not original process output"
        key = (
            rec["traces"][0]["id"],
            rec["traces"][0]["arm"],
            rec["traces"][0]["condition"],
            rec["traces"][0]["reader"],
        )
        original = next(
            x for x in r if (x["id"], x["arm"], x["condition"], x["reader"]) == key
        )
        original["tool_trace_sha256"] = sha(rec["traces"][0])
        rec["original_sha256"] = sha(r)
        with self.assertRaisesRegex(
            ValueError, "independent subprocess replay differs"
        ):
            audit(p, r, s, rec)

    def test_modified_test_recipe_fails_preexposure_binding(self):
        p, r, s, rec = fixture_traces()
        s["cases"][0]["tests"][0]["target"] = [99]
        with self.assertRaisesRegex(ValueError, "pre-exposure program tests changed"):
            audit(p, r, s, rec)

    def test_worker_source_change_detected(self):
        p, r, s, rec = fixture_traces()
        p["program_worker_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "worker executable changed"):
            audit(p, r, s, rec)

    def test_program_counters_must_equal_real_process(self):
        p, r, s, rec = fixture_traces()
        record = next(x for x in r if x["id"] == "case-3")
        record["program_tests_passed"] = 1
        rec["original_sha256"] = sha(r)
        with self.assertRaisesRegex(ValueError, "counters detached"):
            audit(p, r, s, rec)

    def test_must_keep_complete_model_census(self):
        p, r, s, rec = fixture_traces()
        r.pop()
        rec["original_sha256"] = sha(r)
        with self.assertRaisesRegex(ValueError, "incomplete complete-model"):
            audit(p, r, s, rec)

    def test_duplicate_program_call_rejected(self):
        p, r, s, rec = fixture_traces()
        rec["traces"][1] = copy.deepcopy(rec["traces"][0])
        with self.assertRaisesRegex(ValueError, "missing or duplicate program trace"):
            audit(p, r, s, rec)


if __name__ == "__main__":
    unittest.main()
