"""Disjoint-source learned video continuation-value Cell with actual lazy CLIP work.

This estimates bounded next-pair correctness change, not general NDU/FBSDE.
One frozen four-exit Reader is shared by value, confidence and fixed baselines.
No label or future observation enters the online stopping interface.
"""
from __future__ import annotations

from pathlib import Path

import torch

from experiments.shared_stem_cell import execution as e, media_execution as media
from experiments.shared_stem_cell import video_anytime as anytime
from experiments.shared_stem_cell import video_temporal as temporal

COSTS = (0.0, 0.005, 0.02, 0.05, 0.10, 0.20)
RIDGE = 0.5
DEPTHS = anytime.DEPTHS
ARMS = ("value", "cache_value", "confidence", "fixed_2", "fixed_4", "fixed_6", "fixed_8")
# Accuracy-equivalent penalty for two extra recurrent steps even on cache hits.
# Experimental units, NOT measured seconds, joules, or calibrated hardware price.
STEP_PRICE = 0.005


def observable(p, depth):
    """Five current-state features, never the next frame or the correct answer."""
    if depth not in DEPTHS[:-1] or not isinstance(p, torch.Tensor):
        raise e.InputError("bounded current Reader depth/probabilities required")
    temporal.score(p, torch.zeros(len(p), dtype=torch.long))
    top = p.max(-1).values.double()
    margin = (p[:, 0] - p[:, 1]).abs().double()
    entropy = -(p.double() * p.double().clamp_min(1e-12).log()).sum(-1) / 0.6931471805599453
    return torch.stack((torch.ones_like(top), top, margin, entropy,
                        torch.full_like(top, depth / 8)), -1)


def fit_value(exits, labels):
    """Fit on source-disjoint critic rows; next-step labels only train the critic."""
    if set(exits) != set(DEPTHS) or not isinstance(labels, torch.Tensor) or labels.dtype != torch.long:
        raise e.InputError("complete separate critic split required")
    if not 2 <= len(labels) <= 64:
        raise e.InputError("bounded independent-source critic rows required")
    coefficients, diagnostics = {}, {}
    for depth in DEPTHS:
        temporal.score(exits[depth], labels)
    with e.measured() as cost:
        for depth in DEPTHS[:-1]:
            x = observable(exits[depth], depth)
            current = (exits[depth].argmax(-1) == labels).double()
            future = (exits[depth + 2].argmax(-1) == labels).double()
            delta = future - current
            gram = x.T @ x + RIDGE * torch.eye(x.shape[1], dtype=torch.float64)
            w = torch.linalg.solve(gram, x.T @ delta)
            residual = (gram @ w - x.T @ delta).abs().max().item()
            if not bool(torch.isfinite(w).all()) or residual > 1e-9:
                raise e.InputError("critic ridge residual not satisfied")
            coefficients[str(depth)] = [float(k) for k in w]
            diagnostics[str(depth)] = {"rows": len(delta), "target_mean_next_pair_correctness_change":
                                       float(delta.mean()), "ridge_equation_abs_max": residual,
                                       "target_positive": int((delta > 0).sum()),
                                       "target_negative": int((delta < 0).sum())}
    return {"schema": "hepta.video-value-critic.v1", "coefficients": coefficients,
            "diagnostics": diagnostics, "ridge": RIDGE, "fit_work": cost,
            "trained_with_critic_split_labels_only": True, "production_accepted": False}


def estimate(p, depth, critic):
    if not isinstance(critic, dict) or critic.get("schema") != "hepta.video-value-critic.v1":
        raise e.InputError("trained and bound value critic required")
    if str(depth) not in critic.get("coefficients", {}):
        raise e.InputError("missing per-depth critic")
    weights = critic["coefficients"][str(depth)]
    if (not isinstance(weights, list) or len(weights) != 5
            or any(type(x) is not float or not -10 < x < 10 for x in weights)):
        raise e.InputError("finite bounded critic parameters required")
    x = observable(p, depth)
    return (x @ torch.tensor(weights, dtype=torch.float64)).clamp(-1, 1)


