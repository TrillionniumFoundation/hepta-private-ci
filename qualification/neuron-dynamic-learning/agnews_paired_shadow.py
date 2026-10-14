"""Physical Laya421 vs frozen/learned Gemma 2 on one pinned public task panel.

Diagnostic cross-sectional binary AG News only: no temporal future, owner outcome,
full lifecycle cost matching, independent model signature, FinalUse or promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

SCHEMA = "hepta.stem.agnews-binary-capability-panel.v1"
REPORT = "hepta.stem.agnews-physical-arm.v1"
ARMS = {"laya421_frozen", "gemma2_frozen_head", "gemma2_trained_head"}


class CapabilityError(ValueError):
    """Incomplete, unverifiable, or incomparable public capability evidence."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(x in "0123456789abcdef" for x in value)


def check_panel(panel: dict) -> tuple[str, dict]:
    if (not isinstance(panel, dict) or panel.get("schema") != SCHEMA or
            panel.get("dataset") != "szhuggingface/ag_news" or
            panel.get("dataset_commit_prefix") != "98c5322" or
            panel.get("cross_sectional_not_future") is not True or
            panel.get("pretrained_model_execution") is not False or
            panel.get("production_promotion") != "DENY_ALL" or
            panel.get("case_count") != 224):
        raise CapabilityError("unregistered public-only capability panel")
    from public_agnews_panel import FILES
    if panel.get("dataset_file_sha256") != {name: entry[1] for name, entry in FILES.items()}:
        raise CapabilityError("dataset source file hashes unbound")
    cases = panel.get("cases")
    if not isinstance(cases, list) or len(cases) != 224:
        raise CapabilityError("incomplete public panel")
    seen, sources, splits = set(), set(), {"train":[], "calibration":[], "test":[]}
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {
            "case_id", "split", "label", "label_name", "source_digest",
            "joint_input", "joint_input_digest", "group_id"}):
            raise CapabilityError("incomplete case identity")
        joint = case["joint_input"]
        if (not isinstance(joint, dict) or set(joint) != {"question", "options", "state"}
                or joint["question"] != "Which category does the news report describe?"
                or joint["options"] != ["world", "sports"]
                or not isinstance(joint["state"], str)
                or not 1 <= len(joint["state"].encode("utf-8")) <= 8192
                or type(case["label"]) is not int or case["label"] not in (0,1)
                or case["label_name"] != joint["options"][case["label"]]
                or case["source_digest"] != sha(joint["state"].encode("utf-8"))
                or case["joint_input_digest"] != sha(canonical(joint))
                or case["group_id"] != case["source_digest"]
                or case["case_id"] != case["source_digest"][:24]
                or case["case_id"] in seen or case["source_digest"] in sources
                or case["split"] not in splits):
            raise CapabilityError("source, group or task label leakage")
        seen.add(case["case_id"]); sources.add(case["source_digest"])
        splits[case["split"]].append(case)
    if {k:len(v) for k,v in splits.items()} != {"train":128,"calibration":32,"test":64}:
        raise CapabilityError("wrong fixed split count")
    for name, rows in splits.items():
        if sum(row["label"] for row in rows)*2 != len(rows):
            raise CapabilityError("not balanced in "+name)
    return sha(canonical(panel)), splits


def _bound_report(panel_digest: str, arm: str, rows: list, **metadata):
    return {"schema":REPORT, "panel_digest":panel_digest, "arm_id":arm,
            "rows":rows,"metadata":metadata,"real_model_execution_claim":True,
            "model_execution_independently_attested":False,
            "source_outcome_independently_attested":False,
            "cross_sectional_not_future":True,
            "physical_transformer_forward_calls":None,
            "full_lifecycle_equal_cost_verified":False,
            "production_promotion":"DENY_ALL"}


def _row(case, probability:float, elapsed_us:int):
    if (not isinstance(probability, (int,float)) or not math.isfinite(probability)
            or not 0 <= probability <= 1 or type(elapsed_us) is not int or elapsed_us <= 0):
        raise CapabilityError("missing finite probability or observed forward timing")
    return {"case_id":case["case_id"],
            "source_digest":case["source_digest"],
            "joint_input_digest":case["joint_input_digest"],
            "split":case["split"], "prob_sports":float(probability),
            "measured_serving_micros":elapsed_us}


