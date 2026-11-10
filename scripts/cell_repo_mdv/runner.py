"""Run explicit development recipes against actual repository workspaces.

This is a small approved-recipe driver, not an autonomous patch author or an
independent evaluator. It emits unsigned evidence, never an adoption receipt.
"""

import argparse
from contextlib import chdir
import hashlib
import os
from pathlib import Path
import resource
import time

from ndu_real_runtime import span_meter, subprocess_supervisor

from .contracts import SHA, digest, load, read_bound, require, validate_task, write_new
from .memory import initial_state, retrieve, update, validate_state

ENV_KEYS = {
    "PATH",
    "RUSTUP_TOOLCHAIN",
    "CARGO_BUILD_JOBS",
    "CARGO_TARGET_DIR",
    "CARGO_NET_OFFLINE",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONPATH",
}


def child_cpu():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def bound_files(workspace, expected):
    require(
        type(expected) is dict and 1 <= len(expected) <= 32, "source file pins required"
    )
    rows = []
    for relative, sha in expected.items():
        path = Path(relative)
        require(
            not path.is_absolute() and ".." not in path.parts and SHA.fullmatch(sha),
            "invalid source pin",
        )
        target = workspace / path
        require(target.resolve().is_relative_to(workspace), "source escapes workspace")
        raw = read_bound(target, 16 * 1024 * 1024)
        actual = hashlib.sha256(raw).hexdigest()
        require(actual == sha, "source pin mismatch: " + relative)
        rows.append({"path": relative, "bytes": len(raw), "sha256": actual})
    return rows


