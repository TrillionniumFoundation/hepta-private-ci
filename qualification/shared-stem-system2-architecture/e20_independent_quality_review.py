"""E20 independent label-late review: no full-human label reconstruction.

Only the original HISTORICAL scored summary becomes visible to this separate
process AFTER the blind E20 output is frozen. Independently reconstructs all
33 candidates, avoids importing E19/E20 producer transform and applies the
actual class-zero-on-logit-tie rule. Does not certify any model efficacy.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from fractions import Fraction as Q
from hashlib import sha256
from math import fsum,isclose,isfinite,nextafter,tanh
from pathlib import Path
from zipfile import ZipFile
import json

from e14_multirc_route import ARMS, ARCHIVE_SHA, OBS_ID, read_prelabel, strict_json, write_once
from e19_independent_review import independent_f32, independent_cast, SCORE_SHA, SCORE_PATH

SCHEMA="hepta.e20.independent-original-quality-envelope.v1"
PROFILES=("original_fp32","bf16_two_logits_then_sub","bf16_margin_after_sub",
          "bf16_question_centered_with_fp32_anchor","fp16_two_logits_then_sub",
          "fp16_margin_after_sub","fp16_question_centered_with_fp32_anchor")


def independently_compute(source: dict) -> tuple[list,dict]:
    groups=defaultdict(list)
    for i,info in enumerate(source["rows"]):
        groups[(info["source_group"],info["question_slot"])].append(i)
    if len(groups)!=8 or len(source["rows"])!=33:
        raise ValueError("original groups changed")
    result=[]
    for (source_id,slot),ix in sorted(groups.items()):
        ars={}
        for arm in ARMS:
            originals=source["predictions"][arm]
            logits=[]
            for i in ix:
                record=originals[i]
                info=source["rows"][i]
                if (record["task_id"]!=info["task_id"]
                        or record["source_group"]!=source_id
                        or record["question_slot"]!=slot):
                    raise ValueError("unmatched real Reader origin")
                a,b=record["logits"]
                if a!=independent_f32(a) or b!=independent_f32(b):
                    raise ValueError("changed original FP32 evidence")
                logits.append((a,b))
            ref=tuple(independent_f32(b-a) for a,b in logits)
            center=independent_f32(float(sum((Q.from_float(v) for v in ref),Q(0))/len(ref)))
            vals={"original_fp32":ref}
            for precision in ("bf16","fp16"):
                vals[f"{precision}_two_logits_then_sub"]=tuple(
                    independent_f32(independent_cast(b,precision)-independent_cast(a,precision))
                    for a,b in logits)
                vals[f"{precision}_margin_after_sub"]=tuple(independent_cast(v,precision) for v in ref)
                vals[f"{precision}_question_centered_with_fp32_anchor"]=tuple(
                    independent_f32(center+independent_cast(independent_f32(v-center),precision)) for v in ref)
            probs_ref=tuple((1+tanh(v/2))/2 for v in ref)
            ars[arm]={}
            for profile in PROFILES:
                values=vals[profile]
                probabilities=tuple((1+tanh(v/2))/2 for v in values)
                # Binary Brier is sum of the two squared one-hot residuals.
                # The per-case max across y=0,1 is a source-label-blind bound.
                diffs=[]
                for p,q in zip(probs_ref,probabilities):
                    diffs.append(nextafter(2*abs(p-q)*max(p+q,2-p-q),float("inf")))
                ars[arm][profile]={
                    "hard_decision_changes_ties_choose_zero":sum((x>0)!=(y>0) for x,y in zip(ref,values)),
                    "absolute_probability_shift_sum":fsum(abs(p-q) for p,q in zip(probs_ref,probabilities)),
                    "max_absolute_probability_shift":max(abs(p-q) for p,q in zip(probs_ref,probabilities)),
                    "binary_brier_worst_case_delta_sum":fsum(diffs),
                    "max_brier_delta_per_case":max(diffs),
                    "candidate_count":len(ix),
                }
        result.append({"source_group":source_id,"question_slot":slot,"candidate_count":len(ix),"arms":ars})
    sums={}
    for arm in ARMS:
        sums[arm]={}
        for profile in PROFILES:
            rows=[v["arms"][arm][profile] for v in result]
            sums[arm][profile]={
                "hard_decision_changes":sum(v["hard_decision_changes_ties_choose_zero"] for v in rows),
                "mean_absolute_probability_shift":fsum(v["absolute_probability_shift_sum"] for v in rows)/33,
                "max_absolute_probability_shift":max(v["max_absolute_probability_shift"] for v in rows),
                "brier_delta_bound":nextafter(fsum(v["binary_brier_worst_case_delta_sum"] for v in rows)/33,float("inf")),
            }
    return result,sums


def same_numeric(a,b,*,atol=2e-14):
    if type(a) not in (float,int) or type(b) not in (float,int) or not isfinite(a) or not isfinite(b):
        return False
    return isclose(a,b,rel_tol=0,abs_tol=atol)


def review(blind_path: str, source_sha: str, archive: str, output: str) -> str:
    raw=Path(blind_path).read_bytes()
    if type(source_sha) is not str or sha256(raw).hexdigest()!=source_sha or not 500<len(raw)<500_000:
        raise ValueError("unsealed or oversized E20 evidence")
    d=strict_json(raw)
    flags={"schema":"hepta.e20.original-reader-output-quality-bounds.v1",
           "authority":"DENY_ALL","original_archive_sha256":ARCHIVE_SHA,
           "original_prelabel_observation_id":OBS_ID,"original_passages":4,"original_questions":8,
           "original_candidates":33,"complete_question_slate_required_for_centering":True,
           "tie_policy":"class_zero_on_equal_logits","model_weights_loaded":False,
           "new_pretrained_forward_count":0,"human_labels_seen_by_producer":False,
           "qualified_source_observer_signature":False,
           "numerical_precision_only_no_semantic_reasoning_claim":True,
           "selected_precision_changed":False,"real_online_service_gain":False,
           "production_accepted":False,"complete_model_forward_training_caching_network_storage_energy_verifier_cost_measured":False,
           "hypothetical_4_Reader_panels_FP32_two_logits_bytes_only":1056,
           "hypothetical_4_Reader_panels_BF16_centered_anchors_bytes_only":392}
    if type(d) is not dict or any(d.get(k)!=v or type(d.get(k)) is not type(v) for k,v in flags.items()):
        raise ValueError("E20 typed source/no authority contract changed")
    if set(d)!=(set(flags)|{"rows","summary","profiles","self_observed_cpu_arithmetic_only"}) or d["profiles"]!=list(PROFILES):
        raise ValueError("unknown/missing experimental fields")
    met=d["self_observed_cpu_arithmetic_only"]
    if type(met) is not dict or set(met)!={"fp32_direct","bf16_direct","bf16_centered"}:
        raise ValueError("declared Python arithmetic cost arms incomplete")
    for v in met.values():
        if type(v) is not dict or set(v)!={"actual_cpu_ns","actual_wall_ns","p50_cpu_ns","p95_cpu_ns","work_per_batch"}:
            raise ValueError("timing profile keys missing")
        cpu,wall=v["actual_cpu_ns"],v["actual_wall_ns"]
        if (type(cpu) is not list or type(wall) is not list or not 4<=len(cpu)<=200
                or len(cpu)!=len(wall) or type(v["work_per_batch"]) is not int or v["work_per_batch"]!=132
                or any(type(x) is not int or x<=0 or x>10**12 for x in cpu+wall)
                or any(type(v[z]) is not int or v[z]<=0 for z in ("p50_cpu_ns","p95_cpu_ns"))):
            raise ValueError("unpaid or fabricated research arithmetic counters")
        sorted_cpu=sorted(cpu)
        import statistics
        if v["p50_cpu_ns"]!=int(statistics.median(cpu)) or v["p95_cpu_ns"]!=sorted_cpu[(95*len(cpu)+99)//100-1]:
            raise ValueError("false arithmetic timing quantiles")
    original=read_prelabel(archive)
    expected_rows,expected_sums=independently_compute(original)
    got=d["rows"]
    if type(got) is not list or len(got)!=len(expected_rows):
        raise ValueError("question inventory missing")
    for orig,produced in zip(expected_rows,got):
        if (type(produced) is not dict or set(produced)!={"source_group","question_slot","candidate_count","arms"}
                or any(produced[k]!=orig[k] for k in ("source_group","question_slot","candidate_count"))
                or set(produced["arms"])!=set(ARMS)):
            raise ValueError("mixed source/group identity")
        for arm in ARMS:
            for mode in PROFILES:
                ref=orig["arms"][arm][mode]
                item=produced["arms"][arm][mode]
                if type(item) is not dict or set(item)!=set(ref):
                    raise ValueError("numeric row fields unsupported")
                for k,v in ref.items():
                    if k in ("candidate_count","hard_decision_changes_ties_choose_zero"):
                        if type(item[k]) is not int or item[k]!=v:raise ValueError("forged decision/count")
                    elif not same_numeric(item[k],v):raise ValueError("forged probability/brier row")
    if type(d["summary"]) is not dict or set(d["summary"])!=set(ARMS):
        raise ValueError("unqualified summary")
    for arm in ARMS:
        for mode in PROFILES:
            old=expected_sums[arm][mode]; val=d["summary"][arm][mode]
            if (type(val) is not dict or set(val)!={"hard_decision_changes",
                        "exact_archive_accuracy_parity_for_any_binary_labels",
                        "mean_absolute_probability_shift","max_absolute_probability_shift",
                        "human_label_independent_brier_delta_upper_bound",
                        "brier_interval_is_an_fp64_numeric_envelope_not_formal_error_proof",
                        "candidate_count"}
                    or type(val["hard_decision_changes"]) is not int
                    or val["hard_decision_changes"]!=old["hard_decision_changes"]
                    or val["exact_archive_accuracy_parity_for_any_binary_labels"] is not (old["hard_decision_changes"]==0)
                    or val["brier_interval_is_an_fp64_numeric_envelope_not_formal_error_proof"] is not True
                    or type(val["candidate_count"]) is not int or val["candidate_count"]!=33):
                raise ValueError("false original hard class/Brier assurance")
            for key,ref in (("mean_absolute_probability_shift",old["mean_absolute_probability_shift"]),
                            ("max_absolute_probability_shift",old["max_absolute_probability_shift"])):
                if not same_numeric(val[key],ref):raise ValueError("false summary probability effect")
            # Independent Float64 differences can be within 1e-14. Envelope
            # must not understate the independently reconstructed bound.
            bound=val["human_label_independent_brier_delta_upper_bound"]
            if (type(bound) is not float or not isfinite(bound) or bound<0
                    or bound+2e-14<old["brier_delta_bound"] or abs(bound-old["brier_delta_bound"])>2e-14):
                raise ValueError("false numeric Brier interval")
    # ORIGINAL historical human-scored summary, not a new label set.
    with ZipFile(archive) as z:
        score_raw=z.read(SCORE_PATH)
    if sha256(score_raw).hexdigest()!=SCORE_SHA:
        raise ValueError("original human summary changed")
    historic=strict_json(score_raw)
    if historic.get("candidate_count")!=33 or set(historic.get("results",{}))!=set(ARMS):
        raise ValueError("original human aggregate incomplete")
    outcomes={}
    for arm in ARMS:
        reference=historic["results"][arm]
        if type(reference["correct"]) is not int or reference["total"]!=33 or not 0<=reference["brier"]<=2:
            raise ValueError("invalid human original score")
        outcomes[arm]={}
        for profile in PROFILES:
            bound=d["summary"][arm][profile]["human_label_independent_brier_delta_upper_bound"]
            unchanged=d["summary"][arm][profile]["exact_archive_accuracy_parity_for_any_binary_labels"]
            outcomes[arm][profile]={
                "reconstructed_accuracy_correct_if_no_hard_changes":reference["correct"] if unchanged else None,
                "retrospective_original_binary_brier":reference["brier"],
                "potential_brier_interval_lower":max(0.,reference["brier"]-bound),
                "potential_brier_interval_upper":min(2.,reference["brier"]+bound),
                "this_is_an_envelope_not_rescored_human_labels":True,
                "new_human_labels_read":False,
                "quantization_ever_improved_accuracy_established":False,
            }
    return write_once(output,{
        "schema":SCHEMA,"source_blind_sha256":source_sha,"original_archive_sha256":ARCHIVE_SHA,
        "original_human_score_summary_sha256":SCORE_SHA,"authority":"DENY_ALL",
        "source_groups":4,"original_questions":8,"original_candidates":33,
        "all_precision_profiles_recomputed_by_distinct_algorithm":True,
        "historical_human_metric_envelopes":outcomes,
        "source_recomputed_hard_accuracy_parity":all(
            v["hard_decision_changes"]==0 for groups in expected_sums.values() for v in groups.values()),
        "tiny_grouped_arithmetic_timings_are_not_serving_costs":True,
        "prospective_task_improvement":False,"physical_bf16_model_forward":False,
        "qualified_online_memory_latency_or_energy":False,
        "production_accepted":False})


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--archive",required=True)
    cli.add_argument("--blind",required=True);cli.add_argument("--blind-sha256",required=True)
    cli.add_argument("--output",required=True)
    a=cli.parse_args()
    print(review(a.blind,a.blind_sha256,a.archive,a.output),"DENY_ALL")
