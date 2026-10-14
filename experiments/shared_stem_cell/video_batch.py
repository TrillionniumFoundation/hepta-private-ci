"""Depth-synchronous microbatches for many shared-Reader video Cells.

This is a separately charged research shadow, not a transparent replacement for
FIFO Cell execution. Group scheduling changes cache visibility; notably the
cache-aware continuation policy may choose a different depth. Never assign
shared CLIP work to every Cell or claim full-study wall savings.
"""
from __future__ import annotations

from pathlib import Path

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import video_anytime as anytime
from experiments.shared_stem_cell import video_temporal as temporal
from experiments.shared_stem_cell import video_value as value

SHADOW_ARMS = ("fixed_2", "fixed_8", "cache_value")
MAX_CELLS_PER_BATCH = 4  # two frames per active Cell; frozen tower limit 16


def validate_policy(policy, critic):
    if not isinstance(policy, dict) or policy.get("kind") not in ("fixed", "confidence", "value", "cache_value"):
        raise e.InputError("sealed supported video execution policy required")
    kind = policy["kind"]
    if kind == "fixed":
        if policy.get("depth") not in anytime.DEPTHS:
            raise e.InputError("bounded fixed depth required")
    elif kind == "confidence":
        if type(policy.get("threshold")) is not float or policy["threshold"] not in anytime.THRESHOLDS:
            raise e.InputError("declared confidence threshold required")
    else:
        if type(policy.get("price")) is not float or policy["price"] not in value.COSTS:
            raise e.InputError("declared value price required")
        # Reject an invalid future-depth critic before any physical Encoder call.
        for d in anytime.DEPTHS[:-1]:
            value.estimate(torch.full((1, 2), .5), d, critic)
    return kind


def validate_cases(cases):
    if not isinstance(cases, (list, tuple)) or not 1 <= len(cases) <= 256:
        raise e.InputError("bounded explicit Cell batch required")
    identities, scopes = set(), set()
    for c in cases:
        if not isinstance(c.case_id, str) or c.case_id in identities or not isinstance(c.scope, str):
            raise e.InputError("unique bounded Cell identity required")
        identities.add(c.case_id); scopes.add(c.scope)
        frames = c.inputs.get("video") if isinstance(c.inputs, dict) else None
        if not isinstance(frames, list) or len(frames) != 8:
            raise e.InputError("exact eight input-frame references required")
        stamps = []
        for ref in frames:
            if not isinstance(ref, dict) or set(ref) != {"path", "sha256", "timestamp_us"}:
                raise e.InputError("source-bound video frame metadata required")
            key, stamp, path = ref["sha256"], ref["timestamp_us"], ref["path"]
            if not isinstance(key, str) or len(key) != 64 or any(x not in "0123456789abcdef" for x in key):
                raise e.InputError("valid frame SHA identity required")
            if type(stamp) is not int or not 0 <= stamp <= 2**63-1:
                raise e.InputError("valid monotonically increasing timestamps required")
            if not isinstance(path, str) or not 1 <= len(path) <= 1024:
                raise e.InputError("nonempty bounded frame location required")
            stamps.append(stamp)
        if any(y <= x for x, y in zip(stamps, stamps[1:])):
            raise e.InputError("strict input-frame chronology required")
    if len(scopes) != 1:
        raise e.InputError("cannot reuse cached features across scopes")


