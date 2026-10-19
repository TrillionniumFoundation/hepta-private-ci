"""Research-only paired Reader diagnostic with annotation-selected source premises.

IMPORTANT: the source evidence IDs in the 'annotated_all' arm come from hidden
benchmark annotations after ranking was sealed. They are a privileged diagnostic,
NOT a retrieval policy, an independent sufficiency judge, or a memory gain.

The plan producer needs reference annotations. The inference worker receives ONLY
the sealed plan (question + selected source excerpts) and pinned Reader weights.
The reviewer later reopens labels to score sealed, unchanged model outputs.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import hashlib
import json
import os
import re
import sys

from associative_question_conditioned import (
    _answer_with_fixed_reader, _checked_run, _select_reader_questions,
    _token_f1, REGISTERED_READER_IDENTITY,
)
from associative_locomo_shadow import canonical, exclusive, read_regular, strict_json
from associative_cell import sha256

SCHEMA = "hepta.associative-privileged-reader-premise.research.v1"
READER_SCHEMA = "hepta.associative-privileged-reader-execution.research.v1"
ARMS = ("annotated_all", "annotated_minus_one")
PER_FAMILY = 2
MAX_NEW_TOKENS = 48
MAX_PREMISES = 8
MAX_PLAN_BYTES = 512 * 1024


def _validated_annotations(prepared, rank):
    public, meta, _, rank_seal = _checked_run(prepared, rank, reviewer=True)
    path = Path(prepared) / "private.json"
    raw = read_regular(path)
    if sha256(raw) != meta["private_sha256"]:
        raise ValueError("reviewer reference digest mismatch")
    hidden = strict_json(raw)
    if (not isinstance(hidden, dict) or set(hidden) != {"schema", "annotations"}
        or hidden["schema"] != meta["schema"]
        or not isinstance(hidden["annotations"], dict)):
        raise ValueError("unrecognized reviewer annotations")
    expected = {q["id"] for g in public["families"] for q in g["questions"]}
    if set(hidden["annotations"]) != expected:
        raise ValueError("missing or extra reference question")
    return public, meta, rank_seal, hidden["annotations"]


def _make_plan(public, manifest, rank_seal, annotations):
    selected = _select_reader_questions(public, PER_FAMILY)
    entries = []
    supported = 0
    for group in public["families"]:
        family = group["family"]
        source = {d["id"]: d for d in group["sources"]}
        for query in group["questions"]:
            qid = query["id"]
            if qid not in selected:
                continue
            gold = annotations[qid]
            evidence = gold.get("evidence")
            if (not isinstance(evidence, list) or not 1 <= len(evidence) <= MAX_PREMISES
                or any(not isinstance(x, str) or not x for x in evidence)
                or len(set(evidence)) != len(evidence)
                or type(gold.get("unresolved_reference")) is not bool):
                raise ValueError("invalid or unbounded annotated source IDs")
            usable = not gold["unresolved_reference"] and set(evidence) <= set(source)
            supported += int(usable)
            # The removed premise is fixed before any Reader output, and is
            # selected without looking at the answer text or score.
            removed = min(evidence, key=lambda x: (
                hashlib.sha256(("hepta.premise-lesion.v1\0" + qid + "\0" + x).encode()).digest(), x))
            for arm in ARMS:
                ids = (list(evidence) if arm == "annotated_all"
                       else [x for x in evidence if x != removed]) if usable else []
                ex = [dict(label=f"E{i}", source_id=did, source_start=0,
                           text=source[did]["speaker"] + ": " + source[did]["text"][:384])
                      for i, did in enumerate(ids, start=1)]
                entries.append(dict(question_id=qid, family=family, arm=arm,
                    question=query["text"], source_support_complete=usable,
                    source_status="available" if usable else "missing-or-unresolved-annotation",
                    evidence=ex))
    if len(selected) != 20 or len(entries) != 40:
        raise ValueError("incomplete preselected question/arm census")
    return dict(schema=SCHEMA, public_sha256=manifest["public_sha256"],
        source_journal_sha256=rank_seal["journal_sha256"],
        fixed_question_selection="hepta.fixed-reader.v1", per_family=PER_FAMILY,
        arms=list(ARMS), planned_questions=len(selected), planned_attempts=len(entries),
        source_supported_questions=supported, required_source_max=MAX_PREMISES,
        premise_remove_rule="sha256-first-required-source-v1",
        gold_selected_source_ids_used=True, raw_gold_answers_included=False,
        independently_verified_sufficiency=False,
        trainable_memory_utility_comparison=False,
        production_accepted=False, entries=entries)


def make_plan(prepared_dir, run_dir, target_dir):
    public, meta, rank_seal, annotations = _validated_annotations(prepared_dir, run_dir)
    value = _make_plan(public, meta, rank_seal, annotations)
    out = Path(target_dir)
    out.mkdir(exist_ok=False)
    plan_sha = exclusive(out / "plan.json", value)
    seal = dict(schema=SCHEMA, plan_sha256=plan_sha,
                source_journal_sha256=rank_seal["journal_sha256"],
                public_sha256=meta["public_sha256"],
                planned=40, gold_selected_source_ids_used=True,
                gold_answer_bytes_exported=False, production_accepted=False)
    exclusive(out / "seal.json", seal)
    return dict(plan_sha256=plan_sha, source_supported_questions=value["source_supported_questions"],
                planned_questions=20, planned_attempts=40, production_accepted=False)


def _read_plan(plan_dir):
    path = Path(plan_dir)
    if (not path.is_dir() or path.is_symlink()
        or set(p.name for p in path.iterdir()) != {"plan.json", "seal.json"}
        or any(p.is_symlink() for p in path.iterdir())):
        raise ValueError("isolated two-file privileged Reader plan required")
    raw = read_regular(path / "plan.json", maximum=MAX_PLAN_BYTES)
    obj = strict_json(raw)
    seal = strict_json(read_regular(path / "seal.json"))
    if (not isinstance(obj, dict) or obj.get("schema") != SCHEMA
        or not isinstance(seal, dict) or seal.get("schema") != SCHEMA
        or seal.get("plan_sha256") != sha256(raw)
        or seal.get("source_journal_sha256") != obj.get("source_journal_sha256")
        or seal.get("public_sha256") != obj.get("public_sha256")
        or obj.get("arms") != list(ARMS) or obj.get("planned_attempts") != 40
        or obj.get("raw_gold_answers_included") is not False
        or obj.get("gold_selected_source_ids_used") is not True
        or seal.get("gold_answer_bytes_exported") is not False):
        raise ValueError("drifted or unsealed privileged plan")
    entries = obj.get("entries")
    if not isinstance(entries, list) or len(entries) != 40:
        raise ValueError("incomplete privileged Reader plan")
    seen = set()
    grouped = defaultdict(dict)
    for item in entries:
        if (not isinstance(item, dict)
            or set(item) != {"question_id", "family", "arm", "question",
                                "source_support_complete", "source_status", "evidence"}
            or item["arm"] not in ARMS
            or not isinstance(item["question_id"], str)
            or not isinstance(item["family"], str)
            or not isinstance(item["question"], str) or not item["question"].strip()
            or not isinstance(item["evidence"], list)
            or type(item["source_support_complete"]) is not bool):
            raise ValueError("unknown privileged Reader input record")
        key = (item["question_id"], item["arm"])
        if key in seen:
            raise ValueError("duplicate privileged Reader attempt")
        seen.add(key)
        if (not item["source_support_complete"] and item["evidence"]
            or len(item["evidence"]) > MAX_PREMISES
            or any(not isinstance(e, dict) or set(e) != {"label", "source_id", "source_start", "text"}
                   or not isinstance(e["text"], str) or not e["text"]
                   or e["label"] != f"E{i}" or e["source_start"] != 0
                   for i, e in enumerate(item["evidence"], 1))):
            raise ValueError("unbounded, fabricated or mislabeled evidence")
        grouped[item["question_id"]][item["arm"]] = item
    if len(grouped) != 20 or any(set(group) != set(ARMS) for group in grouped.values()):
        raise ValueError("incomplete two-condition paired sample")
    for pair in grouped.values():
        all_evidence = pair["annotated_all"]["evidence"]
        ablated = pair["annotated_minus_one"]["evidence"]
        if pair["annotated_all"]["source_support_complete"]:
            if (len(all_evidence) < 1 or len(ablated) != len(all_evidence) - 1
                or not set(e["source_id"] for e in ablated).issubset(
                    {e["source_id"] for e in all_evidence})):
                raise ValueError("removed condition did not delete exactly one premise")
        elif ablated:
            raise ValueError("unavailable gold leaked into lesioned condition")
    return obj, seal


def run_reader(plan_dir, model_dir, output_dir):
    plan, seal = _read_plan(plan_dir)
    if any((Path(plan_dir) / n).exists() for n in ("private.json", "labels.json", "answers.json")):
        raise ValueError("hidden reference visible to privileged Reader worker")
    from reader_reference import ReferenceReader
    from pretrained import file_inventory
    from native import digest
    model = Path(model_dir)
    if not model.is_dir() or model.is_symlink():
        raise ValueError("pinned Reader directory required")
    if digest(file_inventory(model)) != REGISTERED_READER_IDENTITY:
        raise ValueError("unregistered Reader weights")
    reader = ReferenceReader(model, expected_inventory=REGISTERED_READER_IDENTITY)
    out = Path(output_dir)
    out.mkdir(exist_ok=False)
    records = []
    for entry in plan["entries"]:
        if not entry["source_support_complete"]:
            result = dict(status="unavailable", reason="missing-annotated-source", answer=None)
        else:
            try:
                result = _answer_with_fixed_reader(reader, entry, MAX_NEW_TOKENS)
            except Exception as error:
                result = dict(status="failed", reason=type(error).__name__, answer=None)
        records.append(dict(question_id=entry["question_id"], arm=entry["arm"],
                            family=entry["family"],
                            evidence_ids=[e["source_id"] for e in entry["evidence"]],
                            result=result))
    reader.verify_frozen()
    journal_sha = exclusive(out / "reader-journal.json", records)
    observed = dict(schema=READER_SCHEMA, plan_sha256=seal["plan_sha256"],
                    source_journal_sha256=plan["source_journal_sha256"],
                    reader_journal_sha256=journal_sha, planned=40,
                    per_family=PER_FAMILY, max_new_tokens=MAX_NEW_TOKENS,
                    frozen_reader_identity=reader.identity, frozen_reader_profile=reader.profile,
                    executed_successes=sum(v["result"].get("status") == "succeeded" for v in records),
                    source_unavailable=sum(v["result"].get("reason") == "missing-annotated-source" for v in records),
                    gold_answer_bytes_visible=False,
                    independent_sufficiency_verified=False,
                    production_accepted=False)
    exclusive(out / "reader-seal.json", observed)
    return observed


def review(prepared_dir, public_dir, rank_dir, plan_dir, reader_dir, report_file):
    plan, plan_seal = _read_plan(plan_dir)
    from associative_question_conditioned import _read_public
    public, meta, rank_seal, annotations = _validated_annotations(prepared_dir, rank_dir)
    published, published_meta = _read_public(public_dir)
    if canonical(published) != canonical(public) or published_meta["public_sha256"] != meta["public_sha256"]:
        raise ValueError("reader-public source differs from trusted reference")
    actual = _make_plan(public, meta, rank_seal, annotations)
    if canonical(actual) != read_regular(Path(plan_dir) / "plan.json", maximum=MAX_PLAN_BYTES):
        raise ValueError("privileged plan does not match pinned current annotations")
    original = strict_json(read_regular(Path(reader_dir) / "reader-journal.json"))
    raw_reader = read_regular(Path(reader_dir) / "reader-journal.json")
    rseal = strict_json(read_regular(Path(reader_dir) / "reader-seal.json"))
    if (rseal.get("schema") != READER_SCHEMA
        or rseal.get("plan_sha256") != plan_seal["plan_sha256"]
        or rseal.get("source_journal_sha256") != rank_seal["journal_sha256"]
        or rseal.get("reader_journal_sha256") != sha256(raw_reader)
        or rseal.get("gold_answer_bytes_visible") is not False
        or rseal.get("planned") != 40
        or rseal.get("frozen_reader_identity") != REGISTERED_READER_IDENTITY
        or rseal.get("production_accepted") is not False):
        raise ValueError("unsealed or label-exposed privileged reader result")
    expected = {(e["question_id"], e["arm"]):e for e in plan["entries"]}
    if not isinstance(original, list) or len(original) != len(expected):
        raise ValueError("incomplete scored Reader attempts")
    seen=set();scores=defaultdict(list);statuses=defaultdict(lambda:defaultdict(int))
    by_question=defaultdict(dict)
    for record in original:
        if (not isinstance(record,dict)
            or set(record) != {"question_id", "arm", "family", "evidence_ids", "result"}):
            raise ValueError("foreign privileged Reader result")
        key = record["question_id"], record["arm"]
        if key not in expected or key in seen:
            raise ValueError("missing or duplicated privileged Reader response")
        seen.add(key)
        e=expected[key]
        if (record["family"] != e["family"]
            or record["evidence_ids"] != [s["source_id"] for s in e["evidence"]]):
            raise ValueError("privileged reader source-payload changed")
        r = record["result"]
        if not isinstance(r,dict) or r.get("status") not in ("unavailable","failed","succeeded"):
            raise ValueError("unrecognized reader execution status")
        if r["status"] == "succeeded" and (
            not isinstance(r.get("answer"), str) or not r["answer"].strip()
            or r.get("reader_identity") != REGISTERED_READER_IDENTITY):
            raise ValueError("unverified or empty fixed-reader output")
        statuses[e["arm"]][r["status"]] += 1
        gold=annotations[e["question_id"]].get("answer")
        if r["status"] == "succeeded" and isinstance(gold,str) and gold.strip():
            if not isinstance(r.get("answer"),str) or not r["answer"].strip():
                raise ValueError("missing native language response")
            f1 = _token_f1(r["answer"], gold)
            scores[e["arm"]].append(f1)
            by_question[e["question_id"]][e["arm"]] = f1
        else:
            by_question[e["question_id"]][e["arm"]] = None
    if seen != set(expected):
        raise ValueError("missing Reader arm/question")
    paired=[v["annotated_all"]-v["annotated_minus_one"] for v in by_question.values()
            if v.get("annotated_all") is not None and v.get("annotated_minus_one") is not None]
    report=dict(schema=READER_SCHEMA, plan_sha256=plan_seal["plan_sha256"],
        source_journal_sha256=rank_seal["journal_sha256"],
        by_arm={arm:dict(planned=20, source_supported=plan["source_supported_questions"],
              statuses=dict(statuses[arm]),scored_answers=len(scores[arm]),
              unscored_or_failed=20-len(scores[arm]),
              diagnostic_token_f1_mean=sum(scores[arm])/len(scores[arm]) if scores[arm] else None)
              for arm in ARMS},
        paired_scored_count=len(paired),paired_annotated_minus_lesioned_mean=(
             sum(paired)/len(paired) if paired else None),
        source_supported_questions=plan["source_supported_questions"],
        source_missing_or_unresolved_questions=20-plan["source_supported_questions"],
        gold_selected_sources_are_privileged=True, semantic_sufficiency_certified=False,
        reference_answer_independently_adjudicated=False,
        statistically_significant_superiority=False, production_accepted=False)
    exclusive(report_file,report)
    return report


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    actions=parser.add_subparsers(dest="command",required=True)
    p=actions.add_parser("plan")
    p.add_argument("prepared");p.add_argument("rank");p.add_argument("output")
    p=actions.add_parser("reader")
    p.add_argument("plan");p.add_argument("model");p.add_argument("output")
    p=actions.add_parser("review")
    for arg in ("prepared","public","rank","plan","reader","output"):
        p.add_argument(arg)
    args=parser.parse_args(argv)
    if args.command=="plan": result=make_plan(args.prepared,args.rank,args.output)
    elif args.command=="reader": result=run_reader(args.plan,args.model,args.output)
    else: result=review(args.prepared,args.public,args.rank,args.plan,args.reader,args.output)
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
