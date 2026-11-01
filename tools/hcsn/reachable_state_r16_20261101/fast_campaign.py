"""Frozen namespace18 owner comparison for the same faster projection."""

import argparse
import gzip
import json
import os
from pathlib import Path
import time

import numpy as np
from scipy.stats import t

from ..addressed_decision_r15_20261101.execution import run_episode
from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.planner import BeliefMemory
from ..addressed_decision_r15_20261101.world import make_episode
from .campaign import ROOT, canonical, digest, verify_freeze, world_tape, write_new
from .compression import ProjectionLaw, decode, encode
from .fast_compression import FastProjectionLaw


HERE = Path(__file__).resolve().parent
PROTOCOL = json.loads((HERE / "FAST_PROTOCOL.json").read_text())


def worker(fit, domain, folder, owner):
    started = time.process_time()
    folder.mkdir(parents=True, exist_ok=False)
    previous = HERE.parent / "addressed_decision_r15_20261101/run_01"
    calibrated = json.loads(gzip.decompress((previous / "calibration" / f"{fit}.json.gz").read_bytes()))
    pattern = json.loads((previous / "FREEZE.json").read_text())["selections"][str(fit)]["fixed"]
    actors = {}
    for name in PROTOCOL["arms"]:
        begin = time.process_time()
        factory = FastProjectionLaw if name == "fast_block2" else ProjectionLaw
        law = factory(Law.from_payload(calibrated["models"]["hx"]["payload"]))
        actors[name] = dict(law=law, projection="full" if name == "D_full" else "block2",
                            preparation_cpu=time.process_time() - begin,
                            online_cpu=0., checkpoint_cpu=0., utilities=[], rewards=[])
    archives, shard, worlds_cpu, completed = [], [], 0., 0
    current = None
    try:
        for index in range(PROTOCOL["episodes_per_fit_domain"]):
            seed = 18 * 10**12 + fit * 10**5 + (10000 if domain == "ood" else 0) + index
            begin = time.process_time()
            episode = make_episode(owner, seed, domain)
            worlds_cpu += time.process_time() - begin
            current = dict(index=index, world=world_tape(episode), arms={})
            order = np.random.default_rng(seed).permutation(PROTOCOL["arms"])
            current["actor_order"] = order.tolist()
            for name in order:
                actor = actors[name]
                row = run_episode(actor["law"], episode, policy="value", pattern=pattern,
                                  projection=actor["projection"], capture_states=True)
                actor["online_cpu"] += row["cpu_seconds"]
                begin = time.process_time()
                checkpoint = folder / "checkpoint.json"
                with checkpoint.open("w") as stream:
                    stream.write(canonical(row["states"][-1]))
                    stream.flush()
                    os.fsync(stream.fileno())
                restored = BeliefMemory.restore(actor["law"], json.loads(checkpoint.read_text()))
                assert restored.checkpoint() == row["states"][-1]
                if actor["projection"] == "block2":
                    packed = encode(restored.beliefs, "block2")
                    assert np.max(abs(decode(packed) - restored.beliefs)) < 2e-11
                    row["compressed_state_bytes"] = packed.nbytes
                actor["checkpoint_cpu"] += time.process_time() - begin
                actor["utilities"].append(row["utility"])
                actor["rewards"].append(row["reward"])
                current["arms"][str(name)] = row
            left, right = (current["arms"][name] for name in ("old_block2", "fast_block2"))
            clean = lambda rows: [{k: v for k, v in row.items() if k != "checkpoint_sha256"} for row in rows]
            assert clean(left["queries"]) == clean(right["queries"])
            for a, b in zip(left["states"], right["states"], strict=True):
                assert np.max(abs(np.asarray(a["beliefs"]) - np.asarray(b["beliefs"]))) < 2e-11
            shard.append(current)
            completed += 1
            if len(shard) == 8:
                archives.append(write_new(folder / f"raw_{len(archives):03d}.json.gz", shard, True))
                shard = []
    except Exception as error:
        write_new(folder / "FAILURE.json", dict(error=type(error).__name__, message=str(error),
                                                completed=completed, cpu_seconds=time.process_time() - started))
        write_new(folder / "partial.json.gz", dict(shard=shard, current=current), True)
        raise
    result = dict(fit=fit, domain=domain, completed=completed, archives=archives,
                  arms={name: {k: v for k, v in actor.items() if k != "law"} for name, actor in actors.items()},
                  inherited_calibration_cost=calibrated["accounting"],
                  worlds_cpu=worlds_cpu, cpu_seconds=time.process_time() - started,
                  old_fast_full_query_equality=True)
    write_new(folder / "RESULT.json", result)
    return result


def run(output, commit):
    started = time.process_time()
    inherited = verify_freeze(commit)
    manifest = HERE / "FAST_SOURCE_FREEZE.json"
    for relative, expected in json.loads(manifest.read_text())["files"].items():
        if digest(ROOT / relative) != expected:
            raise RuntimeError(f"Frozen fast source changed: {relative}")
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "PUBLICATION.json", dict(commit=commit, manifest_sha256=digest(manifest),
                                                inherited_manifest_sha256=inherited))
    owner, records = Law(), []
    for fit in PROTOCOL["fit_seeds"]:
        for domain in PROTOCOL["domains"]:
            record = worker(fit, domain, output / f"{fit}_{domain}", owner)
            records.append(record)
            print(canonical(dict(fit=fit, domain=domain, completed=record["completed"])), flush=True)
    summaries = {}
    for domain in PROTOCOL["domains"]:
        rows = [r for r in records if r["domain"] == domain]
        quality = {}
        for metric in ("utilities", "rewards"):
            delta = np.array([np.mean(r["arms"]["fast_block2"][metric])
                              - np.mean(r["arms"]["D_full"][metric]) for r in rows])
            lower = float(delta.mean() - t.ppf(1 - .05 / 4, 7) * delta.std(ddof=1) / np.sqrt(8))
            quality[metric] = dict(per_fit=delta.tolist(), mean=float(delta.mean()),
                                   simultaneous_lower=lower, passes=lower > -.01)
        cost = {name: dict(online=sum(r["arms"][name]["online_cpu"] for r in rows),
                          preparation_and_1000_owner_uses=sum(r["arms"][name]["preparation_cpu"] +
                              1000 * (r["arms"][name]["online_cpu"] + r["arms"][name]["checkpoint_cpu"]) /
                              r["completed"] for r in rows)) for name in PROTOCOL["arms"]}
        ratios = {base: {key: cost["fast_block2"][key] / cost[base][key] for key in cost[base]}
                  for base in ("old_block2", "D_full")}
        summaries[domain] = dict(quality=quality, measured_cpu=cost, fast_over=ratios,
            engineering_speed_gate=max(ratios["old_block2"].values()) <= .9,
            full_state_benefit_gate=all(g["passes"] for g in quality.values()) and max(ratios["D_full"].values()) <= .9)
    result = dict(schema="hcsn-r16-fast-owner-confirmation-v1", source_commit=commit,
                  namespace=18, worlds=sum(r["completed"] for r in records), old_fast_full_query_equality=True,
                  domains=summaries, process_body_cpu_seconds=time.process_time() - started,
                  cost_scope="Includes all worker preparation/execution/archive work, excludes startup/imports and historical fitting; no energy/network claim",
                  original_primary_gate_unchanged=True, inherited_manifest_sha256=inherited)
    write_new(output / "SUMMARY.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze-commit", required=True)
    args = parser.parse_args()
    run(args.output, args.freeze_commit)
