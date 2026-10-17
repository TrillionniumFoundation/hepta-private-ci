"""Frozen Smol135 Reader prompt-format diagnosis, on previously exposed LoCoMo roots.

Research only: actual original-weight inference, not prospective family validation,
human evidence sufficiency, parameter-memory training, or production admission.
All questions and evidence come from the *already sealed*, SHA-pinned previous
source preparation. No target answers are loaded until after durable completion.
"""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import time

from locomo_reader_four_regimes import DATA_SHA, MODEL_ZIP_SHA, sha, digest, source_file, metric, write

SCHEMA = "hepta.memory.locomo-format-original-smol135.v1"
GENERATOR = "hepta.locomo-preexposed-format-diagnostic.v1"
SOURCE_PIN = "fa7d9e676f9aca8f7c524e6f592cabb88a22c490a8c441db4bd6a8e05fbc6033"
PREREGISTRATION_PIN = None  # Bound at execution to source cut and local source code.
BASELINE_SYSTEM = (
    "Answer briefly using only supplied dialogue excerpts. Cite [E1] etc when possible. "
    "If insufficient evidence, say I do not have enough evidence."
)
FORMATS = ("original_json", "linear_evidence", "question_first")
EVIDENCE_ARMS = ("empty", "annotated_witness")
MAX_INPUT, MAX_OUTPUT = 1200, 24
MARKER = re.compile(r"\[E([1-9][0-9]*)\]")
WORD = re.compile(r"[a-z0-9]+")


def frozen_requests(sealed):
    if not isinstance(sealed, dict) or sealed.get("schema") != "hepta.memory.locomo-fixed-reader-private-input.v1":
        raise ValueError("exact earlier sealed source schema required")
    source = sealed.get("requests")
    if not isinstance(source, list) or len(source) != 32:
        raise ValueError("original 8-by-4 input census required")
    grouped = {}
    for row in source:
        if not isinstance(row, dict) or set(row) != {
            "qid", "root_sha256", "question", "arm", "sources", "source_ids"
        }:
            raise ValueError("original raw answer or source envelope unexpected")
        key = (row["qid"], row["arm"])
        if key in grouped:
            raise ValueError("duplicate original question/arm")
        grouped[key] = row
    question_ids = tuple(dict.fromkeys(row["qid"] for row in source))
    if len(question_ids) != 8 or any((q, a) not in grouped for q in question_ids for a in (
        "empty", "bm25_top3", "annotated_witness", "witness_lesion"
    )):
        raise ValueError("old source family census changed")
    result = []
    for qid in question_ids:
        for arm in EVIDENCE_ARMS:
            r = grouped[qid, arm]
            if not isinstance(r["question"], str) or len(r["question"]) > 280:
                raise ValueError("bounded query required")
            if arm == "empty" and (r["sources"] or r["source_ids"]):
                raise ValueError("hidden evidence in empty control")
            if len(r["sources"]) != len(r["source_ids"]) or len(r["sources"]) > 3:
                raise ValueError("invalid delivered source census")
            for item, source_id in zip(r["sources"], r["source_ids"], strict=True):
                if (not isinstance(item, dict) or set(item) != {"id", "speaker", "text"}
                    or item["id"] != source_id or not isinstance(item["text"], str)
                    or len(item["text"]) > 600):
                    raise ValueError("delivered original source mismatch")
            result.append(r)
    return result


