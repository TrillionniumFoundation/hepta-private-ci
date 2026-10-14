"""Independent stdlib-only archived audit of grouped CLIP/GRU Cell execution.

Replays the microbatch queue, cache membership, critic routes and counters.
Does not import torch, use the runtime evaluator, attest physical forward calls,
verify source licensing, or certify population quality/production selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from experiments.shared_stem_cell import audit_video_value as v

ARMS = ("fixed_2", "fixed_8", "cache_value")


def audit(root):
    root = Path(root)
    baseline = v.audit(root)  # same sealed scalar source/critics, verified independently
    report = v.load(root / "value/report.json")
    meta = report.get("microbatch_shadow")
    v.need(isinstance(meta, dict) and meta.get("schema") == "hepta.video-microbatch-executed.v1",
           "missing microbatch execution")
    dataset = v.load(root / "manifest.json")["dataset"]
    cases = [json.loads(line) for line in (root / dataset["path"]).read_bytes().splitlines()]
    holdout = [case for case in cases if case["split"] == "holdout"]
    selection = v.load(root / "value/selection.json", report["selection_sha256"])
    original = v.load(root / "value/predictions.json", report["prediction_sha256"])
    plan = v.load(root / "value/batch/plan.json")
    saved = v.load(root / "value/batch/predictions.json", meta["predictions_sha256"])
    v.need(plan["schema"] == "hepta.video-microbatch-plan.v1"
           and plan["selection_sha256"] == report["selection_sha256"]
           and plan["scalar_predictions_sha256"] == report["prediction_sha256"]
           and plan["arms"] == list(ARMS) and plan["batch_size"] == 4,
           "batch experiment plan changed")
    v.need(saved["selection_sha256"] == report["selection_sha256"]
           and saved["scalar_predictions_sha256"] == report["prediction_sha256"]
           and saved["case_ids"] == [case["case_id"] for case in holdout]
           and set(saved["arms"]) == set(ARMS)
           and set(saved["comparisons"]) == set(ARMS),
           "batch/scalar predictions binding drift")
    coef = v.verify_critic(selection)
    audited = {}
    total_extra_calls = 0
    for arm in ARMS:
        data = saved["arms"][arm]
        v.need(v.load(root / f"value/batch/{arm}.json") == data,
               "individually sealed batch arm modified")
        policy = selection["policies"][arm]
        rows, events, groups = data["records"], data["events"], data["groups"]
        v.need(data["schedule"] == "fifo_microbatch_depth_synchronous"
               and len(rows) == len(holdout) and len(groups) == (len(holdout)+3)//4,
               "microbatch schedule/row count drift")
        seen, event_index, requested, calls, hits = set(), 0, 0, 0, 0
        for block_id, group in enumerate(groups):
            offset = 4 * block_id
            subset = holdout[offset:offset+4]
            v.need(group["case_ids"] == [r["case_id"] for r in subset]
                   and group["microbatch_size"] == len(subset),
                   "microbatch group membership drift")
            active = list(range(len(subset)))
            for d in v.DEPTHS:
                if not active:
                    break
                v.need(event_index < len(events), "missing microbatch event")
                event = events[event_index]
                names = [subset[i]["case_id"] for i in active]
                requested_ids = [ref["sha256"] for i in active
                                 for ref in subset[i]["inputs"]["video"][d-2:d]]
                expected_hits = sum(key in seen for key in requested_ids)
                fresh = set(requested_ids) - seen
                expected_calls = int(bool(fresh))
                v.need(event["batch"] == block_id and event["depth"] == d
                       and event["case_ids"] == names
                       and event["requested_frames"] == len(requested_ids)
                       and event["physical_video_calls"] == expected_calls
                       and event["charged_once_to_batch"] is True
                       and 0 < event["wall"]["wall_ns"],
                       "batched physical event/count drift")
                seen.update(fresh); hits += expected_hits
                requested += len(requested_ids); calls += expected_calls
                upcoming = []
                for i in active:
                    case = subset[i]
                    row = rows[offset+i]
                    visits = row["exits_seen"]
                    expected_digest = hashlib.sha256((json.dumps([case["scope"], case["inputs"]],
                        sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()).hexdigest()
                    v.need(row["case_id"] == case["case_id"]
                           and row["scope"] == case["scope"]
                           and row["input_digest"] == expected_digest,
                           "Cell identity/scope drift")
                    expected_position = (d//2)-1
                    v.need(len(visits) >= expected_position+1 and
                           visits[expected_position]["depth"] == d and
                           visits[expected_position]["shared_batch_event_id"] == event_index,
                           "batched Reader trace/order drift")
                    step = visits[expected_position]
                    p = step["probabilities"]
                    v.argmax(p)
                    estimate = v.value_est(p, d, coef) if d < 8 and policy["kind"] in ("value","cache_value") else None
                    identifiers = [f["sha256"] for f in case["inputs"]["video"]]
                    marginal = int(any(key not in seen for key in identifiers[d:d+2])) if d < 8 and policy["kind"] == "cache_value" else None
                    price = .005 + policy["price"]*marginal if marginal is not None else None
                    v.need(step["next_pair_physical_calls_if_continued"] == marginal
                           and step["next_pair_price_accuracy_units"] == price,
                           "batched cached marginal pricing drift")
                    if estimate is None:
                        v.need(step["critic_value_estimate"] is None,"unexpected batched critic")
                    else:
                        v.need(abs(step["critic_value_estimate"]-estimate) <= 1e-5,
                               "batched critic estimate drift")
                    stop = (d == 8 or policy["kind"] == "fixed" and d >= policy["depth"]
                            or policy["kind"] == "confidence" and max(p) >= policy["threshold"]
                            or policy["kind"] == "value" and estimate <= policy["price"]
                            or policy["kind"] == "cache_value" and estimate <= price)
                    if not stop:
                        upcoming.append(i)
                    else:
                        v.need(row["depth"] == d and row["prediction"] == v.argmax(p)
                               and row["probabilities"] == p and len(visits) == d//2,
                               "batched stop result changed")
                active = upcoming
                event_index += 1
        v.need(event_index == len(events),"unexpected microbatch events")
        physical = data["physical_work"]
        v.need(physical["unique_frames"] == len(seen)
               and physical["physical_video_calls"] == calls
               and physical["cache_hits"] == hits
               and physical["requested_frame_rows"] == requested
               and physical["batch_size_limit"] == 4
               and physical["microbatches"] == len(groups)
               and physical["tower_calls_are_shared_not_per_cell"] is True,
               "batch physical work ledger drift")
        scalar = original["records"][arm]
        same_depth = sum(a["depth"] == b["depth"] for a,b in zip(rows,scalar))
        same_prediction = sum(a["prediction"] == b["prediction"] for a,b in zip(rows,scalar))
        comp = saved["comparisons"][arm]
        v.need(comp["cases"] == len(holdout)
               and comp["same_depth"] == same_depth
               and comp["same_prediction"] == same_prediction
               and comp["batched_unique_frames"] == len(seen)
               and comp["batched_physical_calls"] == calls
               and comp["scalar_unique_frames"] == original["physical_work"][arm]["unique_frames"]
               and comp["scalar_physical_calls"] == original["physical_work"][arm]["physical_video_calls"],
               "scalar-vs-batch comparison drift")
        if policy["kind"] == "fixed":
            v.need(same_depth == len(holdout) and same_prediction == len(holdout),
                   "fixed-depth batched semantics drift")
        correct = sum(row["prediction"] == case["label"] for row,case in zip(rows,holdout))
        quality = report["microbatch_shadow_scores"][arm]
        v.need(quality["correct"] == correct and quality["cases"] == len(holdout),
               "batched postseal scoring drift")
        audited[arm] = {"cases":len(holdout),"correct":correct,"unique_frames":len(seen),
                        "physical_video_calls":calls,"requested_frame_rows":requested,
                        "same_prediction_as_scalar":same_prediction}
        total_extra_calls += calls
        v.need(meta["comparison"][arm] == comp, "microbatch report comparison drift")
    v.need(report["microbatch_shadow_total_extra_calls"] == total_extra_calls,
           "hidden microbatch shadow physical calls")
    return {"status":"audited_archived_consistency_only",
            "microbatch":audited,"extra_shadow_calls":total_extra_calls,
            "physical_tower_execution_attested":False,"population_latency_gain_certified":False}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(audit(args.root),sort_keys=True))
