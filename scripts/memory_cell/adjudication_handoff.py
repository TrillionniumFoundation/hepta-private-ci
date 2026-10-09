"""Export a pinned, complete LongMemEval census for independent adjudication.

No models, network, signing keys or semantic judgements are used. The official
QA files preserve every original hypothesis; the separate citation worklist
contains only actually delivered excerpts. A zero citation denominator is null,
not perfect precision. Existing learning.eval owners still verify signed returns.
"""

import argparse
import json
import re
from pathlib import Path

from benchmark_coverage import ARMS, decode_plan
from benchmark_review import read_json
from citation_audit import MARKER, request_payload, sha
from native import Question, digest
from native_citation import capture_native

MAX_FILE_BYTES = 256 * 1024 * 1024
FILES = {"summary.json", "review.jsonl", "review-index.jsonl"}


def read_bytes(path: Path, bound: int) -> bytes:
    if (
        path.is_symlink()
        or any(p.is_symlink() for p in path.parents)
        or not path.is_file()
    ):
        raise ValueError("regular non-symlink evidence required")
    with path.open("rb") as stream:
        value = stream.read(bound + 1)
    if len(value) > bound:
        raise ValueError("evidence byte bound")
    return value


def lines(raw: bytes) -> list[dict]:
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("nonfinite JSON number: " + value)

    result = []
    for line in raw.decode("utf-8", "strict").splitlines():
        row = json.loads(line, object_pairs_hook=pairs, parse_constant=invalid)
        if not isinstance(row, dict):
            raise ValueError("object record required")
        result.append(row)
        if len(result) > 80_000:
            raise ValueError("adjudication record bound")
    return result


