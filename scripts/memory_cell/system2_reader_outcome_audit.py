"""Read the immutable new-question Reader experiment; no models or new verdicts.

Transport/source/receipt checks are not independent semantic adjudication.
Unknown scores remain unknown. Raw answers are never rewritten. The review queue
hides arm names but supplies no fabricated reviewer, reference answer or verdict.
"""

import argparse
import hashlib
import json
from pathlib import Path

from system2_native_receipt import index_rows, number, strict_json, verified_archive

SOURCE = "920aede3ccc4c39ced56c90c6c6936a7245c533c"
TREE = "a58aaff0da1cc548f9fff1d7788b7028a8537585"
ARCHIVE = "53dff155f79d4b333ba30060022cc38d351807993f09812ee94e0d8f5f24aee3"
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
SCORE_FIELDS = {
    "diagnostic_f1",
    "weak_source_hit",
    "native_unanswerable",
    "source_labels_unresolved",
    "semantic_correctness_independently_verified",
}


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


def lines(raw):
    return [strict_json(line) for line in raw.splitlines() if line.strip()]


def metrics(rows):
    n = len(rows)
    if not n:
        return dict(planned=0, scored=0, conditional_f1=None, f1_bounds=None)
    vals = [r["diagnostic_f1"] for r in rows if r["diagnostic_f1"] is not None]
    hits = [r["weak_source_hit"] for r in rows if r["weak_source_hit"] is not None]
    receipts = [r["receipt"] for r in rows if "receipt" in r]
    return dict(
        planned=n,
        succeeded=sum(r["status"] == "succeeded" for r in rows),
        failed=sum(r["status"] == "failed" for r in rows),
        scored=len(vals),
        conditional_f1=sum(vals) / len(vals) if vals else None,
        f1_bounds=[sum(vals) / n, (sum(vals) + n - len(vals)) / n],
        source_scored=len(hits),
        source_hits=sum(hits),
        empty_selections=sum(r.get("selected") == [] for r in rows),
        reader_attempts=sum(r["reader_attempted"] for r in rows),
        input_tokens=sum(x["input_tokens"] for x in receipts),
        generated_tokens=sum(x["generated_tokens"] for x in receipts),
        seconds_including_failures=sum(r["seconds"] for r in rows),
    )