def messages(request, style):
    if style not in FORMATS or request["arm"] not in EVIDENCE_ARMS:
        raise ValueError("undeclared evidence/prompt condition")
    original = request["sources"]
    if style == "original_json":
        # Byte-identical to the inherited 32-request real-model experiment.
        return [dict(role="system", content=BASELINE_SYSTEM),
                dict(role="user", content=json.dumps(dict(
                    question=request["question"],
                    evidence=[dict(label=f"E{i}", speaker=d["speaker"], text=d["text"])
                              for i, d in enumerate(original, 1)]), ensure_ascii=False))]
    excerpts = "\n".join(f"[E{i}] {d['speaker']}: {d['text']}"
                         for i, d in enumerate(original, 1)) or "(none)"
    if style == "linear_evidence":
        return [dict(role="system", content=(
            "Answer the question based only on evidence lines. Reply with one short answer, "
            "then a valid [E1] source marker if supported; otherwise reply 'I do not have enough evidence.'"
        )), dict(role="user", content=(
            f"Question: {request['question']}\nEvidence lines:\n{excerpts}\nAnswer:"
        ))]
    return [dict(role="system", content=(
        "You are answering a memory question. Do not repeat the question, format JSON, "
        "or quote the entire evidence. Respond with a short factual answer and an "
        "[E1] citation when justified. If unsupported, say 'I do not have enough evidence.'"
    )), dict(role="user", content=(
        f"What is the short answer to: {request['question']}\n"
        f"Available dialogue:\n{excerpts}\nShort answer only:"
    ))]


def prepare(prior_dir, destination):
    prior_dir, destination = Path(prior_dir), Path(destination)
    plan_bytes = (prior_dir / "preregistered.json").read_bytes()
    prior = json.loads(plan_bytes)
    source_bytes = (prior_dir / "sealed-inputs.json").read_bytes()
    if sha(source_bytes) != SOURCE_PIN or sha(source_bytes) != prior["sealed_inputs_sha256"]:
        raise ValueError("original sealed pre-scoring source bytes changed")
    frozen = frozen_requests(json.loads(source_bytes))
    destination.mkdir(parents=True, exist_ok=False)
    trials = [dict(request=q, format=style) for q in frozen for style in FORMATS]
    write(destination / "sealed-prompts.json", dict(schema=GENERATOR, trials=trials))
    write(destination / "preregistered.json", dict(
        schema=SCHEMA, source_original_sha256=SOURCE_PIN,
        original_source_json_sha256=DATA_SHA, original_model_zip_sha256=MODEL_ZIP_SHA,
        original_readout_profile="hepta.offline-original-smol135-fp32.v1",
        code_sha256=sha(Path(__file__).read_bytes()),
        sealed_prompt_sha256=sha((destination / "sealed-prompts.json").read_bytes()),
        prompt_formats=list(FORMATS), evidence_conditions=list(EVIDENCE_ARMS),
        model_calls=48, distinct_existing_roots=8,
        input_tokens_limit=MAX_INPUT, output_tokens_limit=MAX_OUTPUT,
        scoring_labels_accessed_at_registration=False,
        prior_benchmark_public=True, publisher_witness_independently_sufficient=False,
        learning_updates=0, independently_observed_future_windows=0,
        stronger_reference_reader_used=False, production_accepted=False,
    ))
    return destination


def load_registered(directory):
    directory=Path(directory)
    pre=json.loads((directory / "preregistered.json").read_bytes())
    sealed=(directory / "sealed-prompts.json").read_bytes()
    if (pre.get("schema") != SCHEMA or pre.get("source_original_sha256") != SOURCE_PIN
        or pre.get("sealed_prompt_sha256") != sha(sealed)
        or pre.get("code_sha256") != sha(Path(__file__).read_bytes())
        or pre.get("prompt_formats") != list(FORMATS)
        or pre.get("evidence_conditions") != list(EVIDENCE_ARMS)
        or pre.get("model_calls") != 48 or pre.get("learning_updates") != 0):
        raise ValueError("registered source, code or evaluation conditions changed")
    result=json.loads(sealed)
    if result.get("schema") != GENERATOR or len(result.get("trials", [])) != 48:
        raise ValueError("complete model-free sealed trial census required")
    expected={(v["request"]["qid"],v["request"]["arm"],v["format"])
              for v in result["trials"]}
    if len(expected)!=48:
        raise ValueError("duplicate 48-arm original model request")
    return pre,result["trials"]


