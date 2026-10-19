"""Read-only verification of the ACTUALLY uploaded LoCoMo reviewer handoff.

Pin the uploaded stage-1, stage-2 and manifest ZIPs and the original
pretrained Qwen answer ZIP; never infer independence, fill human verdicts,
open benchmark answers, make a reader call or qualify production.
"""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SCHEMA = "hepta.memorycell.locomo-uploaded-two-stage-handoff-audit.v1"
WORKLIST_SCHEMA = "hepta.memorycell.locomo-source-first-review.v1"
PINS = {
    "source": "d0d2fc3ed8ed4ad01ad34beb2764954051dfad19dd2a7fd9673169b2709c2b63",
    "answer": "0f57e7d79208dd6cf7e56ae13cc804bc3e41421641e7410a743b5423b327eb45",
    "manifest": "0c16df842da612856d89cc6719d191634f300934d7e1b52bd0615cfaadd08955",
    "reader": "7160ede72114b04135e544fb687a804dc0c4852834cf1695440a75b85214bf48",
}
ARTIFACTS = {
    "source": 11779535979,
    "answer": 11779431120,
    "manifest": 11779426223,
    "reader": 11763718022,
}
READER_COMMIT = "96b5ec37b82f87d445740403e07e3705e9850955"
READER_ID = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
REVIEW_COMMIT = "72a145cc5f12586035d3728374264c0c7a830778"
CITATION = re.compile(r"\[E([1-9][0-9]{0,5})\]")


def checked_json(data: bytes):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate JSON field")
            out[key] = value
        return out

    return json.loads(
        data,
        object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError("nonfinite JSON")
        ),
    )


