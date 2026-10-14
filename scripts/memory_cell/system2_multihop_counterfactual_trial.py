"""Frozen Reader counterfactual relation-composition experiment.

Positive evidence and absent-link controls are generated without selecting from
answer labels. Every raw answer is sealed before synthetic answer/citation scoring.
Synthetic numbers/symbols and language are not independent human judgments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time

from system2_multihop_counterfactual import ARMS, PAIRS, cases, select, source_manifest
from system2_multihop_evidence import digest, join_path
from system2_multihop_trial import ABSTAIN, CITATION_RE, TOKEN_RE, evidence


def write(path, item):
    with path.open("x", encoding="utf-8") as f:
        json.dump(item, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def append(path, item):
    with path.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(item, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        )
        f.flush()
        os.fsync(f.fileno())


def score(case, selected, raw):
    """Ground truth enters only AFTER the raw answer journal has been sealed."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("nonempty raw Reader output required")
    path = join_path(case.question, selected)
    complete = len(path) == case.hops and set(case.required_ids).issubset(
        d.identity for d in selected
    )
    if complete != bool(path):
        raise ValueError("inconsistent evidence sufficiency")
    mentions = TOKEN_RE.findall(raw.upper())
    exact = len(mentions) == 1 and mentions[0] == case.answer
    abstain = raw.strip().strip('"').casefold() == ABSTAIN.casefold()
    citations = [label.upper() for label in CITATION_RE.findall(raw)]
    label_to_doc = {"E" + str(i + 1): d.identity for i, d in enumerate(selected)}
    valid = bool(citations) and all(label in label_to_doc for label in citations)
    cited = {label_to_doc[label] for label in citations} if valid else set()
    cites_required = valid and complete and set(case.required_ids).issubset(cited)
    return dict(
        programmatic_evidence_sufficient=complete,
        raw_answer_exact=exact,
        cites_required=bool(cites_required),
        citation_syntax_valid=valid,
        raw_abstention_exact=abstain,
        copied_target_without_path=bool(exact and not complete),
        strict_success=bool(exact and cites_required) if complete else abstain,
        synthetic_not_independently_adjudicated=True,
    )


def evaluate(rows, pairs):
    cmap = {
        c.question.identity: (j, v, c)
        for j, pair in enumerate(pairs)
        for v, c in enumerate(pair)
    }
    expected = {(qid, arm) for qid in cmap for arm in ARMS}
    keys = [(r["qid"], r["arm"]) for r in rows]
    if (
        len(keys) != len(expected)
        or len(set(keys)) != len(keys)
        or set(keys) != expected
    ):
        raise ValueError("incomplete/duplicated matched counterfactual census")
    if any(r["status"] not in ("succeeded", "failed") for r in rows):
        raise ValueError("unrecognized Reader status")
    scored = []
    for r in rows:
        row = dict(qid=r["qid"], arm=r["arm"], status=r["status"])
        if r["status"] == "succeeded":
            j, v, c = cmap[r["qid"]]
            selected = select(r["arm"], c.question, c.documents)
            if r["selected"] != [d.identity for d in selected]:
                raise ValueError("post-seal selector drift")
            row.update(pair_index=j, variant=v, **score(c, selected, r["answer"]))
        else:
            row.update(strict_success=None, error_type=r.get("error_type"))
        scored.append(row)
    out = []
    for arm in ARMS:
        group = [r for r in scored if r["arm"] == arm]
        ok = [r for r in group if r["status"] == "succeeded"]
        by_key = {(r.get("pair_index"), r.get("variant")): r for r in ok}
        double = 0
        for j in range(len(pairs)):
            a = by_key.get((j, 0))
            b = by_key.get((j, 1))
            if a is not None and b is not None:
                double += int(
                    a["raw_answer_exact"]
                    and a["cites_required"]
                    and b["raw_answer_exact"]
                    and b["cites_required"]
                )
        out.append(
            dict(
                arm=arm,
                planned=len(group),
                completed=len(ok),
                failed=len(group) - len(ok),
                complete_evidence=sum(
                    r["programmatic_evidence_sufficient"] for r in ok
                ),
                exact_answers=sum(r["raw_answer_exact"] for r in ok),
                correct_citations=sum(r["cites_required"] for r in ok),
                strict_successes=sum(r["strict_success"] for r in ok),
                unsupported_target_copy=sum(
                    r["copied_target_without_path"] for r in ok
                ),
                abstentions=sum(r["raw_abstention_exact"] for r in ok),
                both_counterfactual_variants_exact_and_cited=double,
                pair_denominator=len(pairs),
                unknown_failures_not_imputed=True,
            )
        )
    return scored, out


