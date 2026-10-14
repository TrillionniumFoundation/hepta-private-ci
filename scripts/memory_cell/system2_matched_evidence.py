"""Fixed-cardinality evidence selection below the frozen prompt's token budget.

Pure selection mechanics, not a learned sufficiency or stopping policy. Enumerate
at most four subsets of the same top-four proposal. Count complete prompts with
the actual Reader tokenizer; never truncate evidence or consult outcome labels.
"""

from itertools import combinations
import math
import re
import time

POLICY = {
    "schema": "hepta.system2.matched-evidence.v1",
    "proposal_limit": 4,
    "evidence_count": 3,
    "input_token_ceiling": "exact frozen top-three prompt length, at most 4096",
    "ordering": "frozen relevance order within every selected set",
    "objective": "sum of fixed candidate scores; not joint sufficiency",
    "tie_break": "prefer frozen reference, then candidate identities",
    "stop": "fixed min(3,pool size) for ALL evidence arms; not a refusal test",
    "no_evidence_exempt": True,
    "same_exposed_cohort": True,
    "exact_compute_matched": False,
    "production_accepted": False,
}


def choose(candidate_ids, frozen_scores, scores, measure):
    """measure(indices) returns complete input_tokens and input_ids_digest.

    The native adapter may return digest=None only for prompts above the absolute
    4096 limit. Baseline overflow fails the condition, not a silent smaller set.
    Timing and compilation attempts are retained in every successful receipt.
    """
    started = time.perf_counter()
    if (
        not callable(measure)
        or not 0 <= len(candidate_ids) <= 64
        or len(frozen_scores) != len(candidate_ids)
        or len(scores) != len(candidate_ids)
        or any(not isinstance(x, str) or not x for x in candidate_ids)
        or len(set(candidate_ids)) != len(candidate_ids)
        or any(
            type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e6
            for v in (*frozen_scores, *scores)
        )
    ):
        raise ValueError("invalid bounded candidate census or scores")
    proposal = sorted(
        range(len(candidate_ids)), key=lambda i: (-frozen_scores[i], candidate_ids[i])
    )[:4]
    size = min(3, len(proposal))
    reference = tuple(proposal[:size])
    # combinations preserves the same frozen ordering for every Reader prompt.
    paths = [reference] + [p for p in combinations(proposal, size) if p != reference]
    results, ceiling = [], None
    for path in paths:
        measured = measure(list(path))
        tokens, token_digest = measured["input_tokens"], measured["input_ids_digest"]
        if (
            type(tokens) is not int
            or not 1 <= tokens <= 100000
            or (tokens <= 4096 and not re.fullmatch("[0-9a-f]{64}", token_digest or ""))
            or (tokens > 4096 and token_digest is not None)
        ):
            raise ValueError("invalid complete-prompt token measurement")
        if ceiling is None:
            if tokens > 4096:
                raise ValueError(
                    "frozen reference prompt exceeds absolute input budget"
                )
            ceiling = tokens
        results.append(
            dict(
                selected=list(path),
                input_tokens=tokens,
                input_ids_digest=token_digest,
                feasible=tokens <= ceiling,
                objective=math.fsum(scores[i] for i in path),
            )
        )
    best = min(
        (r for r in results if r["feasible"]),
        key=lambda r: (
            -r["objective"],
            tuple(r["selected"]) != reference,
            tuple(candidate_ids[i] for i in r["selected"]),
        ),
    )
    return best["selected"], dict(
        schema=POLICY["schema"],
        proposal=proposal,
        reference=list(reference),
        cardinality=size,
        baseline_input_tokens=ceiling,
        selected_input_tokens=best["input_tokens"],
        selected_input_ids_digest=best["input_ids_digest"],
        compiled_alternatives=len(results),
        alternatives=results,
        unchanged_reference=best["selected"] == list(reference),
        selection_seconds=time.perf_counter() - started,
        label_access=False,
        evidence_truncated=False,
        calibrated_stop=False,
    )


def verify_receipt(selection, receipt):
    """Reject post-selection rendering drift before recording a successful answer."""
    if (
        receipt["input_tokens"] != selection["selected_input_tokens"]
        or receipt["input_ids_digest"] != selection["selected_input_ids_digest"]
        or receipt["input_tokens"] > selection["baseline_input_tokens"]
        or receipt["token_limit"] != 4096
        or receipt["omitted_evidence_bytes"] != 0
        or len(receipt["delivered_evidence"]) != selection["cardinality"]
    ):
        raise ValueError("actual Reader input differs from matched evidence budget")


def summarize(records):
    """Budget integrity is distinct from source-hit and answer-quality metrics."""
    references, successful, compiles, seconds = {}, 0, 0, 0.0
    for row in records:
        detail = row.get("evidence_selection")
        if detail is not None:
            compiles += detail["compiled_alternatives"]
            seconds += detail["selection_seconds"]
        if row["status"] != "succeeded" or row["arm"] == "no_evidence":
            continue
        if detail is None:
            raise ValueError("successful evidence arm lacks budget receipt")
        verify_receipt(detail, row["receipt"])
        qid = row["query_id"]
        key = (
            detail["reference"],
            detail["cardinality"],
            detail["baseline_input_tokens"],
        )
        if qid in references and references[qid] != key:
            raise ValueError("baseline evidence budget changed across arms")
        references[qid] = key
        successful += 1
    return dict(
        policy=POLICY,
        verified_evidence_answers=successful,
        retained_selection_receipt_compilations=compiles,
        successful_selection_seconds=seconds,
        independent_confirmation=False,
        failed_probe_costs="native prompt-probe journal, including failed attempts",
        generated_tokens_and_training_compute_are_not_equalized=True,
    )