def load_zip(path: Path, expected: str):
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 16 * 1024 * 1024
    ):
        raise ValueError("regular bounded original uploaded ZIP required")
    data = path.read_bytes()
    if sha256(data).hexdigest() != expected:
        raise ValueError("uploaded ZIP hash differs from external pin")
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        if (
            not 1 <= len(entries) <= 48
            or sum(i.file_size for i in entries) > 24 * 1024 * 1024
        ):
            raise ValueError("unbounded ZIP census")
        out = {}
        for entry in entries:
            name = entry.filename
            pp = PurePosixPath(name)
            if (
                entry.is_dir()
                or pp.is_absolute()
                or ".." in pp.parts
                or str(pp) != name
                or "\\" in name
                or name in out
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise ValueError("unsafe or repeated ZIP member")
            out[name] = z.read(entry)
    return out


def check_sha256sums(files, prefix=""):
    path = prefix + "SHA256SUMS"
    if path not in files:
        raise ValueError("missing archived SHA256SUMS")
    declared = {}
    for line in files[path].decode().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
        if match is None:
            raise ValueError("bad SHA256SUMS line")
        digest, name = match.groups()
        if name in declared:
            raise ValueError("duplicate SHA256SUMS path")
        declared[name] = digest
    expected = {name.removeprefix(prefix) for name in files if name != path}
    if set(declared) != expected:
        raise ValueError("missing or extra archive member")
    for name, digest in declared.items():
        if sha256(files[prefix + name]).hexdigest() != digest:
            raise ValueError("modified ZIP member")
    return len(declared)


def audit(source, answer, manifest, reader):
    source_files = load_zip(source, PINS["source"])
    answer_files = load_zip(answer, PINS["answer"])
    manifest_files = load_zip(manifest, PINS["manifest"])
    reader_files = load_zip(reader, PINS["reader"])
    if set(source_files) != {"sufficiency-only.json"} or set(answer_files) != {
        "answer-and-citation.json"
    }:
        raise ValueError("worklist role file census changed")
    if set(manifest_files) != {
        "locomo-unreviewed-worklists/SHA256SUMS",
        "locomo-unreviewed-worklists/manifest.json",
        "locomo-unreviewed-worklists/auditor-source-commit.txt",
        "locomo-worklist-manifest.log",
    }:
        raise ValueError("worklist manifest ZIP census drift")
    reader_members = check_sha256sums(reader_files)
    declared = (
        manifest_files["locomo-unreviewed-worklists/SHA256SUMS"].decode().splitlines()
    )
    sums = {}
    for line in declared:
        match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
        if match is None:
            raise ValueError("invalid worklist manifest line")
        h, key = match.groups()
        if key in sums:
            raise ValueError("duplicate worklist manifest line")
        sums[key] = h
    if set(sums) != {
        "sufficiency-only.json",
        "answer-and-citation.json",
        "manifest.json",
    }:
        raise ValueError("worklist manifest not complete")
    if (
        sums["sufficiency-only.json"]
        != sha256(source_files["sufficiency-only.json"]).hexdigest()
        or sums["answer-and-citation.json"]
        != sha256(answer_files["answer-and-citation.json"]).hexdigest()
        or sums["manifest.json"]
        != sha256(
            manifest_files["locomo-unreviewed-worklists/manifest.json"]
        ).hexdigest()
    ):
        raise ValueError("uploaded worklist differs from generation manifest")
    if (
        manifest_files["locomo-unreviewed-worklists/auditor-source-commit.txt"]
        .decode()
        .strip()
        != REVIEW_COMMIT
    ):
        raise ValueError("worklist issuing source changed")
    meta = checked_json(manifest_files["locomo-unreviewed-worklists/manifest.json"])
    if (
        meta.get("schema") != WORKLIST_SCHEMA
        or meta.get("generating_reader_source_commit") != READER_COMMIT
        or meta.get("model_identity") != READER_ID
        or meta.get("sufficiency_worklist_sha256") != sums["sufficiency-only.json"]
        or meta.get("answer_citation_worklist_sha256")
        != sums["answer-and-citation.json"]
        or meta.get("original_source_artifacts_sha256")
        != {
            "public": "51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37",
            "decisions": "3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097",
            "reader": PINS["reader"],
        }
        or meta.get("original_model_answers") != 32
        or meta.get("original_public_question_count") != 16
        or meta.get("original_published_source_family_proxies") != 2
        or meta.get("source_sufficiency_decisions") != 0
        or meta.get("answer_citation_review_decisions") != 0
        or meta.get("independent_human_semantic_judgement") is not False
        or meta.get("production_accepted") is not False
        or meta.get("training_permitted") is not False
    ):
        raise ValueError("human review worklist falsely promoted or drifted")
    if reader_files["tested-commit.txt"].decode().strip() != READER_COMMIT:
        raise ValueError("original reader generating source differs")
    original = [
        checked_json(line)
        for line in reader_files["run/raw-answers.jsonl"].splitlines()
        if line
    ]
    if len(original) != 32 or any(row.get("status") != "succeeded" for row in original):
        raise ValueError("incomplete original Qwen reader attempts")
    reader_by_key = {}
    pairs = {}
    for row in original:
        if (
            row["receipt"].get("reader_identity") != READER_ID
            or row["receipt"].get("answer_postprocessed") is not False
            or row["receipt"].get("trainable_parameters") != 0
            or row["receipt"].get("production_accepted") is not False
        ):
            raise ValueError("original Qwen reader identity/optimization drift")
        key = (row["family_proxy_digest"], tuple(row["selected"]))
        if key in reader_by_key:
            raise ValueError("ambiguous original selected source set")
        reader_by_key[key] = row
        pairs.setdefault(row["question_id"], {})[row["arm"]] = row
    if len(pairs) != 16 or any(
        set(v) != {"lexical_k4", "lexical_k8"}
        or v["lexical_k4"]["selected"] != v["lexical_k8"]["selected"][:4]
        for v in pairs.values()
    ):
        raise ValueError("original frozen Reader k4/k8 population changed")
    sufficiency = checked_json(source_files["sufficiency-only.json"])
    citations = checked_json(answer_files["answer-and-citation.json"])
    if (
        sufficiency.get("schema") != WORKLIST_SCHEMA
        or citations.get("schema") != WORKLIST_SCHEMA
        or sufficiency.get("model_answers_in_this_worklist") is not False
        or sufficiency.get("original_reference_targets_in_this_worklist") is not False
        or sufficiency.get("original_sources_only") is not True
        or citations.get("original_reader_answers_unchanged") is not True
        or citations.get("original_reference_targets_in_this_worklist") is not False
        or sufficiency.get("reviewer_verdicts_recorded") != 0
        or citations.get("reviewer_verdicts_recorded") != 0
        or sufficiency.get("production_accepted") is not False
        or citations.get("production_accepted") is not False
    ):
        raise ValueError("source-first review stages not separated")
    first = sufficiency.get("review_cases")
    second = citations.get("review_cases")
    if (
        not isinstance(first, list)
        or not isinstance(second, list)
        or len(first) != 32
        or len(second) != 32
    ):
        raise ValueError("incomplete reviewer handoff")
    by_id = {case["review_id"]: case for case in second}
    if (
        len(by_id) != 32
        or len({case["review_id"] for case in first}) != 32
        or set(by_id) != {case["review_id"] for case in first}
    ):
        raise ValueError("stage 1 and 2 reviewer IDs differ")
    counter = Counter()
    for case in first:
        later = by_id[case["review_id"]]
        for field in (
            "question",
            "observed_at",
            "source_family_proxy",
            "selected_ids",
            "evidence",
            "review_id",
        ):
            if case[field] != later[field]:
                raise ValueError("source-first evidence swapped in answer stage")
        if any(
            case.get(k) is not None
            for k in (
                "reviewer_identity",
                "reviewed_at",
                "sufficient_to_answer",
                "reviewer_answer_from_sources",
            )
        ):
            raise ValueError("stage-one reviewer verdict fabricated")
        if (
            case.get("supporting_utf8_byte_spans") != []
            or case.get("contradictory_source_ids") != []
        ):
            raise ValueError("source offset or contradiction judgement fabricated")
        if "unedited_reader_answer" in case or any(
            k in case
            for k in (
                "answer_supported_by_delivered_sources",
                "cited_claims_entailed",
                "citation_chain_complete",
            )
        ):
            raise ValueError("source-only stage exposes model answers or verdicts")
        if any(
            later.get(k) is not None
            for k in (
                "reviewer_identity",
                "reviewed_at",
                "answer_supported_by_delivered_sources",
                "cited_claims_entailed",
                "citation_chain_complete",
            )
        ):
            raise ValueError("stage-two human verdict fabricated")
        key = (case["source_family_proxy"], tuple(case["selected_ids"]))
        old = reader_by_key.get(key)
        if old is None or old["answer"] != later["unedited_reader_answer"]:
            raise ValueError("worklist answer altered from real original Reader")
        if not old["receipt"]["delivered_evidence"]:
            raise ValueError("missing originally delivered sources")
        query = {
            "identity": old["question_id"],
            "family": old["family_proxy_digest"],
            "scope": old["receipt"]["delivered_evidence"][0]["scope"],
            "content": case["question"],
            "observed_at": case["observed_at"],
        }
        query_digest = sha256(
            json.dumps(
                query, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        if query_digest != old["receipt"]["query_digest"]:
            raise ValueError("review question or time detached from original reader")
        if len(case["evidence"]) != len(old["receipt"]["delivered_evidence"]):
            raise ValueError("source excerpt census differs")
        for source, original_source in zip(
            case["evidence"], old["receipt"]["delivered_evidence"], strict=True
        ):
            excerpt = original_source["excerpt"]
            if source != {
                "label": original_source["label"],
                "observed_at": original_source["observed_at"],
                "original_text": excerpt,
                "source_id": original_source["original_id"],
                "source_root": original_source["root"],
                "utf8_sha256": sha256(excerpt.encode("utf-8")).hexdigest(),
            }:
                raise ValueError(
                    "stage source is not the actually delivered Reader bytes"
                )
        cited = sorted(
            set("E" + n for n in CITATION.findall(later["unedited_reader_answer"]))
        )
        delivered = {x["label"] for x in case["evidence"]}
        if sorted(later["cited_labels"]) != cited or sorted(
            later["undelivered_cited_labels"]
        ) != sorted(set(cited) - delivered):
            raise ValueError("model citation markers were rewritten")
        counter[len(case["selected_ids"])] += 1
    if counter != {4: 16, 8: 16} or len({x["source_family_proxy"] for x in first}) != 2:
        raise ValueError("wrong per-arm or family-proxy census")
    return {
        "schema": SCHEMA,
        "source_upload_artifact_id": ARTIFACTS["source"],
        "answer_upload_artifact_id": ARTIFACTS["answer"],
        "manifest_upload_artifact_id": ARTIFACTS["manifest"],
        "original_reader_artifact_id": ARTIFACTS["reader"],
        "uploaded_zip_sha256": PINS,
        "worklist_generating_commit": REVIEW_COMMIT,
        "original_reader_generating_commit": READER_COMMIT,
        "independently_verified_original_reader_members": reader_members,
        "original_questions": len(pairs),
        "original_source_family_proxies": 2,
        "source_first_cases": 32,
        "answer_citation_cases": 32,
        "original_model_answers_exact_match": 32,
        "original_delivered_source_spans_verified": sum(
            len(x["evidence"]) for x in first
        ),
        "first_stage_contains_model_answer_fields": False,
        "first_stage_contains_reference_targets": False,
        "actual_independent_reviewer_decisions": 0,
        "reviewer_access_separation_certified": False,
        "prospective_independent_families": 0,
        "source_material_is_published_development": True,
        "parametric_memory_training_qualified": False,
        "production_accepted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for role in ("source", "answer", "manifest", "reader"):
        parser.add_argument(role, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.source, args.answer, args.manifest, args.reader)
    if args.output.exists():
        raise ValueError("no receipt overwrite")
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
