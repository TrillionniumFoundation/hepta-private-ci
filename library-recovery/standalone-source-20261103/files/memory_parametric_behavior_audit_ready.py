#!/usr/bin/env python3
"""Independently re-open original native MemoryCell outputs; no model or training.

Audits the exact successful native pilot run, preserving unscored denominators
and rejecting mismatched input, retrieval, original answer, archive or family
receipts. An unchanged F1 is not proof that model answers were unchanged.
"""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import zipfile

RUN_ID = 38675845950
SOURCE_SHA = "2b33c6321f52711761ec626ead27c9482c7c1cb0"
MODEL_SHA = "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c"
ENCODER_SHA = "5afecdd6098fec07380bc10a30fd8debcffcd147274b3ffd18143f1fa86dc12a"
ARCHIVES = {
    "locomo": ("310e38cfe87ae55838afb8612fb90eb028fc7abde55c529faa1d807fa878f333", 101),
    "longmemeval": ("95d1b57cab057e7fb5c45d9ba994c4b9d22d49f6e834abe7a0a7b2cc6106c315", 98),
}
ARMS = ("no_memory", "rag", "rag_lora", "parametric_only")
PAIRINGS = (("no_memory", "parametric_only"), ("rag", "rag_lora"))
EXTRA_PAIR = ("no_memory", "rag")
HEX = re.compile(r"[0-9a-f]{64}\Z")


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def strict_json(data: bytes):
    def fields(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON property")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("nonfinite JSON constant: " + value)

    return json.loads(data, object_pairs_hook=fields, parse_constant=invalid_constant)


def verified_archive(path: Path, benchmark: str):
    require(benchmark in ARCHIVES, "unregistered original benchmark")
    expected, count = ARCHIVES[benchmark]
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size < 80_000_000,
            "bounded original ZIP file required")
    require(digest(path.read_bytes()) == expected, "external whole-ZIP SHA-256 mismatch")
    with zipfile.ZipFile(path, "r") as source:
        infos = source.infolist()
        names = [item.filename for item in infos]
        require(len(names) == len(set(names)) == count + 1 and "SHA256SUMS" in names,
                "incomplete or duplicated ZIP census")
        require(all(not item.is_dir() and (item.external_attr >> 16) & 0o170000 != 0o120000
                    for item in infos), "symbolic links or directories are not original output")
        manifest = source.read("SHA256SUMS").decode("utf-8", "strict").splitlines()
        require(len(manifest) == count, "incomplete original SHA256SUMS census")
        seen = set()
        total_bytes = 0
        for line in manifest:
            marker = re.fullmatch(r"([0-9a-f]{64})  /tmp/mcell-native/(.+)", line)
            require(marker is not None, "unrecognized internal original path/hash")
            member = marker.group(2)
            require(member.startswith(benchmark + "/") or member in
                    {"python-lock.txt", "staging.json", "tested-commit.txt"},
                    "unexpected cross-benchmark original member")
            require(member in names and member not in seen and not member.endswith("/"),
                    "missing or duplicate inner original member")
            seen.add(member)
            value = source.read(member)
            total_bytes += len(value)
            require(total_bytes < 512_000_000, "excessive expanded original ZIP")
            require(digest(value) == marker.group(1), "internal original bytes changed")
        require(seen == set(names) - {"SHA256SUMS"}, "unlisted original ZIP members")
        report = strict_json(source.read(f"{benchmark}/report.json"))
        require(report["execution_binding"]["source_commit"] == SOURCE_SHA
                and report["execution_binding"]["backend_profile"] == "pretrained-offline"
                and report["reader_identity"] == MODEL_SHA
                and report["embedding_identity"] == ENCODER_SHA,
                "original native generating source/model differs")
        outputs = {}
        for arm in ARMS:
            raw = source.read(f"{benchmark}/{arm}-hypotheses.jsonl")
            require(raw.endswith(b"\n"), "original model journal truncated")
            lines = [strict_json(line) for line in raw.splitlines()]
            require(len(lines) == 16, "original 16-answer census incomplete")
            records = {}
            for row in lines:
                question = row["question_id"]
                question = question if question.startswith(benchmark + ":") else f"{benchmark}:{question}"
                require(question not in records and row["execution_status"] == "succeeded"
                        and isinstance(row["hypothesis"], str),
                        "duplicate/failed original model output")
                records[question] = row["hypothesis"]
            results = report["results"][arm]
            require(len(results) == 16 and len({r["question_id"] for r in results}) == 16,
                    "original report question census changed")
            require(set(records) == {r["question_id"] for r in results},
                    "original answers no longer match report IDs")
            for row in results:
                require(row["status"] == "succeeded"
                        and row["hypothesis"] == records[row["question_id"]],
                        "report regenerated/rewritten original model answer")
            outputs[arm] = {r["question_id"]: r for r in results}
        return dict(benchmark=benchmark, archived_zip_sha256=expected,
                    inner_sha256_members=count, source_sha256=SOURCE_SHA,
                    results=outputs)


