"""Independent second-algorithm E19 precision & historical-human audit.

Rebuilds the ENTIRE per-question report with Fraction/Decimal and exponent
rounding (not producer struct quantizers), after source byte integrity checks.
Original human score bytes are opened ONLY AFTER blind predictions are sealed.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from fractions import Fraction as Q
from hashlib import sha256
from itertools import combinations
from math import frexp, ldexp, isfinite
from pathlib import Path
from struct import pack,unpack
from zipfile import ZipFile

from e14_multirc_route import ARMS, ARCHIVE_SHA, OBS_ID, read_prelabel, strict_json, write_once

BLIND_SCHEMA="hepta.e19.real-reader-question-centered-output-precision.v1"
SCORE_PATH="multirc-native-candidate-scores/scores.json"
SCORE_SHA="3a3fd807585dd09ef4f089391dc68db4b008e87b69060f68f384a07daaa9f8e4"
PROFILES=("original_fp32","bf16_two_logits_then_sub","bf16_margin_after_sub",
          "bf16_question_centered_with_fp32_anchor","fp16_two_logits_then_sub",
          "fp16_margin_after_sub","fp16_question_centered_with_fp32_anchor")


def independent_f32(x):
    if type(x) not in (float, int) or not isfinite(x) or abs(x) > 8:
        raise ValueError("invalid original finite input")
    return unpack(">f",pack(">f",float(x)))[0]


def independent_cast(x, kind):
    x=independent_f32(x)
    if kind=="fp32":return x
    if kind not in ("bf16","fp16"):
        raise ValueError("unregistered alternate cast")
    if x==0:return x
    bits = 7 if kind=="bf16" else 10
    exponent = frexp(abs(x))[1]
    subnormal_min = -133 if kind=="bf16" else -24
    ulp = ldexp(1.0, max(exponent-bits-1,subnormal_min))
    return float(round(x/ulp)*ulp)


def independently_build(source: dict) -> dict:
    if (type(source) is not dict or source.get("observation_id")!=OBS_ID
            or source.get("schema")!="hepta.multirc.genuine-answer-slate-frozen-readers.v1"
            or source.get("actual_candidate_count")!=33 or source.get("question_count")!=8
            or source.get("passage_count")!=4 or source.get("evaluation_labels_loaded") is not False
            or type(source.get("rows")) is not list or len(source["rows"])!=33
            or type(source.get("predictions")) is not dict
            or set(source["predictions"])!=set(ARMS)):
        raise ValueError("not the original validated prelabel archive")
    origin=sha256(json.dumps({k:v for k,v in source.items() if k!="observation_id"},
                             sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    if origin != OBS_ID:
        raise ValueError("altered fixed-source historical model content")
    groups=defaultdict(list)
    for i,r in enumerate(source["rows"]):
        if (type(r) is not dict or set(r)!={"candidate_id","original_v1_candidate",
                                          "question_slot","source_group","task_id"}
                or type(r["source_group"]) is not str or type(r["question_slot"]) is not int
                or r["question_slot"] not in (0,1)):
            raise ValueError("malformed original public question")
        groups[(r["source_group"],r["question_slot"])].append(i)
    if len(groups)!=8 or len(set(g[0] for g in groups))!=4 or sum(map(len,groups.values()))!=33:
        raise ValueError("not eight complete original questions")
    output=[]
    for (source_id,slot),indices in sorted(groups.items()):
        if not 2<=len(indices)<=8:
            raise ValueError("not a bounded complete answer slate")
        arm_rows={}
        for arm in ARMS:
            original=source["predictions"][arm]
            if type(original) is not list or len(original)!=33:
                raise ValueError("missing pretrained Reader")
            logit_pairs=[]
            for i in indices:
                item=original[i];meta=source["rows"][i]
                if (type(item) is not dict or set(item)!={"logits","question_slot",
                         "source_group","task_id","weights_sha256"}
                        or [item[k] for k in ("task_id","source_group","question_slot")]!=
                           [meta[k] for k in ("task_id","source_group","question_slot")]
                        or type(item["logits"]) is not list or len(item["logits"])!=2):
                    raise ValueError("mismatched archived Reader prediction")
                a,b=item["logits"]
                if a!=independent_f32(a) or b!=independent_f32(b):
                    raise ValueError("non-exact original FP32 logits")
                logit_pairs.append((a,b))
            # Exact rational summation of FP32-subtracted dyadic margins.
            ref=tuple(independent_f32(b-a) for a,b in logit_pairs)
            mean=independent_f32(float(sum((Q.from_float(v) for v in ref),Q(0))/len(ref)))
            values={"original_fp32":ref}
            for mode in ("bf16","fp16"):
                values[f"{mode}_two_logits_then_sub"]=tuple(
                    independent_f32(independent_cast(b,mode)-independent_cast(a,mode))
                    for a,b in logit_pairs)
                values[f"{mode}_margin_after_sub"]=tuple(independent_cast(v,mode) for v in ref)
                values[f"{mode}_question_centered_with_fp32_anchor"]=tuple(
                    independent_f32(mean+independent_cast(independent_f32(v-mean),mode)) for v in ref)
            computed={}
            for mode in PROFILES:
                arr=values[mode]
                compare=[((ref[i]>ref[j])-(ref[i]<ref[j]), (arr[i]>arr[j])-(arr[i]<arr[j]))
                         for i,j in combinations(range(len(arr)),2)]
                computed[mode]={
                    "distinct_candidate_margins":len(set(arr)),
                    "equal_margin_pairs":sum(q==0 for _p,q in compare),
                    "candidate_pairs":len(arr)*(len(arr)-1)//2,
                    "new_false_ties_relative_to_fp32":sum(p!=0 and q==0 for p,q in compare),
                    "pair_order_reversals_relative_to_fp32":sum(p*q==-1 for p,q in compare),
                    "non_tied_pair_order_preserved":sum(p!=0 and p==q for p,q in compare),
                    "hard_prediction_changes_from_fp32":sum((p>=0)!=(q>=0) for p,q in zip(ref,arr)),
                    "maximum_absolute_margin_error":max(abs(p-q) for p,q in zip(ref,arr)),
                    "maximum_candidate_margin_span":max(arr)-min(arr),
                }
            arm_rows[arm]=computed
        output.append({"source_group":source_id,"question_slot":slot,
                       "candidate_count":len(indices),"arms":arm_rows})
    summary={}
    for arm in ARMS:
        summary[arm]={}
        for mode in PROFILES:
            vals=[x["arms"][arm][mode] for x in output]
            summary[arm][mode]={
                "candidate_invariant_questions":sum(r["distinct_candidate_margins"]==1 for r in vals),
                "questions_with_candidate_signal":sum(r["distinct_candidate_margins"]>1 for r in vals),
                "equal_margin_pairs":sum(r["equal_margin_pairs"] for r in vals),
                "new_false_ties_relative_to_fp32":sum(r["new_false_ties_relative_to_fp32"] for r in vals),
                "pair_order_reversals_relative_to_fp32":sum(r["pair_order_reversals_relative_to_fp32"] for r in vals),
                "non_tied_pair_order_preserved":sum(r["non_tied_pair_order_preserved"] for r in vals),
                "hard_prediction_changes_from_fp32":sum(r["hard_prediction_changes_from_fp32"] for r in vals),
                "max_absolute_margin_error":max(r["maximum_absolute_margin_error"] for r in vals),
            }
    return {
        "schema":BLIND_SCHEMA,"authority":"DENY_ALL","archive_sha256":ARCHIVE_SHA,
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
        "question_rows":output,"summary":summary,
    }


def equal_with_types(actual,expected):
    if type(actual) is not type(expected):
        raise ValueError("forged report type or authority status")
    if type(expected) is dict:
        if set(actual)!=set(expected):
            raise ValueError("missing/extra precision receipt fields")
        for key in expected:equal_with_types(actual[key],expected[key])
    elif type(expected) is list:
        if len(actual)!=len(expected):
            raise ValueError("incomplete original question summary")
        for a,b in zip(actual,expected,strict=True):equal_with_types(a,b)
    elif actual!=expected:
        raise ValueError("mutated precision output or false quantization identity")


def review(archive: str, blind_path: str, sealed_sha256: str, output: str) -> str:
    data=Path(blind_path).read_bytes()
    if not 0<len(data)<=1_000_000 or type(sealed_sha256) is not str or sha256(data).hexdigest()!=sealed_sha256:
        raise ValueError("missing create-only prelabel source seal")
    blind=strict_json(data)
    original=read_prelabel(archive)
    independent=independently_build(original)
    equal_with_types(blind,independent)
    # Preserve the original historical evidence after the blind seal exists.
    with ZipFile(archive) as z:
        human_raw=z.read(SCORE_PATH)
    if sha256(human_raw).hexdigest()!=SCORE_SHA:
        raise ValueError("original human task score bytes changed")
    human=strict_json(human_raw)
    if (human.get("schema")!="hepta.multirc.genuine-answer-slate-evaluation.v1"
            or human.get("observation_id")!=OBS_ID or human.get("candidate_count")!=33
            or human.get("question_count")!=8 or human.get("production_authorized") is not False
            or any(human.get("results",{}).get(a,{}).get("mixed_label_question_count")!=8 for a in ARMS)):
        raise ValueError("original human-label negative-control cannot be verified")
    given=blind["summary"]["conditioned"]
    if [(given[m]["candidate_invariant_questions"],given[m]["new_false_ties_relative_to_fp32"])
        for m in ("original_fp32","bf16_two_logits_then_sub","bf16_margin_after_sub",
                  "bf16_question_centered_with_fp32_anchor")] != [(4,0),(8,19),(8,19),(4,0)]:
        raise ValueError("registered negative and signal-preservation controls drifted")
    if blind["summary"]["no_query"]["bf16_question_centered_with_fp32_anchor"]["candidate_invariant_questions"]!=8:
        raise ValueError("unrecoverable original invariant Reader falsely amplified")
    return write_once(output,{
        "schema":"hepta.e19.independent-fp32-bf16-precision-replay.v1",
        "authority":"DENY_ALL","original_archive_sha256":ARCHIVE_SHA,
        "original_human_scoring_sha256":SCORE_SHA,"blind_input_sha256":sealed_sha256,
        "historical_human_questions_with_mixed_labels":8,
        "conditioned_input_exactly_invariant_questions":4,
        "conditioned_question_centered_bf16_recovered_noninvariant_questions":4,
        "conditioned_bf16_raw_logits_equal_pairs":55,
        "conditioned_group_centered_bf16_equal_pairs":36,
        "proof_applies_to_post_logit_format_only":True,
        "physical_bf16_foundation_encoder_rerun":False,
        "new_pretrained_model_forwards":0,
        "source_label_observer_independently_signed":False,
        "actual_online_latency_or_watt_benefit":False,
        "training_gain_or_end_to_end_task_success":False,
        "fbsde_online_promotion":False,"model_selected":False,"production_accepted":False,
    })


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("archive","blind","blind-sha256","output"):
        p.add_argument("--"+name,required=True)
    a=p.parse_args()
    print(review(a.archive,a.blind,a.blind_sha256,a.output),"DENY_ALL")
