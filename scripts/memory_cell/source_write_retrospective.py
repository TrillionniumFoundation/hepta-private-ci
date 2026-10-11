"""Immutable diagnostic for completed source-only memory experiments.

This is a read-only replay of already generated answers, not new model inference,
statistical significance, semantic citation adjudication or production acceptance.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

ARMS = (
    "hybrid",
    "organized",
    "knowledge",
    "parameter_only",
    "empty",
    "policy_initial",
    "policy",
)
PAIRS = (
    ("organization_vs_hybrid", "hybrid", "organized"),
    ("policy_vs_initialization", "policy_initial", "policy"),
    ("policy_vs_organized", "organized", "policy"),
    ("knowledge_vs_same_evidence", "organized", "knowledge"),
    ("parameter_only_vs_empty", "empty", "parameter_only"),
)
CITATION = re.compile(r"\[E[1-9][0-9]*\]")


def strict_json(data):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate field in original record")
            obj[key] = value
        return obj

    def invalid(value):
        raise ValueError("non-finite JSON: " + value)

    return json.loads(data, object_pairs_hook=unique, parse_constant=invalid)


def checked_archive(archive_path, expected_sha256):
    """Verify the outer pinned artifact and EVERY internal recorded file."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("external artifact pin required")
    path = Path(archive_path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024**2:
        raise ValueError("bounded regular artifact required")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("original artifact ZIP hash differs")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if (
            not 1 <= len(entries) <= 256
            or sum(e.file_size for e in entries) > 32 * 1024**2
        ):
            raise ValueError("unbounded artifact contents")
        found = {}
        for item in entries:
            name = PurePosixPath(item.filename)
            key = str(name)
            if (
                item.is_dir()
                or name.is_absolute()
                or ".." in name.parts
                or "\\" in item.filename
                or stat.S_ISLNK(item.external_attr >> 16)
                or key in found
                or str(name) != item.filename
            ):
                raise ValueError("duplicate, symlink or unsafe artifact entry")
            found[key] = archive.read(item)
    if "SHA256SUMS" not in found:
        raise ValueError("missing complete internal inventory")
    expected = {}
    for line in found["SHA256SUMS"].decode().splitlines():
        if "  " not in line:
            raise ValueError("noncanonical SHA256SUMS entry")
        checksum, name = line.split("  ", 1)
        if not re.fullmatch(r"[0-9a-f]{64}", checksum) or not name.startswith("./"):
            raise ValueError("invalid internal file checksum")
        name = name[2:]
        if name in expected:
            raise ValueError("duplicate checksum entry")
        expected[name] = checksum
    if set(found) != set(expected) | {"SHA256SUMS"}:
        raise ValueError("incomplete or extra internal artifact file")
    if any(
        hashlib.sha256(found[name]).hexdigest() != checksum
        for name, checksum in expected.items()
    ):
        raise ValueError("original artifact internal bytes changed")
    return found


def diagnose(found, generating_commit):
    if not re.fullmatch(r"[0-9a-f]{40}", generating_commit):
        raise ValueError("exact generating source commit required")
    get = lambda name: strict_json(found[name].decode())
    ready, execution = get("snapshot/READY.json"), get("tasks/execution.json")
    source = found["tested-commit.txt"].decode().strip()
    if (
        generating_commit != source
        or ready["writer_source"] != source
        or execution["writer_source"] != source
        or execution["source_commit"] != source
        or execution["snapshot_loaded_before_task_payload"] is not True
        or ready["task_payload_consumed"] is not False
        or ready["production_accepted"] is not False
    ):
        raise ValueError("original source/read separation drift")
    if (
        hashlib.sha256(found["snapshot/READY.json"]).hexdigest()
        != execution["ready_sha"]
    ):
        raise ValueError("original READY pin differs")
    training = ready["training"]
    sched = training["write_schedule"]
    if (
        type(training["steps"]) is not int
        or training["steps"] < 1
        or training["steps"] != sched["planned_steps"]
        or training["input_tokens"] != sched["planned_input_tokens"]
        or training["supervised_tokens"] != sched["planned_supervised_tokens"]
        or training["steps"] != sum(sched["visits_per_example"])
        or training["examples"] != len(sched["visits_per_example"])
        or len(training["losses"]) != training["steps"]
        or not all(
            type(x) in (int, float) and math.isfinite(x) and x >= 0
            for x in training["losses"]
        )
        or type(training["adapter_delta_squared_norm"]) not in (int, float)
        or not math.isfinite(training["adapter_delta_squared_norm"])
        or training["adapter_delta_squared_norm"] <= 0
    ):
        raise ValueError("training exposure, optimizer or integrity drift")
    raw = [
        strict_json(line.decode())
        for line in found["tasks/raw-answers.jsonl"].splitlines()
    ]
    scored = get("tasks/scored-answers.json")
    old_report, old_effects = get("tasks/report.json"), get("tasks/source-effects.json")
    if (
        old_effects["raw_answers_sha256"]
        != hashlib.sha256(found["tasks/raw-answers.jsonl"]).hexdigest()
    ):
        raise ValueError("published effects do not bind original raw answers")
    questions = {r["question_id"] for r in raw}
    census = {(q, arm) for q in questions for arm in ARMS}
    if (
        not questions
        or len(questions) > 1024
        or len(raw) != len(census)
        or len(scored) != len(raw)
    ):
        raise ValueError("incomplete original seven-arm census")
    rows, unsupported, totals = {}, {}, {arm: 0 for arm in ARMS}
    for original, annotated in zip(raw, scored, strict=True):
        key = (original["question_id"], original["arm"])
        if (
            key in rows
            or key not in census
            or original["status"] not in ("succeeded", "failed")
            or any(k not in annotated or annotated[k] != v for k, v in original.items())
            or set(annotated) - set(original)
            != (
                {"parsed_identifier", "strict_task_success", "procedure_verification"}
                if original["status"] == "succeeded" and original["kind"] == "procedure"
                else {"parsed_identifier", "strict_task_success"}
                if original["status"] == "succeeded"
                else set()
            )
        ):
            raise ValueError(
                "missing, duplicate or retrospectively rewritten raw answer"
            )
        if original["status"] == "succeeded":
            if type(annotated["strict_task_success"]) is not bool:
                raise ValueError("missing strict task result")
            receipt = original["receipt"]
            if type(receipt["knowledge_module_enabled"]) is not bool or receipt[
                "knowledge_module_enabled"
            ] != (key[1] in ("knowledge", "parameter_only")):
                raise ValueError("adapter did not match declared arm")
            if len(receipt["delivered_evidence"]) != len(original["selected"]):
                raise ValueError("source count differs from selected evidence")
            if key[1] in ("empty", "parameter_only") and (
                original["selected"] or receipt["delivered_evidence"]
            ):
                raise ValueError("empty-context arm received evidence")
            totals[key[1]] += int(annotated["strict_task_success"])
            if (
                CITATION.search(original["answer"])
                and not receipt["delivered_evidence"]
            ):
                unsupported[key] = True
        rows[key] = annotated
    if set(rows) != census:
        raise ValueError("missing original task/arm pairs")
    if old_report["all_attempts"] != len(raw) or old_report["source_commit"] != source:
        raise ValueError("old report does not belong to original model execution")
    for arm, success in totals.items():
        if old_report["arms"][arm]["strict_task_successes"] != success:
            raise ValueError("published original task total differs")
    contrasts = {}
    for label, before, after in PAIRS:
        wins = losses = missing = changed = 0
        for q in questions:
            a, b = rows[(q, before)], rows[(q, after)]
            if a["status"] != "succeeded" or b["status"] != "succeeded":
                missing += 1
                continue
            wins += int(b["strict_task_success"] and not a["strict_task_success"])
            losses += int(a["strict_task_success"] and not b["strict_task_success"])
            changed += int(a["answer"] != b["answer"])
            if label.startswith(("knowledge_", "parameter_only_")):
                for attr in ("selected",):
                    if a[attr] != b[attr]:
                        raise ValueError("parameter comparison changed selection")
                for attr in (
                    "input_ids_digest",
                    "delivered_evidence",
                    "derived_evidence",
                ):
                    if a["receipt"][attr] != b["receipt"][attr]:
                        raise ValueError("parameter comparison changed model input")
        bound = old_effects["contrasts"][label]["all"]
        if any(
            bound[k] != v
            for k, v in (
                ("wins", wins),
                ("losses", losses),
                ("missing_pairs", missing),
                ("changed_answers", changed),
            )
        ):
            raise ValueError("published effect comparison differs from original")
        contrasts[label] = dict(
            wins=wins, losses=losses, missing_pairs=missing, changed_answers=changed
        )
    bad_citations = {
        arm: sum(bool(unsupported.get((q, arm))) for q in questions) for arm in ARMS
    }
    # Wrong labels on zero delivered sources are structural unsupported claims,
    # not an independently measured entailment precision.
    module_rejected = (
        contrasts["knowledge_vs_same_evidence"]["wins"]
        <= contrasts["knowledge_vs_same_evidence"]["losses"]
        or contrasts["parameter_only_vs_empty"]["wins"]
        <= contrasts["parameter_only_vs_empty"]["losses"]
        or bad_citations["parameter_only"] > 0
    )
    return dict(
        schema="hepta.source-write.retrospective.v1",
        exact_original_generating_commit=source,
        original_answers_sha256=hashlib.sha256(
            found["tasks/raw-answers.jsonl"]
        ).hexdigest(),
        original_snapshot_sha256=hashlib.sha256(
            found["snapshot/READY.json"]
        ).hexdigest(),
        original_task_count=len(questions),
        original_generation_calls=len(raw),
        actual_optimizer_updates=training["steps"],
        source_examples=training["examples"],
        examples_visited_once=sched["visits_per_example"].count(1),
        examples_visited_twice=sched["visits_per_example"].count(2),
        unvisited_examples=len(sched["unvisited_examples"]),
        early_training_loss_mean=sum(training["losses"][:8])
        / min(8, len(training["losses"])),
        late_training_loss_mean=sum(training["losses"][-8:])
        / min(8, len(training["losses"])),
        actual_adapter_delta_squared_norm=training["adapter_delta_squared_norm"],
        strict_task_successes=totals,
        paired_effects=contrasts,
        unsupported_empty_context_citation_answers=bad_citations,
        research_parameter_candidate_rejected=module_rejected,
        reason_codes=(
            (
                ["no_independent_knowledge_gain"]
                if contrasts["knowledge_vs_same_evidence"]["wins"]
                <= contrasts["knowledge_vs_same_evidence"]["losses"]
                else []
            )
            + (
                ["no_parameter_only_task_gain"]
                if contrasts["parameter_only_vs_empty"]["wins"]
                <= contrasts["parameter_only_vs_empty"]["losses"]
                else []
            )
            + (
                ["empty_context_hallucinated_citations"]
                if bad_citations["parameter_only"]
                else []
            )
        ),
        output_source="pinned_completed_historical_model_execution",
        new_model_calls=0,
        independent_new_source_families=0,
        semantic_citation_precision=None,
        significance_established=False,
        production_accepted=False,
    )


def run(archive, expected_sha256, generating_commit, destination):
    if destination.exists():
        raise ValueError("audit output must not overwrite an older result")
    data = diagnose(checked_archive(archive, expected_sha256), generating_commit)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--generating-commit", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.artifact, args.artifact_sha256, args.generating_commit, args.output
            )
        )
    )
