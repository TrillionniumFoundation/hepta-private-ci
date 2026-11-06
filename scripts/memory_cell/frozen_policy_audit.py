"""Task comparisons for the frozen-session policy study, not acceptance."""

import math

ARMS = ("hybrid", "organized", "initial", "learned")


def summarize(rows, questions):
    if (
        not questions
        or len(questions) != len(set(questions))
        or len(rows) != len(questions) * len(ARMS)
        or {(r["question_id"], r["arm"]) for r in rows}
        != {(q, a) for q in questions for a in ARMS}
    ):
        raise ValueError("complete unique paired task census required")
    by_query, profiles = {}, set()
    for row in rows:
        if row["status"] not in ("succeeded", "failed"):
            raise ValueError("unknown task status")
        by_query.setdefault(row["question_id"], {})[row["arm"]] = row
        if row["status"] == "succeeded":
            r = row["receipt"]
            profiles.add((r["reader_identity"], r["reader_profile"]))
            if type(row.get("strict_task_success")) is not bool:
                raise ValueError("successful task must have an actual score")
            if row["session_record"]["query_train_tokens"] != 0:
                raise ValueError("query-time updates violate frozen experiment")
            for key in ("input_tokens", "generated_tokens"):
                if type(r[key]) is not int or r[key] < 0:
                    raise ValueError("invalid measured token count")
            if (
                type(r["seconds"]) not in (int, float)
                or not math.isfinite(r["seconds"])
                or r["seconds"] < 0
            ):
                raise ValueError("invalid measured time")
            if row["kind"] == "procedure" and row["strict_task_success"] != (
                row["procedure_verification"]["exit_code"] == 0
            ):
                raise ValueError("procedure score not tied to actual worker exit")
    if len(profiles) != 1:
        raise ValueError("no shared fixed reader")
    for group in by_query.values():
        if len({(r["candidate_digest"], r["kind"]) for r in group.values()}) != 1:
            raise ValueError("comparison changed candidate pool or task kind")
    arms = {}
    for arm in ARMS:
        group = [r for r in rows if r["arm"] == arm]
        good = [r for r in group if r["status"] == "succeeded"]
        arms[arm] = dict(
            planned=len(group),
            succeeded=len(good),
            failed=len(group) - len(good),
            strict_successes=sum(r["strict_task_success"] for r in good),
            per_kind={
                k: dict(
                    planned=sum(r["kind"] == k for r in group),
                    strict_successes=sum(
                        r["strict_task_success"] for r in good if r["kind"] == k
                    ),
                )
                for k in sorted({r["kind"] for r in group})
            },
            inference_seconds=sum(r["receipt"]["seconds"] for r in good),
            input_tokens=sum(r["receipt"]["input_tokens"] for r in good),
            generated_tokens=sum(r["receipt"]["generated_tokens"] for r in good),
        )
    contrasts = {}
    for base in ("hybrid", "organized", "initial"):
        wins = losses = missing = changed = 0
        for group in by_query.values():
            a, b = group[base], group["learned"]
            if a["status"] != "succeeded" or b["status"] != "succeeded":
                missing += 1
                continue
            wins += b["strict_task_success"] and not a["strict_task_success"]
            losses += a["strict_task_success"] and not b["strict_task_success"]
            changed += a["selected"] != b["selected"]
        contrasts[base] = dict(
            paired_wins=wins,
            paired_losses=losses,
            missing_pairs=missing,
            selection_changes=changed,
            all_planned_delta_bounds=[
                (wins - losses - missing) / len(questions),
                (wins - losses + missing) / len(questions),
            ],
            significance_established=False,
        )
    return dict(
        arms=arms,
        contrasts=contrasts,
        all_attempts=len(rows),
        evaluated_public_controlled_cases=True,
        semantic_citation_precision=None,
        task_success_is_not_citation_entailment=True,
        production_accepted=False,
    )
