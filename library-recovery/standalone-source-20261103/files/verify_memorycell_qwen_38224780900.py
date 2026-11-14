#!/usr/bin/env python3
"""External read-only recheck of an ACTUAL Qwen 40+72 GitHub Actions result.

Inputs are immutable PUBLIC original GitHub Actions ZIPs. This checks exact
bytes, unmodified original generation rows, source/citation membership, narrow
task correctness, bounded program outcomes, paired contrasts and stability.
It neither runs a language model nor judges independent semantic entailment.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

GENERATOR = "6304b451268c73f3d1a605985226b102df841bbf"
PINS = {
    "original": "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b",
    "reader": "7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8",
    "replay": "2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071",
}
MANIFEST_COUNTS = {"original": 35, "reader": 43, "replay": 8}
ARMS = ("selected_k", "hybrid_k4", "hybrid_k6", "hybrid_k4_reversed", "single_hop", "entity_time", "organized", "program_support", "empty")
KS = (1, 2, 3, 4, 6)
IDENT = re.compile(r"\s*((?:site|mode)_[0-9a-f]{8})(?:\s*\[E[1-9][0-9]*\])*\s*\.?\s*")
CITATIONS = re.compile(r"\[(E[1-9][0-9]*)\]")
SHA = re.compile(r"[0-9a-f]{64}")
SCORE_ONLY = {"parsed_identifier", "strict_task_success", "required_sources_covered", "procedure_verification"}


def strict_json(raw):
    def unique(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise ValueError("duplicate JSON key " + k)
            d[k] = v
        return d
    def nonfinite(value):
        raise ValueError("nonfinite JSON constant")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def native_digest(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


def read_pinned_zip(path, kind):
    raw = Path(path).read_bytes()
    if sha(raw) != PINS[kind]:
        raise ValueError("externally pinned ZIP differs: " + kind)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("oversized ZIP")
    with zipfile.ZipFile(path) as z:
        info = z.infolist()
        if len(info) != MANIFEST_COUNTS[kind] + 1 or sum(x.file_size for x in info) > 64 * 1024 * 1024:
            raise ValueError("unexpected complete file census")
        files = {}
        for item in info:
            n = item.filename
            parsed = PurePosixPath(n)
            if n in files or parsed.is_absolute() or ".." in parsed.parts or "\\" in n or item.is_dir() or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("unsafe or duplicate ZIP member")
            files[n] = z.read(item)
    lines = files["SHA256SUMS"].decode().splitlines()
    actual = {}
    for line in lines:
        m = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
        if not m or m.group(2) in actual:
            raise ValueError("invalid checksum declaration")
        actual[m.group(2)] = m.group(1)
    if set(actual) != set(files) - {"SHA256SUMS"}:
        raise ValueError("unlisted or missing inner source")
    for name, digest in actual.items():
        if sha(files[name]) != digest:
            raise ValueError("modified inner source " + name)
    return files


def verify_procedure(truth, answer_id, scored):
    recipe = truth["procedure"]
    if truth["kind"] != "procedure":
        if "procedure_verification" in scored:
            raise ValueError("fake procedure verification")
        return answer_id == truth["expected"]
    request = {"operation": "execute", "recipe": recipe, "supplied": answer_id or "invalid_response"}
    mode = recipe["modes"].get(request["supplied"])
    result = sorted(recipe["values"]) if mode == "sort" else list(reversed(recipe["values"])) if mode == "reverse" else None
    worked = result is not None and result == recipe["target"]
    saved = scored["procedure_verification"]
    if saved["request"] != request or saved["exit_code"] != (0 if worked else 2) or strict_json(saved["stdout"]) != {"succeeded": worked, "supplied": request["supplied"], "actual_output": result} or saved["stderr"]:
        raise ValueError("program execution receipt differs from independent replay")
    return worked


def validate_answer_row(raw, scored, case, truth, original_docs, reader_identity, selection=None):
    if raw["status"] != "succeeded" or raw["question_id"] != case["query"]["identity"]:
        raise ValueError("missing original success or query mismatch")
    if raw != {k: v for k, v in scored.items() if k not in SCORE_ONLY}:
        raise ValueError("scoring rewrote an original model answer")
    selected = raw["selected"]
    if not isinstance(selected, list) or len(selected) != len(set(selected)) or any(n not in original_docs for n in selected):
        raise ValueError("unregistered or duplicate original selected source")
    if selection is not None and selected != selection:
        raise ValueError("selected sources differ from frozen non-answer policy")
    receipt = raw["receipt"]
    if receipt["reader_identity"] != reader_identity or receipt["trainable_parameters"] != 0 or receipt["answer_postprocessed"] is not False or receipt["production_accepted"] is not False or receipt["token_limit"] != 2048 or receipt["input_tokens"] > 2048:
        raise ValueError("different or modified reader")
    for field in ("input_ids_digest", "generated_ids_digest"):
        if not SHA.fullmatch(receipt[field]):
            raise ValueError("invalid original token identity")
    delivered = receipt["delivered_evidence"]
    if len(delivered) != len(selected):
        raise ValueError("delivered source count differs")
    original_labels = {}
    for i, (source_id, source) in enumerate(zip(selected, delivered, strict=True), 1):
        original = original_docs[source_id]
        label = f"E{i}"
        if (source["original_id"] != source_id or source["label"] != label or source["scope"] != case["query"]["scope"] or original["scope"] != case["query"]["scope"] or source["root"] != original["root"] or source["excerpt"] != original["content"] or source["source_digest"] != native_digest(original["content"]) or source["source_start"] != 0 or source["source_end"] != len(original["content"].encode())):
            raise ValueError("reader received unpinned or modified source bytes")
        original_labels[label] = source_id
    request = raw["citation_audit"]["request"]
    if (request["query_id"] != raw["question_id"] or request["question"] != case["query"]["content"] or request["question_time"] != case["query"]["observed_at"] or request["answer"] != raw["answer"] or request["prompt_digest"] != receipt["input_ids_digest"] or raw["citation_audit"]["judgement"] is not None):
        raise ValueError("original model answer or unsigned citation payload modified")
    if [s["label"] for s in request["sources"]] != list(original_labels) or [s["excerpt"] for s in request["sources"]] != [d["excerpt"] for d in delivered]:
        raise ValueError("quoted citation sources detached from delivered bytes")
    cited = CITATIONS.findall(raw["answer"])
    if not set(cited) <= set(original_labels):
        raise ValueError("answer cites undelivered original source")
    match = IDENT.fullmatch(raw["answer"])
    ansid = match[1] if match else None
    correct = verify_procedure(truth, ansid, scored)
    if scored["parsed_identifier"] != ansid or scored["strict_task_success"] is not correct or scored["required_sources_covered"] is not set(truth["support"]).issubset(selected):
        raise ValueError("post-journal strict benchmark scoring differs")
    return {"correct":correct,"full_citation":correct and set(truth["support"]).issubset({original_labels[k] for k in cited}),"input_tokens":receipt["input_tokens"],"output_tokens":receipt["generated_tokens"],"seconds":receipt["seconds"],"prompt":receipt["input_ids_digest"],"generated":receipt["generated_ids_digest"],"answer":raw["answer"],"selected":selected,"question":raw["question_id"],"arm":raw["arm"]}


def audit(original_path, reader_path, replay_path):
    original = read_pinned_zip(original_path, "original")
    model = read_pinned_zip(reader_path, "reader")
    replay = read_pinned_zip(replay_path, "replay")
    if sha(original["plan/plan.json"]) != "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897":
        raise ValueError("historical plan changed")
    if model["tested-commit.txt"].decode().strip() != GENERATOR or replay["auditor-source-commit.txt"].decode().strip() != GENERATOR:
        raise ValueError("model generator and independent replay source mismatch")
    plan = strict_json(original["plan/plan.json"])
    collection = strict_json(original["observations/collection.json"])
    labels = strict_json(original["observations/labels.json"])
    label_by_id = {r["id"]:r for r in labels}
    if len(label_by_id) != 16 or len(labels) != 16:
        raise ValueError("wrong question count")
    view = strict_json(original["plan/source-view.json"])
    docs = {d["identity"]:d for d in view}
    if len(view) != 108 or len(docs) != 108:
        raise ValueError("wrong exact source document census")
    prep = strict_json(model["prep/calibration-plan.json"])
    cal_sources = strict_json(model["prep/calibration-sources.json"])
    cal_docs = {d["identity"]:d for d in cal_sources}
    cal_qids = [c["query"]["identity"] for c in prep["cases"]]
    eval_qids = [c["query"]["identity"] for c in plan["cases"]]
    if len(cal_qids) != 8 or len(set(cal_qids)) != 8 or len(eval_qids) != 8 or len(set(eval_qids)) != 8 or set(cal_qids) & set(eval_qids):
        raise ValueError("missing independent calibration/test partitions")
    if set(d["scope"] for d in cal_sources) != set(cal_qids) or set(prep["frozen_indices"]) != set(cal_qids):
        raise ValueError("test source or index hash leaked into calibrator")
    frozen = strict_json(model["calibration/frozen-policy.json"])
    identity = strict_json(model["inventory.json"])["inventory_digest"]
    if frozen["selected_k"] not in KS or frozen["source_commit"] != GENERATOR or frozen["reader_identity"] != identity:
        raise ValueError("frozen policy or model identity mismatch")
    reader_results = {}
    for phase, cases, docs_for_phase, arms, qids in (("calibration",prep["cases"],cal_docs,tuple(f"k{k}" for k in KS),cal_qids),("evaluation",plan["cases"],docs,ARMS,eval_qids)):
        data = model[f"{phase}/raw-answers.jsonl"]
        if not data.endswith(b"\n"):
            raise ValueError("unflushed model answer journal")
        raw = [strict_json(line) for line in data.splitlines()]
        scored = strict_json(model[f"{phase}/scored-answers.json"])
        if len(raw) != len(scored) or Counter((x["question_id"],x["arm"]) for x in raw) != Counter((qid,arm) for qid in qids for arm in arms):
            raise ValueError("incomplete or duplicated original generation census")
        cases_by_id={c["query"]["identity"]:c for c in cases}
        result=[]
        for original_row, scored_row in zip(raw,scored,strict=True):
            case=cases_by_id[original_row["question_id"]]
            control=None
            if phase=="calibration":control=case["candidate_ids"][:int(original_row["arm"][1:])]
            else:
                if original_row["arm"] in ("selected_k","hybrid_k4","hybrid_k6"):
                    size={"selected_k":frozen["selected_k"],"hybrid_k4":4,"hybrid_k6":6}[original_row["arm"]]
                    control=case["candidate_ids"][:size]
                elif original_row["arm"]=="hybrid_k4_reversed":control=list(reversed(case["candidate_ids"][:4]))
                elif original_row["arm"] in case["controls"]:control=case["controls"][original_row["arm"]]["selected"]
                elif original_row["arm"]=="single_hop":
                    # Single-hop source selection is persisted before test labels.
                    prepared=strict_json(model["evaluation/single-hop-control.json"])
                    lookup={row["question_id"]:row["first_hop"] for row in prepared["test_cases"]}
                    control=lookup.get(original_row["question_id"])
            result.append(validate_answer_row(original_row,scored_row,case,label_by_id[original_row["question_id"]],docs_for_phase,identity,selection=control))
        reader_results[phase]=result
        stated=strict_json(model[f"{phase}/report.json"])
        if sha(data)!=stated["raw_answers_sha256"]:
            raise ValueError("reported original answer hash differs")
        if phase=="evaluation":
            by_arm={}
            for arm in ARMS:
                rec=[r for r in result if r["arm"]==arm]
                by_arm[arm]={"correct":sum(x["correct"] for x in rec),"correct_with_all_declared_sources_cited":sum(x["full_citation"] for x in rec),"prompt_tokens":sum(x["input_tokens"] for x in rec),"generated_tokens":sum(x["output_tokens"] for x in rec),"model_seconds":round(sum(x["seconds"] for x in rec),3)}
                stat=stated["success_by_arm"][arm]
                if stat["strict_success"]!=by_arm[arm]["correct"] or stat["input_tokens"]!=by_arm[arm]["prompt_tokens"] or stat["output_tokens"]!=by_arm[arm]["generated_tokens"] or not math.isclose(stat["inference_seconds"],sum(x["seconds"] for x in rec),abs_tol=1e-6):
                    raise ValueError("evaluation report not derivable from original receipts")
            reader_results["by_arm"]=by_arm
    calib=reader_results["calibration"]
    cal_stats={f"k{k}":{"correct":sum(x["correct"] for x in calib if x["arm"]==f"k{k}"),"tokens":sum(x["input_tokens"] for x in calib if x["arm"]==f"k{k}")} for k in KS}
    best=max(KS,key=lambda k:(cal_stats[f"k{k}"]["correct"],-cal_stats[f"k{k}"]["tokens"],-k))
    if best!=frozen["selected_k"]:
        raise ValueError("selected frozen k not obtained from genuine calibration")
    loo=Counter()
    for omitted in cal_qids:
        reduced=[r for r in calib if r["question"]!=omitted]
        k=max(KS,key=lambda k:(sum(x["correct"] for x in reduced if x["arm"]==f"k{k}"),-sum(x["input_tokens"] for x in reduced if x["arm"]==f"k{k}"),-k))
        loo[k]+=1
    replay_doc=strict_json(replay["receipt.json"])
    if replay_doc["generating_commit"]!=GENERATOR or replay_doc["calibration"]["attempts"]!=40 or replay_doc["evaluation"]["attempts"]!=72 or replay_doc["production_accepted"] is not False:
        raise ValueError("independent replay does not match actual model run")
    return {"schema":"memorycell.external.recheck.actual-qwen-40plus72.v1","model_source_commit":GENERATOR,"run_id":38224780900,"pin_sha256":PINS,"verified_inner_archive_files":MANIFEST_COUNTS,"model_identity":identity,"original_answer_rows":{"calibration":len(calib),"evaluation":len(reader_results["evaluation"])},"calibration":{"selected_k":best,"by_k":cal_stats,"leave_one_out_choices":{str(k):loo[k] for k in KS},"loo_stable":len(loo)==1},"evaluation":{"by_arm":reader_results["by_arm"]},"independent_replay":{"matching_source":True,"all_original_answers":True,"formal_semantic_judgment":False},"independent_new_source_families":0,"learned_parametric_superiority_proven":False,"production_accepted":False}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--original",type=Path,default=Path("/mnt/data/event-inputs-20261010.zip"))
    parser.add_argument("--reader",type=Path,default=Path("/mnt/data/strong-rag-qwen-38224780900.zip"))
    parser.add_argument("--replay",type=Path,default=Path("/mnt/data/strong-rag-independent-replay-38224780900.zip"))
    parser.add_argument("--output",type=Path,default=Path("/mnt/data/memorycell_qwen_40_72_external_recheck.json"))
    args=parser.parse_args()
    result=audit(args.original,args.reader,args.replay)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"source":result["model_source_commit"],"calibration":result["calibration"],"evaluation":result["evaluation"]["by_arm"]},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
