"""Pre-Reader scoring audit: distinguish safe abstention from useful answers.

Deterministic symbolic responder is a TEST POSITIVE CONTROL, not a learned model
or independent human adjudicator. It sees only the selected evidence snippets,
never the Case.answer, gold path identities, or hidden documents. Adversarial
responses are explicit scoring probes, never model outputs.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from system2_multihop_counterfactual import ARMS, PAIRS, cases, select, source_manifest
from system2_multihop_counterfactual_trial import score
from system2_multihop_evidence import digest, join_path, parse_relation
from system2_multihop_trial import ABSTAIN


AUDIT_SCHEMA = "hepta.system2.counterfactual-scorer-audit.v1"


def write(path, value):
    with path.open("x", encoding="utf-8") as output:
        json.dump(
            value, output, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        output.write("\n")


def answer_from_delivered(question, selected):
    """TEST-ONLY: typed composition over delivered text, no hidden gold answer.

    This establishes that sufficient input evidence is executable, not that the
    real frozen generative Reader can follow it. Source labels are derived from
    their actual delivered positions, including reversed presentation.
    """
    path = join_path(question, selected)
    if not path:
        return ABSTAIN
    final = parse_relation(path[-1])
    if final is None or final[2] != "token":
        raise ValueError("unexpected terminal relation type")
    labels = [
        "[E"
        + str(
            next(
                j for j, doc in enumerate(selected, 1) if doc.identity == edge.identity
            )
        )
        + "]"
        for edge in path
    ]
    return final[3] + " " + " ".join(labels)


def diagnostics(scored, pairs):
    """Use a fixed task denominator even when selection lacks enough evidence."""
    n_questions = 2 * len(pairs)
    grouped = defaultdict(list)
    for row in scored:
        grouped[row["arm"]].append(row)
    if set(grouped) != set(ARMS):
        raise ValueError("missing scorer audit arm")
    out = []
    for arm in ARMS:
        rows = grouped[arm]
        if (
            len(rows) != n_questions
            or len({(x["pair_index"], x["variant"]) for x in rows}) != n_questions
        ):
            raise ValueError("partial or duplicated scorer condition")
        suff = sum(r["programmatic_evidence_sufficient"] for r in rows)
        useful = sum(
            r["programmatic_evidence_sufficient"]
            and r["raw_answer_exact"]
            and r["cites_required"]
            for r in rows
        )
        safe_refusals = sum(
            not r["programmatic_evidence_sufficient"] and r["raw_abstention_exact"]
            for r in rows
        )
        unsafe_copy = sum(r["copied_target_without_path"] for r in rows)
        strict = sum(r["strict_success"] for r in rows)
        if useful + safe_refusals != strict:
            raise ValueError("strict success failed its evidence decomposition")
        by_pair = {(r["pair_index"], r["variant"]): r for r in rows}
        both = sum(
            int(
                all(
                    by_pair[j, v]["programmatic_evidence_sufficient"]
                    and by_pair[j, v]["raw_answer_exact"]
                    and by_pair[j, v]["cites_required"]
                    for v in (0, 1)
                )
            )
            for j in range(len(pairs))
        )
        out.append(
            dict(
                arm=arm,
                questions=n_questions,
                sufficient_evidence=suff,
                verified_answer_yield=useful,
                correct_refusals=safe_refusals,
                strict_successes=strict,
                unsupported_answer_copy=unsafe_copy,
                both_counterfactual_variants_answered=both,
                pair_denominator=len(pairs),
                useful_answer_rate=useful / n_questions,
                abstention_does_not_count_as_answer=True,
            )
        )
    return out


def run(output, *, count=PAIRS):
    if type(count) is not int or not 1 <= count <= PAIRS:
        raise ValueError("bounded fixed pair subset required")
    pairset = cases()[:count]
    output.mkdir(parents=True, exist_ok=False)
    plan = dict(
        schema=AUDIT_SCHEMA,
        pairs=len(pairset),
        arms=list(ARMS),
        oracle_kind="deterministic test positive control, not neural Reader",
        source_identity=digest([case.question.identity for p in pairset for case in p]),
        no_neural_model_invoked=True,
        online_case_answers_read=False,
        true_semantic_adequacy_established=False,
        production_accepted=False,
    )
    write(output / "plan.json", plan)
    rows = []
    for j, pair in enumerate(pairset):
        for v, case in enumerate(pair):
            for arm in ARMS:
                selected = select(arm, case.question, case.documents)
                raw = answer_from_delivered(case.question, selected)
                outcome = score(case, selected, raw)
                rows.append(
                    dict(
                        pair_index=j,
                        variant=v,
                        arm=arm,
                        qid=case.question.identity,
                        evidence_ids=[d.identity for d in selected],
                        raw=raw,
                        **outcome,
                    )
                )
    expected = 2 * count * len(ARMS)
    if len(rows) != expected:
        raise ValueError("incomplete positive-control audit")
    digest_rows = hashlib.sha256(
        json.dumps(
            rows,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    write(output / "positive-control-rows.json", rows)
    summary = diagnostics(rows, pairset)
    write(
        output / "summary.json",
        dict(
            plan=plan,
            planned=expected,
            completed=len(rows),
            positive_control_digest=digest_rows,
            methods=summary,
            no_neural_result_claim=True,
            independent_human_review=False,
        ),
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sealed-reader-run", type=Path)
    args = parser.parse_args()
    result = (
        audit_sealed_model_run(args.sealed_reader_run, args.output)
        if args.sealed_reader_run
        else run(args.output)
    )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


def audit_sealed_model_run(source, output, *, count=PAIRS):
    """Post-seal audit; model responses are read-only, unknown failures retained.

    This must run *after* the frozen Reader trial. The original answers and their
    published scorer are independently checked against their immutable raw seal.
    It cannot rewrite answers, change evidence, or substitute a test oracle.
    """
    from system2_multihop_counterfactual_trial import evaluate

    if type(count) is not int or not 1 <= count <= PAIRS:
        raise ValueError("registered pair count required")
    pairset = cases()[:count]
    original_plan = json.loads((source / "plan.json").read_text(encoding="utf-8"))
    if (
        original_plan.get("schema") != "hepta.system2.counterfactual-reader.v1"
        or original_plan.get("pair_count") != count
        or original_plan.get("arms") != list(ARMS)
        or original_plan.get("planned_reader_calls") != 2 * count * len(ARMS)
    ):
        raise ValueError("original Reader experiment plan identity changed")
    source_commit = original_plan.get("source_commit")
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(c not in "0123456789abcdef" for c in source_commit)
    ):
        raise ValueError("original generating commit is unavailable")
    expected_pairs = [
        dict(
            pair_index=j,
            questions=[c.question.identity for c in pair],
            source_manifests=[source_manifest(c) for c in pair],
            hops=pair[0].hops,
        )
        for j, pair in enumerate(pairset)
    ]
    if original_plan.get("pairs") != expected_pairs:
        raise ValueError("question or source identity drift")

    raw = (source / "raw-answers.jsonl").read_bytes()
    seal = json.loads((source / "raw-seal.json").read_text(encoding="utf-8"))
    planned = 2 * count * len(ARMS)
    if (
        seal.get("scoring_started") is not False
        or seal.get("sha256") != hashlib.sha256(raw).hexdigest()
        or seal.get("rows") != planned
        or len(raw.splitlines()) != planned
    ):
        raise ValueError("missing or mutated original sealed Reader outputs")
    rows = [json.loads(line) for line in raw.splitlines()]
    rescored, original_summary = evaluate(rows, pairset)
    expected_score = json.loads((source / "scored.json").read_text(encoding="utf-8"))
    if expected_score != rescored:
        raise ValueError("original post-seal scoring drift")
    published = json.loads((source / "summary.json").read_text(encoding="utf-8"))
    if (
        published.get("arms") != original_summary
        or published.get("source_commit") != source_commit
        or published.get("census", {}).get("planned") != planned
    ):
        raise ValueError("original published Reader summary drift")

    # Every question/arm is accounted for. A failed Reader call remains unknown:
    # a fallback deterministic answer must not silently substitute for it.
    lookup = {
        case.question.identity: (j, variant, case)
        for j, pair in enumerate(pairset)
        for variant, case in enumerate(pair)
    }
    by_arm = defaultdict(list)
    if len({(r["qid"], r["arm"]) for r in rows}) != planned:
        raise ValueError("missing or duplicate Reader journal identities")
    for row, scored in zip(rows, rescored, strict=True):
        if row["qid"] not in lookup or row["arm"] not in ARMS:
            raise ValueError("unknown Reader audit condition")
        j, variant, case = lookup[row["qid"]]
        expected_evidence = select(row["arm"], case.question, case.documents)
        sufficient = len(join_path(case.question, expected_evidence)) == case.hops
        if row["status"] == "succeeded":
            receipt = row.get("reader")
            if (
                not isinstance(receipt, dict)
                or type(receipt.get("input_tokens")) is not int
                or type(receipt.get("generated_tokens")) is not int
                or not 0 < receipt["input_tokens"] <= 1024
                or not 0 <= receipt["generated_tokens"] <= 64
                or not receipt.get("reader_identity")
                or not receipt.get("reader_profile")
            ):
                raise ValueError("incomplete frozen Reader cost/identity receipt")
            if scored["programmatic_evidence_sufficient"] != sufficient:
                raise ValueError("selector/source sufficiency drift")
        by_arm[row["arm"]].append(
            dict(
                pair_index=j,
                variant=variant,
                sufficient=sufficient,
                status=row["status"],
                raw=scored,
                reader=row.get("reader"),
            )
        )
    reader_ident = {
        (r["reader"]["reader_identity"], r["reader"]["reader_profile"])
        for vals in by_arm.values()
        for r in vals
        if r["status"] == "succeeded"
    }
    if len(reader_ident) > 1:
        raise ValueError(
            "multiple Reader/model/prompt identities in matched experiment"
        )
    results = []
    for arm in ARMS:
        parts = by_arm[arm]
        if (
            len(parts) != 2 * count
            or len({(r["pair_index"], r["variant"]) for r in parts}) != 2 * count
        ):
            raise ValueError("incomplete per-arm Reader pair denominator")
        done = [r for r in parts if r["status"] == "succeeded"]
        failed = [r for r in parts if r["status"] != "succeeded"]
        sufficient = sum(r["sufficient"] for r in parts)
        yielded = sum(
            r["raw"]["raw_answer_exact"]
            and r["raw"]["cites_required"]
            and r["sufficient"]
            for r in done
        )
        refusers = sum(
            r["raw"]["raw_abstention_exact"] and not r["sufficient"] for r in done
        )
        copied = sum(r["raw"]["copied_target_without_path"] for r in done)
        unknown_sufficient = sum(r["sufficient"] for r in failed)
        unknown_refusal = len(failed) - unknown_sufficient
        double = 0
        pending_pairs = 0
        indexed = {(r["pair_index"], r["variant"]): r for r in parts}
        for j in range(count):
            pair = [indexed[j, v] for v in (0, 1)]
            if any(r["status"] != "succeeded" for r in pair):
                pending_pairs += 1
            elif all(
                r["sufficient"]
                and r["raw"]["raw_answer_exact"]
                and r["raw"]["cites_required"]
                for r in pair
            ):
                double += 1
        results.append(
            dict(
                arm=arm,
                planned=2 * count,
                completed=len(done),
                failed=len(failed),
                programmatically_sufficient=sufficient,
                useful_verified_answers=yielded,
                correct_refusals=refusers,
                unsupported_target_copies=copied,
                useful_answer_yield_bounds=[yielded, yielded + unknown_sufficient],
                correct_refusal_bounds=[refusers, refusers + unknown_refusal],
                counterfactual_pairs_both_correct=double,
                paired_unknown=pending_pairs,
                pair_denominator=count,
                actual_reader_input_tokens=sum(
                    r["reader"]["input_tokens"] for r in done
                ),
                actual_reader_generated_tokens=sum(
                    r["reader"]["generated_tokens"] for r in done
                ),
                unknown_failed_costs_not_free=bool(failed),
            )
        )
    output.mkdir(parents=True, exist_ok=False)
    report = dict(
        schema=AUDIT_SCHEMA,
        source_commit=source_commit,
        reader_identity=list(reader_ident),
        original_raw_sha256=seal["sha256"],
        planned=planned,
        completed=sum(r["completed"] for r in results),
        failures=sum(r["failed"] for r in results),
        results=results,
        separate_answer_yield_from_abstention=True,
        actual_model_answers_not_modified=True,
        independent_semantic_judgment=False,
        production_accepted=False,
    )
    write(output / "postseal-reader-yield.json", report)
    return report


if __name__ == "__main__":
    main()