def _fresh_report(panel_digest, original_digest, arm_id, rows, **metadata):
    return {
        "schema": "hepta.stem.agnews-confirmatory-physical-arm.v1",
        "panel_digest": panel_digest,
        "original_train_panel_digest": original_digest,
        "arm_id": arm_id, "rows": rows, "metadata": metadata,
        "raw_source_and_model_origin_independently_attested": False,
        "cross_sectional_new_source_not_temporal_future": True,
        "foundation_pretraining_overlap_ruled_out": False,
        "matched_full_lifecycle_cost": False,
        "production_promotion": "DENY_ALL",
    }


def run_gemma(panel:dict, runner, *, seed:int=17, steps:int=40, confirmatory=None):
    """Consume actual pinned-model Q24 receipts; fit existing bounded Head on train only."""
    import numpy as np
    from cell_learning import budgeted_cell, rust_candidate_digest
    from embeddinggemma2_shadow import rust_feature_digest_q24
    panel_digest, splits = check_panel(panel)
    if (getattr(runner,"_verified_local_weights",False) is not True or
            runner.manifest.get("dimension") != 256 or
            runner.manifest.get("profile") != "text"):
        raise CapabilityError("real approved 256d text snapshot required")
    if confirmatory is not None:
        from public_agnews_confirmatory import check_panel as check_fresh
        check_fresh(confirmatory, panel)
    all_cases = sum((splits[k] for k in ("train","calibration","test")),[])
    features, durations = {}, {}
    for j in range(0,len(all_cases),8):
        chunk=all_cases[j:j+8]
        batch=[]
        for case in chunk:
            data=canonical(case["joint_input"]).decode("utf-8")
            batch.append({"scope_id":"public.agnews", "principal_id":"shadow.cpu",
                          "purpose_id":"capability.noeffects",
                          "cell_id":"case."+case["case_id"],
                          "generation":1,"authority_epoch":1,
                          "input":{"modality":"text","role":"classification",
                                   "value":data,"sha256":sha(data.encode("utf-8"))}})
        tic=time.perf_counter_ns()
        receipt=runner.encode_cells(batch)
        elapsed=max(1,(time.perf_counter_ns()-tic)//1000)
        if (receipt.get("physical_local_model_execution") is not True or
                receipt.get("evidence_type")!="local_weight_execution_unverified_origin" or
                receipt.get("production_promotion")!="DENY_ALL" or
                receipt.get("feature_dimension")!=256 or
                receipt.get("cell_requests")!=len(chunk) or
                not isinstance(receipt.get("rows"),list) or len(receipt["rows"])!=len(chunk)):
            raise CapabilityError("incomplete physical feature receipt")
        for case, expected, observed in zip(chunk,batch,receipt["rows"]):
            values=observed.get("features_q24")
            if (not isinstance(values,list) or len(values)!=256 or
                    observed.get("cell_id")!=expected["cell_id"] or
                    observed.get("input_digest")!=expected["input"]["sha256"] or
                    observed.get("feature_digest")!=rust_feature_digest_q24(values) or
                    observed.get("pipeline_digest")!=runner.profile_digest or
                    any(observed.get(k)!=expected[k] for k in ("scope_id","principal_id", "purpose_id","generation","authority_epoch")) or
                    observed.get("authority")!="DENY_ALL"):
                raise CapabilityError("Q24/source/Cell order mismatch")
            features[case["case_id"]]=np.array(values,dtype=np.float64)/(1<<24)
            # Measured total batch wall time allocated equally, not per-sample latency.
            durations[case["case_id"]]=max(1, math.ceil(elapsed/len(chunk)))
    def xy(kind):
        cases=splits[kind]
        return np.stack([features[c["case_id"]] for c in cases]), np.array([c["label"] for c in cases], dtype=float)
    train_x, train_y=xy("train")
    head=budgeted_cell("shadow.agnews.binary",runner.profile_digest,256,2048,seed)
    frozen=head.clone_frozen()
    tic=time.perf_counter_ns()
    for _ in range(steps):
        head.learn(train_x,train_y,0.15)
    train_us=max(1,(time.perf_counter_ns()-tic)//1000)
    def sigmoid(x): return np.exp(-np.logaddexp(0.0,-x))
    reports=[]
    for arm, cell in (("gemma2_frozen_head",frozen),("gemma2_trained_head",head)):
        rows=[]
        for kind in ("calibration","test"):
            cases=splits[kind]
            x, _=xy(kind)
            tic=time.perf_counter_ns()
            probabilities=sigmoid(cell.predict(x))
            head_us=max(1,(time.perf_counter_ns()-tic)//1000)
            for c,p in zip(cases,probabilities):
                rows.append(_row(c,float(np.clip(p,1e-9,1-1e-9)),
                                 durations[c["case_id"]]+max(1,math.ceil(head_us/len(cases)))))
        reports.append(_bound_report(panel_digest,arm,rows,
            backend="google/embeddinggemma-2",revision=runner.manifest["revision"],
            stem_digest=runner.profile_digest,
            optimizer_steps=steps if arm.endswith("trained_head") else 0,
            local_head_train_micros=train_us if arm.endswith("trained_head") else 0,
            head_parameters=cell.parameter_count(),
            head_artifact_digest=rust_candidate_digest(cell.export_q24()),
            model_encode_api_calls=runner.model_encode_calls,
            cpu_batch_wall_allocation="equal_shared_batch_wall_amortized_not_direct_latency"))
    if confirmatory is not None:
        from public_agnews_confirmatory import check_panel as check_fresh
        from exploratory_temperature_probe import scale_probability
        from historical_head_anchor import check_values as require_previous_head
        # Reject a silently retrained/replaced Head BEFORE any new val2
        # input is passed through the real model.
        require_previous_head(
            original_panel_digest=panel_digest,
            gemma_revision=runner.manifest["revision"],
            stem_digest=runner.profile_digest,
            frozen_head_digest=rust_candidate_digest(frozen.export_q24()),
            trained_head_digest=rust_candidate_digest(head.export_q24()),
            head_parameters=head.parameter_count(),
            head_optimizer_steps=steps,
            training_seed=seed,
        )
        new_digest, new_cases = check_fresh(confirmatory, panel)
        extra_vectors, allocated_us = [], []
        for start in range(0, len(new_cases), 8):
            chunk = new_cases[start:start+8]
            batch = []
            for case in chunk:
                source = canonical(case["joint_input"]).decode("utf-8")
                batch.append({
                    "scope_id": "public.agnews", "principal_id": "shadow.cpu",
                    "purpose_id": "capability.noeffects",
                    "cell_id": "confirm."+case["case_id"],
                    "generation": 1, "authority_epoch": 1,
                    "input": {"modality":"text", "role":"classification", "value":source,
                              "sha256":sha(source.encode("utf-8"))},
                })
            wall = time.perf_counter_ns()
            receipt = runner.encode_cells(batch)
            micros = max(1, (time.perf_counter_ns()-wall)//1000)
            if (receipt.get("physical_local_model_execution") is not True
                    or receipt.get("evidence_type") != "local_weight_execution_unverified_origin"
                    or receipt.get("production_promotion") != "DENY_ALL"
                    or receipt.get("feature_dimension") != 256
                    or receipt.get("cell_requests") != len(batch)
                    or not isinstance(receipt.get("rows"), list)
                    or len(receipt["rows"]) != len(batch)):
                raise CapabilityError("unverified fresh cohort physical inference")
            for expected, observed in zip(batch, receipt["rows"]):
                values = observed.get("features_q24")
                if (not isinstance(values, list) or len(values) != 256
                        or observed.get("cell_id") != expected["cell_id"]
                        or observed.get("input_digest") != expected["input"]["sha256"]
                        or observed.get("feature_digest") != rust_feature_digest_q24(values)
                        or observed.get("pipeline_digest") != runner.profile_digest
                        or observed.get("authority") != "DENY_ALL"
                        or observed.get("modality") != "text"
                        or observed.get("role") != "classification"
                        or observed.get("requires_new_neuron_profile") is not False
                        or any(observed.get(k) != expected[k] for k in (
                            "scope_id", "principal_id", "purpose_id", "generation", "authority_epoch"))):
                    raise CapabilityError("new cohort source/cell/Q24 binding mismatch")
                extra_vectors.append(np.array(values, dtype=np.float64)/(1<<24))
                allocated_us.append(max(1, math.ceil(micros/len(chunk))))
        x = np.stack(extra_vectors)
        extra_reports = []
        for name, cell, multiplier in (
            ("gemma2_frozen_head", frozen, 1),
            ("gemma2_trained_head", head, 1),
            ("gemma2_trained_head_scaled_1024", head, 1024),
        ):
            wall = time.perf_counter_ns()
            raw = sigmoid(cell.predict(x))
            per_head_us = max(1,math.ceil(max(1,(time.perf_counter_ns()-wall)//1000)/len(new_cases)))
            probabilities = [float(np.clip(v,1e-9,1-1e-9)) for v in raw]
            if multiplier != 1:
                probabilities = [scale_probability(v, multiplier) for v in probabilities]
            rows = [_row(case, probability, spent+per_head_us) for case, probability, spent
                    in zip(new_cases, probabilities, allocated_us)]
            extra_reports.append(_fresh_report(new_digest,panel_digest,name,rows,
                backend="google/embeddinggemma-2",
                revision=runner.manifest["revision"],
                stem_digest=runner.profile_digest,
                frozen_head_digest=rust_candidate_digest(frozen.export_q24()),
                trained_head_digest=rust_candidate_digest(head.export_q24()),
                reported_head_digest=rust_candidate_digest(cell.export_q24()),
                trainable_head_parameters=cell.parameter_count(),
                head_training_steps=steps if cell is head else 0,
                predetermined_logit_multiplier=multiplier,
                shared_batch_wall_time_allocation="equal_amortization_not_individual_latency",
                pretrained_model_tokenization_identity_only="not_independently_attested"))
        return reports, extra_reports
    return reports


def run_laya(panel:dict, agent, *, revision:str, confirmatory=None):
    """Frozen Laya uses its own typed-choice realization of same semantic task."""
    panel_digest,splits=check_panel(panel)
    if not isinstance(revision,str) or len(revision)!=40:
        raise CapabilityError("explicit model revision required")
    if confirmatory is not None:
        from public_agnews_confirmatory import check_panel as check_fresh
        check_fresh(confirmatory, panel)
    questions={"category":{"type":"choice", "instructions":
              "Which category does the news report describe?",
              "criteria":{"world":"World news category","sports":"Sports news category"}}}
    rows=[]
    for kind in ("calibration","test"):
        for case in splits[kind]:
            tic=time.perf_counter_ns()
            response=agent.system_one({"text":case["joint_input"]["state"]},questions)
            elapsed=max(1,(time.perf_counter_ns()-tic)//1000)
            try:
                answer=response["answers"]["category"]
                probabilities=answer["probabilities"]
                if set(probabilities)!={"world","sports"}:
                    raise KeyError("not a 2-choice typed result")
                value=float(probabilities["sports"])
                if abs(float(probabilities["world"])+value-1)>1e-3:
                    raise ValueError("probabilities do not sum to 1")
            except (KeyError,TypeError,ValueError,AttributeError) as exc:
                raise CapabilityError("malformed Laya model probabilities") from exc
            rows.append(_row(case,value,elapsed))
    original = _bound_report(panel_digest,"laya421_frozen",rows,
            backend="convaiinnovations/laya",revision=revision,
            prompt_realization="typed_choice_described_world_sports",
            pretrained_checkpoint_verified_by_loader=True,
            trainable_parameters=0)
    if confirmatory is None:
        return original
    from public_agnews_confirmatory import check_panel as check_fresh
    new_digest, new_cases = check_fresh(confirmatory, panel)
    scored = []
    for case in new_cases:
        tic = time.perf_counter_ns()
        response = agent.system_one({"text":case["joint_input"]["state"]}, questions)
        micros = max(1,(time.perf_counter_ns()-tic)//1000)
        try:
            choices = response["answers"]["category"]["probabilities"]
            if (set(choices) != {"world","sports"}
                    or not all(type(v) in (float,int) and math.isfinite(v)
                               for v in choices.values())
                    or abs(choices["world"]+choices["sports"]-1) > 1e-3):
                raise ValueError("invalid frozen comparison probabilities")
            value = float(choices["sports"])
        except (KeyError, ValueError, AttributeError, TypeError) as exc:
            raise CapabilityError("malformed Laya output on new cohort") from exc
        scored.append(_row(case,value,micros))
    extra = _fresh_report(new_digest,panel_digest,"laya421_frozen",scored,
        backend="convaiinnovations/laya", revision=revision,
        prompt_realization="typed_choice_described_world_sports",
        pretrained_checkpoint_verified_by_loader=True,
        trainable_parameters=0,
        predetermined_logit_multiplier=1,
        shared_batch_wall_time_allocation="not_shared_singleton_calls")
    return original, extra


def compare(panel:dict,reports:list[dict]):
    panel_digest,splits=check_panel(panel)
    if (not isinstance(reports,list) or len(reports)!=3 or
            {x.get("arm_id") for x in reports if isinstance(x,dict)}!=ARMS):
        raise CapabilityError("all three physical arms are mandatory")
    expected={c["case_id"]:c for kind in ("calibration","test") for c in splits[kind]}
    series={}
    for report in reports:
        arm=report["arm_id"]
        if (report.get("schema")!=REPORT or report.get("panel_digest")!=panel_digest
                or report.get("production_promotion")!="DENY_ALL" or
                report.get("real_model_execution_claim") is not True or
                report.get("model_execution_independently_attested") is not False or
                report.get("source_outcome_independently_attested") is not False or
                report.get("cross_sectional_not_future") is not True or
                report.get("full_lifecycle_equal_cost_verified") is not False or
                report.get("physical_transformer_forward_calls") is not None):
            raise CapabilityError("unsupported authority or mismatched panel")
        seen={}
        rows=report.get("rows")
        if not isinstance(rows,list) or len(rows)!=len(expected):
            raise CapabilityError("arm missing observed cases")
        for row in rows:
            if not isinstance(row,dict) or set(row)!={"case_id","source_digest","joint_input_digest","split","prob_sports","measured_serving_micros"}:
                raise CapabilityError("wrong arm output schema")
            case=expected.get(row["case_id"])
            if (not case or row["case_id"] in seen or
                    any(row[k]!=case[k] for k in ("source_digest","joint_input_digest","split"))):
                raise CapabilityError("reused or changed paired case")
            p=row["prob_sports"]
            if (type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1
                    or type(row["measured_serving_micros"]) is not int or
                    row["measured_serving_micros"]<=0):
                raise CapabilityError("invalid probability or timing")
            seen[row["case_id"]]=row
        series[arm]=seen
    metrics={}
    for kind in ("calibration","test"):
        cases=splits[kind]
        metrics[kind]={}
        for arm in sorted(ARMS):
            rows=[series[arm][case["case_id"]] for case in cases]
            p=[x["prob_sports"] for x in rows]
            truth=[case["label"] for case in cases]
            # Equal-width, nonparametric ECE diagnostics; tiny cohorts are
            # descriptive, never an OOD or deployment calibration gate.
            calibration = []
            for start in range(8):
                group = [(a, b) for a, b in zip(p, truth)
                         if min(7, int(max(a, 1-a) * 8)) == start]
                if group:
                    actual = sum((a >= 0.5) == b for a, b in group) / len(group)
                    confidence = sum(max(a, 1-a) for a, _ in group) / len(group)
                    calibration.append(len(group) / len(p) * abs(actual-confidence))
            metrics[kind][arm]={
                "uncalibrated_ece_8_bin": sum(calibration),
                "cases":len(cases),"brier":sum((x-y)**2 for x,y in zip(p,truth))/len(cases),
                "accuracy":sum((x>=0.5)==y for x,y in zip(p,truth))/len(cases),
                "sum_measured_serving_micros":sum(x["measured_serving_micros"] for x in rows)}
    return {"schema":"hepta.stem.agnews-comparison.shadow.v1",
            "panel_digest":panel_digest,"arms":sorted(ARMS),"windows":metrics,
            "paired_same_source_case_ids":True,
            "pretrained_forward_claims_locally_recorded":True,
            "independent_model_and_outcome_authentication":False,
            "matched_full_lifecycle_cost":False,
            "three_future_windows_present":False,
            "ood_discrimination_tested":False,
            "posthoc_calibration_fit":False,
            "causal_longitudinal_learning":False,
            "production_promotion":"DENY_ALL"}



def _attach_laya_parameters(result, count: int, *, include_fresh: bool):
    """Bind the physical 421M count to both old and new reports without tuple aliasing.

    A confirmatory Laya run returns (original_report, val2_report); treating
    that tuple as a dict crashed the real public study after completing 96
    original model predictions. Reject malformed report pairs before mutation.
    """
    if type(count) is not int or not 400_000_000 <= count <= 450_000_000:
        raise CapabilityError("unqualified frozen Laya model parameter count")
    if include_fresh:
        if type(result) is not tuple or len(result) != 2:
            raise CapabilityError("missing paired original/new Laya reports")
        targets = result
    else:
        if not isinstance(result, dict):
            raise CapabilityError("expected one original frozen Laya report")
        targets = (result,)
    if any(not isinstance(row, dict) or row.get("arm_id") != "laya421_frozen"
           or not isinstance(row.get("metadata"), dict)
           or row["metadata"].get("backend") != "convaiinnovations/laya"
           or row["metadata"].get("trainable_parameters") != 0
           or row.get("production_promotion") != "DENY_ALL"
           for row in targets):
        raise CapabilityError("wrong or unbound frozen Laya arm payload")
    for row in targets:
        row["metadata"]["model_parameter_count"] = count
    return result


def main():
    p=argparse.ArgumentParser(description="Non-authorizing real model capability pair")
    p.add_argument("--mode",choices=("laya","gemma","compare"),required=True)
    p.add_argument("--panel",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--manifest",type=Path)
    p.add_argument("--snapshot",type=Path)
    p.add_argument("--sha-manifest",type=Path)
    p.add_argument("--revision")
    p.add_argument("--confirmatory-panel", type=Path)
    p.add_argument("--confirmatory-output", type=Path)
    p.add_argument("--gemma-report",type=Path)
    p.add_argument("--laya-report",type=Path)
    args=p.parse_args()
    panel=json.loads(args.panel.read_text(encoding="utf-8"))
    if (args.confirmatory_panel is None) != (args.confirmatory_output is None):
        raise CapabilityError("confirmatory input/output must be explicitly paired")
    if args.confirmatory_panel is not None and args.mode == "compare":
        raise CapabilityError("new cohorts require physical model mode, not comparator")
    confirmatory = (json.loads(args.confirmatory_panel.read_text(encoding="utf-8"))
                    if args.confirmatory_panel else None)
    if args.mode=="gemma":
        from embeddinggemma2_shadow import FrozenGemmaShadow
        if args.manifest is None: raise CapabilityError("exact Gemma manifest required")
        result=run_gemma(panel,FrozenGemmaShadow(args.manifest,device="cpu"),
                         confirmatory=confirmatory)
    elif args.mode=="laya":
        from laya import load
        if args.snapshot is None or args.sha_manifest is None or args.revision is None:
            raise CapabilityError("exact Laya snapshot and manifest required")
        hashes=json.loads(args.sha_manifest.read_text(encoding="utf-8"))
        if not isinstance(hashes,dict) or not hashes:
            raise CapabilityError("missing complete Laya file digests")
        agent=load(str(args.snapshot),device="cpu",expected_sha256=hashes)
        params=sum(p.numel() for p in agent.model.parameters())
        if not 400_000_000<=params<=450_000_000:
            raise CapabilityError("Laya baseline weight scale mismatch")
        result=run_laya(panel,agent,revision=args.revision,
                        confirmatory=confirmatory)
        result = _attach_laya_parameters(result, params, include_fresh=confirmatory is not None)
    else:
        if args.gemma_report is None or args.laya_report is None:
            raise CapabilityError("both real weight reports required")
        reports=json.loads(args.gemma_report.read_text(encoding="utf-8"))
        laya=json.loads(args.laya_report.read_text(encoding="utf-8"))
        result=compare(panel,[*reports,laya])
    if confirmatory is not None:
        result, extra = result
        args.confirmatory_output.write_bytes(canonical(extra))
    args.output.write_bytes(canonical(result))
    print(json.dumps({"mode":args.mode,"output":str(args.output),
                      "production_promotion":"DENY_ALL"},sort_keys=True))

if __name__=="__main__":
    main()