@torch.no_grad()
def stream_cases(model, cases, root, base, policy, critic, *, batch_size=MAX_CELLS_PER_BATCH):
    """Run one frozen Reader, batch only currently active Cells at each depth.

    No known future feature is read by a stop decision. The exact frame SHA of
    future requests may be inspected for marginal cache cost, as in scalar run.
    Model/label independence is structural: labels are not accepted here.
    """
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_CELLS_PER_BATCH:
        raise e.InputError("declared bounded microbatch size required")
    kind = validate_policy(policy, critic)
    validate_cases(cases)
    if (model.training or any(p.requires_grad for p in model.parameters())
            or not isinstance(model, anytime.AnytimeCell)):
        raise e.InputError("frozen shared video Reader required")
    root = Path(root)
    tower = temporal.FrameCacheTowers(base)
    result, events, groups = [], [], []
    model_id = e.parameters(model)["sha256"]
    with e.measured() as total:
        for start in range(0, len(cases), batch_size):
            block = cases[start:start+batch_size]
            n = len(block)
            current = torch.zeros(n, model.core.hidden_size, dtype=torch.float32)
            active = list(range(n))
            rows = [{"case_id": c.case_id, "input_digest": c.input_digest,
                     "exits_seen": [], "scope": c.scope, "model_sha256": model_id} for c in block]
            with e.measured() as group_wall:
                for depth in anytime.DEPTHS:
                    if not active:
                        break
                    requested = [ref for i in active for ref in block[i].inputs["video"][depth-2:depth]]
                    before = tower.physical_video_calls
                    with e.measured() as pair_work:
                        features, stamps = tower.encode("video", requested, root)
                        expected = torch.tensor([ref["timestamp_us"] for ref in requested], dtype=torch.long)
                        if (not isinstance(features, torch.Tensor) or features.device.type != "cpu"
                                or features.dtype != torch.float32
                                or features.shape != (len(active)*2, model.project.in_features)
                                or not bool(torch.isfinite(features).all())
                                or not isinstance(stamps, torch.Tensor) or stamps.device.type != "cpu"
                                or stamps.dtype != torch.long or not torch.equal(stamps, expected)):
                            raise e.InputError("batched CLIP result/time/shape changed")
                        indices = torch.tensor(active, dtype=torch.long)
                        next_state = current[indices]
                        # One true batched GRUCell update per frame position.
                        for frame_index in (0, 1):
                            z = torch.tanh(model.project(features[frame_index::2].detach()))
                            next_state = model.core(z, next_state)
                        current[indices] = next_state
                        predictions = model.readout(next_state).softmax(-1).float()
                        temporal.score(predictions, torch.zeros(len(active), dtype=torch.long))
                    event_id = len(events)
                    new_active = []
                    for j, i in enumerate(active):
                        p = predictions[j:j+1]
                        estimate = (float(value.estimate(p, depth, critic)[0])
                                    if kind in ("value", "cache_value") and depth < 8 else None)
                        marginal = (value.next_pair_marginal(set(tower.cache),
                                      [f["sha256"] for f in block[i].inputs["video"]], depth)
                                    if kind == "cache_value" and depth < 8 else None)
                        price = (value.cache_price(policy["price"], marginal) if marginal is not None else None)
                        stop = (depth == 8 or kind == "fixed" and depth >= policy["depth"]
                                or kind == "confidence" and float(p.max()) >= policy["threshold"]
                                or kind == "value" and estimate is not None and estimate <= policy["price"]
                                or kind == "cache_value" and estimate is not None and estimate <= price)
                        row = rows[i]
                        row["exits_seen"].append({"depth": depth,
                            "probabilities": p[0].tolist(), "critic_value_estimate": estimate,
                            "next_pair_physical_calls_if_continued": marginal,
                            "next_pair_price_accuracy_units": price,
                            "shared_batch_event_id": event_id})
                        if stop:
                            row.update({"depth": depth, "prediction": int(p.argmax()),
                                        "probabilities": p[0].tolist()})
                        else:
                            new_active.append(i)
                    events.append({"batch": start//batch_size, "depth": depth,
                                   "case_ids": [block[i].case_id for i in active],
                                   "requested_frames": len(requested),
                                   "physical_video_calls": tower.physical_video_calls - before,
                                   "wall": pair_work, "charged_once_to_batch": True})
                    active = new_active
            if any("prediction" not in row for row in rows):
                raise e.InputError("unfinished microbatch Reader output")
            result.extend(rows)
            groups.append({"case_ids": [c.case_id for c in block], "wall": group_wall,
                           "microbatch_size": n})
    physical = {"unique_frames": len(tower.cache), "physical_video_calls": tower.physical_video_calls,
                "cache_hits": tower.frame_cache_hits,
                "requested_frame_rows": sum(row["depth"] for row in result),
                "isolated_cache": True, "batch_size_limit": batch_size,
                "microbatches": len(groups), "whole_stream_wall": total,
                "tower_calls_are_shared_not_per_cell": True}
    if sum(event["physical_video_calls"] for event in events) != tower.physical_video_calls:
        raise e.InputError("lost physical CLIP call accounting")
    if sum(event["requested_frames"] for event in events) != physical["requested_frame_rows"]:
        raise e.InputError("lost requested frame row accounting")
    return {"records": result, "events": events, "groups": groups, "physical_work": physical,
            "schedule": "fifo_microbatch_depth_synchronous", "production_accepted": False}


