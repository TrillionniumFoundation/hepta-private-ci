"""Multi-hop evidence / frozen Reader diagnostic, NEVER production qualification.

Synthetic grammar supplies executable expected answers, NOT independent human
sufficiency.  All raw Reader outputs are sealed before any target is scored.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import time

from system2_multihop_evidence import (
    ARMS,
    TOP_K,
    TASKS,
    choose,
    case_manifest,
    digest,
    fixed_cases,
    join_path,
)

TOKEN_RE = re.compile(r"\bTOK-[A-F0-9]{7}\b", re.I)
CITATION_RE = re.compile(r"\[(E\d+)\]", re.I)
ABSTAIN = "I do not have enough evidence."


def write(path, value):
    with path.open("x", encoding="utf8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def append(path, value):
    with path.open("a", encoding="utf8") as stream:
        stream.write(
            json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
            + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())


def evidence(case, selected, arm):
    from evidence_bundle import EvidenceBundle, EvidenceSpan
    from native import digest as native_digest

    if case.question.scope not in {d.scope for d in case.documents}:
        raise ValueError("source identity discrepancy")
    originals = {d.identity: d for d in case.documents}
    frontier = native_digest(
        [(key, native_digest(d.content)) for key, d in sorted(originals.items())]
    )
    spans = tuple(
        EvidenceSpan(
            d.identity,
            d.root,
            d.scope,
            d.session,
            d.observed_at,
            0,
            len(d.content.encode("utf8")),
            d.content,
            native_digest(d.content),
        )
        for d in selected
    )
    bundle = EvidenceBundle(
        native_digest(asdict(case.question)),
        frontier,
        spans,
        "synthetic-verified:" + arm,
        rounds=1,
    )
    bundle.validate(case.question, originals, frontier=frontier, revoked=set())
    return bundle, originals, frontier


def score(case, arm, selected_ids, raw):
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("unavailable Reader output")
    delivered = choose(arm, case.question, case.documents)
    if [d.identity for d in delivered] != selected_ids:
        raise ValueError("selection replay changed source identities")
    present = {d.identity for d in delivered}
    complete = set(case.required_ids).issubset(present)
    # Independent programmatic check: withholding any critical premise removes
    # the only typed path to the generated synthetic outcome.
    if bool(join_path(case.question, delivered)) != complete:
        raise ValueError("synthetic path audit inconsistent")
    tokens = TOKEN_RE.findall(raw.upper())
    exact = len(tokens) == 1 and tokens[0] == case.answer
    cited = [label.upper() for label in CITATION_RE.findall(raw)]
    bound = set("E" + str(i + 1) for i in range(len(delivered)))
    citation_valid = bool(cited) and set(cited).issubset(bound)
    mapping = {"E" + str(i + 1): d.identity for i, d in enumerate(delivered)}
    complete_citation = (
        citation_valid
        and set(case.required_ids).issubset({mapping[label] for label in cited})
        if complete
        else False
    )
    abstained = raw.strip().strip('"').casefold() == ABSTAIN.casefold()
    return dict(
        programmatically_complete=complete,
        answer_exact=exact,
        citation_syntax_valid=citation_valid,
        cites_all_required_sources=complete_citation,
        abstained_exactly=abstained,
        strict_task_success=(exact and complete_citation if complete else abstained),
        synthetic_only_no_independent_human_verdict=True,
    )


def census(rows, question_ids):
    expected = {(qid, arm) for qid in question_ids for arm in ARMS}
    actual = [(r["qid"], r["arm"]) for r in rows]
    if (
        len(actual) != len(expected)
        or set(actual) != expected
        or len(actual) != len(set(actual))
    ):
        raise ValueError("incomplete Reader attempts / duplicated cells")
    if any(r["status"] not in ("succeeded", "failed") for r in rows):
        raise ValueError("unknown Reader attempt")
    return dict(
        planned=len(expected),
        recorded=len(actual),
        succeeded=sum(r["status"] == "succeeded" for r in rows),
        failed=sum(r["status"] == "failed" for r in rows),
    )


def evaluate(rows, cases):
    cmap = {case.question.identity: case for case in cases}
    c = census(rows, list(cmap))
    scores = []
    for row in rows:
        if row["status"] == "failed":
            scores.append(
                dict(
                    qid=row["qid"],
                    arm=row["arm"],
                    status="failed",
                    error_type=row.get("error_type"),
                    strict_task_success=None,
                )
            )
            continue
        case = cmap[row["qid"]]
        score_row = score(case, row["arm"], row["selected"], row["answer"])
        scores.append(
            dict(
                qid=row["qid"],
                arm=row["arm"],
                status="succeeded",
                hops=case.hops,
                attack_distractor=case.attack_distractor,
                **score_row,
            )
        )
    aggregations = []
    for arm in ARMS:
        part = [r for r in scores if r["arm"] == arm]
        valid = [r for r in part if r["status"] == "succeeded"]
        aggregations.append(
            dict(
                arm=arm,
                planned=len(part),
                completed=len(valid),
                exact_and_cited=sum(
                    r["answer_exact"] and r["cites_all_required_sources"] for r in valid
                ),
                programmatically_sufficient=sum(
                    r["programmatically_complete"] for r in valid
                ),
                strict_task_success=sum(r["strict_task_success"] for r in valid),
                abstentions=sum(r["abstained_exactly"] for r in valid),
                failures=len(part) - len(valid),
                task_rate_denominator=len(part),
                unknown_failures_not_imputed=True,
            )
        )
    return c, scores, aggregations


def run(output, reader, *, source_commit, count=TASKS):
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact commit identity required")
    cases = fixed_cases(count)
    output.mkdir(parents=True, exist_ok=False)
    plan = dict(
        schema="hepta.system2.synthetic-multihop-reader.v1",
        source_commit=source_commit,
        cohort=[case.question.identity for case in cases],
        source_manifests=[case_manifest(case) for case in cases],
        dataset_kind="deterministic generated English (not independent human test)",
        two_and_three_hop=True,
        task_count=len(cases),
        arms=list(ARMS),
        selected_evidence_limit=TOP_K,
        reader_input_token_limit=1024,
        actual_costs_are_not_identical=True,
        zero_training_updates=True,
        no_model_or_target_data_entering_selectors=True,
        target_not_given_to_online_selector_or_reader=True,
        generated_targets_checked_for_case_integrity_before_predictions=True,
        answer_scoring_after_raw_seal=True,
        production_accepted=False,
        reasoning_emergence_established=False,
    )
    write(output / "plan.json", plan)
    rows = []
    all_pairs = [(case, arm) for case in cases for arm in ARMS]
    # Rotate the order per-question; do not let a consistent arm be first.
    all_pairs.sort(
        key=lambda pair: (
            pair[0].question.identity,
            (ARMS.index(pair[1]) + int(digest(pair[0].question.identity)[:8], 16))
            % len(ARMS),
        )
    )
    try:
        for case, arm in all_pairs:
            started = time.perf_counter()
            row = dict(
                qid=case.question.identity,
                arm=arm,
                source_manifest=case_manifest(case),
                status="started",
            )
            append(output / "starts.jsonl", row)
            try:
                # No synthetic truth or target enters choose(), bundle, or reader.
                selected = choose(arm, case.question, case.documents)
                row["selected"] = [d.identity for d in selected]
                row["selected_count"] = len(selected)
                row["scanned_document_bytes"] = sum(
                    len(d.content.encode()) for d in case.documents
                )
                bundle, originals, frontier = evidence(case, selected, arm)
                row["bundle_digest"] = bundle.seal()
                answer, receipt = reader.answer(
                    case.question,
                    bundle,
                    originals,
                    frontier=frontier,
                    revoked=set(),
                    token_limit=1024,
                )
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("blank Reader output")
                row.update(status="succeeded", answer=answer, reader=receipt)
            except Exception as exc:
                row.update(
                    status="failed", error_type=type(exc).__name__, error=str(exc)[:512]
                )
            row["elapsed_seconds"] = time.perf_counter() - started
            rows.append(row)
            append(output / "raw-answers.jsonl", row)
        raw = (output / "raw-answers.jsonl").read_bytes()
        seal = hashlib.sha256(raw).hexdigest()
        write(
            output / "raw-seal.json",
            dict(sha256=seal, rows=len(rows), scoring_started=False),
        )
        all_census, scores, summary = evaluate(rows, cases)
        write(output / "census.json", all_census)
        write(output / "scored.json", scores)
        write(
            output / "summary.json",
            dict(
                census=all_census,
                arms=summary,
                source_commit=source_commit,
                independent_human_adequacy=False,
                production_accepted=False,
            ),
        )
        if (
            hashlib.sha256((output / "raw-answers.jsonl").read_bytes()).hexdigest()
            != seal
        ):
            raise ValueError("raw answers changed during scoring")
        if all_census["failed"]:
            raise RuntimeError("failed Reader calls retained; experiment incomplete")
        return dict(census=all_census, arms=summary)
    except BaseException as exc:
        write(
            output / "run-failure.json",
            dict(
                error_type=type(exc).__name__,
                error=str(exc)[:512],
                planned=len(all_pairs),
                attempted=len(rows),
                incomplete_work_not_free=True,
            ),
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reader", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    if not args.development:
        raise ValueError("synthetic experiment requires explicit --development")
    from bundle_reader import FrozenBundleReader
    from stem_cell_trial import READER

    reader = FrozenBundleReader(args.reader, expected_inventory=READER)
    result = run(
        args.output,
        reader,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    reader.verify_frozen()
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