def export(
    plan_path: Path,
    review_root: Path,
    output: Path,
    *,
    expected_plan_sha256: str,
    expected_manifest_sha256: str,
    exporter_commit: str,
) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", exporter_commit):
        raise ValueError("exact exporter source required")
    if sha(read_bytes(plan_path, MAX_FILE_BYTES)) != expected_plan_sha256:
        raise ValueError("pre-run plan pin mismatch")
    declared, plan_hash, _ = read_json(plan_path, MAX_FILE_BYTES)
    plan = decode_plan(declared["coverage"])
    binding = declared["execution_binding"]
    if (
        declared["schema"] != "hepta.memory-benchmark.preregistered.v1"
        or plan.benchmark != "longmemeval"
        or plan.per_fold_limit is not None
        or len(plan.cases) != plan.native_total
    ):
        raise ValueError("complete native LongMemEval plan required")
    # A handoff is only valid for the exact source that produced the native
    # attempts.  In particular, do not let a later exporter HEAD re-label an
    # older successful run as current-head evidence.
    if binding.get("source_commit") != exporter_commit:
        raise ValueError("execution source commit differs from exporter HEAD")
    manifest = read_bytes(review_root / "SHA256SUMS", 4096)
    if sha(manifest) != expected_manifest_sha256:
        raise ValueError("external review manifest pin mismatch")
    inventory = {}
    for line in manifest.decode("ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([a-zA-Z0-9.-]+)", line)
        if not match or match[2] in inventory:
            raise ValueError("invalid or duplicate review manifest entry")
        inventory[match[2]] = match[1]
    if set(inventory) != FILES:
        raise ValueError("exact complete review files required")
    data = {name: read_bytes(review_root / name, MAX_FILE_BYTES) for name in FILES}
    if any(sha(raw) != inventory[name] for name, raw in data.items()):
        raise ValueError("review file differs from pinned bytes")
    summary = lines(data["summary.json"].replace(b"\n", b" "))[0]
    coverage = summary["coverage"]
    if (
        summary["schema"] != "hepta.memory-benchmark.review-result.v1"
        or summary["plan_file_sha256"] != plan_hash
        or summary["execution_source_commit"] != binding["source_commit"]
        or coverage["execution_binding"] != binding
        or coverage["coverage_digest"] != plan.seal()
        or coverage["complete"] is not True
        or coverage["all_native_questions_covered"] is not True
        or type(coverage["native_cases"]) is not int
        or coverage["native_cases"] != plan.native_total
        or type(summary["all_attempts_exported"]) is not int
        or summary["all_attempts_exported"] != len(ARMS) * plan.native_total
    ):
        raise ValueError("complete census/source binding mismatch")
    for arm in ARMS:
        counts = coverage["arms"][arm]
        if any(
            type(counts[k]) is not int for k in ("planned", "succeeded", "failed")
        ) or (counts["planned"], counts["succeeded"], counts["failed"]) != (
            plan.native_total,
            plan.native_total,
            0,
        ):
            raise ValueError("failed or missing native attempts cannot be filtered")
    indexes = lines(data["review-index.jsonl"])
    work = lines(data["review.jsonl"])
    expected = {(arm, q): f for q, f, _, _ in plan.cases for arm in ARMS}
    by_id, observed = {}, set()
    for index in indexes:
        arm, qid, family = index["arm"], index["question_id"], index["family"]
        pair = (arm, qid)
        rid = digest(("hepta.memory-benchmark.blind-review.v1", plan.seal(), arm, qid))
        if (
            pair not in expected
            or expected[pair] != family
            or pair in observed
            or index["review_id"] != rid
            or rid in by_id
        ):
            raise ValueError("non-bijective native review index")
        if not re.fullmatch(r"[0-9a-f]{64}", index["original_record_sha256"]):
            raise ValueError("missing original record digest")
        observed.add(pair)
        by_id[rid] = index
    if observed != set(expected) or len(work) != len(expected):
        raise ValueError("incomplete question/arm census")
    diagnostics = {
        a: dict(
            attempts=0,
            answers_without_markers=0,
            emitted_markers=0,
            undelivered_label_occurrences=0,
        )
        for a in ARMS
    }
    hypotheses = {a: [] for a in ARMS}
    payloads, seen = {}, set()
    for item in work:
        rid = item["review_id"]
        if rid not in by_id or rid in seen:
            raise ValueError("duplicate or unknown review attempt")
        seen.add(rid)
        index = by_id[rid]
        arm, qid = index["arm"], index["question_id"]
        if (
            item["schema"] != "hepta.memory-benchmark.review-item.v1"
            or item["status"] != "awaiting_independent_judgement"
            or item["production_accepted"] is not False
            or any(
                item[k] is not None
                for k in (
                    "generator_signature",
                    "evaluator_signature",
                    "judgement",
                    "semantic_precision",
                )
            )
        ):
            raise ValueError(
                "only original unsigned attempts; no invented verdicts or signatures"
            )
        request = item["request"]
        query = Question(
            qid, index["family"], qid, item["question"], item["question_time"]
        )
        original = dict(
            input_ids_sha256=item["original_prompt_sha256"],
            delivered_evidence=item["delivered_evidence"],
        )
        rebuilt = capture_native(
            query,
            item["answer"],
            original,
            experiment_digest=digest((plan.seal(), binding, arm)),
            family_digest=digest(index["family"]),
        )
        if (
            request != rebuilt["request"]
            or item["request_sha256"] != rebuilt["request_sha256"]
        ):
            raise ValueError(
                "answer/prompt/source/request detached from original attempt"
            )
        payloads[rid] = request_payload(request)
        if not qid.startswith("longmemeval:") or not qid[len("longmemeval:") :]:
            raise ValueError("native question ID namespace mismatch")
        hypotheses[arm].append(
            dict(question_id=qid[len("longmemeval:") :], hypothesis=item["answer"])
        )
        markers = list(MARKER.finditer(item["answer"].encode("utf-8")))
        labels = {s["label"] for s in request["sources"]}
        count = diagnostics[arm]
        count["attempts"] += 1
        count["answers_without_markers"] += not markers
        count["emitted_markers"] += len(markers)
        count["undelivered_label_occurrences"] += sum(
            m.group()[1:-1].decode("ascii") not in labels for m in markers
        )
    for count in diagnostics.values():
        n = count["emitted_markers"]
        count["structural_precision_ceiling_ppm"] = (
            (n - count["undelivered_label_occurrences"]) * 1_000_000 // n if n else None
        )
        count["semantic_precision"] = None
    result = dict(
        schema="hepta.memory-adjudication.handoff.v1",
        exporter_commit=exporter_commit,
        execution_source_commit=binding["source_commit"],
        original_review_manifest_sha256=expected_manifest_sha256,
        preregistered_plan_sha256=plan_hash,
        native_questions=plan.native_total,
        all_attempts_exported=len(work),
        source_family_groups=len(set(expected.values())),
        citation_structure=diagnostics,
        official_judge_executed=False,
        signed_semantic_precision=None,
        independent_acceptance=None,
        prospective_calendar_windows=0,
        production_accepted=False,
        superiority_claim=False,
    )
    # Validate every byte/case before creating output. READY is published last;
    # interrupted I/O leaves an explicitly incomplete, non-reusable directory.
    output.mkdir()
    (output / "requests").mkdir()
    (output / "official-qa-inputs").mkdir()
    (output / "citation-review.jsonl").write_bytes(data["review.jsonl"])
    for rid, raw in payloads.items():
        (output / "requests" / (rid + ".bin")).write_bytes(raw)
    for arm, rows in hypotheses.items():
        with (output / "official-qa-inputs" / (arm + ".jsonl")).open(
            "x", encoding="utf-8"
        ) as stream:
            for row in sorted(rows, key=lambda r: r["question_id"]):
                stream.write(
                    json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                )
    (output / "handoff.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (output / "SCOPE.txt").write_text(
        "Unsigned transfer, not a generator attestation, semantic judgement, future observation or production authority.\n"
        "Use official-qa-inputs only with the official LongMemEval QA evaluator and the original pinned corpus.\n"
        "QA correctness and citation entailment are distinct. Do not expose QA labels or arm comparisons to the blinded citation reviewer.\n"
        "Canonical request bytes must not be altered or retroactively presented as contemporaneously signed generation.\n"
        "Independent actors must review exact answer claims and actually delivered excerpts through existing learning.eval signing/verification owners.\n"
        "Do not infer 100% precision from no citations, or certify source independence from question/shard counts.\n",
        encoding="utf-8",
    )
    entries = {
        str(p.relative_to(output)): sha(p.read_bytes())
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    (output / "READY.json").write_text(
        json.dumps(
            dict(files=entries, production_accepted=False), sort_keys=True, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--exporter-commit", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            export(
                args.plan,
                args.review,
                args.output,
                expected_plan_sha256=args.plan_sha256,
                expected_manifest_sha256=args.manifest_sha256,
                exporter_commit=args.exporter_commit,
            ),
            indent=2,
        )
    )
