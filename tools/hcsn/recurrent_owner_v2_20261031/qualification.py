"""Implementation replay of frozen v1 evidence; no model selection or efficacy test.

The published frozen policies, actions, inputs and cell laws remain unchanged.
Both ordinary and analytic representations now retain their own causal state.
Timing includes construction, each query and every consumed interval. The old
distribution implementation did not advance after the final query, whereas this
owner does, so the new implementation performs that additional terminal work.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..task_value_factorial_20261030.cells import augmented_features, initial, physical
from ..task_value_factorial_20261030.controller import forward
from ..task_value_factorial_20261030.execution import sample_interval, sampled_features
from .owner import CellOwner


FROZEN_COMMIT = "8fef2abec58dc0b40287de1e656f9042371979b5"
POLICIES = ("ordinary_myopic", "ordinary_value", "analytic_myopic", "analytic_value",
            "analytic_value_sampled")


def unpack(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def timed_features(row, parameters, implementation):
    wall, cpu = time.perf_counter(), time.process_time()
    family = row["policy"].split("_")[0]
    sampled = row["policy"].endswith("_sampled")
    mode = "sampled" if sampled else "distribution"
    outputs, transitions = [], []
    if implementation == "incremental":
        owner = CellOwner(family, parameters, mode, row["rng_seed"])
    elif sampled:
        rng = np.random.default_rng(row["rng_seed"])
        index = int(rng.choice(5, p=initial(physical(parameters, 0.))))
    for decision, event in zip(row["decision_trace"], row["events"], strict=True):
        record = decision["record"]
        if implementation == "incremental":
            features, sequence = owner.query(record["driver"], record["horizon"])
            transition = owner.advance(sequence+1, record["driver"], event["duration"],
                                       reset=event["action"] == "FIRE")
            transitions.append(transition)
        elif sampled:
            features = sampled_features(parameters, index, record["driver"], record["horizon"])
            index, transition = sample_interval(parameters, index, record["driver"], event["duration"],
                                               event["action"] == "FIRE", rng)
            transitions.append(transition)
        else:
            features = augmented_features(family, parameters, [record])[0]
        outputs.append(features.tolist())
    return dict(features=outputs, transitions=transitions,
                cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)


def long_stream(parameters):
    """Bounded cache, irregular observations, reset and resume over 2,048 intervals."""
    owner = CellOwner("analytic", parameters)
    max_mass_error, minimum_mass, expected_events = 0., 1., 0.
    rng = np.random.default_rng(319871)
    for step in range(2048):
        driver, duration = float(rng.uniform(-1, 1)), float(10**rng.uniform(-6, .6))
        owner.query(driver, max(duration, 1e-5))
        receipt = owner.advance(step+1, driver, duration, reset=(step+1) % 37 == 0)
        state = np.asarray(receipt["state"])
        max_mass_error = max(max_mass_error, abs(float(state.sum())-1))
        minimum_mass = min(minimum_mass, float(state.min()))
        expected_events += receipt["event_count"]
        if step % 251 == 0:
            checkpoint = owner.snapshot()
            restored = CellOwner("analytic", parameters)
            restored.restore(checkpoint)
            if restored.snapshot() != checkpoint:
                raise AssertionError("Long-stream checkpoint did not preserve its exact bytes")
            owner = restored
    return dict(intervals=2048, maximum_mass_error=max_mass_error, minimum_mass=minimum_mass,
                expected_latent_events=expected_events, final_cache_entries=len(owner._kernels),
                maximum_cache_entries=128, final_checkpoint=owner.snapshot(),
                passed=max_mass_error <= 2e-10 and minimum_mass >= -2e-12 and len(owner._kernels) <= 128)


def qualify(frozen, out):
    out.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    rows, input_hashes, mismatch_examples = [], {}, []
    ordering = np.random.default_rng(319873)
    final_parameters = None
    for result_file in sorted((frozen/"results").glob("seed*.json.gz")):
        seed = int(result_file.name.split("_")[0][4:])
        model_file = frozen/"models"/f"seed{seed}.json.gz"
        model, result = unpack(model_file), unpack(result_file)
        for path in (result_file, model_file):
            input_hashes[str(path.relative_to(frozen))] = hashlib.sha256(path.read_bytes()).hexdigest()
        for row in result["rows"]:
            if row["policy"] not in POLICIES:
                continue
            family = row["policy"].split("_")[0]
            arm = row["policy"].removesuffix("_sampled")
            parameters = np.asarray(model["cellfits"][family]["parameters"])
            if family == "analytic":
                final_parameters = parameters
            weights = {k:np.asarray(v) for k,v in model["controllers"][arm]["weights"].items()}
            pair = {}
            for implementation in ordering.permutation(["legacy", "incremental"]):
                pair[str(implementation)] = timed_features(row, parameters, str(implementation))
            expected = np.asarray([d["cell_features"] for d in row["decision_trace"]])
            got = np.asarray(pair["incremental"]["features"])
            old = np.asarray(pair["legacy"]["features"])
            public = np.asarray([d["record"]["features"] for d in row["decision_trace"]])
            public = (public-model["norm"]["mean"])/model["norm"]["scale"]
            q, _ = forward(weights, np.column_stack((public, (got-.5)*2)))
            old_q = np.asarray([d["q"] for d in row["decision_trace"]])
            legal = np.asarray([d["record"]["feasible"] for d in row["decision_trace"]])
            actions = np.argmax(np.where(legal, q, -np.inf), axis=1)
            expected_actions = np.argmax(np.where(legal, old_q, -np.inf), axis=1)
            mismatch = np.flatnonzero(actions != expected_actions)
            for i in mismatch:
                mismatch_examples.append(dict(seed=seed, session_id=row["session_id"],
                    policy=row["policy"], step=int(i), old_action=int(expected_actions[i]),
                    new_action=int(actions[i]), old_q=old_q[i].tolist(), new_q=q[i].tolist()))
            sampled_equal = True
            if row["policy"].endswith("_sampled"):
                sampled_equal = all(
                    a["jumps"] == b["jumps"] == d["latent_transition"]["jumps"]
                    and a["event_count"] == b["count"] == d["latent_transition"]["count"]
                    and a["sampled_index"] == b["after"] == d["latent_transition"]["after"]
                    for a,b,d in zip(pair["incremental"]["transitions"], pair["legacy"]["transitions"],
                                     row["decision_trace"], strict=True))
            rows.append(dict(seed=seed, split=row["split"], session_id=row["session_id"], policy=row["policy"],
                decisions=len(got), maximum_feature_error=float(np.max(np.abs(got-expected))),
                maximum_legacy_error=float(np.max(np.abs(old-expected))),
                maximum_q_error=float(np.max(np.abs(q-old_q))), action_mismatches=len(mismatch),
                sampled_path_equal=sampled_equal,
                **{name+"_"+measure:pair[name][measure] for name in pair for measure in ("cpu_seconds", "wall_seconds")}))
    stream = long_stream(final_parameters)
    summaries = []
    for policy in POLICIES:
        group = [r for r in rows if r["policy"] == policy]
        summaries.append(dict(policy=policy, episodes=len(group), decisions=sum(r["decisions"] for r in group),
            **{name+"_cpu_seconds":sum(r[name+"_cpu_seconds"] for r in group) for name in ("legacy", "incremental")},
            maximum_feature_error=max(r["maximum_feature_error"] for r in group),
            maximum_q_error=max(r["maximum_q_error"] for r in group),
            action_mismatches=sum(r["action_mismatches"] for r in group),
            sampled_paths_equal=all(r["sampled_path_equal"] for r in group)))
    accepted = (all(r["maximum_feature_error"] < 2e-12 and r["maximum_legacy_error"] < 2e-12
        and r["maximum_q_error"] < 2e-11 and not r["action_mismatches"] and r["sampled_path_equal"]
        for r in rows) and stream["passed"])
    report = dict(schema="hcsn.incremental-owner.implementation-replay.v2", accepted=accepted,
        frozen_research_commit=FROZEN_COMMIT, source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(__file__).parent.glob("*.py"))}, inputs_sha256=input_hashes,
        episodes=len(rows), decisions=sum(r["decisions"] for r in rows), summaries=summaries,
        mismatch_examples=mismatch_examples, long_stream=stream,
        replay_cpu_seconds=time.process_time()-cpu, replay_wall_seconds=time.perf_counter()-wall,
        scope="Implementation regression on already published heldout evidence, not new efficacy, refitting or selection.",
        timing_scope="Randomized paired order; fresh owner per stream; cell construction, query and advance only, no content IO or controller. New distribution path additionally advances the last interval. CPU is host-process CPU, not measured energy.",
        main_activation=False)
    (out/"REPORT.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    (out/"REPLAYS.json.gz").write_bytes(gzip.compress(json.dumps(rows, separators=(",", ":")).encode(), mtime=0))
    print(json.dumps(report, indent=2))
    return accepted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if qualify(args.frozen, args.out) else 1)
