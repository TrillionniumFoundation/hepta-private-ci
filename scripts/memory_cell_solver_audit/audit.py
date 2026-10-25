"""Read-only audit of a committed hosted code-solver evidence archive."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def identity(path):
    raw = Path(path).read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def read(path):
    return json.loads(Path(path).read_text())


def complete_semantics(report, required):
    expected = Counter(required)
    return bool(report) and (
        report.get("tests_run") == len(required)
        and report.get("unittest_success") is True
        and all(
            Counter(report.get(key, [])) == expected
            for key in ("discovered", "started", "completed")
        )
        and Counter(row["id"] for row in report.get("outcomes", [])) == expected
        and all(row.get("status") == "success" for row in report.get("outcomes", []))
    )


def audit(evidence, expected):
    evidence = Path(evidence).resolve()
    root = evidence / "run"
    checks, trajectories = [], []

    def check(name, passed, detail=None):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    result = {
        "schema": "hepta.memory-cell.repair-hosted-audit.v1",
        "checks": checks,
        "trajectories": trajectories,
        "model_queries_run_by_auditor": 0,
        "training_updates_by_auditor": 0,
        "production_accepted": False,
        "independent_future_cases": 0,
        "strong_rag_qualified": False,
    }
    try:
        check(
            "no_symlink_in_extracted_evidence",
            not any(p.is_symlink() for p in evidence.rglob("*")),
        )
        check(
            "hosted_checkout_identity",
            (evidence / "source.txt").read_text().splitlines()
            == [expected["head"], expected["tree"]],
        )
        protocol, freeze = read(root / "protocol.json"), read(root / "freeze.json")
        check(
            "frozen_protocol_bytes",
            identity(root / "protocol.json") == freeze["protocol"],
        )
        check(
            "registered_before_model_calls",
            freeze["model_calls_so_far"] == freeze["training_updates"] == 0,
        )
        check(
            "exact_committed_source_head",
            protocol["source_head"] == expected["head"] == freeze["source_head"],
        )
        check(
            "executed_source_inventory",
            protocol["source_files"]
            == expected["files"]
            == read(root / "source-before.json"),
        )
        check(
            "registered_tasks_and_arms",
            protocol["task_order"] == ["ruff", "codec"]
            and protocol["arms"] == ["no_history", "retrieval"],
        )
        check(
            "staged_model_manifest_bytes",
            identity(root / "model-manifest.json") == protocol["staged_model_manifest"],
        )
        model = read(root / "model-manifest.json")
        check("staged_model_definition", model == expected["model"])
        acquisition = read(evidence / "model-acquisition.json")
        check(
            "acquired_weight_identity",
            acquisition["identity"] == model["file"]
            and acquisition["model_calls"] == acquisition["training_updates"] == 0,
        )
        summary = read(root / "summary.json")
        check(
            "study_binds_protocol",
            summary["protocol_sha256"] == identity(root / "protocol.json")["sha256"]
            and summary["source_head"] == expected["head"],
        )
        check(
            "study_source_unchanged",
            summary.get("source_unchanged") is True
            and read(root / "source-after.json") == expected["files"],
        )
        planned = {
            (task, arm) for task in protocol["task_order"] for arm in protocol["arms"]
        }
        observed = {(row["task"], row["arm"]) for row in summary["rows"]}
        unexecuted = {
            (row["task"], row["arm"]) for row in summary["unexecuted_trajectories"]
        }
        check(
            "all_registered_denominators_retained",
            observed.isdisjoint(unexecuted)
            and observed | unexecuted == planned
            and len(observed) == len(summary["rows"]),
        )
        costs = Counter()
        successes = Counter()
        for task in protocol["task_order"]:
            path = root / "tasks" / task
            qualification = read(path / "qualification/qualification.json")
            profile = read(path / "runtime-profile.json")
            check(
                task + ":qualified_runtime",
                qualification["accepted"] is True
                and qualification["tests_run"] == {"ruff": 9, "codec": 6}[task]
                and all(
                    qualification[key] == 0 for key in ("errors", "failures", "skips")
                ),
            )
            check(
                task + ":profile_hash",
                identity(path / "runtime-profile.json")["sha256"]
                == protocol["tasks"][task]["runtime_profile"]["sha256"],
            )
            check(
                task + ":profile_contract",
                profile["task_contract_sha256"] == expected["contract_hashes"][task],
            )
            spec = expected["contracts"][task]
            fixture = {
                str(p.relative_to(path / "fixture")): identity(p)
                for p in (path / "fixture").rglob("*")
                if p.is_file()
            }
            check(task + ":original_source_inventory", fixture == spec["files"])
            check(
                task + ":frozen_input_bytes",
                identity(path / "task-input.json")
                == {
                    k: protocol["tasks"][task]["input"][k] for k in ("bytes", "sha256")
                },
            )
        for row in summary["rows"]:
            task, arm = row["task"], row["arm"]
            name = task + "-" + arm
            path = root / "trajectories" / name
            trajectory = {"task": task, "arm": arm, "accepted": row["accepted"]}
            trajectories.append(trajectory)
            if "result" not in row:
                check(
                    name + ":missing_result_not_success",
                    not row["accepted"] and not row["execution_valid"],
                )
                continue
            local = read(path / "result.json")
            check(
                name + ":result_bytes",
                identity(path / "result.json") == row["result_file"]
                and local == row["result"],
            )
            starts = list(path.glob("generation-*/query-start.json"))
            responses = list(path.glob("generation-*/response.json"))
            totals = Counter()
            current_files = dict(
                read(root / "tasks" / task / "task-input.json")["files"]
            )
            for response_path in sorted(responses):
                generation = response_path.parent
                response, request = (
                    read(response_path),
                    read(generation / "request.json"),
                )
                usage = response["usage"]
                totals.update(
                    {
                        "prompt_tokens": usage["prompt_tokens"],
                        "generated_tokens": usage["completion_tokens"],
                    }
                )
                check(
                    name + ":prompt_usage:" + generation.name,
                    all(
                        type(usage[k]) is int and usage[k] >= 0
                        for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                    )
                    and usage["prompt_tokens"] == len(request["prompt_token_ids"])
                    and usage["completion_tokens"]
                    <= protocol["generation"]["max_new_tokens"]
                    and usage["total_tokens"]
                    == usage["prompt_tokens"] + usage["completion_tokens"]
                    and usage["total_tokens"]
                    <= protocol["generation"]["context_tokens"],
                )
                messages = request["messages"]
                model_input = json.loads(messages[1]["content"])
                frozen_input = read(root / "tasks" / task / "task-input.json")
                retrieval = read(root / "tasks" / task / (arm + "-retrieval.json"))
                check(
                    name + ":source_only_input:" + generation.name,
                    model_input["task"] == frozen_input["task"]
                    and model_input["current_files"] == current_files
                    and model_input["retrieved_history"] == retrieval["documents"]
                    and (arm != "no_history" or not retrieval["documents"]),
                )
                candidate_path = (
                    path
                    / generation.name.replace("generation-", "attempt-")
                    / "candidate.json"
                )
                if candidate_path.exists():
                    candidate = read(candidate_path)
                    edits = json.loads(response["choices"][0]["message"]["content"])[
                        "edits"
                    ]
                    proposed = dict(current_files)
                    for edit in edits:
                        value = proposed[edit["path"]]
                        if edit["old"] is None:
                            if value is not None:
                                raise ValueError("candidate created an existing file")
                            proposed[edit["path"]] = edit["new"]
                        else:
                            if not edit["old"] or value.count(edit["old"]) != 1:
                                raise ValueError(
                                    "candidate edit is not a single exact span"
                                )
                            proposed[edit["path"]] = value.replace(
                                edit["old"], edit["new"], 1
                            )
                    reconstructed = dict(frozen_input["files"])
                    reconstructed.update(
                        {item["path"]: item["content"] for item in candidate["files"]}
                    )
                    check(
                        name + ":actual_model_edits:" + generation.name,
                        reconstructed == proposed,
                    )
                    current_files = proposed
            check(
                name + ":model_cost_counts",
                local["model_queries_started"] == len(starts)
                and local["model_queries_returned"] == len(responses)
                and local["prompt_tokens"] == totals["prompt_tokens"]
                and local["generated_tokens"] == totals["generated_tokens"],
            )
            check(
                name + ":attempt_budget",
                len(starts) <= protocol["generation"]["maximum_calls"]
                and len(local["attempts"]) <= protocol["generation"]["maximum_calls"]
                and local["training_updates"] == 0,
            )
            costs.update(totals)
            costs["calls"] += len(starts)
            accepted_attempts = []
            for attempt in local["attempts"]:
                attempt_root = path / f"attempt-{attempt['number']:02d}"
                check(
                    name + ":attempt_receipt:" + str(attempt["number"]),
                    read(attempt_root / "attempt.json") == attempt,
                )
                if "gate_result" not in attempt:
                    check(
                        name + ":no_gate_no_success:" + str(attempt["number"]),
                        not attempt["accepted"],
                    )
                    continue
                gate_root = attempt_root / "gate"
                gate = read(gate_root / "result.json")
                check(
                    name + ":gate_bytes:" + str(attempt["number"]),
                    identity(gate_root / "result.json") == attempt["gate_result"]
                    and gate["accepted"] == attempt["accepted"],
                )
                if gate["accepted"]:
                    accepted_attempts.append(attempt["number"])
                    if task == "ruff":
                        semantic = complete_semantics(
                            gate.get("semantic"),
                            expected["contracts"][task]["test_ids"],
                        )
                        lint = read(gate_root / "candidate-lint/process.json")
                        check(
                            name + ":actual_76_id_success",
                            semantic
                            and lint["returncode"] == 0
                            and not lint["timeout"]
                            and read(gate_root / "candidate-lint/stdout") == [],
                        )
                    else:
                        profiles = gate["profiles"]
                        check(
                            name + ":actual_21_id_success",
                            complete_semantics(
                                profiles["provisioned"]["semantic"],
                                expected["contracts"][task]["test_ids"],
                            ),
                        )
                        for profile in ("missing_ffmpeg", "missing_ffprobe"):
                            process = read(
                                gate_root / profile / "execution/process.json"
                            )
                            check(
                                name + ":actual_refusal:" + profile,
                                isinstance(process["returncode"], int)
                                and process["returncode"] > 0
                                and not process["timeout"]
                                and profiles[profile]["missing_tool_refused"] is True,
                            )
            check(
                name + ":task_success_requires_valid_execution",
                row["accepted"]
                == bool(
                    local["accepted"]
                    and local["execution_valid"]
                    and row["process"]["returncode"] == 0
                    and not row["process"]["timed_out"]
                ),
            )
            if row["accepted"]:
                check(
                    name + ":stopped_on_actual_success",
                    accepted_attempts == [local["attempts"][-1]["number"]]
                    and local["stop_reason"] == "first_actual_task_success",
                )
                successes[arm] += 1
            trajectory.update(
                model_calls=len(starts),
                prompt_tokens=totals["prompt_tokens"],
                generated_tokens=totals["generated_tokens"],
                stop_reason=local["stop_reason"],
            )
        for arm in protocol["arms"]:
            check(
                arm + ":task_denominator",
                summary["task_success"][arm]["registered_total"] == 2
                and summary["task_success"][arm]["correct"] == successes[arm],
            )
        check(
            "aggregate_observed_costs",
            summary["recorded_model_calls_started"] == costs["calls"]
            and summary["recorded_prompt_tokens"] == costs["prompt_tokens"]
            and summary["recorded_generated_tokens"] == costs["generated_tokens"],
        )
        result.update(
            task_success=summary["task_success"],
            observed_model_costs=dict(costs),
            study_execution_complete=not summary.get("execution_error")
            and not unexecuted,
        )
        check(
            "final_format_and_clean_source",
            (evidence / "final-format.log").is_file()
            and (evidence / "post-test-format.patch").stat().st_size == 0
            and (evidence / "final-worktree-status.txt").stat().st_size == 0,
        )
    except Exception as error:
        check("complete_readable_evidence", False, f"{type(error).__name__}: {error}")
    result["accepted"] = bool(checks) and all(row["passed"] for row in checks)
    result["checks_passed"] = sum(row["passed"] for row in checks)
    result["checks_total"] = len(checks)
    result["scope"] = (
        "Receipt, source-pin, token and original-test consistency audit; no independent hardware attestation or hostile-candidate proof."
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.evidence, read(args.expected))
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {key: result[key] for key in ("accepted", "checks_passed", "checks_total")}
        )
    )
    raise SystemExit(0 if result["accepted"] else 1)
