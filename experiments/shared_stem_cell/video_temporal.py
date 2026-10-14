"""Frozen frame tower -> light temporal Cells with order-blind strong controls.

The task is original-vs-reversed presentation of the same real source frames.
It diagnoses temporal order use; it is NOT general action recognition, video
reasoning, generation, or a production router.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F

from experiments.shared_stem_cell import execution as e, media_execution as media

CHECKPOINTS = (0, 1, 2, 5, 10, 20, 40, 80)


def validate_video(item, labels=None):
    if not isinstance(item, tuple) or len(item) != 3:
        raise e.InputError("exact video feature/mask/time tuple required")
    x, mask, stamps = item
    if (not isinstance(x, torch.Tensor) or x.dtype != torch.float32 or x.device.type != "cpu"
            or x.ndim != 3 or not 1 <= len(x) <= 256 or x.shape[1] != 8
            or not 1 <= x.shape[2] <= 8192 or not bool(torch.isfinite(x).all())
            or not isinstance(mask, torch.Tensor) or mask.dtype != torch.bool
            or mask.shape != x.shape[:2] or not bool(mask.all())
            or not isinstance(stamps, torch.Tensor) or stamps.dtype != torch.long
            or stamps.device.type != "cpu" or stamps.shape != mask.shape
            or not bool((stamps[:, 1:] > stamps[:, :-1]).all())):
        raise e.InputError("finite complete eight-frame temporal feature profile required")
    if labels is not None and (not isinstance(labels, torch.Tensor) or labels.dtype != torch.long
            or labels.device.type != "cpu" or labels.shape != (len(x),)
            or bool(((labels < 0) | (labels > 1)).any())):
        raise e.InputError("binary temporal labels required")
    return x, mask, stamps


class OrderBlind(nn.Module):
    """Parameter-rich static control; reversing the same frames is invariant."""
    def __init__(self, width, hidden=24):
        super().__init__()
        self.project = nn.Linear(width, hidden)
        self.hidden = nn.Linear(hidden, hidden)
        self.readout = nn.Linear(hidden, 2)

    def forward(self, item):
        x, mask, _ = validate_video(item)
        z = torch.tanh(self.project(x.detach()))
        pooled = (z * mask.unsqueeze(-1)).sum(1) / mask.sum(1, keepdim=True)
        return self.readout(torch.tanh(self.hidden(pooled)))


class EndpointDelta(nn.Module):
    """Cheap order-sensitive Cell using the same first/last frozen features."""
    def __init__(self, width, hidden=24):
        super().__init__()
        self.project = nn.Linear(width, hidden)
        self.readout = nn.Linear(hidden, 2)

    def forward(self, item):
        x, _mask, _ = validate_video(item)
        return self.readout(torch.tanh(self.project((x[:, -1] - x[:, 0]).detach())))


class TemporalGRU(nn.Module):
    """Shared recurrent temporal Cell; one small state update per frame."""
    def __init__(self, width, hidden=24):
        super().__init__()
        self.project = nn.Linear(width, hidden)
        self.core = nn.GRU(hidden, hidden, batch_first=True)
        self.readout = nn.Linear(hidden, 2)

    def forward(self, item):
        x, _mask, _ = validate_video(item)
        z = torch.tanh(self.project(x.detach()))
        values, _ = self.core(z)
        return self.readout(values[:, -1])


def score(probabilities, labels):
    if (not isinstance(probabilities, torch.Tensor) or probabilities.dtype != torch.float32
            or probabilities.device.type != "cpu" or probabilities.shape != (len(labels), 2)
            or not bool(torch.isfinite(probabilities).all())
            or bool(((probabilities < 0) | (probabilities > 1)).any())
            or not bool(torch.allclose(probabilities.sum(-1), torch.ones(len(labels)), atol=1e-5))):
        raise e.InputError("complete finite temporal probability matrix required")
    validate_video((torch.zeros(len(labels), 8, 1), torch.ones(len(labels), 8, dtype=torch.bool),
                    torch.arange(8).repeat(len(labels), 1)), labels)
    hits = probabilities.argmax(-1) == labels
    return {"cases": len(labels), "correct": int(hits.sum()),
            "accuracy": float(hits.float().mean()),
            "nll": float(F.nll_loss(probabilities.clamp_min(1e-8).log(), labels))}


def fit_arm(factory, train, train_y, calibration, calibration_y, holdout, *, steps=80, seed=17):
    validate_video(train, train_y); validate_video(calibration, calibration_y); validate_video(holdout)
    if train[0].shape[2] != calibration[0].shape[2] or train[0].shape[2] != holdout[0].shape[2]:
        raise e.InputError("same frozen frame width required")
    e.integer(steps, 1, 1000, "temporal steps")
    if steps not in CHECKPOINTS:
        raise e.InputError("registered temporal checkpoint horizon required")
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = factory(train[0].shape[2]).cpu().float()
        initial = deepcopy(model).eval()
        optimizer = torch.optim.AdamW(model.parameters(), lr=.01, weight_decay=0)
        snapshots = {0: deepcopy(initial)}
        with e.measured() as training:
            for step in range(1, steps + 1):
                model.train(); optimizer.zero_grad(set_to_none=True)
                loss = F.cross_entropy(model(train), train_y)
                if not bool(torch.isfinite(loss)):
                    raise e.InputError("nonfinite temporal loss")
                loss.backward(); nn.utils.clip_grad_norm_(model.parameters(), 1., error_if_nonfinite=True)
                optimizer.step()
                if step in CHECKPOINTS:
                    snapshots[step] = deepcopy(model).eval()
        history = []
        with torch.no_grad():
            for step in CHECKPOINTS:
                if step > steps:
                    continue
                p = snapshots[step](calibration).softmax(-1)
                history.append({"step": step, **score(p, calibration_y),
                                "model_sha256": e.parameters(snapshots[step])["sha256"]})
        selected_row = min(range(len(history)), key=lambda i: (-history[i]["correct"], history[i]["nll"], history[i]["step"]))
        selected_step = history[selected_row]["step"]
        selected, final = snapshots[selected_step], snapshots[steps]
        with torch.no_grad():
            predictions = {"frozen": initial(holdout).softmax(-1).tolist(),
                           "selected": selected(holdout).softmax(-1).tolist(),
                           "final": final(holdout).softmax(-1).tolist()}
    return predictions, {"history": history, "selected_step": selected_step,
        "selected_model_sha256": e.parameters(selected)["sha256"],
        "final_model_sha256": e.parameters(final)["sha256"],
        "frozen_model_sha256": e.parameters(initial)["sha256"],
        "training": {**training, **e.parameters(final), "steps": steps,
                     "examples_processed": steps * len(train)}}


def trial(train, train_y, calibration, calibration_y, holdout, *, steps=80, seed=17):
    factories = {"order_blind": OrderBlind, "endpoint_delta": EndpointDelta,
                 "temporal_gru": TemporalGRU}
    predictions, selections = {}, {}
    for name, factory in factories.items():
        predictions[name], selections[name] = fit_arm(factory, train, train_y, calibration,
            calibration_y, holdout, steps=steps, seed=seed)
    return {"predictions": predictions, "selections": selections,
            "task": "same-real-frames_original_vs_reversed", "production_accepted": False}


class FrameCacheTowers:
    """Reuse exact frame features across forward/reverse paired observations."""
    def __init__(self, base):
        self.base, self.cache = base, {}
        self.frame_cache_hits = 0
        self.physical_video_calls = 0

    def __getattr__(self, name):
        return getattr(self.base, name)

    def encode(self, name, item, root):
        if name != "video":
            return self.base.encode(name, item, root)
        if not isinstance(item, list) or not 1 <= len(item) <= 16:
            raise e.InputError("bounded explicit video frame list required")
        missing, seen = [], set()
        for frame in item:
            key = frame["sha256"]
            if key in self.cache:
                self.frame_cache_hits += 1
            elif key not in seen:
                missing.append(frame); seen.add(key)
        if missing:
            values, _stamps = self.base.encode("video", missing, root)
            self.physical_video_calls += 1
            expected_stamps = torch.tensor([frame["timestamp_us"] for frame in missing], dtype=torch.long)
            if (not isinstance(values, torch.Tensor) or values.dtype != torch.float32
                    or values.device.type != "cpu" or values.ndim != 2
                    or not 1 <= values.shape[1] <= 8192 or len(values) != len(missing)
                    or not bool(torch.isfinite(values).all())
                    or not isinstance(_stamps, torch.Tensor) or _stamps.dtype != torch.long
                    or _stamps.device.type != "cpu" or not torch.equal(_stamps, expected_stamps)):
                raise e.InputError("physical frame feature/timestamp coverage drift")
            for frame, value in zip(missing, values):
                self.cache[frame["sha256"]] = value.detach().clone().contiguous()
        values = torch.stack([self.cache[frame["sha256"]] for frame in item])
        stamps = torch.tensor([frame["timestamp_us"] for frame in item], dtype=torch.long)
        return values, stamps


def cohort(root, descriptor):
    raw = media.reference(root, descriptor)
    value = e.decode(raw)
    if not isinstance(value, list) or not 4 <= len(value) <= 256:
        raise e.InputError("bounded temporal cohort required")
    required = {"case_id", "pair_id", "source_id", "split", "direction", "frame_sha256s"}
    if (any(not isinstance(row, dict) or set(row) != required for row in value)
            or len({row["case_id"] for row in value}) != len(value)):
        raise e.InputError("temporal cohort fields/identities")
    pairs = {}
    for row in value:
        if (row["split"] not in {"train", "calibration", "holdout"}
                or row["direction"] not in {"forward", "reverse"}
                or not isinstance(row["frame_sha256s"], list) or len(row["frame_sha256s"]) != 8):
            raise e.InputError("temporal cohort values")
        pairs.setdefault(row["pair_id"], []).append(row)
    for rows in pairs.values():
        if (len(rows) != 2 or {r["direction"] for r in rows} != {"forward", "reverse"}
                or len({r["source_id"] for r in rows}) != 1 or len({r["split"] for r in rows}) != 1):
            raise e.InputError("complete source-bound direction pair required")
        ordered = {r["direction"]: r["frame_sha256s"] for r in rows}
        if ordered["forward"] != list(reversed(ordered["reverse"])):
            raise e.InputError("paired rows must contain identical frames in reverse order")
    return value, pairs


def run(manifest_path, output, *, _tower_factory=media.LocalTowers):
    manifest_raw = manifest_path.read_bytes()
    config = e.decode(manifest_raw)
    if (config.get("schema") != "hepta.shared-stem-media.v1" or config.get("classes") != 2
            or config.get("video_profile") != "paired_temporal_order_v1"
            or type(config.get("temporal")) is not bool or config["temporal"]):
        raise e.InputError("registered video temporal manifest required")
    root = manifest_path.parent
    output.mkdir(parents=True, exist_ok=False)
    e.write_once(output / "plan.json", config)
    try:
        cases, labels = media.read_cases(root, config["dataset"], 2)
        registered, pairs = cohort(root, config["cohort"])
        if ([c.case_id for c in cases] != [row["case_id"] for row in registered]
                or any(set(c.inputs) != {"video"} or len(c.inputs["video"]) != 8 for c in cases)):
            raise e.InputError("dataset/cohort ordering or video-only profile drift")
        sources = {}
        for row in registered:
            prior = sources.setdefault(row["source_id"], row["split"])
            if prior != row["split"]:
                raise e.InputError("source video crosses folds")
        with e.measured() as loading:
            base = _tower_factory(root, config["models"])
            towers = FrameCacheTowers(base)
        with e.measured() as encoding:
            values = media.extract(towers, cases, root)
        item = values["video"]
        split_ids = {s: [i for i, c in enumerate(cases) if c.split == s]
                     for s in ("train", "calibration", "holdout")}
        select = lambda s: tuple(v[split_ids[s]] for v in item)
        target = lambda s: torch.tensor([labels[cases[i].case_id] for i in split_ids[s]], dtype=torch.long)
        result = trial(select("train"), target("train"), select("calibration"), target("calibration"),
                       select("holdout"), steps=config.get("steps", 80), seed=config.get("seed", 17))
        selection_seal = e.write_once(output / "selection.json", result["selections"])
        payload = {"case_ids": [cases[i].case_id for i in split_ids["holdout"]],
                   "input_digests": [cases[i].input_digest for i in split_ids["holdout"]],
                   "predictions": result["predictions"], "selection_sha256": selection_seal}
        prediction_seal = e.write_once(output / "predictions.json", payload)
        base.close()
        media.read_cases(root, config["dataset"], 2)
        cohort(root, config["cohort"])
        if manifest_path.read_bytes() != manifest_raw:
            raise e.InputError("video manifest changed during execution")
        sealed = e.decode(e.bound_file(output / "predictions.json", prediction_seal))
        holdout_y = target("holdout")
        scores, pair_scores = {}, {}
        holdout_positions = {cases[i].case_id: j for j, i in enumerate(split_ids["holdout"])}
        for arm, profiles in sealed["predictions"].items():
            scores[arm] = {}
            for profile, rows in profiles.items():
                probabilities = torch.tensor(rows, dtype=torch.float32)
                scores[arm][profile] = score(probabilities, holdout_y)
                both = total = 0
                for pair_rows in pairs.values():
                    if pair_rows[0]["split"] != "holdout":
                        continue
                    positions = [holdout_positions[row["case_id"]] for row in pair_rows]
                    both += int(bool((probabilities[positions].argmax(-1) == holdout_y[positions]).all()))
                    total += 1
                pair_scores.setdefault(arm, {})[profile] = {"pairs": total, "both_directions_correct": both}
        blind = torch.tensor(sealed["predictions"]["order_blind"]["selected"])
        max_difference = 0.0
        for pair_rows in pairs.values():
            if pair_rows[0]["split"] == "holdout":
                a, b = (holdout_positions[row["case_id"]] for row in pair_rows)
                max_difference = max(max_difference, float((blind[a] - blind[b]).abs().max()))
        if max_difference > 1e-6:
            raise e.InputError("order-blind control changed on the same frame multiset")
        report = {"schema": "hepta.public-video-temporal-executed.v1",
            "manifest_sha256": e.sha(manifest_raw), "prediction_sha256": prediction_seal,
            "selection_sha256": selection_seal, "scores": scores, "pair_scores": pair_scores,
            "order_blind_pair_max_probability_difference": max_difference,
            "source_video_split_disjoint": True, "same_frame_pairing": True,
            "frame_cache": {"unique_frames": len(towers.cache), "hits": towers.frame_cache_hits,
                            "physical_video_calls": towers.physical_video_calls,
                            "requested_frame_rows": sum(len(c.inputs["video"]) for c in cases)},
            "tower_forward_calls": base.calls, "model_identities": base.identities,
            "model_load": loading, "encoding": encoding, "simulated_towers": base.simulated,
            "action_recognition_established": False, "general_video_reasoning_established": False,
            "video_generation_completed": False, "independent_evaluation": False,
            "production_accepted": False}
        e.write_once(output / "report.json", report)
        return report
    except Exception as error:
        e.write_once(output / "failure.json", {"error": type(error).__name__, "message": str(error),
                                               "production_accepted": False})
        raise
