"""Independent E13 scorer: original truth is visible ONLY in this process.

Re-checks source identity, per-Case frozen predictions, every E12 interval
certificate against an independently implemented full nonlinear tree, and
all route decisions before opening any success metric. Retrospective only.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from fractions import Fraction as Q
from hashlib import sha256
from math import comb, isfinite
import json
from pathlib import Path

from e7_second_opinion import (archive, group_labels, model_predictions,
                               HIST_SHA, REAL_SHA)
from e12_nonlinear_cert import Law, Solve, State, Trace
from e12_independent_audit import audit, exact, reference

SCHEMA = "hepta.e13.real-prediction-label-blind-fbsde-route.v1"
ARMS = ("granite_only", "mmbert_only", "confidence_075", "cheap_one_map", "e12_certified")
CUT = Q(1, 4)


def expect(ok: bool, why: str) -> None:
    if not ok:
        raise ValueError(why)


def json_read(data: bytes) -> dict:
    expect(type(data) is bytes and 0 < len(data) <= 1_000_000, "bounded sealed source required")
    def hook(pairs):
        d={}
        for k,v in pairs:
            expect(k not in d,"duplicate JSON key")
            d[k]=v
        return d
    return json.loads(data,object_pairs_hook=hook,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def take_source(path: str, declared_sha: str) -> dict:
    raw=Path(path).read_bytes()
    expect(type(declared_sha) is str and sha256(raw).hexdigest()==declared_sha,
           "sealed prelabel source SHA required")
    return json_read(raw)


def original_law(physical_p: float) -> Law:
    """Independent transformation: exact ASCII decimal -> floor uncertainty grid."""
    expect(type(physical_p) is float and isfinite(physical_p) and 0<=physical_p<=1,
           "invalid original archived probability")
    p=Q(str(physical_p))
    uncertain=2*min(p,1-p)
    n=(uncertain*64).numerator // (uncertain*64).denominator
    return Law(depth=2, a="1/3", x0=str(Q(n,64)))


def decode_cert(d: dict) -> Solve:
    expect(type(d) is dict and set(d)==set(Solve.__dataclass_fields__),
           "unknown or missing E12 certification field")
    t=d["trace"]
    expect(type(t) is dict and set(t)=={"states","z"}
           and type(t["states"]) is list and type(t["z"]) is list,
           "incomplete full stochastic tree")
    states=[]
    for s in t["states"]:
        expect(type(s) is dict and set(s)=={"x","y"},"malformed state")
        states.append(State(**s))
    return Solve(**{**d,"trace":Trace(tuple(states),tuple(t["z"]))})


def mcnemar_p(wins: int, losses: int) -> Q:
    n=wins+losses
    expect(type(wins) is int and type(losses) is int and 0<=n<=128,
           "invalid paired discordance")
    return min(Q(1), Q(2*sum(comb(n,k) for k in range(min(wins,losses)+1)),2**n)) if n else Q(1)


def score(proposer: dict, labels: dict, models: dict) -> dict:
    expected={"schema","authority","physical_archive_sha256",
              "human_labels_loaded_by_proposer","historical_source_archive_accessed",
              "new_pretrained_encoder_forwards","online_routing_executed",
              "numerical_model_is_fixed_nonlinear_toy",
              "all_human_sources_are_retrospective_one_AGNews_family",
              "depth","decision_threshold","quantization","arms","production_accepted","rows"}
    expect(type(proposer) is dict and set(proposer)==expected
           and proposer["schema"]==SCHEMA and proposer["authority"]=="DENY_ALL"
           and proposer["physical_archive_sha256"]==REAL_SHA
           and proposer["human_labels_loaded_by_proposer"] is False
           and proposer["historical_source_archive_accessed"] is False
           and type(proposer["new_pretrained_encoder_forwards"]) is int
           and proposer["new_pretrained_encoder_forwards"]==0
           and proposer["online_routing_executed"] is False
           and proposer["numerical_model_is_fixed_nonlinear_toy"] is True
           and proposer["all_human_sources_are_retrospective_one_AGNews_family"] is True
           and proposer["depth"]==2 and proposer["decision_threshold"]=="1/4"
           and proposer["quantization"]==64 and proposer["arms"]==list(ARMS)
           and proposer["production_accepted"] is False,
           "unapproved post-label research profile")
    rows=proposer["rows"]
    expect(type(rows) is list and len(rows)==128
           and list(sorted(labels))==[r.get("case_id") for r in rows]
           and set(models)=={"granite97","mmbert_small"},
           "missing or duplicate original source cases")
    summary={name:{"correct":0,"brier_sum":Q(0),"secondary_calls":0,
                   "archived_inference_time_proxy_ns":0,"recovered":0,"lost":0}
             for name in ARMS}
    full_cpu=cheap_cpu=0
    allowed_row={"case_id","group_id","joint_input_digest","granite_prob",
                 "mmbert_prob","granite_archived_ns","mmbert_archived_ns",
                 "x0","law","cheap_root","cheap_cpu_ns","cert","routes"}
    source_groups=[]
    for row in rows:
        expect(type(row) is dict and set(row)==allowed_row, "changed per-case proposal schema")
        cid=row["case_id"]
        g=labels[cid]
        pg,cg=models["granite97"][cid]
        pm,cm=models["mmbert_small"][cid]
        expect((row["group_id"],row["joint_input_digest"])==g[:2]
               and row["granite_prob"]==pg and row["mmbert_prob"]==pm
               and type(row["granite_archived_ns"]) is int and row["granite_archived_ns"]==cg
               and type(row["mmbert_archived_ns"]) is int and row["mmbert_archived_ns"]==cm,
               "original model/read source identity or cost changed")
        source_groups.append(row["group_id"])
        law=original_law(pg)
        expect(row["x0"]==law.x0 and row["law"]==asdict(law), "altered registered fixed law")
        cert=decode_cert(row["cert"])
        independence=audit(law,cert)
        expect(independence.certified and independence.independent_iteration_replay
               and not independence.natural_task_improvement_proven,
               "E12 independent whole-tree math invalid")
        exact_cheap=reference(law,(Q(0),)*(2**law.depth-1))[2][0]
        expect(row["cheap_root"]==str(exact_cheap),"cheap reference mismatch")
        expect(type(row["cheap_cpu_ns"]) is int and 0<row["cheap_cpu_ns"]<10**12,
               "unsupported numerical timer")
        cheap_cpu += row["cheap_cpu_ns"]
        full_cpu += cert.cpu_ns
        full_root=exact(cert.trace.states[0].y)
        full_bound=exact(cert.fixed_point_error_bound)
        expected_routes={
            "granite_only":False,
            "mmbert_only":True,
            "confidence_075": max(pg,1-pg) < .75,
            "cheap_one_map":exact_cheap>CUT,
            "e12_certified":full_root-full_bound>CUT,
        }
        expect(type(row["routes"]) is dict and row["routes"]==expected_routes
               and all(type(v) is bool for v in row["routes"].values()),
               "route changed after original labels or uncertified E12 interval")
        original_truth=g[2]
        base_good=(pg>=.5)==bool(original_truth)
        for name,second in expected_routes.items():
            chosen=pm if second else pg
            actual_good=(chosen>=.5)==bool(original_truth)
            s=summary[name]
            s["correct"]+=int(actual_good)
            s["brier_sum"]+=(Q(str(chosen))-original_truth)**2
            s["secondary_calls"]+=int(second)
            # Existing archived model-forward meters only; E12 local-process
            # CPU is recorded separately and MUST NOT be mixed as one host.
            s["archived_inference_time_proxy_ns"]+= (cm if name=="mmbert_only" else cg+(cm if second else 0))
            s["recovered"]+=int(actual_good and not base_good)
            s["lost"]+=int(base_good and not actual_good)
    expect(len(set(source_groups))==128,"source group leakage")
    base=summary["granite_only"]
    calibrated={}
    pvals={}
    for name in ARMS:
        s=summary[name]
        expect(s["correct"]==base["correct"]+s["recovered"]-s["lost"],
               "paired score arithmetic invalid")
        value={"n":128,"correct":s["correct"],
               "brier":float(s["brier_sum"]/128),
               "hypothetical_secondary_model_calls":s["secondary_calls"],
               "archived_inference_proxy_ns":s["archived_inference_time_proxy_ns"],
               "paired_recovered":s["recovered"],"paired_lost":s["lost"],
               "delta_correct_from_granite":s["correct"]-base["correct"],
               "extra_archived_proxy_ns_vs_granite":s["archived_inference_time_proxy_ns"]-base["archived_inference_time_proxy_ns"]}
        if name!="granite_only":
            pvals[name]=mcnemar_p(s["recovered"],s["lost"])
            value["exploratory_unadjusted_mcnemar_p_exact"]=str(pvals[name])
        calibrated[name]=value
    previous=Q(0)
    for i,(name,p) in enumerate(sorted(pvals.items(),key=lambda x:(x[1],x[0]))):
        previous=max(previous,min(Q(1),p*(len(pvals)-i)))
        calibrated[name]["holm_four_comparisons_p_exact"]=str(previous)
    return {
        "schema":"hepta.e13.independent-retrospective-task-and-cost-review.v1",
        "authority":"DENY_ALL", "case_count":128,
        "independent_original_label_panel_reloaded":True,
        "independent_E12_entire_tree_replayed_per_case":True,
        "registered_arms":list(ARMS),"scored":calibrated,
        "numerical_e12_solver_local_cpu_ns":full_cpu,
        "numerical_cheap_one_map_local_cpu_ns":cheap_cpu,
        "numerical_timers_are_different_host_to_original_pretrained":True,
        "entire_online_lifecycle_cost_qualified":False,
        "original_source_signer_authenticated":False,
        "future_time_task_outcome":False,
        "new_pretrained_model_forwards":0,
        "real_online_second_model_invocations":0,
        "neural_FBSDE_coefficient_identification":False,
        "continuous_time_stochastic_FBSDE_proven":False,
        "model_promotion_allowed":False,
        "production_accepted":False,
    }


def review(prelabel: str, prelabel_sha: str, historical_zip: str,
           physical_zip: str, output: str) -> str:
    src=take_source(prelabel,prelabel_sha)
    # The scorer -- unlike the proposer -- has the independently sealed
    # ORIGINAL human-source text+labels ZIP, and rereads the physical model.
    old=archive(historical_zip,HIST_SHA)
    new=archive(physical_zip,REAL_SHA)
    labels=group_labels(old)
    models=model_predictions(new,labels)
    findings=score(src,labels,models)
    findings["original_prelabel_sha256"]=prelabel_sha
    findings["original_historical_zip_sha256"]=HIST_SHA
    findings["original_physical_zip_sha256"]=REAL_SHA
    contents=(json.dumps(findings,sort_keys=True,separators=(",", ":"),allow_nan=False)+"\n").encode()
    with Path(output).open("xb") as f:
        f.write(contents)
    return sha256(contents).hexdigest()


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prelabel",required=True)
    ap.add_argument("--prelabel-sha256",required=True)
    ap.add_argument("--historical",required=True)
    ap.add_argument("--physical",required=True)
    ap.add_argument("--output",required=True)
    x=ap.parse_args()
    print(json.dumps({"independent_score_sha256":review(x.prelabel,x.prelabel_sha256,
           x.historical,x.physical,x.output),"authority":"DENY_ALL"},sort_keys=True))
