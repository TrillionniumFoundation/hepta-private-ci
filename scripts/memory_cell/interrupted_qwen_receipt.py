"""Fail-closed, model-free receipt for the original interrupted Qwen calibration.

Never opens gold labels or scores answer correctness. This is not a future-source,
semantic citation, model-capability, or production acceptance certificate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

ARCHIVE_SHA256 = "129351221d56c9668c57e33f8dec79a6443c0252675752085538375b12ca25a8"
SOURCE_COMMIT = "02c12b4aff0d589d10e5ed25d22b05d794ca96a0"
READER_IDENTITY = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
CALIBRATION_PLAN_SHA256 = (
    "205c9a46b3776a7e8f3063b8eb63cf7a0f5cd4647a1947b6e90d2b2e0d570e45"
)
EXPECTED_K = (1, 2, 3, 4, 6)


def canonical_digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def strict_json(raw):
    def unique(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise ValueError("duplicate JSON key")
            obj[k] = v
        return obj

    def reject(value):
        raise ValueError("nonfinite number in journal")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject)


def verify_members(archive):
    """Require an externally pinned outer ZIP and a complete inner SHA census."""
    raw = Path(archive).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("archive outer SHA differs from the completed run")
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        if not 1 <= len(entries) <= 64 or sum(i.file_size for i in entries) > 8_000_000:
            raise ValueError("unsafe archive bounds")
        names = set()
        for entry in entries:
            p = PurePosixPath(entry.filename)
            if (
                p.is_absolute()
                or ".." in p.parts
                or "\\" in entry.filename
                or entry.is_dir()
                or stat.S_ISLNK(entry.external_attr >> 16)
                or entry.filename in names
            ):
                raise ValueError("unsafe or duplicate archived file")
            names.add(entry.filename)
        if "SHA256SUMS" not in names:
            raise ValueError("missing immutable-file manifest")
        pins = {}
        for line in z.read("SHA256SUMS").decode("utf-8").splitlines():
            m = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
            if not m or m.group(2) in pins:
                raise ValueError("invalid or duplicated manifest entry")
            pins[m.group(2)] = m.group(1)
        if set(pins) != names - {"SHA256SUMS"}:
            raise ValueError("archive contains extra or missing files")
        for name, sha in pins.items():
            if hashlib.sha256(z.read(name)).hexdigest() != sha:
                raise ValueError("inner file SHA differs from archived manifest")
        return {name: z.read(name) for name in names}


def audit(archive):
    members = verify_members(archive)
    if members["tested-commit.txt"].decode().strip() != SOURCE_COMMIT:
        raise ValueError("archive emitting commit differs")
    plan_raw = members["prep/calibration-plan.json"]
    if hashlib.sha256(plan_raw).hexdigest() != CALIBRATION_PLAN_SHA256:
        raise ValueError("unregistered calibration plan")
    plan = strict_json(plan_raw)
    run = strict_json(members["calibration/run.json"])
    if (
        plan["source_commit"] != SOURCE_COMMIT
        or plan["calibration_only"] is not True
        or plan["test_cases_materialized"] is not False
        or tuple(plan["ks"]) != EXPECTED_K
        or len(plan["cases"]) != 8
        or run["source_commit"] != SOURCE_COMMIT
        or run["stage"] != "calibration"
        or run["test_tasks_opened"] is not False
        or run["optimizer_executed"] is not False
        or run["production_accepted"] is not False
        or run["model"]["inventory_digest"] != READER_IDENTITY
        or run["calibration_sha256"] != CALIBRATION_PLAN_SHA256
        or run["model_stage_sha256"]
        != hashlib.sha256(members["stage.json"]).hexdigest()
    ):
        raise ValueError("calibration plan, reader or provenance drift")
    forbidden = {
        "calibration/scored-answers.json",
        "calibration/frozen-policy.json",
        "evaluation/raw-answers.jsonl",
        "observations/labels.json",
        "plan/plan.json",
    }
    if forbidden & set(members):
        raise ValueError("partial reader artifact contains a future or scored result")
    cases = {x["query"]["identity"]: x for x in plan["cases"]}
    if len(cases) != 8:
        raise ValueError("duplicate declared calibration question")
    sources = strict_json(members["prep/calibration-sources.json"])
    originals = {d["identity"]: d for d in sources}
    if len(originals) != len(sources):
        raise ValueError("duplicate original source")
    raw_answers = members["calibration/raw-answers.jsonl"]
    if not raw_answers.endswith(b"\n"):
        raise ValueError("unfinished original-answer JSONL line")
    rows = [strict_json(line) for line in raw_answers.splitlines()]
    keys = set()
    inputs = 0
    tokens = 0
    seconds = 0.0
    by_arm = {}
    for row in rows:
        key = (row["question_id"], row["arm"])
        if (
            key in keys
            or key[0] not in cases
            or key[1] not in {f"k{k}" for k in EXPECTED_K}
        ):
            raise ValueError("unexpected, duplicate or out-of-census reader answer")
        keys.add(key)
        case = cases[key[0]]
        if (
            row["status"] != "succeeded"
            or row["candidate_digest"] != case["candidate_digest"]
            or row["selected"] != case["candidate_ids"][: int(key[1][1:])]
        ):
            raise ValueError("altered original candidate ranking or failed call")
        receipt = row["receipt"]
        delivered = receipt["delivered_evidence"]
        if (
            len(delivered) != len(row["selected"])
            or receipt["reader_identity"] != READER_IDENTITY
            or receipt["token_limit"] != 2048
            or receipt["answer_postprocessed"] is not False
            or receipt["trainable_parameters"] != 0
            or receipt["production_accepted"] is not False
            or receipt["semantic_citation_precision"] is not None
        ):
            raise ValueError("reader identity, delivery count or frozen status differs")
        for index, (identity, source) in enumerate(zip(row["selected"], delivered), 1):
            original = originals.get(identity)
            if (
                original is None
                or source["original_id"] != identity
                or source["label"] != f"E{index}"
                or source["root"] != original["root"]
                or source["excerpt"] != original["content"]
                or source["source_digest"] != canonical_digest(original["content"])
            ):
                raise ValueError(
                    "delivered evidence not equal to original source bytes"
                )
        citation = row["citation_audit"]
        if (
            citation["request"]["answer"] != row["answer"]
            or citation["request"]["prompt_digest"] != receipt["input_ids_digest"]
            or citation["judgement"] is not None
            or citation["production_accepted"] is not False
        ):
            raise ValueError("citation queue unbound to raw generation")
        elapsed = receipt["seconds"]
        if (
            not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed)
            or elapsed < 0
        ):
            raise ValueError("invalid model duration")
        if type(receipt["input_tokens"]) is not int or receipt["input_tokens"] <= 0:
            raise ValueError("invalid model input token count")
        inputs += 1
        tokens += receipt["input_tokens"]
        seconds += elapsed
        by_arm[row["arm"]] = dict(
            input_tokens=receipt["input_tokens"],
            generated_tokens=receipt["generated_tokens"],
            model_seconds=round(elapsed, 3),
        )
    return dict(
        schema="hepta.memory-strong-rag.interrupted-calibration-audit.v1",
        source_commit=SOURCE_COMMIT,
        archive_sha256=ARCHIVE_SHA256,
        original_answers_sha256=hashlib.sha256(raw_answers).hexdigest(),
        manifest_file_count=len(members) - 1,
        model_identity=READER_IDENTITY,
        calibration_questions_planned=8,
        original_reader_calls_planned=40,
        observed_calls=inputs,
        missing_calls=40 - inputs,
        observed_question_ids=sorted({qid for qid, _ in keys}),
        observed_arms=sorted({arm for _, arm in keys}),
        input_tokens=tokens,
        model_seconds=round(seconds, 3),
        per_arm=dict(sorted(by_arm.items())),
        selected_k=None,
        calibration_complete=False,
        evaluation_started=False,
        label_correctness_scored=False,
        independent_semantic_review=False,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.archive)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
