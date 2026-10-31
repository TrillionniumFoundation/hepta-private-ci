"""One measured command for fresh initialization, full execution, delivery and review."""

import argparse
import os
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from operational.parameter_field_recovery07 import common as c  # noqa: E402
from operational.parameter_field_recovery07 import initialize, terminal  # noqa: E402
from operational.parameter_field_recovery07.process import run_owned  # noqa: E402

RUN = Path("/work/execution07")
CONFIG = RUN / "ops/registrations/initial/PIPELINE_CONFIG.json"


def source_guard(commit):
    contract = c.read(c.OWN / "INPUT_CONTRACT.json")
    c.need(
        ROOT == Path(contract["source_root"])
        and str(Path(sys.executable)) == contract["python"],
        "Bootstrap requires the committed canonical qualified container",
    )
    closure = initialize.committed_closure(commit, contract)
    c.need(
        all(
            "operational/parameter_field_recovery07/" + name in closure
            for name in ("bootstrap.py", "terminal.py", "postseal/review.py")
        ),
        "Lifecycle source closure is incomplete",
    )
    return closure


def child(commit):
    closure = source_guard(commit)
    terminal.initialize(commit)
    config_item = c.descriptor(CONFIG)
    config, unchanged = c.load_config(config_item["path"], config_item["sha256"])
    c.need(
        unchanged == config_item and config["source_files"] == closure,
        "Initialized source closure changed",
    )
    semantic_argv = [
        config["python"],
        "-B",
        str(c.OWN / "semantic_preflight.py"),
        "--config",
        config_item["path"],
        "--expected-config-sha256",
        config_item["sha256"],
    ]
    semantic = terminal.measured(
        "original-semantic-preflight",
        semantic_argv,
        RUN / "ops/registrations/initial/semantic_measurement",
        RUN / "ops/registrations/initial/semantic-preflight.log",
        config["empty_cwd"],
        terminal.health_callback(time.monotonic() + 3600),
        {"pipeline_config": config_item},
    )
    supervisor = terminal.run(config, config_item)
    terminal.publish(config, config_item)
    terminal_item = c.descriptor(RUN / "ops/TERMINAL_CLOSURE.json")
    argv = [
        config["python"],
        "-B",
        str(c.OWN / "postseal/review.py"),
        "--config",
        config_item["path"],
        "--expected-config-sha256",
        config_item["sha256"],
        "--terminal-closure",
        terminal_item["path"],
        "--expected-terminal-closure-sha256",
        terminal_item["sha256"],
        "--output",
        str(RUN / "postseal"),
        "--execute-post-seal",
    ]
    review_measurement = terminal.measured(
        "postseal-review",
        argv,
        RUN / "postseal_measurement",
        RUN / "postseal.log",
        config["empty_cwd"],
        terminal.health_callback(time.monotonic() + 3600),
        {"pipeline_config": config_item, "terminal_closure": terminal_item},
    )
    review_item = c.descriptor(RUN / "postseal/COMPLETE.json")
    result = c.bound(review_item)
    c.need(
        result.get("schema") == "hepta.execution07.postseal-review.1"
        and result.get("complete") is True
        and result.get("execution_episode") == c.EPISODE
        and result.get("pipeline_config") == config_item
        and result.get("terminal_closure") == terminal_item,
        "Postseal review did not seal its actual inputs",
    )
    c.committed_sources(c.SOURCE, commit, closure)
    c.write_new(
        RUN / "pipeline_measurement/CHILD_COMPLETE.json",
        {
            "schema": "hepta.execution07.lifecycle-child.1",
            "complete": True,
            "execution_episode": c.EPISODE,
            "pipeline_config": config_item,
            "primary_completion": c.descriptor(RUN / "ops/COMPLETE.json"),
            "original_semantic_preflight": c.descriptor(
                RUN / "ops/registrations/initial/SEMANTIC_PREFLIGHT.json"
            ),
            "semantic_preflight_measurement": semantic,
            "supervisor_measurement": supervisor,
            "terminal_closure": terminal_item,
            "postseal_completion": review_item,
            "postseal_measurement": review_measurement,
            "scientific_review_disposition": result["status"],
            "scientific_efficacy_adoption": "not_assessed",
            "this_child_final_wait4_pending": True,
            "delivery_scope": "The final workflow operational artifact must deliver this child receipt and its subsequently closed outer wait4.",
        },
    )


