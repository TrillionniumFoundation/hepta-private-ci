"""Original-weight Reader citation grammar study; offline, shadow-only, DENY_ALL.

Four predeclared output grammars share the SAME original publisher source IDs,
source excerpt bytes, question, frozen Reader and 48-token generation ceiling.
No private answer is available to the planning or inference worker. A source
citation label is NOT proof that an answer is entailed by its source.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import json
import math
import re
import sys
import time

import associative_graph_causal as graph
import reader_premise_format as baseline
from associative_question_conditioned import _token_f1
from associative_offline_reader_diagnostic import SYSTEM
from offline_smol_reader import OriginalSmol, verify_files
from reader_weight_transport import verify_reader_transport

SCHEMA = "hepta.reader-citation-grammar.shadow.v1"
ARMS = ("legacy_lines", "citation_first", "citation_last", "two_field")
MAX_TOKENS = baseline.MAX_TOKENS
COUNT = baseline.Q_COUNT * len(ARMS)
CITATIONS = re.compile(r"\[E([1-8])\]")


def _user_text(entry):
    lines = "\n".join(f"[{e['label']}] {e['text']}" for e in entry["evidence"])
    question = entry["question"]
    if entry["arm"] == "legacy_lines":
        return baseline._prompt({**entry, "arm": "annotated_lines"})
    if entry["arm"] == "citation_first":
        rule = (
            "Begin your response with one bracketed source label that occurs in Evidence, "
            "then give a short answer. Do not invent a label. If the evidence is "
            "insufficient, say so without a label."
        )
    elif entry["arm"] == "citation_last":
        rule = (
            "Give a short answer ending with one bracketed source label that occurs "
            "in Evidence. Do not invent a label. If evidence is insufficient, "
            "say so without a label."
        )
    elif entry["arm"] == "two_field":
        rule = (
            "Return two lines only: the first beginning 'Answer:' with your short "
            "answer, and the second beginning 'Source:' with one bracketed "
            "label that occurs in Evidence. If unknown, say insufficient evidence "
            "and do not make up a source label."
        )
    else:
        raise ValueError("unknown citation grammar arm")
    return f"Question: {question}\nEvidence:\n{lines}\nInstruction: {rule}"


def make_plan(original_plan):
    baseline.validate_plan(original_plan)
    source = sorted(
        (r for r in original_plan["entries"] if r["arm"] == "annotated_lines"),
        key=lambda r: (r["family"], r["question_id"]),
    )
    if len(source) != baseline.Q_COUNT:
        raise ValueError("ten fixed original evidence questions required")
    rows = []
    for s in source:
        for arm in ARMS:
            rows.append(
                {
                    "family": s["family"],
                    "question_id": s["question_id"],
                    "question": s["question"],
                    "arm": arm,
                    "evidence": [{**item} for item in s["evidence"]],
                }
            )
    result = {
        "schema": SCHEMA,
        "parent_plan_sha256": graph.digest(graph.canonical(original_plan)),
        "original_source_sha256": graph.DATASET_SHA256,
        "source_annotations_are_not_semantic_sufficiency": True,
        "answers_in_worker": False,
        "production_accepted": False,
        "rows": rows,
    }
    validate(result)
    return result


def validate(value):
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema",
            "parent_plan_sha256",
            "original_source_sha256",
            "source_annotations_are_not_semantic_sufficiency",
            "answers_in_worker",
            "production_accepted",
            "rows",
        }
        or value["schema"] != SCHEMA
        or not re.fullmatch(r"[0-9a-f]{64}", value["parent_plan_sha256"])
        or value["original_source_sha256"] != graph.DATASET_SHA256
        or value["source_annotations_are_not_semantic_sufficiency"] is not True
        or value["answers_in_worker"] is not False
        or value["production_accepted"] is not False
        or not isinstance(value["rows"], list)
        or len(value["rows"]) != COUNT
    ):
        raise ValueError("untrusted citation protocol envelope")
    census = defaultdict(dict)
    for r in value["rows"]:
        if (
            not isinstance(r, dict)
            or set(r) != {"family", "question_id", "question", "arm", "evidence"}
            or r["arm"] not in ARMS
            or not isinstance(r["family"], str)
            or not re.fullmatch(r"conv-\d{1,4}", r["family"])
            or not re.fullmatch(re.escape(r["family"]) + r"/q\d{4}", r["question_id"])
            or not graph.ascii_ok(r["question"])
            or not isinstance(r["evidence"], list)
            or not 1 <= len(r["evidence"]) <= 8
        ):
            raise ValueError("invalid citation protocol row")
        if r["arm"] in census[r["question_id"]]:
            raise ValueError("duplicated citation grammar arm")
        census[r["question_id"]][r["arm"]] = r
        for n, e in enumerate(r["evidence"], 1):
            if (
                not isinstance(e, dict)
                or set(e) != {"label", "source_id", "text"}
                or e["label"] != f"E{n}"
                or not isinstance(e["source_id"], str)
                or not baseline.SOURCE_ID.fullmatch(e["source_id"])
                or not isinstance(e["text"], str)
                or not e["text"].strip()
                or len(e["text"].encode("utf-8")) > 1500
            ):
                raise ValueError("invalid source-bound label")
        if len({e["source_id"] for e in r["evidence"]}) != len(r["evidence"]):
            raise ValueError("duplicate evidence source")
    if len(census) != baseline.Q_COUNT:
        raise ValueError("missing original question groups")
    for byarm in census.values():
        if set(byarm) != set(ARMS):
            raise ValueError("missing citation grammar variant")
        common = [(r["family"], r["question"], r["evidence"]) for r in byarm.values()]
        if any(x != common[0] for x in common):
            raise ValueError("candidate evidence differs by citation format")


def _read_plan(directory):
    root = Path(directory)
    if root.is_symlink() or {p.name for p in root.iterdir()} != {
        "plan.json",
        "seal.json",
    }:
        raise ValueError("plan worker must be restricted to public plan/seal")
    raw = graph.regular_bytes(root / "plan.json", limit=2 * 1024 * 1024)
    val = graph.strict_load(raw)
    seal = graph.strict_load(graph.regular_bytes(root / "seal.json"))
    validate(val)
    if raw != graph.canonical(val) or seal != {
        "schema": SCHEMA,
        "sha256": graph.digest(raw),
        "planned": COUNT,
        "production_accepted": False,
    }:
        raise ValueError("unsealed citation grammar plan")
    return val, seal


def prepare(base_plan_dir, output_dir):
    base, _ = baseline._read_plan(base_plan_dir)
    plan = make_plan(base)
    out = Path(output_dir)
    out.mkdir(exist_ok=False)
    sha = graph.create_only(out / "plan.json", plan)
    seal = {
        "schema": SCHEMA,
        "sha256": sha,
        "planned": COUNT,
        "production_accepted": False,
    }
    graph.create_only(out / "seal.json", seal)
    return seal


def generate(model, row):
    started = time.perf_counter()
    try:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _user_text(row)},
        ]
        ids = model.tokenizer.encode(model.tokenizer.render(messages))
        if not 1 <= len(ids) <= 2048 or len(ids) + MAX_TOKENS > 8192:
            return {
                "status": "unavailable",
                "reason": "input_budget",
                "input_tokens": len(ids),
            }
        output = model.generate(ids, maximum=MAX_TOKENS)
        answer = model.tokenizer.decode(output)
        if not answer.strip():
            return {
                "status": "failed",
                "reason": "empty_output",
                "input_tokens": len(ids),
            }
        return {
            "status": "succeeded",
            "answer": answer,
            "input_tokens": len(ids),
            "generated_tokens": len(output),
            "input_ids_sha256": graph.digest(graph.canonical(ids)),
            "generated_ids_sha256": graph.digest(graph.canonical(output)),
            "model_profile": "original-SmolLM2-135m-fp32-no-HF-parity",
            "seconds": time.perf_counter() - started,
            "answer_postprocessed": False,
        }
    except (ValueError, RuntimeError, IndexError) as exc:
        return {"status": "failed", "reason": type(exc).__name__}


def run(plan_dir, model_dir, out_dir):
    plan, seal = _read_plan(plan_dir)
    verify_reader_transport(model_dir)
    verify_files(model_dir)
    import torch

    torch.set_num_threads(2)
    model = OriginalSmol(model_dir)
    out = Path(out_dir)
    out.mkdir(exist_ok=False)
    rows = []
    for index, entry in enumerate(plan["rows"], 1):
        rows.append(
            {
                "question_id": entry["question_id"],
                "arm": entry["arm"],
                "family": entry["family"],
                "source_ids": [x["source_id"] for x in entry["evidence"]],
                "prompt_sha256": graph.digest(_user_text(entry).encode()),
                "result": generate(model, entry),
            }
        )
        if index % 10 == 0:
            print(
                f"citation grammar generation {index}/{COUNT}",
                file=sys.stderr,
                flush=True,
            )
    model.verify_frozen()
    digest = graph.create_only(out / "journal.json", rows)
    output = {
        "schema": SCHEMA,
        "plan_sha256": seal["sha256"],
        "journal_sha256": digest,
        "reader_identity": "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c",
        "reader_parity_certified": False,
        "planned": COUNT,
        "max_generated_tokens": MAX_TOKENS,
        "answers_in_worker": False,
        "production_accepted": False,
    }
    graph.create_only(out / "seal.json", output)
    return output


def _read_journal(plan, seal, run_dir):
    root = Path(run_dir)
    raw = graph.regular_bytes(root / "journal.json", limit=8 * 1024 * 1024)
    rows = graph.strict_load(raw)
    runseal = graph.strict_load(graph.regular_bytes(root / "seal.json"))
    expected = {
        "schema": SCHEMA,
        "plan_sha256": seal["sha256"],
        "journal_sha256": graph.digest(raw),
        "reader_identity": "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c",
        "reader_parity_certified": False,
        "planned": COUNT,
        "max_generated_tokens": MAX_TOKENS,
        "answers_in_worker": False,
        "production_accepted": False,
    }
    if runseal != expected or not isinstance(rows, list) or len(rows) != COUNT:
        raise ValueError("untrusted original citation output")
    inputs = {(x["question_id"], x["arm"]): x for x in plan["rows"]}
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "question_id",
            "arm",
            "family",
            "source_ids",
            "prompt_sha256",
            "result",
        }:
            raise ValueError("unknown original result fields")
        key = (row["question_id"], row["arm"])
        if key in seen or key not in inputs:
            raise ValueError("missing or duplicated original condition")
        seen.add(key)
        src = inputs[key]
        if (
            row["family"] != src["family"]
            or row["source_ids"] != [x["source_id"] for x in src["evidence"]]
            or row["prompt_sha256"] != graph.digest(_user_text(src).encode())
        ):
            raise ValueError("prompt or source lineage drift")
        result = row["result"]
        if not isinstance(result, dict) or result.get("status") not in (
            "succeeded",
            "failed",
            "unavailable",
        ):
            raise ValueError("unknown Reader state")
        if result["status"] == "succeeded" and (
            not isinstance(result.get("answer"), str)
            or not result["answer"].strip()
            or result.get("answer_postprocessed") is not False
        ):
            raise ValueError("invalid original language answer")
    if seen != set(inputs):
        raise ValueError("missing planned Reader prompt")
    return rows, runseal


def review(
    base_plan_dir,
    plan_dir,
    run_dir,
    reader_dir,
    original_dataset,
    public_dir,
    rank_dir,
    output_dir,
):
    plan, seal = _read_plan(plan_dir)
    base, _ = baseline._read_plan(base_plan_dir)
    rebuilt = make_plan(base)
    if plan != rebuilt:
        raise ValueError("derived plan no longer matches fixed original source plan")
    rows, runseal = _read_journal(plan, seal, run_dir)
    verify_reader_transport(reader_dir)
    verify_files(reader_dir)
    import torch

    torch.set_num_threads(2)
    reader = OriginalSmol(reader_dir)
    expected = {(e["question_id"], e["arm"]): e for e in plan["rows"]}
    for n, row in enumerate(rows, 1):
        original = expected[(row["question_id"], row["arm"])]
        replay = generate(reader, original)
        supplied = row["result"]
        keys = set(replay) | set(supplied)
        keys.discard("seconds")
        if any(replay.get(k) != supplied.get(k) for k in keys):
            raise ValueError("original Reader tokens changed across clean processes")
        if n % 10 == 0:
            print(
                f"citation grammar independent replay {n}/{COUNT}",
                file=sys.stderr,
                flush=True,
            )
    reader.verify_frozen()
    # The entire publisher dataset is introduced strictly after actual model replay.
    corpus = baseline._original(original_dataset)
    canonical = baseline.make_plan(public_dir, rank_dir, corpus)
    if canonical != base:
        raise ValueError("original publisher evidence/question source drift")
    published = {
        f"{entry['sample_id']}/q{i:04d}": q.get("answer")
        for entry in corpus
        for i, q in enumerate(entry["qa"])
    }
    totals = {arm: Counter() for arm in ARMS}
    scores = defaultdict(list)
    by_q = defaultdict(dict)
    for row in rows:
        arm = row["arm"]
        result = row["result"]
        stats = totals[arm]
        stats["planned"] += 1
        stats[result["status"]] += 1
        if result["status"] != "succeeded":
            continue
        response = result["answer"]
        matches = [f"E{v}" for v in CITATIONS.findall(response)]
        allowed = {f"E{i}" for i in range(1, len(row["source_ids"]) + 1)}
        stats["any_citation"] += int(bool(matches))
        stats["all_citations_delivered"] += int(
            bool(matches) and all(v in allowed for v in matches)
        )
        stats["invalid_citations"] += int(any(v not in allowed for v in matches))
        stats["starts_with_citation"] += int(
            bool(re.match(r"^\s*\[E[1-8]\]", response))
        )
        stats["input_tokens"] += result["input_tokens"]
        stats["generated_tokens"] += result["generated_tokens"]
        stats["hit_output_ceiling"] += int(result["generated_tokens"] == MAX_TOKENS)
        gold = published.get(row["question_id"])
        if isinstance(gold, str) and gold.strip():
            score = _token_f1(response, gold)
            scores[arm].append(score)
            by_q[row["question_id"]][arm] = score
        else:
            stats["unscorable"] += 1
    comparisons = {}
    for new in ARMS[1:]:
        pairs = [
            (v[new], v["legacy_lines"])
            for v in by_q.values()
            if new in v and "legacy_lines" in v
        ]
        comparisons[new + "_vs_legacy"] = {
            "n": len(pairs),
            "mean_delta": sum(a - b for a, b in pairs) / len(pairs) if pairs else None,
            "gained": sum(a > b for a, b in pairs),
            "lost": sum(a < b for a, b in pairs),
            "tied": sum(a == b for a, b in pairs),
        }
    result = {
        "schema": SCHEMA,
        "source_sha256": graph.DATASET_SHA256,
        "plan_sha256": seal["sha256"],
        "original_reader_sha256": runseal["journal_sha256"],
        "source_groups": 10,
        "planned": COUNT,
        "replayed_model_calls": COUNT,
        "by_arm": {
            a: {
                **dict(totals[a]),
                "scorable": len(scores[a]),
                "mean_token_f1": sum(scores[a]) / len(scores[a]) if scores[a] else None,
            }
            for a in ARMS
        },
        "paired": comparisons,
        "publisher_annotations_not_independent_sufficiency": True,
        "citation_labels_are_not_semantic_entailment": True,
        "model_HF_BF16_parity_certified": False,
        "equal_prompt_token_budget": False,
        "actual_tokens_recorded": True,
        "production_accepted": False,
        "statistical_superiority": False,
    }
    destination = Path(output_dir)
    graph.create_only(destination, result)
    return result


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if len(a) == 3 and a[0] == "prepare":
        output = prepare(a[1], a[2])
    elif len(a) == 4 and a[0] == "run":
        output = run(a[1], a[2], a[3])
    elif len(a) == 9 and a[0] == "review":
        output = review(*a[1:])
    else:
        raise SystemExit(
            "prepare ORIGINAL_PLAN NEW_PLAN | run PLAN READER NEW_OUTPUT | review BASE_PLAN NEW_PLAN SEALED_RUN READER ORIGINAL PUBLIC RANK NEW_REPORT"
        )
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
