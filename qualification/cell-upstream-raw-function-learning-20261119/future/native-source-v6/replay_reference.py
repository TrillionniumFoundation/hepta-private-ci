"""Replay an already retained original pair under the explicit plugin runtime.

Every package, test, oracle, dependency and case identity stays bound to the
original receipt. This performs two new real native children and never edits or
relabels either old result. No model or training code is imported.
"""

import argparse
import json
from pathlib import Path
import time

import future_native as native


def identities(receipt):
    return [[row["classname"], row["name"]] for row in receipt.get("cases", [])]


def replay(source, source_sha, output):
    begun = time.perf_counter()
    original_raw = (source / "RESULT.json").read_bytes()
    if native.sha(original_raw) != source_sha:
        raise ValueError("original native receipt changed")
    original = json.loads(original_raw)
    if original["after"]["timed_out"] or original["after"]["errors"]:
        raise ValueError("this replay requires an original complete collected case set")
    spec_raw = (source / "TASK_SPEC.json").read_bytes()
    spec = native.bound(source / "TASK_SPEC.json", original["task_spec_sha256"])
    if spec["project_id"] != "scrapy/w3lib":
        raise ValueError(
            "this prospective replay is limited to the fixed w3lib history"
        )
    plugins = native.original_pytest_plugins(spec)
    if plugins != [native.HYPOTHESIS_PLUGIN]:
        raise ValueError("exact original pytest plugin admission is incomplete")
    output.mkdir(parents=True, exist_ok=False)
    native.write(
        output / "INTENT.json",
        {
            "started_at_ns": str(time.time_ns()),
            "original_qualification_root": str(source),
            "original_result_sha256": source_sha,
            "original_task_spec_sha256": native.sha(spec_raw),
            "replay_source_sha256": native.sha(Path(__file__).read_bytes()),
            "native_runtime_sha256": native.sha(Path(native.__file__).read_bytes()),
            "explicit_original_pytest_plugins": plugins,
            "original_case_scope_timeouts_permissions_and_success_gate_unchanged": True,
            "new_model_calls": 0,
            "new_training_updates": 0,
            "planned_native_children": 2,
        },
    )
    for row in spec["files"]:
        raw = (source / row["path"]).read_bytes()
        if len(raw) != row["bytes"] or native.sha(raw) != row["sha256"]:
            raise ValueError("original retained material changed before exact copy")
        target = output / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        native.write(target, raw)
    native.write(output / "TASK_SPEC.json", spec_raw)
    native.write(output / "ORIGINAL_RESULT.json", original_raw)
    admitted = native.bound(output / "TASK_SPEC.json", original["task_spec_sha256"])
    before, after = native.before_oracle(admitted)
    gate = native.load_module(
        "replay_original_gate", native.ANCESTOR, native.ANCESTOR_SHA
    )
    gate.TARGETS[spec["project_id"]] = (
        spec["source_path"],
        spec["function"],
        spec.get("optional_constant"),
    )
    native.write(
        output / "REFERENCE_ADMISSION.json",
        gate.check_ast(spec["project_id"], before, after, after),
    )
    first = native.run_native(admitted, output / "before-run", label="original_parent")
    second = native.run_native(
        admitted, output / "after-run", after, label="exact_reference_function"
    )
    same_original = (
        identities(first) == identities(second) == original["expected_cases"]
    )
    qualified = bool(
        first["actual_wait_returncode"] == 1
        and first.get("failures", 0) > 0
        and first.get("errors") == first.get("skipped") == 0
        and not first["timed_out"]
        and first["sandbox_attestation_sha256"]
        and second["success"]
        and same_original
    )
    result = {
        **{
            key: original[key]
            for key in (
                "repository",
                "commit_index",
                "source_index",
                "commit",
                "parent",
                "function",
                "source_path",
                "remaining_qualification",
            )
        },
        "status": "ORIGINAL_NATIVE_PAIR_PASSED"
        if qualified
        else "ORIGINAL_NATIVE_PAIR_REJECTED",
        "task_spec_sha256": native.sha(spec_raw),
        "same_original_case_set": same_original,
        "expected_cases": identities(second),
        "before": first,
        "after": second,
        "native_children": 2,
        "model_calls": 0,
        "training_updates": 0,
        "wall_seconds": time.perf_counter() - begun,
        "candidate_selected": False,
        "replayed_original_result_sha256": source_sha,
        "original_case_identities_compared_to_prior_profile": True,
        "explicit_original_pytest_plugins": plugins,
        "native_runtime_sha256": native.sha(Path(native.__file__).read_bytes()),
    }
    native.write(output / "RESULT.json", result)
    print(
        json.dumps(
            {
                "path": str(output / "RESULT.json"),
                "sha256": native.sha((output / "RESULT.json").read_bytes()),
                "status": result["status"],
                "same_original_case_set": same_original,
                "before": {
                    key: first.get(key)
                    for key in (
                        "tests",
                        "failures",
                        "errors",
                        "skipped",
                        "actual_wait_returncode",
                    )
                },
                "after": {
                    key: second.get(key)
                    for key in (
                        "tests",
                        "failures",
                        "errors",
                        "skipped",
                        "actual_wait_returncode",
                    )
                },
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-result-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    replay(Path(args.source), args.source_result_sha256, Path(args.output))