def run_shadow(model, cases, root, base, policies, critic, serial_records, serial_costs,
               output, *, selection_sha256, serial_predictions_sha256):
    """Opt-in, separately charged evaluation; never chooses from held-out labels."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    validate_cases(cases)
    if (not isinstance(policies, dict) or not all(x in policies for x in SHADOW_ARMS)
            or not isinstance(serial_records, dict) or not isinstance(serial_costs, dict)
            or type(selection_sha256) is not str or len(selection_sha256) != 64
            or type(serial_predictions_sha256) is not str or len(serial_predictions_sha256) != 64):
        raise e.InputError("externally presealed scalar study required")
    e.write_once(output / "plan.json", {"schema": "hepta.video-microbatch-plan.v1",
        "selection_sha256": selection_sha256, "scalar_predictions_sha256": serial_predictions_sha256,
        "source_sha256": e.sha(Path(__file__).read_bytes()), "batch_size": MAX_CELLS_PER_BATCH,
        "arms": SHADOW_ARMS, "label_blind": True, "production_accepted": False})
    studies, comparisons = {}, {}
    try:
        for arm in SHADOW_ARMS:
            observed = stream_cases(model, cases, root, base, policies[arm], critic)
            older = serial_records[arm]
            if [r["case_id"] for r in observed["records"]] != [r["case_id"] for r in older]:
                raise e.InputError("batched and scalar Cell coverage differs")
            same_depth = sum(a["depth"] == b["depth"] for a, b in zip(observed["records"], older))
            same_class = sum(a["prediction"] == b["prediction"] for a, b in zip(observed["records"], older))
            if policies[arm]["kind"] == "fixed":
                if same_depth != len(cases) or same_class != len(cases):
                    raise e.InputError("fixed-depth batched inference changed observable outcome")
                if any(not torch.allclose(torch.tensor(a["probabilities"]),torch.tensor(b["probabilities"]),
                                          atol=2e-5,rtol=2e-5)
                       for a,b in zip(observed["records"], older)):
                    raise e.InputError("fixed-depth microbatch output diverged")
            comparisons[arm] = {"cases": len(cases), "same_depth": same_depth,
                "same_prediction": same_class,
                "scalar_unique_frames": serial_costs[arm]["unique_frames"],
                "scalar_physical_calls": serial_costs[arm]["physical_video_calls"],
                "batched_unique_frames": observed["physical_work"]["unique_frames"],
                "batched_physical_calls": observed["physical_work"]["physical_video_calls"],
                "batched_schedule_changes_cache_visibility": True,
                "batched_decisions_not_claimed_equivalent_for_cache_value": arm == "cache_value"}
            studies[arm] = observed
            e.write_once(output / f"{arm}.json", observed)
        seal = e.write_once(output / "predictions.json", {"selection_sha256": selection_sha256,
            "scalar_predictions_sha256": serial_predictions_sha256,
            "case_ids": [c.case_id for c in cases], "arms": studies,
            "comparisons": comparisons})
        return {"schema": "hepta.video-microbatch-executed.v1", "predictions_sha256": seal,
            "comparison": comparisons, "shadow_charged_separately": True,
            "independent_quality_gain_established": False, "production_accepted": False}
    except Exception as error:
        e.write_once(output / "failure.json", {"exception": type(error).__name__,
            "message": str(error), "production_accepted": False})
        raise
