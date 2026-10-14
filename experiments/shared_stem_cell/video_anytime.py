"""Actual incremental frozen-CLIP frame execution for a bounded video-order Cell.

A separately fitted four-exit reader uses the SAME weights at depths 2/4/6/8.
Calibration-only routing selects how much frozen visual encoding to acquire on
holdout. Fixed-depth and order-blind/endpoint/full-GRU research controls remain.
This is NOT general NDU/FBSDE, causal video understanding or production routing.
"""
from __future__ import annotations

from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F

from experiments.shared_stem_cell import execution as e, media_execution as media
from experiments.shared_stem_cell import video_temporal as v

DEPTHS = (2, 4, 6, 8)
THRESHOLDS = (0.0, 0.55, 0.65, 0.75, 0.85, 0.95, 1.01)
ARMS = ("adaptive", "fixed_2", "fixed_4", "fixed_6", "fixed_8")


class AnytimeCell(nn.Module):
    """One parameter set; depth-independent recurrent parameters and readout."""
    def __init__(self, width, hidden=24):
        super().__init__()
        e.integer(width, 1, 8192, "video feature width")
        e.integer(hidden, 1, 128, "reader hidden width")
        self.project = nn.Linear(width, hidden)
        self.core = nn.GRUCell(hidden, hidden)
        self.readout = nn.Linear(hidden, 2)

    def step_pair(self, pair, state=None):
        if (not isinstance(pair, torch.Tensor) or pair.dtype != torch.float32
                or pair.device.type != "cpu" or pair.ndim != 2 or pair.shape != (2, self.project.in_features)
                or not bool(torch.isfinite(pair).all())):
            raise e.InputError("two ordered finite frozen-CLIP frames required")
        if state is not None and (not isinstance(state, torch.Tensor) or state.shape != (1, self.core.hidden_size)
                                  or state.dtype != torch.float32 or not bool(torch.isfinite(state).all())):
            raise e.InputError("bounded recurrent video state required")
        for row in pair:
            feature = torch.tanh(self.project(row.detach().view(1, -1)))
            state = self.core(feature, state if state is not None else
                              feature.new_zeros(1, self.core.hidden_size))
        return state, self.readout(state)

    def all_exits(self, item):
        x, _mask, _stamps = v.validate_video(item)
        state = x.new_zeros(len(x), self.core.hidden_size)
        result = {}
        for frame in range(8):
            z = torch.tanh(self.project(x[:, frame].detach()))
            state = self.core(z, state)
            if frame + 1 in DEPTHS:
                result[frame + 1] = self.readout(state)
        return result


def fit(train, labels, *, steps=80, seed=20261014):
    v.validate_video(train, labels)
    e.integer(steps, 1, 1000, "anytime training steps")
    if type(seed) is not int or not 0 <= seed <= 2**31-1:
        raise e.InputError("bounded anytime seed")
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = AnytimeCell(train[0].shape[2]).train()
        opt = torch.optim.AdamW(model.parameters(), lr=.01, weight_decay=0.0)
        with e.measured() as timing:
            for _ in range(steps):
                opt.zero_grad(set_to_none=True)
                outputs = model.all_exits(train)
                loss = sum(F.cross_entropy(outputs[depth], labels) for depth in DEPTHS) / len(DEPTHS)
                if not bool(torch.isfinite(loss)):
                    raise e.InputError("nonfinite multi-exit training loss")
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1., error_if_nonfinite=True)
                opt.step()
        model.eval().requires_grad_(False)
    return model, {**timing, **e.parameters(model), "optimizer_steps": steps,
                   "examples_processed": steps * len(labels), "exit_loss_depths": DEPTHS,
                   "training_uses_calibration_labels": False}


@torch.no_grad()
def probabilities(model, item):
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise e.InputError("frozen evaluation reader required")
    return {depth: value.softmax(-1).detach().cpu().float().contiguous()
            for depth, value in model.all_exits(item).items()}


def route(exits, threshold):
    if type(threshold) is not float or threshold not in THRESHOLDS:
        raise e.InputError("fixed non-target-derived threshold required")
    if set(exits) != set(DEPTHS) or any(not isinstance(p, torch.Tensor)
            or p.dtype != torch.float32 or p.device.type != "cpu" or p.ndim != 2
            or p.shape[1] != 2 for p in exits.values()):
        raise e.InputError("complete multi-exit probabilities required")
    n = len(exits[2])
    if not 1 <= n <= 256 or any(p.shape[0] != n for p in exits.values()):
        raise e.InputError("multi-exit row cardinality drift")
    for depth in DEPTHS:
        v.score(exits[depth], torch.zeros(n, dtype=torch.long))  # checks full simplex
    chosen = []
    for row in range(n):
        for depth in DEPTHS:
            if depth == 8 or float(exits[depth][row].max()) >= threshold:
                chosen.append((depth, int(exits[depth][row].argmax())))
                break
    return chosen


