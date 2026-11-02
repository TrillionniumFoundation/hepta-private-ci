"""Independent post-hoc constant-reference decision and utility reconstruction."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(base):
    base=Path(base);candidate=base.parent/"development001"
    protocol=json.loads((base/"PROTOCOL.json").read_text())
    summary=json.loads((base/"SUMMARY.json").read_text())
    assert protocol["posthoc_to_original_experiment"] is True
    assert protocol["original_B_selection_replaced"] is False
    assert protocol["historical_recordings_are_new_confirmation"] is False
    assert sha(candidate/"PLAN.json")==protocol["candidate_plan_sha256"]
    assert sha(base/"PROTOCOL.json")==summary["protocol_sha256"]
    assert sha(base/"TRACES.jsonl.gz")==summary["raw_sha256"]
    original=json.loads((candidate/"SCORES.json").read_text())
    frozen=json.loads((candidate/"FROZEN_MODELS.json").read_text())
    assert original["frozen_selection"]==frozen["selection"]
    labels={};endpoints={}
    with gzip.open(candidate/"TRACES.jsonl.gz","rt") as stream:
        for line in stream:
            row=json.loads(line);a,v=0,0
            for event in row["execution"]["events"]:
                if event.get("status")!="accepted":continue
                _,modality,level=event["action"].split(":")
                if modality=="audio":a=int(level)
                else:v=int(level)
            labels[row["task"],row["index"]]=row["label"]
            endpoints[row["task"],row["index"],a,v]=row["execution"]["output"]["probabilities"]
    with gzip.open(base/"TRACES.jsonl.gz","rt") as stream:runs=[json.loads(line) for line in stream]
    assert len(runs)==2*len(labels)==summary["runs"]
    indexed={};head_checked=0;head_not_covered=[]
    for row in runs:
        receipt=row["execution"];a,v=0,0
        for event in receipt["events"]:
            assert event.get("status") not in ("failed","rejected","timed_out")
            if event.get("status")!="accepted":continue
            _,modality,level=event["action"].split(":")
            if modality=="audio":assert int(level)==a+1;a=int(level)
            else:assert int(level)==v+1;v=int(level)
        assert row["label"]==labels[row["task"],row["index"]]
        key=row["task"],row["index"],a,v
        if key in endpoints:
            assert receipt["output"]["probabilities"]==endpoints[key];head_checked+=1
        else:head_not_covered.append(key)
        assert row["requests"]==receipt["requested_observations"]
        correct=int(np.argmax(receipt["output"]["probabilities"])==row["label"])
        assert correct==row["correct"]
        utility=correct-receipt["observation_fee"]-receipt["latency_fee"]-receipt["deadline_penalty"]
        assert abs(utility-row["utility"])<1e-12
        obs=receipt["observation_fee"]/receipt["requested_observations"]
        elapsed=receipt["latency_fee"]/receipt["output_elapsed_seconds"]
        for decision in receipt["decisions"]:
            if decision.get("mode")=="fixed":continue
            for candidate_value in decision["plans"]:
                assert candidate_value["correctness"]==.5
                assert candidate_value["deadline_miss_probability"]==0
                expected=.5-obs*candidate_value["expected_requested_reads"]-elapsed*candidate_value["expected_seconds"]
                assert abs(expected-candidate_value["score"])<1e-12
            best=max(decision["plans"],key=lambda r:(r["score"],r["plan"]),default=None)
            selected=best["plan"] if best is not None and best["score"]>decision["stop_score"] else None
            assert selected==decision["selected"]
        key=row["task"],row["index"],row["policy"]
        assert key not in indexed;indexed[key]=row
    effects={}
    for task in protocol["tasks"]:
        differences=[r["utility"]-indexed[task,r["index"],"value"]["utility"] for r in original["rows"]
                     if r["task"]==task and r["family"]=="renewal" and r["policy"]=="value"]
        delta=float(np.mean(differences))
        assert abs(delta-summary["contrasts"][task]["D_minus_constant_half_descriptive_mean"])<1e-12
        effects[task]=delta
    return {"runs_reconstructed":len(runs),"final_head_outputs_cross_checked_with_main_AV":head_checked,
        "final_endpoints_not_covered_by_main_AV_runs":head_not_covered,
        "D_minus_constant_half_descriptive_mean":effects,"original_B_selection_retained":True,
        "posthoc":True,"fresh_confirmation":False,
        "scope":"Additional validation-motivated historical logical-service reference; no replacement of original B or physical deployment timing claim"}