def analyze(plan, raw, scored):
    if tuple(plan["arms"]) != ARMS or plan["production_accepted"] is not False:
        raise ValueError("unregistered arms or acceptance")
    qfamily = {q: g["family"] for g in plan["groups"] for q in g["query_ids"]}
    supports = [q for g in plan["groups"] for q in g["support_ids"]]
    query_count = sum(len(g["query_ids"]) for g in plan["groups"])
    if (
        len(qfamily) != query_count
        or len(set(supports)) != len(supports)
        or set(supports) & set(qfamily)
        or len({g["family"] for g in plan["groups"]}) != len(plan["groups"])
        or (set(qfamily) | set(supports)) & set(plan["excluded_question_ids"])
        or plan["planned_queries"] != query_count
        or plan["planned_answers"] != query_count * len(ARMS)
    ):
        raise ValueError("question/support/plan census")
    expected = {(q, a) for q in qfamily for a in ARMS}
    original = index_rows(raw, ("query_id", "arm"), expected)
    observed = index_rows(scored, ("query_id", "arm"), expected)
    if [(r["query_id"], r["arm"]) for r in raw] != [
        (r["query_id"], r["arm"]) for r in scored
    ]:
        raise ValueError("scoring reordered original answers")
    profiles, input_outputs, qfeatures = set(), {}, {}
    for key, row in original.items():
        score = observed[key]
        if (
            {k: v for k, v in score.items() if k not in SCORE_FIELDS} != row
            or set(score) - set(row) - SCORE_FIELDS
            or set(row) & SCORE_FIELDS
        ):
            raise ValueError("scoring rewrote original answer/receipt")
        if (
            row["family"] != qfamily[key[0]]
            or row["status"] not in ("succeeded", "failed")
            or type(row["reader_attempted"]) is not bool
        ):
            raise ValueError("family/status/call counter mismatch")
        number(row["seconds"])
        value, hit = score["diagnostic_f1"], score["weak_source_hit"]
        if value is not None:
            number(value, maximum=1)
        if hit is not None and type(hit) is not bool:
            raise ValueError("non-boolean source metric")
        if row["status"] == "failed":
            if value is not None or hit is not None:
                raise ValueError("failure imputed as scored success")
            continue
        if (
            not row["reader_attempted"]
            or not isinstance(row["answer"], str)
            or not row["answer"].strip()
            or type(score["native_unanswerable"]) is not bool
            or type(score["source_labels_unresolved"]) is not bool
            or score["semantic_correctness_independently_verified"] is not False
        ):
            raise ValueError("invalid success or invented semantic judgment")
        selected = row["selected"]
        if (
            not isinstance(selected, list)
            or len(set(selected)) != len(selected)
            or any(type(i) is not int or not 0 <= i < 64 for i in selected)
            or len(selected)
            > (3 if key[1] == "ranked3" else 0 if key[1] == "no_evidence" else 1)
        ):
            raise ValueError("invalid evidence selection")
        rec = row["receipt"]
        if (
            rec["reader_identity"] != plan["reader_inventory"]
            or rec["token_limit"] != 4096
            or rec["answer_postprocessed"] is not False
            or rec["trainable_parameters"] != 0
            or rec["omitted_evidence_bytes"] != 0
            or rec["production_accepted"] is not False
            or rec["semantic_sufficiency"] is not None
            or rec["semantic_citation_precision"] is not None
            or len(rec["delivered_evidence"]) != len(selected)
        ):
            raise ValueError("Reader configuration or evidence drift")
        for name in ("input_tokens", "generated_tokens"):
            if type(rec[name]) is not int:
                raise ValueError("invalid token counter")
        number(rec["input_tokens"], 1, 4096)
        number(rec["generated_tokens"], 1, 64)
        number(rec["seconds"])
        profiles.add((rec["reader_identity"], rec["reader_profile"]))
        request = (
            rec["reader_identity"],
            rec["reader_profile"],
            rec["query_digest"],
            rec["input_ids_digest"],
        )
        output = (row["answer"], rec["generated_ids_digest"])
        if request in input_outputs and input_outputs[request] != output:
            raise ValueError("same Reader input has different recorded output")
        input_outputs[request] = output
        if key[0] in qfeatures and qfeatures[key[0]] != row["feature_digest"]:
            raise ValueError("shared features changed across arms")
        qfeatures[key[0]] = row["feature_digest"]
    if len(profiles) > 1:
        raise ValueError("mixed Reader profiles")
    contrasts = {}
    for arm in ARMS:
        if arm == "differentiated":
            continue
        pairs = [(observed[q, "differentiated"], observed[q, arm]) for q in qfamily]
        values = [
            c["diagnostic_f1"] - b["diagnostic_f1"]
            for c, b in pairs
            if c["diagnostic_f1"] is not None and b["diagnostic_f1"] is not None
        ]
        missing = len(pairs) - len(values)
        source = [
            int(c["weak_source_hit"]) - int(b["weak_source_hit"])
            for c, b in pairs
            if c["weak_source_hit"] is not None and b["weak_source_hit"] is not None
        ]
        contrasts[arm] = dict(
            pairs=len(pairs),
            scored_pairs=len(values),
            unknown_pairs=missing,
            f1_wins=sum(d > 0 for d in values),
            f1_losses=sum(d < 0 for d in values),
            all_planned_delta_bounds=[
                (sum(values) - missing) / len(pairs),
                (sum(values) + missing) / len(pairs),
            ],
            source_pairs=len(source),
            source_wins=sum(d > 0 for d in source),
            source_losses=sum(d < 0 for d in source),
            changed_selections=sum(
                c.get("selected") != b.get("selected") for c, b in pairs
            ),
            changed_raw_answers=sum(
                c.get("answer") != b.get("answer") for c, b in pairs
            ),
        )
    return dict(
        by_arm={a: metrics([r for r in scored if r["arm"] == a]) for a in ARMS},
        by_family={
            f: {
                a: metrics([r for r in scored if r["family"] == f and r["arm"] == a])
                for a in ARMS
            }
            for f in sorted(set(qfamily.values()))
        },
        by_answerability={
            tag: {
                a: metrics(
                    [
                        r
                        for r in scored
                        if r["arm"] == a and r.get("native_unanswerable") is value
                    ]
                )
                for a in ARMS
            }
            for tag, value in (("answerable", False), ("unanswerable", True))
        },
        comparisons=contrasts,
        recorded=len(raw),
        unique_queries=len(qfamily),
        source_families=len(plan["groups"]),
        unique_successful_requests=len(input_outputs),
        new_model_calls=0,
        raw_answers_preserved=True,
        scores_independently_rejudged=False,
        independent_confirmation=False,
        production_accepted=False,
        reader_adequacy_established=False,
    )