def run(task, corpus, output, *, state=None, state_receipt=None, policy=None):
    validate_task(task, corpus)
    policy = {"kind": "learned"} if policy is None else dict(policy)
    require(
        policy in ({"kind": "learned"}, {"kind": "bm25"})
        or (
            set(policy) == {"kind", "document_id"}
            and policy["kind"] == "fixed"
            and policy["document_id"] in {d["id"] for d in corpus["documents"]}
        ),
        "unknown or unbound selection policy",
    )
    state = initial_state(corpus) if state is None else state
    validate_state(state, corpus)
    if state["updates"]:
        require(
            type(state_receipt) is dict
            and state_receipt.get("schema") == "hepta.repo-mdv.dev-result.v1",
            "updated state needs original development result",
        )
        require(
            state_receipt.get("terminal") == "proved"
            and state_receipt.get("released_checkpoint", {}).get("state_digest")
            == digest(state),
            "unreleased/failed state cannot be consumed",
        )
    workspace = Path(task["workspace"])
    require(
        workspace.is_absolute()
        and workspace.is_dir()
        and workspace.resolve() == workspace,
        "explicit real workspace required",
    )
    source = task["source"]
    require(
        all(
            isinstance(source.get(k), str) and len(source[k]) == 40
            for k in ("head", "tree")
        ),
        "source Git identity required",
    )
    env_overrides = task.get("environment", {})
    require(
        type(env_overrides) is dict and set(env_overrides) <= ENV_KEYS,
        "unsupported environment override",
    )
    require(
        all(type(v) is str for v in env_overrides.values()), "invalid environment value"
    )
    require(
        type(task.get("learn_on_success")) is bool,
        "explicit development learning mode required",
    )
    output = Path(output)
    require(output.is_absolute() and not output.exists(), "create-only output required")
    output.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, **env_overrides, "PYTHONDONTWRITEBYTECODE": "1"}
    operations, checks = [], []
    started, cpu_start = time.monotonic(), child_cpu()
    deadline = started + task["budget"]["wall_seconds"]
    before_digest = digest(state)
    report = {
        "schema": "hepta.repo-mdv.dev-result.v1",
        "task_id": task["task_id"],
        "lineage_group": task["lineage_group"],
        "split": "development",
        "task_sha256": digest(task),
        "corpus_sha256": digest(corpus),
        "declared_source": source,
        "workspace": str(workspace),
        "state_before_digest": before_digest,
        "state_updates_before": state["updates"],
        "operations": operations,
        "runtime_environment_overrides": env_overrides,
        "production_qualified": False,
        "scientific_qualified": False,
        "formal_adoption_receipt": None,
        "independent_evaluation": None,
        "state_use_mode": "development_direct_state",
        "selection_policy": policy,
        "baseline_executed": False,
        "terminal": "unknown",
        "residual_obligations": [],
        "driver_sources": {},
        "complete_end_to_end_cost_established": False,
    }
    for module in (span_meter, subprocess_supervisor):
        raw = read_bound(module.__file__)
        report["driver_sources"][module.__name__] = hashlib.sha256(raw).hexdigest()
    for name in ("runner.py", "contracts.py", "memory.py"):
        report["driver_sources"][name] = hashlib.sha256(
            read_bound(Path(__file__).with_name(name))
        ).hexdigest()
    with (output / "spans.jsonl").open("xb") as journal:

        def sink(raw):
            journal.write(raw)
            journal.flush()
            os.fsync(journal.fileno())

        meter = span_meter.SpanMeter(task["task_id"], event_sink=sink)

        def execute(argv, kind, timeout):
            require(
                len(operations) < task["budget"]["tool_calls"], "tool budget exhausted"
            )
            remaining = min(timeout, deadline - time.monotonic())
            require(
                remaining > subprocess_supervisor.CLEANUP_SECONDS,
                "wall budget exhausted",
            )
            number = len(operations)
            prefix = output / f"tool-{number:02d}"
            row = {
                "id": f"{task['task_id']}/tool/{number:02d}",
                "kind": kind,
                "argv": argv,
                "cwd": str(workspace),
                "status": "started",
            }
            operations.append(row)
            write_new(prefix.with_suffix(".intent.json"), row)
            cpu_before = child_cpu()
            with meter.span(
                f"tool-{number:02d}", "critic" if kind == "verify" else "planning"
            ) as scope:
                with (
                    prefix.with_suffix(".stdout").open("xb") as stdout,
                    prefix.with_suffix(".stderr").open("xb") as stderr,
                ):
                    with chdir(workspace):
                        supervision = subprocess_supervisor.run_logged(
                            argv,
                            stdout=stdout,
                            stderr=stderr,
                            timeout=remaining,
                            env=env,
                        )
                row.update(supervision)
                if supervision["error"] is not None:
                    scope.set_status("UNKNOWN")
                elif supervision["returncode"] != 0:
                    scope.set_status("FAILED")
            row["child_cpu_seconds"] = child_cpu() - cpu_before
            row["status"] = "observed"
            row["logs"] = {}
            for stream in ("stdout", "stderr"):
                path = prefix.with_suffix("." + stream)
                raw = read_bound(path, subprocess_supervisor.STREAM_LIMIT)
                row["logs"][stream] = {
                    "path": path.name,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            write_new(prefix.with_suffix(".result.json"), row)
            require(
                row["error"] is None and row["cleanup_complete"],
                "unresolved tool execution",
            )
            require(time.monotonic() <= deadline, "total task envelope exceeded")
            return row, prefix

        def identity(label):
            row, prefix = execute(
                ["git", "rev-parse", "HEAD", "HEAD^{tree}"], "identity", 10
            )
            require(row["returncode"] == 0, "Git identity failed")
            values = read_bound(prefix.with_suffix(".stdout")).decode().splitlines()
            require(values == [source["head"], source["tree"]], "Git identity changed")
            status, status_prefix = execute(
                ["git", "status", "--porcelain=v1", "--untracked-files=all"],
                "identity",
                10,
            )
            require(status["returncode"] == 0, "Git status failed")
            text = read_bound(status_prefix.with_suffix(".stdout")).decode()
            require(
                text == source.get(label + "_status", ""), "unplanned workspace changes"
            )
            report[label + "_source"] = {
                "head": values[0],
                "tree": values[1],
                "status": text,
                "file_pins": bound_files(workspace, source[label + "_pins"]),
            }

        try:
            with meter.attempt("development-task"):
                identity("before")
                with meter.span("retrieval", "encoder"):
                    baseline = retrieve(corpus, task["query"])
                    ranking = (
                        retrieve(corpus, task["query"], state)
                        if policy["kind"] == "learned"
                        else baseline
                    )
                    selected = (
                        policy["document_id"]
                        if policy["kind"] == "fixed"
                        else ranking[0]["document_id"]
                    )
                    report.update(
                        selected_document=selected,
                        ranking=ranking,
                        baseline_ranking=baseline,
                        development_state_consumed=policy["kind"] == "learned",
                        ranking_order_changed=[r["document_id"] for r in ranking]
                        != [r["document_id"] for r in baseline],
                        selected_document_changed=selected
                        != baseline[0]["document_id"],
                    )
                passed = True
                for step in task["recipes"][selected]:
                    row, prefix = execute(
                        step["argv"], step["kind"], step["timeout_seconds"]
                    )
                    if step["kind"] == "verify":
                        checks.append(row)
                    expected = step.get("expected_returncode", 0)
                    require(type(expected) is int, "invalid expected return code")
                    matched = row["returncode"] == expected
                    for stream, text in step.get("required_output", {}).items():
                        require(
                            stream in {"stdout", "stderr"}
                            and type(text) is str
                            and 0 < len(text) <= 4096,
                            "invalid required output",
                        )
                        matched &= text.encode() in read_bound(
                            prefix.with_suffix("." + stream),
                            subprocess_supervisor.STREAM_LIMIT,
                        )
                    if not matched:
                        passed = False
                        break
                identity("after")
                mandatory = bool(checks) and all(
                    row["returncode"] == 0 for row in checks
                )
                report["terminal"] = "proved" if passed and mandatory else "refuted"
                if report["terminal"] == "proved" and task["learn_on_success"]:
                    feedback = {
                        "task_id": task["task_id"],
                        "lineage_group": task["lineage_group"],
                        "split": "development",
                        "terminal": "proved",
                        "selected_document": selected,
                        "query_sha256": digest(task["query"]),
                        "mandatory_checks": checks,
                        "source": report["after_source"],
                        "all_tool_attempts_sha256": digest(operations),
                    }
                    write_new(output / "feedback.json", feedback)
                    with meter.span("memory-update", "shared"):
                        state = update(corpus, state, task["query"], selected, feedback)
                    report["feedback_sha256"] = digest(feedback)
                require(time.monotonic() <= deadline, "total task envelope exceeded")
        except Exception as error:
            report["terminal"] = "unknown"
            report["residual_obligations"].append(
                {"type": type(error).__name__, "message": str(error)}
            )
        report["state_after_digest"] = digest(state)
        report["state_updated"] = digest(state) != before_digest
        # A failure after fitting cannot release an updated checkpoint.
        if report["terminal"] != "proved" and report["state_updated"]:
            report["residual_obligations"].append(
                {"type": "UnreleasedState", "message": "task incomplete after fitting"}
            )
            report["released_checkpoint"] = None
        else:
            checkpoint_sha = write_new(output / "state.json", state)
            report["released_checkpoint"] = {
                "path": "state.json",
                "file_sha256": checkpoint_sha,
                "state_digest": digest(state),
            }
        raw = meter.finish("SUCCEEDED" if report["terminal"] == "proved" else "UNKNOWN")
    replay = span_meter.verify_record(raw)
    require(replay["valid"] and replay["complete_record"], "invalid raw meter")
    if time.monotonic() > deadline:
        report["terminal"] = "unknown"
        report["released_checkpoint"] = None
        report["residual_obligations"].append(
            {
                "type": "BudgetExceeded",
                "message": "including checkpoint/accounting; any retained state is not released",
            }
        )
    report["training_updates_consumed"] = (
        state["updates"] - report["state_updates_before"]
    )
    report["baseline_executed"] = policy["kind"] == "bm25" and report["terminal"] in {
        "proved",
        "refuted",
    }
    report["raw_spans_sha256"] = replay["record_sha256"]
    report["costs"] = {
        "envelope_wall_seconds": replay["envelope"]["inclusive_wall_ns"] / 1e9,
        "emitting_process_cpu_seconds": replay["envelope"]["inclusive_process_cpu_ns"]
        / 1e9,
        "reaped_child_cpu_seconds": child_cpu() - cpu_start,
        "nested_tool_windows_not_additive": True,
        "scope": "admitted development process window; import/input validation, final serialization and external preparation excluded",
        "peak_memory_bytes": None,
        "energy_joules": None,
        "financial_cost": None,
    }
    write_new(output / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("task", "corpus", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--state")
    parser.add_argument("--state-receipt")
    args = parser.parse_args()
    if args.state:
        require(
            args.state_receipt is not None,
            "state file requires its original result receipt",
        )
        receipt = load(args.state_receipt)
        require(
            receipt.get("released_checkpoint", {}).get("file_sha256")
            == hashlib.sha256(read_bound(args.state)).hexdigest(),
            "checkpoint file byte mismatch",
        )
    else:
        require(args.state_receipt is None, "orphan state receipt")
        receipt = None
    result = run(
        load(args.task),
        load(args.corpus),
        args.output,
        state=load(args.state) if args.state else None,
        state_receipt=receipt,
    )
    print(
        result["terminal"],
        result["state_after_digest"],
        result["costs"]["envelope_wall_seconds"],
    )
    return 0 if result["terminal"] == "proved" else 2


if __name__ == "__main__":
    raise SystemExit(main())
