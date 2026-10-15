"""Physical original LoCoMo Reader-capacity diagnostic; shadow / DENY_ALL.

Four precommitted regimes: zero evidence, original BM25 Top-3, original
publisher-ANNOTATED witness (+2 original BM25 distractors), and a witness
lesion (same distractors, unrelated original source). Publisher annotation is
NOT independently verified sufficient evidence. Gold answers never enter the
Reader executable process. No new Head, graph, authority or FinalUse.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from amcn_original_text_reader import (ArchivedByteLevelBPE, ArchivedLlama,
                                       WEIGHT_SHA256, format_archived_chat)

PROFILE = "hepta.amcn.reader-evidence-sufficiency-physical.shadow.v1"
ARMS = ("no_evidence", "original_bm25_top3", "publisher_annotated_witness",
        "publisher_witness_lesion")
FAMILIES = ("conv-47", "conv-48", "conv-49", "conv-50")
MAX_NEW = 24
MAX_CONTEXT = 1024
MAX_CASES_PER_FAMILY = 3
TOKENIZER_SHA = "9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c"
PUBLIC_SHA = "dac70024f437d81a85b99e7b143fbdf2b79d8951ce5960fb390d1d214a62c34a"
# Source/report authoring host hashes are not independent source-owner signatures.
DATA_SHA = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"


def file_sha(path):
    h = sha256()
    with Path(path).open("rb") as reader:
        for chunk in iter(lambda: reader.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def hash_bytes(value):
    return sha256(value).hexdigest()


def sha(value):
    return hash_bytes(canonical(value))


def no_dupes(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, "duplicate JSON key")
        out[key] = value
    return out


def pinned(path, expected, maximum=12_000_000):
    p = Path(path)
    require(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size <= maximum,
            "missing/unsafe source or journal")
    require(re.fullmatch(r"[0-9a-f]{64}", expected or "") is not None
            and file_sha(p) == expected, "externally pinned raw byte SHA drift")
    return json.loads(p.read_bytes(), object_pairs_hook=no_dupes,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def create_once(path, record):
    path = Path(path)
    require(not path.exists() and not path.is_symlink(), "create-only experiment output")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as out:
        out.write(canonical(record))
        out.flush()
        os.fsync(out.fileno())
    return file_sha(path)


def append_once(path, record):
    path = Path(path)
    with path.open("ab") as out:
        out.write(canonical(record))
        out.flush()
        os.fsync(out.fileno())


def read_journal(path):
    p = Path(path)
    require(p.is_file() and not p.is_symlink() and p.stat().st_size < 16_000_000,
            "missing raw attempt journal")
    raw = p.read_bytes()
    require(raw.endswith(b"\n"), "incomplete JSONL line")
    return [json.loads(z, object_pairs_hook=no_dupes) for z in raw.splitlines()]


def empty_evidence_prompt(question):
    # Same system policy as original precommitted research Reader, zero sources.
    return ("<|im_start|>system\nAnswer only from the provided evidence. "
            "If insufficient evidence, say unknown. Cite [E1], [E2].<|im_end|>\n"
            f"<|im_start|>user\nQuestion: {question}<|im_end|>\n"
            "<|im_start|>assistant\n")


def render(question, ids, sources):
    if not ids:
        return empty_evidence_prompt(question)
    return format_archived_chat(question, [sources[s]["text"] for s in ids])


def select_cases(public, rank, annotations, tokenizer, *, candidate_whitelist=None, per_family=3):
    """Only original publisher support IDs may enter upper-bound evidence.

    No actual answers, categories, independently judged truth, or gold answer
    text is received. All four heldout source families are represented.
    """
    require(public.get("gold_included") is False and
            public.get("production_accepted") is False and
            len(public.get("sources", {})) == 10 and len(public.get("cases", [])) == 1986,
            "not complete original label-blind source snapshot")
    require(len(rank.get("predictions", [])) == 1986 and
            rank.get("ranking_publisher_gold_opened") is False and
            rank.get("production_accepted") is False,
            "rank not original label-blind source-only census")
    require(annotations.get("production_accepted") is False and
            annotations.get("public_sha256") == PUBLIC_SHA and
            annotations.get("heldout_source_families") == 4,
            "publisher witness not independently segregated")
    by_rank = {x["case_id"]: x for x in rank["predictions"]}
    by_weak = {x["case_id"]: x for x in annotations["targets"]}
    require(len(by_rank) == 1986 and len(by_weak) == 829,
            "missing or duplicated source-only rank or publisher witnesses")
    chosen = []
    for fam in FAMILIES:
        sources = {s["id"]: s for s in public["sources"][fam]}
        options = []
        for case in public["cases"]:
            if case["family"] != fam:
                continue
            cid = case["case_id"]
            if candidate_whitelist is not None and cid not in candidate_whitelist:
                continue
            if cid not in by_weak or cid not in by_rank:
                continue
            witness = by_weak[cid]["publisher_support"]
            if (len(witness) != 1 or witness[0] not in sources
                    or by_weak[cid]["unresolved_original_annotations"]):
                continue
            support = witness[0]
            bm25 = by_rank[cid]["selected"]["bm25"]
            if support in bm25 or len(bm25) != 3 or len(set(bm25)) != 3:
                continue
            # Full original inventory, no source truncation, and exclude the
            # publisher witness from the entire ordinary retrieval arm.
            seeds = bm25
            non = [s for s in seeds if s != support]
            # A fourth ORIGINAL nonwitness is selected from lexical BM25 seeds
            # stored in the public rank census's original top16 if available;
            # where only Top3 is sealed, take a stable next source by source ID.
            extras = [s for s in sorted(sources) if s not in set(seeds) | {support}]
            if not extras:
                continue
            arm_sources = {
                "no_evidence": [],
                "original_bm25_top3": seeds,
                "publisher_annotated_witness": [support, non[0], non[1]],
                "publisher_witness_lesion": [non[0], non[1], extras[0]],
            }
            ids = set(s for v in arm_sources.values() for s in v)
            if any(len(sources[s]["text"].encode()) > 640 for s in ids):
                continue
            requests = {}
            for arm in ARMS:
                prompt = render(case["question"], arm_sources[arm], sources)
                seq = tokenizer.encode(prompt)
                if not seq or len(seq) + MAX_NEW > MAX_CONTEXT:
                    break
                requests[arm] = {"sources": arm_sources[arm],
                                 "prompt": prompt,
                                 "prompt_sha256": hash_bytes(prompt.encode()),
                                 "input_tokens": len(seq),
                                 "input_ids_sha256": sha(seq)}
            if len(requests) != len(ARMS):
                continue
            require(by_rank[cid]["question_sha256"] == case["question_sha256"],
                    "original question changed after model source ranking")
            options.append({"case_id": cid, "family": fam,
                            "question_sha256": case["question_sha256"],
                            "publisher_weak_source_id": support,
                            "requests": requests})
        options.sort(key=lambda c: (hash_bytes(("precommit-sufficiency-v1|" + c["case_id"]).encode()),
                                     c["case_id"]))
        require(len(options) >= per_family, "insufficient eligible original cases")
        chosen.extend(options[:per_family])
    chosen.sort(key=lambda c: (c["family"], c["case_id"]))
    return chosen


def make_plan(public, pub_sha, rank, rank_sha, weak, weak_sha, tokenizer, *,
              candidate_whitelist=None):
    require(pub_sha == PUBLIC_SHA and re.fullmatch(r"[0-9a-f]{64}", rank_sha or "")
            and re.fullmatch(r"[0-9a-f]{64}", weak_sha or ""),
            "original external source pins required")
    stress = candidate_whitelist is not None
    per_family = 2 if stress else MAX_CASES_PER_FAMILY
    cases = select_cases(public, rank, weak, tokenizer,
                         candidate_whitelist=candidate_whitelist, per_family=per_family)
    plan = {"profile": PROFILE, "public_sha256": pub_sha,
            "rank_sha256": rank_sha, "publisher_source_annotation_sha256": weak_sha,
            "reader_sha256": WEIGHT_SHA256, "tokenizer_sha256": TOKENIZER_SHA,
            "max_new_tokens": MAX_NEW, "families": list(FAMILIES),
            "arms": list(ARMS), "cases": cases,
            "publisher_support_not_independent_human_review": True,
            "publisher_answer_text_ever_seen_during_prepare": stress,
            "independent_future_windows": 0, "production_accepted": False}
    if stress:
        plan["cases_per_family"] = per_family
        plan["publisher_answer_used_for_stress_cohort_selection"] = True
    validate_plan(plan, tokenizer)
    return plan


def validate_plan(plan, tokenizer):
    require(plan.get("profile") == PROFILE and plan.get("arms") == list(ARMS)
            and plan.get("families") == list(FAMILIES)
            and plan.get("reader_sha256") == WEIGHT_SHA256
            and plan.get("tokenizer_sha256") == TOKENIZER_SHA
            and plan.get("public_sha256") == PUBLIC_SHA
            and plan.get("max_new_tokens") == MAX_NEW
            and plan.get("publisher_support_not_independent_human_review") is True
            and plan.get("publisher_answer_text_ever_seen_during_prepare") is
                plan.get("publisher_answer_used_for_stress_cohort_selection", False)
            and plan.get("independent_future_windows") == 0
            and plan.get("production_accepted") is False,
            "original model/issuer/negative-authority drift")
    cases = plan.get("cases")
    per_family = plan.get("cases_per_family", MAX_CASES_PER_FAMILY)
    require(per_family == (2 if plan.get("publisher_answer_used_for_stress_cohort_selection", False)
                           else MAX_CASES_PER_FAMILY), "invalid precommitted cohort size")
    require(isinstance(cases, list) and len(cases) == len(FAMILIES) * per_family,
            "missing original Reader cohort")
    groups = Counter(x["family"] for x in cases)
    require(groups == {f: per_family for f in FAMILIES}
            and len({x["case_id"] for x in cases}) == len(cases),
            "duplicate or omitted case/family")
    for c in cases:
        require(set(c) == {"case_id", "family", "question_sha256",
                          "publisher_weak_source_id", "requests"}
                and set(c["requests"]) == set(ARMS),
                "original case/arm shape mismatch")
        source = c["publisher_weak_source_id"]
        oracle = c["requests"]["publisher_annotated_witness"]["sources"]
        ablated = c["requests"]["publisher_witness_lesion"]["sources"]
        baseline = c["requests"]["original_bm25_top3"]["sources"]
        require(c["requests"]["no_evidence"]["sources"] == [] and
                len(oracle) == len(ablated) == len(baseline) == 3 and
                source == oracle[0] and source not in baseline and source not in ablated
                and oracle[1:] == ablated[:2] and len(set(ablated)) == 3,
                "support manipulation incorrect or publisher source leaked")
        for arm in ARMS:
            row = c["requests"][arm]
            require(set(row) == {"sources", "prompt", "prompt_sha256",
                                  "input_tokens", "input_ids_sha256"}
                    and isinstance(row["prompt"], str)
                    and hash_bytes(row["prompt"].encode()) == row["prompt_sha256"],
                    "question/answer prompt mutation")
            toks = tokenizer.encode(row["prompt"])
            require(len(toks) == row["input_tokens"]
                    and sha(toks) == row["input_ids_sha256"]
                    and 0 < len(toks) <= MAX_CONTEXT - MAX_NEW,
                    "original tokenizer or input budget drift")
    return len(cases) * len(ARMS)



def original_verbatim_ids(public, weak, original_corpus, *, expected_original_sha256):
    """Explicit posthoc answer-based capacity-stress cohort, NOT causal selection.

    This function can inspect publisher answers only at PREPARE-VERBATIM stage.
    Only qualifying CASE IDs reach Reader dispatch, not original gold fields.
    Reader is NEVER told the answer or gold-based selection metadata.
    """
    require(expected_original_sha256 == DATA_SHA, "original publisher corpus pin drift")
    originals = {str(r["sample_id"]): r for r in original_corpus}
    require(set(originals) == set(public["sources"]), "unregistered publisher source family")
    cases = {r["case_id"]: r for r in public["cases"]}
    matched = set()
    for row in weak["targets"]:
        case_id = row["case_id"]
        if case_id not in cases or len(row["publisher_support"]) != 1 or row["unresolved_original_annotations"]:
            continue
        case = cases[case_id]
        family = case["family"]
        if family not in FAMILIES:
            continue
        original = originals[family]["qa"][int(case_id.rsplit(":", 1)[1])]
        if not ("answer" in original and "adversarial_answer" not in original
                and hash_bytes(original["question"].encode()) == case["question_sha256"]):
            continue
        answer = str(original["answer"]).strip().casefold()
        # Reject trivial yes/no and 1-3 character substring accidents.
        if len(answer) < 4 or answer in ("yes", "no", "true", "false"):
            continue
        sources = {s["id"]: s for s in public["sources"][family]}
        support = sources.get(row["publisher_support"][0])
        if support is not None and answer in support["text"].casefold():
            matched.add(case_id)
    return matched


def original_generate(plan, tokenizer, reader, output_dir, *, expected_plan_sha256):
    require(sha(plan) == expected_plan_sha256, "original plan external precommit drift")
    validate_plan(plan, tokenizer)
    folder = Path(output_dir)
    require(not folder.exists() and not folder.is_symlink(), "create-only Reader run directory")
    folder.mkdir(parents=True, mode=0o700)
    starts, responses, statuses = (folder / f for f in
                                  ("starts.jsonl", "raw_answers.jsonl", "statuses.jsonl"))
    for p in (starts, responses, statuses):
        p.touch(exist_ok=False)
    ordinal = 0
    successes, failures = 0, 0
    for case in plan["cases"]:
        for arm in ARMS:
            req = case["requests"][arm]
            key = case["case_id"] + "/" + arm
            record = {"index": ordinal, "key": key, "request_sha256": sha(req),
                      "reader_sha256": WEIGHT_SHA256}
            append_once(starts, record)
            try:
                seq = tokenizer.encode(req["prompt"])
                require(sha(seq) == req["input_ids_sha256"], "request token drift")
                ids = reader.generate(seq, max_new_tokens=MAX_NEW)
                require(isinstance(ids, list) and 1 <= len(ids) <= MAX_NEW
                        and all(type(k) is int and 0 <= k < 49152 for k in ids),
                        "original reader invalid token output")
                output = tokenizer.decode(ids)
                response = {**record, "raw_output": output, "generated_ids": ids,
                            "output_sha256": hash_bytes(output.encode()),
                            "token_ids_sha256": sha(ids),
                            "input_tokens": len(seq), "output_tokens": len(ids)}
                append_once(responses, response)
                append_once(statuses, {**record, "status": "success"})
                successes += 1
            except Exception as error:
                # Never replace a failed invocation with a fabricated answer.
                append_once(statuses, {**record, "status": "failed",
                                       "error_type": type(error).__name__})
                failures += 1
            ordinal += 1
            if ordinal % 4 == 0:
                print(f"real_reader_attempts={ordinal}; successes={successes}; failures={failures}", flush=True)
    summary = {"profile": PROFILE + ".original-answers.v1",
               "plan_sha256": expected_plan_sha256,
               "reader_sha256": WEIGHT_SHA256,
               "tokenizer_sha256": TOKENIZER_SHA,
               "attempts": ordinal, "successes": successes, "failures": failures,
               "starts_sha256": file_sha(starts),
               "responses_sha256": file_sha(responses),
               "statuses_sha256": file_sha(statuses),
               "production_accepted": False, "original_reader_not_hf_parity_qualified": True}
    # A complete journal with failed calls is still useful, never labeled success.
    seal = create_once(folder / "seal.json", summary)
    return {"seal_sha256": seal, **summary}


def recount(plan, directory, tokenizer, expected_plan_sha256, expected_seal_sha256):
    require(sha(plan) == expected_plan_sha256, "external plan changed")
    validate_plan(plan, tokenizer)
    folder = Path(directory)
    seal = pinned(folder / "seal.json", expected_seal_sha256)
    require(seal["plan_sha256"] == expected_plan_sha256 and
            seal["reader_sha256"] == WEIGHT_SHA256 and
            seal["tokenizer_sha256"] == TOKENIZER_SHA and
            seal["production_accepted"] is False,
            "original reader material or plan identity drift")
    paths = {k: folder / k for k in ("starts.jsonl", "raw_answers.jsonl", "statuses.jsonl")}
    require(seal["starts_sha256"] == file_sha(paths["starts.jsonl"]) and
            seal["responses_sha256"] == file_sha(paths["raw_answers.jsonl"]) and
            seal["statuses_sha256"] == file_sha(paths["statuses.jsonl"]),
            "original file journals modified since complete seal")
    starts = read_journal(paths["starts.jsonl"])
    answers = read_journal(paths["raw_answers.jsonl"])
    statuses = read_journal(paths["statuses.jsonl"])
    expected = [(i, c, arm) for i, (c, arm) in enumerate(
        (c, arm) for c in plan["cases"] for arm in ARMS)]
    require(len(starts) == len(statuses) == len(expected) == seal["attempts"],
            "omitted or duplicated starts and statuses")
    response_by = {}
    for r in answers:
        require(r["index"] not in response_by, "repeated model answer")
        response_by[r["index"]] = r
    for index, case, arm in expected:
        base = {"index": index, "key": case["case_id"] + "/" + arm,
                "request_sha256": sha(case["requests"][arm]),
                "reader_sha256": WEIGHT_SHA256}
        require(starts[index] == base, "start sequence or model request changed")
        status = statuses[index]
        require(all(status.get(k) == v for k, v in base.items())
                and status.get("status") in ("success", "failed"),
                "invalid attempt status")
        row = response_by.get(index)
        if status["status"] == "failed":
            require(row is None and isinstance(status.get("error_type"), str),
                    "failed Reader attempt concealed by answer")
            continue
        require(row is not None and all(row.get(k) == v for k, v in base.items()),
                "missing or foreign original model answer")
        ids = row["generated_ids"]
        require(isinstance(ids, list) and 1 <= len(ids) <= MAX_NEW and
                all(type(k) is int and 0 <= k < 49152 for k in ids) and
                row["raw_output"] == tokenizer.decode(ids) and
                row["token_ids_sha256"] == sha(ids) and
                row["output_sha256"] == hash_bytes(row["raw_output"].encode())
                and row["input_tokens"] == case["requests"][arm]["input_tokens"]
                and row["output_tokens"] == len(ids),
                "original Reader answer Token IDs, source, or cost altered")
    require(sum(s["status"] == "success" for s in statuses) == seal["successes"]
            and sum(s["status"] == "failed" for s in statuses) == seal["failures"]
            and len(answers) == seal["successes"],
            "failed or missing original Reader calls silently dropped")
    return {r["index"]: r for r in answers}


def score(plan, answers, publisher, raw_corpus, *, expected_corpus_sha256):
    require(expected_corpus_sha256 == DATA_SHA, "original publisher dataset SHA drift")
    samples = {str(z["sample_id"]): z for z in raw_corpus}
    weak = {x["case_id"]: x for x in publisher["targets"]}
    by_arm = defaultdict(Counter)
    by_fam = defaultdict(lambda: defaultdict(Counter))
    cohort = Counter()
    support_verbatim = Counter()
    pairwise_changed = Counter()
    case_rows = []
    for index, case, arm in ((index, case, arm) for index, case, arm in
                             ((i, c, arm) for i, (c, arm) in enumerate(
                                 (c, arm) for c in plan["cases"] for arm in ARMS))):
        qa = samples[case["family"]]["qa"][int(case["case_id"].rsplit(":", 1)[1])]
        require(hash_bytes(qa["question"].encode()) == case["question_sha256"],
                "original question/corpus target mismatch")
        require(weak[case["case_id"]]["publisher_support"] ==
                [case["publisher_weak_source_id"]],
                "original publisher witness changed after plan freeze")
        response = answers.get(index)
        label_class = "adversarial" if "adversarial_answer" in qa else "ordinary"
        value = qa.get("adversarial_answer" if label_class == "adversarial" else "answer")
        # No string equivalence implies independent semantic task adjudication.
        gold = str(value).strip().casefold() if value is not None else ""
        literal = int(response is not None and bool(gold)
                      and response["raw_output"].strip().casefold() == gold)
        substring = int(response is not None and bool(gold)
                        and gold in response["raw_output"].casefold())
        unknown_marker = int(response is not None and
                             "unknown" in response["raw_output"].casefold())
        hit_output_ceiling = int(response is not None and
                                 len(response["generated_ids"]) == MAX_NEW)
        support = case["publisher_weak_source_id"]
        ids = case["requests"][arm]["sources"]
        hit = int(support in ids)
        completed = int(response is not None)
        sample = {"case_id": case["case_id"], "family": case["family"],
                  "arm": arm, "answer_class": label_class,
                  "weak_support_hit": hit, "strict_literal": literal,
                  "publisher_answer_substring_proxy": substring,
                  "contains_literal_unknown_marker": unknown_marker,
                  "output_ceiling_reached": hit_output_ceiling,
                  "completed": completed,
                  "input_tokens": case["requests"][arm]["input_tokens"],
                  "output_tokens": response["output_tokens"] if response else 0}
        case_rows.append(sample)
        by_arm[arm].update({"questions": 1, "completed": completed,
                           "weak_support_hit": hit, "strict_literal": literal,
                           "publisher_answer_substring_proxy": substring,
                           "contains_literal_unknown_marker": unknown_marker,
                           "output_ceiling_reached": hit_output_ceiling,
                           "input_tokens": sample["input_tokens"],
                           "output_tokens": sample["output_tokens"]})
        by_fam[case["family"]][arm].update({"questions": 1, "completed": completed,
                                              "weak_support_hit": hit,
                                              "strict_literal": literal,
                                              "publisher_answer_substring_proxy": substring})
        cohort["ordinary"] += int(arm == ARMS[0] and label_class == "ordinary")
        cohort["adversarial"] += int(arm == ARMS[0] and label_class == "adversarial")
    for case in plan["cases"]:
        original = samples[case["family"]]["qa"][int(case["case_id"].rsplit(":", 1)[1])]
        answer = original.get("answer")
        support = case["publisher_weak_source_id"]
        source_text = next((z["text"] for z in raw_corpus_sources(samples[case["family"]])
                            if z["id"] == support), "")
        if answer is not None:
            support_verbatim["ordinary_questions"] += 1
            support_verbatim["gold_literal_in_original_witness"] += int(
                bool(str(answer).strip()) and str(answer).casefold() in source_text.casefold())
    out = {"profile": PROFILE + ".postseal-diagnostic.v1",
           "cohort_questions": len(plan["cases"]),
           "source_family_roots": list(FAMILIES),
           "answer_classes": dict(cohort),
           "observed_arm_aggregates": {a: dict(by_arm[a]) for a in ARMS},
           "by_family": {f: {a: dict(by_fam[f][a]) for a in ARMS} for f in FAMILIES},
           "publisher_oracle_witness_verbatim_ordinary": dict(support_verbatim),
           "experimental_decisions": {
                "reader_sufficiency_human_verified": False,
                "publisher_proxy_evidence_may_be_insufficient": True,
                "independent_semantic_correctness": None,
                "substring_proxy_not_semantic_correctness": True,
                "reader_replaced_by_stronger_model": False,
                "trained_memorycell_task_gain": None,
                "true_future_calendar_windows": 0,
                "production_accepted": False},
           "publisher_answer_read_only_after_reader_seal": not plan.get("publisher_answer_used_for_stress_cohort_selection", False),
           "publisher_answer_used_for_stress_cohort_selection":
               plan.get("publisher_answer_used_for_stress_cohort_selection", False),
           "publisher_answer_never_in_model_prompt": True}
    return out


def raw_corpus_sources(sample):
    rows = []
    for session in sample["conversation"]:
        if not session.startswith("session_") or not session[8:].isdigit():
            continue
        for turn in sample["conversation"][session]:
            rows.append({"id": turn["dia_id"], "text": turn.get("speaker", "") + ": " + turn.get("text", "")})
    return rows


def main():
    c = argparse.ArgumentParser(description=__doc__)
    sub = c.add_subparsers(dest="phase", required=True)
    p = sub.add_parser("prepare")
    for a in ("public", "rank", "weak", "reader"):
        p.add_argument("--" + a, required=True)
    p.add_argument("--public-sha", required=True)
    p.add_argument("--rank-sha", required=True)
    p.add_argument("--weak-sha", required=True)
    p.add_argument("--plan-out", required=True)
    p = sub.add_parser("prepare-verbatim")
    for a in ("public", "rank", "weak", "reader", "original"):
        p.add_argument("--" + a, required=True)
    p.add_argument("--public-sha", required=True)
    p.add_argument("--rank-sha", required=True)
    p.add_argument("--weak-sha", required=True)
    p.add_argument("--plan-out", required=True)
    p = sub.add_parser("run")
    for a in ("plan", "reader", "output"):
        p.add_argument("--" + a, required=True)
    p.add_argument("--plan-sha", required=True)
    p = sub.add_parser("score")
    for a in ("plan", "journal", "reader", "weak", "original", "out"):
        p.add_argument("--" + a, required=True)
    for a in ("plan-sha", "seal-sha", "weak-sha"):
        p.add_argument("--" + a, required=True)
    v = c.parse_args()
    if v.phase in ("prepare", "prepare-verbatim"):
        tokenizer = ArchivedByteLevelBPE(Path(v.reader), expected_tokenizer_sha256=TOKENIZER_SHA)
        pub = pinned(v.public, v.public_sha)
        rank = pinned(v.rank, v.rank_sha)
        weak = pinned(v.weak, v.weak_sha)
        selected = None
        if v.phase == "prepare-verbatim":
            require(file_sha(v.original) == DATA_SHA, "original corpus SHA invalid")
            original = json.loads(Path(v.original).read_bytes())
            selected = original_verbatim_ids(pub, weak, original,
                                             expected_original_sha256=DATA_SHA)
        plan = make_plan(pub, v.public_sha, rank, v.rank_sha, weak, v.weak_sha,
                         tokenizer, candidate_whitelist=selected)
        print("original_reader_plan_sha256=" + create_once(v.plan_out, plan))
    elif v.phase == "run":
        tokenizer = ArchivedByteLevelBPE(Path(v.reader), expected_tokenizer_sha256=TOKENIZER_SHA)
        plan = pinned(v.plan, v.plan_sha)
        model = ArchivedLlama(Path(v.reader), expected_sha256=WEIGHT_SHA256)
        print(json.dumps(original_generate(plan, tokenizer, model, v.output,
                                           expected_plan_sha256=sha(plan)), sort_keys=True))
    else:
        tokenizer = ArchivedByteLevelBPE(Path(v.reader), expected_tokenizer_sha256=TOKENIZER_SHA)
        plan = pinned(v.plan, v.plan_sha)
        answers = recount(plan, v.journal, tokenizer, sha(plan), v.seal_sha)
        weak = pinned(v.weak, v.weak_sha)
        require(file_sha(v.original) == DATA_SHA, "original source gold SHA invalid")
        gold = json.loads(Path(v.original).read_bytes())
        verdict = score(plan, answers, weak, gold, expected_corpus_sha256=DATA_SHA)
        verdict["sealed_plan_sha256"] = v.plan_sha
        verdict["sealed_reader_answer_journal_sha256"] = v.seal_sha
        verdict["publisher_original_sha256"] = DATA_SHA
        print("original_postseal_score_sha256=" + create_once(v.out, verdict))


if __name__ == "__main__":
    main()