def audit(path):
    files = verified_archive(path, ARCHIVE)
    if (
        files["tested-commit.txt"].decode().strip() != SOURCE
        or files["tested-tree.txt"].decode().strip() != TREE
    ):
        raise ValueError("wrong generating source")
    for name, sha in (
        ("system2_new_questions.py", "5ad46cec6fb6c770062b46a3e7ef2665274eb75d"),
        ("system2_frozen_cohort.py", "b23687683553ba89fbfde1953767daddd176c51e"),
    ):
        data = files["source/" + name]
        if (
            hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            != sha
        ):
            raise ValueError("generating source bytes drift")
    plan = strict_json(files["native/registered-plan.json"])
    if (
        plan != strict_json(files["native/trial/plan.json"])
        or plan["source_commit"] != SOURCE
        or plan["reader_inventory"] != READER
        or len(plan["groups"]) != 6
        or plan["planned_supports"] != 12
        or plan["planned_queries"] != 48
        or plan["planned_answers"] != 384
        or any(
            len(g["support_ids"]) != 2 or len(g["query_ids"]) != 8
            for g in plan["groups"]
        )
    ):
        raise ValueError("not the pinned native cohort")
    raw_bytes = files["native/trial/answers.jsonl"]
    seal = strict_json(files["native/trial/answer-seal.json"])
    if seal != dict(
        sha256=hashlib.sha256(raw_bytes).hexdigest(), rows=384, scoring_started=False
    ):
        raise ValueError("answer journal seal mismatch")
    raw, scored = lines(raw_bytes), lines(files["native/trial/scored.jsonl"])
    report = analyze(plan, raw, scored)
    summary = strict_json(files["native/trial/summary.json"])
    for arm, observed in report["by_arm"].items():
        saved = summary["by_arm"][arm]
        for key, expected in (
            ("planned", observed["planned"]),
            ("failed", observed["failed"]),
            ("scored", observed["scored"]),
            ("conditional_f1", observed["conditional_f1"]),
            ("all_planned_f1_bounds", observed["f1_bounds"]),
            ("reader_calls", observed["reader_attempts"]),
        ):
            if saved[key] != expected:
                raise ValueError("published aggregate differs from original records")
    inputs = lines(files["native/reader-inputs.jsonl"])
    attempts = [r for r in raw if r["reader_attempted"]]
    if len(inputs) != len(attempts):
        raise ValueError("Reader input journal census")
    bindings = {q: v for g in plan["groups"] for q, v in g["question_bindings"].items()}
    for row, data in zip(attempts, inputs, strict=True):
        q, bundle = data["query"], data["bundle"]
        if (
            q["identity"] != row["query_id"]
            or digest((q["content"], q["observed_at"], q["scope"]))
            != bindings[q["identity"]]
            or bundle["query_digest"] != digest(q)
            or len(bundle["selected"]) != len(row["selected"])
        ):
            raise ValueError("original Reader question/evidence binding")
        if "receipt" in row:
            rec = row["receipt"]
            if rec["query_digest"] != digest(q) or rec["bundle_digest"] != digest(
                ("hepta.evidence-bundle.v1", bundle)
            ):
                raise ValueError("compiled bundle digest changed")
        originals = {d["identity"]: d for d in data["selected_originals"]}
        for i, span in enumerate(bundle["selected"], 1):
            doc = originals[span["source_id"]]
            start, end = span["start"], span["end"]
            if (
                type(start) is not int
                or type(end) is not int
                or not 0 <= start < end <= len(doc["content"].encode())
                or doc["content"].encode()[start:end].decode("utf-8") != span["excerpt"]
                or digest(doc["content"]) != span["source_digest"]
                or any(
                    doc[k] != span[k]
                    for k in ("root", "scope", "session", "observed_at")
                )
            ):
                raise ValueError("detached original evidence bytes")
            expected = dict(
                label=f"E{i}",
                id=digest(span),
                original_id=span["source_id"],
                root=span["root"],
                scope=span["scope"],
                excerpt=span["excerpt"],
                source_start=start,
                source_end=end,
                observed_at=span["observed_at"],
                source_digest=span["source_digest"],
            )
            if (
                "receipt" in row
                and row["receipt"]["delivered_evidence"][i - 1] != expected
            ):
                raise ValueError("delivered evidence receipt drift")
    supports = {q for g in plan["groups"] for q in g["support_ids"]}
    queries = {q for g in plan["groups"] for q in g["query_ids"]}
    encodings = lines(files["native/encoding.jsonl"])
    if len(encodings) != len({r["query_id"] for r in encodings}) or any(
        r["query_id"] not in supports | queries
        or r["after_snapshot_freeze"] is not (r["query_id"] in queries)
        for r in encodings
    ):
        raise ValueError("encoding phase/census mismatch")
    fits = lines(files["native/trial/fits.jsonl"])
    states = [r for r in fits if "method" in r]
    expected = {(g["family"], a) for g in plan["groups"] for a in ARMS[:6]}
    index_rows(states, ("family", "method"), expected)
    for row in states:
        if (
            "state_file" in row
            and hashlib.sha256(files["native/trial/" + row["state_file"]]).hexdigest()
            != row["state_sha256"]
        ):
            raise ValueError("frozen state file mismatch")
    review, mapping = {}, []
    for row, data in zip(attempts, inputs, strict=True):
        if row["status"] != "succeeded":
            continue
        rec = row["receipt"]
        key = digest(
            (
                rec["query_digest"],
                rec["input_ids_digest"],
                row["answer"],
                rec["generated_ids_digest"],
            )
        )
        review.setdefault(
            key,
            dict(
                case_id=key,
                query=data["query"],
                bundle=data["bundle"],
                selected_originals=data["selected_originals"],
                answer=row["answer"],
                reference_answer=None,
                reviewer=None,
                semantic_verdict=None,
                independent_review_completed=False,
            ),
        )
        mapping.append(dict(query_id=row["query_id"], arm=row["arm"], case_id=key))
    report.update(
        schema="hepta.system2.new-question-outcome-audit.v1",
        generating_commit=SOURCE,
        generating_tree=TREE,
        archive_sha256=ARCHIVE,
        verified_manifest_entries=len(files) - 1,
        verified_state_files=sum("state_file" in r for r in states),
        native_run_summary=strict_json(files["native/run-summary.json"]),
        fit_diagnostics=[
            {
                k: r[k]
                for k in ("family", "method", "status", "receipt", "disposition")
                if k in r
            }
            for r in states
        ],
        blind_review_cases=len(review),
        review_coverage=len(mapping),
        natural_chronology_verified=False,
        raw_score_is_not_semantic_accuracy=True,
    )
    return report, [review[k] for k in sorted(review)], mapping


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    result, queue, mapping = audit(args.archive)
    for name, value in (("audit.json", result), ("review-arm-map.json", mapping)):
        (args.output / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
    (args.output / "blind-review.jsonl").write_text(
        "".join(
            json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in queue
        )
    )
    display = {
        k: v
        for k, v in result.items()
        if k not in ("by_family", "fit_diagnostics", "native_run_summary")
    }
    print("OUTCOME_AUDIT=" + json.dumps(display, sort_keys=True, allow_nan=False))
    fit_display = [
        dict(
            family=r["family"],
            method=r["method"],
            status=r.get("status", r.get("receipt", {}).get("status")),
            direct_solves=r.get("receipt", {}).get("direct_solves"),
            disposition=r.get("disposition"),
        )
        for r in result["fit_diagnostics"]
    ]
    print("FIT_DIAGNOSTICS=" + json.dumps(fit_display, sort_keys=True, allow_nan=False))
    print(
        "FAMILY_METRICS="
        + json.dumps(result["by_family"], sort_keys=True, allow_nan=False)
    )
