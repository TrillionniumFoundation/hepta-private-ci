"""Measured initialization, supervisor ownership, and separate terminal publication."""

import argparse
import importlib
import os
from pathlib import Path
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from operational.parameter_field_recovery07.process import (  # noqa: E402
    EPISODE,
    GIB,
    PREFIX,
    Terminated,
    checked,
    descriptor,
    load_config,
    read,
    regular_tree,
    require,
    run_owned,
    source_check,
    write,
)
from operational.parameter_field_recovery07.job_queue import LABELS, ORDER  # noqa: E402

RUN = Path("/work/execution07")
CONFIG = RUN / "ops/registrations/initial/PIPELINE_CONFIG.json"


def health_callback(deadline, baseline=None):
    resource = importlib.import_module(PREFIX + "resource_v2")
    initial = resource.memory_profile() if baseline is None else baseline

    def health():
        require(
            time.monotonic() < deadline,
            "Measured operational process deadline exhausted",
        )
        current = resource.memory_profile()
        require(
            current["limit"] == 8 * GIB
            and all(current[key] <= initial[key] for key in ("oom", "oom_kill")),
            "Registered eight-GiB cgroup or OOM baseline differs",
        )

    health()
    return health


def require_measurement(directory, expected_argv=None):
    directory = Path(directory)
    closure, waited = (
        read(directory / "CLOSURE.json"),
        read(directory / "001.WAIT4.json"),
    )
    require(
        closure.get("all_returned_direct_children_reaped") is True
        and closure.get("accounting_complete_for_attempted_direct_workers") is True
        and closure.get("attempt_count") == closure.get("returned_children") == 1
        and len(closure.get("children", [])) == 1
        and waited.get("exit_code") == 0
        and closure["children"][0].get("wait4") == waited,
        "A complete successful single-owner wait4 measurement is required",
    )
    require(
        closure.get("binding", {}).get("execution_episode") == EPISODE,
        "Measurement belongs to another episode",
    )
    if expected_argv is not None:
        require(
            closure["attempts"][0]["argv"] == expected_argv,
            "Measured entrypoint argv differs",
        )
    return {
        "wait4": descriptor(directory / "001.WAIT4.json"),
        "closure": descriptor(directory / "CLOSURE.json"),
    }


def measured(name, argv, directory, log, cwd, health, binding):
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with Path(log).open("xb"):
        pass
    result = run_owned(
        argv,
        directory=directory,
        cwd=str(cwd),
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
        log=log,
        health=health,
        binding={"name": name, **binding},
    )
    require(result["exit_code"] == 0, name + " did not succeed; evidence retained")
    return require_measurement(directory, argv)


def initialize(source_commit):
    require(
        ROOT == Path("/work/source")
        and str(Path(sys.executable)) == "/opt/runtime/venv/bin/python",
        "Initialization must run in its canonical qualified container",
    )
    directory = RUN / "initialization_measurement"
    directory.mkdir(parents=True, exist_ok=False)
    empty = directory / "empty_cwd"
    empty.mkdir()
    program = descriptor(ROOT / "operational/parameter_field_recovery07/initialize.py")
    base = ["--source-commit", source_commit]
    plan = write(
        directory / "INITIALIZATION_PLAN.json",
        {
            "schema": "hepta.execution07.initialization-plan.1",
            "execution_episode": EPISODE,
            "source_commit": source_commit,
            "program": program,
            "python": sys.executable,
            "base_argv": base,
            "generated_config_path": str(CONFIG),
        },
    )
    argv = [
        sys.executable,
        "-B",
        program["path"],
        *base,
        "--initialization-intent",
        plan["path"],
        "--initialization-intent-sha256",
        plan["sha256"],
    ]
    result = measured(
        "initialization",
        argv,
        directory / "children",
        directory / "initialize.log",
        empty,
        health_callback(time.monotonic() + 3600),
        {"initialization_intent": plan},
    )
    checked(plan)
    config = read(CONFIG)
    require(
        config.get("initialization_intent") == plan,
        "Initialization plan was not bound into configuration",
    )
    write(
        directory / "COMPLETE.json",
        {
            "schema": "hepta.execution07.initialization-measurement.1",
            "complete": True,
            "execution_episode": EPISODE,
            "initialization_intent": plan,
            "pipeline_config": descriptor(CONFIG),
            **result,
        },
    )


