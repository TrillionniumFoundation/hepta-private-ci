"""Fresh four-arm confirmation with real channel costs and inherited weights."""

import argparse
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from ...addressed_decision_r15_20261101.law import Law
from ...addressed_decision_r15_20261101.world import make_episode
from .execution import execute
from .features import KINDS, prepare


HERE = Path(__file__).parent
ROOT = HERE.parents[3]
PREVIOUS = HERE.parents[1] / "addressed_decision_r15_20261101"
PROTOCOL = json.loads((HERE / "PROTOCOL.json").read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value, compressed=False):
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if compressed:
        raw = gzip.compress(raw, mtime=0)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return dict(file=path.name, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


def freeze():
    files = [HERE / name for name in ("__init__.py", "features.py", "execution.py", "campaign.py",
                                      "statistics.py", "checks.py", "PROTOCOL.json")]
    files.extend(PREVIOUS / name for name in ("__init__.py", "law.py", "planner.py", "execution.py", "world.py"))
    files.extend(PREVIOUS / "run_01/training" / f"{seed}.json.gz" for seed in PROTOCOL["fit_seeds"])
    files.extend([PREVIOUS.parent / "unified_cell_r12_20261031/cell.py",
                  PREVIOUS.parent / "unified_cell_r12_20261031/PROTOCOL.json",
                  PREVIOUS.parent / "calibrated_operator_r11_20261031/numerics/kernel.py"])
    manifest = dict(schema="hcsn-r16-channel-source-freeze-v1", base_commit=PROTOCOL["base_commit"],
                    files={str(path.relative_to(ROOT)): digest(path) for path in files})
    write_new(HERE / "SOURCE_FREEZE.json", manifest)
    return manifest


def verify(commit):
    if len(commit) != 40 or any(x not in "0123456789abcdef" for x in commit):
        raise ValueError("Published source/input freeze SHA is required")
    manifest = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    for path, expected in manifest["files"].items():
        if digest(ROOT / path) != expected:
            raise ValueError(f"Frozen channel source/input changed: {path}")
    return digest(HERE / "SOURCE_FREEZE.json")


def inputs(seed):
    path = PREVIOUS / "run_01/training" / f"{seed}.json.gz"
    result = json.loads(gzip.decompress(path.read_bytes()))
    if result["seed"] != seed or result["development"]:
        raise ValueError("Wrong inherited training object")
    return result, digest(path)


def tape(world):
    return dict(seed=world.seed, domain=world.domain, fingerprint=world.fingerprint,
                initial_values=world.initial_values.tolist(), query_keys=world.query_keys.tolist(),
                dts=world.dts.tolist(), deadlines=world.deadlines.tolist(),
                public_events=[world.events_at(i) for i in range(6)],
                paths=[dict(times=t.tolist(), states=s.tolist()) for t, s in world._paths])


def confirm(seed, domain, output, commit, development=False):
    if seed not in PROTOCOL["fit_seeds"] or domain not in PROTOCOL["domains"]:
        raise ValueError("Unregistered fit/domain")
    manifest = None if development else verify(commit)
    output.mkdir(parents=True, exist_ok=False)
    started = time.process_time()
    write_new(output / "CLAIM.json", dict(seed=seed, domain=domain, source_commit=commit,
               source_manifest_sha256=manifest, development=development, started_unix=time.time()))
    decode_start = time.process_time()
    training, input_hash = inputs(seed)
    shared_input_decode_cpu = time.process_time() - decode_start
    actors, preparation = {}, {}
    for kind in KINDS:
        begin = time.process_time()
        law = Law.from_payload(training["calibration"]["models"]["hx"]["payload"])
        restore_cpu = time.process_time() - begin
        preparation[kind] = prepare(law, kind, domain)
        preparation[kind]["law_restore_cpu_seconds"] = restore_cpu
        # Frozen list-to-array conversion is charged in each actual owner call.
        actors[kind] = dict(law=law, learned=training["learned"]["models"][kind])
    world_start = time.process_time()
    owner = Law()
    world_cpu = time.process_time() - world_start
    count = PROTOCOL["development_episodes_per_fit_domain"] if development else PROTOCOL["episodes_per_fit_domain"]
    namespace = PROTOCOL["development_namespace"] if development else PROTOCOL["namespace"]
    archive, shards = [], []
    totals = {kind: dict(utilities=[], rewards=[], fees=[], online_cpu_seconds=0., feature_cpu_seconds=0.,
                        reads=0, refreshes=0, first_hit_calls=0, stop_value_calls=0) for kind in KINDS}
    current = None
    try:
        for index in range(count):
            sample = namespace * 10**12 + seed * 10**5 + (10000 if domain == "ood" else 0) + index
            before = time.process_time()
            world = make_episode(owner, sample, domain)
            world_cpu += time.process_time() - before
            order = list(map(str, np.random.default_rng(sample).permutation(KINDS)))
            current = dict(index=index, world=tape(world), order=order, arms={})
            for kind in order:
                current["pending_actor"] = kind
                row = execute(actors[kind]["law"], world, actors[kind]["learned"])
                current["arms"][kind] = row
                for source, target in (("utility", "utilities"), ("reward", "rewards"), ("fee", "fees")):
                    totals[kind][target].append(row[source])
                totals[kind]["online_cpu_seconds"] += row["cpu_seconds"]
                totals[kind]["feature_cpu_seconds"] += row["feature_cpu_seconds"]
                for name in ("reads", "refreshes"):
                    totals[kind][name] += row[name]
                for name in ("first_hit_calls", "stop_value_calls"):
                    totals[kind][name] += row["operation_counts"][name]
            current.pop("pending_actor")
            archive.append(current)
            current = None
            if len(archive) == 8 or index == count - 1:
                shards.append(write_new(output / f"raw_{len(shards):03d}.json.gz", archive, True))
                archive = []
    except Exception as error:
        if archive:
            write_new(output / "partial.json.gz", archive, True)
        if current is not None:
            write_new(output / "failing_world.json.gz", current, True)
        write_new(output / "FAILURE.json", dict(error=type(error).__name__, detail=str(error),
                  full_process_cpu_so_far=time.process_time() - started))
        raise
    for kind, row in totals.items():
        row["mean_utility"] = float(np.mean(row["utilities"]))
        row["mean_reward"] = float(np.mean(row["rewards"]))
        row["mean_fee"] = float(np.mean(row["fees"]))
        row["final_transition_cache_entries"] = len(actors[kind]["law"]._transition_cache)
        row["final_event_cache_entries"] = len(actors[kind]["law"]._event_cache)
    historical = dict(source_commit=training["source_commit"],
                      whole_training_function_cpu_seconds=training["training_cpu_seconds"],
                      nested_learned_controller_cpu_seconds=training["learned"]["cpu_seconds"],
                      scope="Nested old-host function timers; not additional current CPU and not complete process costs.")
    result = dict(schema="hcsn-r16-channel-confirmation-v1", seed=seed, domain=domain, count=count,
                  development=development, source_commit=commit, source_manifest_sha256=manifest,
                  training_input_sha256=input_hash, arms=totals, preparation=preparation,
                  shared_input_decode_cpu_seconds=shared_input_decode_cpu, world_generation_cpu_seconds=world_cpu,
                  historical_training=historical, archives=shards,
                  measured_worker_cpu_seconds=time.process_time() - started)
    write_new(output / "RESULT.json", result)
    print(json.dumps(dict(seed=seed, domain=domain, count=count, cpu_seconds=result["measured_worker_cpu_seconds"])), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("freeze", "confirm", "development"))
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--domain", choices=("iid", "ood"))
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        if args.stage == "freeze":
            freeze()
        elif args.seed is None or args.output is None or args.domain is None:
            raise ValueError("Execution requires fit, domain and new output path")
        else:
            confirm(args.seed, args.domain, args.output, args.source_commit, args.stage == "development")


if __name__ == "__main__":
    main()
