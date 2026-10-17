"""Source-sealed original-weight Reader capacity trial for parametric MemoryCell.

The offline FP32 SmolLM2 implementation is NOT validated as equivalent to the
registered Transformers/BF16 Reader. Reader inputs never contain gold labels.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import json
import math
import re
import sys

import associative_graph_causal as graph
import parametric_stem_reader as stem
from offline_smol_reader import OriginalSmol, verify_files
from reader_weight_transport import verify_reader_transport
from associative_offline_reader_diagnostic import strict_offline_result
from associative_question_conditioned import _token_f1


def read_rank(public_dir, rank_dir):
    public, public_manifest = graph.load_public(public_dir)
    raw = graph.regular_bytes(
        Path(rank_dir) / "predictions.json", limit=8 * 1024 * 1024
    )
    journal = graph.strict_load(raw)
    seal = graph.strict_load(graph.regular_bytes(Path(rank_dir) / "seal.json"))
    if (
        not isinstance(journal, dict)
        or set(journal)
        != {
            "schema",
            "public_sha256",
            "source_sha256",
            "arms",
            "top_k",
            "rows",
            "cells",
            "training_receipts",
            "model",
        }
        or journal["schema"] != stem.SCHEMA
        or journal["source_sha256"] != graph.DATASET_SHA256
        or journal["public_sha256"] != public_manifest["public_sha256"]
        or journal["arms"] != list(stem.ARMS)
        or journal["top_k"] != graph.TOP_K
        or not isinstance(seal, dict)
        or seal.get("schema") != stem.SCHEMA
        or seal.get("predictions_sha256") != graph.digest(raw)
        or seal.get("public_sha256") != public_manifest["public_sha256"]
        or seal.get("number_questions") != 240
        or seal.get("labels_visible") is not False
        or seal.get("production_accepted") is not False
    ):
        raise ValueError("unsigned/unregistered parametric source ranking")
    index = {}
    for group in public["families"]:
        for q in group["questions"]:
            index[q["id"]] = (
                group["family"],
                q["text"],
                {d["id"]: d for d in stem._pool(group)},
            )
    if len(index) != 240 or len(journal["rows"]) != 240:
        raise ValueError("incomplete source evidence census")
    seen = set()
    for row in journal["rows"]:
        qid = row["question_id"]
        if (
            set(row) != {"family", "question_id", "arms"}
            or qid not in index
            or qid in seen
            or row["family"] != index[qid][0]
            or not isinstance(row["arms"], dict)
            or set(row["arms"]) != set(stem.ARMS)
        ):
            raise ValueError("foreign or duplicate source question")
        seen.add(qid)
        for ranked in row["arms"].values():
            if (
                not isinstance(ranked, list)
                or len(ranked) != graph.TOP_K
                or len(set(ranked)) != graph.TOP_K
                or not set(ranked) <= set(index[qid][2])
            ):
                raise ValueError("source out of original chronology cut")
    if seen != set(index):
        raise ValueError("missing original question")
    return public, public_manifest, journal, seal, index


def reader_inputs(public_dir, rank_dir):
    public, manifest, journal, seal, index = read_rank(public_dir, rank_dir)
    selected = {
        min(
            (q["id"] for q in group["questions"]),
            key=lambda qid: (
                hashlib.sha256(
                    ("hepta.parametric-stem-reader.fixed.v1\0" + qid).encode()
                ).hexdigest(),
                qid,
            ),
        )
        for group in public["families"]
    }
    rows = []
    for row in journal["rows"]:
        if row["question_id"] not in selected:
            continue
        family, question, docs = index[row["question_id"]]
        for arm in stem.READER_ARMS:
            ids = [] if arm == "empty" else row["arms"][arm]
            evidence = [
                {
                    "label": f"E{n}",
                    "source_id": sid,
                    "text": docs[sid]["speaker"]
                    + ": "
                    + docs[sid]["text"][: stem.READ_CHARS],
                }
                for n, sid in enumerate(ids, 1)
            ]
            rows.append(
                {
                    "family": family,
                    "question_id": row["question_id"],
                    "arm": arm,
                    "question": question,
                    "evidence": evidence,
                    "public_sha256": manifest["public_sha256"],
                }
            )
    if len(rows) != 10 * len(stem.READER_ARMS):
        raise ValueError("expected complete precommitted 50-call Reader plan")
    return rows, seal


def run(public_dir, rank_dir, reader_dir, output_dir):
    if (Path(public_dir) / "private.json").exists() or (
        Path(public_dir) / "private.json"
    ).is_symlink():
        raise ValueError("Reader saw hidden reference labels")
    plan, ranking = reader_inputs(public_dir, rank_dir)
    transport = verify_reader_transport(reader_dir)
    verify_files(reader_dir)
    import torch

    torch.set_num_threads(2)
    reader = OriginalSmol(reader_dir)
    out = Path(output_dir)
    out.mkdir(exist_ok=False)
    result = []
    for n, row in enumerate(plan, 1):
        generated = strict_offline_result(reader, row)
        result.append(
            {
                "family": row["family"],
                "question_id": row["question_id"],
                "arm": row["arm"],
                "evidence_ids": [e["source_id"] for e in row["evidence"]],
                "input_sha256": graph.digest(graph.canonical(row)),
                "result": generated,
            }
        )
        if n % 10 == 0:
            print(
                f"original-reader attempts {n}/{len(plan)}", file=sys.stderr, flush=True
            )
    reader.verify_frozen()
    journal_sha = graph.create_only(out / "reader-journal.json", result)
    meta = {
        "schema": stem.READER_SCHEMA,
        "source_public_sha256": plan[0]["public_sha256"],
        "rank_journal_sha256": ranking["predictions_sha256"],
        "reader_journal_sha256": journal_sha,
        "reader_file_identity": transport["registered_identity"],
        "reader_backend": "original-smol-fp32-not-HF-parity",
        "planned": len(plan),
        "generated_token_ceiling": stem.READER_TOKENS,
        "source_heldout_labels_visible": False,
        "independent_semantic_citation_adjudication": False,
        "production_accepted": False,
    }
    graph.create_only(out / "reader-seal.json", meta)
    return meta


def review(public_dir, rank_dir, reader_result_dir, original_dataset, target):
    """Open publisher answer annotations only AFTER verifying all sealed calls."""
    plan, rankseal = reader_inputs(public_dir, rank_dir)
    raw = graph.regular_bytes(Path(reader_result_dir) / "reader-journal.json")
    record = graph.strict_load(raw)
    seal = graph.strict_load(
        graph.regular_bytes(Path(reader_result_dir) / "reader-seal.json")
    )
    if (
        not isinstance(seal, dict)
        or seal.get("schema") != stem.READER_SCHEMA
        or seal.get("source_public_sha256") != plan[0]["public_sha256"]
        or seal.get("rank_journal_sha256") != rankseal["predictions_sha256"]
        or seal.get("reader_journal_sha256") != graph.digest(raw)
        or seal.get("planned") != len(plan)
        or seal.get("generated_token_ceiling") != stem.READER_TOKENS
        or seal.get("reader_backend") != "original-smol-fp32-not-HF-parity"
        or seal.get("source_heldout_labels_visible") is not False
        or seal.get("production_accepted") is not False
        or not isinstance(record, list)
        or len(record) != len(plan)
    ):
        raise ValueError("untrusted original Reader journal or model identity")
    idx = {(e["question_id"], e["arm"]): e for e in plan}
    seen, stats, paired = set(), defaultdict(list), defaultdict(dict)
    for item in record:
        if not isinstance(item, dict) or set(item) != {
            "family",
            "question_id",
            "arm",
            "evidence_ids",
            "input_sha256",
            "result",
        }:
            raise ValueError("unknown Reader journal field")
        key = (item["question_id"], item["arm"])
        if key not in idx or key in seen:
            raise ValueError("unknown Reader question/arm combination")
        seen.add(key)
        expected = idx[key]
        if (
            item["family"] != expected["family"]
            or item["evidence_ids"] != [e["source_id"] for e in expected["evidence"]]
            or item["input_sha256"] != graph.digest(graph.canonical(expected))
        ):
            raise ValueError("Reader evidence/identity mismatch")
        res = item["result"]
        if (
            not isinstance(res, dict)
            or res.get("status") not in ("succeeded", "unavailable", "failed")
            or (
                res["status"] == "succeeded"
                and (
                    not isinstance(res.get("answer"), str) or not res["answer"].strip()
                )
            )
        ):
            raise ValueError("Reader output has untrusted result status")
    if seen != set(idx):
        raise ValueError("missing Reader generation")
    # The model worker has no path to this original publisher/source file.
    original_raw = graph.regular_bytes(original_dataset, limit=8 * 1024 * 1024)
    if graph.digest(original_raw) != graph.DATASET_SHA256:
        raise ValueError("original LoCoMo source drift")
    original = graph.strict_load(original_raw)
    answers = {
        f"{item['sample_id']}/q{i:04d}": r.get("answer")
        for item in original
        for i, r in enumerate(item["qa"])
    }
    markers = Counter()
    for item in record:
        qid, arm = item["question_id"], item["arm"]
        result = item["result"]
        ref = answers.get(qid)
        if result["status"] == "succeeded":
            response = result["answer"]
            markers[arm] += int(bool(re.search(r"\[E[1-8]\]", response)))
            if isinstance(ref, str) and ref.strip():
                score = _token_f1(response, ref)
                stats[arm].append(score)
                paired[qid][arm] = score
    report = {
        "schema": stem.READER_SCHEMA,
        "source_sha256": graph.DATASET_SHA256,
        "reader_journal_sha256": seal["reader_journal_sha256"],
        "planned": len(plan),
        "unique_questions": len({e["question_id"] for e in plan}),
        "by_arm": {
            arm: {
                "scorable": len(stats[arm]),
                "mean_token_f1": sum(stats[arm]) / len(stats[arm])
                if stats[arm]
                else None,
                "emitted_any_citation_label": markers[arm],
            }
            for arm in stem.READER_ARMS
        },
        "reader_backend_parity_verified": False,
        "semantic_citation_entailment_verified": False,
        "independent_semantic_judge": False,
        "independent_source_family_count_verified": False,
        "source_catalogue_required_for_memorycell": True,
        "statistical_superiority": False,
        "production_accepted": False,
    }
    graph.create_only(target, report)
    return report


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 5 and args[0] == "run":
        result = run(args[1], args[2], args[3], args[4])
    elif len(args) == 6 and args[0] == "review":
        result = review(args[1], args[2], args[3], args[4], args[5])
    else:
        raise SystemExit(
            "run PUBLIC RANK READER NEW_OUT | review PUBLIC RANK READER_RESULTS ORIGINAL_LOCOMO NEW_REPORT"
        )
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