def initialization_receipts(config):
    plan_desc = config["initialization_intent"]
    plan = read(plan_desc)
    require(
        plan.get("execution_episode") == EPISODE
        and plan["source_commit"] == config["source_commit"]
        and plan["python"] == config["python"],
        "Initialization provenance differs",
    )
    argv = [
        plan["python"],
        "-B",
        plan["program"]["path"],
        *plan["base_argv"],
        "--initialization-intent",
        plan_desc["path"],
        "--initialization-intent-sha256",
        plan_desc["sha256"],
    ]
    result = require_measurement(Path(plan_desc["path"]).parent / "children", argv)
    checked(plan["program"])
    return result


def run(config, item):
    initialization_receipts(config)
    source_check(config)
    directory = Path(config["ops_root"]) / "outer_wait4"
    argv = [
        config["python"],
        "-B",
        str(ROOT / "operational/parameter_field_recovery07/supervisor.py"),
        "--config",
        item["path"],
        "--expected-config-sha256",
        item["sha256"],
    ]
    result = measured(
        "supervisor",
        argv,
        directory,
        directory.parent / "supervisor.log",
        config["empty_cwd"],
        health_callback(time.monotonic() + 12 * 3600),
        {"pipeline_config": item},
    )
    complete = read(Path(config["ops_root"]) / "COMPLETE.json")
    require(
        complete.get("complete") is True and complete.get("pipeline_config") == item,
        "Supervisor returned without a complete bound pipeline seal",
    )
    return result


def primary_closure(config, item):
    ops = Path(config["ops_root"])
    complete_desc = descriptor(ops / "COMPLETE.json")
    complete = read(complete_desc)
    require(
        complete.get("schema") == "hepta.fullstudy.pipeline-completion.4"
        and complete.get("complete") is True
        and complete.get("execution_episode") == EPISODE
        and complete.get("pipeline_config") == item
        and complete.get("jobs") == ORDER
        and complete.get("jobs_executed_here") == 14
        and complete.get("jobs_imported") == 0
        and complete.get("imported_jobs") == []
        and complete.get("scientific_jobs_executed_here") == ORDER,
        "Primary closure is not the exact fresh fourteen-job episode",
    )
    stages = complete["durable_stages"]
    require(
        len(stages) == 17 and [stage["binding"]["label"] for stage in stages] == LABELS,
        "Primary closure lacks seventeen ordered ACKs",
    )
    for index, row in enumerate(stages):
        ack = read(row["ack"])
        expected = {
            "execution_episode": EPISODE,
            "sequence": index + 1,
            "label": LABELS[index],
            "pipeline_config": item,
            "completed_jobs": ORDER[: min(index + 1, 14)],
            "previous_ack": stages[index - 1]["ack"] if index else None,
        }
        require(
            row["binding"] == ack["binding"] == expected
            and ack.get("readback", {}).get("all_sha256_and_bytes_match") is True,
            "Primary closure ACK ancestry or readback differs",
        )
    argv = [
        config["python"],
        "-B",
        str(ROOT / "operational/parameter_field_recovery07/supervisor.py"),
        "--config",
        item["path"],
        "--expected-config-sha256",
        item["sha256"],
    ]
    outer = require_measurement(ops / "outer_wait4", argv)
    initial = initialization_receipts(config)
    return complete, complete_desc, outer, initial


