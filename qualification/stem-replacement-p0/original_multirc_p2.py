"""Source-owner bridge: original human MultiRC P0 -> P2 label-blind source panel.

This bridge is a *source/label-custody stage*, NOT a model worker. It consumes
previously produced original public MultiRC source-owner outputs at the exact
pinned source format. No internet, pickle, tokenizer, model weights, effect,
trainable parameter or heldout human label is consumed or minted.
The P0 owner must still independently recheck original Parquet bytes and labels.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import gate
import matched_head
import physical_feature_bank as bank

SCHEMA = "hepta.p0.multirc-human-semantic.v1"
DATA_REPO = "aps/super_glue"
DATA_REVISION = "4e14482c58d790d467ecfb29b6790e1917bf8756"
SOURCE_SELECTION = "sha256-passage-first-two-questions-all-first-four-answer-ids:blind:v1"
COUNTS = {"train": 12, "calibration": 4, "test": 8}
ORIGINAL_ONLY = "original"
NO_EVIDENCE = "no_evidence"
RESULT_SCHEMA = "hepta.stem.equal-size.multirc-original-source-adapter.v1"


def check(v, reason):
    gate.require(v, reason)


def _read_meta(fit, blind):
    check(type(fit) is dict and type(blind) is dict and
          set(fit) == set(blind) == {"metadata", "cases"} and
          type(fit["metadata"]) is dict and fit["metadata"] == blind["metadata"],
          "missing authentic original MultiRC source pair")
    meta=fit["metadata"]
    check(set(meta) == {"schema", "repo", "revision", "train_sha256",
                        "validation_sha256", "selection_rule", "source_passages_by_split",
                        "training_license_independently_approved", "contamination_ruled_out",
                        "temporal_future_windows_verified", "authority",
                        "production_promotion_permitted", "panel_id"} and
          meta["schema"] == SCHEMA and meta["repo"] == DATA_REPO and
          meta["revision"] == DATA_REVISION and
          meta["selection_rule"] == SOURCE_SELECTION and
          meta["source_passages_by_split"] == COUNTS and
          gate.sha(meta["train_sha256"]) and gate.sha(meta["validation_sha256"]) and
          meta["training_license_independently_approved"] is False and
          meta["contamination_ruled_out"] is False and
          meta["temporal_future_windows_verified"] is False and
          meta["authority"] == "DENY_ALL" and
          meta["production_promotion_permitted"] is False,
          "unreviewed original human source identity or authority")
    expected=gate.digest({"base":{k:v for k,v in meta.items() if k!="panel_id"},
                          "fit":fit["cases"],"blind":blind["cases"]})
    check(meta["panel_id"] == expected,"original source material/panel content mutated")
    return meta


def _original_groups(fit,blind):
    rows=[]
    groups=defaultdict(dict)
    seen=set()
    seen_source_by_split={s:set() for s in COUNTS}
    for document in (fit,blind):
        check(type(document["cases"]) is list and document["cases"],
              "missing original source case rows")
        isblind=document is blind
        for r in document["cases"]:
            allowed={"case_id","source_id","source_group","split","question_id",
                     "answer_id","condition","candidate_text","original_question_text",
                     "joint_input","view_sha256"}
            check(type(r) is dict and set(r)==(allowed if isblind else allowed|{"label"}),
                  "unexpected original MultiRC source columns")
            case=r["case_id"]
            check(type(case) is str and len(case)==32 and case not in seen and
                  r["split"] in COUNTS and (r["split"]=="test")==isblind and
                  r["condition"] in (ORIGINAL_ONLY,NO_EVIDENCE),
                  "wrong original group/label boundary or duplicate identity")
            seen.add(case)
            for key in ("source_id","source_group"):
                check(gate.sha(r[key]),"invalid source group/hash")
            check(type(r["question_id"]) is str and len(r["question_id"]) == 32 and
                  type(r["answer_id"]) is str and len(r["answer_id"]) == 32 and
                  type(r["candidate_text"]) is str and r["candidate_text"] and
                  type(r["original_question_text"]) is str and r["original_question_text"],
                  "invalid original question/answer identity")
            view=r["joint_input"]
            check(type(view) is dict and set(view)=={"state","question","options"} and
                  view["options"] == bank.OPTIONS and
                  gate.digest(view) == r["view_sha256"],
                  "changed exact original evidence/question/ordered options")
            prompt=("Is the proposed answer supported by the original passage? " +
                    "Question: " + json.dumps(r["original_question_text"],ensure_ascii=False) +
                    " Candidate answer: " + json.dumps(r["candidate_text"],ensure_ascii=False))
            check(view["question"] == prompt,"source question/answer prompt reinterpreted")
            key=(r["split"],r["source_group"],r["question_id"],r["answer_id"])
            check(r["condition"] not in groups[key],"repeated source intervention")
            groups[key][r["condition"]]=r
            if r["condition"] == ORIGINAL_ONLY:
                check(len(view["state"])>=100 and
                      r["source_id"] == hashlib.sha256(view["state"].encode()).hexdigest(),
                      "original source or passage length changed")
                seen_source_by_split[r["split"]].add(r["source_group"])
                if not isblind:
                    check(type(r["label"]) is int and r["label"] in (0,1),
                          "original source human label missing")
                rows.append(r)
            else:
                check(view["state"]=="(no passage evidence available)" and
                      (isblind or r["label"] is None),
                      "generated no-evidence has an invented human label")
    check({s:len(x) for s,x in seen_source_by_split.items()}==COUNTS,
          "missing or duplicate original source passages")
    check(all(not seen_source_by_split[a].intersection(seen_source_by_split[b])
              for a in COUNTS for b in COUNTS if a!=b),
          "source passage leaked across original splits")
    for k,v in groups.items():
        check(set(v)=={ORIGINAL_ONLY,NO_EVIDENCE},"missing exactly paired original intervention")
        a,b=v[ORIGINAL_ONLY],v[NO_EVIDENCE]
        check(a["joint_input"]["question"]==b["joint_input"]["question"] and
              a["source_id"]==b["source_id"] and
              a["source_group"]==b["source_group"] and
              a["candidate_text"]==b["candidate_text"] and
              a["original_question_text"]==b["original_question_text"],
              "generated intervention changed original human task identity")
    return rows


def build_source_owner(fit,blind):
    """Outputs only selected ORIGINAL views and their separately scoped FIT labels."""
    meta=_read_meta(fit,blind)
    original=_original_groups(fit,blind)
    bysplit={s:defaultdict(list) for s in COUNTS}
    for r in original:
        bysplit[r["split"]][r["source_group"]].append(r)
    chosen=[]
    for original_split in COUNTS:
        groups=bysplit[original_split]
        check(len(groups)==COUNTS[original_split],"incorrect source-group census")
        for grp in sorted(groups):
            # **Only IDs, not original binary labels, choose the 4 case IDs.**
            cases=sorted(groups[grp],key=lambda r:(r["question_id"],r["answer_id"],r["case_id"]))
            check(len(cases)>=4,"incomplete original source alternatives")
            chosen.extend(cases[:4])
    check(len(chosen)==4*sum(COUNTS.values())==bank.MAX_CASES_PHYSICAL,
          "not the frozen per-source four-case physical pilot")
    source_sha=gate.digest({"repo":DATA_REPO,"revision":DATA_REVISION,
                            "train_sha256":meta["train_sha256"],
                            "validation_sha256":meta["validation_sha256"],
                            "p0_panel_id":meta["panel_id"]})
    rows=[];views=[];fit_labels=[]
    translate={"train":"fit","calibration":"cal","test":"test"}
    for r in chosen:
        original_view=r["joint_input"]
        split=translate[r["split"]]
        case={"case_id":r["case_id"],"group_id":r["source_group"],
              "family_id":"multirc-original:"+r["split"],"split":split,
              "source_sha256":hashlib.sha256(original_view["state"].encode()).hexdigest(),
              "input_sha256":gate.digest(original_view),
              # This lexical **source-only** count is not any model tokenizer count.
              "token_count":min(512,max(1,sum(len(x.split()) for x in
                                    (original_view["state"],original_view["question"]))+2))}
        rows.append(case)
        views.append({"case_id":r["case_id"],"source_sha256":case["source_sha256"],
                      "input_sha256":case["input_sha256"],**original_view})
        if split=="fit":
            fit_labels.append({"case_id":r["case_id"],"target":r["label"]})
    panel={"schema":gate.SCHEMA,"source_revision":DATA_REVISION,
           "source_material_sha256":source_sha,"purpose":"binary-support-research-only",
           "budget":{"max_tokens":512,"head_steps":40,
                     "head_trainable_params":matched_head.PARAMS,"head_seed":41,
                     "head_optimizer":"sgd-lr-0.1","precision":"float32"},
           "cases":rows,"authority":"DENY_ALL","production_promotion_permitted":False,
           "future_window_verified":False}
    psha=gate.digest(panel)
    views_doc={"schema":bank.SCHEMA,"panel_sha256":psha,
               "source_revision":DATA_REVISION,"source_material_sha256":source_sha,
               "cases":views,"authority":"DENY_ALL","production_authorized":False}
    fit_doc={"schema":matched_head.FIT_SCHEMA,"panel_sha256":psha,
             "source_label_owner_sha256":gate.digest({
                 "dataset":DATA_REPO,"dataset_revision":DATA_REVISION,
                 "original_source_panel_id":meta["panel_id"],
                 "fit_original_cases":[r["case_id"] for r in chosen if r["split"]=="train"]}),
             "targets":fit_labels,"authority":"DENY_ALL","production_authorized":False}
    gate.validate_panel(panel)
    bank.manifest_views(panel,views_doc)
    matched_head.validate_fit(panel,fit_doc)
    return panel,views_doc,fit_doc


def main(argv=None):
    p=argparse.ArgumentParser(description="Original human MultiRC source owner only; no models/gold leak")
    p.add_argument('--fit',type=Path,required=True)
    p.add_argument('--blind',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(argv)
    fit=gate.strict_load(a.fit);blind=gate.strict_load(a.blind)
    panel,views,labels=build_source_owner(fit,blind)
    check(a.out.parent.is_dir() and not a.out.is_symlink() and not a.out.exists(),
          "source owner outputs must be new private directory")
    a.out.mkdir(mode=0o700)
    # Separate original-source owner output from model worker access.
    # Never feed fit_labels to a frozen-feature producer subprocess.
    bank._save_once(a.out/'panel.json',panel)
    bank._save_once(a.out/'original_views.json',views)
    bank._save_once(a.out/'fit_owner_only.json',labels)
    print('96 selected original human MultiRC cases / 24 groups; 0 held truth in model views; HOLD_NO_GO')

if __name__=='__main__':main()