def run(output, reader, *, source_commit, num_pairs=PAIRS):
    if (
        not re.fullmatch(r"[0-9a-f]{40}", source_commit or "")
        or type(num_pairs) is not int
        or not 1 <= num_pairs <= PAIRS
    ):
        raise ValueError("bounded exact experiment parameters required")
    pairs = cases()[:num_pairs]
    expected = 2 * len(pairs) * len(ARMS)
    output.mkdir(parents=True, exist_ok=False)
    plan = dict(
        schema="hepta.system2.counterfactual-reader.v1",
        source_commit=source_commit,
        pair_count=len(pairs),
        planned_reader_calls=expected,
        pairs=[
            dict(
                pair_index=j,
                questions=[c.question.identity for c in pair],
                source_manifests=[source_manifest(c) for c in pair],
                hops=pair[0].hops,
            )
            for j, pair in enumerate(pairs)
        ],
        arms=list(ARMS),
        matched_global_document_token_bag=True,
        matched_question_text=True,
        original_results_not_rewritten=True,
        reader_input_limit=1024,
        frozen_reader_and_no_training=True,
        no_eval_target_online=True,
        synthetic_no_independent_human_verdict=True,
        exact_compute_matched=False,
        production_accepted=False,
    )
    write(output / "plan.json", plan)
    attempted = []
    entries = [
        (j, v, case, arm)
        for j, pair in enumerate(pairs)
        for v, case in enumerate(pair)
        for arm in ARMS
    ]
    entries.sort(
        key=lambda x: (
            x[0],
            (
                x[1] * len(ARMS)
                + ARMS.index(x[3])
                + int(digest(x[2].question.content)[:8], 16)
            )
            % (2 * len(ARMS)),
        )
    )
    try:
        for j, v, case, arm in entries:
            row = dict(
                pair_index=j,
                variant=v,
                qid=case.question.identity,
                arm=arm,
                source_manifest=source_manifest(case),
                status="started",
            )
            append(output / "starts.jsonl", row)
            started = time.perf_counter()
            try:
                selected = select(arm, case.question, case.documents)
                bundle, originals, frontier = evidence(case, selected, arm)
                row.update(
                    selected=[d.identity for d in selected],
                    evidence_count=len(selected),
                    bundle_digest=bundle.seal(),
                    scanned_document_bytes=sum(
                        len(d.content.encode("utf-8")) for d in case.documents
                    ),
                )
                answer, receipt = reader.answer(
                    case.question,
                    bundle,
                    originals,
                    frontier=frontier,
                    revoked=set(),
                    token_limit=1024,
                )
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("empty Reader generation")
                row.update(status="succeeded", answer=answer, reader=receipt)
            except Exception as ex:
                row.update(
                    status="failed",
                    error_type=type(ex).__name__,
                    error=str(ex)[:512],
                    unknown_cost=True,
                )
            row["elapsed_seconds"] = time.perf_counter() - started
            attempted.append(row)
            append(output / "raw-answers.jsonl", row)
        raw = (output / "raw-answers.jsonl").read_bytes()
        digest_raw = hashlib.sha256(raw).hexdigest()
        write(
            output / "raw-seal.json",
            dict(sha256=digest_raw, rows=len(attempted), scoring_started=False),
        )
        scored, summary = evaluate(attempted, pairs)
        write(output / "scored.json", scored)
        census = dict(
            planned=expected,
            recorded=len(attempted),
            succeeded=sum(x["status"] == "succeeded" for x in attempted),
            failed=sum(x["status"] == "failed" for x in attempted),
            independent_pairs=len(pairs),
            synthetic_only=True,
        )
        write(
            output / "summary.json",
            dict(
                census=census,
                arms=summary,
                source_commit=source_commit,
                independent_human_semantic_review=False,
                production_accepted=False,
            ),
        )
        if (
            hashlib.sha256((output / "raw-answers.jsonl").read_bytes()).hexdigest()
            != digest_raw
        ):
            raise ValueError("raw answer seal drift")
        if census["failed"]:
            raise RuntimeError("Reader failures retained; trial not complete")
        return dict(census=census, arms=summary)
    except BaseException as ex:
        write(
            output / "run-failure.json",
            dict(
                error_type=type(ex).__name__,
                error=str(ex)[:512],
                planned=expected,
                attempted=len(attempted),
                missing_work_not_free=True,
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
        raise ValueError("explicit development mode required")
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
