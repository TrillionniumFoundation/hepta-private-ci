"""Verify actual *incomplete* Qwen calibration without promoting it to a result.

No model is loaded; original GitHub Actions ZIP bytes and inner file manifests
must match their fixed external digests. A cancellation never becomes a smaller
valid calibration set or an inferred result for unobserved arms/questions.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

PARTIAL_ZIP_SHA = "129351221d56c9668c57e33f8dec79a6443c0252675752085538375b12ca25a8"
REFERENCE_ZIP_SHA = "831ce9658bafcbaf04f4a15879982e58317322f7cd5137724498d7d20df7bb98"
PARTIAL_COMMIT = "02c12b4aff0d589d10e5ed25d22b05d794ca96a0"
REFERENCE_COMMIT = "59f9eadd5cc919359079e04442f7343838a60057"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
READER_SHA = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
PROFILE_SHA = "8250c8c41ec4d27655b0193ac8a2429bbae9e66d1e40afbced758b0ad56db00d"
FIRST_QUESTION = "controlled_4b61ce33"
CALIBRATION_ARMS = ("k1", "k2", "k3", "k4", "k6")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verified_zip(path, pin):
    """External ZIP digest plus complete and exact inner SHA256SUMS census."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular immutable archive required")
    payload = path.read_bytes()
    if len(payload) > 16 * 1024 * 1024 or sha256(payload) != pin:
        raise ValueError("GitHub Actions archive bytes differ from external SHA")
    with zipfile.ZipFile(BytesIO(payload)) as stream:
        metadata = stream.infolist()
        names = set()
        for info in metadata:
            name = PurePosixPath(info.filename)
            if (info.is_dir() or info.filename != str(name)
                or name.is_absolute() or ".." in name.parts
                or "\\" in info.filename or str(name) in names
                or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError("unsafe or duplicate archived member")
            names.add(str(name))
        if not 2 <= len(names) <= 256 or "SHA256SUMS" not in names:
            raise ValueError("incomplete ZIP file census")
        declared = {}
        for line in stream.read("SHA256SUMS").decode("ascii").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
            if match is None:
                raise ValueError("malformed archived SHA list")
            expected, filename = match.groups()
            if filename in declared or filename not in names or filename == "SHA256SUMS":
                raise ValueError("unexpected archived SHA entry")
            declared[filename] = expected
            if sha256(stream.read(filename)) != expected:
                raise ValueError("original artifact member was modified")
        if set(declared) != names - {"SHA256SUMS"}:
            raise ValueError("incomplete original archived manifest")
        return {name: stream.read(name) for name in names}


def json_file(members, name):
    return json.loads(members[name].decode("utf-8"))


def lines(members, path):
    raw = members[path]
    if not raw.endswith(b"\n"):
        raise ValueError("unterminated model generation journal")
    rows = [json.loads(row.decode("utf-8")) for row in raw.splitlines()]
    if not rows:
        raise ValueError("missing actual model generation")
    return rows


def audit(partial_archive, reference_archive):
    partial = verified_zip(partial_archive, PARTIAL_ZIP_SHA)
    reference = verified_zip(reference_archive, REFERENCE_ZIP_SHA)
    if (partial["tested-commit.txt"].decode().strip() != PARTIAL_COMMIT
        or reference["tested-commit.txt"].decode().strip() != REFERENCE_COMMIT):
        raise ValueError("generating commit identity does not match external pin")
    plan = json_file(partial, "prep/calibration-plan.json")
    truth = json_file(partial, "prep/calibration-labels.json")
    sources = json_file(partial, "prep/calibration-sources.json")
    run = json_file(partial, "calibration/run.json")
    if (plan["historical_plan_sha256"] != PLAN_SHA
        or plan["source_commit"] != PARTIAL_COMMIT
        or run["source_commit"] != PARTIAL_COMMIT
        or plan["calibration_only"] is not True
        or plan["test_cases_materialized"] is not False
        or len(plan["cases"]) != 8 or len(truth) != 8
        or len({r["id"] for r in truth}) != 8
        or run["stage"] != "calibration"
        or run["test_tasks_opened"] is not False):
        raise ValueError("no exact original 8-question calibration contract")
    case = plan["cases"][0]
    target = {row["id"]: row for row in truth}[FIRST_QUESTION]
    original = {row["identity"]: row for row in sources}
    rows = lines(partial, "calibration/raw-answers.jsonl")
    expected_arms = ["k1", "k2", "k3", "k4"]
    if (len(rows) != 4
        or [r["arm"] for r in rows] != expected_arms
        or any(r["question_id"] != FIRST_QUESTION for r in rows)
        or case["query"]["identity"] != FIRST_QUESTION):
        raise ValueError("journal does not match actual 4/40-prefix cancellation")
    observed = []
    for row in rows:
        k = int(row["arm"][1:])
        receipt = row["receipt"]
        selected = case["candidate_ids"][:k]
        delivered = receipt["delivered_evidence"]
        if (row["status"] != "succeeded" or row["selected"] != selected
            or len(delivered) != len(selected)
            or [s["original_id"] for s in delivered] != selected
            or any(s["excerpt"] != original[s["original_id"]]["content"] for s in delivered)
            or receipt["reader_identity"] != READER_SHA
            or receipt["reader_profile"] != PROFILE_SHA
            or receipt["trainable_parameters"] != 0
            or receipt["answer_postprocessed"] is not False
            or row["citation_audit"]["request"]["answer"] != row["answer"]
            or receipt["seconds"] <= 0
            or not 1 <= receipt["input_tokens"] <= 2048
            or not 1 <= receipt["generated_tokens"] <= 64):
            raise ValueError("raw model answer or original source context changed")
        observed.append(dict(
            arm=row["arm"], question_id=FIRST_QUESTION,
            input_tokens=receipt["input_tokens"],
            generated_tokens=receipt["generated_tokens"],
            inference_seconds=receipt["seconds"],
            selected_sources=len(selected),
            annotated_support_covered=set(target["support"]).issubset(selected),
            strict_task_correct=False if target["expected"] not in row["answer"] else None,
            answer=row["answer"],
        ))
    if any(item["strict_task_correct"] is None for item in observed):
        raise ValueError("new answer needs original strict-grammar scorer, not guess")
    ref_rows = lines(reference, "run/raw-answers.jsonl")
    if (len(ref_rows) != 48
        or any(r["status"] != "succeeded" for r in ref_rows)
        or any(r["receipt"]["reader_identity"] != READER_SHA
               or r["receipt"]["reader_profile"] != PROFILE_SHA for r in ref_rows)
        or Counter(r["arm"] for r in ref_rows) != {
            "empty":8,"hybrid":8,"entity_time":8,"organized":8,
            "program_support":8,"without_prerequisite":8}):
        raise ValueError("reference 48-call reader receipt does not match frozen control")
    hybrid = [r for r in ref_rows if r["arm"] == "hybrid"]
    comparator = [r for r in hybrid if abs(r["receipt"]["input_tokens"] - 1370) <= 100]
    if not comparator:
        raise ValueError("no comparable historical prompt length")
    comparator_seconds = [r["receipt"]["seconds"] for r in comparator]
    from statistics import median
    result = {
        "schema": "hepta.memory-strong-rag.partial-cancellation-forensics.v1",
        "partial_run": 38111452963,
        "partial_artifact": 11696974258,
        "partial_outer_zip_sha256": PARTIAL_ZIP_SHA,
        "partial_raw_answers_sha256": sha256(partial["calibration/raw-answers.jsonl"]),
        "generating_source_commit": PARTIAL_COMMIT,
        "reference_run": 38063870516,
        "reference_artifact": 11674741321,
        "reference_outer_zip_sha256": REFERENCE_ZIP_SHA,
        "reference_source_commit": REFERENCE_COMMIT,
        "original_test_plan_sha256": PLAN_SHA,
        "same_frozen_reader_inventory_sha256": READER_SHA,
        "same_reader_profile_sha256": PROFILE_SHA,
        "planned_calibration_attempts": 40,
        "observed_calibration_attempts": 4,
        "missing_calibration_attempts": 36,
        "generation_succeeded": 4,
        "observed_strict_success": 0,
        "observed_support_covered": 4,
        "actual_reader_seconds_total": sum(x["inference_seconds"] for x in observed),
        "historical_hybrid_comparable_prompt_count": len(comparator),
        "historical_hybrid_comparable_median_seconds": median(comparator_seconds),
        "old_host_to_reference_k4_duration_ratio": observed[-1]["inference_seconds"] / median(comparator_seconds),
        "old_host_k1_exceeds_current_180s_gate": observed[0]["inference_seconds"] > 180,
        "incomplete_calibration": True,
        "frozen_k_selected": None,
        "model_capacity_gain_established": False,
        "reader_efficacy_established": False,
        "statistical_superiority": False,
        "independent_semantic_review": False,
        "production_accepted": False,
        "attempts": observed,
    }
    return result


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("partial_zip", type=Path)
    p.add_argument("reference_zip", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.write_text(json.dumps(audit(args.partial_zip,args.reference_zip),
                                      ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")


if __name__ == "__main__":
    main()
