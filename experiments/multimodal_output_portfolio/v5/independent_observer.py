"""Independent raw-output semantic and budget auditor (synthetic research).

Does not import experiment loss, experiment evaluation, CVaR helper, or
portfolio costs. It must see final raw outputs and externally held truth.
Not a separate institution, signed hardware observer or natural media test.
"""
from __future__ import annotations

import hashlib
import json
import math


def observe(raw: dict, truth: int, action: str) -> tuple[int, int, int, int]:
    if type(raw) is not dict or set(raw) != {"text", "audio", "image", "video"}:
        raise ValueError("missing/extra actual modality")
    if type(truth) is not int or truth not in (0, 1):
        raise ValueError("external reference unavailable")
    text = raw["text"]
    audio = raw["audio"]
    image = raw["image"]
    video = raw["video"]
    if type(text) is not str or text not in ("symbol:0", "symbol:1"):
        raise ValueError("invalid decoded text")
    token = 0 if text == "symbol:0" else 1
    if type(audio) is not tuple or len(audio) != 4 or audio[1] != -audio[0] or audio[2] != audio[0] or audio[3] != -audio[0]:
        raise ValueError("invalid decoded acoustic samples")
    tone = audio[0]
    if (type(image) is not tuple or len(image) != 2
        or any(type(row) is not tuple or len(row) != 2 for row in image)
        or image != ((image[0][0],) * 2,) * 2):
        raise ValueError("invalid generated image pixels")
    pixel = image[0][0]
    if (type(video) is not tuple or len(video) != 2
        or any(type(frame) is not tuple or len(frame) != 2 for frame in video)
        or video != (((video[0][0][0],) * 2,) * 2,) * 2):
        raise ValueError("invalid generated video frames")
    frame = video[0][0][0]
    values = (token, tone, pixel, frame)
    if any(type(x) is not int or x not in (0, 1) for x in values):
        raise ValueError("nonbinary generated fact")
    if action == "EMIT":
        resource = 4
    elif type(action) is str and action in ("REFINE_TEXT", "REFINE_AUDIO", "REFINE_IMAGE", "REFINE_VIDEO"):
        resource = 5
    elif action == "QUERY":
        resource = 7
    else:
        raise ValueError("unknown or unstamped selected action")
    wrong = sum(q != truth for q in values)
    cross = (token != tone) + (pixel != frame)
    return wrong + 2 * cross, wrong, cross, resource


def rerun_and_audit(saved_report: dict) -> dict:
    # Training/generation policy implementation imported only to execute
    # the pinned four arm snapshots, NOT to score or aggregate outcome.
    from factorial import (TRAININGS, CONTROLS, make_worlds, train,
                           train_policies, predict, choose, apply_action, decode_raw)
    seeds = [entry["seed"] for entry in saved_report["seeds"]]
    if seeds != [17, 29, 43]:
        raise ValueError("wrong source-seed census")
    source_seen = set()
    ledger = hashlib.sha256()
    per_arm = {}
    count = 0
    for entry in saved_report["seeds"]:
        seed = entry["seed"]
        train_set = make_worlds(seed, "train", 768)
        dev_set = make_worlds(seed, "dev", 256)
        test_set = make_worlds(seed, "test", 512)
        for world in test_set:
            if world.source_id in source_seen:
                raise ValueError("duplicate source identity")
            source_seen.add(world.source_id)
        for method in TRAININGS:
            weights, _ = train(train_set, seed, method)
            critic = train_policies(dev_set, weights)
            for control in CONTROLS:
                key = f"{method}|{control}"
                actual_losses, actual_costs = [], []
                for world in test_set:
                    observed = world.public
                    predicted = predict(observed, weights)
                    action = choose(observed, predicted, critic, control)
                    # Future witness is revealed only after policy selection.
                    raw = decode_raw(apply_action(predicted, action, world.witness))
                    loss, wrong, conflict, units = observe(raw, world.truth, action)
                    if units > critic["budget"]:
                        raise ValueError("unfunded four-modal action")
                    actual_losses.append(loss)
                    actual_costs.append(units)
                    encoded_raw = json.dumps(raw, sort_keys=True,
                                             separators=(",", ":")).encode()
                    row = (world.source_id, method, control, action,
                           hashlib.sha256(encoded_raw).hexdigest(),
                           loss, wrong, conflict, units)
                    ledger.update(json.dumps(row, separators=(",", ":")).encode() + b"\n")
                    count += 1
                mean_loss = sum(actual_losses) / len(actual_losses)
                mean_cost = sum(actual_costs) / len(actual_costs)
                expected = entry["arms"][key]
                if (not math.isclose(mean_loss, expected["mean_loss"], abs_tol=1e-12)
                    or not math.isclose(mean_cost, expected["mean_cost_units"], abs_tol=1e-12)):
                    raise AssertionError(f"independent decoded-score disagreement: {seed}:{key}")
                per_arm[f"{seed}:{key}"] = {"mean_loss": mean_loss,
                                               "modeled_cost": mean_cost,
                                               "rows": len(test_set)}
    if count != 3 * 4 * 512 or len(source_seen) != 3 * 512:
        raise AssertionError("incomplete source, training or controller census")
    return {"scope": "SYNTHETIC_EXTERNAL_OBSERVER_NOT_TRUSTED_HARDWARE",
            "source_groups": len(source_seen), "generated_output_rows": count,
            "four_output_rows_verified": count,
            "raw_output_ledger_sha256": ledger.hexdigest(),
            "independently_scored_arms": per_arm,
            "real_pretrained_generation": False,
            "external_signature": False,
            "production_authority": False}

if __name__ == "__main__":
    from pathlib import Path
    p = Path(__file__).with_name("development-report.json")
    print(json.dumps(rerun_and_audit(json.loads(p.read_text())), indent=2, sort_keys=True))
