"""Bind a registered source cut to every attempted fixed-Reader evaluation arm.

This is a read-only research consistency check, not source authenticity, a model
run, a human correctness judgment, or a production/promotion issuer. The caller
must externally preregister and authenticate the capture and model artifacts.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from prospective_family_gate import admission

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SCHEMA = "hepta.memory.paired-source-cut-audit.v1"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical_sha(value):
    """Stable content commitment; a digest alone does not establish capture time."""
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def bind_contract(cut, plan, rows):
    """Enforce exact source-question-task roots across all preregistered arms."""
    source_audit = admission(cut)
    require(
        isinstance(plan, dict) and isinstance(rows, list),
        "paired experiment plan and attempts required",
    )
    cut_sha = canonical_sha(cut)
    require(
        plan.get("source_cut_sha256") == cut_sha,
        "evaluation plan bound to a different source cut",
    )
    cases = plan.get("cases")
    require(isinstance(cases, list), "evaluation cases missing")
    source_cases = {s["id"]: s for s in cut["sources"] if s["partition"] == "test"}
    case_map = {}
    for case in cases:
        require(
            isinstance(case, dict) and isinstance(case.get("id"), str),
            "typed task identity required",
        )
        require(case["id"] not in case_map, "duplicate evaluation task identity")
        case_map[case["id"]] = case
    require(
        len(case_map) == len(cases) and set(case_map) == set(source_cases),
        "test source census mismatch: skipped, inserted or duplicate task",
    )
    for case_id, registered in source_cases.items():
        case = case_map[case_id]
        for key, expected, reason in (
            ("family", registered["family"], "source-family mismatch"),
            ("kind", registered["kind"], "task-stratum mismatch"),
            ("snapshot_frozen_at", cut["frozen_at"], "snapshot epoch mismatch"),
            ("revealed_at", registered["exposed_at"], "task reveal time mismatch"),
            (
                "policy_snapshot_sha256",
                cut["policy_snapshot_sha256"],
                "policy was not frozen with registered source",
            ),
            (
                "knowledge_snapshot_sha256",
                cut["knowledge_snapshot_sha256"],
                "knowledge was not frozen with registered source",
            ),
            (
                "candidate_pool_sha256",
                registered.get("candidate_pool_sha256"),
                "candidate pool not bound to preregistration",
            ),
            (
                "question_sha256",
                registered.get("question_sha256"),
                "question identity not bound to preregistration",
            ),
        ):
            require(case.get(key) == expected, reason)
        require(
            all(
                isinstance(registered.get(x), str) and HEX64.fullmatch(registered[x])
                for x in ("question_sha256", "candidate_pool_sha256")
            ),
            "missing precommitted test question/candidate hash",
        )
    require(len(rows) == len(cases) * 12, "full attempted evaluation census required")
    for attempt in rows:
        require(isinstance(attempt, dict), "malformed attempted Reader row")
        task_id = attempt.get("task_id")
        require(
            isinstance(task_id, str) and task_id in source_cases,
            "unregistered evaluation task",
        )
        require(
            attempt.get("source_cut_sha256") == cut_sha,
            "attempt bound to a different source cut",
        )
        require(
            attempt.get("original_source_sha256")
            == source_cases[task_id]["source_digest"],
            "original evidence bytes differ from registered source",
        )
    return {
        "source_cut_sha256": cut_sha,
        "source_audit": source_audit,
        "test_families": len({s["family"] for s in source_cases.values()}),
        "bound_task_count": len(cases),
    }


def audit(cut, plan, rows):
    """Run both existing hard gates on an exactly bound complete attempt census."""
    from four_stage_evidence import prospective_guard

    bound = bind_contract(cut, plan, rows)
    study = prospective_guard(plan, rows)
    require(
        study["recorded_tasks"] == bound["bound_task_count"],
        "paired Reader study changed task census",
    )
    return dict(
        schema=SCHEMA,
        source_cut_sha256=bound["source_cut_sha256"],
        registered_source_families_unverified=bound["test_families"],
        paired_attempts=len(rows),
        by_arm=study["by_arm"],
        comparisons=study["paired_descriptive"],
        independent_source_capture_verified=False,
        task_reveal_time_externally_attested=False,
        original_model_inference_verification=False,
        program_execution_independently_attested=False,
        independent_human_semantics=False,
        learned_memory_gain_established=False,
        complete_cost_verified=False,
        production_accepted=False,
        decision="DENY_ALL",
    )


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, "duplicate JSON field")
        out[key] = value
    return out


def _deny_nonfinite(value):
    raise ValueError("nonfinite JSON constant " + value)


def read_pinned(path, expected_sha, limit):
    path = Path(path)
    require(
        isinstance(expected_sha, str) and HEX64.fullmatch(expected_sha),
        "external SHA256 pin required",
    )
    require(
        not path.is_symlink()
        and path.is_file()
        and all(not p.is_symlink() for p in path.parents)
        and 0 < path.stat().st_size <= limit,
        "bounded regular JSON input required",
    )
    data = path.read_bytes()
    require(
        hashlib.sha256(data).hexdigest() == expected_sha,
        "externally supplied original byte SHA mismatch",
    )
    return json.loads(
        data, object_pairs_hook=_unique_pairs, parse_constant=_deny_nonfinite
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cut", required=True, type=Path)
    parser.add_argument("--source-cut-sha256", required=True)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--attempts", required=True, type=Path)
    parser.add_argument("--attempts-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    cut = read_pinned(args.source_cut, args.source_cut_sha256, 32 * 1024 * 1024)
    plan = read_pinned(args.plan, args.plan_sha256, 16 * 1024 * 1024)
    rows = read_pinned(args.attempts, args.attempts_sha256, 64 * 1024 * 1024)
    result = audit(cut, plan, rows)
    require(
        not args.output.exists()
        and not args.output.is_symlink()
        and args.output.parent.is_dir()
        and not args.output.parent.is_symlink(),
        "refuse overwrite or unsafe output parent",
    )
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, sort_keys=True, indent=2, allow_nan=False)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    print(
        json.dumps(
            {"decision": result["decision"], "output": str(args.output)}, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
