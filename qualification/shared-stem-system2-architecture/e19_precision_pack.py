"""E19 genuine archived Reader logits: quantization ORDER, not a BF16 model.

The producer opens ONLY the original pre-human-score pretrained Reader bytes.
It performs actual FP32 arithmetic and simulates RNE casts of original logits,
or group-centered *signed class margins*. Nothing grants runtime authority.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from collections import defaultdict
from itertools import combinations
from math import fsum, isfinite
from struct import pack, unpack

from e14_multirc_route import ARMS, ARCHIVE_SHA, OBS_ID, read_prelabel, write_once

SCHEMA = "hepta.e19.real-reader-question-centered-output-precision.v1"
PROFILES = (
    "original_fp32",
    "bf16_two_logits_then_sub",
    "bf16_margin_after_sub",
    "bf16_question_centered_with_fp32_anchor",
    "fp16_two_logits_then_sub",
    "fp16_margin_after_sub",
    "fp16_question_centered_with_fp32_anchor",
)


def fp32(value: float) -> float:
    if type(value) not in (float, int) or not isfinite(value) or abs(value) > 8:
        raise ValueError("invalid bounded numerical value")
    return unpack(">f", pack(">f", float(value)))[0]


def quantize(value: float, profile: str) -> float:
    """IEEE RNE half/bfloat16 conversion of an FP32 input, independently checkable."""
    x = fp32(value)
    if profile == "fp32":
        return x
    if profile == "fp16":
        return float(unpack(">e", pack(">e", x))[0])
    if profile == "bf16":
        bits = unpack(">I", pack(">f", x))[0]
        upper, lower = bits >> 16, bits & 65535
        upper += int(lower > 32768 or (lower == 32768 and (upper & 1) == 1))
        return unpack(">f", pack(">I", upper << 16))[0]
    raise ValueError("unregistered numeric profile")


def group_source(obs: dict) -> list[tuple[tuple[str, int], tuple[int, ...]]]:
    if (type(obs) is not dict or obs.get("observation_id") != OBS_ID
            or obs.get("schema") != "hepta.multirc.genuine-answer-slate-frozen-readers.v1"
            or obs.get("actual_candidate_count") != 33 or obs.get("passage_count") != 4
            or obs.get("question_count") != 8 or obs.get("evaluation_labels_loaded") is not False
            or type(obs.get("rows")) is not list or len(obs["rows"]) != 33
            or type(obs.get("predictions")) is not dict or set(obs["predictions"]) != set(ARMS)):
        raise ValueError("unqualified original full-source prelabel observation")
    digest=sha256(json.dumps({k:v for k,v in obs.items() if k!="observation_id"},
                             sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    if digest != OBS_ID:
        raise ValueError("original research model content does not match fixed historical observation")
    groups: dict[tuple[str, int], list[int]] = defaultdict(list)
    seen = set()
    for i, r in enumerate(obs["rows"]):
        if (type(r) is not dict or set(r) != {"candidate_id", "original_v1_candidate",
                                                  "question_slot", "source_group", "task_id"}
                or type(r["source_group"]) is not str or type(r["question_slot"]) is not int
                or r["question_slot"] not in (0, 1) or type(r["task_id"]) is not str
                or r["task_id"] in seen):
            raise ValueError("missing or duplicate original question/candidate identity")
        seen.add(r["task_id"])
        groups[(r["source_group"], r["question_slot"])].append(i)
    if (len(groups) != 8 or len({k[0] for k in groups}) != 4
            or any(not 2 <= len(ix) <= 8 for ix in groups.values())
            or sum(map(len, groups.values())) != 33):
        raise ValueError("incomplete original genuine candidate/source census")
    return [(key, tuple(v)) for key, v in sorted(groups.items())]


def margins_for(obs: dict, arm: str, indices: tuple[int, ...]) -> tuple[tuple[float, float], ...]:
    pred = obs["predictions"][arm]
    if type(pred) is not list or len(pred) != 33:
        raise ValueError("missing original Reader prediction inventory")
    output = []
    for i in indices:
        row, item = obs["rows"][i], pred[i]
        if (type(item) is not dict or set(item) != {"logits", "question_slot", "source_group",
                                                   "task_id", "weights_sha256"}
                or (item["task_id"], item["source_group"], item["question_slot"]) !=
                    (row["task_id"], row["source_group"], row["question_slot"])
                or type(item["logits"]) is not list or len(item["logits"]) != 2):
            raise ValueError("mismatched original pretrained prediction")
        left, right = item["logits"]
        if fp32(left) != left or fp32(right) != right:
            raise ValueError("model output not exact originally archived FP32")
        output.append((left, right))
    return tuple(output)


def encode_group(logits: tuple[tuple[float, float], ...]) -> dict[str, tuple[float, ...]]:
    """The anchor requires a WHOLE SAME-QUESTION slate; never cross scopes.

    FP32 subtract, float64 correctly accumulated mean rounded to FP32, FP32
    centered residual -> BF16/FP16, reconstructed in FP32. This preserves
    original per-question representational DIFFERENCES, not task truth.
    """
    if not 2 <= len(logits) <= 8:
        raise ValueError("entire bounded question slate required")
    margin = tuple(fp32(b-a) for a, b in logits)
    anchor = fp32(fsum(margin)/len(margin))
    result = {"original_fp32": margin}
    for dtype in ("bf16", "fp16"):
        result[f"{dtype}_two_logits_then_sub"] = tuple(
            fp32(quantize(b,dtype) - quantize(a,dtype)) for a,b in logits)
        result[f"{dtype}_margin_after_sub"] = tuple(quantize(v,dtype) for v in margin)
        result[f"{dtype}_question_centered_with_fp32_anchor"] = tuple(
            fp32(anchor + quantize(fp32(v-anchor),dtype)) for v in margin)
    if set(result) != set(PROFILES):
        raise ValueError("incomplete precision profiles")
    return result


def metrics(reference: tuple[float, ...], candidate: tuple[float, ...]) -> dict:
    if len(reference) != len(candidate) or len(reference) < 2:
        raise ValueError("incomplete original per-question comparison")
    false_ties = 0
    reversed_pairs = 0
    agreement = 0
    exact_ties = 0
    for (a,b) in combinations(range(len(reference)),2):
        r = (reference[a]>reference[b])-(reference[a]<reference[b])
        v = (candidate[a]>candidate[b])-(candidate[a]<candidate[b])
        false_ties += int(r != 0 and v == 0)
        reversed_pairs += int(r*v == -1)
        agreement += int(r != 0 and r == v)
        exact_ties += int(v == 0)
    return {
        "distinct_candidate_margins":len(set(candidate)),
        "equal_margin_pairs":exact_ties,
        "candidate_pairs":len(reference)*(len(reference)-1)//2,
        "new_false_ties_relative_to_fp32":false_ties,
        "pair_order_reversals_relative_to_fp32":reversed_pairs,
        "non_tied_pair_order_preserved":agreement,
        "hard_prediction_changes_from_fp32":sum(int((r>=0)!=(v>=0)) for r,v in zip(reference,candidate)),
        "maximum_absolute_margin_error":max(abs(r-v) for r,v in zip(reference,candidate)),
        "maximum_candidate_margin_span":max(candidate)-min(candidate),
    }


def analyze(obs: dict) -> dict:
    groups = group_source(obs)
    data=[]
    for (source, slot), indices in groups:
        arms={}
        for arm in ARMS:
            strategies=encode_group(margins_for(obs,arm,indices))
            arms[arm]={profile:metrics(strategies["original_fp32"],strategies[profile])
                       for profile in PROFILES}
        data.append({"source_group":source,"question_slot":slot,"candidate_count":len(indices),"arms":arms})
    summary={}
    for arm in ARMS:
        summary[arm]={}
        for name in PROFILES:
            m=[row["arms"][arm][name] for row in data]
            summary[arm][name]={
                "candidate_invariant_questions":sum(q["distinct_candidate_margins"]==1 for q in m),
                "questions_with_candidate_signal":sum(q["distinct_candidate_margins"]>1 for q in m),
                "equal_margin_pairs":sum(q["equal_margin_pairs"] for q in m),
                "new_false_ties_relative_to_fp32":sum(q["new_false_ties_relative_to_fp32"] for q in m),
                "pair_order_reversals_relative_to_fp32":sum(q["pair_order_reversals_relative_to_fp32"] for q in m),
                "non_tied_pair_order_preserved":sum(q["non_tied_pair_order_preserved"] for q in m),
                "hard_prediction_changes_from_fp32":sum(q["hard_prediction_changes_from_fp32"] for q in m),
                "max_absolute_margin_error":max(q["maximum_absolute_margin_error"] for q in m),
            }
    return {
        "schema":SCHEMA,"authority":"DENY_ALL","archive_sha256":ARCHIVE_SHA,
        "original_pretrained_observation_id":OBS_ID,"original_passages":4,"original_questions":8,
        "original_candidates":33,"profiles":list(PROFILES),
        "operation":"FP32_pair_subtract_then_FP32_question_center_then_BF16_FP16_residual_cast",
        "original_fp32_pair_weight_bytes_only":264,"bf16_two_logits_storage_bytes_only":132,
        "bf16_margin_only_storage_bytes_only":66,
        "centered_bf16_margin_plus_fp32_question_anchor_storage_bytes_only":98,
        "no_new_pretrained_forwards":True,"original_model_weight_or_activation_precision_changed":False,
        "original_human_labels_opened_before_blind_seal":False,
        "real_model_serving_latency_measured":False,
        "question_bound_identity_required_for_centering":True,
        "additional_FP32_group_aggregation_cost_unmeasured":True,
        "online_inference_gain_established":False,"system2_fbsde_admitted":False,
        "production_accepted":False,"model_selected":False,
        "question_rows":data,"summary":summary,
    }


def produce(archive: str, output: str) -> str:
    return write_once(output, analyze(read_prelabel(archive)))


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", required=True)
    p.add_argument("--output", required=True)
    x=p.parse_args()
    print(produce(x.archive,x.output),"DENY_ALL")
