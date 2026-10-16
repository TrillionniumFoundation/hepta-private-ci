"""Physical frozen Smol135 Reader on eight published LoCoMo source families.

An original-model research diagnosis, NOT a prospective independent cohort or a
human-sufficient evidence oracle. 'prepare' reads questions and publisher source
IDs but NEVER answer labels; 'execute' reads only the sealed projection; a
separate 'score' invocation opens publisher labels after all model rows are fsynced.
No fine-tuning, memory-Cell benefit, new project repair or production authority.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

DATA_SHA = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
READER_GIT_BLOB = "c9567b43e5d15ca428baeb3a972b70435bcc7ed7"
MODEL_ZIP_SHA = "07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af"
ARMS = ("empty", "bm25_top3", "annotated_witness", "witness_lesion")
CATEGORIES = (2, 3, 4, 2, 3, 4, 2, 4)
MAX_INPUT, MAX_OUTPUT = 1200, 24
WORD = re.compile(r"[a-z0-9]+")
MARKER = re.compile(r"\[E([1-9][0-9]*)\]")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode())


def write(path, data):
    with Path(path).open("x", encoding="utf8") as out:
        json.dump(data, out, ensure_ascii=False, sort_keys=True, indent=2,
                  allow_nan=False)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())


def source_file(path, expected):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("regular original source file required")
    data = path.read_bytes()
    if sha(data) != expected:
        raise ValueError("original LoCoMo source digest mismatch")
    return json.loads(data)


def rank_bm25(question, turns):
    """Question-only lexical retrieval, fixed before model or annotation scoring."""
    tokens = WORD.findall(question.lower())
    lengths = []
    counters = []
    df = Counter()
    for turn in turns:
        counts = Counter(WORD.findall(turn["text"].lower()))
        lengths.append(sum(counts.values()))
        counters.append(counts)
        df.update(counts.keys())
    n = len(turns)
    mean_len = max(1, sum(lengths) / max(1, n))
    scored = []
    for i, counts in enumerate(counters):
        score = 0.0
        for term in set(tokens):
            freq = counts.get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * freq * 2.2 / (freq + 1.2 * (0.25 + 0.75 * lengths[i] / mean_len))
        scored.append((score, turns[i]["id"]))
    return [t for _, t in sorted(scored, key=lambda p: (-p[0], p[1]))]


def prepare(dataset, output):
    corpus = source_file(dataset, DATA_SHA)
    if not isinstance(corpus, list) or len(corpus) != 10:
        raise ValueError("exact published LoCoMo root census required")
    roots = sorted(corpus, key=lambda item: sha(item["sample_id"].encode()))[:8]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    plan, requests = [], []
    for index, root in enumerate(roots):
        turns = []
        for name, session in root["conversation"].items():
            if re.fullmatch(r"session_[0-9]+", name) and isinstance(session, list):
                for turn in session:
                    if isinstance(turn, dict) and isinstance(turn.get("dia_id"), str) \
                            and isinstance(turn.get("text"), str) and 1 <= len(turn["text"]) <= 600:
                        turns.append(dict(id=turn["dia_id"], speaker=turn["speaker"],
                                          text=turn["text"]))
        by_id = {t["id"]: t for t in turns}
        if len(by_id) != len(turns):
            raise ValueError("ambiguous original dialogue IDs")
        category = CATEGORIES[index]
        eligible = [(j, q) for j, q in enumerate(root["qa"])
                    if q.get("category") == category
                    and isinstance(q.get("question"), str) and len(q["question"]) <= 280
                    and isinstance(q.get("evidence"), list) and len(q["evidence"]) == 1
                    and q["evidence"][0] in by_id]
        if not eligible:
            raise ValueError("fixed source-only selection lacks evidence-local case")
        j, chosen = min(eligible, key=lambda item: sha(
            (root["sample_id"] + ":" + str(item[0]) + ":" + item[1]["question"]).encode()))
        # Deliberately no reference to chosen['answer'] in this process.
        witness = chosen["evidence"][0]
        ranked = rank_bm25(chosen["question"], turns)
        distractors = [doc_id for doc_id in ranked if doc_id != witness][:2]
        arms = dict(empty=[], bm25_top3=ranked[:3],
                    annotated_witness=[witness, *distractors],
                    witness_lesion=distractors)
        qid = digest((root["sample_id"], j, chosen["question"]))
        for arm in ARMS:
            ids = arms[arm]
            projected = [by_id[source_id] for source_id in ids]
            requests.append(dict(qid=qid, root_sha256=sha(root["sample_id"].encode()),
                                 question=chosen["question"], arm=arm,
                                 sources=projected, source_ids=ids))
        plan.append(dict(qid=qid, root_sha256=sha(root["sample_id"].encode()),
                         original_question_index=j, category=category,
                         witness_original_id_sha256=sha(witness.encode()),
                         publisher_annotation_is_not_independent_review=True))
    sealed = dict(schema="hepta.memory.locomo-fixed-reader-private-input.v1", requests=requests)
    write(output / "sealed-inputs.json", sealed)
    write(output / "preregistered.json", dict(
        schema="hepta.memory.locomo-four-evidence-regimes.v1",
        source_archive_sha256=DATA_SHA, reader_source_git_blob=READER_GIT_BLOB,
        original_model_archive_sha256=MODEL_ZIP_SHA,
        source_roots=len(roots), fixed_cases=plan, arms=ARMS,
        max_input_tokens=MAX_INPUT, max_output_tokens=MAX_OUTPUT,
        sealed_inputs_sha256=sha((output / "sealed-inputs.json").read_bytes()),
        selection="SHA-lowest question with 1 published dialogue witness per root/category",
        reader_frozen_before_task_scoring=True, no_answer_labels_opened_in_prepare=True,
        same_reader_prompt_tools_and_budget_for_each_arm=True,
        publisher_witness_independent_sufficiency=False, dataset_previously_public=True,
        production_accepted=False))
    return output / "preregistered.json"


def execute(run_dir, model_root):
    from offline_smol_reader import OriginalSmol, PROFILE, PINS
    import torch

    run_dir = Path(run_dir)
    plan = json.loads((run_dir / "preregistered.json").read_text())
    original = (run_dir / "sealed-inputs.json").read_bytes()
    if sha(original) != plan["sealed_inputs_sha256"]:
        raise ValueError("precommitted source/question evidence changed")
    contents = json.loads(original)
    requests = contents["requests"]
    if len(requests) != 8 * len(ARMS) or tuple(plan["arms"]) != ARMS:
        raise ValueError("incomplete preregistered condition census")
    torch.set_num_threads(2)
    model = OriginalSmol(model_root)
    script = Path(__file__).with_name("offline_smol_reader.py").read_bytes()
    if hashlib.sha1(b"blob " + str(len(script)).encode() + b"\0" + script).hexdigest() != READER_GIT_BLOB:
        raise ValueError("original model operator source changed")
    with (run_dir / "raw-answers.jsonl").open("x", encoding="utf8") as stream:
        for request in requests:
            messages = [
                dict(role="system", content="Answer briefly using only supplied dialogue excerpts. Cite [E1] etc when possible. If insufficient evidence, say I do not have enough evidence."),
                dict(role="user", content=json.dumps(dict(question=request["question"],
                      evidence=[dict(label=f"E{i}", speaker=d["speaker"], text=d["text"])
                                for i, d in enumerate(request["sources"], 1)]), ensure_ascii=False)),
            ]
            row = dict(qid=request["qid"], root_sha256=request["root_sha256"],
                       arm=request["arm"], delivered_ids_digest=digest(request["source_ids"]),
                       model_identity=model.identity, reader_profile=PROFILE)
            started = time.perf_counter()
            try:
                rendered = model.tokenizer.render(messages)
                ids = model.tokenizer.encode(rendered)
                if not 1 <= len(ids) <= MAX_INPUT:
                    raise ValueError("full prompt exceeds precommitted input ceiling")
                output = model.generate(ids, MAX_OUTPUT)
                row.update(status="succeeded", answer=model.tokenizer.decode(output),
                           generated_token_digest=digest(output), input_tokens=len(ids),
                           output_tokens=len(output), result_origin="actual original FP32 CPU model")
            except Exception as error:
                row.update(status="failed", error_type=type(error).__name__,
                           error=str(error)[:500], input_tokens=None, output_tokens=0)
            row["actual_reader_wall_seconds"] = time.perf_counter() - started
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    model.verify_frozen()
    print("frozen_real_model_attempts", len(requests), "raw_journal_sha256",
          sha((run_dir / "raw-answers.jsonl").read_bytes()))


def metric(answer, target):
    a, b = WORD.findall(answer.lower()), WORD.findall(str(target).lower())
    if not a or not b:
        return 0.0
    overlap = sum((Counter(a) & Counter(b)).values())
    return 2 * overlap / (len(a) + len(b))


def score(dataset, run_dir, report_path):
    run_dir = Path(run_dir)
    plan = json.loads((run_dir / "preregistered.json").read_text())
    original = (run_dir / "sealed-inputs.json").read_bytes()
    if sha(original) != plan["sealed_inputs_sha256"]:
        raise ValueError("source input changed after sealing")
    private = json.loads(original)
    raw_path = run_dir / "raw-answers.jsonl"
    if not raw_path.is_file() or raw_path.is_symlink():
        raise ValueError("durable full original answer journal required")
    raw_bytes = raw_path.read_bytes()
    attempts = [json.loads(x) for x in raw_bytes.splitlines()]
    expected_ids = [(r["qid"], r["arm"]) for r in private["requests"]]
    if len(attempts) != 8 * len(ARMS) or [(r["qid"], r["arm"]) for r in attempts] != expected_ids:
        raise ValueError("unsealed or incomplete raw model census")
    # This is the first and only stage that opens publisher target-answer labels.
    corpus = source_file(dataset, DATA_SHA)
    by_root = {sha(r["sample_id"].encode()): r for r in corpus}
    totals = {arm: Counter() for arm in ARMS}
    for row in attempts:
        control = next(p for p in plan["fixed_cases"] if p["qid"] == row["qid"])
        case = by_root[control["root_sha256"]]["qa"][control["original_question_index"]]
        expected = str(case["answer"])
        ok = row["status"] == "succeeded"
        chosen = str(row.get("answer", ""))
        normalized = WORD.findall(chosen.lower())
        desired = WORD.findall(expected.lower())
        arm = totals[row["arm"]]
        arm["planned"] += 1
        arm["model_succeeded"] += ok
        arm["strict_correct"] += bool(ok and normalized == desired)
        arm["token_f1_sum"] += metric(chosen, expected) if ok else 0.0
        arm["input_tokens"] += row.get("input_tokens") or 0
        arm["output_tokens"] += row.get("output_tokens") or 0
        arm["model_wall_seconds"] += row["actual_reader_wall_seconds"]
        marker_ids = {int(m.group(1)) for m in MARKER.finditer(chosen)}
        source_count = len(next(r for r in private["requests"] if r["qid"] == row["qid"] and r["arm"] == row["arm"])["sources"])
        arm["structurally_valid_citation"] += bool(ok and marker_ids and all(1 <= m <= source_count for m in marker_ids))
    report = dict(schema="hepta.memory.locomo-eight-family-physical-smol135.v1",
                  original_model_zip_sha256=MODEL_ZIP_SHA, source_json_sha256=DATA_SHA,
                  actual_reader_source_git_blob=READER_GIT_BLOB,
                  original_raw_journal_sha256=sha(raw_bytes),
                  source_and_prompts_sha256=plan["sealed_inputs_sha256"],
                  real_neural_model_attempts=8 * len(ARMS),
                  successful_neural_model_attempts=sum(row["status"] == "succeeded" for row in attempts),
                  independent_source_roots_not_authenticated=8,
                  original_published_benchmark_preexposed=True,
                  original_reader_frozen=True, trained_parameter_memory=False,
                  reference_stronger_reader_executed=False,
                  human_semantic_evidence_review=False,
                  program_execution_tasks=0, independent_future_windows=0,
                  complete_lifecycle_cost_usd=None, production_accepted=False,
                  by_arm={a:dict(totals[a]) | dict(
                      mean_diagnostic_token_f1=totals[a]["token_f1_sum"] / 8)
                      for a in ARMS})
    write(report_path, report)
    print(json.dumps({"published_result":str(report_path),
                      "real_model_calls":report["successful_neural_model_attempts"],
                      "raw_sha": report["original_raw_journal_sha256"]}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="stage", required=True)
    q = sub.add_parser("prepare")
    q.add_argument("dataset", type=Path)
    q.add_argument("output", type=Path)
    q = sub.add_parser("execute")
    q.add_argument("run_dir", type=Path)
    q.add_argument("reader_dir", type=Path)
    q = sub.add_parser("score")
    q.add_argument("dataset", type=Path)
    q.add_argument("run_dir", type=Path)
    q.add_argument("report", type=Path)
    args = p.parse_args()
    if args.stage == "prepare":
        print(prepare(args.dataset, args.output))
    elif args.stage == "execute":
        execute(args.run_dir, args.reader_dir)
    elif args.stage == "score":
        score(args.dataset, args.run_dir, args.report)