def run(commit):
    started, cpu = time.monotonic(), time.process_time()
    closure = source_guard(commit)
    c.need(
        not any(
            (RUN / name).exists()
            for name in (
                "ops",
                "raw",
                "raw_cas",
                "pipeline_measurement",
                "initialization_measurement",
            )
        ),
        "The registered lifecycle is fresh and cannot resume or overwrite evidence",
    )
    directory = RUN / "pipeline_measurement"
    directory.mkdir(parents=True, exist_ok=False)
    empty = directory / "empty_cwd"
    empty.mkdir()
    log = directory / "bootstrap.log"
    log.touch(exist_ok=False)
    argv = [
        sys.executable,
        "-B",
        str(Path(__file__).resolve()),
        "--source-commit",
        commit,
        "--child",
    ]
    program = c.descriptor(Path(__file__).resolve())
    c.write_new(
        directory / "PLAN.json",
        {
            "schema": "hepta.execution07.lifecycle-plan.1",
            "execution_episode": c.EPISODE,
            "source_commit": commit,
            "program": program,
            "argv": argv,
            "registered_scientific_jobs": list(c.ORDER),
            "source_files": closure,
            "imported_jobs": [],
            "automatic_retry": False,
            "scientific_supervisor_deadline_seconds": 12 * 3600,
            "outer_lifecycle_deadline_seconds": 16 * 3600,
            "outer_additional_scope": "Initialization, original semantic preflight, terminal publication and postseal have separate one-hour bounds; the original scientific supervisor deadline remains twelve hours.",
        },
    )
    result = run_owned(
        argv,
        directory=directory / "children",
        cwd=str(empty),
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
        log=log,
        health=terminal.health_callback(time.monotonic() + 16 * 3600),
        binding={
            "source_commit": commit,
            "program": program,
            "lifecycle_plan": c.descriptor(directory / "PLAN.json"),
        },
    )
    c.need(
        result["exit_code"] == 0,
        "Lifecycle child failed; partial evidence remains and no retry is authorized",
    )
    measurement = terminal.require_measurement(directory / "children", argv)
    completed_item = c.descriptor(directory / "CHILD_COMPLETE.json")
    completed = c.bound(completed_item)
    c.need(
        completed.get("complete") is True
        and completed.get("execution_episode") == c.EPISODE,
        "Lifecycle child returned without closure",
    )
    c.committed_sources(c.SOURCE, commit, closure)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {
        "schema": "hepta.execution07.lifecycle-completion.1",
        "complete": True,
        "execution_episode": c.EPISODE,
        "source_commit": commit,
        "child_completion": completed_item,
        "pipeline_measurement": measurement,
        "pipeline_config": completed["pipeline_config"],
        "primary_completion": completed["primary_completion"],
        "terminal_closure": completed["terminal_closure"],
        "postseal_completion": completed["postseal_completion"],
        "postseal_measurement": completed["postseal_measurement"],
        "scientific_review_disposition": completed["scientific_review_disposition"],
        "engineering_status": "ALL_REGISTERED_STAGES_AND_REVIEW_CLOSED",
        "scientific_adoption": "not_assessed",
        "inclusive_pipeline_cpu_seconds": result["cpu_seconds"],
        "inclusive_pipeline_wall_seconds": result["wall_seconds"],
        "pipeline_peak_rss_bytes": result["peak_rss_bytes"],
        "launcher_self_cpu_seconds_before_final_receipt": time.process_time() - cpu,
        "launcher_waited_children_cpu_seconds_cumulative": children.ru_utime
        + children.ru_stime,
        "launcher_wall_seconds_before_final_receipt": time.monotonic() - started,
        "cost_scope": "The pipeline direct-child wait4 includes actual initialization, supervisor, transport, terminal publication, review and descendant waits. Those nested stage measurements are attribution, not additional totals. Launcher self CPU and its final serialization are outside the child interval; cumulative waited-child CPU overlaps the pipeline and must not be added.",
        "environment_preparation_cost": "Installation/download wall time comes from actual workflow steps; preparation CPU is unknown and outside this episode.",
        "history_cost_complete": False,
        "final_serialization_cpu_not_individually_measured": True,
        "final_workflow_artifact_required": True,
        "this_receipt_not_claimed_in_prior_18_artifacts": True,
    }
    item = c.write_new(directory / "COMPLETE.json", receipt)
    return {
        "completion": item,
        "engineering_status": receipt["engineering_status"],
        "scientific_review_disposition": receipt["scientific_review_disposition"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        result = child(args.source_commit) if args.child else run(args.source_commit)
        if result is not None:
            print(c.encode(result).decode(), end="")
        return 0
    except BaseException as error:
        failed = {
            "schema": "hepta.execution07.lifecycle-failure.1",
            "complete": False,
            "execution_episode": c.EPISODE,
            "error_type": type(error).__name__,
            "message": str(error)[:8192],
            "automatic_retry": False,
            "partial_evidence_preserved": True,
        }
        target = (
            RUN
            / "pipeline_measurement"
            / ("CHILD_FAILED.json" if args.child else "FAILED.json")
        )
        if target.parent.is_dir() and not target.exists():
            c.write_new(target, failed)
        print(c.encode(failed).decode(), file=sys.stderr, end="")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
