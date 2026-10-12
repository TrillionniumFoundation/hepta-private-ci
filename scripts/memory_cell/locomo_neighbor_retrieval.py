"""Exploratory, source-only LoCoMo adjacency recall at frozen lexical-k8 byte cost.

No benchmark gold enters ranking, no parameter learning, reader calls or claims
of independent human support. Public test data have already been exposed.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

STOP = frozenset(
    "what when where why who how which did does do is was are were a an the in on "
    "at of for and to from with about her his she he they their that this it by "
    "have has had kind like".split()
)
WORD = re.compile(r"[^\W_]+", re.UNICODE)
TURN = re.compile(r"^(.*?/D[0-9]+:)([0-9]+)$")
WEIGHT = 0.6
LIMIT = 8
ARMS = ("lexical_k8", "neighbor_k8_bytebound")


def canonical(obj):
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def score_terms(question, documents):
    """Frozen local BM25; same corpus and no publisher QA evidence."""
    terms = set(WORD.findall(question.lower()))
    terms -= STOP
    if not terms:
        terms = set(WORD.findall(question.lower()))
    if not terms or not documents:
        raise ValueError("no bounded query terms or original sources")
    counts = [Counter(WORD.findall(d["content"].lower())) for d in documents]
    lengths = [sum(c.values()) for c in counts]
    average = sum(lengths) / len(lengths)
    df = {t: sum(t in c for c in counts) for t in terms}
    result = {}
    for d, cnt, length in zip(documents, counts, lengths, strict=True):
        score = 0.0
        for term in terms:
            tf = cnt[term]
            if tf:
                score += (
                    math.log1p((len(documents) - df[term] + 0.5) / (df[term] + 0.5))
                    * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / max(average, 1)))
                )
        result[d["identity"]] = score
    return result


def neighbor_rank(question, documents):
    """Boost only immediate turns within the same registered D-session."""
    base = score_terms(question, documents)
    neighbors = {}
    for key, value in base.items():
        match = TURN.fullmatch(key)
        if match and value > 0:
            for delta in (-1, 1):
                index = int(match[2]) + delta
                sibling = match[1] + str(index)
                if index > 0 and sibling in base:
                    neighbors[sibling] = max(neighbors.get(sibling, 0.0), WEIGHT * value)
    return sorted(base, key=lambda k: (-(base[k] + neighbors.get(k, 0.0)), k))


def pack(question, originals, baseline):
    """No excerpt truncation or token proxy: hard cap the ORIGINAL UTF-8 source bytes."""
    if (
        len(set(d["identity"] for d in originals)) != len(originals)
        or len(baseline) != LIMIT or len(set(baseline)) != LIMIT
        or not set(baseline) <= {d["identity"] for d in originals}
    ):
        raise ValueError("invalid exact lexical-k8 candidate control")
    docs = {d["identity"]: d for d in originals}
    budget = sum(len(docs[k]["content"].encode()) for k in baseline)
    remaining = budget
    chosen = []
    for key in neighbor_rank(question, originals):
        cost = len(docs[key]["content"].encode())
        if 0 < cost <= remaining:
            chosen.append(key)
            remaining -= cost
            if len(chosen) == LIMIT:
                break
    if len(set(chosen)) != len(chosen) or budget - remaining > budget:
        raise ValueError("duplicate or oversized neighbor evidence")
    return chosen, budget - remaining, budget


def decisions(public, documents, frozen):
    """Compute both arms from source only, verifying every frozen old control."""
    from locomo_ninearm_source_replay import rank
    rows = []
    by_qid = {(r["question_id"], r["arm"]): r for r in frozen}
    for split in ("train", "selection", "evaluation"):
        for q in public["splits"][split]:
            qid = q["question_id"]
            original = [documents[s] for s in q["source_ids"]]
            baseline = rank(q, original)["lexical"][:LIMIT]
            expected = by_qid[(qid, "lexical_k8")]
            if (
                baseline != expected["selected"]
                or q["family_proxy_digest"] != expected["family_proxy_digest"]
                or q["source_census_sha256"] != expected["source_census_sha256"]
                or expected["split"] != split
            ):
                raise ValueError("frozen historical BM25 lexical-k8 changed")
            chosen, cost, original_bytes = pack(q["question"], original, baseline)
            if original_bytes != expected["selected_source_bytes"]:
                raise ValueError("original source-byte budget altered")
            for arm, selected, used in (
                (ARMS[0], baseline, original_bytes),
                (ARMS[1], chosen, cost),
            ):
                rows.append(dict(
                    question_id=qid, family_proxy_digest=q["family_proxy_digest"],
                    split=split, source_census_sha256=q["source_census_sha256"],
                    arm=arm, selected=selected, selected_source_bytes=used,
                    frozen_baseline_source_bytes=original_bytes,
                ))
    if len(rows) != 160 or len({(r["question_id"], r["arm"]) for r in rows}) != 160:
        raise ValueError("incomplete original 80x2 cohort")
    return rows


def _write_once(path, data):
    if path.is_symlink() or path.exists():
        raise ValueError("cannot overwrite source-only journal or report")
    with path.open("xb") as file:
        file.write(data)
        file.flush()
        import os
        os.fsync(file.fileno())


def load_and_verify(public_root, directory):
    from locomo_ninearm_source_replay import (
        check_roles, compute, load_public, verify_original_six, strict_json,
    )
    check_roles(public_root)
    pop, docs = load_public(public_root)
    frozen = compute(pop, docs)
    verify_original_six(public_root, frozen)
    rows = decisions(pop, docs, frozen)
    raw = b"".join(canonical(row) + b"\n" for row in rows)
    if (directory / "source-only-decisions.jsonl").read_bytes() != raw:
        raise ValueError("source-only decisions differ from original frozen source")
    receipt = strict_json((directory / "receipt.json").read_bytes())
    if (
        receipt["schema"] != "hepta.locomo.neighbor-source-only.v1"
        or receipt["original_frozen_six_verified"] != 480
        or receipt["decision_sha256"] != sha(raw)
        or receipt["target_labels_read_during_retrieval"] is not False
        or receipt["new_model_calls"] != 0
    ):
        raise ValueError("not an immutable source-only retrieval census")
    return pop, rows


def retrieve(public_root, directory):
    from locomo_ninearm_source_replay import (
        check_roles, compute, load_public, verify_original_six, strict_json,
    )
    check_roles(public_root)
    pop, docs = load_public(public_root)
    frozen = compute(pop, docs)
    n = verify_original_six(public_root, frozen)
    rows = decisions(pop, docs, frozen)
    raw = b"".join(canonical(r) + b"\n" for r in rows)
    directory.mkdir(parents=True, exist_ok=False)
    _write_once(directory / "source-only-decisions.jsonl", raw)
    receipt = dict(
        schema="hepta.locomo.neighbor-source-only.v1",
        source_commit=pop["generating_source_commit"],
        original_frozen_six_verified=n,
        decision_sha256=sha(raw), planned_questions=80,
        arms=list(ARMS), fixed_weight=WEIGHT, max_sources=LIMIT,
        source_byte_budget="per-query original lexical_k8",
        target_labels_read_during_retrieval=False,
        exploratory_public_development_after_multiple_variants_inspected=True,
        new_model_calls=0, independent_source_families=0,
        semantic_citation_precision=None, production_accepted=False,
    )
    _write_once(directory / "receipt.json", canonical(receipt) + b"\n")
    return receipt


def scoring(pop, rows, split, labels):
    questions = pop["splits"][split]
    if set(labels) != {q["question_id"] for q in questions}:
        raise ValueError("missing or leaked scoring split")
    table = {(r["question_id"], r["arm"]): r for r in rows}
    result = {}
    for arm in ARMS:
        outcomes = []
        for q in questions:
            label = labels[q["question_id"]]
            evidence = label["support"]
            eligible = (
                bool(evidence) and not label["unanswerable"]
                and not label["unresolved_support"]
                and set(evidence) <= set(q["source_ids"])
            )
            row = table[(q["question_id"], arm)]
            outcomes.append(dict(
                question_id=q["question_id"],
                family_proxy_digest=q["family_proxy_digest"],
                eligible=bool(eligible),
                covered=bool(eligible and set(evidence) <= set(row["selected"])),
                selected_source_bytes=row["selected_source_bytes"],
                chosen_count=len(row["selected"]),
            ))
        result[arm] = outcomes
    paired = []
    for b, c in zip(result[ARMS[0]], result[ARMS[1]], strict=True):
        if (b["question_id"], b["eligible"]) != (c["question_id"], c["eligible"]):
            raise ValueError("pair census drift")
        paired.append(dict(
            question_id=b["question_id"],
            family_proxy_digest=b["family_proxy_digest"],
            eligible=b["eligible"],
            baseline_covered=b["covered"],
            neighbor_covered=c["covered"],
        ))
    return dict(
        planned=len(questions),
        eligible=sum(x["eligible"] for x in paired),
        baseline_covered=sum(x["baseline_covered"] for x in paired),
        neighbor_covered=sum(x["neighbor_covered"] for x in paired),
        wins=sum(x["eligible"] and x["neighbor_covered"] and not x["baseline_covered"] for x in paired),
        losses=sum(x["eligible"] and x["baseline_covered"] and not x["neighbor_covered"] for x in paired),
        baseline_bytes=sum(x["selected_source_bytes"] for x in result[ARMS[0]]),
        neighbor_bytes=sum(x["selected_source_bytes"] for x in result[ARMS[1]]),
        by_family={
            family: dict(eligible=sum(x["eligible"] for x in paired if x["family_proxy_digest"] == family),
                         baseline_covered=sum(x["baseline_covered"] for x in paired if x["family_proxy_digest"] == family),
                         neighbor_covered=sum(x["neighbor_covered"] for x in paired if x["family_proxy_digest"] == family))
            for family in sorted({x["family_proxy_digest"] for x in paired})
        },
        paired=paired,
        support_is_native_document_reference_not_entailment=True,
        new_reader_answers=0,
        independent_semantic_citation_precision=None,
        production_accepted=False,
    )


def select(public_root, label_root, directory):
    from locomo_ninearm_source_replay import check_roles, read_zip, strict_json
    check_roles(public_root, label_root)
    pop, rows = load_and_verify(public_root, directory)
    targets = strict_json(read_zip(label_root, "selection")["targets.json"])
    score = scoring(pop, rows, "selection", targets)
    # Do not tune weights on these labels: the preselected hypothesis is fixed.
    policy = dict(
        schema="hepta.locomo.neighbor-selection.v1",
        source_decision_sha256=sha((directory / "source-only-decisions.jsonl").read_bytes()),
        selection=score,
        # This is exploratory; previous public-result inspection invalidates blind claims.
        research_candidate_only=score["neighbor_covered"] > score["baseline_covered"]
        and score["neighbor_bytes"] <= score["baseline_bytes"],
        weights_selected_from_test_labels=False,
        independent_prospective_validation=False,
        production_accepted=False,
    )
    _write_once(directory / "selection-policy.json", canonical(policy) + b"\n")
    return policy


def evaluate(public_root, select_root, eval_root, directory):
    from locomo_ninearm_source_replay import check_roles, read_zip, strict_json
    check_roles(public_root, select_root, eval_root)
    pop, rows = load_and_verify(public_root, directory)
    selraw = (directory / "selection-policy.json").read_bytes()
    policy = strict_json(selraw)
    selection = scoring(pop, rows, "selection", strict_json(read_zip(select_root, "selection")["targets.json"]))
    if (
        policy["schema"] != "hepta.locomo.neighbor-selection.v1"
        or policy["source_decision_sha256"] != sha((directory / "source-only-decisions.jsonl").read_bytes())
        or policy["selection"] != selection
        or policy["weights_selected_from_test_labels"] is not False
    ):
        raise ValueError("original selection policy changed")
    result = scoring(pop, rows, "evaluation", strict_json(read_zip(eval_root, "evaluation")["targets.json"]))
    output = dict(
        schema="hepta.locomo.neighbor-exploratory-evaluation.v1",
        decision_sha256=policy["source_decision_sha256"],
        selection_policy_sha256=sha(selraw),
        result=result,
        public_development_cohort_already_inspected=True,
        output_cannot_prove_reader_quality=True,
        independent_family_n=0,
        semantic_citation_precision=None,
        production_accepted=False,
    )
    _write_once(directory / "evaluation.json", canonical(output) + b"\n")
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for cmd in ("retrieve", "select", "evaluate"):
        s = sub.add_parser(cmd)
        s.add_argument("public", type=Path)
        if cmd in ("select", "evaluate"):
            s.add_argument("selection", type=Path)
        if cmd == "evaluate":
            s.add_argument("evaluation", type=Path)
        s.add_argument("output", type=Path)
    args = p.parse_args()
    if args.command == "retrieve":
        result = retrieve(args.public, args.output)
    elif args.command == "select":
        result = select(args.public, args.selection, args.output)
    else:
        result = evaluate(args.public, args.selection, args.evaluation, args.output)
    print(json.dumps(result, ensure_ascii=False)[:2000])


if __name__ == "__main__":
    main()
