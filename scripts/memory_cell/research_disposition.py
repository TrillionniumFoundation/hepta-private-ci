"""Research triage from verified task outcomes, never production admission.

A completed experiment can reject a candidate. It cannot approve deployment or
turn repeatedly exposed development questions into independent held-out data.
The historical CLI first replays the pinned full task/source/lifecycle archive;
it does not trust a user-authored aggregate or execute a model again.
"""

import argparse
import json
import math
import os
from pathlib import Path
import re

CONTROLS = {
    "learned_policy": ("hybrid", "organized", "initial"),
    "knowledge": ("hybrid", "organized"),
    "parameter_only": ("empty", "organized"),
}
RULE = "hepta.observed-development-triage.v1"


def decide(candidate, comparisons, planned):
    """Require every control; observed ties are not independent module gains."""
    if (
        candidate not in CONTROLS
        or type(planned) is not int
        or not 1 <= planned <= 20000
    ):
        raise ValueError("registered candidate and complete task count required")
    controls = CONTROLS[candidate]
    if set(comparisons) != set(controls):
        raise ValueError("every registered comparator is required")
    missing, regression, no_increment = [], [], []
    census = {}
    for control in controls:
        pair = comparisons[control]
        values = [pair[key] for key in ("wins", "losses", "missing_pairs")]
        if any(type(v) is not int or not 0 <= v <= planned for v in values):
            raise ValueError("bounded integer paired outcomes required")
        wins, losses, absent = values
        if sum(values) > planned:
            raise ValueError("paired outcomes exceed planned census")
        bounds = pair["all_planned_effect_bounds"]
        expected = [
            (wins - losses - absent) / planned,
            (wins - losses + absent) / planned,
        ]
        denominator = pair.get("planned_pairs", planned)
        if (
            not isinstance(bounds, list)
            or len(bounds) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
            or bounds != expected
            or type(denominator) is not int
            or denominator != planned
        ):
            raise ValueError("missing-outcome bounds or denominator changed")
        if absent:
            missing.append(control)
        if losses:
            regression.append(control)
        if wins <= losses:
            no_increment.append(control)
        census[control] = dict(
            planned=planned,
            wins=wins,
            losses=losses,
            missing_pairs=absent,
            ties=planned - sum(values),
            all_planned_effect_bounds=expected,
        )
    if missing:
        disposition = "inconclusive_incomplete_execution"
    elif candidate == "parameter_only":
        # This arm diagnoses compression fidelity, not universal RAG replacement.
        disposition = "compression_boundary_only"
    elif regression:
        disposition = "reject_observed_task_regression"
    elif no_increment:
        disposition = "reject_no_increment_over_controls"
    else:
        disposition = "fresh_evaluation_required"
    return dict(
        rule=RULE,
        candidate=candidate,
        disposition=disposition,
        comparisons=census,
        incomplete_controls=missing,
        regression_controls=regression,
        no_increment_controls=no_increment,
        continue_training_on_same_census=False,
        independent_confirmation=False,
        population_superiority_established=False,
        production_accepted=False,
        modifies_serving_state=False,
    )


def inspect_history(path, *, archive_sha, generating_source, auditor_source):
    from frozen_policy_receipt import replay
    from reader_reference_receipt import archive, sha

    if not re.fullmatch(r"[0-9a-f]{40}", auditor_source):
        raise ValueError("exact auditor source required")
    files = archive(path, archive_sha)
    verified = replay(files, generating_source)
    if verified["all_attempts"] % 4:
        raise ValueError("complete four-arm historical census required")
    decision = decide(
        "learned_policy", verified["contrasts"], verified["all_attempts"] // 4
    )
    return dict(
        schema="hepta.historical-candidate-disposition.v1",
        generating_source=generating_source,
        auditor_source=auditor_source,
        original_archive_sha256=archive_sha,
        candidate_sha256=sha(files["policy.json"]),
        raw_answers_sha256=verified["raw_answers_sha256"],
        rule_registered_before_original_generation=False,
        interpretation="retrospective development triage; not a confirmatory test",
        decision=decision,
        verified_task_and_cost_receipt=verified,
        new_model_calls=0,
        new_independent_observations=0,
        production_accepted=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("output", type=Path)
    for name in ("archive-sha", "generating-source", "auditor-source"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = inspect_history(
        args.artifact,
        archive_sha=args.archive_sha,
        generating_source=args.generating_source,
        auditor_source=args.auditor_source,
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