def publication_child(config, item):
    complete, complete_desc, outer, initial = primary_closure(config, item)
    ops = Path(config["ops_root"])
    paths = {
        "ops/COMPLETE.json": checked(complete_desc),
        "metadata/PIPELINE_CONFIG.json": checked(item),
    }
    for directory in (
        ops / "outer_wait4",
        Path(config["initialization_intent"]["path"]).parent,
    ):
        for path in regular_tree(directory):
            paths[
                (
                    "ops/outer_wait4/"
                    if directory.name == "outer_wait4"
                    else "initialization_measurement/"
                )
                + path.relative_to(directory).as_posix()
            ] = path
    for row in complete["durable_stages"]:
        for value in (row["ack"], row["manifest"]):
            path = checked(value)
            paths["ops/" + path.relative_to(ops).as_posix()] = path
        for path in Path(row["ack"]["path"]).parent.glob("*.json"):
            paths["ops/" + path.relative_to(ops).as_posix()] = path
    for relative in ("STATUS.json", "supervisor.log"):
        paths["ops/" + relative] = ops / relative
    binding = {
        "execution_episode": EPISODE,
        "sequence": 18,
        "label": "terminal_metadata",
        "pipeline_config": item,
        "completed_jobs": ORDER,
        "previous_ack": complete["durable_stages"][-1]["ack"],
    }
    transport = importlib.import_module(
        "operational.parameter_field_recovery07.artifact_transport"
    )
    result = transport.archive_terminal_metadata(
        paths,
        binding,
        ops / "terminal_archive",
        health_check=health_callback(time.monotonic() + 3600),
    )
    source_check(config)
    write(
        ops / "PUBLICATION.json",
        {
            "schema": "hepta.execution07.terminal-publication.1",
            "execution_episode": EPISODE,
            "pipeline_config": item,
            "primary_completion": complete_desc,
            "supervisor_measurement": outer,
            "initialization_measurement": initial,
            "terminal_archive": result,
            "publication_process_exit_cost_pending": True,
        },
    )


def publish(config, item):
    primary_closure(config, item)
    ops = Path(config["ops_root"])
    argv = [
        config["python"],
        "-B",
        str(Path(__file__).resolve()),
        "publish-child",
        "--config",
        item["path"],
        "--expected-config-sha256",
        item["sha256"],
    ]
    cost = measured(
        "terminal-publication",
        argv,
        ops / "terminal_publication_measurement",
        ops / "terminal-publication.log",
        config["empty_cwd"],
        health_callback(time.monotonic() + 3600),
        {"pipeline_config": item},
    )
    publication = read(ops / "PUBLICATION.json")
    checked(publication["terminal_archive"]["ack"])
    write(
        ops / "TERMINAL_CLOSURE.json",
        {
            "schema": "hepta.execution07.terminal-closure.1",
            "complete": True,
            "execution_episode": EPISODE,
            "pipeline_config": item,
            "publication": descriptor(ops / "PUBLICATION.json"),
            "publication_measurement": cost,
            "terminal_ack": publication["terminal_archive"]["ack"],
            "this_closure_in_its_referenced_terminal_archive": False,
            "later_delivery_scope": "A separate final workflow artifact must retain terminal closure and postseal review.",
            "cost_scope": "Initialization, supervisor and terminal-publication child wait4 are separate inclusive intervals; nested ledgers are not additive.",
            "outer_driver_final_serialization_cpu_is_not_in_publication_child_wait4": True,
        },
    )


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    initial = sub.add_parser("measure-init")
    initial.add_argument("--source-commit", required=True)
    for mode in ("run", "publish", "publish-child"):
        target = sub.add_parser(mode)
        target.add_argument("--config", required=True)
        target.add_argument("--expected-config-sha256", required=True)
    args = parser.parse_args()

    def terminated(signum, frame):
        raise Terminated("Execution07 terminal process received signal " + str(signum))

    signal.signal(signal.SIGTERM, terminated)
    if args.mode == "measure-init":
        initialize(args.source_commit)
    else:
        config, item = load_config(args.config, args.expected_config_sha256)
        {"run": run, "publish": publish, "publish-child": publication_child}[args.mode](
            config, item
        )


if __name__ == "__main__":
    main()
