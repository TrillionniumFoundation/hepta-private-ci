"""Historical *real* frozen Reader behavior: bounded, source-sealed, no inference.

Read-only analysis of an already-completed fixed-Reader hosted study. Separate
citation *syntax* and prescribed no-evidence refusal from answer truth, source
sufficiency, citation semantics and NDU performance. No model calls are made.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import re

from system2_native_receipt import strict_json, verified_archive

SOURCE = "920aede3ccc4c39ced56c90c6c6936a7245c533c"
TREE = "a58aaff0da1cc548f9fff1d7788b7028a8537585"
ARCHIVE = "53dff155f79d4b333ba30060022cc38d351807993f09812ee94e0d8f5f24aee3"
ANSWER_SEAL = "065b365b78b3ce91210dbdd25d825ccd0559e27060de1ddb0bf45890181b96e8"
READER = "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c"
ARMS = (
    "frozen",
    "shared",
    "local_only",
    "differentiated",
    "erased_update",
    "neighbor",
    "no_evidence",
    "ranked3",
)
ABSTAIN = "I do not have enough evidence."
CITATION = re.compile(r"\[E([1-9][0-9]*)\]", re.IGNORECASE)
SCHEMA = "hepta.system2.historical-reader-obedience.v1"


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def lines(blob):
    return [strict_json(item) for item in blob.splitlines()]


def validate_reader_input(item):
    query = item["query"]
    bundle = item["bundle"]
    originals = item["selected_originals"]
    if bundle["query_digest"] != digest(query):
        raise ValueError("question digest detached from Reader input")
    if len(originals) != len({d["identity"] for d in originals}):
        raise ValueError("duplicated Reader original source")
    if len(bundle["selected"]) > 3:
        raise ValueError("unregistered evidence count")
    originals = {d["identity"]: d for d in originals}
    delivered = []
    for pos, source_span in enumerate(bundle["selected"], 1):
        original = originals[source_span["source_id"]]
        for name in ("root", "scope", "session", "observed_at"):
            if original[name] != source_span[name]:
                raise ValueError("source scope/time/session detached")
        if original["scope"] != query["scope"]:
            raise ValueError("cross-scope Reader evidence")
        encoded = original["content"].encode("utf-8", "strict")
        start, end = source_span["start"], source_span["end"]
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(encoded)
            or encoded[start:end].decode("utf-8", "strict") != source_span["excerpt"]
            or digest(original["content"]) != source_span["source_digest"]
        ):
            raise ValueError("unaligned original evidence bytes")
        delivered.append(
            dict(
                label="E" + str(pos),
                id=digest(source_span),
                original_id=original["identity"],
                root=original["root"],
                scope=original["scope"],
                excerpt=source_span["excerpt"],
                source_start=start,
                source_end=end,
                observed_at=original["observed_at"],
                source_digest=source_span["source_digest"],
            )
        )
    return (
        query["identity"],
        digest(query),
        digest(("hepta.evidence-bundle.v1", bundle)),
        tuple(json.dumps(d, sort_keys=True, ensure_ascii=False) for d in delivered),
    )


def summarize(files):
    """Use every planned question/arm; reject altered provenance or incomplete data."""
    required = (
        "tested-commit.txt",
        "tested-tree.txt",
        "native/trial/plan.json",
        "native/registered-plan.json",
        "native/trial/answers.jsonl",
        "native/trial/answer-seal.json",
        "native/trial/scored.jsonl",
        "native/trial/summary.json",
        "native/run-summary.json",
        "native/reader-inputs.jsonl",
    )
    if any(k not in files for k in required):
        raise ValueError("historical Reader evidence missing")
    if (
        files["tested-commit.txt"].decode().strip() != SOURCE
        or files["tested-tree.txt"].decode().strip() != TREE
    ):
        raise ValueError("historical generating source drift")
    plan = strict_json(files["native/trial/plan.json"])
    if plan != strict_json(files["native/registered-plan.json"]):
        raise ValueError("planned Reader task split drift")
    if (
        plan["source_commit"] != SOURCE
        or plan["reader_inventory"] != READER
        or tuple(plan["arms"]) != ARMS
        or plan["planned_answers"] != 384
        or plan["planned_queries"] != 48
        or plan["production_accepted"] is not False
    ):
        raise ValueError("unexpected historical Reader experiment")
    group_ids = [qid for g in plan["groups"] for qid in g["query_ids"]]
    if len(group_ids) != 48 or len(set(group_ids)) != 48:
        raise ValueError("question family/identity overlap")
    expected = {(qid, arm) for qid in group_ids for arm in ARMS}
    raw = files["native/trial/answers.jsonl"]
    seal = strict_json(files["native/trial/answer-seal.json"])
    if (
        seal != dict(sha256=ANSWER_SEAL, rows=384, scoring_started=False)
        or hashlib.sha256(raw).hexdigest() != ANSWER_SEAL
    ):
        raise ValueError("raw immutable neural answers changed")
    rows = lines(raw)
    scored = lines(files["native/trial/scored.jsonl"])
    saved = strict_json(files["native/trial/summary.json"])
    published = strict_json(files["native/run-summary.json"])
    if (
        saved["answer_seal"] != ANSWER_SEAL
        or published["answer_seal"] != ANSWER_SEAL
        or saved["source_commit"] != SOURCE
        or saved["recorded"] != 384
        or saved["production_accepted"] is not False
    ):
        raise ValueError("historical scored result drift")
    if len(rows) != 384 or len(scored) != 384:
        raise ValueError("incomplete 384-call Reader census")
    indexed = {}
    for row in rows:
        key = row["query_id"], row["arm"]
        if key in indexed or key not in expected:
            raise ValueError("duplicate/unregistered Reader answer")
        indexed[key] = row
    if set(indexed) != expected:
        raise ValueError("missing Reader attempt")
    check = {}
    for row in scored:
        key = row["query_id"], row["arm"]
        if key in check or key not in expected:
            raise ValueError("duplicated/unregistered scored record")
        check[key] = row
    if set(check) != expected:
        raise ValueError("missing original score")
    for key, row in indexed.items():
        scored_row = check[key]
        if any(scored_row.get(k) != v for k, v in row.items()):
            raise ValueError("scored receipt mutated original answer")
        score = scored_row.get("diagnostic_f1")
        if score is not None and (
            type(score) not in (int, float) or not 0 <= score <= 1
        ):
            raise ValueError("invalid historical diagnostic F1")
        if row["status"] not in ("succeeded", "failed"):
            raise ValueError("unrecognized Reader attempt status")

    # The exact prompt receipt binds the model answer back to its original
    # document bytes; the canonical body digest does not expose gold labels.
    source_inputs = Counter(
        validate_reader_input(x) for x in lines(files["native/reader-inputs.jsonl"])
    )
    recorded_inputs = Counter()
    signatures = {}
    profiles = set()
    for row in rows:
        if row["status"] == "failed":
            continue
        answer = row["answer"]
        receipt = row["receipt"]
        if (
            not isinstance(answer, str)
            or not answer.strip()
            or receipt["reader_identity"] != READER
            or receipt["answer_postprocessed"] is not False
            or receipt["trainable_parameters"] != 0
            or receipt["token_limit"] != 4096
            or receipt["production_accepted"] is not False
        ):
            raise ValueError("frozen Reader output/identity drift")
        for field, maximum in (("input_tokens", 4096), ("generated_tokens", 64)):
            if type(receipt[field]) is not int or not 0 <= receipt[field] <= maximum:
                raise ValueError("Reader token accounting drift")
        if (
            not receipt["reader_profile"]
            or not receipt["input_ids_digest"]
            or not receipt["generated_ids_digest"]
        ):
            raise ValueError("missing deterministic model receipt")
        profiles.add((receipt["reader_identity"], receipt["reader_profile"]))
        d = receipt["delivered_evidence"]
        if any(item["label"] != "E" + str(j) for j, item in enumerate(d, 1)):
            raise ValueError("nonpositional source labels")
        k = (
            row["query_id"],
            receipt["query_digest"],
            receipt["bundle_digest"],
            tuple(json.dumps(e, sort_keys=True, ensure_ascii=False) for e in d),
        )
        recorded_inputs[k] += 1
        signature = (
            receipt["reader_identity"],
            receipt["reader_profile"],
            receipt["input_ids_digest"],
        )
        generated = (answer, receipt["generated_ids_digest"])
        if signature in signatures and signatures[signature] != generated:
            raise ValueError("identical frozen prompt generated different answers")
        signatures[signature] = generated
    if len(profiles) != 1 or source_inputs != recorded_inputs:
        raise ValueError(
            "mixed model profile or Reader inputs not bound to source bytes"
        )

    arms = []
    by_arm = defaultdict(list)
    for row in rows:
        by_arm[row["arm"]].append(row)
    for arm in ARMS:
        subset = by_arm[arm]
        good = [r for r in subset if r["status"] == "succeeded"]
        citations = 0
        fully_bound_citations = 0
        unbound_citations = 0
        strict_refusals = 0
        empty_evidence = 0
        nonrefusal_without_evidence = 0
        hits_cap = 0
        for row in good:
            text = row["answer"]
            delivered = row["receipt"]["delivered_evidence"]
            labels = {e["label"].upper() for e in delivered}
            refs = ["E" + idx for idx in CITATION.findall(text)]
            citations += bool(refs)
            fully_bound_citations += bool(refs) and all(
                ref.upper() in labels for ref in refs
            )
            unbound_citations += sum(ref.upper() not in labels for ref in refs)
            refused = text.strip().strip('"').casefold() == ABSTAIN.casefold()
            strict_refusals += refused
            empty_evidence += not bool(delivered)
            nonrefusal_without_evidence += not bool(delivered) and not refused
            hits_cap += row["receipt"]["generated_tokens"] == 64
        usable_f1 = [
            check[(r["query_id"], arm)]["diagnostic_f1"]
            for r in subset
            if check[(r["query_id"], arm)]["diagnostic_f1"] is not None
        ]
        arms.append(
            dict(
                arm=arm,
                planned=48,
                completed=len(good),
                failed=48 - len(good),
                citation_syntax_present=citations,
                citation_labels_all_bound=fully_bound_citations,
                unbound_citation_labels=unbound_citations,
                prescribed_strict_refusals=strict_refusals,
                delivered_zero_evidence=empty_evidence,
                nonrefusal_with_zero_evidence=nonrefusal_without_evidence,
                generated_token_cap_hits=hits_cap,
                total_reader_input_tokens=sum(
                    r["receipt"]["input_tokens"] for r in good
                ),
                total_reader_output_tokens=sum(
                    r["receipt"]["generated_tokens"] for r in good
                ),
                diagnostic_f1_known=len(usable_f1),
                original_diagnostic_f1_mean=(
                    sum(usable_f1) / len(usable_f1) if usable_f1 else None
                ),
                unknown_failures_are_not_negative_labels=True,
            )
        )
    result = dict(
        schema=SCHEMA,
        producing_commit=SOURCE,
        producing_tree=TREE,
        archive_sha256=ARCHIVE,
        raw_answer_sha256=ANSWER_SEAL,
        reader_identity=READER,
        reader_profile=next(iter(profiles))[1],
        unique_questions=48,
        complete_384_call_census=True,
        counted_answers=384,
        original_annotation_f1_not_readjudged=True,
        per_arm=arms,
        totals=dict(
            planned=384,
            completed=sum(a["completed"] for a in arms),
            valid_label_citations=sum(a["citation_labels_all_bound"] for a in arms),
            prescribed_refusals=sum(a["prescribed_strict_refusals"] for a in arms),
            zero_evidence_outputs=sum(a["delivered_zero_evidence"] for a in arms),
            nonrefusal_zero_evidence_outputs=sum(
                a["nonrefusal_with_zero_evidence"] for a in arms
            ),
            distinct_deterministic_prompts=len(signatures),
        ),
        citation_semantics_independently_verified=False,
        human_evidence_sufficiency_verified=False,
        new_neural_calls=0,
        production_accepted=False,
        candidate_disposition="reader_citation_and_refusal_preflight_failed",
    )
    return result


def run(path, output):
    verified = verified_archive(path, ARCHIVE)
    data = summarize(verified)
    output.mkdir(parents=True, exist_ok=False)
    (output / "historical-reader-behavior.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original_archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.original_archive, args.output), ensure_ascii=False, allow_nan=False
        )
    )
