"""Before-gold source-selection identity audit for a genuinely trained tiny Head.

Compares ONLY which original source IDs the trained and strong frozen arms would
show to an identical frozen Reader. This does not execute or score a Reader.
A copied source choice is not evidence that SGD improved an answer.
"""

import argparse
import json
from pathlib import Path

from source_head_sgd_original import (
    ARMS,
    FEATURES,
    PROFILE,
    SOURCE_SHA,
    STEPS,
    canonical,
    from_file,
    h,
)

SCHEMA = "hepta.memory-cell.actual-sgd-reader-input-identity.v1"


def compare(public, weights, predictions, *, public_sha, weights_sha, predictions_sha):
    """Fail closed unless all 8×4 sealed source selections are comparable."""
    if (
        public.get("profile") != PROFILE
        or public.get("source_zip_sha256") != SOURCE_SHA
        or public.get("target_labels_present") is not False
        or public.get("calibration_sources_present") is not False
        or len(public.get("cases", [])) != 8
        or len(set(public.get("heldout_scopes", []))) != 8
        or {row["scope"] for row in public["cases"]}
        != set(public["heldout_scopes"])
        or weights.get("profile") != PROFILE
        or weights.get("frozen_before_test") is not True
        or weights.get("tested_questions_exposed") is not False
        or weights.get("heldout_task_metric") is not None
        or weights.get("actual_model_generations") != 0
        or weights.get("production_accepted") is not False
        or weights.get("feature_keys") != list(FEATURES)
        or set(weights.get("training", {})) != {"teacher_sgd", "shuffled_sgd"}
        or any(
            item.get("gradient_updates") != STEPS
            or item.get("parameter_count") != len(FEATURES)
            or type(item.get("actual_update_squared_l2")) not in (int, float)
            or not item["actual_update_squared_l2"] > 0
            for item in weights["training"].values()
        )
        or predictions.get("profile") != PROFILE
        or predictions.get("public_test_data_sha256") != public_sha
        or predictions.get("policy_sha256") != weights_sha
        or predictions.get("heldout_label_bytes_opened") is not False
        or predictions.get("original_model_calls") != 0
        or predictions.get("no_future_window_independence") is not True
        or predictions.get("production_accepted") is not False
        or len(predictions.get("predictions", [])) != 8 * len(ARMS)
    ):
        raise ValueError("unqualified frozen-before-gold training/selection provenance")
    cases = {row["scope"]: row for row in public["cases"]}
    if len(cases) != 8:
        raise ValueError("duplicate original heldout source scope")
    # A source ID is not a delivered Reader input without its exact frozen
    # original text and observed-at coordinate. Keep this target-label-blind.
    docs = {}
    for scope, case in cases.items():
        candidates = case.get("candidate_ids")
        sources = case.get("docs")
        if (
            not isinstance(candidates, list)
            or not isinstance(sources, list)
            or len(candidates) != len(sources)
            or not 1 <= len(candidates) <= 32
            or len(set(candidates)) != len(candidates)
        ):
            raise ValueError("incomplete exact original frozen source bytes")
        grouped = {}
        for event in sources:
            if (
                not isinstance(event, dict)
                or not isinstance(event.get("identity"), str)
                or event["identity"] not in candidates
                or event["identity"] in grouped
                or event.get("scope") != scope
                or not isinstance(event.get("content"), str)
                or not event["content"]
                or not isinstance(event.get("observed_at"), str)
                or not event["observed_at"]
            ):
                raise ValueError("unknown, duplicate or changed original source bytes")
            def unique_event_fields(pairs):
                value = {}
                for key, field in pairs:
                    if key in value:
                        raise ValueError("duplicate original source event JSON field")
                    value[key] = field
                return value

            def reject_nonfinite(value):
                raise ValueError("nonfinite original source event JSON: " + value)

            try:
                original = json.loads(
                    event["content"],
                    object_pairs_hook=unique_event_fields,
                    parse_constant=reject_nonfinite,
                )
            except (TypeError, ValueError) as error:
                raise ValueError("invalid immutable source event content") from error
            if not isinstance(original, dict) or original.get("id") != event["identity"]:
                raise ValueError("event body identity differs from chosen source ID")
            grouped[event["identity"]] = event
        if set(grouped) != set(candidates):
            raise ValueError("missing original frozen candidate source content")
        docs[scope] = grouped
    matched = {}
    for row in predictions["predictions"]:
        key = (row.get("scope"), row.get("arm"))
        case = cases.get(key[0])
        arm = key[1]
        if case is None or arm not in ARMS or key in matched:
            raise ValueError("missing, unknown or repeated heldout prediction")
        candidates = case["candidate_ids"]
        selected = row.get("selected")
        if (
            row.get("kind") != case["kind"]
            or row.get("evidence_candidate_pool_sha256") != h(canonical(candidates))
            or not isinstance(selected, list)
            or len(selected) != len(case["path"])
            or len(set(selected)) != len(selected)
            or not set(selected).issubset(candidates)
            or len(set(candidates)) != len(candidates)
            or row.get("trainable_parameters")
            != (len(FEATURES) if "sgd" in arm else 0)
            or row.get("actual_reader_model_calls") != 0
            or row.get("independent_semantic_review") is not False
            or (arm == "frozen_organized" and selected != case["organized"])
        ):
            raise ValueError("original Reader evidence choice/source pool drift")
        matched[key] = tuple(selected)
    if set(matched) != {(scope, arm) for scope in cases for arm in ARMS}:
        raise ValueError("incomplete four-arm heldout prediction census")
    comparisons = []
    for scope in sorted(cases):
        learned = matched[scope, "teacher_sgd"]
        strong = matched[scope, "frozen_organized"]
        def delivered_bytes(selected):
            delivered = [
                dict(
                    original_id=identity,
                    observed_at=docs[scope][identity]["observed_at"],
                    excerpt=docs[scope][identity]["content"],
                )
                for identity in selected
            ]
            return h(canonical(delivered))

        teacher_digest = delivered_bytes(learned)
        frozen_digest = delivered_bytes(strong)
        comparisons.append(
            dict(
                scope=scope,
                kind=cases[scope]["kind"],
                teacher_selected_ids=list(learned),
                strong_frozen_selected_ids=list(strong),
                exact_ordered_source_choice_same=learned == strong,
                teacher_original_evidence_bytes_sha256=teacher_digest,
                strong_frozen_evidence_bytes_sha256=frozen_digest,
                exact_original_delivery_bytes_same=teacher_digest == frozen_digest,
                source_ids_belong_to_frozen_candidates=True,
            )
        )
    same = sum(item["exact_ordered_source_choice_same"] for item in comparisons)
    different = len(comparisons) - same
    return dict(
        schema=SCHEMA,
        original_public_source_zip_sha256=SOURCE_SHA,
        before_gold_public_sha256=public_sha,
        frozen_weights_sha256=weights_sha,
        before_gold_predictions_sha256=predictions_sha,
        original_development_task_count=len(comparisons),
        matched_choice_tasks=same,
        distinct_choice_tasks=different,
        matching_original_evidence_byte_tasks=sum(
            row["exact_original_delivery_bytes_same"] for row in comparisons
        ),
        exact_frozen_source_bytes_present=True,
        same_original_candidate_pool_and_source_order=True,
        identical_reader_prompt_conditional_on_same_template=True,
        reader_capacity_effect_measured=False,
        model_answers_generated_in_audit=0,
        exact_response_gain_over_strong_frozen_organizer_proven=False,
        learned_head_selection_gap_over_strong_organizer_observed=different > 0,
        independent_sufficient_evidence_review=False,
        prospective_source_family_count=0,
        production_accepted=False,
        per_scope=comparisons,
    )


def audit(public_file, weights_file, predictions_file, *, public_sha, weights_sha, predictions_sha):
    return compare(
        from_file(public_file, public_sha),
        from_file(weights_file, weights_sha),
        from_file(predictions_file, predictions_sha),
        public_sha=public_sha,
        weights_sha=weights_sha,
        predictions_sha=predictions_sha,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("public", type=Path)
    parser.add_argument("weights", type=Path)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("report", type=Path)
    for name in ("public-sha", "weights-sha", "predictions-sha"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = audit(
        args.public,
        args.weights,
        args.predictions,
        public_sha=args.public_sha,
        weights_sha=args.weights_sha,
        predictions_sha=args.predictions_sha,
    )
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(result, output, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")
    print(
        json.dumps(
            dict(
                same=result["matched_choice_tasks"],
                different=result["distinct_choice_tasks"],
                new_reader_calls=0,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
