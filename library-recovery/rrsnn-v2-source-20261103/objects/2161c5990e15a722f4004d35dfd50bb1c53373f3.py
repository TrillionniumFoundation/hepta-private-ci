"""Frozen-weight, exploratory paired maturity x announced-shock diagnostic.

Run from the workspace parent:
  /tmp/rrsnn-venv/bin/python -m rrsnn_experiments.runtime.paired_counterfactual

Uses the ORIGINAL evaluate_closed_loop function unchanged, in expected mode.
Its Oracle symbol is temporarily supplied by a read-only table containing values
computed by the original Oracle. This only avoids repeated task DP solves.
Training code and checkpoints are verified against their frozen SHA256 records.

128 value vectors x {A,B} x {shock0,shock2}, paired across all 12 x 5 weights.
No retraining, hyperparameter search, or model/reference selection occurs here.
The reference ctrnn_budget was selected by the original validation protocol.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import gzip
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import pickle
import time
from types import MappingProxyType

for _variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                  "NUMEXPR_NUM_THREADS"):
    os.environ[_variable] = "1"

import numpy as np
import torch

from .. import train_compare as tc
from ..resource_env import (ACTION_DIGITS, FEATURES, EPS, Oracle, Scenario,
                            exogenous, legal_actions, next_deadlines,
                            state_features, transition)

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "results" / "paired_counterfactual"
SEEDS = (101, 211, 307, 401, 503)
N_VALUES = 128
DATA_SEED = 72001
REFERENCE = "ctrnn_budget"
CONDITIONS = ("A_shock0", "A_shock2", "B_shock0", "B_shock2")
ORIGINAL_ORACLE = Oracle
_CACHE = {}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scenario_from_dict(d):
    d = dict(d)
    d["values"] = tuple(d["values"])
    d["deadlines"] = tuple(d["deadlines"])
    return Scenario(**d)


def key(s):
    return (tuple(s.values), tuple(s.deadlines), s.budget, s.shock_amount,
            s.refill_amount, s.shock_time, s.refill_time, s.horizon,
            s.renewal_period, s.early_penalty)


class ReadOnlyOracle:
    """Original-Oracle results only; never supplies input to the learned policy."""

    def __init__(self, scenario):
        entry = _CACHE[key(scenario)]
        self.times = entry["times"]
        self._values = entry["values"]
        self._q = entry["q"]

    def value(self, index, live, budget_before):
        return self._values[(index, live, budget_before)]

    def q_values(self, index, live, budget_after):
        return self._q[(index, live, budget_after)]


def make_scenarios():
    rng = np.random.default_rng(DATA_SEED)
    scenarios, metadata = [], []
    max_unchanged_difference = 0.0
    for sample in range(N_VALUES):
        raw = rng.uniform(0.25, 1.5, 4)
        permutation = rng.permutation(4)
        values = tuple(float(v) for v in raw[permutation])
        deadlines_a = tuple(float(d) for d in np.array([1, 1, 3, 3])[permutation])
        deadlines_b = (2.0, 2.0, 2.0, 2.0)
        group = []
        for profile, deadlines in (("A", deadlines_a), ("B", deadlines_b)):
            for shock in (0, 2):
                s = Scenario(values=values, deadlines=deadlines, budget=4,
                             shock_amount=shock, refill_amount=1,
                             shock_time=1.5, refill_time=2.5, profile=profile,
                             split="exploratory_paired_72001")
                scenarios.append(s)
                group.append(s)
                metadata.append({"episode": len(scenarios)-1, "sample": sample,
                                 "condition": f"{profile}_shock{shock}",
                                 "permutation": permutation.tolist(),
                                 "scenario": asdict(s)})
        for shock_index in (0, 1):
            a, b = group[shock_index], group[shock_index+2]
            xa, xb = state_features(a, 0, 15, 4), state_features(b, 0, 15, 4)
            unchanged = np.ones(22, dtype=bool)
            unchanged[7:11] = False
            assert np.array_equal(xa[unchanged], xb[unchanged])
            assert np.all(xa[7:11] != xb[7:11])
            assert a.values == b.values and sum(a.deadlines) == sum(b.deadlines) == 8
            assert a.events() == b.events()
            max_unchanged_difference = max(max_unchanged_difference,
                float(np.max(np.abs(xa[unchanged]-xb[unchanged]))))
        # Across shock conditions, the only initial feature change is the
        # announced shock amount. Shock time remains announced even at amount0.
        for i, j in ((0, 1), (2, 3)):
            xi, xj = state_features(group[i], 0, 15, 4), state_features(group[j], 0, 15, 4)
            assert np.flatnonzero(xi != xj).tolist() == [15]
    return scenarios, metadata, {
        "samples": N_VALUES, "episodes": len(scenarios), "data_seed": DATA_SEED,
        "same_values_budget_total_memory_mean_deadline": True,
        "same_exogenous_schedule_within_A_B": True,
        "same_observation_grid_A_B": True,
        "initial_feature_changes_A_vs_B": FEATURES[7:11],
        "initial_feature_changes_shock0_vs_shock2": [FEATURES[15]],
        "maximum_difference_outside_deadline_features": max_unchanged_difference,
        "item_permutation": "Values and A/B deadline vectors receive the same random item permutation per sample.",
        "schedule_observed": "Shock amount/time and refill amount/time are announced once at time0.",
    }


def reachable_states(s):
    """Finite task graph; independent of item values, includes all legal actions."""
    times = s.events()
    states = [{(15, s.budget)}]
    for i, t in enumerate(times[:-1]):
        nxt = set()
        for live, budget_before in states[i]:
            budget, _, _ = exogenous(s, t, budget_before)
            valid, _ = legal_actions(s, t, live, budget)
            for action in np.flatnonzero(valid):
                live2, budget2, _, _ = transition(s, t, live, budget, int(action))
                nxt.add((live2, budget2))
        states.append(nxt)
    return states


def create_cache(scenarios, path):
    begun = time.perf_counter()
    graphs, entries = {}, []
    value_entries = q_entries = 0
    for s in scenarios:
        graph_key = (s.deadlines, s.budget, s.shock_amount, s.refill_amount)
        if graph_key not in graphs:
            graphs[graph_key] = reachable_states(s)
        oracle = ORIGINAL_ORACLE(s)
        oracle.value(0, 15, s.budget)
        values, q = {}, {}
        for index, states in enumerate(graphs[graph_key]):
            t = oracle.times[index]
            for live, before in sorted(states):
                values[(index, live, before)] = oracle.value(index, live, before)
                after, _, _ = exogenous(s, t, before)
                _, due = legal_actions(s, t, live, after)
                if due.any():
                    q[(index, live, after)] = oracle.q_values(index, live, after)
        value_entries += len(values)
        q_entries += len(q)
        entries.append({"key": key(s), "times": oracle.times, "values": values, "q": q})
    with path.open("wb") as handle:
        pickle.dump(entries, handle, protocol=5)
    return {"source": "All numeric entries computed by the frozen original resource_env.Oracle.",
            "entries": len(entries), "reachable_value_states": value_entries,
            "reachable_decision_states": q_entries, "topology_graphs": len(graphs),
            "seconds": time.perf_counter()-begun, "sha256": digest(path),
            "file_bytes": path.stat().st_size}


def install_cache(path):
    global _CACHE
    with Path(path).open("rb") as handle:
        entries = pickle.load(handle)  # trusted cache produced locally by this script
    _CACHE = {}
    for entry in entries:
        for q in entry["q"].values():
            q.setflags(write=False)
        entry["q"] = MappingProxyType(entry["q"])
        entry["values"] = MappingProxyType(entry["values"])
        _CACHE[entry["key"]] = entry
    _CACHE = MappingProxyType(_CACHE)
    tc.Oracle = ReadOnlyOracle


def load_model(variant, seed):
    path = ROOT / "results" / variant / f"seed_{seed}" / "model.pt"
    saved = torch.load(path, map_location="cpu", weights_only=True)
    assert saved["variant"] == variant and saved["seed"] == seed
    expected_hash = json.loads(path.with_name("result.json").read_text())["checkpoint_sha256"]
    actual_hash = digest(path)
    assert expected_hash == actual_hash, f"Modified checkpoint {path}"
    model = tc.Policy(variant)
    model.load_state_dict(saved["state_dict"])
    return model, actual_hash


def reconstruct_episode(s, trace, utility, oracle):
    """Rebuild terminal masks and the ledger from observed legal action traces.

    A zero action means drop ONLY for a currently due live item. Zeros elsewhere
    are ignored. This prevents classifying every non-due memory as dropped.
    """
    live, budget, emitted, dropped = 15, s.budget, 0, 0
    reward, spent, shock_removed, refill_added = 0.0, 0, 0, 0
    actions_at = {float(row["time"]): row for row in trace}
    assert len(actions_at) == len(trace)
    enriched = []
    pre_shock = None
    values = np.asarray(s.values)
    for t in s.events():
        budget, removed, added = exogenous(s, t, budget)
        shock_removed += removed
        refill_added += added
        if t >= s.horizon-EPS:
            break
        valid, due = legal_actions(s, t, live, budget)
        if not due.any():
            assert t not in actions_at
            continue
        row = actions_at[t]
        digits = np.array(row["action"], dtype=int)
        matching = np.flatnonzero(np.all(ACTION_DIGITS == digits, axis=1))
        assert len(matching) == 1 and valid[matching[0]]
        before_live = live
        assert row["budget_before"] == budget
        for item in np.flatnonzero(due):
            if digits[item] == 0:
                live &= ~(1 << int(item))
                dropped |= 1 << int(item)
            elif digits[item] == 2:
                live &= ~(1 << int(item))
                emitted |= 1 << int(item)
                reward += values[item]*np.exp(-s.early_penalty*(s.horizon-t))
        cost = int(np.count_nonzero(digits))
        budget -= cost
        spent += cost
        assert budget == row["budget_after"] and cost == row["cost"]
        enriched.append({**row, "due_mask": due.tolist(), "live_before": before_live,
                         "live_after": live})
        if s.profile == "A" and abs(t-1.0) < EPS:
            pre_shock = {"action": digits.tolist(),
                         "renewals": int(np.sum(digits[due] == 1)),
                         "emissions": int(np.sum(digits[due] == 2)),
                         "drops": int(np.sum(digits[due] == 0)),
                         "emitted_value": float(values[digits == 2].sum())}
    retained = np.array([(live >> i) & 1 for i in range(4)], dtype=bool)
    emitted_mask = np.array([(emitted >> i) & 1 for i in range(4)], dtype=bool)
    dropped_mask = np.array([(dropped >> i) & 1 for i in range(4)], dtype=bool)
    assert np.all(retained.astype(int)+emitted_mask.astype(int)+dropped_mask.astype(int) == 1)
    terminal_value = float(values[retained].sum())
    reward += terminal_value
    assert abs(reward-utility) < 1e-9
    assert reward <= oracle+1e-8 and budget >= 0
    assert budget == s.budget + refill_added - shock_removed - spent
    k = int(retained.sum())
    top2 = np.argsort(values)[-2:]
    topk = float(np.sort(values)[-k:].sum()) if k else 0.0
    return {
        "utility": float(utility), "oracle_utility": float(oracle),
        "normalized_utility": float(utility/oracle) if oracle else 1.0,
        "regret": float(oracle-utility), "terminal_live_mask": live,
        "emitted_mask": emitted, "dropped_mask": dropped,
        "retained_count": k, "retained_value": terminal_value,
        "retained_mean_value": float(values[retained].mean()) if k else None,
        "retained_top2_fraction": float(retained[top2].mean()),
        "retained_top2_excess_over_uniform_same_count": float(retained[top2].mean()-k/4),
        "retained_value_excess_over_uniform_same_count": float(terminal_value-k*values.mean()),
        "retained_value_fraction_of_topk": terminal_value/topk if k else None,
        "retained_or_emitted_top2_fraction": float((retained | emitted_mask)[top2].mean()),
        "budget_final": budget, "spent": spent,
        "shock_removed": shock_removed, "refill_added": refill_added,
        "pre_shock_action": pre_shock, "trace": enriched,
    }


def worker_init(cache_path):
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    install_cache(cache_path)


def evaluate_job(job):
    variant, seed, destination = job
    begun = time.perf_counter()
    scenarios, _, _ = make_scenarios()
    model, checkpoint_hash = load_model(variant, seed)
    result = tc.evaluate_closed_loop(model, scenarios, seed=seed+920_000,
                                    mode="expected", keep_trace=True)
    episodes = [reconstruct_episode(s, trace, value, oracle)
                for s, trace, value, oracle in zip(scenarios, result["traces"],
                  result["episode_utility"], result["episode_oracle"])]
    payload = {"schema": "rrsnn.paired-counterfactual-run.v1", "variant": variant,
               "seed": seed, "checkpoint_sha256": checkpoint_hash,
               "mode": "expected", "scope": "exploratory frozen weights",
               "scenario_order": "sample then A_shock0,A_shock2,B_shock0,B_shock2",
               "result": result, "episodes": episodes,
               "elapsed_seconds": time.perf_counter()-begun}
    path = Path(destination) / f"{variant}_seed_{seed}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
    return {"variant": variant, "seed": seed, "path": str(path),
            "seconds": payload["elapsed_seconds"],
            "normalized_utility": result["normalized_utility_mean"]}


class PairedSummary:
    def __init__(self, replicates=2000):
        rng = np.random.default_rng(72002)
        self.seed_indices = rng.integers(0, len(SEEDS), (replicates, len(SEEDS)))
        self.value_indices = rng.integers(0, N_VALUES, (replicates, N_VALUES))

    def metric(self, arr):
        arr = np.asarray(arr, dtype=float)
        assert arr.shape == (len(SEEDS), N_VALUES) and np.isfinite(arr).all()
        seed_averaged = arr[self.seed_indices].mean(axis=1)
        boot = np.take_along_axis(seed_averaged, self.value_indices, axis=1).mean(axis=1)
        means = arr.mean(axis=1)
        return {"mean": float(arr.mean()), "seed_means": means.tolist(),
                "seed_sd": float(means.std(ddof=1)),
                "two_way_bootstrap_95_percentile_interval": np.quantile(boot, [.025, .975]).tolist()}


def aggregate(destination, metadata, cache_info, source_hashes, cache_check, elapsed):
    summary = PairedSummary()
    runs = {}
    for variant in tc.VARIANTS:
        runs[variant] = []
        for seed in SEEDS:
            path = destination / f"{variant}_seed_{seed}.json.gz"
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                runs[variant].append(json.load(handle))
    scalar_metrics = ("utility", "normalized_utility", "regret", "retained_count",
                      "retained_value", "retained_top2_fraction",
                      "retained_top2_excess_over_uniform_same_count",
                      "retained_value_excess_over_uniform_same_count",
                      "retained_or_emitted_top2_fraction")
    arrays = {variant: {metric: np.asarray([[ep[metric] for ep in run["episodes"]]
                   for run in rr]).reshape(len(SEEDS), N_VALUES, 4)
               for metric in scalar_metrics} for variant, rr in runs.items()}
    rows = []
    for variant in tc.VARIANTS:
        a = arrays[variant]
        u = a["utility"]
        nu = a["normalized_utility"]
        delta = u-arrays[REFERENCE]["utility"]
        ndelta = nu-arrays[REFERENCE]["normalized_utility"]
        changed, renewal_delta, emission_delta, drop_delta, emit_value_delta = [], [], [], [], []
        for run in runs[variant]:
            cr, re, em, dr, ev = [], [], [], [], []
            for i in range(N_VALUES):
                p0 = run["episodes"][4*i]["pre_shock_action"]
                p2 = run["episodes"][4*i+1]["pre_shock_action"]
                assert p0 is not None and p2 is not None
                cr.append(p0["action"] != p2["action"])
                re.append(p2["renewals"]-p0["renewals"])
                em.append(p2["emissions"]-p0["emissions"])
                dr.append(p2["drops"]-p0["drops"])
                ev.append(p2["emitted_value"]-p0["emitted_value"])
            changed.append(cr); renewal_delta.append(re); emission_delta.append(em)
            drop_delta.append(dr); emit_value_delta.append(ev)
        interaction = (u[:,:,1]-u[:,:,0])-(u[:,:,3]-u[:,:,2])
        baseline_u = arrays[REFERENCE]["utility"]
        baseline_interaction = ((baseline_u[:,:,1]-baseline_u[:,:,0])-
                                (baseline_u[:,:,3]-baseline_u[:,:,2]))
        row = {"variant": variant,
               "by_condition": {condition: {metric: summary.metric(a[metric][:,:,j])
                       for metric in scalar_metrics} for j, condition in enumerate(CONDITIONS)},
               "all_conditions_mean": {metric: summary.metric(a[metric].mean(axis=2))
                                       for metric in scalar_metrics},
               "shock_x_maturity_utility_interaction": summary.metric(interaction),
               "shock_x_maturity_utility_interaction_minus_reference": summary.metric(interaction-baseline_interaction),
               "announced_shock_changes_A_t1_action_fraction": summary.metric(changed),
               "A_t1_shock2_minus_shock0_renewals": summary.metric(renewal_delta),
               "A_t1_shock2_minus_shock0_emissions": summary.metric(emission_delta),
               "A_t1_shock2_minus_shock0_drops": summary.metric(drop_delta),
               "A_t1_shock2_minus_shock0_emitted_value": summary.metric(emit_value_delta),
               "paired_reference": REFERENCE,
               "utility_delta_vs_reference": summary.metric(delta.mean(axis=2)),
               "normalized_utility_delta_vs_reference": summary.metric(ndelta.mean(axis=2)),
               "utility_delta_vs_reference_by_condition": {name: summary.metric(delta[:,:,j])
                    for j, name in enumerate(CONDITIONS)},
               "negative_transfer_episode_fraction": summary.metric((delta < -1e-9).mean(axis=2)),
               "positive_transfer_episode_fraction": summary.metric((delta > 1e-9).mean(axis=2)),
               "equal_utility_episode_fraction": summary.metric((np.abs(delta) <= 1e-9).mean(axis=2)),
               "negative_transfer_value_group_fraction": summary.metric((delta.mean(axis=2) < -1e-9).astype(float)),
               "retained_value_excess_delta_vs_reference": summary.metric((
                    a["retained_value_excess_over_uniform_same_count"]-
                    arrays[REFERENCE]["retained_value_excess_over_uniform_same_count"]).mean(axis=2)),
               "checkpoint_hashes": {str(r["seed"]): r["checkpoint_sha256"] for r in runs[variant]}}
        rows.append(row)
    oracle = np.array(runs[REFERENCE][0]["result"]["episode_oracle"]).reshape(N_VALUES, 4)
    oracle_interaction = (oracle[:,1]-oracle[:,0])-(oracle[:,3]-oracle[:,2])
    result = {
        "schema": "rrsnn.paired-counterfactual-summary.v1",
        "evidence_level": "Exploratory frozen-weight synthetic paired diagnostic; not new confirmatory model selection.",
        "seeds": list(SEEDS), "samples": N_VALUES, "conditions": list(CONDITIONS),
        "episodes_per_run": 512, "runs": len(rows)*len(SEEDS),
        "mode": "expected", "reference": REFERENCE,
        "reference_selection": "Pre-existing lowest mean validation oracle-set NLL among seven baselines; unchanged.",
        "pair_verification": metadata, "dp_cache": cache_info,
        "original_evaluator_vs_cached_evaluator": cache_check,
        "frozen_source_hashes": source_hashes,
        "utility_interaction_definition": "(U_A_shock2-U_A_shock0)-(U_B_shock2-U_B_shock0)",
        "negative_transfer_definition": "Same seed/value/condition achieved utility below ctrnn_budget by more than1e-9; distinct from intrinsic task loss due to shock.",
        "high_value_retention_definition": "Terminal retained sum minus k/4 times total initial value, where k is retained count; zero is uniform item selection at the same count. Top2 excess is retained top2 fraction minus k/4. Emitted items are separately included in retained_or_emitted_top2_fraction.",
        "uncertainty": "Exploratory 2000-replicate crossed two-way bootstrap: resample the5 training seeds and128 value groups independently, preserving all4conditions and paired models. Few training seeds, no multiplicity correction, no population causal/superiority claim.",
        "oracle_by_condition": {name: float(oracle[:,j].mean()) for j,name in enumerate(CONDITIONS)},
        "oracle_utility_interaction_mean": float(oracle_interaction.mean()),
        "oracle_utility_interaction_value_sd": float(oracle_interaction.std(ddof=1)),
        "rows": rows,
        "limitations": [
            "Known and announced schedule, only maturity-time actions; anticipatory response means changing A actions at t1 after the t0 forecast, not predicting an unannounced shock.",
            "Expected-mode observation-grid neural proxies, not exact continuous-time R1 spike networks.",
            "Maturity changes feasible actions and optimal task utility; raw A/B differences are not evidence of architectural benefit.",
            "Primary comparative quantities are paired differences versus the fixed strong baseline and each episode's own task oracle.",
            "Legal masks ensure budget feasibility for every model; absence of overdrafts is not learned risk control.",
            "Retained-item metrics alone omit early output value; utility includes both discounted emissions and terminal retained value.",
            "128 synthetic value groups and5 fitted seeds; not real future windows or Hepta Cell validation.",
        ],
        "total_elapsed_seconds": elapsed,
    }
    (destination/"summary.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    return result


def main(workers=4):
    begun = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = json.loads((ROOT/"results/source_freeze.json").read_text())
    for name, expected in frozen.items():
        assert digest(ROOT/name) == expected, f"Frozen source changed: {name}"
    existing = json.loads((ROOT/"results/aggregate.json").read_text())
    assert existing["selected_reference_baseline"] == REFERENCE
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    scenarios, scenario_metadata, checks = make_scenarios()
    (OUT/"scenarios.json").write_text(json.dumps(scenario_metadata, indent=2)+"\n")
    cache_path = OUT/"original_oracle_readonly_cache.pkl"
    cache_info = create_cache(scenarios, cache_path)
    print(json.dumps({"stage": "cache_ready", **cache_info}), flush=True)
    # A small implementation equivalence check, not an additional task/model test.
    model, _ = load_model(REFERENCE, SEEDS[0])
    original = tc.evaluate_closed_loop(model, scenarios[:8], seed=920101,
                                      mode="expected", keep_trace=True)
    install_cache(cache_path)
    cached = tc.evaluate_closed_loop(model, scenarios[:8], seed=920101,
                                    mode="expected", keep_trace=True)
    keys = [k for k in original if k != "elapsed_seconds_with_oracle_and_prefix_replay"]
    assert all(original[k] == cached[k] for k in keys)
    cache_check = {"episodes": 8, "identical_all_outputs_except_elapsed_time": True,
                   "evaluator_source_unchanged": True}
    jobs = [(variant, seed, str(OUT)) for variant in tc.VARIANTS for seed in SEEDS]
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"),
            initializer=worker_init, initargs=(str(cache_path),)) as pool:
        pending = [pool.submit(evaluate_job, job) for job in jobs]
        for completed, future in enumerate(as_completed(pending), start=1):
            info = future.result()
            print(json.dumps({"completed": completed, "total": len(jobs), **info}), flush=True)
    for name, expected in frozen.items():
        assert digest(ROOT/name) == expected, f"Frozen source changed during evaluation: {name}"
    result = aggregate(OUT, checks, cache_info, frozen, cache_check, time.perf_counter()-begun)
    print(json.dumps({"stage": "complete", "path": str(OUT/"summary.json"),
                      "seconds": result["total_elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    main(args.workers)