def route_value(exits, critic, cost):
    if type(cost) is not float or cost not in COSTS or set(exits) != set(DEPTHS):
        raise e.InputError("predeclared bounded value price and exits required")
    n = len(exits[2])
    if not 1 <= n <= 256:
        raise e.InputError("bounded value route cardinality")
    for depth in DEPTHS:
        temporal.score(exits[depth], torch.zeros(n, dtype=torch.long))
    estimates = {depth: estimate(exits[depth], depth, critic) for depth in DEPTHS[:-1]}
    selected = []
    for row in range(n):
        for depth in DEPTHS:
            if depth == 8 or float(estimates[depth][row]) <= cost:
                selected.append((depth, int(exits[depth][row].argmax())))
                break
    return selected



def next_pair_marginal(known, row, depth):
    """Known content identities only; never reads unseen frame pixels or labels.

    FrameCacheTowers calls one physical vision forward for any missing member
    of the next two-frame chunk. Existing vision features make the call free,
    though two GRU updates and all metadata handling still incur work.
    """
    if (not isinstance(known, set) or not isinstance(row, list) or len(row) != 8
            or depth not in DEPTHS[:-1]
            or any(not isinstance(k, str) or len(k) != 64 or
                   any(ch not in "0123456789abcdef" for ch in k) for k in row)):
        raise e.InputError("exact bounded SHA identities required for marginal vision cost")
    next_pair = row[depth:depth+2]
    return int(any(k not in known for k in next_pair))


def cache_price(price, calls):
    if type(price) is not float or price not in COSTS or type(calls) is not int or calls not in (0, 1):
        raise e.InputError("declared bounded next-pair cost required")
    return STEP_PRICE + price*calls


def route_cache_value(exits, critic, price, frame_ids):
    """Replay an actual across-request SHA cache and only use current outputs.

    The next-frame *identity* is observable workload metadata but neither its
    visual content nor the next Reader state is available to the critic.
    """
    if type(price) is not float or price not in COSTS or set(exits) != set(DEPTHS):
        raise e.InputError("registered cache-value price/depths required")
    n = len(exits[2])
    if (not isinstance(frame_ids, list) or len(frame_ids) != n or not 1 <= n <= 256):
        raise e.InputError("complete cache-bound case rows required")
    for depth in DEPTHS:
        temporal.score(exits[depth], torch.zeros(n, dtype=torch.long))
    estimates = {d: estimate(exits[d], d, critic) for d in DEPTHS[:-1]}
    known, selected = set(), []
    for i, row in enumerate(frame_ids):
        # Validate ALL identity metadata before simulating any cache update.
        next_pair_marginal(set(), row, 2)
        for depth in DEPTHS:
            known.update(row[depth-2:depth])
            if (depth == 8 or float(estimates[depth][i]) <=
                    cache_price(price, next_pair_marginal(known, row, depth))):
                selected.append((depth, int(exits[depth][i].argmax())))
                break
    return selected


def _profile(frame_ids, picks, labels):
    cost = anytime.simulated_cache_work(frame_ids, picks)
    return {"correct": sum(int(guess == int(y)) for (_depth, guess), y in zip(picks, labels)),
            "cases": len(labels), "mean_depth": sum(d for d, _ in picks) / len(picks), **cost}


def _cost_order(profile, index):
    return (profile["unique_frames"], profile["physical_video_calls"],
            profile["requested_frame_rows"], -profile["correct"], index)


