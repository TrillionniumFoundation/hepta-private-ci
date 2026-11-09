"""Execute frozen development controls in separate local Git clones.

This measures complete terminal recipes, not just retrieval rankings. Local
clones isolate tracked source; they are not a sandbox for external effects or
shared caches. Results never admit confirmation, adoption or scientific benefit.
"""

import argparse
import copy
from contextlib import chdir
import hashlib
import os
from pathlib import Path
import resource
import time

from ndu_real_runtime import subprocess_supervisor

from .contracts import digest, load, read_bound, require, validate_task, write_new
from .memory import initial_state, validate_state
from .runner import run

ARMS = ("candidate", "no_update", "bm25", "fixed_expert")


def _usage():
    own = resource.getrusage(resource.RUSAGE_SELF)
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.monotonic(), own.ru_utime + own.ru_stime, child.ru_utime + child.ru_stime


def _costs(start):
    end = _usage()
    return dict(
        zip(
            ("wall_seconds", "process_cpu_seconds", "reaped_child_cpu_seconds"),
            (after - before for before, after in zip(start, end)),
        ),
        peak_memory_bytes=None,
        energy_joules=None,
        financial_cost=None,
    )


def _released(state, receipt, corpus):
    validate_state(state, corpus)
    if state["updates"] == 0:
        require(state == initial_state(corpus), "noncanonical initial state")
        require(receipt is None, "initial state cannot claim a training receipt")
        return
    require(type(receipt) is dict, "updated state requires its original result")
    checkpoint = receipt.get("released_checkpoint")
    require(
        receipt.get("schema") == "hepta.repo-mdv.dev-result.v1"
        and receipt.get("terminal") == "proved"
        and receipt.get("corpus_sha256") == digest(corpus)
        and type(checkpoint) is dict
        and checkpoint.get("state_digest") == digest(state)
        and receipt.get("state_after_digest") == digest(state),
        "unreleased or mismatched development state",
    )