def simulated_cache_work(frame_ids, picks):
    """Replay exact per-arm SHA cache policy WITHOUT invoking CLIP or seeing labels."""
    if (not isinstance(frame_ids, list) or len(frame_ids) != len(picks)
            or not 1 <= len(frame_ids) <= 256):
        raise e.InputError("complete calibration source frame identities required")
    stored, calls, hits = set(), 0, 0
    for row, (depth, _prediction) in zip(frame_ids, picks):
        if (not isinstance(row, list) or len(row) != 8
                or any(not isinstance(key, str) or len(key) != 64
                       or any(c not in "0123456789abcdef" for c in key) for key in row)):
            raise e.InputError("source-bound eight-frame identity inventory required")
        if depth not in DEPTHS:
            raise e.InputError("registered reader depth required")
        for pos in range(0, depth, 2):
            pair = row[pos:pos+2]
            fresh = set(pair) - stored
            hits += sum(key in stored for key in pair)
            if fresh:
                calls += 1
                stored.update(fresh)
    return {"unique_frames": len(stored), "physical_video_calls": calls,
            "cache_hits": hits, "requested_frame_rows": sum(depth for depth, _ in picks)}


def select(exits, labels, frame_ids):
    if not isinstance(labels, torch.Tensor) or labels.dtype != torch.long:
        raise e.InputError("calibration labels must be int64")
    if set(exits) != set(DEPTHS) or any(len(p) != len(labels) for p in exits.values()):
        raise e.InputError("complete fixed-depth calibration profiles required")
    controls = {}
    for depth in DEPTHS:
        quality = v.score(exits[depth], labels)
        costs = simulated_cache_work(frame_ids, [(depth, 0)] * len(labels))
        controls[str(depth)] = {**quality, **costs}
    floor = max(profile["correct"] for profile in controls.values())
    grid = []
    for threshold in THRESHOLDS:
        picks = route(exits, float(threshold))
        correct = sum(pred == int(target) for (_, pred), target in zip(picks, labels))
        grid.append({"threshold": float(threshold), "correct": correct, "cases": len(labels),
                     **simulated_cache_work(frame_ids, picks),
                     "mean_depth": sum(depth for depth, _ in picks) / len(picks)})
    eligible = [i for i, row in enumerate(grid) if row["correct"] >= floor]
    # An adaptive threshold may never match the best intermediate-depth baseline.
    # In this case select the actual fixed control, not a favorable fiction.
    if eligible:
        winner = min(eligible, key=lambda i: (grid[i]["unique_frames"],
                        grid[i]["physical_video_calls"], grid[i]["requested_frame_rows"],
                        -grid[i]["correct"], i))
        policy = {"arm": "adaptive", "threshold": grid[winner]["threshold"],
                  "selected_index": winner, "calibration_result": grid[winner]}
    else:
        depth = min(DEPTHS, key=lambda d: (-controls[str(d)]["correct"],
            controls[str(d)]["unique_frames"], controls[str(d)]["physical_video_calls"], d))
        policy = {"arm": f"fixed_{depth}", "depth": depth,
                  "fallback_reason": "no adaptive threshold reached best fixed-depth accuracy"}
    return {"schema": "hepta.video-anytime-calibration.v1", "grid": grid,
            "fixed_depth_controls": controls, "calibration_correct_floor": floor, "policy": policy,
            "fixed_thresholds": THRESHOLDS, "policy_objective":
            "accuracy_floor_then_unique_frames_then_physical_calls_then_requested_rows",
            "quality_is_not_certified": True, "production_accepted": False}


