"""Source-pinned LoCoMo sufficiency and answer review worklists, NEVER verdicts.

No benchmark target file may enter this program. The sufficiency reviewer first
sees only the original question and exactly delivered source evidence, while
separate answer/citation cases preserve unmodified pretrained generations.
Public source families here are proxies, not prospective human-certified data.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SCHEMA = "hepta.memorycell.locomo-source-first-review.v1"
PINS = {
    "public": "51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37",
    "decisions": "3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097",
    "reader": "7160ede72114b04135e544fb687a804dc0c4852834cf1695440a75b85214bf48",
}
READER_COMMIT = "96b5ec37b82f87d445740403e07e3705e9850955"
MODEL_ID = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
ARMS = ("lexical_k4", "lexical_k8")
REQUIRED = {
    "public": {"population.json", "histories.jsonl", "histories-manifest.json"},
    "decisions": {"decisions.jsonl", "receipt.json", "SHA256SUMS"},
}
CITE = re.compile(r"\[E([1-9][0-9]{0,5})\]")


def digest_bytes(raw):
    return sha256(raw).hexdigest()


def native_digest(value):
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return digest_bytes(payload)


def read_json(raw):
    def no_duplicates(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate original JSON field")
            obj[key] = value
        return obj

    def no_constant(value):
        raise ValueError("nonfinite original JSON value: " + value)

    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=no_duplicates,
        parse_constant=no_constant,
    )


def jsonl(raw, *, limit):
    if not raw.endswith(b"\n") or len(raw) > 16 * 1024 * 1024:
        raise ValueError("incomplete or oversized source journal")
    rows = [read_json(s) for s in raw.splitlines() if s]
    if not 1 <= len(rows) <= limit:
        raise ValueError("source census not in bounds")
    return rows


def pinned_zip(path, role):
    if role not in PINS or path.is_symlink() or not path.is_file():
        raise ValueError("unregistered immutable original archive")
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("original archive transport size bound")
    data = path.read_bytes()
    if digest_bytes(data) != PINS[role]:
        raise ValueError("original archived ZIP SHA-256 does not match")
    out = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        info = archive.infolist()
        if (
            not 1 <= len(info) <= 48
            or sum(i.file_size for i in info) > 32 * 1024 * 1024
        ):
            raise ValueError("bounded original archive file census")
        for item in info:
            p = PurePosixPath(item.filename)
            if (
                item.is_dir()
                or item.filename.startswith("/")
                or "\\" in item.filename
                or ".." in p.parts
                or not str(p)
                or stat.S_ISLNK(item.external_attr >> 16)
                or item.filename in out
                or item.file_size > 16 * 1024 * 1024
            ):
                raise ValueError("unsafe source ZIP entry")
            out[item.filename] = archive.read(item)
    if role in REQUIRED and set(out) != REQUIRED[role]:
        raise ValueError("source archive member census drift")
    if "SHA256SUMS" in out:
        seen = set()
        for line in out["SHA256SUMS"].decode("utf-8").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
            if not match:
                raise ValueError("invalid source manifest line")
            expected, name = match.groups()
            if name in seen or name not in out or digest_bytes(out[name]) != expected:
                raise ValueError("source manifest mismatch")
            seen.add(name)
        if seen != set(out) - {"SHA256SUMS"}:
            raise ValueError("incomplete source manifest")
    return out


def verify_inputs(public, decisions, reader):
    population = read_json(public["population.json"])
    history_manifest = read_json(public["histories-manifest.json"])
    if (
        history_manifest["population_sha256"] != digest_bytes(public["population.json"])
        or history_manifest["histories_sha256"]
        != digest_bytes(public["histories.jsonl"])
        or population["model_input_contains_answers"] is not False
        or population["production_accepted"] is not False
        or population["source_sha256"]
        != {
            "locomo": "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
        }
    ):
        raise ValueError("source-only published histories changed")
    docs_rows = jsonl(public["histories.jsonl"], limit=6000)
    docs = {d["identity"]: d for d in docs_rows}
    if len(docs_rows) != 5882 or len(docs) != len(docs_rows):
        raise ValueError("original published document census drift")
    decisions_rows = jsonl(decisions["decisions.jsonl"], limit=500)
    lookup = {(r["question_id"], r["arm"]): r for r in decisions_rows}
    if len(decisions_rows) != 480 or len(lookup) != len(decisions_rows):
        raise ValueError("original 480 label-blind source decisions changed")
    ready = read_json(reader["run/READY.json"])
    journal = reader["run/raw-answers.jsonl"]
    if (
        reader["tested-commit.txt"].decode().strip() != READER_COMMIT
        or ready["generating_commit"] != READER_COMMIT
        or ready["raw_journal_sha256"] != digest_bytes(journal)
        or ready["original_source_sha256"] != PINS["public"]
        or ready["original_six_decisions_sha256"] != PINS["decisions"]
        or ready["model_identity"] != MODEL_ID
        or ready["planned_model_calls"] != 32
        or ready["actual_model_calls"] != 32
        or ready["succeeded"] != 32
        or ready["failed"] != 0
        or ready["labels_seen_during_generation"] is not False
        or ready["original_answers_rewritten"] is not False
        or ready["production_accepted"] is not False
        or ready["weight_updates"] != 0
    ):
        raise ValueError("original completed model identity or embargo drift")
    raw_rows = jsonl(journal, limit=32)
    return population, docs, lookup, raw_rows, ready


def make_worklists(population, docs, decisions, answers, ready):
    cases = population["splits"]["evaluation"]
    if (
        len(cases) != 16
        or len({q["question_id"] for q in cases}) != 16
        or len({q["family_proxy_digest"] for q in cases}) != 2
        or len(answers) != 32
    ):
        raise ValueError("original two published family proxies required")
    expected_order = [(q["question_id"], arm) for q in cases for arm in ARMS]
    if [(r["question_id"], r["arm"]) for r in answers] != expected_order:
        raise ValueError("original reader ordered attempt census drift")
    sufficiency, answer_review = [], []
    source_roots = set()
    for case in cases:
        qid = case["question_id"]
        for arm in ARMS:
            row = answers[len(sufficiency)]
            selected = decisions[(qid, arm)]["selected"]
            if (
                row["selected"] != selected
                or row["family_proxy_digest"] != case["family_proxy_digest"]
                or row["source_census_sha256"] != case["source_census_sha256"]
                or row["status"] != "succeeded"
                or type(row.get("answer")) is not str
                or not row["answer"].strip()
            ):
                raise ValueError(
                    "model answers differ from the committed source selection"
                )
            count = 4 if arm == "lexical_k4" else 8
            if len(selected) != count or len(set(selected)) != count:
                raise ValueError("unregistered source count")
            if arm == "lexical_k8" and selected[:4] != sufficiency[-1]["selected_ids"]:
                raise ValueError("nested retrieval baseline changed")
            receipt = row["receipt"]
            if (
                receipt.get("reader_identity") != MODEL_ID
                or receipt.get("reader_profile") != ready["model_profile"]
                or receipt.get("token_limit") != 2048
                or receipt.get("answer_postprocessed") is not False
                or receipt.get("production_accepted") is not False
                or receipt.get("trainable_parameters") != 0
                or receipt.get("semantic_citation_precision") is not None
                or receipt.get("semantic_sufficiency") is not None
                or len(receipt.get("delivered_evidence", [])) != count
                or type(receipt.get("input_tokens")) is not int
                or not 0 < receipt["input_tokens"] <= 2048
                or type(receipt.get("generated_tokens")) is not int
                or not 0 <= receipt["generated_tokens"] <= 64
                or type(receipt.get("seconds")) not in (float, int)
                or not math.isfinite(receipt["seconds"])
                or receipt["seconds"] < 0
            ):
                raise ValueError("original frozen reader budget/profile/cost drift")
            original_sources = []
            for i, (sid, delivered) in enumerate(
                zip(selected, receipt["delivered_evidence"], strict=True), 1
            ):
                original = docs[sid]
                raw = original["content"].encode("utf-8")
                if (
                    original["scope"] != case["scope"]
                    or original["root"] != case["scope"]
                    or delivered["label"] != f"E{i}"
                    or delivered["original_id"] != sid
                    or delivered["excerpt"] != original["content"]
                    or delivered["root"] != original["root"]
                    or delivered["scope"] != case["scope"]
                    or delivered["source_start"] != 0
                    or delivered["source_end"] != len(raw)
                    or delivered["source_digest"] != native_digest(original["content"])
                ):
                    raise ValueError(
                        "original model prompt excerpt is not original source"
                    )
                source_roots.add(original["root"])
                original_sources.append(
                    dict(
                        label=f"E{i}",
                        source_id=sid,
                        source_root=original["root"],
                        observed_at=original["observed_at"],
                        utf8_sha256=digest_bytes(raw),
                        original_text=original["content"],
                    )
                )
            key = digest_bytes((READER_COMMIT + "\0" + qid + "\0" + arm).encode())[:24]
            base = dict(
                review_id=key,
                question=case["question"],
                source_family_proxy=case["family_proxy_digest"],
                observed_at=case["observation_time"],
                selected_ids=list(selected),
                evidence=original_sources,
            )
            sufficiency.append(
                dict(
                    **base,
                    sufficient_to_answer=None,
                    reviewer_answer_from_sources=None,
                    supporting_utf8_byte_spans=[],
                    contradictory_source_ids=[],
                    reviewer_identity=None,
                    reviewed_at=None,
                )
            )
            cited = sorted({"E" + x for x in CITE.findall(row["answer"])})
            answer_review.append(
                dict(
                    **base,
                    unedited_reader_answer=row["answer"],
                    cited_labels=cited,
                    undelivered_cited_labels=sorted(
                        set(cited) - {v["label"] for v in original_sources}
                    ),
                    answer_supported_by_delivered_sources=None,
                    cited_claims_entailed=None,
                    citation_chain_complete=None,
                    reviewer_identity=None,
                    reviewed_at=None,
                )
            )
    if len(sufficiency) != 32 or len(answer_review) != 32 or len(source_roots) != 2:
        raise ValueError("original native source-family review census changed")
    return sufficiency, answer_review


def write_once(path, value):
    raw = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode()
    with path.open("xb") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())
    return digest_bytes(raw)


def run(public_path, decisions_path, reader_path, output):
    if output.exists():
        raise ValueError("review packet output must be new")
    public = pinned_zip(public_path, "public")
    decisions = pinned_zip(decisions_path, "decisions")
    reader = pinned_zip(reader_path, "reader")
    population, docs, decisions_lookup, raw, ready = verify_inputs(
        public, decisions, reader
    )
    sufficiency, answer_review = make_worklists(
        population, docs, decisions_lookup, raw, ready
    )
    output.mkdir()
    source_hash = write_once(
        output / "sufficiency-only.json",
        dict(
            schema=SCHEMA,
            original_sources_only=True,
            model_answers_in_this_worklist=False,
            original_reference_targets_in_this_worklist=False,
            reviewer_verdicts_recorded=0,
            review_cases=sufficiency,
            production_accepted=False,
        ),
    )
    answer_hash = write_once(
        output / "answer-and-citation.json",
        dict(
            schema=SCHEMA,
            original_reader_answers_unchanged=True,
            original_reference_targets_in_this_worklist=False,
            reviewer_verdicts_recorded=0,
            review_cases=answer_review,
            production_accepted=False,
        ),
    )
    manifest = dict(
        schema=SCHEMA,
        original_source_artifacts_sha256=dict(PINS),
        generating_reader_source_commit=READER_COMMIT,
        model_identity=MODEL_ID,
        original_public_question_count=16,
        original_published_source_family_proxies=2,
        original_model_answers=32,
        source_sufficiency_decisions=0,
        answer_citation_review_decisions=0,
        independent_human_semantic_judgement=False,
        sources_are_published_development=True,
        prospective_source_families=0,
        training_permitted=False,
        production_accepted=False,
        sufficiency_worklist_sha256=source_hash,
        answer_citation_worklist_sha256=answer_hash,
    )
    write_once(output / "manifest.json", manifest)
    with (output / "SHA256SUMS").open("x", encoding="utf-8") as checks:
        for item in sorted(output.glob("*.json")):
            checks.write(f"{digest_bytes(item.read_bytes())}  ./{item.name}\n")
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("public", type=Path)
    p.add_argument("decisions", type=Path)
    p.add_argument("reader", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    print(
        json.dumps(
            run(args.public, args.decisions, args.reader, args.output), sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
