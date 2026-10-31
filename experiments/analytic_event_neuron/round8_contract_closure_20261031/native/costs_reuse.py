"""Same frozen cost jobs, one persistent original broker, fresh native owner per job.

The original cold run and exact job order remain fixed. The first real episode
pays Python broker startup; shutdown is included. No warmup episode is discarded.
"""
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import time

from ...round7.broker import BrokerClient
from ...round7.data import task_configuration
from ...round7.task import State
from ..native_policy import NativePolicy
from .costs import child_cpu, process_record


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def deploy(case, index, restart, broker, args):
    folder = args.output / "runs" / f"case_{index:04d}_{int(restart)}"
    folder.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter(), time.process_time()
    records, processes = [], []
    native = None
    setup = time.perf_counter_ns()
    try:
        response = broker.start(8103100 + case["fit"] * 100, task_configuration(case["fit"], "nominal"))
        if not response.get("ok"):
            raise AssertionError(response)
        setup_nanos = time.perf_counter_ns() - setup
        state = State.from_dict(response["state"])
        native = NativePolicy(case["model"], binary=args.binary, owner_dir=folder / "owner",
            seed=9103100 + case["fit"], head=1, deployment=case["deployment"])
        while not state.terminated:
            action, prediction = native.act(state)
            result = broker.step(action)
            if not result.get("ok"):
                raise AssertionError(result)
            records.append(dict(action=action, prediction=prediction, result=result))
            state = State.from_dict(result["state"])
            if restart and len(records) == 1 and not state.terminated:
                snapshot = native.snapshot()
                native.close()
                processes.append(process_record(native))
                native = NativePolicy(case["model"], binary=args.binary, owner_dir=folder / "owner",
                    seed=9103100 + case["fit"], head=1, deployment=case["deployment"],
                    ack=snapshot["acknowledged_pair_sha256"])
        native.close()
        processes.append(process_record(native))
        return dict(case=case, index=index, restarted=restart, processes=processes, records=records,
            broker_pid=broker.process.pid, broker_setup_nanos=setup_nanos,
            parent_cpu_seconds=time.process_time() - cpu,
            native_cpu_seconds=sum(p["cpu_seconds"] for p in processes),
            deployment_wall_seconds=time.perf_counter() - start,
            actions=[r["action"] for r in records], final_state=state.to_dict(),
            artifact_output=records[-1]["result"]["artifact"]["output"],
            artifact_sha256=records[-1]["result"]["artifact"]["sha256"])
    finally:
        if native is not None:
            native.close()


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    plan = json.loads((args.baseline / "REGISTERED.json").read_text())
    baseline = json.loads((args.baseline / "REPORT.json").read_text())
    if not baseline["passed"] or sha(args.binary) != plan["binary_sha256"]:
        raise ValueError("qualified baseline/binary required")
    if sha(args.baseline / "RAW.jsonl.gz") != baseline["raw_sha256"]:
        raise ValueError("baseline cost raw changed")
    expected = []
    with gzip.open(args.baseline / "RAW.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            expected.append((row["case"], row["restarted"], row["actions"], row["final_state"],
                row["records"][-1]["result"]["artifact"]["output"],
                row["records"][-1]["result"]["artifact"]["sha256"]))
    if len(expected) != len(plan["jobs"]):
        raise ValueError("baseline job count mismatch")
    for job in plan["jobs"]:
        if sha(job["case"]["model"]) != job["case"]["model_sha256"]:
            raise ValueError("frozen model changed")
    registration = dict(schema="hepta.broker-reuse-cost-plan.v1", baseline_registration_sha256=sha(args.baseline / "REGISTERED.json"),
        baseline_report_sha256=sha(args.baseline / "REPORT.json"), baseline_raw_sha256=sha(args.baseline / "RAW.jsonl.gz"),
        jobs=plan["jobs"], intervention="Only reuse the original BrokerClient process; fresh native owner and same native restart flag/model per job.",
        accounting="The first real job pays broker import/startup. Final broker close is charged. No discarded warmup. Whole-campaign CPU includes imports and evidence work.")
    (args.output / "REGISTERED.json").write_text(json.dumps(registration, indent=2, sort_keys=True) + "\n")
    cpu, wall, children = time.process_time(), time.perf_counter(), child_cpu()
    broker = BrokerClient(args.output / "artifacts")
    construction_cpu, construction_wall = time.process_time() - cpu, time.perf_counter() - wall
    results = []
    try:
        with gzip.open(args.output / "RAW.jsonl.gz", "wt") as stream:
            for ordinal, job in enumerate(plan["jobs"]):
                row = deploy(job["case"], job["index"], job["restarted"], broker, args)
                actual = (row["case"], row["restarted"], row["actions"], row["final_state"], row["artifact_output"], row["artifact_sha256"])
                if actual != expected[ordinal]:
                    raise AssertionError(("broker reuse changed qualified effects", ordinal))
                row["baseline_behavior_and_artifact_exact"] = True
                stream.write(json.dumps(row, sort_keys=True) + "\n")
                stream.flush()
                results.append(row)
                if ordinal % 40 == 0:
                    print(json.dumps(dict(completed=ordinal + 1, total=len(plan["jobs"]))), flush=True)
        close_cpu, close_wall = time.process_time(), time.perf_counter()
        broker.close()
        close_cpu, close_wall = time.process_time() - close_cpu, time.perf_counter() - close_wall
        child_total = child_cpu() - children
        native_total = sum(row["native_cpu_seconds"] for row in results)
        parent_total = sum(row["parent_cpu_seconds"] for row in results) + construction_cpu + close_cpu
        full_cpu = child_total + parent_total
        full_wall = sum(row["deployment_wall_seconds"] for row in results) + construction_wall + close_wall
        groups = defaultdict(list)
        for row in results:
            case = row["case"]
            groups[(case["mode"], case["stage"], case["deployment"], row["restarted"])].append(row)
        summaries = []
        for (mode, stage, deployment, restart), rows in sorted(groups.items()):
            summaries.append(dict(mode=mode, stage=stage, deployment=deployment, restarted=restart, fits=len(rows),
                mean_parent_cpu_seconds=sum(r["parent_cpu_seconds"] for r in rows) / len(rows),
                mean_native_cpu_seconds=sum(r["native_cpu_seconds"] for r in rows) / len(rows),
                mean_deployment_wall_seconds=sum(r["deployment_wall_seconds"] for r in rows) / len(rows),
                mean_broker_start_nanos=sum(r["broker_setup_nanos"] for r in rows) / len(rows),
                broker_cpu_per_episode=None))
        report = dict(schema="hepta.broker-reuse-cost-result.v1", passed=True, executions=len(results),
            exact_behavior_and_terminal_artifact_matches=len(results), broker_process_count=1,
            native_process_count=sum(len(r["processes"]) for r in results), broker_pid=broker.process.pid,
            first_real_episode_broker_start_nanos=results[0]["broker_setup_nanos"],
            broker_construction_cpu_seconds=construction_cpu, broker_construction_wall_seconds=construction_wall,
            broker_close_cpu_seconds=close_cpu, broker_close_wall_seconds=close_wall,
            native_cpu_seconds=native_total, broker_cpu_seconds=child_total - native_total,
            parent_deployment_cpu_seconds=parent_total, measured_deployment_cpu_seconds=full_cpu,
            measured_deployment_wall_seconds=full_wall,
            baseline_deployment_cpu_seconds=baseline["measured_deployment_cpu_seconds"],
            baseline_deployment_wall_seconds=baseline["measured_deployment_wall_seconds"],
            cpu_reduction_fraction=1 - full_cpu / baseline["measured_deployment_cpu_seconds"],
            wall_reduction_fraction=1 - full_wall / baseline["measured_deployment_wall_seconds"],
            campaign_parent_cpu_seconds=time.process_time(), campaign_child_cpu_seconds=child_cpu(),
            baseline_campaign_cpu_seconds=baseline["campaign_parent_cpu_seconds"] + baseline["campaign_child_cpu_seconds"],
            parent_overhead_outside_deployment_seconds=time.process_time() - parent_total,
            groups=summaries, raw_sha256=sha(args.output / "RAW.jsonl.gz"), registered_sha256=sha(args.output / "REGISTERED.json"),
            scientific_scope="A process-lifecycle optimization measured on the same frozen policies and 240 exact ordered tasks. It is not a faster cell kernel, fewer model calls, or learned-policy efficacy result.",
            accounting="Broker CPU is measured from the actual child rusage after final closure and charged once in full; no arbitrary per-episode allocation. Native processes remain distinct and their CPU is also fully charged. Per-row wall includes the first actual startup when applicable. Per-campaign totals include driver import, baseline readback, checks and evidence serialization.",
            warmup_excluded=False, energy_joules=None, production_activation=False)
        (args.output / "REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps({key: report[key] for key in ("passed", "executions", "measured_deployment_cpu_seconds", "measured_deployment_wall_seconds", "cpu_reduction_fraction", "wall_reduction_fraction")}))
    except BaseException as error:
        (args.output / "FAILURE.json").write_text(json.dumps(dict(error=repr(error), completed=len(results))) + "\n")
        raise
    finally:
        if broker.process.poll() is None:
            broker.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "baseline", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    main(parser.parse_args())