@torch.no_grad()
def stream_one(model, frames, root, tower, *, arm, policy=None):
    """Each two-frame chunk is acquired only after observing prior state."""
    if arm not in ARMS or (arm == "adaptive" and (not isinstance(policy, dict)
                             or policy.get("arm") not in ARMS)):
        raise e.InputError("declared frame-budget arm required")
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise e.InputError("frozen anytime Cell required")
    if not isinstance(frames, list) or len(frames) != 8:
        raise e.InputError("exact registered eight-frame window required")
    intended = (policy["arm"] if arm == "adaptive" else arm)
    if intended not in ARMS or intended == "adaptive" and policy["threshold"] not in THRESHOLDS:
        raise e.InputError("sealed evaluated policy required")
    limit = 8 if intended == "adaptive" else int(intended.split("_")[1])
    state, results, observed_frames = None, [], 0
    with e.measured() as wall:
        for depth in DEPTHS:
            if depth > limit:
                break
            pair_refs = frames[depth-2:depth]
            before = tower.physical_video_calls
            data, times = tower.encode("video", pair_refs, root)
            if (not isinstance(data, torch.Tensor) or data.shape != (2, model.project.in_features)
                    or data.dtype != torch.float32 or data.device.type != "cpu"
                    or not bool(torch.isfinite(data).all())
                    or not torch.equal(times, torch.tensor([f["timestamp_us"] for f in pair_refs]))):
                raise e.InputError("physical incremental CLIP pair drift")
            state, logits = model.step_pair(data, state)
            value = logits.softmax(-1)[0]
            if not bool(torch.isfinite(value).all()):
                raise e.InputError("nonfinite streaming probabilities")
            results.append({"depth": depth, "probabilities": value.tolist(),
                            "physical_pair_call_delta": tower.physical_video_calls - before})
            observed_frames = depth
            if intended == "adaptive" and (float(value.max()) >= policy["threshold"] or depth == 8):
                break
    final = results[-1]
    return {"depth": observed_frames, "prediction": int(torch.tensor(final["probabilities"]).argmax()),
            "probabilities": final["probabilities"], "exits_seen": results,
            "foreground_wall": wall, "model_sha256": e.parameters(model)["sha256"]}


