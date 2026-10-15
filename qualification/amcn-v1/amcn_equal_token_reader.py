"""Equal-*actual-input-token*, same-original-Reader AMCN three-arm exploratory study.

All source/Head choices and eligibility are computed without benchmark gold.
Select original heldout questions whose unedited 3-arm Reader prompts happen
naturally to have identical token counts; do not pad, truncate or alter sources.
Two historical source roots only. This is diagnostic, never a production gate.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter
import torch

from amcn_original_trained_rank_heads import (
    pinned, SOURCE_SHA, RANK_DECISION_SHA, stable_rank_digest,
    file_sha, require,
)
from amcn_original_text_reader import (
    ArchivedLlama, ArchivedByteLevelBPE, WEIGHT_SHA256, format_archived_chat,
)

ARMS = ("bm25", "untyped_equal_budget", "typed_equal_budget")
HELDOUT = (("conv-49", "retrospective_heldout_a"),
           ("conv-50", "retrospective_heldout_b"))
READER_TOKENIZER_SHA = "9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c"
ORIGINAL_DATASET_SHA = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
GOLD_SHA = "758d951c2fb296c3ba23ef539e3f243fb8464d52ed0d42c8d0981943ac907a06"


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def seal_once(path, record):
    target = Path(path)
    require(not target.exists() and not target.is_symlink(),
            "create-only original research material required")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(canonical(record))
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(str(target.parent), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return file_sha(target)

PROFILE = "hepta.amcn.original-equal-input-token-three-arm-natural-reader.shadow.v1"
QUESTIONS_PER_FAMILY = 12
MAX_NEW_TOKENS = 48
MAX_INPUT_PLUS_OUTPUT = 1024
MAX_JOURNAL_BYTES = 32 * 1024 * 1024


def _sha(text):
    return sha256(text.encode("utf-8")).hexdigest()


def _fixed_plan(plan):
    require(isinstance(plan, dict) and plan.get("schema") == PROFILE and
            plan.get("source_sha256") == SOURCE_SHA and
            plan.get("reader_sha256") == WEIGHT_SHA256 and
            plan.get("tokenizer_sha256") == READER_TOKENIZER_SHA and
            plan.get("original_rank_decision_sha256") == RANK_DECISION_SHA and
            plan.get("max_output_tokens") == MAX_NEW_TOKENS and
            plan.get("final_evidence_slots") == 3 and
            plan.get("arms") == list(ARMS) and
            plan.get("independent_future_calendar_windows") == 0 and
            plan.get("gold_used_before_reader") is False and
            plan.get("production_accepted") is False and
            len(plan.get("cases", ())) == 2 * QUESTIONS_PER_FAMILY,
            "invalid original equal-token Reader preregistration")
    expected = {x[0]: QUESTIONS_PER_FAMILY for x in HELDOUT}
    seen = set()
    for case in plan["cases"]:
        fam, cid = case["family"], case["case_id"]
        require(fam in expected and cid not in seen and
                case["split"] == dict(HELDOUT)[fam], "unregistered heldout family")
        seen.add(cid)
        expected[fam] -= 1
        require(set(case["requests"]) == set(ARMS) and
                case["matched_input_token_count"] > 0,
                "incomplete original three-arm input")
        for arm in ARMS:
            req = case["requests"][arm]
            require(len(req["source_ids"]) == 3 and
                    len(set(req["source_ids"])) == 3 and
                    req["prompt_sha256"] == _sha(req["prompt"]) and
                    req["expected_input_tokens"] == case["matched_input_token_count"] and
                    req["expected_input_tokens"] + MAX_NEW_TOKENS <= MAX_INPUT_PLUS_OUTPUT,
                    "unmatched Reader original bytes or exact token cap")
    require(all(x == 0 for x in expected.values()), "not twelve questions per family")


def build_plan(public, frozen_rank, predictions, reader_directory, *,
               source_sha, rank_sha, predictions_sha):
    require(source_sha == SOURCE_SHA and
            public.get("publisher_targets_not_included") is True and
            public.get("production_accepted") is False and
            len(public.get("cases", ())) == 1986 and
            len(public.get("source_families", {})) == 10,
            "original source material or full census unavailable")
    require(all(isinstance(c, dict) and set(c) ==
                {"case_id", "family", "split", "question", "question_sha256"}
                for c in public["cases"]) and
            all(isinstance(s, dict) and set(s) == {"id", "root", "text"}
                for items in public["source_families"].values() for s in items),
            "publisher labels or unknown fields infiltrated original source material")
    require(frozen_rank.get("training_or_publisher_gold_accessed") is False and
            stable_rank_digest(frozen_rank) == RANK_DECISION_SHA and
            len(frozen_rank.get("case_predictions", ())) == 1986,
            "original source/Encoder rank decision drift")
    require(predictions.get("rank_sha256") == rank_sha and
            predictions.get("source_sha256") == source_sha and
            predictions.get("training_gold_never_opened_in_prediction_process") is True and
            predictions.get("production_accepted") is False and
            len(predictions.get("complete_predictions", ())) == 829,
            "missing original physically trained Head observation inventory")
    tokenizer = ArchivedByteLevelBPE(Path(reader_directory),
                                      expected_tokenizer_sha256=READER_TOKENIZER_SHA)
    by_case = {c["case_id"]: c for c in public["cases"]}
    by_predict = {p["case_id"]: p for p in predictions["complete_predictions"]}
    require(all(isinstance(x, dict) and set(x) ==
                {"case_id", "family", "split", "question_sha256", "memory_type", "ranked_source_ids"}
                for x in predictions["complete_predictions"]),
            "saved Head prediction contains publisher targets or unrecognized metadata")
    require(len(by_case) == 1986 and len(by_predict) == 829,
            "duplicate original source or Head case")
    chosen = []
    eligibility_counts = {}
    for family, split in HELDOUT:
        inv = {s["id"]: s["text"] for s in public["source_families"][family]}
        candidates = []
        for cid, prediction in by_predict.items():
            if prediction["family"] != family:
                continue
            original = by_case[cid]
            require(original["split"] == split and
                    original["question_sha256"] == prediction["question_sha256"] and
                    original["family"] == family,
                    "original prospective question/type switched")
            chosen_ids = {arm: prediction["ranked_source_ids"][arm][:3]
                          for arm in ARMS}
            require(all(len(v) == 3 and len(set(v)) == 3 for v in chosen_ids.values()),
                    "source rank missing actual Top-3")
            if any(sid not in inv or len(inv[sid].encode("utf-8")) > 640
                   for ids in chosen_ids.values() for sid in ids):
                continue
            prompts = {arm: format_archived_chat(original["question"],
                       [inv[sid] for sid in chosen_ids[arm]]) for arm in ARMS}
            ids = {arm: tokenizer.encode(prompt) for arm, prompt in prompts.items()}
            lengths = {arm: len(items) for arm, items in ids.items()}
            if len(set(lengths.values())) != 1 or max(lengths.values()) + MAX_NEW_TOKENS > MAX_INPUT_PLUS_OUTPUT:
                continue
            candidates.append((_sha(cid), cid, original, prediction, chosen_ids,
                               prompts, ids, next(iter(lengths.values()))))
        candidates.sort(key=lambda c: (c[0], c[1]))
        eligibility_counts[family] = len(candidates)
        require(len(candidates) >= QUESTIONS_PER_FAMILY,
                "not enough gold-blind NATURALLY same-token original prompts")
        for _, cid, original, prediction, selected, prompts, ids, length in candidates[:QUESTIONS_PER_FAMILY]:
            chosen.append({"case_id": cid, "family": family, "split": split,
                           "question_sha256": original["question_sha256"],
                           "memory_type": prediction["memory_type"],
                           "matched_input_token_count": length,
                           "requests": {arm: {"source_ids": selected[arm],
                                  "prompt": prompts[arm],
                                  "prompt_sha256": _sha(prompts[arm]),
                                  "input_token_ids_sha256": _sha(json.dumps(ids[arm], separators=(",", ":"))),
                                  "expected_input_tokens": length}
                                  for arm in ARMS}})
    plan = {"schema": PROFILE, "source_sha256": source_sha,
            "original_rank_file_sha256": rank_sha,
            "original_rank_decision_sha256": RANK_DECISION_SHA,
            "original_physical_head_predictions_sha256": predictions_sha,
            "reader_sha256": WEIGHT_SHA256,
            "tokenizer_sha256": READER_TOKENIZER_SHA,
            "arms": list(ARMS), "final_evidence_slots": 3,
            "max_output_tokens": MAX_NEW_TOKENS,
            "original_question_count": len(chosen), "matched_input_tokens_for_each_question": True,
            "original_eligible_counts_by_family": eligibility_counts,
            "cohort_rule": "12 smallest sha256(case_id) in EACH historical heldout family among real unmodified 3-arm prompts with identical exact input-token length; no benchmark gold",
            "cases": chosen,
            "gold_used_before_reader": False,
            "independent_future_calendar_windows": 0,
            "production_accepted": False}
    _fixed_plan(plan)
    return plan


def _read_journal(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and
            0 < path.stat().st_size <= MAX_JOURNAL_BYTES,
            "missing/oversized original Reader journal")
    raw = path.read_bytes()
    require(raw.endswith(b"\n"), "truncated original Reader journal")
    records = []
    for line in raw.splitlines():
        def strict_pairs(pairs):
            found = {}
            for k, v in pairs:
                require(k not in found, "duplicate original journal JSON key")
                found[k] = v
            return found
        records.append(json.loads(line, object_pairs_hook=strict_pairs))
    return records


def _recount(plan, run_directory, tokenizer):
    """Recount and authenticate the *contents* of original journal attempts.

    Original Reader producer SHA-consistency alone is not issuer signing;
    outside assessor must also independently pin plan and full journal bytes.
    """
    start = Path(run_directory) / "starts.jsonl"
    answer = Path(run_directory) / "raw_answers.jsonl"
    starts = _read_journal(start)
    answers = _read_journal(answer)
    require(len(starts) in (len(answers), len(answers) + 1),
            "incomplete Reader attempt census")
    attempts = [(c, arm) for c in plan["cases"] for arm in ARMS]
    complete, interrupted = {}, 0
    for idx, a in enumerate(answers):
        s = starts[idx]
        require(set(s) == {"case_id", "arm", "prompt_sha256", "reader_sha256"},
                "invalid original pre-attempt record")
        for key in s:
            require(a.get(key) == s[key], "original start/answer identity drift")
        key = s["case_id"], s["arm"]
        require(key in {(c["case_id"], arm) for c, arm in attempts},
                "unregistered original Reader attempt")
        original = next(c for c, arm in attempts if (c["case_id"], arm) == key)
        req = original["requests"][s["arm"]]
        require(req["prompt_sha256"] == s["prompt_sha256"] and
                s["reader_sha256"] == WEIGHT_SHA256,
                "mismatched original Reader prompt/weights")
        if a.get("status") == "interrupted":
            require(a.get("not_a_completed_reader_response") is True,
                    "interrupted inference was silently converted into success")
            interrupted += 1
            continue
        require(a.get("status") == "ok" and key not in complete and
                a.get("source_ids") == req["source_ids"] and
                a.get("input_tokens") == original["matched_input_token_count"] and
                type(a.get("output_tokens")) is int and
                1 <= a["output_tokens"] <= MAX_NEW_TOKENS and
                isinstance(a.get("generated_token_ids"), list) and
                len(a["generated_token_ids"]) == a["output_tokens"] and
                all(type(t) is int and 0 <= t < 49152 for t in a["generated_token_ids"]) and
                a.get("raw_model_text") == tokenizer.decode(a["generated_token_ids"]) and
                a.get("raw_model_text_sha256") == _sha(a["raw_model_text"]),
                "changed original model answer / token / budget")
        complete[key] = a
    require(len(starts) <= len(attempts) + interrupted + 1 and
            len(complete) + interrupted == len(answers),
            "lost or repeated original Reader attempt")
    if len(starts) > len(answers):
        require(starts[-1]["reader_sha256"] == WEIGHT_SHA256,
                "unregistered pending original Reader model")
    return starts, answers, complete, interrupted


def run(plan, reader_dir, output, *, resume=False):
    _fixed_plan(plan)
    target = Path(output)
    if not resume:
        require(not target.exists() and not target.is_symlink(),
                "create-only original Reader output")
        target.mkdir(parents=True)
    else:
        require(target.is_dir() and not target.is_symlink() and
                not (target / "seal.json").exists(),
                "cannot resume an already sealed Reader run")
    tok = ArchivedByteLevelBPE(Path(reader_dir),
                                expected_tokenizer_sha256=READER_TOKENIZER_SHA)
    starts_file, answers_file = target / "starts.jsonl", target / "raw_answers.jsonl"
    planned = [(c, arm) for c in plan["cases"] for arm in ARMS]
    if resume:
        starts, answers, complete, interrupted = _recount(plan, target, tok)
        if len(starts) > len(answers):
            open_attempt = starts[-1]
            with answers_file.open("ab") as stream:
                stream.write(canonical({**open_attempt, "status": "interrupted",
                     "not_a_completed_reader_response": True}))
                stream.flush(); os.fsync(stream.fileno())
            interrupted += 1
        require(len(complete) < len(planned), "already complete, cannot mask missing seal")
    else:
        require(not starts_file.exists() and not answers_file.exists(),
                "original Reader journal unexpectedly exists")
        complete, interrupted = {}, 0
    torch.set_num_threads(2)
    reader = ArchivedLlama(Path(reader_dir))
    for c, arm in planned:
        key = c["case_id"], arm
        if key in complete:
            continue
        request = c["requests"][arm]
        tokens = tok.encode(request["prompt"])
        require(len(tokens) == c["matched_input_token_count"] and
                _sha(json.dumps(tokens, separators=(",", ":"))) == request["input_token_ids_sha256"] and
                len(tokens) + MAX_NEW_TOKENS <= MAX_INPUT_PLUS_OUTPUT,
                "original WordPiece/ByteLevel Reader token input drift")
        start = {"case_id": key[0], "arm": arm,
                 "prompt_sha256": request["prompt_sha256"],
                 "reader_sha256": WEIGHT_SHA256}
        with starts_file.open("ab") as stream:
            stream.write(canonical(start)); stream.flush(); os.fsync(stream.fileno())
        try:
            t0 = perf_counter()
            generated = reader.generate(tokens, max_new_tokens=MAX_NEW_TOKENS)
            elapsed = perf_counter() - t0
            text = tok.decode(generated)
            completed = {**start, "status": "ok",
                         "source_ids": request["source_ids"],
                         "input_tokens": len(tokens),
                         "output_tokens": len(generated),
                         "generated_token_ids": generated,
                         "raw_model_text": text,
                         "raw_model_text_sha256": _sha(text),
                         "observed_wall_seconds": elapsed}
        except Exception:
            with answers_file.open("ab") as stream:
                stream.write(canonical({**start, "status": "interrupted",
                     "not_a_completed_reader_response": True}))
                stream.flush(); os.fsync(stream.fileno())
            raise
        with answers_file.open("ab") as stream:
            stream.write(canonical(completed)); stream.flush(); os.fsync(stream.fileno())
        complete[key] = completed
    started, answered, complete, interrupted = _recount(plan, target, tok)
    require(len(complete) == len(planned) and len(started) == len(answered) and
            len(answered) == len(planned) + interrupted,
            "refuse partially completed or lost original model results")
    seal = {"schema": PROFILE + ".sealed-original-reader-answers.v1",
            "original_source_sha256": plan["source_sha256"],
            "original_physical_head_predictions_sha256": plan["original_physical_head_predictions_sha256"],
            "original_plan_sha256": sha256(canonical(plan)).hexdigest(),
            "reader_sha256": WEIGHT_SHA256, "tokenizer_sha256": READER_TOKENIZER_SHA,
            "attempt_starts_sha256": file_sha(starts_file),
            "attempt_answers_sha256": file_sha(answers_file),
            "original_question_count": len(plan["cases"]),
            "successful_model_answers": len(complete),
            "incomplete_attempts_preserved": interrupted,
            "input_tokens_per_question_equal_across_all_arms": True,
            "raw_answer_count_exact": len(planned),
            "cases": [complete[c["case_id"], arm] for c, arm in planned],
            "gold_used_before_reader": False,
            "official_hf_parity_verified": False,
            "production_accepted": False}
    seal_once(target / "seal.json", seal)
    return seal


def score(plan, sealed, publisher, *, plan_sha, seal_sha, tokenizer, run_directory):
    _fixed_plan(plan)
    require(sealed.get("schema") == PROFILE + ".sealed-original-reader-answers.v1" and
            sealed["original_source_sha256"] == plan["source_sha256"] and
            sealed["original_plan_sha256"] == sha256(canonical(plan)).hexdigest() and
            sealed["reader_sha256"] == plan["reader_sha256"] and
            sealed["tokenizer_sha256"] == plan["tokenizer_sha256"] and
            sealed["official_hf_parity_verified"] is False and
            sealed["gold_used_before_reader"] is False and
            sealed["production_accepted"] is False,
            "original Reader model/plan or independent source drift")
    directory = Path(run_directory)
    require(sealed["attempt_starts_sha256"] == file_sha(directory / "starts.jsonl") and
            sealed["attempt_answers_sha256"] == file_sha(directory / "raw_answers.jsonl"),
            "original Reader journal byte identity changed")
    _, _, complete, interrupted = _recount(plan, directory, tokenizer)
    require(len(complete) == len(plan["cases"]) * len(ARMS) and
            len(sealed["cases"]) == len(complete) and
            sealed["incomplete_attempts_preserved"] == interrupted and
            sealed["successful_model_answers"] == len(complete),
            "hidden failures or incomplete sealed original Reader tasks")
    for a, b in zip(sealed["cases"], [complete[c["case_id"], arm]
                            for c in plan["cases"] for arm in ARMS]):
        require(a == b, "original answer differs from durable attempt journal")
    require(publisher.get("dataset_sha256") == ORIGINAL_DATASET_SHA and
            publisher.get("publisher_weak_sha256") == GOLD_SHA and
            publisher.get("post_reader_seal_only") is True and
            isinstance(publisher.get("by_case_id"), dict),
            "untrusted postseal original publisher target material")
    counts = {arm: {"questions": 0, "weak_any_at3": 0,
                    "weak_all_at3": 0, "literal_answer_exact": 0,
                    "input_tokens": 0, "output_tokens": 0,
                    "answers_capped": 0,
                    "publisher_standard_labels": 0,
                    "publisher_adversarial_labels": 0,
                    "standard_answer_literal_exact": 0,
                    "adversarial_answer_literal_exact": 0} for arm in ARMS}
    family_stats = {family: {arm: dict(counts[arm]) for arm in ARMS}
                    for family, _ in HELDOUT}
    question_measures = {}
    for case in plan["cases"]:
        cid, family = case["case_id"], case["family"]
        require(cid in publisher["by_case_id"], "publisher heldout question missing")
        target = publisher["by_case_id"][cid]
        require(target["family"] == family and
                _sha(target["question"]) == case["question_sha256"],
                "publisher question identity changed after source selection")
        label_kind = target.get("publisher_label_kind")
        require(label_kind in ("standard_answer", "adversarial_answer") and
                isinstance(target.get("answer"), (str, int, float)),
                "original publisher normal/adversarial answer field is missing")
        support = set(target["publisher_support"])
        outcomes = {}
        for arm in ARMS:
            raw = complete[cid, arm]
            refs = set(case["requests"][arm]["source_ids"])
            hit = bool(support & refs)
            all_hit = bool(support) and support <= refs
            text = raw["raw_model_text"].strip().casefold()
            gold = str(target["answer"]).strip().casefold()
            exact = bool(text) and text == gold
            capped = raw["output_tokens"] == MAX_NEW_TOKENS
            m = {"weak_any_at3": int(hit), "weak_all_at3": int(all_hit),
                 "literal_answer_exact": int(exact),
                 "answers_capped": int(capped),
                 "publisher_standard_labels": int(label_kind == "standard_answer"),
                 "publisher_adversarial_labels": int(label_kind == "adversarial_answer"),
                 "standard_answer_literal_exact": int(exact and label_kind == "standard_answer"),
                 "adversarial_answer_literal_exact": int(exact and label_kind == "adversarial_answer") }
            for group in (counts[arm], family_stats[family][arm]):
                group["questions"] += 1
                group["input_tokens"] += raw["input_tokens"]
                group["output_tokens"] += raw["output_tokens"]
                for k, v in m.items():
                    group[k] += v
            outcomes[arm] = m
        question_measures[_sha(cid)] = outcomes
    require(all(x["questions"] == 2 * QUESTIONS_PER_FAMILY for x in counts.values()) and
            len({x["input_tokens"] for x in counts.values()}) == 1,
            "incomplete or unequal actual Reader context-token denominator")
    return {"schema": PROFILE + ".independent-postseal-publisher-description.v1",
            "original_plan_file_sha256": plan_sha,
            "original_answer_seal_file_sha256": seal_sha,
            "source_families": len(HELDOUT),
            "questions": 2 * QUESTIONS_PER_FAMILY,
            "actual_original_reader_forwards": len(complete),
            "successful_pretrained_reader_outputs": len(complete),
            "observed_interrupted_attempts": interrupted,
            "identical_reader_input_tokens_across_arms": True,
            "identical_max_new_token_budget_across_arms": True,
            "equal_total_compute_including_pretrained_retrieval_and_training": False,
            "original_bert_and_llama_hf_parity_verified": False,
            "publisher_weak_support_not_independent_entailment": True,
            "original_standard_and_adversarial_labels_scored_separately": True,
            "original_reader_semantic_task_success_independently_accepted": False,
            "independent_future_calendar_windows": 0,
            "original_retrospective_family_roots": 2,
            "arm_totals": counts,
            "per_family": family_stats,
            "paired_positive_negative_flips_vs_bm25": {
                arm: {"new_weak_hit": sum(1 for v in question_measures.values()
                            if v[arm]["weak_any_at3"] > v["bm25"]["weak_any_at3"]),
                      "lost_weak_hit": sum(1 for v in question_measures.values()
                            if v[arm]["weak_any_at3"] < v["bm25"]["weak_any_at3"])}
                for arm in ARMS},
            "production_accepted": False,
            "three_axis_superiority_claim": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sp = p.add_subparsers(dest="phase", required=True)
    x = sp.add_parser("plan")
    for opt in ("public", "rank", "predictions", "reader_directory", "output"):
        x.add_argument("--" + opt.replace("_", "-"), required=True)
    for opt in ("source_sha", "rank_sha", "predictions_sha"):
        x.add_argument("--" + opt.replace("_", "-"), required=True)
    for mode in ("generate", "resume"):
        x = sp.add_parser(mode)
        for opt in ("plan", "plan_sha", "reader_directory", "output"):
            x.add_argument("--" + opt.replace("_", "-"), required=True)
    x = sp.add_parser("score")
    for opt in ("plan", "plan_sha", "seal", "seal_sha", "reader_directory",
                "original_gold", "gold_sha", "output"):
        x.add_argument("--" + opt.replace("_", "-"), required=True)
    args = p.parse_args()
    if args.phase == "plan":
        plan = build_plan(pinned(args.public, args.source_sha),
                          pinned(args.rank, args.rank_sha),
                          pinned(args.predictions, args.predictions_sha),
                          args.reader_directory,
                          source_sha=args.source_sha, rank_sha=args.rank_sha,
                          predictions_sha=args.predictions_sha)
        seal_once(args.output, plan)
        result = {"planned": len(plan["cases"]), "eligible": plan["original_eligible_counts_by_family"]}
    elif args.phase in ("generate", "resume"):
        plan = pinned(args.plan, args.plan_sha)
        result = run(plan, args.reader_directory, args.output,
                     resume=args.phase == "resume")
        result = {"original_reader_completed": result["successful_model_answers"],
                  "original_reader_incomplete": result["incomplete_attempts_preserved"]}
    else:
        plan = pinned(args.plan, args.plan_sha)
        sealed = pinned(args.seal, args.seal_sha)
        gold = pinned(args.original_gold, args.gold_sha)
        tok = ArchivedByteLevelBPE(Path(args.reader_directory),
                  expected_tokenizer_sha256=READER_TOKENIZER_SHA)
        summary = score(plan, sealed, gold, plan_sha=args.plan_sha,
                        seal_sha=args.seal_sha, tokenizer=tok,
                        run_directory=Path(args.seal).parent)
        seal_once(args.output, summary)
        result = summary
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
