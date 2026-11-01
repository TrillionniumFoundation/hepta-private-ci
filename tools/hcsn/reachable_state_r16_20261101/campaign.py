"""Fresh paired R15 owner worlds for R16 support-preserving approximations."""

import argparse
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np

from ..addressed_decision_r15_20261101.execution import run_episode
from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.planner import BeliefMemory
from ..addressed_decision_r15_20261101.world import make_episode
from .compression import ProjectionLaw, decode, encode


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = HERE.parent / "addressed_decision_r15_20261101"
PROTOCOL = json.loads((HERE / "PROTOCOL.json").read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def write_new(path, value, compressed=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (canonical(value) + "\n").encode()
    if compressed:
        raw = gzip.compress(raw, mtime=0)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return dict(file=path.name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def verify_freeze(commit):
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("Exact published source commit is required")
    frozen = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    for relative, expected in frozen["files"].items():
        if digest(ROOT / relative) != expected:
            raise RuntimeError(f"Frozen source/model changed: {relative}")
    return digest(HERE / "SOURCE_FREEZE.json")


def world_tape(episode):
    return dict(seed=episode.seed, domain=episode.domain, fingerprint=episode.fingerprint,
                initial_values=episode.initial_values.tolist(), query_keys=episode.query_keys.tolist(),
                dts=episode.dts.tolist(), deadlines=episode.deadlines.tolist(),
                public_events=[episode.events_at(q) for q in range(len(episode.query_keys))],
                paths=[dict(times=t.tolist(), states=s.tolist()) for t, s in episode._paths])


def arms_for(seed):
    calibrated = json.loads(gzip.decompress((PREVIOUS / "run_01" / "calibration" /
                                           f"{seed}.json.gz").read_bytes()))
    selected = json.loads((PREVIOUS / "run_01" / "FREEZE.json").read_text())["selections"][str(seed)]
    specs = {"A": (selected["ordinary"], "fixed", "full"),
             "B": (selected["ordinary"], "value", "full"),
             "C": ("hx", "fixed", "full"), "D": ("hx", "value", "full"),
             "hmm_same_matrix": ("hmm_same_matrix", "value", "full")}
    specs.update({mode: ("hx", "value", mode)
                  for mode in ("factorized", "block2", "block4", "block5")})
    actors = {}
    for name, (model, policy, projection) in specs.items():
        started = time.process_time()
        law = ProjectionLaw(Law.from_payload(calibrated["models"][model]["payload"]))
        actors[name] = dict(law=law, model=model, policy=policy, projection=projection,
                            pattern=selected["fixed"], preparation_cpu=time.process_time() - started,
                            online_cpu=0., checkpoint_cpu=0., rewards=[], utilities=[], fees=[],
                            reads=0, refreshes=0, planner_beliefs=0)
    return actors, calibrated["accounting"], selected


def confirm(seed, domain, out, freeze_commit, development=False):
    started, wall = time.process_time(), time.perf_counter()
    if seed not in PROTOCOL["fit_seeds"] or domain not in PROTOCOL["domains"]:
        raise ValueError("Unregistered fit/domain")
    freeze_hash = None if development else verify_freeze(freeze_commit)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    count = 2 if development else PROTOCOL["episodes_per_fit_domain"]
    namespace = 916 if development else PROTOCOL["namespace"]
    write_new(out / "CLAIM.json", dict(seed=seed, domain=domain, development=development,
                                     freeze_commit=freeze_commit, source_manifest=freeze_hash,
                                     started_unix=time.time(), count=count))
    actors, inherited_cost, selected = arms_for(seed)
    owner = Law()
    shard, archives = [], []
    world_cpu, equivalence = 0., 0
    completed = 0
    episode, rows, order, name = None, {}, [], None
    checkpoint_path = out / "checkpoint.json"
    try:
        for index in range(count):
            episode_seed = namespace * 10**12 + seed * 10**5 + (10000 if domain == "ood" else 0) + index
            begin = time.process_time()
            episode = make_episode(owner, episode_seed, domain)
            world_cpu += time.process_time() - begin
            rows = {}
            order = np.random.default_rng(episode_seed).permutation(list(actors))
            for name in order:
                actor = actors[name]
                row = run_episode(actor["law"], episode, policy=actor["policy"],
                                  pattern=actor["pattern"], projection=actor["projection"],
                                  capture_states=True)
                actor["online_cpu"] += row["cpu_seconds"]
                begin = time.process_time()
                # Serialize and restore a real causal checkpoint. This is a
                # local belief roundtrip, not a production owner crash claim.
                payload = canonical(row["states"][-1])
                with checkpoint_path.open("w") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                restored = BeliefMemory.restore(actor["law"], json.loads(checkpoint_path.read_text()))
                if canonical(restored.checkpoint()) != payload:
                    raise RuntimeError("Checkpoint roundtrip mismatch")
                if actor["projection"].startswith("block"):
                    compressed = encode(restored.beliefs, actor["projection"])
                    if np.max(np.abs(decode(compressed) - restored.beliefs)) > 2e-11:
                        raise RuntimeError("Compressed checkpoint is not a projection fixed point")
                    row["compressed_state_bytes"] = compressed.nbytes
                actor["checkpoint_cpu"] += time.process_time() - begin
                for key, target in (("reward", "rewards"), ("utility", "utilities"), ("fee", "fees")):
                    actor[target].append(row[key])
                actor["reads"] += row["reads"]
                actor["refreshes"] += row["refreshes"]
                actor["planner_beliefs"] += row["belief_evaluations"]
                # Six complete public owner checkpoints are preserved; they
                # contain no hidden target. The scorer tape is a separate field.
                rows[str(name)] = row
            if rows["D"]["queries"] != rows["hmm_same_matrix"]["queries"]:
                raise RuntimeError("Same-matrix ordinary HMM differs")
            equivalence += 1
            shard.append(dict(index=index, actor_order=order.tolist(), world=world_tape(episode), arms=rows))
            completed += 1
            if len(shard) == 8 or completed == count:
                archives.append(write_new(out / f"raw_{len(archives):03d}.json.gz", shard, True))
                shard = []
    except Exception as error:
        if episode is not None:
            write_new(out / "failing_episode.json.gz", dict(
                index=index, world=world_tape(episode), arms=rows,
                actor_order=list(map(str, order)), current_actor=str(name),
                error=type(error).__name__, detail=str(error)), True)
        if shard:
            write_new(out / "partial.json.gz", shard, True)
        write_new(out / "FAILURE.json", dict(error=type(error).__name__, detail=str(error),
                                            completed=completed, expected=count,
                                            cpu_seconds=time.process_time() - started))
        raise
    summary = {}
    for name, actor in actors.items():
        summary[name] = {k: v for k, v in actor.items() if k != "law"}
        summary[name]["operator_identity"] = actor["law"].operator_identity
        summary[name]["model_identity"] = actor["law"].identity
        for key in ("rewards", "utilities", "fees"):
            summary[name]["mean_" + key] = float(np.mean(actor[key]))
    result = dict(schema="hcsn-r16-confirmation-v1", seed=seed, domain=domain,
                  development=development, count=count, completed=completed,
                  freeze_commit=freeze_commit, source_manifest=freeze_hash,
                  selected=selected, arms=summary, archives=archives,
                  same_matrix_identical_worlds=equivalence, world_generation_cpu=world_cpu,
                  inherited_r15_calibration_cost=inherited_cost,
                  process_cpu_seconds=time.process_time() - started,
                  process_wall_seconds=time.perf_counter() - wall)
    write_new(out / "RESULT.json", result)
    print(canonical(dict(seed=seed, domain=domain, completed=completed,
                         cpu_seconds=result["process_cpu_seconds"])))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--domain", choices=PROTOCOL["domains"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--freeze-commit", default="")
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    confirm(args.seed, args.domain, args.out, args.freeze_commit, args.development)