def run(manifest_path: Path, output: Path, *, _tower_factory=media.LocalTowers):
    """Train/calibrate without seeing held-out frames; physical test encode is lazy."""
    manifest_path, output = Path(manifest_path), Path(output)
    manifest_raw = manifest_path.read_bytes()
    config = e.decode(manifest_raw)
    if (config.get("schema") != "hepta.shared-stem-media.v1" or config.get("classes") != 2
            or config.get("video_profile") != "paired_temporal_order_v1"
            or config.get("temporal") is not False or set(config.get("models", {})) != {"clip"}):
        raise e.InputError("closed frozen-CLIP video profile required")
    root = manifest_path.parent
    output.mkdir(parents=True, exist_ok=False)
    e.write_once(output / "plan.json", {"manifest_sha256": e.sha(manifest_raw),
        "training_steps": config.get("steps", 80), "fixed_depths": DEPTHS,
        "thresholds": THRESHOLDS, "control_arms": ARMS,
        "source_sha256": e.sha(Path(__file__).read_bytes()),
        "generation_completed": False, "production_accepted": False})
    try:
        cases, labels = media.read_cases(root, config["dataset"], 2)
        registered, pairs = v.cohort(root, config["cohort"])
        if ([c.case_id for c in cases] != [r["case_id"] for r in registered]
                or any(set(c.inputs) != {"video"} or len(c.inputs["video"]) != 8 for c in cases)):
            raise e.InputError("registered video cohort/data mismatch")
        source_splits = {}
        for record in registered:
            original = source_splits.setdefault(record["source_id"], record["split"])
            if record["split"] != original:
                raise e.InputError("source video crosses folds")
        groups = {split: [c for c in cases if c.split == split]
                  for split in ("train", "calibration", "holdout")}
        if not all(groups.values()) or sum(map(len, groups.values())) != len(cases):
            raise e.InputError("registered exact train/calibration/holdout required")
        with e.measured() as loading:
            base = _tower_factory(root, config["models"])
            train_towers = v.FrameCacheTowers(base)
        with e.measured() as preparation:
            known = media.extract(train_towers, groups["train"] + groups["calibration"], root)["video"]
            n = len(groups["train"])
            train = tuple(t[:n] for t in known)
            calibration = tuple(t[n:] for t in known)
            y_train = torch.tensor([labels[c.case_id] for c in groups["train"]], dtype=torch.long)
            y_cal = torch.tensor([labels[c.case_id] for c in groups["calibration"]], dtype=torch.long)
            model, fit_cost = fit(train, y_train, steps=config.get("steps", 80), seed=config.get("seed", 17))
            exits = probabilities(model, calibration)
            cal_keys = [[f["sha256"] for f in c.inputs["video"]] for c in groups["calibration"]]
            selection = select(exits, y_cal, cal_keys)
        model_identity = e.parameters(model)
        selection.update({"calibration_probabilities": {str(d): exits[d].tolist() for d in DEPTHS},
            "calibration_labels": y_cal.tolist(), "calibration_frame_sha256s": cal_keys,
            "model_sha256": model_identity["sha256"],
            "model_parameters": model_identity["parameters"],
            "model_identity": base.identities, "manifest_sha256": e.sha(manifest_raw),
            "training_ids": [c.case_id for c in groups["train"]],
            "calibration_ids": [c.case_id for c in groups["calibration"]],
            "fit_cost": fit_cost, "training_calibration_encoding": {
                "unique_frames": len(train_towers.cache),
                "cache_hits": train_towers.frame_cache_hits,
                "physical_video_calls": train_towers.physical_video_calls}}
            )
        selection_seal = e.write_once(output / "selection.json", selection)
        policy = e.decode(e.bound_file(output / "selection.json", selection_seal))["policy"]
        training_summary = {"loading": loading, "preparation": preparation}
        records, physical = {}, {}
        for arm in ARMS:
            # Different cache per ARM prevents previously measured full-depth
            # controls from making the selected route look artificially cheap.
            tower = v.FrameCacheTowers(base)
            rows = []
            with e.measured() as arm_wall:
                for case in groups["holdout"]:
                    e.write_once(output / f"{arm}-{case.case_id}.started.json",
                        {"case_id": case.case_id, "arm": arm, "selection_sha256": selection_seal,
                         "input_digest": case.input_digest})
                    result = stream_one(model, case.inputs["video"], root, tower, arm=arm, policy=policy)
                    row = {"case_id": case.case_id, "arm": arm, "input_digest": case.input_digest, **result}
                    e.write_once(output / f"{arm}-{case.case_id}.result.json", row)
                    rows.append(row)
            physical[arm] = {"physical_video_calls": tower.physical_video_calls,
                "unique_frames": len(tower.cache), "cache_hits": tower.frame_cache_hits,
                "requested_frame_rows": sum(r["depth"] for r in rows),
                "full_arm_wall_including_receipts": arm_wall,
                "cache_isolated_across_arms": True}
            records[arm] = rows
        prediction_seal = e.write_once(output / "predictions.json", {
            "selection_sha256": selection_seal, "case_ids": [c.case_id for c in groups["holdout"]],
            "records": records, "physical_work": physical})
        base.close()
        media.read_cases(root, config["dataset"], 2)
        v.cohort(root, config["cohort"])
        if manifest_path.read_bytes() != manifest_raw or e.parameters(model) != model_identity:
            raise e.InputError("source/model changed during incremental evaluation")
        sealed = e.decode(e.bound_file(output / "predictions.json", prediction_seal))
        gold = torch.tensor([labels[c.case_id] for c in groups["holdout"]], dtype=torch.long)
        scores = {}
        for arm, rows in sealed["records"].items():
            tensor = torch.tensor([r["probabilities"] for r in rows], dtype=torch.float32)
            scores[arm] = v.score(tensor, gold)
            scores[arm]["requested_frame_rows"] = sealed["physical_work"][arm]["requested_frame_rows"]
        paired = {}
        positions = {c.case_id: i for i, c in enumerate(groups["holdout"])}
        for arm, rows in sealed["records"].items():
            n = hit = 0
            for pair in pairs.values():
                if pair[0]["split"] != "holdout":
                    continue
                positions_here = [positions[r["case_id"]] for r in pair]
                n += 1
                hit += int(all(rows[i]["prediction"] == int(gold[i]) for i in positions_here))
            paired[arm] = {"pairs": n, "both_directions_correct": hit}
        report = {"schema": "hepta.video-anytime-executed.v1",
            "manifest_sha256": e.sha(manifest_raw), "selection_sha256": selection_seal,
            "prediction_sha256": prediction_seal, "scores": scores, "paired": paired,
            "physical_work": physical, "training_calibration_work": training_summary,
            "actual_tower_calls_entire_experiment": base.calls,
            "model_parameters": {"anytime_cell": model_identity["parameters"],
                "full_clIP_model": sum(p.numel() for p in base.models["clip"].parameters())
                if "clip" in base.models else None},
            "simulated_towers": base.simulated,
            "energy_joules": None, "active_flops": None, "peak_process_rss_bytes": None,
            "foreground_adaptive_or_fallback": policy,
            "control_work_is_not_foreground_saving": True,
            "staged_media_validation_reads_all_frames": True,
            "quality_and_latency_superiority_established": False,
            "pretrained_semantics_independently_verified": False,
            "general_ndu_fbsde_established": False, "video_generation_completed": False,
            "production_accepted": False}
        e.write_once(output / "report.json", report)
        return report
    except Exception as exc:
        e.write_once(output / "failure.json", {"exception": type(exc).__name__,
            "message": str(exc), "production_accepted": False})
        raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(2)
    run(args.manifest, args.output)
