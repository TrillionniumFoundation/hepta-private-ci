"""E20: label-blind output-compression decision/Brier perturbation controls.

Original pinned ModernBERT Reader logits; NO model forward and NO user labels.
A byte checksum is identity evidence, not source authentication. This is an
offline research snapshot, not a production precision or model selector.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
from math import exp, fsum, isfinite, nextafter
import json
from pathlib import Path
from time import process_time_ns, perf_counter_ns

from e14_multirc_route import ARMS, ARCHIVE_SHA, OBS_ID, read_prelabel, write_once
from e19_precision_pack import PROFILES, encode_group, group_source, margins_for, fp32, quantize

SCHEMA = "hepta.e20.original-reader-output-quality-bounds.v1"
REPEATS = 40


def sigmoid(margin: float) -> float:
    """Predict genuine original positive-class probability; no labels."""
    if type(margin) is not float or not isfinite(margin) or abs(margin) > 16:
        raise ValueError("unsupported original margin")
    return 1.0/(1.0+exp(-margin)) if margin >= 0 else exp(margin)/(1.0+exp(margin))


def binary_brier_bound(p0: float, p1: float) -> float:
    """Worst binary two-class squared-probability delta over y in {0,1}.

    Both original and reconstructed values are evaluated in Float64. One-ulp
    outward rounding is a numerical guard, NOT a formal FP verification tool.
    """
    if any(type(v) is not float or not isfinite(v) or not 0 <= v <= 1 for v in (p0,p1)):
        raise ValueError("invalid predictive probabilities")
    a = abs(2*p1*p1-2*p0*p0)
    b = abs(2*(1-p1)**2-2*(1-p0)**2)
    return nextafter(max(a,b), float("inf"))


def physical_batch_measure(obs: dict, repeats: int=REPEATS) -> dict:
    """Actual CPython arithmetic time of EXACT same 132 archived logits.

    Group-buffer construction and precision conversions are included; no
    pretrained forward, training, verification, transfer, storage or IO.
    Do not label these timings as target-host, GPU, watt, or service costs.
    """
    if type(repeats) is not int or not 4 <= repeats <= 200:
        raise ValueError("bounded meter repetitions")
    groups=group_source(obs)
    flows={name:[] for name in ("fp32_direct", "bf16_direct", "bf16_centered")}
    import statistics
    for _ in range(repeats):
        for mode in flows:
            cpu=process_time_ns(); wall=perf_counter_ns(); count=0
            for _,inds in groups:
                for arm in ARMS:
                    logits=margins_for(obs,arm,inds)
                    # Charge ONLY this route's complete numerical transform,
                    # not all seven research profiles in every timed arm.
                    if mode=="fp32_direct":
                        values=tuple(fp32(b-a) for a,b in logits)
                    elif mode=="bf16_direct":
                        values=tuple(fp32(quantize(b,"bf16")-quantize(a,"bf16"))
                                     for a,b in logits)
                    else:
                        fp32_margins=tuple(fp32(b-a) for a,b in logits)
                        anchor=fp32(fsum(fp32_margins)/len(fp32_margins))
                        values=tuple(fp32(anchor+quantize(fp32(m-anchor),"bf16"))
                                     for m in fp32_margins)
                    for margin in values:
                        sigmoid(float(margin));count+=1
            sample=(process_time_ns()-cpu,perf_counter_ns()-wall,count)
            if type(sample[0]) is not int or sample[0]<=0 or count!=132:
                raise ValueError("physical arithmetic batch missing")
            flows[mode].append(sample)
    def percentile(vals,p):
        ordered=sorted(vals)
        return ordered[min(len(vals)-1,max(0,(len(vals)*p+99)//100-1))]
    return {
        mode:{"actual_cpu_ns":[x[0] for x in samples],
              "actual_wall_ns":[x[1] for x in samples],
              "p50_cpu_ns":int(statistics.median(x[0] for x in samples)),
              "p95_cpu_ns":percentile([x[0] for x in samples],95),
              "work_per_batch":132}
        for mode,samples in flows.items()
    }


def analyze(obs: dict, *, meter_repeats: int=REPEATS) -> dict:
    groups=group_source(obs)
    if obs["observation_id"] != OBS_ID:
        raise ValueError("original source mismatch")
    rows=[]
    for (source,slot),inds in groups:
        per_arm={}
        for arm in ARMS:
            vals=encode_group(margins_for(obs,arm,inds))
            ref=vals["original_fp32"]
            profiles={}
            for name in PROFILES:
                cand=vals[name]
                if len(cand)!=len(ref):
                    raise ValueError("incomplete same-question alternatives")
                p_ref=tuple(sigmoid(float(x)) for x in ref)
                p_new=tuple(sigmoid(float(x)) for x in cand)
                # Original scorer uses logits.index(max(logits)); ties select 0.
                # Therefore positive class iff margin STRICTLY > 0 (not >=0).
                changes=sum((x>0)!=(y>0) for x,y in zip(ref,cand))
                max_abs=max(abs(a-b) for a,b in zip(p_ref,p_new))
                bounds=[binary_brier_bound(p,q) for p,q in zip(p_ref,p_new)]
                profiles[name]={
                    "hard_decision_changes_ties_choose_zero":changes,
                    "absolute_probability_shift_sum":fsum(abs(a-b) for a,b in zip(p_ref,p_new)),
                    "max_absolute_probability_shift":max_abs,
                    "binary_brier_worst_case_delta_sum":fsum(bounds),
                    "candidate_count":len(ref),
                    "max_brier_delta_per_case":max(bounds),
                }
            per_arm[arm]=profiles
        rows.append({"source_group":source,"question_slot":slot,
                     "candidate_count":len(inds),"arms":per_arm})
    summary={}
    for arm in ARMS:
        summary[arm]={}
        for name in PROFILES:
            total=sum(r["arms"][arm][name]["candidate_count"] for r in rows)
            if total!=33:raise ValueError("original 33-answer inventory changed")
            m=[r["arms"][arm][name] for r in rows]
            brier_upper=nextafter(fsum(x["binary_brier_worst_case_delta_sum"] for x in m)/total,float("inf"))
            summary[arm][name]={
                "hard_decision_changes":sum(x["hard_decision_changes_ties_choose_zero"] for x in m),
                "exact_archive_accuracy_parity_for_any_binary_labels":all(x["hard_decision_changes_ties_choose_zero"]==0 for x in m),
                "mean_absolute_probability_shift":fsum(x["absolute_probability_shift_sum"] for x in m)/total,
                "max_absolute_probability_shift":max(x["max_absolute_probability_shift"] for x in m),
                "human_label_independent_brier_delta_upper_bound":brier_upper,
                "brier_interval_is_an_fp64_numeric_envelope_not_formal_error_proof":True,
                "candidate_count":total,
            }
    return {"schema":SCHEMA,"authority":"DENY_ALL", "original_archive_sha256":ARCHIVE_SHA,
            "original_prelabel_observation_id":OBS_ID,"original_passages":4,"original_questions":8,
            "original_candidates":33,"complete_question_slate_required_for_centering":True,
            "tie_policy":"class_zero_on_equal_logits", "profiles":list(PROFILES),
            "model_weights_loaded":False,"new_pretrained_forward_count":0,
            "human_labels_seen_by_producer":False,"qualified_source_observer_signature":False,
            "numerical_precision_only_no_semantic_reasoning_claim":True,
            "selected_precision_changed":False,"real_online_service_gain":False,
            "production_accepted":False,"rows":rows,"summary":summary,
            "self_observed_cpu_arithmetic_only":physical_batch_measure(obs,meter_repeats),
            "complete_model_forward_training_caching_network_storage_energy_verifier_cost_measured":False,
            "hypothetical_4_Reader_panels_FP32_two_logits_bytes_only":1056,
            "hypothetical_4_Reader_panels_BF16_centered_anchors_bytes_only":392}


def produce(archive: str, path: str) -> str:
    return write_once(path,analyze(read_prelabel(archive)))


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--archive",required=True);cli.add_argument("--output",required=True)
    a=cli.parse_args()
    print(produce(a.archive,a.output),"DENY_ALL")
