"""Predeclared paired analysis; consumes completed, frozen raw evidence only."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import time

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TASKS = ("mqar", "selective", "binding")
SEEDS = (17, 29, 43)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def bootstrap(delta, rng, plan, primary=False):
    """One shared seed/episode draw for every trailing effect coordinate."""
    delta = np.asarray(delta, dtype=np.float64)
    if delta.ndim == 2:
        delta = delta[..., None]
    count, episodes, width = delta.shape
    draws = np.empty((plan["replicates"], width))
    for start in range(0, len(draws), 50):
        size = min(50, len(draws) - start)
        seeds = rng.integers(count, size=(size, count))
        identifiers = rng.integers(episodes, size=(size, count, episodes))
        draws[start:start + size] = delta[seeds[..., None], identifiers].mean((1, 2))
    output = []
    for index in range(width):
        def interval(level):
            tail = (1 - level) / 2
            return np.quantile(draws[:, index], [tail, 1 - tail]).tolist()
        descriptive = interval(plan["descriptive_interval"])
        family = interval(plan["primary_three_task_family_interval"]) if primary else None
        used = family if family is not None else descriptive
        output.append(dict(mean=float(delta[..., index].mean()), interval95=descriptive,
            primary_family_interval=family, bootstrap_degenerate=bool(np.ptp(draws[:, index]) == 0),
            interpretation=("positive" if used[0] > 0 else "negative" if used[1] < 0 else "not_distinguished_from_zero")))
    return output


def load_evidence(run, provenance):
    protocol = read_json(run / "PROTOCOL.json")
    candidate = read_json(run / "ALL_CHECKPOINTS.json")
    train = read_json(run / "TRAINING_SOURCE.json")
    freeze = read_json(run / "confirmation/CANDIDATE_FREEZE.json")
    receipt = read_json(run / "confirmation/RECEIPT.json")
    require(receipt["failed"] == 0 and receipt["source_unchanged"], "Confirmation is incomplete or source changed")
    require(candidate["protocol_sha256"] == digest(run / "PROTOCOL.json") == train["protocol_sha256"], "Protocol identity mismatch")
    require(candidate["source_commit"] == train["source_commit"], "Training source commit mismatch")
    require(freeze["candidate_freeze_sha256"] == digest(run / "ALL_CHECKPOINTS.json") == receipt["candidate_freeze_sha256"], "Candidate freeze mismatch")
    require(freeze["source_hashes"] == protocol["source_hashes"], "Confirmation source set differs")
    require(freeze["training_source"] == train and train["source_hashes"] == protocol["source_hashes"], "Training identity chain differs")
    for filename, expected in protocol["source_hashes"].items():
        require(digest(ROOT / filename) == expected, "Scientific source mismatch: " + filename)
    records = read_json(run / "confirmation/RESULTS.json")
    expected = {(fit["task"], fit["arm"], fit["seed"], condition) for fit in protocol["fits"]
                for condition in protocol["dynamics_conditions" if fit["task"] == "dynamics" else "content_conditions"]}
    require(len(records) == len(expected) and {(r["task"], r["arm"], r["seed"], r["condition"]) for r in records} == expected,
            "Registered confirmation conditions missing or duplicated")
    fits = {(r["task"], r["arm"], r["seed"]): r for r in candidate["fits"]}
    require(len(fits) == len(protocol["fits"]), "Registered training fits missing or duplicated")
    for fit in fits.values():
        require(fit["status"] == "completed" and digest(run / fit["checkpoint"]) == fit["checkpoint_sha256"], "Checkpoint mismatch")
        require(fit["steps"] == protocol["steps"], "Training budget mismatch")
    for task, seed in {(key[0], key[2]) for key in fits}:
        require(len({r["input_stream_sha256"] for r in fits.values() if r["task"] == task and r["seed"] == seed}) == 1,
                "Training input streams differ across arms")
    arrays, metrics = {}, []
    for row in records:
        key = (row["task"], row["arm"], row["seed"], row["condition"])
        require(row["status"] == "completed", "Failed registered condition: " + str(key))
        path = run / row["artifact"]
        require(digest(path) == row["artifact_sha256"], "Raw artifact hash mismatch: " + str(path))
        require(row["checkpoint_sha256"] == fits[key[:3]]["checkpoint_sha256"], "Raw result/checkpoint identity mismatch")
        with np.load(path, allow_pickle=False) as archive:
            raw = {name: archive[name] for name in archive.files}
        require(np.isfinite(raw["logits"]).all(), "Nonfinite raw logits")
        require(np.array_equal(raw["prediction"], raw["logits"].argmax(-1)), "Stored prediction mismatch")
        correct = raw["prediction"] == raw["target"]
        require(np.array_equal(raw["correct"], correct), "Stored correctness mismatch")
        n = row["episodes"]
        episode = correct.reshape(n, -1)
        require(episode.shape[1] == (8 if key[0] == "dynamics" else 4), "Incorrect number of scored queries")
        require(np.array_equal(raw["episode_id"], np.repeat(np.arange(n), episode.shape[1])), "Episode identity/order mismatch")
        require(n == protocol["confirmation_episodes"], "Incorrect confirmation population")
        require(abs(float(correct.mean()) - row["accuracy"]) < 1e-12 and
                abs(float(episode.all(-1).mean()) - row["all_queries_correct"]) < 1e-12, "Summary differs from raw outcomes")
        arrays[key] = dict(raw=raw, episode=episode, record=row)
        metrics.append(dict(task=key[0], arm=key[1], seed=key[2], condition=key[3],
            accuracy=float(correct.mean()), all4=float(episode.all(-1).mean()),
            base_quality_gate=float(episode.all(-1).mean()) >= .95 if key[0] in TASKS and key[3] == "base" else None,
            available_accuracy=float(correct[raw["target_available"]].mean()) if raw["target_available"].any() else None,
            unavailable_accuracy=float(correct[~raw["target_available"]].mean()) if (~raw["target_available"]).any() else None,
            resampling_error=row.get("resampling_max_abs_logit"),
            jump_first=float(episode[:, 4].mean()) if key[0] == "dynamics" else None,
            jump_later=float(episode[:, 5:].mean()) if key[0] == "dynamics" else None))
        provenance[str(path)] = row["artifact_sha256"]
    for row in metrics:
        if row["condition"] == "resample":
            key = (row["task"], row["arm"], row["seed"])
            base, refined = arrays[(*key, "base")]["raw"], arrays[(*key, "resample")]["raw"]
            require(np.array_equal(base["target"], refined["target"]) and np.array_equal(base["episode_id"], refined["episode_id"]),
                    "Time subdivision changed query targets or episode identities")
            error = float(np.max(np.abs(base["logits"] - refined["logits"])))
            require(error <= row["resampling_error"] + 1e-7, "Raw query error exceeds recorded full-sequence error")
            row["resampling_query_error"] = error
    for name in ("PROTOCOL.json", "ALL_CHECKPOINTS.json", "TRAIN_RECEIPT.json", "TRAINING_SOURCE.json",
                 "confirmation/RESULTS.json", "confirmation/RECEIPT.json", "confirmation/CANDIDATE_FREEZE.json"):
        provenance[str(run / name)] = digest(run / name)
    return protocol, candidate, arrays, metrics


def paired(left, right):
    for key in ("episode_id", "query_position", "target"):
        require(np.array_equal(left["raw"][key], right["raw"][key]), "Unpaired query identities: " + key)
    require(left["record"]["data_sha256"] == right["record"]["data_sha256"], "Arms received different inputs")


def content_effects(protocol, arrays, rng, plan):
    effects = []
    for task in TASKS:
        for condition in protocol["content_conditions"]:
            differences = []
            for seed in SEEDS:
                left, right = (arrays[(task, arm, seed, condition)] for arm in ("addressed_flow", "addressed_diagonal"))
                paired(left, right)
                a, b = left["episode"], right["episode"]
                differences.append(np.stack((a.mean(-1) - b.mean(-1), a.all(-1).astype(float) - b.all(-1)), -1))
            intervals = bootstrap(np.stack(differences), rng, plan["intervals"], primary=condition == "base")
            intervals[0]["primary_family_interval"] = None  # Accuracy is descriptive; primary endpoint is all-four.
            low, high = intervals[0]["interval95"]
            intervals[0]["interpretation"] = "positive" if low > 0 else "negative" if high < 0 else "not_distinguished_from_zero"
            effects.append(dict(task=task, condition=condition, contrast="addressed_flow-addressed_diagonal",
                accuracy=intervals[0], all4=intervals[1], units="fraction; multiply by100 for percentage points"))
    return effects


def control_effects(control, run, rng, plan, provenance):
    if control is None or not (control / "SUMMARY.json").exists():
        return dict(status="not_available", effects=[])
    summary, freeze = read_json(control / "SUMMARY.json"), read_json(control / "POLICY_FREEZE.json")
    require(summary["policy_freeze_sha256"] == digest(control / "POLICY_FREEZE.json"), "Control policy freeze mismatch")
    require(freeze["candidate_freeze_sha256"] == digest(run / "ALL_CHECKPOINTS.json"), "Control candidate mismatch")
    require(len(summary["records"]) == 18, "Control confirmation incomplete")
    candidates = {(r["task"], r["arm"], r["seed"]): r["checkpoint_sha256"] for r in read_json(run / "ALL_CHECKPOINTS.json")["fits"]}
    expected = {(task, core, seed) for task in TASKS for core in ("addressed_diagonal", "addressed_flow") for seed in SEEDS}
    require({(r["task"], r["core"], r["seed"]) for r in summary["records"]} == expected, "Control fit identities differ")
    raw, metrics = {}, []
    for row in summary["records"]:
        key = (row["task"], row["core"], row["seed"])
        path = control / "confirmation" / f"{key[0]}__{key[1]}__{key[2]}.npz"
        require(digest(path) == row["raw_sha256"], "Control raw identity mismatch")
        require(row["checkpoint_sha256"] == freeze["checkpoint_sha256"][f"{key[0]}__{key[1]}__{key[2]}"], "Control checkpoint identity mismatch")
        require(row["checkpoint_sha256"] == candidates[key], "Control checkpoint differs from content checkpoint")
        with np.load(path, allow_pickle=False) as archive:
            raw[key] = {name: archive[name] for name in archive.files}
        r = raw[key]
        for action in ("stop", "read"):
            quality = (r[action + "_logits"].argmax(-1) == r["labels"]).mean(-1)
            require(np.array_equal(quality, r[action + "_quality"]), "Control quality does not match actual predictions")
        policy = freeze["policies"][key[0]]
        for name in ("lightweight", "value"):
            choice = (r["price"] < policy["lightweight_threshold"] if name == "lightweight" else
                      np.clip(r["features"] @ np.asarray(policy["value_coefficients"]), -1, 1) > r["price"])
            utility = np.where(choice, r["read_quality"], r["stop_quality"]) - choice * r["price"]
            require(np.array_equal(choice, r[name + "_action_read"]) and np.allclose(utility, r[name + "_utility"], atol=1e-14, rtol=0), "Control executed utility mismatch")
            metrics.append(dict(task=key[0], core=key[1], seed=key[2], policy=name,
                                utility=float(utility.mean()), read_rate=float(choice.mean())))
        provenance[str(path)] = row["raw_sha256"]
    effects = []
    for task in TASKS:
        deltas = []
        for seed in SEEDS:
            ordinary, flow = (raw[(task, core, seed)] for core in ("addressed_diagonal", "addressed_flow"))
            for name in ("labels", "price", "removed_step"):
                require(np.array_equal(ordinary[name], flow[name]), "Unpaired control episode identities")
            a, b = ordinary["lightweight_utility"], ordinary["value_utility"]
            c, d = flow["lightweight_utility"], flow["value_utility"]
            deltas.append(np.stack((b-a, d-c, c-a, d-b, (d-c)-(b-a)), -1))
        intervals = bootstrap(np.stack(deltas), rng, plan["intervals"])
        effects.extend(dict(task=task, effect=name, **value) for name, value in
            zip(("B-A", "D-C", "C-A", "D-B", "(D-C)-(B-A)"), intervals, strict=True))
    for name in ("SUMMARY.json", "POLICY_FREEZE.json"):
        provenance[str(control / name)] = digest(control / name)
    return dict(status="completed", metrics=metrics, effects=effects, receipt=summary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--control", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    provenance = {str(HERE / name): digest(HERE / name) for name in ("analyze.py", "STATISTICAL_PLAN.json")}
    plan = read_json(HERE / "STATISTICAL_PLAN.json")
    protocol, candidate, arrays, metrics = load_evidence(args.run, provenance)
    rng = np.random.default_rng(plan["intervals"]["seed"])
    effects = content_effects(protocol, arrays, rng, plan)
    control = control_effects(args.control, args.run, rng, plan, provenance)
    grouped = []
    for task, arm, condition in sorted({(r["task"], r["arm"], r["condition"]) for r in metrics}):
        subset = [r for r in metrics if (r["task"], r["arm"], r["condition"]) == (task, arm, condition)]
        grouped.append(dict(task=task, arm=arm, condition=condition,
            accuracy=float(np.mean([r["accuracy"] for r in subset])), all4=float(np.mean([r["all4"] for r in subset])),
            all4_seed_min=min(r["all4"] for r in subset), all4_seed_max=max(r["all4"] for r in subset),
            every_seed_gate=all(r["all4"] >= plan["primary_content"]["threshold"] for r in subset) if task in TASKS else None))
    gates = {arm: all(r["every_seed_gate"] for r in grouped if r["arm"] == arm and r["condition"] == "base" and r["task"] in TASKS)
             for arm in ("addressed_flow", "addressed_diagonal", "legacy_flow", "transformer")}
    dynamics = []
    for arm in ("flow", "diagonal", "gru", "snn", "transformer"):
        for condition in protocol["dynamics_conditions"][1:]:
            delta = np.stack([arrays[("dynamics", arm, seed, condition)]["episode"].mean(-1)
                              - arrays[("dynamics", arm, seed, "base")]["episode"].mean(-1) for seed in SEEDS])
            dynamics.append(dict(arm=arm, condition=condition, contrast="condition-base",
                                 **bootstrap(delta, rng, plan["intervals"])[0]))
    costs = [dict(task=r["task"], arm=r["arm"], seed=r["seed"], cpu_seconds=r["cpu_seconds"],
                  wall_seconds=r["wall_seconds"], **r["resources"]) for r in candidate["fits"]]
    latency = [dict(task=k[0], arm=k[1], seed=k[2], condition=k[3], latency=v["record"]["latency"])
               for k, v in arrays.items() if "latency" in v["record"]]
    result = dict(plan=plan, source_commit=candidate["source_commit"], metrics=metrics, grouped=grouped,
        base_content_gates=gates, content_effects=effects, control=control, dynamics=dynamics,
        analytical_primary_advantage_established=all(r["all4"]["primary_family_interval"][0] > 0 for r in effects if r["condition"] == "base"),
        costs=costs, latency=latency, train_receipt=read_json(args.run / "TRAIN_RECEIPT.json"),
        confirmation_receipt=read_json(args.run / "confirmation/RECEIPT.json"),
        qualifications=["Only three independent training seeds; episodes across seeds are paired, not independent fits",
            "Constant or zero-event bootstrap samples can yield zero-width intervals; this is not population certainty",
            "Content quality, analytical increment, real frontend, energy and foundation-model gates are distinct",
            "Phase and fit timers are nested; do not add them twice; development and external-meter costs remain separate"],
        verified_artifacts=len(provenance), analysis_wall_seconds=time.perf_counter()-started, analysis_cpu_seconds=time.process_time()-cpu)
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "SUMMARY.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    (args.out / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2, sort_keys=True)+"\n")
    with (args.out / "QUALITY.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(grouped[0])); writer.writeheader(); writer.writerows(grouped)
    lines = ["# Independent confirmation analysis", "", "Source: `"+candidate["source_commit"]+"`.", "",
             "Only three training seeds. Degenerate bootstrap intervals do not establish population certainty.", "",
             "| Task | Arm | Condition | Accuracy % | All-four/all-query % | Min–max across seeds % |", "|---|---|---|---:|---:|---:|"]
    lines += [f"| {r['task']} | {r['arm']} | {r['condition']} | {100*r['accuracy']:.3f} | {100*r['all4']:.3f} | {100*r['all4_seed_min']:.3f}–{100*r['all4_seed_max']:.3f} |" for r in grouped]
    lines += ["", "## Primary Flow-minus-diagonal all-four contrasts", "", "| Task | Difference pp | 95% | 98.333% family | Degenerate |", "|---|---:|---|---|---|"]
    for row in effects:
        if row["condition"] == "base":
            r = row["all4"]
            lines.append(f"| {row['task']} | {100*r['mean']:.3f} | {[round(100*x,3) for x in r['interval95']]} | {[round(100*x,3) for x in r['primary_family_interval']]} | {r['bootstrap_degenerate']} |")
    (args.out / "SUMMARY.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(verified_artifacts=len(provenance), content_gates=gates,
                         analytical_primary_advantage_established=result["analytical_primary_advantage_established"])))


if __name__ == "__main__":
    main()
