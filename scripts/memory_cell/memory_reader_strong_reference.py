"""Pinned Qwen3 stronger Reader against an existing six-arm MemoryCell plan.

RESEARCH / DENY_ALL. The worker never reads source gold, old Reader answers,
or MemoryCell model selection. Original source is opened only by postseal audit.
Strong-model bytes are admitted by the pinned, separately reviewed V19 publisher
material contract; no implicit model downloads, synthetic fallback or final use.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import json
import os
import re
import sys
import time

import memory_reader_causal_panel as base

SCHEMA = "hepta.memory-reader-qwen3-strong-reference.research.v1"
REPO = "Qwen/Qwen3-0.6B"
REVISION = "16706fc57485378d4ffaf54139b29ccc66ae08fa"
OUTPUT_CAP = 24  # Bound to the separately pinned V19 model-source profile.
INPUT_CAP = 2048
MAX_ANSWER_BYTES = 8192
ROLE_TOKENS = ("<|im_start|>", "<|im_end|>", "<|fim_prefix|>", "<|fim_middle|>")
EXPECTED_V19_BLOB = "e7269a61ab8d03269de5b9a042d6552fadfae285"


def model_messages(request):
    """Same evidence/question content as 135M, model-native ChatML wrappers."""
    if not isinstance(request, dict) or not isinstance(request.get("question"), str):
        raise ValueError("unregistered reader request")
    evidence = request.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("invalid evidence request")
    for e in evidence:
        if not isinstance(e, dict) or set(e) != {"source_id", "label", "text"}:
            raise ValueError("unregistered evidence fields")
    content = json.dumps({"question": request["question"],
        "evidence": [{"label": e["label"], "text": e["text"]} for e in evidence]},
        ensure_ascii=False)
    if any(delimiter in content for delimiter in ROLE_TOKENS):
        raise ValueError("untrusted model role delimiter")
    return [{"role": "system", "content": base.SYSTEM},
            {"role": "user", "content": content}]


def preflight(plan_dir):
    plan, ph = base.load_plan(plan_dir)
    if (plan["planned_questions"] != 20 or len(plan["requests"]) != 120
        or plan["original_sha256"] != base.ORIGINAL_SHA
        or plan["max_input_tokens"] != 2048 or plan["max_new_tokens"] != 32
        or plan["answer_labels_in_model_plan"] is not False):
        raise ValueError("wrong historical six-arm Reader panel")
    request_ids = [r["request_id"] for r in plan["requests"]]
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("duplicate historical plan request")
    for request in plan["requests"]:
        model_messages(request)
    return plan, ph


def snapshot(model_dir, spec_path):
    """Reuse V19 source authenticity; V19 must be pinned in worker PYTHONPATH."""
    from v19_qwen_material import verify_snapshot, REPO as MATERIAL_REPO
    from v19_qwen_material import REVISION as MATERIAL_REVISION
    if MATERIAL_REPO != REPO or MATERIAL_REVISION != REVISION:
        raise ValueError("staged publisher revision incompatible")
    spec = base.strict(base.read(spec_path, maximum=1_048_576))
    if (spec.get("repo") != REPO or spec.get("revision") != REVISION
        or spec.get("decoding") != "native-qwen3-greedy-24-no-thinking"):
        raise ValueError("unexpected Qwen3 publisher manifest")
    source_hash = verify_snapshot(model_dir, spec)
    if not isinstance(source_hash, str) or not source_hash:
        raise ValueError("Qwen3 source identity unavailable")
    return spec, source_hash


def tokenized_request(tokenizer, request):
    messages = model_messages(request)
    ids = tokenizer.apply_chat_template(messages, tokenize=True,
           add_generation_prompt=True, enable_thinking=False)
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 8192
        or any(type(n) is not int or n < 0 for n in ids)):
        raise ValueError("invalid native Qwen3 tokenizer result")
    return ids


def make_record(request, ph, identity):
    return {"request_id": request["request_id"], "question_id": request["question_id"],
        "family": request["family"], "arm": request["arm"],
        "plan_sha256": ph, "model_spec_digest": identity,
        "evidence_ids": [e["source_id"] for e in request["evidence"]],
        "prompt_digest": base.digest(base.canonical(model_messages(request))),
        "status": "unavailable" if request["unavailable"] else "pending",
        "reason": "original-annotated-evidence-missing" if request["unavailable"] else None,
        "input_tokens": None, "input_ids_digest": None,
        "output_tokens": None, "generated_ids": None, "generated_ids_digest": None,
        "answer": None, "cpu_ms": None, "wall_ms": None}


def record_validate(plan, ph, entries, seal, tokenizer=None):
    """Reject resealed foreign outputs and any incomplete/invalid physical record.

    A valid protocol record is NOT a cryptographic proof of physical inference;
    signed-host independent replay must be established separately.
    """
    if (not isinstance(entries, list) or len(entries) != len(plan["requests"])
        or not isinstance(seal, dict) or set(seal) != {
            "schema", "plan_sha256", "journal_sha256", "model_repo",
            "model_revision", "model_spec_digest", "requests",
            "decoding", "reader_frozen_verified", "no_gold_visible", "production_accepted"}
        or seal["schema"] != SCHEMA
        or seal["plan_sha256"] != ph or seal["model_repo"] != REPO
        or seal["model_revision"] != REVISION
        or not isinstance(seal["model_spec_digest"], str)
        or seal["decoding"] != "greedy-24-no-thinking"
        or seal["requests"] != len(entries)
        or seal["reader_frozen_verified"] is not True
        or seal["no_gold_visible"] is not True
        or seal["production_accepted"] is not False):
        raise ValueError("invalid or unsealed strong Reader manifest")
    status_counts = Counter()
    for req, row in zip(plan["requests"], entries, strict=True):
        if (not isinstance(row, dict) or set(row) != set(make_record(req, ph, seal["model_spec_digest"]))
            or row["request_id"] != req["request_id"]
            or row["question_id"] != req["question_id"]
            or row["family"] != req["family"] or row["arm"] != req["arm"]
            or row["plan_sha256"] != ph
            or row["model_spec_digest"] != seal["model_spec_digest"]
            or row["evidence_ids"] != [v["source_id"] for v in req["evidence"]]
            or row["prompt_digest"] != base.digest(base.canonical(model_messages(req)))
            or row["status"] not in {"succeeded", "unavailable", "failed"}):
            raise ValueError("unbound or incomplete strong Reader record")
        status_counts[row["status"]] += 1
        if req["unavailable"]:
            if (row != make_record(req, ph, seal["model_spec_digest"])):
                raise ValueError("unavailable source was changed or model falsely run")
            continue
        if (type(row["input_tokens"]) is not int or not 1 <= row["input_tokens"] <= 8192
            or not isinstance(row["input_ids_digest"], str)
            or len(row["input_ids_digest"]) != 64):
            raise ValueError("missing physical model input receipt")
        if tokenizer is not None:
            ids = tokenized_request(tokenizer, req)
            if row["input_tokens"] != len(ids) or row["input_ids_digest"] != base.digest(base.canonical(ids)):
                raise ValueError("native tokenization or prompt source changed")
        if row["status"] == "unavailable":
            if row["reason"] != "input-token-cap" or row["input_tokens"] <= INPUT_CAP:
                raise ValueError("false model unavailability")
            if any(row[f] is not None for f in ("answer", "generated_ids", "generated_ids_digest",
                                                   "output_tokens", "cpu_ms", "wall_ms")):
                raise ValueError("unavailable call contains model effect")
            continue
        if (row["status"] != "succeeded" or row["reason"] is not None
            or type(row["output_tokens"]) is not int
            or not 1 <= row["output_tokens"] <= OUTPUT_CAP
            or not isinstance(row["generated_ids"], list)
            or len(row["generated_ids"]) != row["output_tokens"]
            or any(type(i) is not int or i < 0 for i in row["generated_ids"])
            or row["generated_ids_digest"] != base.digest(base.canonical(row["generated_ids"]))
            or not isinstance(row["answer"], str)
            or not 0 < len(row["answer"].encode("utf-8")) <= MAX_ANSWER_BYTES
            or type(row["cpu_ms"]) is not int or row["cpu_ms"] < 0
            or type(row["wall_ms"]) is not int or row["wall_ms"] < 0):
            raise ValueError("failed/unverified model result cannot be scored")
        if tokenizer is not None:
            decoded = tokenizer.decode(row["generated_ids"], skip_special_tokens=True)
            if decoded != row["answer"]:
                raise ValueError("model token IDs disagree with actual decoded answer")
    return status_counts


def write_start(path, row):
    """Durable before-effect intent. Aborted runs remain incomplete, not replayed."""
    from memory_reader_strong_custody import event
    flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, 0o600), "ab") as f:
        f.write(base.canonical(event(row)))
        f.flush()
        os.fsync(f.fileno())


def worker(plan_dir, model_dir, model_spec_path, output_dir):
    plan, ph = preflight(plan_dir)
    out = Path(output_dir)
    if out.exists() or out.is_symlink():
        raise FileExistsError("strong Reader output must be create-only")
    _, material = snapshot(model_dir, model_spec_path)
    # The worker owns only label-free plan, checked model material and receipts.
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    torch.set_num_threads(2)
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True,
                                              trust_remote_code=False, use_fast=True)
    model = AutoModelForCausalLM.from_pretrained(model_dir, local_files_only=True,
                            trust_remote_code=False, use_safetensors=True,
                            dtype=torch.float32, attn_implementation="eager").eval()
    model.requires_grad_(False)
    if snapshot(model_dir, model_spec_path)[1] != material:
        raise ValueError("Qwen3 model source changed during load")
    out.mkdir(mode=0o700)
    rows = []
    intent = out / "started.jsonl"
    with torch.inference_mode():
        for request in plan["requests"]:
            row = make_record(request, ph, material)
            if not request["unavailable"]:
                ids = tokenized_request(tokenizer, request)
                row["input_tokens"] = len(ids)
                row["input_ids_digest"] = base.digest(base.canonical(ids))
                if len(ids) > INPUT_CAP:
                    row.update(status="unavailable", reason="input-token-cap")
                else:
                    write_start(intent, row)
                    t0, c0 = time.perf_counter(), time.process_time()
                    result = model.generate(input_ids=torch.tensor([ids], dtype=torch.long),
                                            do_sample=False, max_new_tokens=OUTPUT_CAP,
                                            eos_token_id=tokenizer.eos_token_id,
                                            pad_token_id=tokenizer.eos_token_id)
                    all_ids = result[0].tolist()
                    if all_ids[:len(ids)] != ids:
                        raise ValueError("native Qwen model response prefix changed")
                    new_ids = all_ids[len(ids):]
                    answer = tokenizer.decode(new_ids, skip_special_tokens=True)
                    if not new_ids or not answer.strip():
                        raise ValueError("empty native Qwen generation")
                    row.update(status="succeeded", generated_ids=new_ids,
                               answer=answer, output_tokens=len(new_ids),
                               generated_ids_digest=base.digest(base.canonical(new_ids)),
                               wall_ms=int((time.perf_counter()-t0)*1000),
                               cpu_ms=int((time.process_time()-c0)*1000))
            rows.append(row)
            # Do not write full outputs to public stdout or GitHub test logs.
    if snapshot(model_dir, model_spec_path)[1] != material:
        raise ValueError("model source changed after native inference")
    if any(p.requires_grad for p in model.parameters()):
        raise ValueError("reference weights became trainable")
    journal_sha = base.write(out / "journal.json", rows)
    seal = {"schema": SCHEMA, "plan_sha256": ph, "journal_sha256": journal_sha,
        "model_repo": REPO, "model_revision": REVISION,
        "model_spec_digest": material, "requests": len(rows),
        "decoding": "greedy-24-no-thinking", "reader_frozen_verified": True,
        "no_gold_visible": True, "production_accepted": False}
    record_validate(plan, ph, rows, seal, tokenizer)
    from memory_reader_strong_custody import check as check_before_effect
    check_before_effect(plan, ph, rows, out)
    base.write(out / "seal.json", seal)
    return {"status": "SEALED_RESEARCH_ONLY", "attempts": len(rows),
            "statuses": dict(Counter(r["status"] for r in rows)),
            "journal_sha256": journal_sha, "production_accepted": False}


def load_output(plan, ph, result_dir, tokenizer=None):
    raw = base.read(Path(result_dir) / "journal.json", maximum=16*1024*1024)
    rows = base.strict(raw)
    seal = base.strict(base.read(Path(result_dir) / "seal.json", maximum=1048576))
    if seal.get("journal_sha256") != base.digest(raw):
        raise ValueError("strong Reader output journal SHA mismatch")
    record_validate(plan, ph, rows, seal, tokenizer)
    return rows, seal


def cite_addresses(answer, evidence):
    labels = re.findall(r"\[E(\d+)\]", answer)
    available = {str(i) for i in range(1, len(evidence)+1)}
    return {"emitted": bool(labels), "in_range": bool(labels) and all(v in available for v in labels),
            "foreign": sum(v not in available for v in labels)}


def score_rows(plan, rows, references):
    """Postseal publisher-token diagnostics only, not semantic/citation judgments."""
    by_arm = defaultdict(lambda: {"planned": 0, "succeeded": 0, "unavailable": 0,
        "scorable": 0, "strict_exact": 0, "citation_emitting": 0,
        "in_range_citation_answers": 0, "foreign_citation_tokens": 0,
        "sum_diagnostic_f1": 0.0, "input_tokens": 0, "output_tokens": 0,
        "cpu_ms": 0, "wall_ms": 0})
    for req, row in zip(plan["requests"], rows, strict=True):
        counts = by_arm[req["arm"]]
        counts["planned"] += 1
        if row["status"] != "succeeded":
            counts["unavailable"] += 1
            continue
        counts["succeeded"] += 1
        counts["input_tokens"] += row["input_tokens"]
        counts["output_tokens"] += row["output_tokens"]
        counts["cpu_ms"] += row["cpu_ms"]
        counts["wall_ms"] += row["wall_ms"]
        citations = cite_addresses(row["answer"], req["evidence"])
        counts["citation_emitting"] += citations["emitted"]
        counts["in_range_citation_answers"] += citations["in_range"]
        counts["foreign_citation_tokens"] += citations["foreign"]
        gold = references.get(req["question_id"])
        if isinstance(gold, str) and gold.strip():
            counts["scorable"] += 1
            counts["sum_diagnostic_f1"] += base.token_f1(row["answer"], gold)
            counts["strict_exact"] += row["answer"].strip().lower() == gold.strip().lower()
    out = {}
    for a in base.ARMS:
        r = by_arm[a]
        if r["planned"] != plan["planned_questions"]:
            raise ValueError("incomplete reader arm population")
        out[a] = {k:v for k,v in r.items() if k != "sum_diagnostic_f1"}
        out[a]["mean_diagnostic_token_f1"] = (r["sum_diagnostic_f1"] / r["scorable"]
                                                   if r["scorable"] else None)
    return out


HISTORICAL_PLAN_SHA = "a7ad39c6548b06dc0fd752cd77149deaeb46875b3307696fe2857ef0cd1fc3e9"
HISTORICAL_135M_JOURNAL_SHA = "0797d8b1a4d9b9e3d7d68925bf4001666f253191d2bac46d90a0af11c78f0d76"


def paired_historical_control(plan, ph, qwen_rows, references, previous_135m_dir):
    """Only original sealed 120-call predecessor; never relabel historical output.

    Different readers have different native tokenizers, 32-vs-24 output caps,
    model sizes, and cost. This diagnostic is NOT a matched-compute trial.
    """
    if ph != HISTORICAL_PLAN_SHA:
        raise ValueError("historical 135M baseline has a different source plan")
    original_raw = base.read(Path(previous_135m_dir) / "journal.json", maximum=16*1024*1024)
    if base.digest(original_raw) != HISTORICAL_135M_JOURNAL_SHA:
        raise ValueError("historical baseline raw generation bytes changed")
    old = base.strict(original_raw)
    seal = base.strict(base.read(Path(previous_135m_dir) / "seal.json"))
    if (not isinstance(old, list) or len(old) != len(qwen_rows)
        or seal != {"schema": base.SCHEMA, "plan_sha256": ph,
            "journal_sha256": HISTORICAL_135M_JOURNAL_SHA,
            "model_sha256": base.MODEL_SHA, "attempts": len(old),
            "arms": list(base.ARMS), "generation_end_checked": True,
            "production_accepted": False}):
        raise ValueError("historical predecessor seal/profile invalid")
    aggregate = defaultdict(lambda: {"jointly_scorable": 0, "qwen_f1": 0.0,
                        "smol135_f1": 0.0, "wins": 0, "losses": 0, "ties": 0})
    for request, oldrow, newrow in zip(plan["requests"], old, qwen_rows, strict=True):
        if (oldrow.get("request_id") != request["request_id"]
            or oldrow.get("question_id") != request["question_id"]
            or oldrow.get("arm") != request["arm"]
            or oldrow.get("plan_sha256") != ph
            or oldrow.get("reader_model_sha256") != base.MODEL_SHA
            or oldrow.get("decoder_max") != 32
            or oldrow.get("evidence_ids") != [x["source_id"] for x in request["evidence"]]
            or oldrow.get("status") not in ("succeeded", "unavailable", "failed")):
            raise ValueError("historical original model metadata disagrees with plan")
        if (oldrow["status"] != "succeeded" or newrow["status"] != "succeeded"):
            continue
        gold = references.get(request["question_id"])
        if not isinstance(gold, str) or not gold.strip():
            continue
        x = base.token_f1(oldrow["answer"], gold)
        y = base.token_f1(newrow["answer"], gold)
        a = aggregate[request["arm"]]
        a["jointly_scorable"] += 1
        a["smol135_f1"] += x
        a["qwen_f1"] += y
        a["wins"] += y > x + 1e-12
        a["losses"] += y < x - 1e-12
        a["ties"] += abs(y-x) <= 1e-12
    return {arm: {
        "jointly_scorable": aggregate[arm]["jointly_scorable"],
        "qwen_mean_f1": aggregate[arm]["qwen_f1"]/aggregate[arm]["jointly_scorable"]
            if aggregate[arm]["jointly_scorable"] else None,
        "smol135_mean_f1": aggregate[arm]["smol135_f1"]/aggregate[arm]["jointly_scorable"]
            if aggregate[arm]["jointly_scorable"] else None,
        "qwen_wins": aggregate[arm]["wins"],
        "qwen_losses": aggregate[arm]["losses"],
        "ties": aggregate[arm]["ties"],
        "native_token_and_generation_budget_equal": False,
    } for arm in base.ARMS}


def review(original, prepared, source_run, plan_dir, qwen_dir, model_dir, spec_path, report_path):
    """Open publisher answers ONLY after sealed strong-model outputs exist."""
    plan, ph = preflight(plan_dir)
    rows, seal = load_output(plan, ph, qwen_dir)
    import tempfile
    with tempfile.TemporaryDirectory(prefix="mcell-strong-postseal-") as t:
        generated = Path(t) / "plan"
        base.make_plan(original, prepared, source_run, generated,
                       per_family=plan["planned_questions"] // 10)
        expected, expected_sha = preflight(generated)
        if expected != plan or expected_sha != ph:
            raise ValueError("strong Reader source/plan does not match original")
    _, material = snapshot(model_dir, spec_path)
    if seal["model_spec_digest"] != material:
        raise ValueError("strong model source changed between worker and reviewer")
    # Recheck tokenizer-level source and actual emitted token/answer consistency.
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True,
                                            trust_remote_code=False, use_fast=True)
    record_validate(plan, ph, rows, seal, tokenizer)
    from memory_reader_strong_custody import check as check_before_effect
    custody = check_before_effect(plan, ph, rows, qwen_dir)
    original_data = base.validated_original(original, base.read_public(prepared, reviewer=True)[0])
    refs = {}
    for req in plan["requests"]:
        qid = req["question_id"]
        qa = original_data[req["family"]]["qa"][int(qid.rsplit("q",1)[1])]
        refs[qid] = qa.get("answer")
    scored = score_rows(plan, rows, refs)
    from memory_reader_source_citation import publisher_sources, audit as audit_citations
    source_citation = audit_citations(plan, rows, publisher_sources(original_data, plan))
    report = {"schema": SCHEMA + ".postseal.v1", "plan_sha256": ph,
        "journal_sha256": seal["journal_sha256"], "model_repo": REPO,
        "model_revision": REVISION, "model_spec_digest": material,
        "questions": plan["planned_questions"], "per_arm": scored,
        "publisher_source_citation": source_citation,
        "before_effect_custody": custody,
        "prompt_content_shared_with_135m": True,
        "native_tokenization_and_generation_budget_matched_to_135m": False,
        "publisher_annotated_evidence_privileged": True,
        "independent_human_sufficiency_certified": False,
        "independent_semantic_answer_adjudicated": False,
        "citation_entailment_verified": False,
        "physical_model_generation_independently_attested": False,
        "statistical_superiority": False,
        "cell_training_or_graph_parameter_gain": False,
        "production_accepted": False,
        "decision": "HOLD_NO_GO"}
    base.write(report_path, report)
    return report


def main(args=None):
    args = sys.argv[1:] if args is None else args
    if len(args) == 2 and args[0] == "preflight":
        plan, ph = preflight(args[1]); output = {"plan_sha256": ph,
          "questions": plan["planned_questions"], "planned": len(plan["requests"]),
          "qualifies_model": False}
    elif len(args) == 5 and args[0] == "worker":
        output = worker(*args[1:])
    elif len(args) == 9 and args[0] == "review":
        output = review(*args[1:])
    else:
        raise SystemExit("preflight PLAN | worker PLAN QWEN_FILES QWEN_SPEC OUT | "
            "review ORIGINAL PREPARED SOURCE_RUN PLAN QWEN_OUT QWEN_FILES QWEN_SPEC REPORT")
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
