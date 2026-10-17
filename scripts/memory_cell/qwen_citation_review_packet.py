"""Sealed, source-preserving Qwen citation review requests; never a review verdict."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from native import digest
from strong_rag_crossrun_audit import SOURCE_PINS, open_sealed, strict_json

ORIGINAL = "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b"
PLAN = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
ARMS = ("selected_k", "hybrid_k4", "single_hop", "entity_time", "organized")
ALL_ARMS = (
    "selected_k",
    "hybrid_k4",
    "hybrid_k6",
    "hybrid_k4_reversed",
    "single_hop",
    "entity_time",
    "organized",
    "program_support",
    "empty",
)
MARKER = re.compile(r"\[(E[1-9][0-9]*)\]")
SCHEMA = "hepta.memory-strong-rag.blind-citation-review-request.v1"


def packet(original: Path, reader: Path, replay: Path) -> dict:
    pin = SOURCE_PINS["A"]
    source = open_sealed(original, ORIGINAL, manifest=True)
    results = open_sealed(reader, pin["full_sha256"], manifest=True)
    review = open_sealed(replay, pin["replay_sha256"], manifest=False)
    if sha256(source["plan/plan.json"]).hexdigest() != PLAN:
        raise ValueError("original plan SHA mismatch")
    if results["tested-commit.txt"].decode().strip() != pin["commit"]:
        raise ValueError("wrong originating reader source commit")
    independent = strict_json(review["shard-replay.json"])
    if (
        independent["generating_commit"] != pin["commit"]
        or independent["model_identity"]
        != "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
        or independent["calibration"]["attempts"] != 40
        or independent["evaluation"]["attempts"] != 72
        or not independent["calibration"]["all_model_calls_succeeded"]
        or not independent["evaluation"]["all_model_calls_succeeded"]
        or independent["production_accepted"] is not False
    ):
        raise ValueError("mechanical independent replay incomplete")
    plan = strict_json(source["plan/plan.json"])
    questions = {q["query"]["identity"]: q["query"] for q in plan["cases"]}
    documents = strict_json(source["plan/source-view.json"])
    docs = {d["identity"]: d for d in documents}
    if len(questions) != 8 or len(documents) != 108 or len(docs) != 108:
        raise ValueError("unregistered original source/test census")
    journal = results["evaluation/raw-answers.jsonl"]
    if not journal.endswith(b"\n"):
        raise ValueError("incomplete original answer journal")
    rows = [strict_json(line) for line in journal.splitlines() if line]
    if (
        len(rows) != 72
        or len({(r["question_id"], r["arm"]) for r in rows}) != 72
        or {(r["question_id"], r["arm"]) for r in rows}
        != {(qid, arm) for qid in questions for arm in ALL_ARMS}
    ):
        raise ValueError("original full nine-arm reader census altered")
    items = []
    for row in rows:
        if row["arm"] not in ARMS:
            continue
        q = questions[row["question_id"]]
        if row["status"] != "succeeded" or not row.get("answer"):
            raise ValueError("unobserved or blank model answer")
        selected = row["selected"]
        evidence = row["receipt"]["delivered_evidence"]
        if len(evidence) != len(selected) or len(set(selected)) != len(selected):
            raise ValueError("original evidence selection drift")
        delivered = []
        for i, (key, entry) in enumerate(zip(selected, evidence, strict=True), 1):
            src = docs[key]
            if (
                entry["original_id"] != key
                or entry["label"] != f"E{i}"
                or entry["excerpt"] != src["content"]
                or entry["source_digest"] != digest(src["content"])
                or entry["root"] != src["root"]
                or entry["scope"] != q["scope"]
                or entry["source_start"] != 0
                or entry["source_end"] != len(src["content"].encode())
            ):
                raise ValueError("delivered source detached from original bytes")
            delivered.append(
                dict(
                    label=entry["label"],
                    original_source_id=key,
                    original_text=entry["excerpt"],
                    original_source_sha256=sha256(
                        entry["excerpt"].encode()
                    ).hexdigest(),
                )
            )
        cited = sorted(set(MARKER.findall(row["answer"])))
        item_id = sha256(
            (pin["commit"] + "\0" + row["question_id"] + "\0" + row["arm"]).encode()
        ).hexdigest()[:24]
        items.append(
            dict(
                review_id=item_id,
                question=q["content"],
                question_time=q["observed_at"],
                original_answer=row["answer"],
                original_sources=delivered,
                cited_labels=cited,
                unknown_citation_labels=sorted(
                    set(cited) - {s["label"] for s in delivered}
                ),
                claim_judgement="unreviewed",
                full_citation_chain_judgement="unreviewed",
            )
        )
    if len(items) != 40 or len({v["review_id"] for v in items}) != 40:
        raise ValueError("review population incomplete")
    return dict(
        schema=SCHEMA,
        origin_commit=pin["commit"],
        original_zip_sha256=ORIGINAL,
        model_zip_sha256=pin["full_sha256"],
        independent_mechanical_replay_zip_sha256=pin["replay_sha256"],
        original_plan_sha256=PLAN,
        review_items=40,
        condition_names_omitted=True,
        expected_answers_omitted=True,
        independent_human_review_performed=False,
        independently_sourced_question_families=False,
        candidate_accepted=False,
        production_accepted=False,
        instructions="Judge entailment and complete citation paths; never infer gold labels.",
        items=sorted(items, key=lambda v: v["review_id"]),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original", "reader", "replay", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    result = packet(args.original, args.reader, args.replay)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(
            result,
            stream,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(dict(review_items=40, production_accepted=False)))


if __name__ == "__main__":
    main()
