"""Replay sealed program-cell worker traces in a separate real subprocess.

Only the allowlisted existing event_probe.py is executed; it accepts bounded
sort/reverse recipes. A SHA string without original request, stdout and exit
receipts is insufficient. This is a *controlled-program* integrity diagnosis,
not proof of executing an arbitrary PR, autonomous coding, or production skill.
Gold answers and target labels are never read by this module.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from factorial_evidence_gate import ARMS, CONDITIONS, READERS, canonical, sha
from memory_trial_admission import bound_read, ensure, hexsha
from memory_trial_independent_score import _answer

SCHEMA = "hepta.memory-cell.controlled-program-trace.v1"
SPEC = "hepta.memory-cell.preregistered-program-tests.v1"
FIELDS = ("id", "arm", "condition", "reader")
MAX_RECEIPTS = 16384
MAX_TESTS_PER_CASE = 8
MAX_PROCESS_OUTPUT = 16384


def audit(plan, originals, specification, receipts, *, worker=None):
    """Reject incomplete/mutated program traces and actually reexecute each test.

    All test recipes are pinned in `plan` BEFORE test tasks are exposed. A
    separate original trace binds the generated identifier to actual captured
    request, stdout, stderr and exit code. Replay can certify only this fixed
    worker's behavior, never human entailment or a successful model generation.
    """
    ensure(isinstance(plan, dict) and isinstance(originals, list),
           "frozen plan and original attempt array required")
    ensure(isinstance(specification, dict) and specification.get("schema") == SPEC,
           "registered bounded program-test specification required")
    ensure(isinstance(receipts, dict) and receipts.get("schema") == SCHEMA,
           "original program trace archive required")
    worker = Path(__file__).with_name("event_probe.py") if worker is None else Path(worker)
    ensure(worker.is_file() and not worker.is_symlink(), "trusted fixed worker required")
    worker_sha = hashlib.sha256(worker.read_bytes()).hexdigest()
    ensure(hexsha(plan.get("program_worker_sha256"))
           and plan["program_worker_sha256"] == worker_sha
           and specification.get("worker_sha256") == worker_sha,
           "fixed worker executable changed after preregistration")
    cases = plan.get("cases")
    ensure(isinstance(cases, list) and cases, "nonempty trial plan required")
    programs = {c["id"]: c for c in cases if c["task"] == "program"}
    ensure(programs, "at least one real-process program case required")
    selected = specification.get("cases")
    ensure(isinstance(selected, list) and len(selected) == len(programs),
           "incomplete program specification")
    recipes = {}
    for spec in selected:
        ensure(isinstance(spec, dict) and set(spec) == {"id", "tests"},
               "unexpected program specification fields")
        cid, tests = spec["id"], spec["tests"]
        ensure(isinstance(cid, str) and cid in programs and cid not in recipes
               and isinstance(tests, list) and 1 <= len(tests) <= MAX_TESTS_PER_CASE,
               "duplicate or invalid registered program case")
        ensure(hexsha(programs[cid].get("program_manifest_sha256"))
               and sha(tests) == programs[cid]["program_manifest_sha256"],
               "pre-exposure program tests changed")
        for recipe in tests:
            ensure(isinstance(recipe, dict)
                   and set(recipe) == {"values", "modes", "target"},
                   "unregistered program workload")
        recipes[cid] = tests
    ensure(set(recipes) == set(programs), "missing program source tests")
    plan_receipt = receipts.get("plan_sha256")
    original_receipt = receipts.get("original_sha256")
    ensure(plan_receipt == sha(plan) and original_receipt == sha(originals),
           "program receipt detached from original plan or model journal")
    original = {}
    all_keys = {(c["id"], a, condition, reader)
                for c in cases for a in ARMS for condition in CONDITIONS
                for reader in READERS}
    ensure(len(originals) == len(all_keys), "incomplete complete-model call census")
    for row in originals:
        ensure(isinstance(row, dict), "original model call required")
        key = tuple(row.get(k) for k in FIELDS)
        ensure(key in all_keys and key not in original,
               "missing or duplicate original model call")
        original[key] = row
    expected = {key for key in original if key[0] in programs}
    trace_rows = receipts.get("traces")
    ensure(isinstance(trace_rows, list) and len(trace_rows) == len(expected)
           and 0 < len(trace_rows) <= MAX_RECEIPTS,
           "complete original program trace census required")
    seen = set()
    replayed = passed = 0
    for trace in trace_rows:
        ensure(isinstance(trace, dict) and set(trace) == {*FIELDS, "tests"},
               "unexpected original program trace fields")
        key = tuple(trace.get(k) for k in FIELDS)
        ensure(key in expected and key not in seen, "missing or duplicate program trace")
        seen.add(key)
        row = original[key]
        ensure(hexsha(row.get("tool_trace_sha256"))
               and sha(trace) == row["tool_trace_sha256"],
               "program hash cannot replace original execution receipt")
        tests = trace["tests"]
        ensure(isinstance(tests, list) and len(tests) == len(recipes[row["id"]]),
               "incomplete program subprocess tests")
        value = _answer(row.get("answer"))
        supplied = value if value is not None else "invalid_response"
        good = 0
        for recipe, saved in zip(recipes[row["id"]], tests, strict=True):
            ensure(isinstance(saved, dict)
                   and set(saved) == {"request", "stdout", "stderr", "exit_code"},
                   "original real-process output receipt missing")
            expected_request = {"operation": "execute", "recipe": recipe,
                                "supplied": supplied}
            ensure(saved["request"] == expected_request,
                   "program request substituted after Reader output")
            ensure(isinstance(saved["stdout"], str)
                   and isinstance(saved["stderr"], str)
                   and len(saved["stdout"].encode()) + len(saved["stderr"].encode())
                   <= MAX_PROCESS_OUTPUT
                   and type(saved["exit_code"]) is int,
                   "invalid original subprocess output")
            process = subprocess.run(
                [sys.executable, "-I", "-S", str(worker)],
                input=json.dumps(expected_request, sort_keys=True),
                text=True, capture_output=True, timeout=10, check=False,
            )
            ensure((process.stdout, process.stderr, process.returncode)
                   == (saved["stdout"], saved["stderr"], saved["exit_code"]),
                   "independent subprocess replay differs from original trace")
            ensure(process.returncode in (0, 2) and not process.stderr,
                   "registered fixed worker failed unexpectedly")
            output = json.loads(process.stdout)
            ensure(type(output.get("succeeded")) is bool
                   and output.get("supplied") == supplied
                   and output["succeeded"] == (process.returncode == 0),
                   "program worker structured result inconsistent")
            good += process.returncode == 0
            replayed += 1
        ensure(type(row.get("program_test_count")) is int
               and type(row.get("program_tests_passed")) is int
               and type(row.get("program_exit_code")) is int
               and row["program_test_count"] == len(tests)
               and row["program_tests_passed"] == good
               and row["program_exit_code"] == (0 if good == len(tests) else 2),
               "original program task success counters detached from execution")
        passed += good
    ensure(seen == expected, "incomplete original program test population")
    return dict(
        schema="hepta.memory-cell.fixed-subprocess-program-replay.v1",
        bound_original_sha256=sha(originals),
        bound_plan_sha256=sha(plan),
        bound_program_spec_sha256=sha(specification),
        bound_worker_sha256=worker_sha,
        complete_program_model_calls=len(seen),
        independently_reexecuted_tests=replayed,
        reproduced_passing_tests=passed,
        independent_process_replay_success=True,
        run_generated_pretrained_model_calls=0,
        controlled_sort_reverse_only=True,
        human_semantic_review_performed=False,
        general_real_project_program_success_proven=False,
        production_qualified=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "original", "spec", "receipts", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("plan", "original", "spec", "receipts"):
        parser.add_argument("--" + name + "-sha256", required=True)
    args = parser.parse_args()
    sources = {name: bound_read(getattr(args, name), getattr(args, name + "_sha256"))
               for name in ("plan", "original", "spec", "receipts")}
    report = audit(sources["plan"], sources["original"], sources["spec"], sources["receipts"])
    report["external_byte_pins"] = {
        name: getattr(args, name + "_sha256")
        for name in ("plan", "original", "spec", "receipts")
    }
    with args.output.open("x", encoding="utf-8") as dest:
        json.dump(report, dest, indent=2, sort_keys=True, allow_nan=False)
        dest.write("\n")
    print(json.dumps({"actual_process_replays": report["independently_reexecuted_tests"],
                      "production_qualified": False}, sort_keys=True))


if __name__ == "__main__":
    main()
