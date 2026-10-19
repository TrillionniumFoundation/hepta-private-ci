"""Read-only cross-version citation audit of a *completed* frozen Qwen run.

The generator and auditor SHAs are separate, never relabelled. This does not
mint a semantic citation judgment, new model response or production admission.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile

SCHEMA = "hepta.memory-strong-rag.posthoc-citation-audit.v1"
ORIGINAL_ZIP_SHA = "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b"
MAX_ZIP_BYTES = 128 * 1024 * 1024
MAX_FILES = 512


def sha_file(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular immutable archive file required")
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def checked_archive(path, expected_sha, output):
    """Verify an externally pinned ZIP and safely materialize its full census."""
    if Path(path).stat().st_size > MAX_ZIP_BYTES:
        raise ValueError("oversized research archive")
    if (
        not re.fullmatch(r"[0-9a-f]{64}", expected_sha)
        or sha_file(path) != expected_sha
    ):
        raise ValueError("archived ZIP bytes differ from the external pin")
    seen, total = set(), 0
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if not members or len(members) > MAX_FILES:
            raise ValueError("invalid archive member count")
        for member in members:
            name = member.filename
            part = PurePosixPath(name)
            if (
                part.is_absolute()
                or not name
                or "\\" in name
                or ".." in part.parts
                or name.startswith("./")
                or stat.S_ISLNK(member.external_attr >> 16)
            ):
                raise ValueError("unsafe ZIP member name/type")
            if member.is_dir():
                continue
            if name in seen or member.file_size > MAX_ZIP_BYTES:
                raise ValueError("duplicate or oversized ZIP member")
            seen.add(name)
            total += member.file_size
            if total > MAX_ZIP_BYTES:
                raise ValueError("inflated archive exceeds bound")
            dest = Path(output).joinpath(*part.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Extract only verified, bounded regular files. Never extract() paths.
            dest.write_bytes(archive.read(member))
    if not seen:
        raise ValueError("empty research archive")
    return len(seen)


def check_lineage(
    generating_commit,
    frozen,
    run,
    report,
    inventory,
    *,
    plan_sha,
    policy_sha,
    attempts,
):
    """Do not attribute post-hoc calculations to a different generating SHA."""
    if not re.fullmatch(r"[0-9a-f]{40}", generating_commit):
        raise ValueError("exact generation SHA required")
    if (
        frozen.get("source_commit") != generating_commit
        or run.get("source_commit") != generating_commit
        or report.get("source_commit") != generating_commit
        or frozen.get("original_test_plan_sha256") != plan_sha
        or run.get("test_plan_sha256") != plan_sha
        or run.get("policy_sha256") != policy_sha
        or frozen.get("reader_identity") != inventory.get("inventory_digest")
        or run.get("phase") != "evaluation"
        or run.get("training_during_query") is not False
        or frozen.get("frozen_before_evaluation") is not True
        or frozen.get("production_accepted") is not False
        or report.get("production_accepted") is not False
        or report.get("total_attempts") != attempts
        or report.get("test_task_count") != 8
    ):
        raise ValueError("generator policy/model/source identity drift")


def audit(
    original_zip,
    result_zip,
    *,
    generating_commit,
    result_zip_sha,
    auditor_commit,
):
    if not re.fullmatch(r"[0-9a-f]{40}", auditor_commit):
        raise ValueError("exact auditor source SHA required")
    from event_memory_trial import read
    from historical_event_citation_chain import audit_evaluation
    from native import Question, digest
    from native_citation import capture_native
    from strong_rag_receipt import (
        _check_row,
        _check_scored,
        _doc_scope,
        _json_file,
        _raw_lines,
        verify_manifest,
    )
    from strong_rag_repeatability import audit_repeats
    from strong_rag_trial import (
        EVAL_ARMS,
        HISTORIC_COLLECTION_SHA,
        HISTORIC_PLAN_SHA,
        _stats,
        eval_selections,
        file_sha,
        freeze_single_hop,
    )

    with tempfile.TemporaryDirectory(prefix="strong-rag-posthoc-") as tmp:
        root = Path(tmp)
        original, generated = root / "source", root / "generated"
        original.mkdir()
        generated.mkdir()
        checked_archive(original_zip, ORIGINAL_ZIP_SHA, original)
        checked_archive(result_zip, result_zip_sha, generated)
        source_count = verify_manifest(original)
        artifact_count = verify_manifest(generated)
        if (generated / "tested-commit.txt").read_text().strip() != generating_commit:
            raise ValueError("uploaded artifact not generated by supplied commit")
        plan = read(original / "plan/plan.json", HISTORIC_PLAN_SHA)
        collection = read(
            original / "observations/collection.json", HISTORIC_COLLECTION_SHA
        )
        specs = read(
            original / "observations/questions.json",
            collection["files"]["questions.json"],
        )
        labels = read(
            original / "observations/labels.json",
            collection["files"]["labels.json"],
        )
        source_view = read(original / "plan/source-view.json", plan["source_view_sha"])
        documents = {d["identity"]: d for d in source_view}
        if len(documents) != 108 or len(specs) != 16 or len(labels) != 16:
            raise ValueError("original public source/target census differs")
        cases, hop_receipt = freeze_single_hop(
            plan["cases"], original / "observations", documents
        )
        if len(cases) != 8:
            raise ValueError("original development test census drift")
        if hop_receipt != _json_file(generated / "evaluation/single-hop-control.json"):
            raise ValueError("single-hop selector overlay differs from archived source")
        frozen_path = generated / "calibration/frozen-policy.json"
        frozen = _json_file(frozen_path)
        run = _json_file(generated / "evaluation/run.json")
        reported = _json_file(generated / "evaluation/report.json")
        inventory = _json_file(generated / "inventory.json")
        question_ids = [c["query"]["identity"] for c in cases]
        count = len(cases) * len(EVAL_ARMS)
        check_lineage(
            generating_commit,
            frozen,
            run,
            reported,
            inventory,
            plan_sha=HISTORIC_PLAN_SHA,
            policy_sha=file_sha(frozen_path),
            attempts=count,
        )
        raw = _raw_lines(generated / "evaluation/raw-answers.jsonl", expected=count)
        scored = _json_file(generated / "evaluation/scored-answers.json")
        truths = [row for row in labels if row["id"] in set(question_ids)]
        replayed = _check_scored(raw, scored, truths, question_ids, EVAL_ARMS)
        by_qid = {c["query"]["identity"]: c for c in cases}
        selections = {
            qid: eval_selections(c, frozen["selected_k"]) for qid, c in by_qid.items()
        }
        profiles = set()
        for row in raw:
            case = by_qid[row["question_id"]]
            selected = selections[row["question_id"]][row["arm"]]
            source_pool = _doc_scope(source_view, case["query"]["scope"])
            _check_row(
                row,
                case,
                selected,
                source_pool,
                inventory["inventory_digest"],
                profiles=profiles,
            )
            if row["status"] == "succeeded":
                seed = digest((HISTORIC_PLAN_SHA, file_sha(frozen_path)))
                canonical = capture_native(
                    Question(**case["query"]),
                    row["answer"],
                    dict(
                        input_ids_sha256=row["receipt"]["input_ids_digest"],
                        delivered_evidence=row["receipt"]["delivered_evidence"],
                    ),
                    experiment_digest=digest((seed, row["arm"])),
                    family_digest=digest(case["query"]["family"]),
                )
                if canonical != row["citation_audit"]:
                    raise ValueError("original citation queue not reproducible")
        if len(profiles) != 1:
            raise ValueError("mixed reader prompt profiles")
        summary, _ = _stats(replayed, EVAL_ARMS, question_ids)
        if summary != reported["success_by_arm"]:
            raise ValueError("posted model task metrics differ from raw answers")
        consistency = audit_repeats(replayed, question_ids, EVAL_ARMS)
        if consistency != reported["same_prompt_consistency"]:
            raise ValueError("identical-source stability receipt changed")
        formal = audit_evaluation(
            replayed,
            specs,
            truths,
            documents,
            expected_qids=question_ids,
            arms=EVAL_ARMS,
        )
        for arm in EVAL_ARMS:
            if (
                formal["by_arm"][arm]["strict_task_success"]
                != summary[arm]["strict_success"]
            ):
                raise ValueError("post-hoc citation/task denominator mismatch")
        if (
            "formal_citation_chain" in reported
            and formal != reported["formal_citation_chain"]
        ):
            raise ValueError("generating job and auditor citation metrics disagree")
        return dict(
            schema=SCHEMA,
            generating_commit=generating_commit,
            auditor_commit=auditor_commit,
            historical_plan_sha256=HISTORIC_PLAN_SHA,
            historical_collection_sha256=HISTORIC_COLLECTION_SHA,
            original_zip_sha256=ORIGINAL_ZIP_SHA,
            generating_artifact_zip_sha256=result_zip_sha,
            source_files_verified=source_count,
            generating_files_verified=artifact_count,
            planned_calibration_calls=40,
            planned_test_calls=count,
            observed_test_calls=len(raw),
            reader_profile=next(iter(profiles)),
            task_success_by_arm={
                arm: summary[arm]["strict_success"] for arm in EVAL_ARMS
            },
            posthoc_formal_citation_chain=formal,
            model_answers_generated_by_auditor=0,
            original_answer_bytes_modified=False,
            independent_semantic_judge=False,
            statistical_superiority=False,
            production_accepted=False,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("historical_input_zip", type=Path)
    parser.add_argument("generating_result_zip", type=Path)
    parser.add_argument("--generating-commit", required=True)
    parser.add_argument("--result-zip-sha256", required=True)
    parser.add_argument("--auditor-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = audit(
        args.historical_input_zip,
        args.generating_result_zip,
        generating_commit=args.generating_commit,
        result_zip_sha=args.result_zip_sha256,
        auditor_commit=args.auditor_commit,
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(
            receipt,
            stream,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(
        json.dumps(
            {
                "generating_commit": receipt["generating_commit"],
                "reader_call_count": receipt["observed_test_calls"],
                "auditor_commit": receipt["auditor_commit"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