def execute(directory, reader_root):
    from offline_smol_reader import OriginalSmol, PROFILE
    import torch
    torch.set_num_threads(2)
    directory=Path(directory)
    pre, trials=load_registered(directory)
    reader=OriginalSmol(reader_root)
    rows=[]
    with (directory / "raw-answers.jsonl").open("x",encoding="utf8") as output:
        for i, condition in enumerate(trials,1):
            request=condition["request"]
            style=condition["format"]
            packet=messages(request,style)
            row=dict(qid=request["qid"],root_sha256=request["root_sha256"],
                     evidence=request["arm"],format=style,
                     source_ids_digest=digest(request["source_ids"]),
                     model_identity=reader.identity,reader_profile=PROFILE,
                     messages_sha256=digest(packet),
                     candidate_pool_oracle=False)
            start=time.perf_counter()
            try:
                prompt=reader.tokenizer.render(packet)
                ids=reader.tokenizer.encode(prompt)
                if not 1 <= len(ids) <= MAX_INPUT:
                    raise ValueError("registered original model input budget exceeded")
                tokens=reader.generate(ids,MAX_OUTPUT)
                answer=reader.tokenizer.decode(tokens)
                row.update(status="succeeded",answer=answer,
                           output_tokens=len(tokens),input_tokens=len(ids),
                           input_ids_sha256=digest(ids),generated_tokens_sha256=digest(tokens))
            except Exception as error:
                row.update(status="failed",error_type=type(error).__name__,
                           error=str(error)[:500],output_tokens=0,input_tokens=None)
            row["wall_seconds"]=time.perf_counter()-start
            output.write(json.dumps(row,allow_nan=False,ensure_ascii=False)+"\n")
            output.flush()
            os.fsync(output.fileno())
            rows.append(row)
            print(f"{i}/48 {request['qid'][:10]} {request['arm']} {style}: {row['status']}",flush=True)
    reader.verify_frozen()
    print("raw_journal_sha256",sha((directory / "raw-answers.jsonl").read_bytes()))


def audit_original(directory, prior_run):
    """Model-free source/readout consistency; gold labels not read here."""
    directory,prior_run=Path(directory),Path(prior_run)
    pre,trials=load_registered(directory)
    raw=(directory / "raw-answers.jsonl").read_bytes()
    rows=[json.loads(x) for x in raw.splitlines()]
    if len(rows)!=len(trials):
        raise ValueError("incomplete sealed answer census")
    old=[json.loads(x) for x in (prior_run / "raw-answers.jsonl").read_bytes().splitlines()]
    old_by={(r["qid"],r["arm"]):r for r in old}
    matched=0
    for i, (r, condition) in enumerate(zip(rows,trials,strict=True)):
        req=condition["request"]
        for key,val in (("qid",req["qid"]),("root_sha256",req["root_sha256"]),
                        ("format",condition["format"]),("evidence",req["arm"]),
                        ("source_ids_digest",digest(req["source_ids"])),
                        ("messages_sha256",digest(messages(req,condition["format"])))):
            if r.get(key)!=val:
                raise ValueError(f"original request binding changed at {i}: {key}")
        if r.get("candidate_pool_oracle") is not False:
            raise ValueError("posthoc answer-space leak in original model")
        if r.get("status") not in ("succeeded","failed"):
            raise ValueError("unregistered original model outcome")
        if r["status"]=="succeeded":
            if not isinstance(r.get("answer"),str) or not isinstance(r.get("input_tokens"),int) or \
               not 1<=r["input_tokens"]<=MAX_INPUT or not 0<=r.get("output_tokens",-1)<=MAX_OUTPUT:
                raise ValueError("unbounded original generation")
        else:
            if "answer" in r:
                raise ValueError("failed attempt cannot claim generated answer")
        if condition["format"]=="original_json":
            old_row=old_by.get((req["qid"],req["arm"]))
            if old_row is None or old_row.get("status")!="succeeded":
                raise ValueError("missing original model comparator")
            if r.get("generated_tokens_sha256") != old_row["generated_token_digest"]:
                raise ValueError("same original model baseline disagrees across runs")
            matched+=1
    if matched!=16:
        raise ValueError("not all 16 original same-prompt calls matched")
    return dict(schema="hepta.memory.locomo-format-replay.v1",
                original_input_sha256=pre["source_original_sha256"],
                original_generation_sha256=sha(raw),
                original_prompts_reproduced=matched,
                original_model_forward_count=0,
                independently_certified_model_runtime=False,
                production_accepted=False)


