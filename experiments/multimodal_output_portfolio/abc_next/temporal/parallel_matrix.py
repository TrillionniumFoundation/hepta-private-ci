"""Two statically sharded, CPU-bounded processes execute frozen case matrices."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import resource
import time

from .audit import sha256, write_json
from .episodes import execute_case
from .facts import ACTIONS
from .policy import PolicyBundle
from .registration import verify_final_freeze
from .speech import SpeechBackend


def execute_shard(shard, source_rows, arguments, assigned_cpu):
    from .external import ExternalObserver
    os.sched_setaffinity(0, {assigned_cpu})
    args = argparse.Namespace(**arguments)
    backend, external = SpeechBackend(args.assets), ExternalObserver(args.external_assets)
    policies = PolicyBundle.load(args.policies)
    write_json(args.output / f"worker-{shard}-load.json", {
        "logical_shard": shard, "pid": os.getpid(), "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "backend": backend.load_receipt, "external": external.load_receipt,
        "policy_sha256": sha256(args.policies), "model_threads": 1,
        "vosk_thread_limit": "library default, process constrained to one CPU; OMP/BLAS environment set to 1"})
    rows = []
    with (args.output / f"shard-{shard}-cases.jsonl").open("x") as stream:
        for completed, (index, source) in enumerate(source_rows, start=1):
            for scenario in range(4):
                directory = args.output / f"source-{index:03d}" / f"scenario-{scenario}"
                execute_case(backend, source, scenario, directory, policies, ACTIONS, external)
                row = {"source_id": source["source_id"], "scenario": scenario,
                       "case_path": str(directory / "case.json"), "case_sha256": sha256(directory / "case.json"),
                       "logical_shard": shard, "worker_pid": os.getpid()}
                stream.write(json.dumps(row) + "\n")
                stream.flush()
                rows.append(row)
            print(json.dumps({"evaluation_shard": shard, "complete_groups_in_shard": completed,
                              "of": len(source_rows)}), flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assets", "external-assets", "freeze", "qualification", "policies", "final-protocol", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    verify_final_freeze(args.final_protocol, args.freeze, args.policies, args.qualification)
    qualification_protocol = json.loads((args.freeze / "qualification_protocol.json").read_text())
    if not json.loads(args.qualification.read_text())["passed"]:
        raise ValueError("Frozen observer qualification failed")
    for path, expected in ((args.assets / "manifest.json", qualification_protocol["tts_online_assets_sha256"]),
                           (args.external_assets / "manifest.json", qualification_protocol["external_assets_sha256"])):
        if sha256(path) != expected:
            raise ValueError("Qualified model identity changed")
    sources = json.loads((args.freeze / "sources.json").read_text())["roles"]["evaluation"]
    args.output.mkdir(parents=True, exist_ok=False)
    affinity = sorted(os.sched_getaffinity(0))
    if len(affinity) < 2:
        raise ValueError("Frozen two-worker design needs two available CPUs")
    assigned_cpus = affinity[-2:]
    load_start = os.getloadavg()
    write_json(args.output / "run_start.json", {"role": "evaluation", "sources": len(sources), "scenarios": 4,
               "actions": ACTIONS, "workers": 2, "worker_start_method": "spawn", "assigned_cpus": assigned_cpus,
               "case_assignment": "frozen source index modulo 2; all four scenarios stay on that logical shard",
               "final_protocol_sha256": sha256(args.final_protocol), "qualification_sha256": sha256(args.qualification),
               "source_manifest_sha256": sha256(args.freeze / "sources.json"), "load_average_start": load_start})
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(execute_shard, shard, [(index, source) for index, source in enumerate(sources)
                                                     if index % 2 == shard], vars(args), assigned_cpus[shard])
                   for shard in range(2)]
        shard_rows = [future.result() for future in futures]
    with (args.output / "cases.jsonl").open("x") as stream:
        for rows in shard_rows:
            for row in rows:
                stream.write(json.dumps(row) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu_ns = int(1e9 * (child_after.ru_utime + child_after.ru_stime - child_before.ru_utime - child_before.ru_stime))
    report = {"role": "evaluation", "source_groups": len(sources), "cases": len(sources) * 4, "paths": len(sources) * 4 * len(ACTIONS),
              "whole_process_before_report": {"wall_ns": time.perf_counter_ns() - started,
                                             "cpu_ns": time.process_time_ns() - cpu + child_cpu_ns},
              "child_process_cpu_ns": child_cpu_ns, "workers": 2, "assigned_cpus": assigned_cpus,
              "load_average_start": load_start, "load_average_end": os.getloadavg(),
              "case_index_sha256": sha256(args.output / "cases.jsonl"),
              "worker_loads": [json.loads(path.read_text()) for path in sorted(args.output.glob("worker-*-load.json"))],
              "cost_scope": "actual parent plus child CPU including startup; summed per-case wall is worker occupancy, not global elapsed time"}
    write_json(args.output / "run_complete.json", report)
    print(json.dumps({"complete": True, "source_groups": len(sources), "paths": report["paths"],
                      "whole_process_before_report": report["whole_process_before_report"]}))


if __name__ == "__main__":
    main()
