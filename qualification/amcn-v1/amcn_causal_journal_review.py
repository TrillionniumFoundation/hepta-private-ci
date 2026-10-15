"""Independent *byte-consistency* census for completed nine-arm Reader journals.

A producer's SHA-256 is not an independent execution attestation. This module
reconstructs every original request, response and attempt receipt from durable
bytes, with externally pinned complete files. It does not execute a model,
score an answer, verify a model host or authenticate a reviewer.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

from amcn_causal_task_audit import (
    ARMS, PROFILE, Refused, _duplicate_reject, bytes_sha, canonical, digest,
    is_sha, original_emitted_sources, require, validate_plan,
)
from amcn_causal_reader_generation import PROMPT_SHA

FILES = frozenset({"frozen-plan.json", "physical-material-binding.json",
                   "starts.jsonl", "answers.jsonl", "attempt-status.jsonl",
                   "answers.json", "sealed-original.json"})
MAX_JOURNAL_BYTES = 128 * 1024 * 1024
TYPE_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]{0,127}\Z")


def read_bytes(root, name, *, sha=None):
    require(name in FILES, "unregistered execution journal file")
    path = root / name
    require(path.is_file() and not path.is_symlink()
            and 0 < path.stat().st_size <= MAX_JOURNAL_BYTES,
            "missing, linked or oversize execution journal")
    data = path.read_bytes()
    if sha is not None:
        require(is_sha(sha) and bytes_sha(data) == sha,
                "externally pinned original journal bytes drifted")
    return data


def decode_json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_duplicate_reject,
                          parse_constant=lambda x: (_ for _ in ()).throw(
                              Refused("nonfinite journal JSON constant")))
    except (ValueError, UnicodeDecodeError) as exc:
        raise Refused("invalid or duplicate original journal JSON") from exc


def json_file(root, name, *, sha=None):
    raw = read_bytes(root, name, sha=sha)
    val = decode_json(raw)
    require(raw == canonical(val) + b"\n",
            "original JSON file is not the exact fsynced canonical bytes")
    return val


def json_lines(root, name):
    raw = read_bytes(root, name)
    require(raw.endswith(b"\n") and b"\r" not in raw,
            "partial execution journal line")
    lines = raw.split(b"\n")
    require(lines.pop() == b"", "partial final JSONL record")
    require(len(lines) <= 8192 * len(ARMS), "unbounded attempt census")
    out = []
    for line in lines:
        val = decode_json(line)
        require(line == canonical(val), "amended, blank or noncanonical JSONL row")
        out.append(val)
    return out, raw


def audit_original_journal(directory, *, source_plan_sha256,
                           original_plan_sha256, original_answers_file_sha256,
                           original_seal_file_sha256, material_manifest_digest):
    """Recount every physical execution *claim*; independence stays unverified."""
    pins = (source_plan_sha256, original_plan_sha256,
            original_answers_file_sha256, original_seal_file_sha256,
            material_manifest_digest)
    require(all(is_sha(x) for x in pins), "independent original material pins required")
    root = Path(directory)
    require(root.is_dir() and not root.is_symlink() and
            {p.name for p in root.iterdir()} == FILES and
            all(p.is_file() and not p.is_symlink() for p in root.iterdir()),
            "incomplete/extra/linked original journal")
    plan = json_file(root, "frozen-plan.json", sha=original_plan_sha256)
    expected = validate_plan(plan)
    require(plan["prompt_sha256"] == PROMPT_SHA,
            "original execution prompt does not match fixed Reader")
    binding = json_file(root, "physical-material-binding.json")
    require(isinstance(binding, dict) and set(binding) == {
        "source_plan_sha256", "material_manifest_digest", "reader_sha256",
        "real_pretrained_execution_independently_attested", "production_accepted"},
        "unexpected Reader material binding")
    require(binding["source_plan_sha256"] == source_plan_sha256
            and binding["material_manifest_digest"] == material_manifest_digest
            and binding["reader_sha256"] == plan["reader_sha256"]
            and binding["real_pretrained_execution_independently_attested"] is False
            and binding["production_accepted"] is False,
            "Reader/material/authority changed after execution")
    answers = json_file(root, "answers.json", sha=original_answers_file_sha256)
    sealed = json_file(root, "sealed-original.json", sha=original_seal_file_sha256)
    require(isinstance(sealed, dict) and set(sealed) == {
        "schema", "plan_sha256", "answers_sha256", "raw_answer_rows_sha256",
        "original_answer_attempts", "failed_attempts",
        "physical_execution_claim_requires_independent_host_evidence",
        "independent_truth_review", "production_accepted"},
        "unregistered or missing original seal fields")
    starts, _ = json_lines(root, "starts.jsonl")
    raw_answers, raw_bytes = json_lines(root, "answers.jsonl")
    statuses, _ = json_lines(root, "attempt-status.jsonl")
    requested = [(case["question_id"], arm) for case in plan["cases"] for arm in ARMS]
    require(len(requested) == len(starts) == len(raw_answers) == len(statuses)
            and isinstance(answers, list) and len(answers) == len(requested),
            "missing/duplicate/interrupted Reader answer or attempt slot")
    require(answers == raw_answers,
            "complete answers do not reproduce original append-only rows")
    require(sealed["schema"] == PROFILE + ".original-reader-journal.shadow.v1"
            and sealed["plan_sha256"] == digest(plan)
            and sealed["answers_sha256"] == digest(answers)
            and sealed["raw_answer_rows_sha256"] == bytes_sha(raw_bytes)
            and sealed["original_answer_attempts"] == len(requested)
            and type(sealed["original_answer_attempts"]) is int
            and sealed["physical_execution_claim_requires_independent_host_evidence"] is True
            and sealed["independent_truth_review"] is False
            and sealed["production_accepted"] is False,
            "original completion seal does not reproduce source material")
    failures = 0
    observed = {arm: {"attempts": 0, "failed": 0,
                      "input_tokens": 0, "output_tokens": 0,
                      "wall_ms": 0, "orphan_citation_count": 0} for arm in ARMS}
    for index, key in enumerate(requested):
        case, choice = expected[key]
        start, row, status = starts[index], raw_answers[index], statuses[index]
        identity = {"question_id": key[0], "arm": key[1],
                    "request_sha256": choice["planned_request_sha256"]}
        require(start == identity,
                "out-of-order, duplicated or replaced execution start")
        require(isinstance(row, dict) and set(row) == set(identity) | {
            "status", "raw_answer", "raw_answer_sha256", "input_tokens",
            "output_tokens", "wall_ms", "emitted_source_ids",
            "reader_execution_receipt_sha256"},
            "original answer record has missing/extra fields")
        require(all(row[k] == v for k, v in identity.items())
                and row["status"] in ("ok", "failed"),
                "answer substituted for a different original request")
        require(isinstance(status, dict) and set(status) == set(identity) | {
            "status", "exception_type"}
                and all(status[k] == v for k, v in identity.items())
                and status["status"] == row["status"],
                "attempt-status contradicts original model answer")
        if row["status"] == "ok":
            require(status["exception_type"] is None,
                    "successful generation unexpectedly recorded exception")
            require(isinstance(row["raw_answer"], str) and
                    0 < len(row["raw_answer"].encode("utf-8")) <= 8192 and
                    row["raw_answer"].strip() and
                    row["raw_answer_sha256"] == bytes_sha(
                        row["raw_answer"].encode("utf-8")),
                    "original raw Reader answer changed")
        else:
            failures += 1
            require(isinstance(status["exception_type"], str)
                    and TYPE_NAME.fullmatch(status["exception_type"]) is not None
                    and row["raw_answer"] is None and row["raw_answer_sha256"] is None,
                    "failed model execution overwritten as successful answer")
        for col, bound in (("input_tokens", plan["max_input_tokens"]),
                           ("output_tokens", plan["max_output_tokens"]),
                           ("wall_ms", 3_600_000)):
            require(type(row[col]) is int and 0 <= row[col] <= bound,
                    "original model tokens/resource report outside limits")
        if row["status"] == "ok":
            require(row["input_tokens"] > 0 and row["output_tokens"] > 0,
                    "model response omitted actual token usage")
        citations = original_emitted_sources(row["raw_answer"], choice["source_ids"])
        require(row["emitted_source_ids"] == citations and len(citations) <= 64,
                "emitted citation labels disagree with original answer text")
        recomputed = digest([
            material_manifest_digest, identity["request_sha256"], row["status"],
            row["raw_answer"], row["input_tokens"], row["output_tokens"],
            row["wall_ms"],
        ])
        require(row["reader_execution_receipt_sha256"] == recomputed,
                "original execution receipt was not derived from physical claim bytes")
        count = observed[key[1]]
        count["attempts"] += 1
        count["failed"] += int(row["status"] == "failed")
        count["input_tokens"] += row["input_tokens"]
        count["output_tokens"] += row["output_tokens"]
        count["wall_ms"] += row["wall_ms"]
        count["orphan_citation_count"] += sum(
            citation not in choice["source_ids"] for citation in citations)
    require(type(sealed["failed_attempts"]) is int and
            sealed["failed_attempts"] == failures,
            "failed original Reader work erased from final seal")
    return {
        "profile": PROFILE + ".journal-byte-recount.shadow.v1",
        "original_plan_sha256": original_plan_sha256,
        "original_answers_file_sha256": original_answers_file_sha256,
        "original_seal_file_sha256": original_seal_file_sha256,
        "original_source_plan_sha256": source_plan_sha256,
        "original_material_manifest_digest": material_manifest_digest,
        "question_count": len(plan["cases"]),
        "fully_recounted_answer_attempts": len(raw_answers),
        "original_failed_attempts": failures,
        "original_per_arm_counters": observed,
        "raw_answer_text_parsed_for_citations": True,
        "independently_authenticated_pretrained_model": False,
        "independently_authenticated_reviewer": False,
        "independent_semantic_task_correctness": None,
        "production_accepted": False, "superiority_claim": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, required=True)
    for field in ("source-plan", "original-plan", "original-answers-file",
                  "original-seal-file", "material-manifest-digest"):
        parser.add_argument("--" + field + "-sha256" if field != "material-manifest-digest"
                            else "--material-manifest-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit_original_journal(
        args.journal,
        source_plan_sha256=args.source_plan_sha256,
        original_plan_sha256=args.original_plan_sha256,
        original_answers_file_sha256=args.original_answers_file_sha256,
        original_seal_file_sha256=args.original_seal_file_sha256,
        material_manifest_digest=args.material_manifest_digest,
    )
    require(not args.output.exists() and not args.output.is_symlink(),
            "refuse to replace previous independent byte-accounting receipt")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as file:
        file.write(canonical(result) + b"\n")
        file.flush()
        import os
        os.fsync(file.fileno())
    return result


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True))