def score(dataset, directory, baseline, output):
    # All prior answers have already been fsynced; labels only enter this phase.
    audit=audit_original(directory,baseline)
    pre,trials=load_registered(directory)
    rows=[json.loads(x) for x in (Path(directory)/"raw-answers.jsonl").read_bytes().splitlines()]
    dataset=source_file(dataset,DATA_SHA)
    root_map={sha(row["sample_id"].encode()):row for row in dataset}
    original_plan=json.loads((Path(baseline)/"preregistered.json").read_bytes())
    targets={v["qid"]:str(root_map[v["root_sha256"]]["qa"][v["original_question_index"]]["answer"])
             for v in original_plan["fixed_cases"]}
    stats={(arm,form):Counter() for arm in EVIDENCE_ARMS for form in FORMATS}
    for row, trial in zip(rows,trials,strict=True):
        key=row["evidence"],row["format"]
        counts=stats[key]
        counts["attempts"]+=1
        ok=row["status"]=="succeeded"
        counts["successful_calls"]+=ok
        if not ok:
            continue
        answer=row["answer"]
        true=targets[row["qid"]]
        counts["strict_correct"]+=WORD.findall(answer.lower())==WORD.findall(true.lower())
        counts["f1_sum"]+=metric(answer,true)
        counts["json_echo"]+=('"question"' in answer.lower() or '"evidence"' in answer.lower())
        counts["question_echo"]+=trial["request"]["question"].lower() in answer.lower()
        found={int(m.group(1)) for m in MARKER.finditer(answer)}
        counts["citation_markers_structurally_valid"]+=bool(found and
            all(i<=len(trial["request"]["sources"]) for i in found))
        counts["input_tokens"]+=row["input_tokens"]
        counts["output_tokens"]+=row["output_tokens"]
        counts["reader_seconds"]+=row["wall_seconds"]
    public={f"{arm}:{form}":dict(s) | dict(mean_diagnostic_f1=s["f1_sum"]/8)
            for (arm,form),s in stats.items()}
    result=dict(schema=SCHEMA, source_original_sha256=SOURCE_PIN,
                frozen_reader_model_zip_sha256=MODEL_ZIP_SHA,
                model_source="offline_smol_reader OriginalSmol FP32; Torch CPU",
                raw_original_journal_sha256=audit["original_generation_sha256"],
                source_reproduction_exact_original_requests=audit["original_prompts_reproduced"],
                complete_real_model_requests=len(rows), actual_successful_requests=sum(r["status"]=="succeeded" for r in rows),
                previous_public_evaluation_exposure=True,
                independently_human_verified_witnesses=0,
                model_training_steps=0, new_source_families=0,
                external_model_operator_parity=False,
                stronger_reference_reader_executed=False, semantic_citation_entailment=None,
                independent_future_windows=0, complete_lifecycle_tco=None,
                production_accepted=False, admission="DENY_ALL",
                by_arm=public)
    write(output,result)
    print(json.dumps({"result_path":str(output),"real_attempts":len(rows),"outcomes":{k:{kk:v[kk] for kk in ("strict_correct","json_echo","question_echo") if kk in v} for k,v in public.items()}},sort_keys=True))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="cmd",required=True)
    q=sub.add_parser("prepare");q.add_argument("prior_run",type=Path);q.add_argument("output",type=Path)
    q=sub.add_parser("execute");q.add_argument("registered",type=Path);q.add_argument("model",type=Path)
    q=sub.add_parser("audit");q.add_argument("registered",type=Path);q.add_argument("prior_run",type=Path)
    q=sub.add_parser("score");q.add_argument("dataset",type=Path);q.add_argument("registered",type=Path);q.add_argument("prior_run",type=Path);q.add_argument("report",type=Path)
    args=p.parse_args()
    if args.cmd=="prepare":main_result=prepare(args.prior_run,args.output)
    elif args.cmd=="execute":main_result=execute(args.registered,args.model)
    elif args.cmd=="audit":main_result=audit_original(args.registered,args.prior_run)
    else:main_result=score(args.dataset,args.registered,args.prior_run,args.report)
    if main_result is not None:
        print(main_result)


if __name__=="__main__":main()