def score_pair(left: dict, right: dict, *, require_same_evidence=True) -> dict:
    require(set(left) == set(right) and len(left) == 16, "unpaired question population")
    changed, f1_wins, f1_losses, f1_ties, missing = [], 0, 0, 0, 0
    roots = Counter()
    left_time = right_time = 0.0
    for question in sorted(left):
        a, b = left[question], right[question]
        ra, rb = a["receipt"], b["receipt"]
        root_a = a["citation_audit"]["request"]["family_digest"]
        root_b = b["citation_audit"]["request"]["family_digest"]
        require(isinstance(root_a, str) and HEX.fullmatch(root_a) and root_a == root_b,
                "source family attribution drift")
        roots[root_a] += 1
        if require_same_evidence:
            require(all(ra.get(key) == rb.get(key) for key in
                        ("input_ids_sha256", "retrieval_selected_ids", "delivered_evidence")),
                    "paired original inference input/evidence mismatch")
        for receipt in (ra, rb):
            require(type(receipt.get("query_seconds")) in (float, int)
                    and math.isfinite(receipt["query_seconds"])
                    and 0 <= receipt["query_seconds"] < 7200,
                    "invalid original inference latency")
        left_time += ra["query_seconds"]
        right_time += rb["query_seconds"]
        score_a, score_b = a.get("diagnostic_token_f1"), b.get("diagnostic_token_f1")
        require((score_a is None) == (score_b is None), "paired diagnostic score missingness changed")
        if score_a is None:
            missing += 1
        else:
            require(all(type(s) in (float, int) and math.isfinite(s) and 0 <= s <= 1
                        for s in (score_a, score_b)), "invalid original diagnostic F1")
            f1_wins += score_b > score_a
            f1_losses += score_b < score_a
            f1_ties += score_b == score_a
        if a["hypothesis"] == b["hypothesis"]:
            require(score_a == score_b, "identical paired answers scored differently")
        else:
            changed.append(dict(question_id=question,
                                original_answer_sha256=digest(a["hypothesis"].encode()),
                                candidate_answer_sha256=digest(b["hypothesis"].encode()),
                                original_diagnostic_f1=score_a,
                                candidate_diagnostic_f1=score_b))
    return dict(attempts=16, exact_answer_identical=16-len(changed), changed_answers=len(changed),
                changed_answer_digests=changed, paired_f1_scored=16-missing,
                paired_f1_unscored=missing, f1_wins=f1_wins, f1_losses=f1_losses,
                f1_ties=f1_ties, source_family_proxy_counts=dict(sorted(roots.items())),
                observed_inference_seconds_original=left_time,
                observed_inference_seconds_candidate=right_time,
                cost_is_query_timing_not_complete_tco=True)


def audit(paths: dict[str, Path]) -> dict:
    require(set(paths) == set(ARCHIVES), "both original native model archives required")
    originals = {bench: verified_archive(paths[bench], bench) for bench in ARCHIVES}
    rows = {}
    roots = set()
    for bench, source in originals.items():
        observations = source["results"]
        pairs = {f"{a}_vs_{b}": score_pair(observations[a], observations[b])
                 for a, b in PAIRINGS}
        pairs["no_memory_vs_rag"] = score_pair(observations["no_memory"],
                                                observations["rag"], require_same_evidence=False)
        for key in ("no_memory_vs_parametric_only", "rag_vs_rag_lora"):
            roots.update(pairs[key]["source_family_proxy_counts"])
        rows[bench] = dict(original_zip_sha256=source["archived_zip_sha256"],
                           inner_member_sha256_verified=source["inner_sha256_members"],
                           original_model_generations=64, comparisons=pairs)
    keysets = [rows[b]["comparisons"][k] for b in rows for k in
               ("no_memory_vs_parametric_only", "rag_vs_rag_lora")]
    total_changed = sum(k["changed_answers"] for k in keysets)
    require(sum(k["attempts"] for k in keysets) == 64,
            "parameter contrast census incomplete")
    return dict(schema="hepta.memory.original-native-parametric-answer-delta.v1",
                original_github_run_id=RUN_ID, generating_source_sha=SOURCE_SHA,
                original_reader_identity=MODEL_SHA, original_encoder_identity=ENCODER_SHA,
                original_real_model_calls=128, original_question_occurrences=32,
                paired_parametric_comparisons=64,
                paired_parametric_answers_exactly_identical=64-total_changed,
                paired_parametric_answers_changed=total_changed,
                distinct_source_family_proxies=len(roots),
                independent_effective_n_certified=False,
                per_benchmark=rows, original_model_answers_rewritten=False,
                new_model_generations_this_audit=0,
                semantic_citation_entailment_certified=False,
                trained_parameter_advantage_established=False,
                independent_future_population_qualified=False,
                full_lifecycle_tco=None, production_qualified=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locomo", type=Path, required=True)
    parser.add_argument("--longmemeval", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    outcome = audit({"locomo": args.locomo, "longmemeval": args.longmemeval})
    require(not args.output.exists() and not args.output.is_symlink(),
            "refuse to overwrite original independent audit")
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(outcome, handle, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps(dict(original_calls=128,
                          changed_parameter_answers=outcome["paired_parametric_answers_changed"],
                          production_qualified=False), sort_keys=True))


if __name__ == "__main__":
    main()
