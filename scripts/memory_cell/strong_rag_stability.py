"""Leave-one-task-out sensitivity for a frozen reader's top-k calibration.

Only already scored calibration answers are accepted. Each held-out prediction
uses a k selected from the OTHER calibration tasks, never its own annotation.
This is an overfitting diagnostic on authored development sources, NOT an
independence-adjusted confidence interval or prospective generalization proof.
"""

from collections import Counter

KS = (1, 2, 3, 4, 6)


def leave_one_out(scored, expected):
    """Replay the preregistered success/token/k ordering without model calls."""
    arms = tuple(f"k{k}" for k in KS)
    if (
        not isinstance(expected, (list, tuple))
        or not 2 <= len(expected) <= 64
        or len(set(expected)) != len(expected)
        or len(scored) != len(expected) * len(arms)
        or {(r["question_id"], r["arm"]) for r in scored}
        != {(qid, arm) for qid in expected for arm in arms}
    ):
        raise ValueError("complete unique calibration census required")

    by_case = {qid: {} for qid in expected}
    for row in scored:
        qid, arm = row["question_id"], row["arm"]
        if arm in by_case[qid] or row["status"] not in ("succeeded", "failed"):
            raise ValueError("duplicate or invalid calibration attempt")
        if row["status"] == "succeeded":
            receipt = row.get("receipt")
            if (
                type(row.get("strict_task_success")) is not bool
                or not isinstance(receipt, dict)
                or type(receipt.get("input_tokens")) is not int
                or not 0 <= receipt["input_tokens"] <= 2048
            ):
                raise ValueError("unscored or invalid calibration cost")
        by_case[qid][arm] = row

    folds = []
    choices = Counter()
    selected_wins = selected_losses = selected_ties = unobserved = 0
    heldout_success = fixed_k4_success = 0
    for heldout in expected:
        training = [by_case[qid] for qid in expected if qid != heldout]
        candidates = []
        for k in KS:
            arm = f"k{k}"
            rows = [group[arm] for group in training]
            if any(row["status"] != "succeeded" for row in rows):
                candidates = []
                break
            successes = sum(row["strict_task_success"] for row in rows)
            tokens = sum(row["receipt"]["input_tokens"] for row in rows)
            candidates.append((successes, -tokens, -k, k))
        chosen = max(candidates)[3] if candidates else None
        if chosen is not None:
            choices[chosen] += 1
        trial = by_case[heldout][f"k{chosen}"] if chosen is not None else None
        fixed = by_case[heldout]["k4"]
        if (
            trial is None
            or trial["status"] != "succeeded"
            or fixed["status"] != "succeeded"
        ):
            unobserved += 1
            classification = "unobserved"
        else:
            good = trial["strict_task_success"]
            reference = fixed["strict_task_success"]
            heldout_success += good
            fixed_k4_success += reference
            if good and not reference:
                selected_wins += 1
                classification = "selected_wins"
            elif reference and not good:
                selected_losses += 1
                classification = "selected_loses"
            else:
                selected_ties += 1
                classification = "tie"
        folds.append(
            dict(
                omitted_calibration_question=heldout,
                chosen_k_without_that_question=chosen,
                heldout_comparison=classification,
            )
        )

    n = len(expected)
    return dict(
        schema="hepta.memory-strong-rag.calibration-loo.v1",
        planned_calibration_questions=n,
        folds=folds,
        chosen_k_counts={str(k): choices[k] for k in KS},
        distinct_choices=sum(count > 0 for count in choices.values()),
        all_folds_qualified=unobserved == 0,
        stable_to_one_calibration_case_removal=(unobserved == 0 and len(choices) == 1),
        selected_wins_over_fixed_k4=selected_wins,
        selected_losses_to_fixed_k4=selected_losses,
        selected_ties_with_fixed_k4=selected_ties,
        missing_comparisons=unobserved,
        observed_heldout_selected_successes=heldout_success,
        observed_heldout_fixed_k4_successes=fixed_k4_success,
        all_planned_delta_lower=(selected_wins - selected_losses - unobserved) / n,
        all_planned_delta_upper=(selected_wins - selected_losses + unobserved) / n,
        bounds_are_confidence_intervals=False,
        folds_are_statistically_independent=False,
        calibration_sources_are_authored_development=True,
        independent_future_task_count=0,
        learned_or_parametric_gain_established=False,
        production_accepted=False,
    )
