"""Score *after* original source-only Head prediction bytes have been sealed.

Original published LoCoMo evaluation annotations, not human-certified future
observations. No Reader runs, no semantic citation precision or learned-memory
admission. Fail closed against altered original frozen lexical source baseline.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
from locomo_tiny_source_head_transfer import (ARMS, DEC_SHA, PUB_SHA, PROFILE,
    loaded_public, original_zip, regular, sha, strict)

GOLD_SHA = "d09823324003ab431301e60fbbb280e216ca03b686e178d4f36fb6d492981978"
OLD_SHA = "41866a4dd8a14abd9430338942f5d8c7f9affccacc110b6a4f27be32f2846823"
PRESEAL_SHA = "88806853eb03eaca083d604934782186063e09050c0dbb2a251cb6e81d7a43ff"


def load_evaluation(zip_path):
    content=original_zip(zip_path,GOLD_SHA,("targets.json",))
    gold=strict(content["targets.json"])
    if not isinstance(gold,dict) or len(gold)!=16:
        raise ValueError("published original 16-question LoCoMo gold required")
    return gold


def score_sealed(public_zip,decision_zip,weights_path,predictions_path,preseal_path,gold_zip,original_report_zip):
    population,docs,catalog=loaded_public(public_zip,decision_zip)
    preseal=strict(regular(preseal_path))
    if (sha(regular(preseal_path))!=PRESEAL_SHA
        or preseal.get("schema")!="hepta.memorycell.locomo-source-head-pre-target-seal.v1"
        or preseal.get("evaluation_target_bytes_opened") is not False
        or preseal.get("actual_torch_training_updates")!=384
        or preseal.get("original_evaluation_family_groups")!=2
        or preseal.get("original_eval_questions")!=16
        or preseal.get("files")!={
          "locomo_transfer_weights_sealed.json":sha(regular(weights_path)),
          "locomo_transfer_predictions_before_targets.json":sha(regular(predictions_path))
        }):
        raise ValueError("missing immutable original pre-gold reader-input seal")
    policy,predictions=[strict(regular(p)) for p in (weights_path,predictions_path)]
    if (policy.get("schema")!=PROFILE or predictions.get("schema")!=PROFILE
        or predictions.get("policy_sha256")!=sha(regular(weights_path))
        or predictions.get("no_gold_evaluation_targets_read") is not True
        or predictions.get("model_generated_answers")!=0
        or policy.get("train_question_labels_used") is not False
        or policy.get("evaluation_documents_seen_during_gradient_updates") is not False
        or len(predictions.get("predictions",[]))!=64):
        raise ValueError("pre-target trained/head original prediction record changed")
    original_cases={c["question_id"]:c for c in population["splits"]["evaluation"]}
    results={}
    for row in predictions["predictions"]:
        qid,arm=row["question_id"],row["arm"]
        key=(qid,arm)
        if (qid not in original_cases or arm not in ARMS or key in results
            or row["family_proxy_digest"]!=original_cases[qid]["family_proxy_digest"]
            or row["source_census_sha256"]!=original_cases[qid]["source_census_sha256"]
            or row["scope"]!=original_cases[qid]["scope"]
            or len(row["selected"])!=8 or len(set(row["selected"]))!=8
            or not set(row["selected"]).issubset(original_cases[qid]["source_ids"])
            or row["selected_source_bytes"] != sum(len(docs[k]["content"].encode()) for k in row["selected"])
            or row["heldout_gold_opened"] is not False
            or row["generation_calls"]!=0):
            raise ValueError("unregistered or tampered source-only original retrieval arm")
        if arm.startswith("frozen_"):
            expected_arm="lexical_k8" if arm=="frozen_lexical_k8" else "recent_k8"
            if row["selected"] !=catalog[qid,expected_arm]["selected"]:
                raise ValueError("original frozen strong baseline or source order rewritten")
        results[key]=row
    if set(results)!={(qid,arm) for qid in original_cases for arm in ARMS}:
        raise ValueError("incomplete 16-question four-arm eval census")
    # First target read occurs *only after* all original immutable files are checked.
    gold=load_evaluation(gold_zip)
    if set(gold)!=set(original_cases):
        raise ValueError("original publisher evaluation target partition drift")
    report_old=original_zip(original_report_zip,OLD_SHA,("SHA256SUMS","report.json"))
    prior=strict(report_old["report.json"])
    if prior.get("schema")!="hepta.memorycell.locomo-frozen-retrieval-evaluation.v1":
        raise ValueError("original six-arm baseline report drift")
    arms={arm:dict(planned=16,eligible=0,covered=0,total_source_bytes=0,per_family=defaultdict(lambda:dict(eligible=0,covered=0))) for arm in ARMS}
    decisions={}
    for qid,case in original_cases.items():
        target=gold[qid]
        support=target.get("support")
        unresolved=target.get("unresolved_support")
        if (not isinstance(support,list) or not isinstance(unresolved,list)
            or type(target.get("unanswerable")) is not bool
            or len(set(support))!=len(support)
            or any(type(x) is not str for x in support+unresolved)):
            raise ValueError("invalid published evidence source annotations")
        eligible=bool(support) and not target["unanswerable"] and not unresolved and set(support).issubset(case["source_ids"])
        decisions[qid]={}
        for arm in ARMS:
            row=results[qid,arm]
            stat=arms[arm]
            fam=stat["per_family"][case["family_proxy_digest"]]
            stat["total_source_bytes"]+=row["selected_source_bytes"]
            covered=eligible and set(support).issubset(row["selected"])
            if eligible:
                stat["eligible"]+=1;fam["eligible"]+=1
                stat["covered"]+=int(covered);fam["covered"]+=int(covered)
            decisions[qid][arm]=dict(eligible=eligible,covered=bool(covered))
    baseline=arms["frozen_lexical_k8"]
    previous=prior["evaluation"]["lexical_k8"]
    if (baseline["eligible"]!=previous["eligible"]
        or baseline["covered"]!=previous["full_annotated_support_covered"]
        or baseline["total_source_bytes"]!=previous["selected_source_bytes"]):
        raise ValueError("independent frozen lexical original score failed reproduction")
    final={}
    for arm,stat in arms.items():
        wins=losses=ties=0
        for qid in original_cases:
            if decisions[qid][arm]["eligible"]:
                cur=decisions[qid][arm]["covered"]
                ref=decisions[qid]["frozen_lexical_k8"]["covered"]
                wins+=cur and not ref
                losses+=ref and not cur
                ties+=cur==ref
        final[arm]=dict(planned=16,eligible=stat["eligible"],covered=stat["covered"],
            selected_source_bytes=stat["total_source_bytes"],paired_wins_over_lexical=wins,
            paired_losses_to_lexical=losses,paired_ties=ties,
            by_published_family={f:dict(v) for f,v in stat["per_family"].items()})
    return dict(schema="hepta.memorycell.locomo-real-published-family-tiny-head-postseal-replay.v1",
                evaluation_family_proxies=2,evaluation_question_count=16,
                original_public_source_sha256=PUB_SHA,original_retrieval_sha256=DEC_SHA,
                original_gold_zip_sha256=GOLD_SHA,original_frozen_baseline_report_sha256=OLD_SHA,
                original_pre_gold_seal_sha256=PRESEAL_SHA,
                pre_gold_predictions_sha256=sha(regular(predictions_path)),
                real_sgd_updates_before_gold=384,matched_original_lexical_score_reproduced=True,
                scored_original_published_annotated_support_only=True,
                actual_reader_model_calls=0,actual_reader_task_success_measured=False,
                independently_human_reviewed_sufficiency=False,
                source_family_proxies_not_future_or_independently_authenticated=True,
                parametric_memory_gain_proven=False,production_accepted=False,
                scores=final)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("public","decisions","policy","predictions","preseal","gold","frozen_report","output"):
        p.add_argument(name,type=Path)
    a=p.parse_args();result=score_sealed(a.public,a.decisions,a.policy,a.predictions,a.preseal,a.gold,a.frozen_report)
    with a.output.open("x",encoding="utf-8") as f:
        json.dump(result,f,indent=2,sort_keys=True,allow_nan=False);f.write("\n")
    print(json.dumps({k:(v["covered"],v["eligible"]) for k,v in result["scores"].items()},sort_keys=True))


if __name__=="__main__":
    main()
