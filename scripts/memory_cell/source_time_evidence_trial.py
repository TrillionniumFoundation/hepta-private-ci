"""Fixed source-session-date ablation on the existing train/select Reader study.

Four cells of a representation x learning comparison, not a parameter search.
Original documents, source selection, labels, base model and objective remain.
All material is previously exposed development data; no semantic qualification.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import gc
from pathlib import Path

import source_time_evidence as metadata

ARMS = (
    ("content_frozen", metadata.CONTENT_ONLY, False),
    ("dated_frozen", metadata.SOURCE_TIME, False),
    ("dated_margin", metadata.SOURCE_TIME, True),
    ("content_margin", metadata.CONTENT_ONLY, True),
)
PLAN = {
    "schema": "hepta.reader.source-session-ablation.v1",
    "arms": ARMS,
    "parent_implementation": "61111917cc99bf4645b27f34a9c8be21ba01df77",
    "question_selection": "existing_train_select_identity_selection_no_replacement",
    "test_readout": False,
    "representation_change": "source_session_time_and_explicit_metadata_layout",
    "retrieve_before_projection": True,
    "question_date_inferred": False,
    "annotation_repair_or_filtering": False,
    "maximum_input_tokens": 2048,
    "maximum_output_tokens": 64,
    "per_call_seconds": 120,
    "automatic_selection": False,
    "compute_matched": False,
    "independent_confirmation": False,
    "production_accepted": False,
}


def project_examples(examples, queries, history, profile):
    index = {metadata.digest(q.identity): q for q in queries}
    projected, receipts = [], []
    for row in examples:
        if row["split"] not in ("train", "select") or row["question_id"] not in index:
            raise ValueError("unregistered question or evaluation partition")
        query = index[row["question_id"]]
        result = deepcopy(row)
        result["request"], receipt = metadata.project(row["request"], history(query), profile)
        projected.append(result)
        receipts.append({"example_id": row["id"], "split": row["split"], **receipt})
    return projected, receipts


def project_cases(cases, queries, history, profile):
    index = {q.identity: q for q in queries}
    projected, receipts = [], []
    for row in cases:
        if row["split"] not in ("train", "select") or row["question_id"] not in index:
            raise ValueError("unregistered free-generation question or partition")
        result = deepcopy(row)
        if row["request"] is not None:
            result["request"], receipt = metadata.project(
                row["request"], history(index[row["question_id"]]), profile)
            receipts.append({"question_id": row["question_id"], "condition": row["condition"], **receipt})
        projected.append(result)
    return projected, receipts


def run(archive, work, output):
    # Reuse the existing HF loader, pair trainer, exact generation and readout.
    # Imports are deferred so public-input projection tests require no models.
    import torch
    from transformers import AutoTokenizer
    import five_causal_experiments as c
    import five_reader_evidence_pair_trial as parent
    import five_reader_response_trial as response
    import five_reader_response_learning as learning
    import five_reader_evidence_pairs as pairs
    from five_causal_native import public_text, generate_exact, count_forwards
    from five_native_historical_smoke import (
        prepare_materials, snapshot, ARCHIVE_SHA256, LOCOMO_SHA256, READER_INVENTORY)
    from experiments.shared_stem_cell.execution import LocalTextGenerator, measured
    from native import load

    archive, work, output = Path(archive), Path(work), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    config = deepcopy(PLAN)
    config.update(archive_sha256=ARCHIVE_SHA256, benchmark_sha256=LOCOMO_SHA256,
                  training=deepcopy(learning.TRAINING), loss_profile=pairs.MARGIN,
                  margin_nats_per_token=pairs.MARGIN_NATS_PER_TOKEN,
                  contrast_weight=pairs.CONTRAST_WEIGHT,
                  readout_profile=response.READOUT_PROFILE,
                  parent_selection_plan_sha256=c.digest(parent.PLAN))
    c.write_new(output/"plan.json", config)
    sources = ("source_time_evidence.py", "source_time_evidence_trial.py",
               "five_reader_evidence_pair_trial.py", "five_reader_evidence_pairs.py",
               "five_reader_response_trial.py", "five_reader_response_learning.py",
               "five_causal_native.py", "five_native_historical_smoke.py")
    c.write_new(output/"source.json", {n:c.file_sha(Path(__file__).with_name(n)) for n in sources})
    with measured() as acquisition:
        original, clean, staging = prepare_materials(archive, work/"staged")
    c.write_new(output/"staging.json", {"cost":acquisition, **staging})
    matches = [p for p in original.rglob("*.json")
               if p.stat().st_size > 50000 and c.file_sha(p) == LOCOMO_SHA256]
    c.require(len(matches)==1, "exact historical benchmark missing")
    benchmark=load(matches[0],"locomo",expected_sha256=LOCOMO_SHA256,allow_unresolved_evidence=True)
    chosen, excluded=parent.choose(benchmark)
    tokenizer=AutoTokenizer.from_pretrained(clean/"reader",local_files_only=True,trust_remote_code=False)
    position_cap=c.load(clean/"reader/config.json")["max_position_embeddings"]
    train,census=response.training_examples(benchmark,chosen["train"],tokenizer,position_cap)
    forbidden=sorted(set(excluded)|{benchmark.families[q.family] for q in chosen["select"]})
    learning.validate_examples(train,forbidden)
    cases=parent.generation_cases(benchmark,chosen,train)
    queries=chosen["train"]+chosen["select"]
    c.write_new(output/"cohort.json", {"chosen":{s:[q.identity for q in rows] for s,rows in chosen.items()},
                 "excluded_test_families":excluded,"training_census":census,
                 "train_examples":len(train),"generation_cases":len(cases)})
    datasets={}
    for profile in metadata.PROFILES:
        transformed,train_receipts=project_examples(train,chosen["train"],benchmark.history,profile)
        requests,input_receipts=project_cases(cases,queries,benchmark.history,profile)
        learning.validate_examples(transformed,forbidden)
        # Preflight both representations on EXACTLY the same admitted cohort.
        # Added metadata never causes silent removal/replacement of long inputs.
        pairs.prepare(tokenizer,transformed,position_cap=position_cap)
        datasets[profile]=(transformed,requests)
        c.write_new(output/(profile+"-projection.json"),{"training":train_receipts,"generation":input_receipts})
        c.write_new(output/(profile+"-public-inputs.json"),requests)
    input_seals={profile:c.file_sha(output/(profile+"-public-inputs.json")) for profile in metadata.PROFILES}
    snap=snapshot(clean/"reader","causal_lm",READER_INVENTORY)
    previous, all_raw, summaries, errors, initial = "0"*64,[],{},[],None
    with (output/"events.jsonl").open("xb") as stream:
        for arm,profile,trainable in ARMS:
            backend,training,load_cost,arm_error=None,None,None,None
            data,requests=datasets[profile]
            previous=c.journal_append(stream,{"event":"arm_started","arm":arm,"representation":profile},previous)
            try:
                with measured() as load_cost:
                    backend=LocalTextGenerator(clean/"reader",snap,config["maximum_input_tokens"])
                if trainable:
                    training=learning.fit_response_adapter(backend,data,output/arm,
                                 forbidden_families=forbidden,loss_profile=pairs.MARGIN)
                    c.require(initial is None or training["initial_adapter_sha256"]==initial,"initial LoRA drift")
                    initial=training["initial_adapter_sha256"]
            except Exception as error:
                arm_error=type(error).__name__+": "+str(error)[:1024]
                errors.append({"arm":arm,"phase":"load_or_train","error":arm_error})
                previous=c.journal_append(stream,{"event":"arm_failed","arm":arm,"error":arm_error},previous)
            raw=[]
            for case in sorted(requests,key=lambda x:c.digest([x["split"],x["question_id"],x["condition"]])):
                row={k:case[k] for k in ("question_id","family","split","condition")}
                row.update(arm=arm,representation=profile,trial_id=c.digest([arm,row]),
                           status="not_executed",answer=None,
                           evidence_ids=[] if case["request"] is None else [e["id"] for e in case["request"]["evidence"]])
                if case["request"] is None:
                    row["status"]="unavailable_support_annotation"
                elif arm_error is not None:
                    row.update(status="blocked_model_or_training",error=arm_error)
                else:
                    row["public_request_sha256"]=c.digest(case["request"])
                    previous=c.journal_append(stream,{"event":"generation_started",**row},previous)
                    decoder=(learning.training_forward_owner(backend.loaded)
                             if hasattr(backend.loaded,"get_base_model") else backend.loaded.base_model)
                    with measured() as cost,count_forwards(decoder) as forwards:
                        try:
                            answer,details=generate_exact(backend,public_text(case["request"]),
                                  config["maximum_input_tokens"],config["maximum_output_tokens"])
                            row.update(status="succeeded",answer=answer,**details)
                        except Exception as error:
                            row.update(status="failed",error=type(error).__name__+": "+str(error)[:1024])
                    row.update(cost=cost,observed_decoder_forwards=forwards["model_calls"])
                    if cost["wall_ns"]>config["per_call_seconds"]*1e9:
                        row["status"]="timeout_with_observed_output"
                    if row["status"]!="succeeded":
                        errors.append({"arm":arm,"phase":"generation","trial_id":row["trial_id"]})
                previous=c.journal_append(stream,{"event":"generation_recorded",**row},previous)
                raw.append(row);all_raw.append(row)
            c.write_new(output/(arm+"-raw.json"),raw)
            c.write_new(output/(arm+"-raw-seal.json"),
                        {"sha256":c.file_sha(output/(arm+"-raw.json")),"before_teacher_forcing":True})
            conditional=None;teacher_cost=None;teacher_forwards=None;teacher_complete=False
            if backend is not None and arm_error is None:
                try:
                    select,select_census=parent.select_pairs(benchmark,chosen["select"],tokenizer,position_cap)
                    selected,_=project_examples(select,chosen["select"],benchmark.history,profile)
                    before=learning.state_digest(backend.loaded.state_dict())
                    decoder=(learning.training_forward_owner(backend.loaded)
                             if hasattr(backend.loaded,"get_base_model") else backend.loaded.base_model)
                    previous=c.journal_append(stream,{"event":"teacher_started","arm":arm},previous)
                    teacher={"model_calls":0}
                    try:
                        with measured() as teacher_cost,count_forwards(decoder) as teacher:
                            conditional=pairs.diagnose(backend.loaded,tokenizer,data+selected,position_cap=position_cap)
                    finally:
                        teacher_forwards=teacher["model_calls"]
                    c.require(teacher_forwards==4*len(conditional),"teacher forward count mismatch")
                    c.require(learning.state_digest(backend.loaded.state_dict())==before,"diagnostic changed weights")
                    teacher_complete=True
                    c.write_new(output/(arm+"-conditional.json"),
                                {"records":conditional,"select_census":select_census})
                except Exception as error:
                    errors.append({"arm":arm,"phase":"teacher","error":str(error)[:1024]})
                previous=c.journal_append(stream,{"event":"teacher_recorded","arm":arm,
                     "observed_decoder_forwards":teacher_forwards,"complete":teacher_complete,
                     "cost":teacher_cost,"retry_permitted":False},previous)
            if backend is not None:
                try:backend.close()
                except Exception as error:errors.append({"arm":arm,"phase":"close","error":str(error)[:1024]})
                del backend
                gc.collect()
            scored=response.score_rows(raw,benchmark)
            for score,row in zip(scored,raw):score["split"]=row["split"]
            c.write_new(output/(arm+"-scores.json"),scored)
            margin_summary=[]
            if conditional is not None and teacher_complete:
                for split in ("train","select"):
                    group=[x for x in conditional if x["split"]==split]
                    margin_summary.append({"split":split,"pairs":len(group),
                         "both_positive":sum(x["both_conditional_preferences_positive"] for x in group),
                         "mean_supported_margin":sum(x["supported_answer_margin"] for x in group)/len(group) if group else None,
                         "mean_empty_margin":sum(x["empty_refusal_margin"] for x in group)/len(group) if group else None})
            summaries[arm]={"representation":profile,"generation":parent.aggregate(scored),"conditional":margin_summary,
                  "training":training,"load_cost":load_cost,"teacher_cost":teacher_cost,
                  "teacher_forwards":teacher_forwards,"teacher_complete":teacher_complete}
            print(c.canonical({"completed_arm":arm,"generation":summaries[arm]["generation"],
                               "conditional":margin_summary}).decode(),flush=True)
    c.require(len(all_raw)==len(cases)*len(ARMS),"missing planned records")
    c.require(c.file_sha(matches[0])==LOCOMO_SHA256,"benchmark changed during study")
    c.require(all(c.file_sha(output/(profile+"-public-inputs.json"))==seal
                  for profile,seal in input_seals.items()),"public input bytes changed")
    c.write_new(output/"raw-answers.json",all_raw)
    report={"schema":"hepta.reader.source-session-ablation-result.v1","plan_sha256":c.digest(config),
            "raw_sha256":c.file_sha(output/"raw-answers.json"),"planned_rows":len(all_raw),
            "succeeded":sum(x["status"]=="succeeded" for x in all_raw),
            "actual_generation_forward_lower_bound":sum(x.get("observed_decoder_forwards",0) for x in all_raw),
            "arms":summaries,"errors":errors,"excluded_test_families":excluded,
            "independent_confirmation":False,"reader_adequacy_established":False,
            "compute_matched":False,"production_accepted":False,"five_experiments_completed":False}
    c.write_new(output/"report.json",report)
    print("SOURCE_TIME_RESULT",c.canonical(report).decode(),flush=True)
    c.require(not errors,"source-time ablation has retained execution failures")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive",type=Path)
    parser.add_argument("--work",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    try:run(args.archive,args.work,args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output/"failure.json").exists():
            (args.output/"failure.json").write_bytes(metadata.canonical(
                {"error":str(error)[:2048],"completed":False,"production_accepted":False}))
        raise
