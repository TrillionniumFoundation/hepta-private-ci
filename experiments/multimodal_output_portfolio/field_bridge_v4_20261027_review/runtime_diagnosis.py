"""Exploratory V3 runtime diagnosis and a bounded, source-honest offline pilot.

Reads only released runtime_fit/runtime_select/runtime_audit evidence.
No model, observer, native-kernel, network or protected-source execution.
Existing V3 gates remain immutable. A tree oracle is a hindsight upper bound.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
from statistics import NormalDist
import time

import numpy as np

SEEDS = (17, 29, 43)
ARMS = ("fixed", "current", "history", "native", "reset_native")
CONDS = ("heavy_noise", "missing", "occlusion", "clean")
OBS = ("reward", "audit")
METRICS = ("net_utility", "image_fact", "text_fact", "relation",
           "crossmodal_disagreement", "pixel_mse")
NODES = ((0,), tuple(range(1, 5)), tuple(range(5, 21)))
WEIGHTS = {"image_fact": .35, "text_fact": .30, "relation": .15,
           "crossmodal_disagreement": .10, "pixel_mse": .10}
SPLIT_SALT = "v4-runtime-source-honesty-exploratory-20261027"
PILOT_CONTROLLERS = {}
INPUTS, COUNTERS = {}, {"ridge_solves": 0, "matrix_covariance_eigensolves": 0,
                       "audit_rows": 0, "bank_trees": 0}

def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def bind(path):
    path = Path(path)
    INPUTS[str(path)] = {"bytes": path.stat().st_size, "sha256": file_sha(path)}
    return path

def read(path):
    return json.loads(bind(path).read_text())

def array_sha(value):
    return hashlib.sha256(np.asarray(value, dtype="<f8").tobytes()).hexdigest()

def choose(head, features):
    z = (features - np.asarray(head["normalizer"]["mean"])) / np.asarray(head["normalizer"]["scale"])
    return np.einsum("bi,ij->bj", np.column_stack((z, np.ones(len(z)))),
                     np.asarray(head["coefficient"]), optimize=False)

def rollout(heads, x, values):
    nodes = np.zeros(len(x), dtype=np.int64)
    live = np.ones(len(x), dtype=bool)
    paths = [[] for _ in range(len(x))]
    for stage in range(3):
        rows = np.flatnonzero(live)
        if not len(rows):
            break
        actions = choose(heads[stage], x[rows, nodes[rows]]).argmax(1)
        for row, action in zip(rows, actions, strict=True):
            paths[row].append(int(action))
        moving = rows[actions != 0]
        nodes[moving] = 4 * nodes[moving] + actions[actions != 0]
        live[rows[actions == 0]] = False
    return values[np.arange(len(x)), nodes], nodes, paths

def action_matrices(heads, x):
    return [choose(heads[s], x[:, ns].reshape(-1, x.shape[-1])).argmax(1)
            .reshape(len(x), len(ns)) for s, ns in enumerate(NODES)]

def ridge(x, y, alpha, stage):
    mean, scale = x.mean(0), np.maximum(x.std(0), 1e-6)
    z = np.column_stack(((x - mean) / scale, np.ones(len(x))))
    gram = z.T @ z
    gram[np.arange(x.shape[1]), np.arange(x.shape[1])] += alpha
    beta = np.linalg.solve(gram, z.T @ y)
    COUNTERS["ridge_solves"] += 1
    return {"stage": stage, "normalizer": {"mean": mean, "scale": scale},
            "coefficient": beta, "alpha": alpha, "fit_rows": len(x)}

def fit_stages(x, values, alpha, rows_by_stage):
    heads, continuation = [None] * 3, values.copy()
    for stage in (2, 1, 0):
        nodes = np.asarray(NODES[stage])
        y = np.stack((values[:, nodes], *[
            continuation[:, 4 * nodes + a] for a in range(1, 5)]), axis=-1)
        rows = rows_by_stage[stage]
        heads[stage] = ridge(x[rows][:, nodes].reshape(-1, x.shape[-1]),
                             y[rows].reshape(-1, 5), alpha, stage)
        a = choose(heads[stage], x[:, nodes].reshape(-1, x.shape[-1])).argmax(1)
        a = a.reshape(len(x), -1)
        continuation[:, nodes] = np.take_along_axis(y, a[..., None], axis=-1)[..., 0]
    actual, _, _ = rollout(heads, x, values)
    assert np.array_equal(actual, continuation[:, 0]), "Own-tail backward/forward mismatch"
    return heads

def spectrum(x):
    centered = x - x.mean(0)
    scale = np.maximum(x.std(0), 1e-6)
    z = centered / scale
    eigen = np.maximum(np.linalg.eigvalsh(z.T @ z / len(z)), 0.)
    COUNTERS["matrix_covariance_eigensolves"] += 1
    return {"columns": x.shape[1], "varying_columns_std_gt_1e_minus6": int((x.std(0) > 1e-6).sum()),
            "covariance_rank_relative_1e_minus10": int((eigen > max(eigen.max(), 1e-300) * 1e-10).sum()),
            "participation_ratio": float(eigen.sum() ** 2 / (eigen @ eigen)) if eigen @ eigen else 0.,
            "nonzero_fraction": float(np.mean(x != 0)),
            "rms": float(np.sqrt(np.mean(x * x)))}

def feature_diagnostics(train, select, controller):
    rep = controller["representation"]
    raw_width = 16 if rep == "current" else 48
    results = []
    for stage, ns in enumerate(NODES):
        tx = train[:, ns].reshape(-1, train.shape[-1])
        sx = select[:, ns].reshape(-1, select.shape[-1])
        head = controller["heads"][stage]
        full = choose(head, sx)
        muted = sx.copy()
        muted[:, raw_width:] = np.asarray(head["normalizer"]["mean"])[raw_width:]
        changed = choose(head, muted).argmax(1) != full.argmax(1)
        results.append({"stage": stage, "training_rows": len(tx), "selection_rows": len(sx),
            "training_full": spectrum(tx), "training_extra": spectrum(tx[:, raw_width:]),
            "selection_full": spectrum(sx), "selection_extra": spectrum(sx[:, raw_width:]),
            "mean_fitted_extra_ablation_changes_on_selection": int(changed.sum()),
            "ablation_scope": "At fixed existing heads only; sensitivity diagnostic, not a refitted baseline"})
    return results

def groups(source_ids):
    pairs = [tuple(pair) for pair in source_ids.tolist()]
    unique = sorted(set(pairs), key=lambda p: hashlib.sha256(
        (SPLIT_SALT + json.dumps(p, separators=(",", ":"))).encode()).hexdigest())
    assigned = {pair: i % 3 for i, pair in enumerate(unique)}
    row_group = np.asarray([assigned[pair] for pair in pairs])
    rows = {2: np.flatnonzero(row_group == 0), 1: np.flatnonzero(row_group == 1),
            0: np.flatnonzero(row_group == 2)}
    sets = {s: {pairs[i] for i in r} for s, r in rows.items()}
    assert len(unique) == 128 and all(len(r) == 4 * len(sets[s]) for s, r in rows.items())
    assert not (sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])
    return rows, {"salt": SPLIT_SALT, "whole_source_pair_groups": True,
                  "pairs_per_stage": {str(s): len(v) for s, v in sets.items()},
                  "row_assignment_sha256": array_sha(row_group)}

def freeze_heads(heads):
    return [{"stage": h["stage"], "alpha": h["alpha"], "fit_rows": h["fit_rows"],
             "normalizer": {k: np.asarray(v).tolist() for k, v in h["normalizer"].items()},
             "coefficient": np.asarray(h["coefficient"]).tolist()} for h in heads]

def compact_values(v, baseline, oracle, conditions):
    delta, regret = v - baseline, oracle - v
    return {"mean": float(v.mean()), "over_selected_fixed": float(delta.mean()),
            "clairvoyant_regret": float(regret.mean()), "over_fixed_positive_cases": int((delta > 0).sum()),
            "over_fixed_negative_cases": int((delta < 0).sum()),
            "per_condition_over_fixed": {c: float(delta[conditions == c].mean()) for c in CONDS}}

def bank_analysis(root, seed):
    directory = root / "runtime"
    fitted = read(directory / "fit" / f"{seed}-frozen" / "READOUTS.json")
    banks = {}
    for role in ("runtime_fit", "runtime_select"):
        with np.load(bind(directory / "bank" / f"{seed}-frozen" / role / "bank.npz"), allow_pickle=False) as z:
            banks[role] = {k: z[k] for k in z.files}
    train, selection = banks["runtime_fit"], banks["runtime_select"]
    assert train["events"].shape == (512, 21, 16) and selection["events"].shape == (256, 21, 16)
    assert not (set(train["source_ids"].ravel()) & set(selection["source_ids"].ravel()))
    COUNTERS["bank_trees"] += len(train["events"]) + len(selection["events"])
    fixed = fitted["fixed_policy"]["node"]
    rows, partition = groups(train["source_ids"])
    result = {"seed": seed, "fixed_node": fixed, "partition": partition, "banks": {},
              "selected_features": {}, "selected_comparisons": {}, "offline_pilots": {}}
    for role, bank in banks.items():
        values = bank["terminal_values"]
        result["banks"][role] = {"trees": len(values), "unique_source_pairs": len(set(map(tuple, bank["source_ids"]))),
            "root_stop_mean": float(values[:, 0].mean()), "fixed_mean": float(values[:, fixed].mean()),
            "clairvoyant_mean": float(values.max(1).mean()),
            "clairvoyant_over_fixed": float((values.max(1) - values[:, fixed]).mean()),
            "mean_within_case_range": float(np.ptp(values, axis=1).mean()), "selected": {}}
    original, matrices = {}, {}
    feature_path = bind(directory / "fit" / f"{seed}-frozen" / "features.npz")
    assert INPUTS[str(feature_path)]["sha256"] == fitted["feature_evidence"]["sha256"]
    with np.load(feature_path, allow_pickle=False) as packed:
        for rep in ("current", "history", "native", "reset_native"):
            controller = fitted["models"][rep]
            assert controller["authority"] == "DENY_ALL" and controller["native_owner_integration"] is False
            transform = controller["transform"]["name"]
            tx, sx = packed[f"{transform}.{rep}.train"], packed[f"{transform}.{rep}.selection"]
            candidate = next(c for c in fitted["candidates"] if c["representation"] == rep
                             and c["candidate_index"] == fitted["selected"][rep]["candidate_index"])
            original[rep] = {}
            for label, role, x in (("training", "runtime_fit", tx), ("selection", "runtime_select", sx)):
                bank = banks[role]
                v, nodes, paths = rollout(controller["heads"], x, bank["terminal_values"])
                assert nodes.tolist() == candidate[label + "_terminal_nodes"]
                assert float(v.mean()) == candidate[label + "_mean_value"]
                original[rep][role] = {"v": v, "nodes": nodes, "paths": paths}
                result["banks"][role]["selected"][rep] = compact_values(
                    v, bank["terminal_values"][:, fixed], bank["terminal_values"].max(1), bank["conditions"])
            result["selected_features"][rep] = {
                "transform": transform, "alpha": controller["alpha"],
                "stages": feature_diagnostics(tx, sx, controller)}
            if rep in ("history", "native"):
                matrices[rep] = (tx, sx)
                baseline_heads = fit_stages(tx, train["terminal_values"], controller["alpha"],
                                           {s: np.arange(len(tx)) for s in range(3)})
                max_error = max(float(np.max(np.abs(baseline_heads[s]["coefficient"] -
                                                    np.asarray(controller["heads"][s]["coefficient"]))))
                                for s in range(3))
                assert max_error <= 1e-7
                baseline_v, baseline_nodes, _ = rollout(baseline_heads, sx, selection["terminal_values"])
                assert np.array_equal(baseline_nodes, original[rep]["runtime_select"]["nodes"])
                honest = fit_stages(tx, train["terminal_values"], controller["alpha"], rows)
                pilot = {"name": "source-disjoint stage-label pilot", "alpha": controller["alpha"],
                         "feature_width": 88, "head_coefficients": 1335,
                         "baseline_reconstruction_max_coefficient_error": max_error, "results": {}}
                for role, x in (("runtime_fit", tx), ("runtime_select", sx)):
                    bank = banks[role]
                    v, nodes, paths = rollout(honest, x, bank["terminal_values"])
                    pilot["results"][role] = compact_values(v, bank["terminal_values"][:, fixed],
                                                           bank["terminal_values"].max(1), bank["conditions"])
                    pilot["results"][role]["over_original_selected_policy"] = float(
                        (v - original[rep][role]["v"]).mean())
                    pilot["results"][role]["terminal_nodes_sha256"] = array_sha(nodes)
                result["offline_pilots"][rep + "_honest_stages"] = pilot
                PILOT_CONTROLLERS[f"{seed}:{rep}_honest_stages"] = {
                    "seed": seed, "representation": rep, "feature_width": 88,
                    "original_transform": controller["transform"], "fourier": controller["fourier"],
                    "heads": freeze_heads(honest), "partition": partition,
                    "source_readout_sha256": INPUTS[str(directory / "fit" / f"{seed}-frozen" / "READOUTS.json")]["sha256"],
                    "later_heads_refitted_after_targets": False, "authority": "DENY_ALL"}
        transform = fitted["models"]["native"]["transform"]["name"]
        result["matched_native_reset_extra"] = []
        a, b = packed[f"{transform}.native.train"], packed[f"{transform}.reset_native.train"]
        assert np.array_equal(a[:, 0], b[:, 0])
        for stage, ns in enumerate(NODES):
            d = a[:, ns, 48:] - b[:, ns, 48:]
            result["matched_native_reset_extra"].append({"stage": stage,
                "different_rows": int(np.any(d != 0, axis=-1).sum()), "rows": int(np.prod(d.shape[:-1])),
                "rms_difference": float(np.sqrt(np.mean(d * d)))})
    raw_train, raw_select = (matrices["history"][0][:, :, :48], matrices["history"][1][:, :, :48])
    assert np.array_equal(raw_train, matrices["native"][0][:, :, :48])
    raw = fit_stages(raw_train, train["terminal_values"], 1., {s: np.arange(len(raw_train)) for s in range(3)})
    PILOT_CONTROLLERS[f"{seed}:raw_history_linear"] = {
        "seed": seed, "representation": "raw_history", "feature_width": 48,
        "heads": freeze_heads(raw), "later_heads_refitted_after_targets": False,
        "feature_rule": "left-aligned zero-padded causal public history, three rounds of sixteen values",
        "authority": "DENY_ALL"}
    result["offline_pilots"]["raw_history_linear"] = {"feature_width": 48, "head_coefficients": 735,
                                                     "alpha": 1., "results": {}}
    for role, x in (("runtime_fit", raw_train), ("runtime_select", raw_select)):
        bank = banks[role]
        v, nodes, paths = rollout(raw, x, bank["terminal_values"])
        result["offline_pilots"]["raw_history_linear"]["results"][role] = compact_values(
            v, bank["terminal_values"][:, fixed], bank["terminal_values"].max(1), bank["conditions"])
    for role in banks:
        a, b = original["native"][role], original["history"][role]
        result["selected_comparisons"][role] = {
            "native_minus_history": float((a["v"] - b["v"]).mean()),
            "same_terminal_nodes": int(np.sum(a["nodes"] == b["nodes"])),
            "same_complete_action_paths": sum(x == y for x, y in zip(a["paths"], b["paths"], strict=True)),
            "cases": len(a["v"])}
    return result

def audit_analysis(root):
    scores = np.full((3, 5, 4, 512, 2, 6), np.nan)
    actions, sources, depths = {}, {}, np.full((3, 5, 4, 512), -1, dtype=int)
    for si, seed in enumerate(SEEDS):
        path = bind(root / "runtime" / "audit" / f"{seed}-frozen" / "selected" / "rows.jsonl.gz")
        with gzip.open(path, "rt") as stream:
            for line in stream:
                row = json.loads(line)
                assert row["role"] == "runtime_audit" and row["profile"] == "frozen" and row["seed"] == seed
                assert row["unchosen_continuations_executed"] == 0
                ai, ci, pi = ARMS.index(row["arm"]), CONDS.index(row["condition"]), row["pair_index"]
                assert np.isnan(scores[si, ai, ci, pi]).all()
                scores[si, ai, ci, pi] = [[row["scores"][o][m] for m in METRICS] for o in OBS]
                actions[si, ai, ci, pi] = tuple(row["actions"])
                depths[si, ai, ci, pi] = row["depth"]
                sources.setdefault(pi, tuple(row["source_ids"]))
                assert sources[pi] == tuple(row["source_ids"])
                COUNTERS["audit_rows"] += 1
    assert np.isfinite(scores).all() and COUNTERS["audit_rows"] == 30720
    shared_error = float(np.max(np.abs(scores[:, :, :, :, 0, [2, 3, 5]] -
                                      scores[:, :, :, :, 1, [2, 3, 5]])))
    assert shared_error == 0
    result = {"conditions": CONDS, "metric_order": METRICS, "observer_order": OBS,
              "shared_text_relation_pixel_max_observer_difference": shared_error, "arms": {}, "comparisons": {}}
    for ai, arm in enumerate(ARMS):
        a = scores[:, ai]
        result["arms"][arm] = {"mean_metrics": a.mean((0, 1, 2)).tolist(),
            "per_seed_net": a[:, :, :, :, 0].mean((1, 2)).tolist(),
            "mean_revisions": float(depths[:, ai].mean()),
            "action_counts_by_decision": [[sum(len(v) > s and v[s] == action
                for (si0, ai0, ci, pi), v in actions.items() if ai0 == ai)
                for action in range(5)] for s in range(3)]}
    for left, right in (("native", "fixed"), ("native", "history"), ("native", "reset_native"), ("history", "fixed")):
        a, b = ARMS.index(left), ARMS.index(right)
        d = scores[:, a] - scores[:, b]
        pooled = d[:, :, :, :, 0].mean((0, 1))
        components = {metric: (-2 * weight * d[..., METRICS.index(metric)]).mean((0, 1, 2)).tolist()
                      for metric, weight in WEIGHTS.items()}
        cost = (-.002 * (depths[:, a] - depths[:, b])).mean()
        recon = np.asarray(list(components.values())).sum(0) + cost
        means = d[..., 0].mean((0, 1, 2))
        assert np.max(np.abs(recon - means)) < 1e-12
        observer_gap = means[0] - means[1]
        gap_components = {m: components[m][0] - components[m][1]
                          for m in ("image_fact", "crossmodal_disagreement")}
        assert abs(sum(gap_components.values()) - observer_gap) < 1e-12
        sd = pooled.std(0, ddof=1)
        critical = NormalDist().inv_cdf(1 - .05 / (2 * 4))
        planning = {}
        for power in (.8, .9):
            z_power = NormalDist().inv_cdf(power)
            planning[str(power)] = {str(delta): np.ceil(((critical + z_power) * sd / delta) ** 2).astype(int).tolist()
                                    for delta in (.001, .002)}
        result["comparisons"][left + "-" + right] = {
            "net_means": means.tolist(), "per_seed_net": d[..., 0].mean((1, 2)).tolist(),
            "per_condition_net": {c: d[:, ci, :, :, 0].mean((0, 1)).tolist() for ci, c in enumerate(CONDS)},
            "source_pair_standard_deviation": sd.tolist(),
            "observer_delta_correlation": float(np.corrcoef(pooled.T)[0, 1]),
            "same_action_paths": sum(actions[si, a, ci, pi] == actions[si, b, ci, pi]
                                     for si in range(3) for ci in range(4) for pi in range(512)),
            "paired_episodes": 6144, "utility_components": components, "revision_cost_component": float(cost),
            "reward_minus_audit_delta": float(observer_gap), "observer_gap_components": gap_components,
            "fixed_n_normal_approximation_per_observer": planning,
            "planning_scope": "Hindsight scale estimate only, fixed models/conditions; not a power guarantee, not sequential sampling, does not enforce per-seed sign or all noninferiority conditions"}
    original = read(root / "INDEPENDENT_RUNTIME_RESULTS-frozen.json")
    result["original_frozen_runtime_gate_receipt_sha256"] = INPUTS[str(root / "INDEPENDENT_RUNTIME_RESULTS-frozen.json")]["sha256"]
    result["original_gate_passed"] = original["passed"]
    assert original["passed"] is False
    return result

def execute(root, source_sha):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    result = {"schema": "hepta.field-bridge.v4.runtime-exploration.1",
        "status": "exploratory_complete", "source_sha256": source_sha,
        "study_scope": "Released V3 runtime data only. No new scientific qualification or confirmatory evidence.",
        "scientific_gate_changed": False, "protected_roles_accessed": [],
        "offline_pilot_contract": {"honest_stage_groups": "stage2 group0, stage1 group1, stage0 group2; paired sources kept intact",
            "fixed_candidate_count": 9, "honest_policies": 6, "raw_history_policies": 3,
            "no_pilot_selection_on_runtime_audit": True, "no_new_model_outputs": True,
            "raw_history_alpha": 1., "honest_transforms_and_alphas": "Previously selected V3 choices retained without search",
            "own_tail_targets": "Every target follows the same candidate frozen later heads",
            "scope_limits": ["Stage splits reduce per-head source count; no claim of budget-matched improvement.",
                "Native/history transforms were already selected using V3 selection data; all pilot results are post hoc.",
                "Oracle means reveal all 85 terminal outcomes per fit/select tree, unavailable to deployed controllers.",
                "Unchosen runtime_audit branches are absent and are never imputed or evaluated."]},
        "banks": [bank_analysis(root, seed) for seed in SEEDS],
        "audit": audit_analysis(root), "input_files": INPUTS, "pilot_parameters": PILOT_CONTROLLERS,
        "actual_new_work": {**COUNTERS, "generator_calls": 0, "observer_calls": 0,
            "native_tick_calls": 0, "network_calls": 0},
        "cost_scope": "This scripted diagnostic only; earlier schema and summary reads were separate and not timed.",
        "authority": "DENY_ALL", "requires_calibration": True, "native_owner_integration": False}
    result.update(wall_ns=time.perf_counter_ns() - started, cpu_ns=time.process_time_ns() - cpu)
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=Path("/tmp/hepta-field-v3-run"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-sha256")
    parser.add_argument("--controllers", type=Path)
    args = parser.parse_args()
    identity = args.source_sha256 or file_sha(__file__)
    result = execute(args.run.resolve(), identity)
    if args.controllers:
        assert args.output is not None and len(result["pilot_parameters"]) == 9
        data = (json.dumps(result.pop("pilot_parameters"), sort_keys=True, allow_nan=False) + "\n").encode()
        with args.controllers.open("xb") as stream:
            with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as encoded:
                encoded.write(data)
        result["pilot_parameters"] = {"path": str(args.controllers.resolve()), "candidates": 9,
            "sha256": file_sha(args.controllers), "bytes": args.controllers.stat().st_size,
            "uncompressed_sha256": hashlib.sha256(data).hexdigest(), "uncompressed_bytes": len(data)}
    if args.output:
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    else:
        print(json.dumps(result, sort_keys=True, allow_nan=False))
