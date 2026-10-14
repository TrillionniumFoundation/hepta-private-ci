"""Fixed weak question-relevance training, not independent Reader qualification.

Reuse the registered TRAIN examples and sealed SELECT inputs. Every new fit
starts from the same base. No TEST targets, best-checkpoint selection, context
truncation, extra model family or accepted assistant-only projection.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import gc
from pathlib import Path

import five_causal_experiments as c
import question_evidence_relevance as relevance
import reader_content_swap as control
import reader_content_swap_trial as saved

SELECT_SHA = "aeb4113b6d2baace0a042f960876861c78b5449b6d9dac404dee2e5c041e46fa"
SELECT_SOURCE = "1672d4b3debb65bf0d7198464d9dc0c55811f08e"
ARMS = (("frozen_reader", None), ("repeat_empty", relevance.REPEAT_EMPTY),
        ("nonempty_aligned", relevance.ALIGNED), ("nonempty_reversed", relevance.REVERSED))
PLAN = {"schema": "hepta.reader.question-relevance-study.v1", "parent": "58583e9c4420415b4b87a5ef119a7705f4655319",
        "arms": ARMS, "epochs": 8, "base_objective": "paired-evidence-margin-v1",
        "relevance_loss_weight": 1.0, "vocabulary_projection": "full-logits-v1",
        "budget_artifact_sha256": saved.BUDGET_SHA, "select_artifact_sha256": SELECT_SHA,
        "train_questions": "exact_previously_admitted_dated_TRAIN_pairs",
        "donors": "unchanged_cross_family_equal_cardinality_identity_rule_on_TRAIN_only",
        "select_inputs": "exact_sealed_1672d4b3_public_inputs",
        "negative_label_status": "experimental_weak_question_swap_not_independently_proven_insufficient",
        "maximum_input_tokens": 2048, "maximum_output_tokens": 64, "per_call_seconds": 120,
        "automatic_selection": False, "compute_matched": False, "test_target_access": False,
        "independent_confirmation": False, "production_accepted": False}


def execution_arms(names=None):
    """Select execution units, never change the registered scientific arm census.

    Omitted names preserve historical full execution. Explicit subsets are
    recorded separately and cannot pass the existing full-result validator.
    A restarted arm starts at the original base/seed, NOT an incomplete adapter.
    """
    if names is None:
        return ARMS
    c.require(isinstance(names, (list, tuple)) and names
              and all(isinstance(x, str) for x in names)
              and len(set(names)) == len(names), "nonempty unique execution arm names required")
    chosen = tuple(row for row in ARMS if row[0] in names)
    c.require(tuple(row[0] for row in chosen) == tuple(names), "unknown or reordered execution arms")
    return chosen


def train_cases(original_cases, plan, train):
    """Keep old four TRAIN recipients; add matched/mismatched donor questions."""
    units = {u["question_id"]: u for u in plan["units"]}
    names = {c.digest(r["question_id"]): r["question_id"] for r in original_cases}
    # Donors may be other admitted TRAIN questions, not free-generation recipients.
    names.update({r["question_id"]: r["original_question_id"] for r in train})
    cases = []
    for old in original_cases:
        if old["split"] != "train" or old["condition"] != "support_only": continue
        qid = c.digest(old["question_id"]); unit = units[qid]
        own = control.neutral_request(old["request"])[0]
        common = {"question_id": old["question_id"], "family": old["family"], "split": "train"}
        for condition, request in (("own_sources", own), ("empty", own | {"evidence": []}),
                                   ("donor_sources", unit["mismatched_request"])):
            cases.append(common | {"condition": condition, "request": deepcopy(request)})
        if unit["donor_question_id"] is None:
            cases.append(common | {"condition": "matched_donor_question", "request": None})
        else:
            cases.append({"question_id": names[unit["donor_question_id"]], "family": unit["donor_family"],
                          "split": "train", "condition": "matched_donor_question",
                          "request": deepcopy(unit["matched_request"])})
    c.require(cases, "old TRAIN generation recipients unavailable")
    return cases


def run(original_archive, budget_archive, select_archive, work, output, *, only_arms=None):
    active_arms = execution_arms(only_arms)
    import torch
    from transformers import AutoTokenizer
    import five_reader_response_learning as learning
    import five_reader_response_trial as response
    import five_reader_evidence_pair_trial as parent
    import five_reader_evidence_pairs as pairs
    import source_time_evidence as metadata
    from source_time_evidence_trial import project_examples
    from five_native_historical_smoke import prepare_materials, snapshot, READER_INVENTORY, LOCOMO_SHA256
    from five_causal_native import public_text, generate_exact, count_forwards
    from experiments.shared_stem_cell.execution import LocalTextGenerator, measured
    from native import load

    work, output = Path(work), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    c.write_new(output/"plan.json", PLAN | {"training":learning.TRAINING})
    if only_arms is not None:
        c.write_new(output/"execution-subset.json", {"schema":"hepta.reader.execution-subset.v1",
            "arms":[a for a,_ in active_arms],"scientific_plan_unchanged":True,
            "full_study_completed_by_this_execution":False,"optimizer_state_resumed":False})
    with measured() as acquisition:
        br, bv = saved.extract_verified(budget_archive, work/"budget", saved.BUDGET_SHA)
        prior, prior_report = saved.validate_budget(br)
        sr, sv = saved.extract_verified(select_archive, work/"select", SELECT_SHA)
        c.require((sr/"source/tested-commit.txt").read_text().strip() == SELECT_SOURCE, "wrong SELECT source")
        selected = sr/"study"
        report = c.load(selected/"report.json")
        c.require(report["errors"] == [] and report["raw_sha256"] == c.file_sha(selected/"raw-answers.json")
                  and report["inventory_sha256"] == c.file_sha(selected/"inventory-plan.json"), "SELECT result identity")
        original, clean, staging = prepare_materials(Path(original_archive), work/"original")
    c.write_new(output/"materials.json", {"budget":bv,"select":sv,"original":staging,"cost":acquisition})
    matches=[p for p in original.rglob("*.json") if p.stat().st_size>50000 and c.file_sha(p)==LOCOMO_SHA256]
    c.require(len(matches)==1,"exact original benchmark missing")
    benchmark=load(matches[0],"locomo",expected_sha256=LOCOMO_SHA256,allow_unresolved_evidence=True)
    chosen, excluded=parent.choose(benchmark)
    reader=clean/"reader"; snap=snapshot(reader,"causal_lm",READER_INVENTORY)
    tokenizer=AutoTokenizer.from_pretrained(reader,local_files_only=True,trust_remote_code=False)
    capacity=c.load(reader/"config.json")["max_position_embeddings"]
    original_train,census=response.training_examples(benchmark,chosen["train"],tokenizer,capacity)
    train,_=project_examples(original_train,chosen["train"],benchmark.history,metadata.SOURCE_TIME)
    c.require(c.digest(train)==c.load(prior/"cohort.json")["train_sha256"],"original TRAIN cohort changed")
    forbidden=sorted(set(excluded)|{benchmark.families[q.family] for q in chosen["select"]})
    learning.validate_examples(train,forbidden)
    rp=relevance.build_plan(train,forbidden)
    prepared={p:relevance.prepare(tokenizer,train,position_cap=capacity,profile=p) for p in relevance.PROFILES}
    c.write_new(output/"train-plan.json",rp | {"census":census,"forbidden_families":forbidden})
    c.write_new(output/"train-compilation.json",{p:[m for _,m in rows] for p,rows in prepared.items()})
    previous_cases=c.load(prior/"public-inputs.json")
    donor_names=[{"question_id":c.digest(q.identity),"original_question_id":q.identity} for q in chosen["train"]]
    cases=train_cases(previous_cases,rp,donor_names)+c.load(selected/"public-inputs.json")
    select_plan=c.load(selected/"inventory-plan.json")
    comparisons=select_plan["comparisons"]
    select_compiled={x["question_id"]:control.compile_comparison(tokenizer,x,position_cap=capacity)
                     for x in comparisons if x["status"]=="available"}
    c.require(len(select_compiled)==report["coverage"]["compiled_recipients"],"SELECT comparison census changed")
    c.write_new(output/"public-inputs.json",cases); seal=c.file_sha(output/"public-inputs.json")
    raw, summaries, errors, tail, initial = [], {}, [], "0"*64, None
    with (output/"events.jsonl").open("xb") as journal:
        for arm,profile in active_arms:
            backend,training,arm_error,load_cost=None,None,None,None
            tail=c.journal_append(journal,{"event":"arm_started","arm":arm},tail)
            try:
                with measured() as load_cost: backend=LocalTextGenerator(reader,snap,PLAN["maximum_input_tokens"])
                if profile is not None:
                    training=learning.fit_response_adapter(backend,train,output/arm,forbidden_families=forbidden,
                        epochs=PLAN["epochs"],loss_profile=pairs.MARGIN,relevance_profile=profile)
                    c.require(initial is None or initial==training["initial_adapter_sha256"],"initialization drift")
                    initial=training["initial_adapter_sha256"]
                c.require(not backend.loaded.training and all(not p.requires_grad for p in backend.loaded.parameters()),"unfrozen model")
                before=learning.state_digest(backend.loaded.state_dict())
            except Exception as error:
                arm_error=str(error)[:1024]; errors.append({"arm":arm,"phase":"load_or_train","error":arm_error})
                tail=c.journal_append(journal,{"event":"arm_failed","arm":arm,"error":arm_error,"retry":False},tail)
            arm_raw=[]
            for slot,case in enumerate(cases):
                row={k:case[k] for k in ("question_id","family","split","condition")}
                row.update(arm=arm,trial_id=c.digest([arm,slot,row]),status="not_executed",answer=None,
                    evidence_ids=[] if case["request"] is None else [e["id"] for e in case["request"]["evidence"]])
                if case["request"] is None: row["status"]="unavailable_source_or_donor"
                elif arm_error is not None: row["status"]="blocked_model_or_training"
                else:
                    row["public_request_sha256"]=c.digest(case["request"])
                    tail=c.journal_append(journal,{"event":"generation_started",**row},tail)
                    decoder=learning.training_forward_owner(backend.loaded) if profile else backend.loaded.base_model
                    with measured() as cost,count_forwards(decoder) as calls:
                        try:
                            answer,detail=generate_exact(backend,public_text(case["request"]),PLAN["maximum_input_tokens"],PLAN["maximum_output_tokens"])
                            row.update(status="succeeded",answer=answer,**detail)
                        except Exception as error: row.update(status="failed",error=str(error)[:1024])
                    row.update(cost=cost,observed_decoder_forwards=calls["model_calls"])
                    if cost["wall_ns"]>PLAN["per_call_seconds"]*1e9: row["status"]="timeout_with_observed_output"
                    if row["status"]!="succeeded": errors.append({"arm":arm,"phase":"generation","trial_id":row["trial_id"]})
                tail=c.journal_append(journal,{"event":"generation_recorded",**row},tail)
                arm_raw.append(row);raw.append(row)
            c.write_new(output/(arm+"-raw.json"),arm_raw)
            c.write_new(output/(arm+"-raw-seal.json"),{"sha256":c.file_sha(output/(arm+"-raw.json")),"before_target_scoring":True})
            audits=[];train_diagnostics=[];integrity=False
            if backend is not None and arm_error is None:
                decoder=learning.training_forward_owner(backend.loaded) if profile else backend.loaded.base_model
                # Always diagnose the intended weak relevance orientation, even for the reversed arm.
                for batch,meta in prepared[relevance.ALIGNED]:
                    item={"question_id":meta["pair_id"],"extra_status":meta["extra_status"],"status":"not_executed"}
                    tail=c.journal_append(journal,{"event":"train_diagnostic_started","arm":arm,**item},tail)
                    with measured() as cost,count_forwards(decoder) as calls,torch.no_grad():
                        try:
                            base_scores=[float(pairs.sequence_score(backend.loaded,b)) for b,_ in batch["original"]["variants"]]
                            extra_scores=[float(pairs.sequence_score(backend.loaded,b)) for b,_ in batch["extra"]]
                            item.update(status="succeeded",original=pairs.metrics(base_scores),extra_log_scores=extra_scores,
                                matched_answer_margin=extra_scores[0]-extra_scores[1] if extra_scores else None,
                                mismatched_refusal_margin=extra_scores[3]-extra_scores[2] if extra_scores else None)
                        except Exception as error: item.update(status="failed",error=str(error)[:1024])
                    item.update(cost=cost,observed_decoder_forwards=calls["model_calls"])
                    if item["status"]!="succeeded": errors.append({"arm":arm,"phase":"train_diagnostic"})
                    tail=c.journal_append(journal,{"event":"train_diagnostic_recorded","arm":arm,**item},tail)
                    train_diagnostics.append(item)
                for recipient in select_plan["recipients"]:
                    item={k:recipient[k] for k in ("question_id","family","split","donor_question_id")}
                    item.update(status="unavailable_recipient_annotation",audit=None,observed_decoder_forwards=0)
                    if recipient["question_id"] in select_compiled:
                        tail=c.journal_append(journal,{"event":"select_audit_started","arm":arm,**item},tail)
                        with measured() as cost,count_forwards(decoder) as calls:
                            try:
                                item.update(status="succeeded",audit=control.score_comparison(backend.loaded,select_compiled[recipient["question_id"]]))
                                c.require(calls["model_calls"]==4,"SELECT audit forward count")
                            except Exception as error: item.update(status="failed",error=str(error)[:1024])
                        item.update(cost=cost,observed_decoder_forwards=calls["model_calls"])
                        if item["status"]=="failed": errors.append({"arm":arm,"phase":"select_audit"})
                    tail=c.journal_append(journal,{"event":"select_audit_recorded","arm":arm,**item},tail);audits.append(item)
                integrity=learning.state_digest(backend.loaded.state_dict())==before
                if not integrity: errors.append({"arm":arm,"phase":"model_integrity"})
            if backend is not None: backend.close();del backend;gc.collect()
            scores=response.score_rows(arm_raw,benchmark)
            for score,row in zip(scores,arm_raw): score["split"]=row["split"]
            c.write_new(output/(arm+"-scores.json"),scores)
            c.write_new(output/(arm+"-train-diagnostic.json"),train_diagnostics)
            c.write_new(output/(arm+"-content-audit.json"),audits)
            summaries[arm]={"training":training,"generation":parent.aggregate(scores),"content":control.summarize(audits),
                "load_cost":load_cost,"model_integrity_verified":integrity,
                "diagnostic_forwards":sum(x["observed_decoder_forwards"] for x in train_diagnostics+audits)}
            print(c.canonical({"completed_arm":arm,"generation":summaries[arm]["generation"],"content":summaries[arm]["content"]}).decode(),flush=True)
    c.require(len(raw)==len(cases)*len(active_arms) and c.file_sha(output/"public-inputs.json")==seal,"input/census drift")
    c.require(c.file_sha(matches[0])==LOCOMO_SHA256,"benchmark changed")
    c.write_new(output/"raw-answers.json",raw)
    result={"schema":"hepta.reader.question-relevance-result.v1","plan_sha256":c.digest(PLAN|{"training":learning.TRAINING}),
        "raw_sha256":c.file_sha(output/"raw-answers.json"),"planned_rows":len(raw),
        "successful_model_calls":sum(x["status"]=="succeeded" for x in raw),"arms":summaries,"errors":errors,
        "generation_forward_lower_bound":sum(x.get("observed_decoder_forwards",0) for x in raw),
        "weak_negative_labels_not_independently_adjudicated":True,"reader_adequacy_established":False,
        "independent_confirmation":False,"compute_matched":False,"production_accepted":False,"five_experiments_completed":False}
    if only_arms is not None:
        result.update(execution_subset=[a for a,_ in active_arms],full_study_completed_by_this_execution=False)
    c.write_new(output/"report.json",result); print("QUESTION_RELEVANCE_RESULT",c.canonical(result).decode(),flush=True)
    c.require(not errors,"retained question-relevance execution failures")
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("original-archive","budget-archive","select-archive","work","output"):
        p.add_argument("--"+key,type=Path,required=True)
    p.add_argument("--only-arm", action="append", choices=[a for a,_ in ARMS])
    args=p.parse_args()
    try: run(args.original_archive,args.budget_archive,args.select_archive,args.work,args.output,only_arms=args.only_arm)
    except Exception as error:
        if args.output.is_dir() and not (args.output/"failure.json").exists():
            c.write_new(args.output/"failure.json",{"error":str(error)[:2048],"completed":False,"production_accepted":False})
        raise
