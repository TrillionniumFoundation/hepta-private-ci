"""Serial full-owner replay of the frozen R14 actors with two controllers."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from threadpoolctl import threadpool_limits

from ..task_aligned_r14_20261101.execution import execute, make_tapes
from ..task_aligned_r14_20261101.models import GenericHMM, restore
from ..task_aligned_r14_20261101.task import TaskModel
from ..unified_cell_r12_20261031.task_value import ExactBeliefDP
from .attainability import R14_FREEZE, digest
from .planner import BatchedBeliefDP


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def run_replay(run, output):
    """Freeze all inputs before metering; abort on any policy/record mismatch."""
    started, wall = time.process_time(), time.perf_counter()
    run, output = Path(run), Path(output)
    if output.exists():
        raise FileExistsError("Retain existing replay evidence; use a new directory")
    config = json.loads((HERE / "REPLAY_PROTOCOL.json").read_text())
    original_protocol_path = HERE.parent / "task_aligned_r14_20261101/PROTOCOL.json"
    original = json.loads(original_protocol_path.read_text())
    freeze_path = run / "FREEZE.json"
    if digest(freeze_path) != R14_FREEZE:
        raise ValueError("Expected the published R14 candidate freeze")
    freeze = json.loads(freeze_path.read_text())
    if config["fit_seeds"] != original["fit_seeds"] or config["episodes_per_case"] != original["confirmation_episodes_per_domain"]:
        raise ValueError("This replay must retain the full original fit and episode set")
    executed_modules = ("__init__.py", "attainability.py", "planner.py", "replay.py")
    sources = {str((HERE / name).relative_to(ROOT)): digest(HERE / name) for name in executed_modules}
    sources[str((HERE / "REPLAY_PROTOCOL.json").relative_to(ROOT))] = digest(HERE / "REPLAY_PROTOCOL.json")
    for name, expected in freeze["sources"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Original scientific source changed: " + name)
    artifacts = {}
    for relative, expected in freeze["artifacts"].items():
        if relative.endswith(".json") and (run / relative).is_file():
            if digest(run / relative) != expected:
                raise ValueError("Original checkpoint changed: " + relative)
            artifacts[relative] = expected
    output.mkdir(parents=True)
    manifest = dict(schema="hcsn.r15.replay.freeze.v1", sources=sources,
                    original_sources=freeze["sources"], artifacts=artifacts,
                    original_freeze_sha256=digest(freeze_path), protocol=config,
                    frozen_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    python=platform.python_version(), platform=platform.platform(),
                    numpy=np.__version__, scipy=scipy.__version__)
    write_new(output / "FREEZE.json", manifest)
    cases = []
    for seed in config["fit_seeds"]:
        directory = run / str(seed)
        common = restore(json.loads((directory / "common_model.json").read_text())["model"]).build_cell()
        selected = freeze["selected_ordinary"][str(seed)]
        ordinary = (GenericHMM(common) if selected == "generic_hmm" else
                    restore(json.loads((directory / (selected + ".json")).read_text())["final_model"]))
        hx = restore(json.loads((directory / "hx_distribution.json").read_text())["final_model"])
        for domain in config["domains"]:
            preparation_started = time.process_time()
            world = TaskModel()
            for dt in original[domain + "_durations"]:
                world.transition(dt)
            tapes = make_tapes(seed + original["confirmation_seed_offsets"][domain],
                               config["episodes_per_case"], original[domain + "_durations"])
            common_preparation_cpu = time.process_time() - preparation_started
            for arm, actor in (("B", ordinary), ("D", hx)):
                identity = f"{seed}_{domain}_{arm}"
                metering = []
                expected_records = None
                expected_values = None
                record_hash = None
                rng = np.random.default_rng(seed + (domain == "ood") * 1000 + (arm == "D") * 10)
                for repeat in range(config["repeats"]):
                    order = list(rng.permutation(config["controllers"]))
                    for position, name in enumerate(order):
                        planner_type = ExactBeliefDP if name == "reference" else BatchedBeliefDP
                        # execute() independently clones this into a cold planner.
                        planner = planner_type(common, reset_cost=common.reset_cost,
                                               latency_price=common.latency_price)
                        result = execute(world, actor, planner, tapes)
                        raw = canonical_bytes(result["records"])
                        observed_hash = hashlib.sha256(raw).hexdigest()
                        if expected_records is None:
                            expected_records = result["records"]
                            expected_values = result["episode_values"]
                            record_hash = observed_hash
                            packed = gzip.compress(raw, mtime=0)
                            (output / (identity + ".records.json.gz")).write_bytes(packed)
                        if (result["records"] != expected_records
                                or result["episode_values"] != expected_values or observed_hash != record_hash):
                            write_new(output / (identity + ".MISMATCH.json"),
                                      dict(repeat=repeat, controller=name, result=result))
                            raise ArithmeticError("Controller changed actual episode records: " + identity)
                        metering.append(dict(repeat=repeat, order=position, controller=str(name),
                                             costs=result["costs"], record_sha256=observed_hash))
                costs = {name: {key: float(np.median([r["costs"][key] for r in metering if r["controller"] == name]))
                                for key in metering[0]["costs"]} for name in config["controllers"]}
                case = dict(seed=seed, domain=domain, arm=arm, selected_ordinary=selected,
                            count=config["episodes_per_case"], tape_hash=result["tape_hash"],
                            planner_identity=result["planner_identity"], means=result["mean"],
                            common_preparation_cpu_seconds=common_preparation_cpu,
                            preparation_scope="Shared by B/D and both controllers; count once per fit/domain",
                            record_file=identity + ".records.json.gz", record_sha256=record_hash,
                            record_file_sha256=digest(output / (identity + ".records.json.gz")),
                            all_episode_records_equal=True, median_costs=costs, calls=metering,
                            batched_reference_cpu_ratio=costs["batched"]["cpu_seconds"] / costs["reference"]["cpu_seconds"])
                write_new(output / (identity + ".json"), case)
                cases.append(case)
                print(json.dumps({"case": identity, "cpu_ratio": case["batched_reference_cpu_ratio"],
                                  "records_equal": True}), flush=True)
    for relative, expected in sources.items():
        if digest(ROOT / relative) != expected:
            raise ValueError("Replay source changed while metering: " + relative)
    for relative, expected in freeze["sources"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError("Original source changed while metering: " + relative)
    for relative, expected in artifacts.items():
        if digest(run / relative) != expected:
            raise ValueError("Frozen input changed while metering: " + relative)
    summaries = {}
    for domain in config["domains"]:
        summaries[domain] = {}
        for arm in config["arms"]:
            rows = [r for r in cases if r["domain"] == domain and r["arm"] == arm]
            sums = {name: sum(r["median_costs"][name]["cpu_seconds"] for r in rows) for name in config["controllers"]}
            summaries[domain][arm] = dict(reference_cpu_sum=sums["reference"], batched_cpu_sum=sums["batched"],
                                          ratio=sums["batched"] / sums["reference"],
                                          per_fit_ratios=[r["batched_reference_cpu_ratio"] for r in rows],
                                          all_episode_records_equal=all(r["all_episode_records_equal"] for r in rows))
    report = dict(schema="hcsn.r15.common-controller-replay.v1", summary=summaries,
                  case_count=len(cases), unique_actor_episodes=sum(r["count"] for r in cases),
                  measured_execute_calls=sum(len(r["calls"]) for r in cases),
                  source_freeze_sha256=digest(output / "FREEZE.json"),
                  sources_unchanged=True, original_artifacts_unchanged=True,
                  scientific_acceptance_changed=False, new_confirmation_opened=False,
                  timing_scope=config["timing_scope"], limitations=config["limits"],
                  cpu_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall,
                  case_files=[f"{r['seed']}_{r['domain']}_{r['arm']}.json" for r in cases])
    write_new(output / "SUMMARY.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        result = run_replay(args.run, args.output)
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
