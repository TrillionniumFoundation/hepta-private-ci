"""Original-weight Reader sufficiency/format diagnosis on immutable published evidence.

Research SHADOW_ONLY / DENY_ALL. The *privileged* preparer uses publisher
reference SOURCE IDs (not answers), emits only question and bounded source text.
The Reader worker receives neither original archive nor private answers.
Publisher annotations are not independently authenticated sufficient premises.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import json
import math
import re
import sys
import time

import associative_graph_causal as graph
import parametric_stem_reader as stem
import parametric_stem_reader_language as language
from associative_question_conditioned import _token_f1
from associative_offline_reader_diagnostic import SYSTEM, strict_offline_result
from offline_smol_reader import OriginalSmol, verify_files
from reader_weight_transport import verify_reader_transport

SCHEMA = "hepta.reader-premise-format.shadow.v1"
ARMS = ("annotated_json", "removed_json", "annotated_lines", "removed_lines")
MAX_SOURCE_TEXT = 300
MAX_TOKENS = 48
Q_COUNT = 10
PLANNED = len(ARMS) * Q_COUNT
SEED = "hepta.reader-premise-deletion.v1"
MARKERS = re.compile(r"\[E([1-8])\]")
SOURCE_ID = re.compile(r"D\d+:\d+")


def _original(original_path):
    raw = graph.regular_bytes(original_path, limit=8 * 1024 * 1024)
    if graph.digest(raw) != graph.DATASET_SHA256:
        raise ValueError("publisher LoCoMo source digest mismatch")
    original = graph.strict_load(raw)
    if not isinstance(original, list) or len(original) != 10:
        raise ValueError("complete original publisher dialogue corpus required")
    if (
        len({entry.get("sample_id") for entry in original if isinstance(entry, dict)})
        != 10
    ):
        raise ValueError("duplicate original publisher dialogue family")
    return original


def _sources(family):
    if (
        not isinstance(family, dict)
        or not isinstance(family.get("conversation"), dict)
        or not isinstance(family.get("qa"), list)
    ):
        raise ValueError("malformed publisher source family")
    docs = {}
    for name, entries in family["conversation"].items():
        if not re.fullmatch(r"session_\d+", name):
            continue
        if not isinstance(entries, list):
            raise ValueError("malformed publisher session")
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("dia_id"), str)
                or not SOURCE_ID.fullmatch(entry["dia_id"])
                or not isinstance(entry.get("text"), str)
                or not isinstance(entry.get("speaker"), str)
                or entry["dia_id"] in docs
            ):
                raise ValueError("missing, duplicated or malformed publisher source")
            docs[entry["dia_id"]] = entry
    return docs


def _evidence(ids, docs):
    if not isinstance(ids, (list, tuple)) or len(ids) > 8:
        raise ValueError("bounded publisher source list required")
    seen, result = set(), []
    for sid in ids:
        if not isinstance(sid, str) or not SOURCE_ID.fullmatch(sid) or sid not in docs:
            raise ValueError("unresolved or invalid original publisher source ID")
        if sid in seen:
            continue  # publisher annotations sometimes repeat one source ID
        seen.add(sid)
        item = docs[sid]
        text = item["speaker"] + ": " + item["text"][:MAX_SOURCE_TEXT]
        if not text.strip() or len(text.encode("utf-8")) > 1500:
            raise ValueError("out-of-bound publisher source excerpt")
        result.append({"label": f"E{len(result) + 1}", "source_id": sid, "text": text})
    if not result:
        raise ValueError("missing registered publisher evidence")
    return result


def make_plan(public_dir, rank_dir, original):
    """Only privileged trusted-original stage may call this function."""
    rows, rank_seal = language.reader_inputs(public_dir, rank_dir)
    selected = {row["question_id"]: row for row in rows if row["arm"] == "empty"}
    if len(selected) != Q_COUNT or len(rows) != Q_COUNT * len(stem.READER_ARMS):
        raise ValueError("fixed original Reader question identity changed")
    original_map = {entry["sample_id"]: entry for entry in original}
    entries = []
    by_family = Counter()
    for qid, row in sorted(selected.items()):
        family = row["family"]
        if family not in original_map or not qid.startswith(f"{family}/q"):
            raise ValueError("unrecognized original question/family")
        by_family[family] += 1
        source = original_map[family]
        q_num = int(qid.rsplit("/q", 1)[1])
        if q_num >= len(source["qa"]):
            raise ValueError("original publisher question missing")
        q = source["qa"][q_num]
        if (
            not isinstance(q, dict)
            or q.get("question") != row["question"]
            or not isinstance(q.get("evidence"), list)
        ):
            raise ValueError("public question changed relative to publisher")
        evidence = _evidence(q["evidence"], _sources(source))
        distinct_ids = [e["source_id"] for e in evidence]
        # A selected annotation is removed by a fixed question/source ID hash,
        # never using answer text, model predictions, or semantic scoring.
        to_remove = min(
            distinct_ids,
            key=lambda sid: (
                hashlib.sha256((SEED + "\0" + qid + "\0" + sid).encode()).hexdigest(),
                sid,
            ),
        )
        remaining = [e for e in evidence if e["source_id"] != to_remove]
        remaining = [
            {"label": f"E{n}", "source_id": e["source_id"], "text": e["text"]}
            for n, e in enumerate(remaining, 1)
        ]
        for arm in ARMS:
            chosen = evidence if arm.startswith("annotated") else remaining
            entries.append(
                {
                    "family": family,
                    "question_id": qid,
                    "arm": arm,
                    "question": row["question"],
                    "evidence": chosen,
                }
            )
    if (
        len(entries) != PLANNED
        or len(by_family) != Q_COUNT
        or set(by_family.values()) != {1}
    ):
        raise ValueError("publisher annotated question census missing")
    plan = {
        "schema": SCHEMA,
        "public_sha256": rows[0]["public_sha256"],
        "source_rank_sha256": rank_seal["predictions_sha256"],
        "publisher_source_sha256": graph.DATASET_SHA256,
        "oracle_reference_ids_from_publisher": True,
        "oracle_is_not_independent_sufficiency": True,
        "answers_exported": False,
        "production_accepted": False,
        "entries": entries,
    }
    validate_plan(plan)
    return plan


def validate_plan(plan):
    fields = {
        "schema",
        "public_sha256",
        "source_rank_sha256",
        "publisher_source_sha256",
        "oracle_reference_ids_from_publisher",
        "oracle_is_not_independent_sufficiency",
        "answers_exported",
        "production_accepted",
        "entries",
    }
    if (
        not isinstance(plan, dict)
        or set(plan) != fields
        or plan["schema"] != SCHEMA
        or plan["publisher_source_sha256"] != graph.DATASET_SHA256
        or not all(
            isinstance(plan[field], str) and re.fullmatch(r"[0-9a-f]{64}", plan[field])
            for field in ("public_sha256", "source_rank_sha256")
        )
        or plan["oracle_reference_ids_from_publisher"] is not True
        or plan["oracle_is_not_independent_sufficiency"] is not True
        or plan["answers_exported"] is not False
        or plan["production_accepted"] is not False
        or not isinstance(plan["entries"], list)
        or len(plan["entries"]) != PLANNED
    ):
        raise ValueError("untrusted fixed Oracle Reader plan")
    keys, by_question, families = set(), defaultdict(dict), set()
    for row in plan["entries"]:
        if (
            not isinstance(row, dict)
            or set(row) != {"family", "question_id", "arm", "question", "evidence"}
            or not isinstance(row["family"], str)
            or not re.fullmatch(r"conv-\d{1,4}", row["family"])
            or not isinstance(row["question_id"], str)
            or not re.fullmatch(
                re.escape(row["family"]) + r"/q\d{4}", row["question_id"]
            )
            or row["arm"] not in ARMS
            or not isinstance(row["question"], str)
            or not graph.ascii_ok(row["question"])
            or not isinstance(row["evidence"], list)
            or len(row["evidence"]) > 8
        ):
            raise ValueError("invalid oracle Reader input envelope")
        key = (row["question_id"], row["arm"])
        if key in keys:
            raise ValueError("duplicate oracle Reader arm")
        keys.add(key)
        by_question[row["question_id"]][row["arm"]] = row
        families.add(row["family"])
        for n, item in enumerate(row["evidence"], 1):
            if (
                not isinstance(item, dict)
                or set(item) != {"label", "source_id", "text"}
                or item["label"] != f"E{n}"
                or not isinstance(item["source_id"], str)
                or not SOURCE_ID.fullmatch(item["source_id"])
                or not isinstance(item["text"], str)
                or not item["text"].strip()
                or len(item["text"].encode("utf-8")) > 1500
            ):
                raise ValueError("invalid labeled original source excerpt")
        if len({e["source_id"] for e in row["evidence"]}) != len(row["evidence"]):
            raise ValueError("duplicated evidence in the Reader envelope")
    if len(by_question) != Q_COUNT or len(families) != Q_COUNT:
        raise ValueError("expected ten original dialogue families")
    for by_arm in by_question.values():
        if set(by_arm) != set(ARMS):
            raise ValueError("missing one comparison condition")
        complete = by_arm["annotated_json"]["evidence"]
        incomplete = by_arm["removed_json"]["evidence"]
        if (
            not complete
            or by_arm["annotated_lines"]["evidence"] != complete
            or by_arm["removed_lines"]["evidence"] != incomplete
            or len(incomplete) != len(complete) - 1
            or not {e["source_id"] for e in incomplete}
            < {e["source_id"] for e in complete}
        ):
            raise ValueError("premise ablation or presentation axis mismatch")


def _read_plan(directory):
    root = Path(directory)
    if root.is_symlink() or any(
        (root / name).is_symlink() for name in ("plan.json", "seal.json")
    ):
        raise ValueError("plan must not be a symlink")
    if {p.name for p in root.iterdir()} != {"plan.json", "seal.json"}:
        raise ValueError("Reader plan must contain only plan and seal")
    raw = graph.regular_bytes(root / "plan.json", limit=2 * 1024 * 1024)
    plan = graph.strict_load(raw)
    seal = graph.strict_load(graph.regular_bytes(root / "seal.json"))
    validate_plan(plan)
    if (
        graph.canonical(plan) != raw
        or not isinstance(seal, dict)
        or seal
        != {
            "schema": SCHEMA,
            "plan_sha256": graph.digest(raw),
            "planned": PLANNED,
            "answers_in_worker": False,
            "production_accepted": False,
        }
    ):
        raise ValueError("unsealed or changed original Oracle Reader input")
    return plan, seal


def prepare(public_dir, rank_dir, original_path, target_dir):
    original = _original(original_path)
    plan = make_plan(public_dir, rank_dir, original)
    target = Path(target_dir)
    target.mkdir(exist_ok=False)
    digest = graph.create_only(target / "plan.json", plan)
    seal = {
        "schema": SCHEMA,
        "plan_sha256": digest,
        "planned": PLANNED,
        "answers_in_worker": False,
        "production_accepted": False,
    }
    graph.create_only(target / "seal.json", seal)
    return seal


def _prompt(row):
    if row["arm"].endswith("json"):
        # Exact inherited original Reader prompt profile and system message.
        body = json.dumps(
            {
                "question": row["question"],
                "evidence": [
                    {"label": e["label"], "text": e["text"]} for e in row["evidence"]
                ],
            },
            ensure_ascii=False,
        )
    else:
        evidence = "\n".join(f"[{e['label']}] {e['text']}" for e in row["evidence"])
        body = (
            f"Question: {row['question']}\n\nEvidence:\n{evidence or '(no evidence)'}"
            "\n\nAnswer concisely. Include the labels supporting your answer, e.g. [E1]."
            " If necessary information is missing, say you do not have enough evidence."
        )
    return body


def _generate(model, row):
    """Use same SYSTEM and 48-token budget as original JSON baseline."""
    if row["arm"].endswith("json"):
        return strict_offline_result(model, row)
    start = time.perf_counter()
    try:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _prompt(row)},
        ]
        ids = model.tokenizer.encode(model.tokenizer.render(messages))
        if not 1 <= len(ids) <= 2048 or len(ids) + MAX_TOKENS > 8192:
            return {
                "status": "unavailable",
                "reason": "prompt-budget",
                "input_tokens": len(ids),
                "answer": None,
            }
        tokens = model.generate(ids, maximum=MAX_TOKENS)
        answer = model.tokenizer.decode(tokens)
        if not answer.strip():
            return {
                "status": "failed",
                "reason": "empty-generation",
                "answer": None,
                "input_tokens": len(ids),
            }
        return {
            "status": "succeeded",
            "answer": answer,
            "input_tokens": len(ids),
            "generated_tokens": len(tokens),
            "input_ids_sha256": graph.digest(graph.canonical(ids)),
            "generated_ids_sha256": graph.digest(graph.canonical(tokens)),
            "seconds": time.perf_counter() - start,
            "model_profile": "original-fp32-unverified-HF-parity",
            "answer_postprocessed": False,
        }
    except (ValueError, RuntimeError, IndexError) as e:
        return {"status": "failed", "reason": type(e).__name__, "answer": None}


def run(plan_dir, model_dir, output_dir):
    plan, seal = _read_plan(plan_dir)
    if any(
        (Path(plan_dir) / name).exists()
        for name in ("private.json", "answers.json", "locomo.json")
    ):
        raise ValueError("original answers present at Reader boundary")
    transport = verify_reader_transport(model_dir)
    verify_files(model_dir)
    import torch

    torch.set_num_threads(2)
    model = OriginalSmol(model_dir)
    out = Path(output_dir)
    out.mkdir(exist_ok=False)
    rows = []
    for n, entry in enumerate(plan["entries"], 1):
        result = _generate(model, entry)
        rows.append(
            {
                "family": entry["family"],
                "question_id": entry["question_id"],
                "arm": entry["arm"],
                "evidence_ids": [e["source_id"] for e in entry["evidence"]],
                "prompt_sha256": graph.digest(_prompt(entry).encode("utf-8")),
                "result": result,
            }
        )
        if n % 10 == 0:
            print(f"original-source Reader {n}/{PLANNED}", file=sys.stderr, flush=True)
    model.verify_frozen()
    journal_sha = graph.create_only(out / "reader.json", rows)
    run_seal = {
        "schema": SCHEMA,
        "plan_sha256": seal["plan_sha256"],
        "journal_sha256": journal_sha,
        "reader_model_identity": transport["registered_identity"],
        "backend": "original-smol135-fp32-unverified-HF-parity",
        "planned": PLANNED,
        "generation_budget": MAX_TOKENS,
        "publisher_answers_visible": False,
        "independent_semantic_sufficiency": False,
        "production_accepted": False,
    }
    graph.create_only(out / "seal.json", run_seal)
    return run_seal


def _read_journal(plan, plan_seal, results_dir):
    results_dir = Path(results_dir)
    raw = graph.regular_bytes(results_dir / "reader.json", limit=8 * 1024 * 1024)
    rows = graph.strict_load(raw)
    seal = graph.strict_load(graph.regular_bytes(results_dir / "seal.json"))
    if (
        not isinstance(seal, dict)
        or seal
        != {
            "schema": SCHEMA,
            "plan_sha256": plan_seal["plan_sha256"],
            "journal_sha256": graph.digest(raw),
            "reader_model_identity": "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c",
            "backend": "original-smol135-fp32-unverified-HF-parity",
            "planned": PLANNED,
            "generation_budget": MAX_TOKENS,
            "publisher_answers_visible": False,
            "independent_semantic_sufficiency": False,
            "production_accepted": False,
        }
        or not isinstance(rows, list)
        or len(rows) != PLANNED
    ):
        raise ValueError("untrusted or incomplete original Reader output")
    expected = {(x["question_id"], x["arm"]): x for x in plan["entries"]}
    seen = set()
    for item in rows:
        if not isinstance(item, dict) or set(item) != {
            "family",
            "question_id",
            "arm",
            "evidence_ids",
            "prompt_sha256",
            "result",
        }:
            raise ValueError("unregistered Reader result fields")
        key = (item["question_id"], item["arm"])
        if key not in expected or key in seen:
            raise ValueError("Reader row duplicated or not in frozen plan")
        seen.add(key)
        original = expected[key]
        if (
            item["family"] != original["family"]
            or item["evidence_ids"] != [e["source_id"] for e in original["evidence"]]
            or item["prompt_sha256"] != graph.digest(_prompt(original).encode("utf-8"))
        ):
            raise ValueError("Reader prompt/lineage changed")
        res = item["result"]
        if (
            not isinstance(res, dict)
            or res.get("status") not in ("succeeded", "failed", "unavailable")
            or res.get("answer_postprocessed", False) is not False
        ):
            raise ValueError("unregistered reader outcome")
        if res["status"] == "succeeded" and (
            not isinstance(res.get("answer"), str) or not res["answer"].strip()
        ):
            raise ValueError("nonempty original language output required")
    if seen != set(expected):
        raise ValueError("missing frozen Reader arm")
    return rows, seal


def _replay_original(model_dir, plan, rows):
    """Reexecute original model; compare deterministic tokens, not wall-clock fields."""
    verify_reader_transport(model_dir)
    verify_files(model_dir)
    import torch

    torch.set_num_threads(2)
    model = OriginalSmol(model_dir)
    expected = {(x["question_id"], x["arm"]): x for x in plan["entries"]}
    for index, record in enumerate(rows, 1):
        row = expected[(record["question_id"], record["arm"])]
        same = _generate(model, row)
        received = record["result"]
        common = set(same) | set(received)
        common -= {"seconds"}
        if any(same.get(field) != received.get(field) for field in common):
            raise ValueError(
                "original Reader output or token journal mismatch on replay"
            )
        if index % 10 == 0:
            print(
                f"independent original Reader replay {index}/{PLANNED}",
                file=sys.stderr,
                flush=True,
            )
    model.verify_frozen()


def review(
    public_dir, rank_dir, original_path, plan_dir, results_dir, reader_dir, destination
):
    """Regenerate plan and Reader tokens before accessing publisher answer labels."""
    plan, plan_seal = _read_plan(plan_dir)
    original = _original(original_path)  # reviewer-only; parse source, not answer text
    rebuilt = make_plan(public_dir, rank_dir, original)
    if rebuilt != plan or graph.canonical(rebuilt) != graph.regular_bytes(
        Path(plan_dir) / "plan.json"
    ):
        raise ValueError("publisher source and planned premises changed")
    records, seal = _read_journal(plan, plan_seal, results_dir)
    _replay_original(reader_dir, plan, records)
    # Only now read reference *answers* and perform literal token-F1 scoring.
    gold = {
        f"{item['sample_id']}/q{i:04d}": q.get("answer")
        for item in original
        for i, q in enumerate(item["qa"])
    }
    scores, statuses, markers, valid_marker, invalid_marker = (
        defaultdict(list),
        defaultdict(Counter),
        Counter(),
        Counter(),
        Counter(),
    )
    examples = defaultdict(dict)
    for record in records:
        arm = record["arm"]
        result = record["result"]
        status = result["status"]
        statuses[arm][status] += 1
        if status != "succeeded":
            continue
        reply = result["answer"]
        matched = MARKERS.findall(reply)
        markers[arm] += int(bool(matched))
        delivered_labels = {f"E{i}" for i in range(1, len(record["evidence_ids"]) + 1)}
        valid_marker[arm] += int(
            bool(matched) and all(f"E{n}" in delivered_labels for n in matched)
        )
        invalid_marker[arm] += int(
            any(f"E{n}" not in delivered_labels for n in matched)
        )
        answer = gold.get(record["question_id"])
        if isinstance(answer, str) and answer.strip():
            score = _token_f1(reply, answer)
            scores[arm].append(score)
            examples[record["question_id"]][arm] = score
        else:
            statuses[arm]["unscorable_original_reference"] += 1
    pairs = {}
    for full, removed in (
        ("annotated_json", "removed_json"),
        ("annotated_lines", "removed_lines"),
    ):
        rows = [
            (v[full], v[removed])
            for v in examples.values()
            if full in v and removed in v
        ]
        pairs[full + "_versus_" + removed] = {
            "scorable_pairs": len(rows),
            "mean_token_f1_delta": sum(a - b for a, b in rows) / len(rows)
            if rows
            else None,
            "gained": sum(a > b for a, b in rows),
            "lost": sum(a < b for a, b in rows),
            "tied": sum(a == b for a, b in rows),
        }
    output = {
        "schema": SCHEMA,
        "original_source_sha256": graph.DATASET_SHA256,
        "plan_sha256": plan_seal["plan_sha256"],
        "model_journal_sha256": seal["journal_sha256"],
        "questions": Q_COUNT,
        "planned": PLANNED,
        "original_reader_calls_replayed": PLANNED,
        "by_arm": {
            arm: {
                "scorable": len(scores[arm]),
                "mean_token_f1": sum(scores[arm]) / len(scores[arm])
                if scores[arm]
                else None,
                "status_counts": dict(statuses[arm]),
                "any_citation_label": markers[arm],
                "all_emitted_labels_delivered": valid_marker[arm],
                "invalid_citation_labels": invalid_marker[arm],
            }
            for arm in ARMS
        },
        "paired_comparisons": pairs,
        "publisher_annotated_sources_not_independent_sufficiency": True,
        "premise_removed_not_proven_semantically_necessary": True,
        "full_original_historical_source_oracle_not_deployment_eligible": True,
        "citation_entailment_independently_certified": False,
        "reader_HF_BF16_parity_certified": False,
        "prospective_external_source_families": 0,
        "production_accepted": False,
        "statistical_superiority": False,
    }
    graph.create_only(destination, output)
    return output


def main(args=None):
    args = sys.argv[1:] if args is None else args
    if len(args) == 5 and args[0] == "prepare":
        result = prepare(args[1], args[2], args[3], args[4])
    elif len(args) == 4 and args[0] == "run":
        result = run(args[1], args[2], args[3])
    elif len(args) == 8 and args[0] == "review":
        result = review(*args[1:])
    else:
        raise SystemExit(
            "prepare PUBLIC RANK ORIGINAL NEW_PLAN | run PLAN READER NEW_RUN | review PUBLIC RANK ORIGINAL PLAN RUN READER NEW_REPORT"
        )
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
