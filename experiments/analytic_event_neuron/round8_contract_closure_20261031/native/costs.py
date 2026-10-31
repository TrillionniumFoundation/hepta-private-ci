"""Measure actual frozen native+broker deployment, without the Python reference oracle.

Select all head-1 nominal cases from the completed qualification manifest. Each
of the 60 frozen models is measured in mean/hard mode and continuous/cold restart
execution. Timing never selects a model or changes a policy.
"""
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import random
import resource
import statistics
import time

from ...round7.broker import BrokerClient
from ...round7.data import task_configuration
from ...round7.task import State
from ..native_policy import NativePolicy


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def child_cpu():
    value = resource.getrusage(resource.RUSAGE_CHILDREN)
    return value.ru_utime + value.ru_stime


def process_record(native):
    return dict(pid=native.ready["pid"], cpu_seconds=native.child_cpu_seconds,
        model_load_nanos=native.ready["model_load_nanos"], owner_open_nanos=native.ready["recovery_nanos"],
        startup_roundtrip_nanos=native.startup_roundtrip_nanos, exit_code=native.process.returncode)


def deploy(case, args, folder, restart):
    folder.mkdir(parents=True)
    wall, cpu, children = time.perf_counter(), time.process_time(), child_cpu()
    broker = None
    native = None
    processes, records = [], []
    setup_started = time.perf_counter_ns()
    try:
        broker = BrokerClient(folder / "artifacts")
        response = broker.start(8103100 + case["fit"] * 100, task_configuration(case["fit"], "nominal"))
        if not response.get("ok"):
            raise AssertionError(response)
        setup_nanos = time.perf_counter_ns() - setup_started
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
        broker.close()
        broker = None
        parent_cpu, all_children = time.process_time() - cpu, child_cpu() - children
        native_cpu = sum(p["cpu_seconds"] for p in processes)
        total_wall = time.perf_counter() - wall
        stages = defaultdict(int)
        for record in records:
            prediction = record["prediction"]
            receipt = prediction["native_receipt"]
            for key, value in prediction["costs"].items():
                stages[key] += value
            for key in ("native_runtime_nanos", "persistence_nanos", "complete_owner_nanos", "durable_bytes_written"):
                stages[key] += receipt[key]
            stages["request_roundtrip_nanos"] += prediction["prediction_ns"]
            stages["broker_roundtrip_nanos"] += round(record["result"]["client_roundtrip_seconds"] * 1e9)
            stages["broker_source_io_nanos"] += round(record["result"]["info"]["broker_io"]["source_io_seconds"] * 1e9)
            if "artifact" in record["result"]:
                stages["broker_terminal_io_nanos"] += round(record["result"]["artifact"]["artifact_io_seconds"] * 1e9)
        inference = sum(stages[key] for key in ("encode_nanos", "cdf_transition_nanos", "ctmc_transition_nanos",
                                              "propagate_nanos", "sample_nanos", "readout_nanos"))
        stages["native_runtime_outside_model_nanos"] = stages["native_runtime_nanos"] - inference
        stages["transport_serialization_scheduling_nanos"] = stages["request_roundtrip_nanos"] - stages["complete_owner_nanos"]
        stages["model_load_nanos"] = sum(p["model_load_nanos"] for p in processes)
        stages["owner_open_nanos"] = sum(p["owner_open_nanos"] for p in processes)
        stages["cold_recovery_nanos"] = sum(p["owner_open_nanos"] for p in processes[1:])
        stages["startup_roundtrip_nanos"] = sum(p["startup_roundtrip_nanos"] for p in processes)
        stages["broker_setup_nanos"] = setup_nanos
        if case["mode"] == "direct":
            stages["identity_transition_nanos"] = stages["cdf_transition_nanos"]
            stages["cdf_transition_nanos"] = 0
        return dict(case=case, restarted=restart, processes=processes, records=records,
            stages=dict(stages), parent_cpu_seconds=parent_cpu, native_cpu_seconds=native_cpu,
            broker_cpu_seconds=all_children - native_cpu, all_child_cpu_seconds=all_children,
            full_cpu_seconds=parent_cpu + all_children, full_wall_seconds=total_wall,
            final_state=state.to_dict(), actions=[r["action"] for r in records],
            utility=records[-1]["result"]["artifact"]["output"]["utility"],
            quality=records[-1]["result"]["artifact"]["output"]["terminal_quality"])
    finally:
        if native is not None: native.close()
        if broker is not None: broker.close()


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    build = json.loads(args.build_report.read_text())
    qualification = json.loads((args.qualification / "REPORT.json").read_text())
    if sha(args.binary) != build["binary_sha256"] or sha(args.binary) != qualification["binary_sha256"]:
        raise ValueError("qualified native binary identity mismatch")
    registration = json.loads((args.qualification / "REGISTERED.json").read_text())
    cases = [(i, row) for i, row in enumerate(registration["cases"]) if row["head"] == 1 and row["condition"] == 0]
    for _, case in cases:
        if sha(case["model"]) != case["model_sha256"]:
            raise ValueError("frozen model changed")
    expected = {}
    with gzip.open(args.qualification / "RAW.jsonl.gz", "rt") as stream:
        for index, line in enumerate(stream):
            if index // 2 in {i for i, _ in cases} and index % 2 == 0:
                row = json.loads(line)
                expected[index // 2] = ([r["action"] for r in row["records"]], row["final_state"])
    jobs = [(i, row, restart) for i, row in cases for restart in (False, True)]
    random.Random(831001).shuffle(jobs)
    manifest = dict(schema="hepta.native-cost-plan.v1", qualification_sha256=sha(args.qualification / "REPORT.json"),
        binary_sha256=sha(args.binary), jobs=[dict(index=i, case=row, restarted=r) for i, row, r in jobs],
        timings="Actual native+broker+adapter execution only; no PyTorch model or oracle imported by this runner.")
    (args.output / "REGISTERED.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    groups, results = defaultdict(list), []
    try:
        with gzip.open(args.output / "RAW.jsonl.gz", "wt") as stream:
            for ordinal, (index, case, restart) in enumerate(jobs):
                result = deploy(case, args, args.output / "runs" / f"case_{index:04d}_{int(restart)}", restart)
                if (result["actions"], result["final_state"]) != expected[index]:
                    raise AssertionError(("cost run changed qualified behavior", index, restart))
                result["qualified_behavior_exact"] = True
                stream.write(json.dumps(result, sort_keys=True) + "\n")
                stream.flush()
                groups[(case["mode"], case["stage"], case["deployment"], restart)].append(result)
                results.append(result)
                if ordinal % 40 == 0: print(json.dumps(dict(completed=ordinal + 1, total=len(jobs))), flush=True)
        summary = []
        for (mode, stage, deployment, restart), rows in sorted(groups.items()):
            keys = sorted({key for row in rows for key in row["stages"]})
            metrics = {key: statistics.mean(row[key] for row in rows) for key in
                ("parent_cpu_seconds", "native_cpu_seconds", "broker_cpu_seconds", "full_cpu_seconds", "full_wall_seconds", "utility", "quality")}
            summary.append(dict(mode=mode, stage=stage, deployment=deployment, restarted=restart, fits=len(rows),
                mean=metrics, mean_stages={key: statistics.mean(row["stages"].get(key, 0) for row in rows) for key in keys},
                decisions_mean=statistics.mean(len(row["records"]) for row in rows),
                processes_mean=statistics.mean(len(row["processes"]) for row in rows)))
        report = dict(schema="hepta.native-cost-profile.v1", passed=True, executions=len(results),
            qualified_behaviors_exact=len(results), groups=summary,
            measured_deployment_cpu_seconds=sum(row["full_cpu_seconds"] for row in results),
            measured_deployment_wall_seconds=sum(row["full_wall_seconds"] for row in results),
            campaign_parent_cpu_seconds=time.process_time(), campaign_child_cpu_seconds=child_cpu(),
            parent_overhead_outside_rollouts_seconds=time.process_time() - sum(row["parent_cpu_seconds"] for row in results),
            registered_sha256=sha(args.output / "REGISTERED.json"), raw_sha256=sha(args.output / "RAW.jsonl.gz"),
            timing_scope="per-rollout complete adapter+Rust+broker CPU, including artifact setup, native startup/model load, all requested actions, writes/readbacks and closure. The campaign parent CPU additionally includes driver import, qualification readback, registration, checks and evidence serialization.",
            overlap="Component nanoseconds are wall durations. inference stages are disjoint; native_runtime contains them; owner includes native_runtime and paired persistence. Startup includes load/open/IPC. The native-runtime remainder includes validation, sparse tick, serialization and journal IO and cannot be called pure commit CPU. Broker setup overlaps broker CPU. Never sum overlapping columns.",
            limitations="Five frozen fits per row; descriptive host measurements under shared load. No energy reading, no new trained-policy selection, no standalone whole-application import amortization assumption.",
            energy_joules=None, production_activation=False)
        (args.output / "REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps({key: report[key] for key in ("passed", "executions", "measured_deployment_cpu_seconds", "measured_deployment_wall_seconds")}))
    except BaseException as error:
        (args.output / "FAILURE.json").write_text(json.dumps(dict(error=repr(error), completed=len(results))) + "\n")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "build-report", "qualification", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    main(parser.parse_args())