def nearest_rank_latency(rows):
    """Descriptive per-row samples only; 16 clustered observations have no tail CI."""
    values = sorted(r["wall"]["wall_ns"] for r in rows)
    if not values or any(type(v) is not int or v <= 0 for v in values):
        raise e.InputError("actual positive row-wall intervals required")
    return {f"p{p}": values[(len(values)*p + 99)//100-1] for p in (50,95,99)}


def select(exits, labels, frame_ids, critic):
    """One sealed calibration cohort decides BOTH continuation policy families."""
    fixed = {d: _profile(frame_ids,
        [(d, int(row.argmax())) for row in exits[d]], labels) for d in DEPTHS}
    floor = max(p["correct"] for p in fixed.values())
    fixed_depth = min(DEPTHS, key=lambda d: (-fixed[d]["correct"],
                        fixed[d]["unique_frames"], fixed[d]["physical_video_calls"], d))
    policies = {f"fixed_{d}": {"kind": "fixed", "depth": d} for d in DEPTHS}
    records = {f"fixed_{d}": fixed[d] for d in DEPTHS}
    grids = {}
    for family, values in (("confidence", anytime.THRESHOLDS), ("value", COSTS),
                           ("cache_value", COSTS)):
        grid = []
        for x in values:
            picks = (anytime.route(exits, float(x)) if family == "confidence" else
                     route_cache_value(exits, critic, float(x), frame_ids) if family == "cache_value" else
                     route_value(exits, critic, float(x)))
            grid.append({"setting": float(x), **_profile(frame_ids, picks, labels)})
        eligible = [i for i, row in enumerate(grid) if row["correct"] >= floor]
        if eligible:
            idx = min(eligible, key=lambda i: _cost_order(grid[i], i))
            policies[family] = {"kind": family,
                ("threshold" if family == "confidence" else "price"): grid[idx]["setting"]}
            records[family] = grid[idx]
        else:
            policies[family] = {"kind": "fixed", "depth": fixed_depth,
                "fallback_reason": "did_not_reach_best_fixed_calibration_correct_count"}
            records[family] = fixed[fixed_depth]
        grids[family] = grid
    # Equal-resource ties prefer the fixed baseline; no research-path promotion.
    selected = min(ARMS, key=lambda arm: (_cost_order(records[arm], 0)[:-1],
                   0 if policies[arm]["kind"] == "fixed" else 1,
                   ARMS.index(arm)))
    return {"schema": "hepta.video-value-policy.v1", "policies": policies,
            "calibration_profiles": records, "grids": grids,
            "best_fixed_depth": fixed_depth, "calibration_correct_floor": floor,
            "best_calibration_arm": selected, "selection_basis":
            "max_fixed_quality_floor_then_unique_frames_physical_calls_requested_rows",
            "calibration_source_independence_not_certified": True,
            "cache_value_step_price_accuracy_units": STEP_PRICE,
            "cache_value_vision_price_basis": "one marginal physical CLIP forward per next pair",
            "cache_value_cost_is_not_empirical_wall_or_energy": True,
            "value_critic_and_reader_train_on_separate_sources": True,
            "production_accepted": False}


@torch.no_grad()
def stream_one(model, frames, root, tower, policy, critic):
    """Incremental input: decision at 2,4,6 only observes earlier acquired frames."""
    if not isinstance(policy, dict) or policy.get("kind") not in ("fixed", "confidence", "value", "cache_value"):
        raise e.InputError("sealed bounded policy required")
    kind = policy["kind"]
    depth_limit = policy.get("depth") if kind == "fixed" else 8
    if kind == "fixed" and depth_limit not in DEPTHS:
        raise e.InputError("registered fixed reader depth required")
    if kind == "confidence" and (type(policy.get("threshold")) is not float
                                  or policy["threshold"] not in anytime.THRESHOLDS):
        raise e.InputError("registered confidence threshold required")
    if kind in ("value", "cache_value") and (type(policy.get("price")) is not float
                             or policy["price"] not in COSTS):
        raise e.InputError("registered value price required")
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise e.InputError("frozen Reader required")
    if not isinstance(frames, list) or len(frames) != 8:
        raise e.InputError("closed eight-frame reference list required")
    if kind == "cache_value":
        next_pair_marginal(set(), [f["sha256"] for f in frames], 2)
    state, exits = None, []
    with e.measured() as timing:
        for depth in DEPTHS:
            if depth > depth_limit: break
            chunk = frames[depth-2:depth]
            before = tower.physical_video_calls
            data, stamps = tower.encode("video", chunk, root)
            if (not isinstance(data, torch.Tensor) or data.shape != (2, model.project.in_features)
                or data.dtype != torch.float32 or not bool(torch.isfinite(data).all())
                or not torch.equal(stamps, torch.tensor([f["timestamp_us"] for f in chunk]))):
                raise e.InputError("stale or nonfinite incremental CLIP response")
            state, logits = model.step_pair(data, state)
            prob = logits.softmax(-1).float()
            temporal.score(prob, torch.zeros(1, dtype=torch.long))
            marginal = (next_pair_marginal(set(tower.cache),
                [f["sha256"] for f in frames], depth)
                if kind == "cache_value" and depth < 8 else None)
            critic_estimate = (float(estimate(prob, depth, critic)[0])
                if kind in ("value", "cache_value") and depth < 8 else None)
            stop = (depth == 8 or kind == "fixed" and depth == depth_limit or
                    kind == "confidence" and float(prob.max()) >= policy["threshold"] or
                    kind == "value" and critic_estimate is not None and
                        critic_estimate <= policy["price"] or
                    kind == "cache_value" and critic_estimate is not None and
                        critic_estimate <= cache_price(policy["price"], marginal))
            exits.append({"depth": depth, "probabilities": prob[0].tolist(),
                          "physical_pair_call_delta": tower.physical_video_calls - before,
                          "critic_value_estimate": critic_estimate,
                          "next_pair_physical_calls_if_continued": marginal,
                          "next_pair_price_accuracy_units":
                              cache_price(policy["price"], marginal)
                              if marginal is not None else None})
            if stop: break
    return {"depth": depth, "prediction": int(prob.argmax()),
            "probabilities": prob[0].tolist(), "exits_seen": exits, "wall": timing,
            "model_sha256": e.parameters(model)["sha256"]}


def run(manifest_path, output, *, _tower_factory=media.LocalTowers, microbatch_shadow=False):
    manifest_path, output = Path(manifest_path), Path(output)
    manifest_raw = manifest_path.read_bytes()
    config = e.decode(manifest_raw)
    if (config.get("schema") != "hepta.shared-stem-media.v1"
        or config.get("video_profile") != "paired_temporal_order_v1"
        or config.get("classes") != 2 or config.get("temporal") is not False
        or set(config.get("models", {})) != {"clip"}):
        raise e.InputError("closed public video training profile required")
    root = manifest_path.parent
    output.mkdir(parents=True, exist_ok=False)
    e.write_once(output / "plan.json", {"schema": "hepta.video-value-plan.v1",
        "manifest_sha256": e.sha(manifest_raw), "critic_prices": COSTS, "cache_step_price": STEP_PRICE,
        "reader_exits": DEPTHS, "ridge": RIDGE, "holdout_control_arms": ARMS,
        "split": "first four of six training sources for reader, final two for critic",
        "source_sha256": e.sha(Path(__file__).read_bytes()),
        "task": "same_real_frames_forward_vs_reversed", "production_accepted": False})
    try:
        cases, targets = media.read_cases(root, config["dataset"], 2)
        registered, pairs = temporal.cohort(root, config["cohort"])
        if ([c.case_id for c in cases] != [r["case_id"] for r in registered]
            or any(set(c.inputs) != {"video"} or len(c.inputs["video"]) != 8 for c in cases)):
            raise e.InputError("registered video ordering/coverage drift")
        source_to_split = {}
        for record in registered:
            original = source_to_split.setdefault(record["source_id"], record["split"])
            if original != record["split"]:
                raise e.InputError("source family overlap")
        train_sources = list(dict.fromkeys(r["source_id"] for r in registered if r["split"] == "train"))
        if len(train_sources) != 6:
            raise e.InputError("requires six original training sources")
        by = {"reader": [], "critic": [], "calibration": [], "holdout": []}
        for c, record in zip(cases, registered):
            group = ("reader" if record["source_id"] in train_sources[:4] else "critic"
                     if record["source_id"] in train_sources[4:] else c.split)
            by[group].append(c)
        if {k: len(v) for k,v in by.items()} != {"reader":32,"critic":16,"calibration":16,"holdout":16}:
            raise e.InputError("closed source-level critic/reader/calibration split")
        with e.measured() as loading:
            base = _tower_factory(root, config["models"])
            cache = temporal.FrameCacheTowers(base)
        with e.measured() as preparation:
            ordered = by["reader"] + by["critic"] + by["calibration"]
            all_features = media.extract(cache, ordered, root)["video"]
            slice_ = lambda lo, hi: tuple(t[lo:hi] for t in all_features)
            reader = slice_(0,32); critic_features = slice_(32,48); cal = slice_(48,64)
            y = lambda cohort: torch.tensor([targets[c.case_id] for c in cohort], dtype=torch.long)
            model, train_work = anytime.fit(reader, y(by["reader"]),
                steps=config.get("steps",80), seed=config.get("seed",17))
            critic_exits = anytime.probabilities(model, critic_features)
            value_critic = fit_value(critic_exits, y(by["critic"]))
            calibration_exits = anytime.probabilities(model, cal)
            cal_keys = [[f["sha256"] for f in c.inputs["video"]] for c in by["calibration"]]
            policy_selection = select(calibration_exits, y(by["calibration"]), cal_keys, value_critic)
        model_id = e.parameters(model)
        policy_selection.update({"model_sha256": model_id["sha256"],
            "manifest_sha256": e.sha(manifest_raw),
            "reader_ids": [c.case_id for c in by["reader"]],
            "critic_ids": [c.case_id for c in by["critic"]],
            "critic_labels": y(by["critic"]).tolist(),
            "critic_exits": {str(k): v.tolist() for k,v in critic_exits.items()},
            "calibration_ids": [c.case_id for c in by["calibration"]],
            "calibration_labels": y(by["calibration"]).tolist(),
            "calibration_exits": {str(k): v.tolist() for k,v in calibration_exits.items()},
            "calibration_frame_sha256s": cal_keys,
            "critic": value_critic, "train_work": train_work,
            "pre_holdout_visual_work": {"unique_frames": len(cache.cache),
                "physical_video_calls": cache.physical_video_calls}})
        seal = e.write_once(output / "selection.json", policy_selection)
        selection = e.decode(e.bound_file(output / "selection.json", seal))
        records, costs = {}, {}
        for arm in ARMS:
            tower = temporal.FrameCacheTowers(base)
            rows = []
            with e.measured() as interval:
                for case in by["holdout"]:
                    e.write_once(output / f"{arm}-{case.case_id}.started.json",
                        {"case_id": case.case_id, "selection_sha256": seal,
                         "arm": arm, "input_digest": case.input_digest})
                    observed = stream_one(model, case.inputs["video"], root, tower,
                        selection["policies"][arm], selection["critic"])
                    row = {"case_id": case.case_id, "input_digest": case.input_digest,
                           "arm": arm, **observed}
                    e.write_once(output / f"{arm}-{case.case_id}.result.json", row)
                    rows.append(row)
            records[arm] = rows
            costs[arm] = {"unique_frames": len(tower.cache),
                "physical_video_calls": tower.physical_video_calls,
                "cache_hits": tower.frame_cache_hits,
                "requested_frame_rows": sum(r["depth"] for r in rows),
                "isolated_cache": True, "whole_arm_wall_with_receipts": interval}
        pred_seal = e.write_once(output / "predictions.json", {
            "selection_sha256": seal, "case_ids": [c.case_id for c in by["holdout"]],
            "records": records, "physical_work": costs})
        batch_report = None
        if type(microbatch_shadow) is not bool:
            raise e.InputError("explicit batched shadow experiment switch required")
        if microbatch_shadow:
            from experiments.shared_stem_cell import video_batch
            batch_report = video_batch.run_shadow(model, by["holdout"], root, base,
                selection["policies"], selection["critic"], records, costs,
                output / "batch", selection_sha256=seal, serial_predictions_sha256=pred_seal)
        base.close()
        media.read_cases(root, config["dataset"],2)
        temporal.cohort(root, config["cohort"])
        if manifest_path.read_bytes() != manifest_raw or e.parameters(model) != model_id:
            raise e.InputError("source or selected Reader changed")
        saved = e.decode(e.bound_file(output / "predictions.json", pred_seal))
        holdout_y = y(by["holdout"])
        batch_scores = None
        if batch_report is not None:
            batch_saved = e.decode(e.bound_file(output / "batch/predictions.json",
                                                batch_report["predictions_sha256"]))
            batch_scores = {}
            for batch_arm, study in batch_saved["arms"].items():
                probabilities = torch.tensor([row["probabilities"] for row in study["records"]],
                                             dtype=torch.float32)
                batch_scores[batch_arm] = temporal.score(probabilities, holdout_y)
            # Deliberately score only after BOTH serial and batched predictions are sealed;
            # heldout labels never influence policy, batching schedule, or model weights.
        scores, pairing, per_source = {}, {}, {}
        source_of = {r["case_id"]: r["source_id"] for r in registered}
        idx = {c.case_id: i for i,c in enumerate(by["holdout"])}
        for arm, rows in saved["records"].items():
            probabilities = torch.tensor([r["probabilities"] for r in rows], dtype=torch.float32)
            scores[arm] = temporal.score(probabilities, holdout_y)
            scores[arm]["latency_ns"] = nearest_rank_latency(rows)
            per_source[arm] = {}
            for case, row in zip(by["holdout"], rows):
                family = source_of[case.case_id]
                counter = per_source[arm].setdefault(family, {"attempted":0, "correct":0})
                counter["attempted"] += 1
                counter["correct"] += int(row["prediction"] == targets[case.case_id])
            pairing[arm] = {"pairs": 0, "both_directions_correct": 0}
            for pair in pairs.values():
                if pair[0]["split"] == "holdout":
                    i, j = (idx[r["case_id"]] for r in pair)
                    pairing[arm]["pairs"] += 1
                    pairing[arm]["both_directions_correct"] += int(
                        rows[i]["prediction"] == int(holdout_y[i]) and
                        rows[j]["prediction"] == int(holdout_y[j]))
        report = {"schema": "hepta.video-value-executed.v1",
            "manifest_sha256": e.sha(manifest_raw), "selection_sha256": seal,
            "prediction_sha256": pred_seal, "scores": scores,
            "paired_direction_scores": pairing, "per_source_video_scores": per_source,
            "row_latency_p95_p99_are_descriptive_not_population_tails": True,
            "holdout_source_video_count": 2, "physical_work": costs,
            "loading_work": loading, "reader_critic_calibration_work": preparation,
            "whole_experiment_tower_calls": base.calls,
            "full_clip_resident_parameters": sum(p.numel() for p in base.models["clip"].parameters())
                if "clip" in base.models else None,
            "reader_parameters": model_id["parameters"],
            "critic_linear_coefficients": 15,
            "cache_aware_marginal_calls_simulated_and_replayed": True,
            "cache_step_cost_not_measured_hardware": True, "value_family_actual_selection": selection["policies"]["value"],
            "confidence_family_actual_selection": selection["policies"]["confidence"],
            "cache_value_family_actual_selection": selection["policies"]["cache_value"],
            "calibration_best_family": selection["best_calibration_arm"],
            "simulated_towers": base.simulated,
            "energy_joules": None, "active_flops": None, "peak_process_rss_bytes": None,
            "staging_already_decoded_and_verified_all_source_frames": True,
            "shadow_fixed_and_confidence_controls_charge_separately": True,
            "train_critic_calibration_source_partition_predeclared": True,
            "ndu_is_bounded_linear_expected_next_pair_correctness": True,
            "general_ndu_fbsde_established": False, "quality_advantage_established": False,
            "source_license_declared": None, "production_accepted": False}
        if batch_report is not None:
            report.update({"microbatch_shadow": batch_report,
                "microbatch_shadow_scores": batch_scores,
                "microbatch_shadow_total_extra_calls":
                    sum(x["batched_physical_calls"] for x in batch_report["comparison"].values())})
        e.write_once(output / "report.json", report)
        return report
    except Exception as error:
        e.write_once(output / "failure.json", {"exception": type(error).__name__,
            "message": str(error), "production_accepted": False})
        raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--microbatch-shadow", action="store_true",
        help="Extra isolated batched Cell controls; no savings claimed for total research run")
    args = parser.parse_args()
    torch.set_num_threads(2)
    run(args.manifest, args.output, microbatch_shadow=args.microbatch_shadow)