def compare(
    task,
    corpus,
    output,
    *,
    parent,
    candidate,
    candidate_receipt,
    fixed_document,
    parent_receipt=None,
    arm_order=ARMS,
):
    """Compare one immediate private-memory update; never train evaluation arms."""
    started = _usage()
    validate_task(task, corpus)
    require(task.get("learn_on_success") is False, "comparison cannot train")
    _released(parent, parent_receipt, corpus)
    _released(candidate, candidate_receipt, corpus)
    require(
        candidate["updates"] == parent["updates"] + 1
        and candidate["parent_sha256"] == digest(parent)
        and candidate_receipt.get("state_before_digest") == digest(parent)
        and candidate_receipt.get("training_updates_consumed") == 1
        and candidate_receipt.get("feedback_sha256") == candidate["last_feedback_sha256"],
        "candidate must be the immediate child of the frozen no-update state",
    )
    require(
        candidate_receipt.get("task_id") != task["task_id"],
        "comparison requires a different successor task",
    )
    require(
        len(arm_order) == len(ARMS) and set(arm_order) == set(ARMS),
        "freeze exactly one execution of every arm",
    )
    require(
        fixed_document in {d["id"] for d in corpus["documents"]},
        "fixed expert requires an existing frozen document",
    )
    source = Path(task["workspace"])
    require(
        source.is_absolute() and source.is_dir() and source.resolve() == source,
        "explicit local source required",
    )
    require(not task["source"].get("before_status", ""), "clean source required")
    # A recipe naming the original source would defeat per-arm clone isolation.
    require(
        not any(
            str(source) in arg
            for steps in task["recipes"].values()
            for step in steps
            for arg in step["argv"]
        ),
        "recipe directly references the original workspace",
    )
    output = Path(output)
    require(
        output.is_absolute()
        and not output.exists()
        and not output.resolve().is_relative_to(source),
        "create-only output must be outside the original workspace",
    )
    output.mkdir(parents=True, exist_ok=False)
    (output / "preparation").mkdir()
    preparation, arms = [], {}
    policies = {
        "candidate": {"kind": "learned"},
        "no_update": {"kind": "learned"},
        "bm25": {"kind": "bm25"},
        "fixed_expert": {"kind": "fixed", "document_id": fixed_document},
    }
    frozen = {
        "schema": "hepta.repo-mdv.development-comparison-plan.v1",
        "task": task,
        "corpus_sha256": digest(corpus),
        "parent_state_sha256": digest(parent),
        "candidate_state_sha256": digest(candidate),
        "candidate_result_sha256": digest(candidate_receipt),
        "parent_result_sha256": None if parent_receipt is None else digest(parent_receipt),
        "arm_order": list(arm_order),
        "policies": policies,
        "setup_timeout_seconds_per_command": 120,
        "execution_budget_per_arm": task["budget"],
        "split": "development",
        "confirmation_admitted": False,
        "fixed_encoder": candidate["encoder"],
        "trainable_object": "private_lexical_association_weights",
        "driver_source_sha256": hashlib.sha256(read_bound(__file__)).hexdigest(),
        "clone_object_store": "shared_with_original_repository",
        "fixed_expert_tuning_verified": False,
    }
    plan_sha = write_new(output / "plan.json", frozen)

    def git(args, cwd):
        prefix = output / "preparation" / f"git-{len(preparation):02d}"
        command = ["git", *args]
        row = {"argv": command, "cwd": str(cwd)}
        preparation.append(row)
        write_new(prefix.with_suffix(".intent.json"), row)
        before = _usage()
        with prefix.with_suffix(".stdout").open("xb") as stdout:
            with prefix.with_suffix(".stderr").open("xb") as stderr:
                with chdir(cwd):
                    row.update(
                        subprocess_supervisor.run_logged(
                            command, stdout=stdout, stderr=stderr, timeout=120, env=dict(os.environ)
                        )
                    )
        row["costs"] = _costs(before)
        row["logs"] = {}
        for stream in ("stdout", "stderr"):
            raw = read_bound(prefix.with_suffix("." + stream), subprocess_supervisor.STREAM_LIMIT)
            row["logs"][stream] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        write_new(prefix.with_suffix(".result.json"), row)
        require(
            row["error"] is None and row["cleanup_complete"] and row["returncode"] == 0,
            "source preparation or readback failed; original logs retained",
        )
        return read_bound(prefix.with_suffix(".stdout")).decode()

    errors = []
    source_verified = False
    try:
        expected = task["source"]["head"] + "\n" + task["source"]["tree"] + "\n"
        require(git(["rev-parse", "HEAD", "HEAD^{tree}"], source) == expected, "source identity mismatch")
        require(git(["status", "--porcelain=v1", "--untracked-files=all"], source) == "", "source is not clean")
        for arm in arm_order:
            arm_start = _usage()
            directory = output / arm
            directory.mkdir()
            workspace = directory / "workspace"
            record = {"terminal": "unknown", "result": None, "error": None}
            arms[arm] = record
            try:
                git(["clone", "--shared", "--no-checkout", "--", str(source), str(workspace)], source)
                git(["checkout", "--detach", task["source"]["head"]], workspace)
                arm_task = copy.deepcopy(task)
                arm_task["workspace"] = str(workspace)
                result = run(
                    arm_task,
                    corpus,
                    directory / "execution",
                    state=candidate if arm == "candidate" else parent,
                    state_receipt=candidate_receipt if arm == "candidate" else parent_receipt,
                    policy=policies[arm],
                )
                record.update(terminal=result["terminal"], result={
                    "path": f"{arm}/execution/result.json",
                    "sha256": hashlib.sha256(read_bound(directory / "execution" / "result.json")).hexdigest(),
                    "selected_document": result.get("selected_document"),
                    "state_before_digest": result["state_before_digest"],
                    "state_after_digest": result["state_after_digest"],
                    "training_updates_consumed": result["training_updates_consumed"],
                })
            except Exception as error:
                record["error"] = {"type": type(error).__name__, "message": str(error)}
            record["costs"] = _costs(arm_start)
            write_new(directory / "receipt.json", record)
            if preparation and preparation[-1].get("cleanup_complete") is not True:
                raise ValueError("unresolved preparation cleanup; later arms not started")
        require(git(["rev-parse", "HEAD", "HEAD^{tree}"], source) == expected, "source identity changed")
        require(git(["status", "--porcelain=v1", "--untracked-files=all"], source) == "", "source changed during comparison")
        source_verified = True
    except Exception as error:
        errors.append({"type": type(error).__name__, "message": str(error)})
    report = {
        "schema": "hepta.repo-mdv.development-comparison-result.v1",
        "plan_sha256": plan_sha,
        "preparation": preparation,
        "arms": arms,
        "registered_arms": list(arm_order),
        "unstarted_arms": [arm for arm in arm_order if arm not in arms],
        "source_unchanged_verified": source_verified,
        "terminal_comparison_complete": source_verified and len(arms) == len(ARMS)
        and all(row["terminal"] in {"proved", "refuted"} for row in arms.values()),
        "errors": errors,
        "costs": _costs(started),
        "cost_scope": "whole compare call through final readback, excluding final report serialization; preparation/arm/tool windows are nested and not additive",
        "complete_end_to_end_cost_established": False,
        "independent_evaluation": False,
        "confirmation_admitted": False,
        "scientific_qualified": False,
        "production_qualified": False,
        "formal_adoption_receipt": None,
    }
    write_new(output / "comparison.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("task", "corpus", "parent", "candidate", "candidate-receipt", "fixed-document", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--parent-receipt")
    parser.add_argument("--arm-order", nargs=4, choices=ARMS, default=ARMS)
    args = parser.parse_args()
    report = compare(
        load(args.task), load(args.corpus), args.output,
        parent=load(args.parent), candidate=load(args.candidate),
        candidate_receipt=load(args.candidate_receipt),
        parent_receipt=load(args.parent_receipt) if args.parent_receipt else None,
        fixed_document=args.fixed_document, arm_order=args.arm_order,
    )
    print("complete" if report["terminal_comparison_complete"] else "unresolved")
    return 0 if report["terminal_comparison_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
