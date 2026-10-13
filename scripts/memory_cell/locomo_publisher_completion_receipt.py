"""Fail-closed postrun audit of 16 REAL privileged-support LoCoMo Reader calls.

The original publisher-supported source selection is label-privileged; this
receipt neither certifies independent source sufficiency nor trains/admits a
MemoryCell. It never opens publisher answer text or changes Reader responses.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

RUN_SHA = "2db775a9b423f5d53c2ec1cf69d4e67da02e35bd"
READER_SHA = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
BASELINE_READER_COMMIT = "96b5ec37b82f87d445740403e07e3705e9850955"
BASELINE_RAW_SHA = "b13f70b5b8ff0664d7a446b11b2a474702d61a50348534ca1b26cc295a0e9bb2"
EXPECTED = {
    "plan": "66bc69310096b0226e90a8503df9d8d29645766066bbcf6acda7fd32241fb2b0",
    "reader": "14dc63bfb0e25b8b15f7b48ba8e1afd4cef4d13f8617d08d28a533baa7a202a0",
    "score": "cb753cd17db2b06027393175097d5a74b3fdfba459698f14d243d6ec14642698",
}
REFUSAL = "I do not have enough evidence."
MARKER = re.compile(r"\[E[1-9][0-9]*\]")
PROFILE = "hepta.locomo.publisher-support-postrun.v1"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate JSON field")
            out[key] = value
        return out

    def bad(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def read_archive(path, expected, *, has_manifest):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_777_216:
        raise ValueError("missing or unbounded archive")
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError("externally pinned ZIP SHA mismatch")
    files = {}
    with zipfile.ZipFile(path) as stream:
        members = stream.infolist()
        if not 1 <= len(members) <= 48 or sum(x.file_size for x in members) > 8_000_000:
            raise ValueError("unbounded ZIP member census")
        for member in members:
            name = member.filename
            posix = PurePosixPath(name)
            if (
                posix.is_absolute()
                or ".." in posix.parts
                or name != posix.as_posix()
                or "\\" in name
                or member.is_dir()
                or stat.S_ISLNK(member.external_attr >> 16)
                or name in files
            ):
                raise ValueError("unsafe or duplicate archive source")
            files[name] = stream.read(member)
    if has_manifest:
        manifest = files.pop("SHA256SUMS", None)
        if manifest is None:
            raise ValueError("missing internal archive manifest")
        declared = {}
        for line in manifest.decode().splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
            if not match or match[2] in declared:
                raise ValueError("malformed or duplicated SHA256SUMS entry")
            declared[match[2]] = match[1]
        if set(declared) != set(files) or any(
            sha(files[n]) != h for n, h in declared.items()
        ):
            raise ValueError("archive member integrity failure")
    return files


def refusal_shape(answer):
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("missing original model response")
    clean = answer.strip()
    if clean == REFUSAL:
        return "strict_refusal"
    if REFUSAL in clean:
        return "mixed_refusal_and_extra_text"
    return "no_canonical_refusal"


def audit(plan_zip, reader_zip, score_zip):
    plan_files = read_archive(plan_zip, EXPECTED["plan"], has_manifest=False)
    reader_files = read_archive(reader_zip, EXPECTED["reader"], has_manifest=True)
    score_files = read_archive(score_zip, EXPECTED["score"], has_manifest=True)
    if set(plan_files) != {"commit.txt", "ids/plan.json"}:
        raise ValueError("privileged plan file census drift")
    if (
        plan_files["commit.txt"].decode().strip() != RUN_SHA
        or reader_files["tested-commit.txt"].decode().strip() != RUN_SHA
        or score_files["score-commit.txt"].decode().strip() != RUN_SHA
    ):
        raise ValueError("mismatched original generating source")
    plan = strict_json(plan_files["ids/plan.json"])
    ready = strict_json(reader_files["run/READY.json"])
    report = strict_json(score_files["result/report.json"])
    original_raw = reader_files["run/raw-answers.jsonl"]
    if (
        ready["generating_commit"] != RUN_SHA
        or ready["reader_identity"] != READER_SHA
        or ready["privileged_plan_sha256"] != sha(plan_files["ids/plan.json"])
        or ready["raw_sha256"] != sha(original_raw)
        or ready["succeeded"] != 16
        or ready["planned"] != 16
        or ready["failed"] != 0
        or ready["unavailable"] != 0
        or ready["weight_updates"] != 0
        or ready["original_gold_answers_accessible_to_generator"] is not False
        or ready["publisher_support_retrieval_privileged"] is not True
        or ready["production_accepted"] is not False
        or plan["publisher_support_selection_is_privileged"] is not True
        or plan["independent_source_review"] is not False
        or report["generating_commit"] != RUN_SHA
        or report["reader_identity"] != READER_SHA
        or report["original_reader_commit"] != BASELINE_READER_COMMIT
        or report["original_32_answers_sha256"] != BASELINE_RAW_SHA
        or report["privileged_16_answers_sha256"] != sha(original_raw)
        or report["privileged_source_selection"] is not True
        or report["publisher_support_not_independent_sufficiency"] is not True
        or report["independent_family_n"] != 0
        or report["production_accepted"] is not False
        or report["semantic_citation_precision"] is not None
        or report["model_calls_executed"] != 16
    ):
        raise ValueError("model source, privilege, or no-go boundary mismatch")
    cases = {x["question_id"]: x for x in plan["cases"]}
    raw = [strict_json(line) for line in original_raw.decode().splitlines()]
    if len(plan["cases"]) != 16 or len(cases) != 16 or len(raw) != 16:
        raise ValueError("incomplete publisher plan/model answer census")
    seen = set()
    families = set()
    refusal = Counter()
    cited = 0
    input_tokens = generated_tokens = 0
    reader_seconds = 0.0
    for row in raw:
        qid = row["question_id"]
        if qid not in cases or qid in seen or row["status"] != "succeeded":
            raise ValueError("duplicate or unavailable original inference")
        seen.add(qid)
        case = cases[qid]
        families.add(case["family_proxy_digest"])
        if (
            row["selected"] != case["selected"]
            or row["mode"] != case["mode"]
            or row["family_proxy_digest"] != case["family_proxy_digest"]
            or row["source_census_sha256"] != case["source_census_sha256"]
            or row["mode"] not in ("publisher_support", "publisher_refusal_support")
        ):
            raise ValueError("privileged plan/executed sources changed")
        rec = row["receipt"]
        evidence = rec["delivered_evidence"]
        if (
            rec["reader_identity"] != READER_SHA
            or rec["reader_profile"] != ready["reader_profile"]
            or rec["token_limit"] != 2048
            or rec["trainable_parameters"] != 0
            or rec["answer_postprocessed"] is not False
            or rec["production_accepted"] is not False
            or not 0 < rec["generated_tokens"] <= 64
            or not 0 < rec["input_tokens"] <= 2048
            or len(evidence) != len(row["selected"])
            or [s["original_id"] for s in evidence] != row["selected"]
        ):
            raise ValueError("mismatched frozen reader/source evidence")
        allowed = set()
        for i, source in enumerate(evidence, 1):
            if (
                source["label"] != f"E{i}"
                or source["source_start"] != 0
                or source["source_end"] != len(source["excerpt"].encode("utf-8"))
                or not re.fullmatch(r"[0-9a-f]{64}", source["source_digest"])
            ):
                raise ValueError("non-original or shifted delivered evidence")
            allowed.add("[" + source["label"] + "]")
        markers = MARKER.findall(row["answer"])
        if any(marker not in allowed for marker in markers):
            raise ValueError("undelivered citation label in original answer")
        cited += bool(markers)
        refusal[row["mode"], refusal_shape(row["answer"])] += 1
        input_tokens += rec["input_tokens"]
        generated_tokens += rec["generated_tokens"]
        reader_seconds += rec["seconds"]
    if seen != set(cases) or len(families) != 2:
        raise ValueError("changed question or family-proxy denominator")
    controls = {}
    for baseline in ("lexical_k4", "lexical_k8"):
        stratum = report["contrasts"][baseline]
        all_rows = stratum["all"]
        if (
            all_rows["planned"] != 16
            or all_rows["complete"] != 16
            or all_rows["missing_or_unscored"] != 0
            or sum(all_rows[k] for k in ("wins", "losses", "ties")) != 16
            or not 0 <= all_rows["privileged_support_reader_f1"] <= 1
            or not 0 <= all_rows["original_retrieval_reader_f1"] <= 1
            or len(all_rows["all_planned_delta_bounds"]) != 2
            or not all(
                math.isclose(
                    value,
                    all_rows["privileged_support_reader_f1"]
                    - all_rows["original_retrieval_reader_f1"],
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                )
                for value in all_rows["all_planned_delta_bounds"]
            )
        ):
            raise ValueError("invalid real scored comparison denominator")
        controls[baseline] = {
            "baseline_token_f1": all_rows["original_retrieval_reader_f1"],
            "privileged_token_f1": all_rows["privileged_support_reader_f1"],
            "descriptive_delta": (
                all_rows["privileged_support_reader_f1"]
                - all_rows["original_retrieval_reader_f1"]
            ),
            "paired_wins": all_rows["wins"],
            "paired_losses": all_rows["losses"],
            "paired_ties": all_rows["ties"],
        }
    missing = report["contrasts"]["lexical_k4"]["support_missing_by_k4"]
    seen_support = report["contrasts"]["lexical_k4"]["support_seen_by_k4"]
    if (
        missing["planned"] != 5
        or seen_support["planned"] != 8
        or missing["missing_or_unscored"] != 0
        or seen_support["missing_or_unscored"] != 0
    ):
        raise ValueError("published support-visibility stratum drift")
    if (
        controls["lexical_k4"]["privileged_token_f1"]
        != controls["lexical_k8"]["privileged_token_f1"]
    ):
        raise ValueError("publisher score differs across original comparators")
    return {
        "schema": PROFILE,
        "generating_commit": RUN_SHA,
        "source_run": 38353622487,
        "exact_zip_sha256": EXPECTED,
        "original_model_calls": 16,
        "matched_public_family_proxies": len(families),
        "frozen_reader_identity": READER_SHA,
        "original_input_tokens": input_tokens,
        "original_generated_tokens": generated_tokens,
        "sum_original_reader_seconds": round(reader_seconds, 3),
        "answers_with_delivered_citation_label": cited,
        "refusal_shapes_by_mode": {
            mode: {shape: refusal[mode, shape] for shape in (
                "strict_refusal", "mixed_refusal_and_extra_text", "no_canonical_refusal"
            )}
            for mode in ("publisher_support", "publisher_refusal_support")
        },
        "original_matched_f1": controls,
        "publisher_privileged_support_visible_effect": {
            "k4_already_had_publisher_support": {
                "questions": seen_support["planned"],
                "lexical_f1": seen_support["original_retrieval_reader_f1"],
                "privileged_f1": seen_support["privileged_support_reader_f1"],
            },
            "k4_missing_publisher_support": {
                "questions": missing["planned"],
                "lexical_f1": missing["original_retrieval_reader_f1"],
                "privileged_f1": missing["privileged_support_reader_f1"],
            },
        },
        "publisher_source_selection_is_privileged": True,
        "new_independently_admitted_source_families": 0,
        "independent_semantic_citation_judgement": False,
        "parameter_memory_gain_established": False,
        "production_accepted": False,
        "research_disposition": (
            "NO_GO: diagnose frozen reader/format and source sufficiency "
            "on new independently reviewed histories before training"
        ),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("plan_zip", type=Path)
    p.add_argument("reader_zip", type=Path)
    p.add_argument("score_zip", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = audit(a.plan_zip, a.reader_zip, a.score_zip)
    with a.output.open("x", encoding="utf-8") as handle:
        json.dump(
            result,
            handle,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        handle.write("\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
