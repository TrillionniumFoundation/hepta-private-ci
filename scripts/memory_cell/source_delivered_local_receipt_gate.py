"""Reject inflated MemoryCell local Reader claims from sanitized original receipts.

This source-only audit never opens original model outputs or assigns model/
reviewer signatures. It checks internally consistent, source-pinned research
dispositions; it cannot certify an external runtime, semantics or production.
"""

import argparse
import json
from pathlib import Path

SCHEMA = "hepta.memory.source-delivered-original-smol-local-observation-20261016.v1"
SOURCE_SHA = "31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a"
MODEL_SHA = "5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c"
ARMS = (
    "empty",
    "hybrid",
    "entity_time",
    "organized",
    "program_support",
    "without_prerequisite",
)


def deny(condition, message):
    if not condition:
        raise ValueError(message)


def replay_published(record):
    """Read-only consistency check; success means receipt integrity, not model QA."""
    deny(isinstance(record, dict) and record.get("schema") == SCHEMA, "wrong report")
    origin = record.get("execution_provenance")
    observed = record.get("observed")
    review = record.get("source_and_program_replay")
    ablation = record.get("retrospective_refusal_ablation")
    interpretation = record.get("interpretation")
    deny(
        all(
            isinstance(x, dict)
            for x in (origin, observed, review, ablation, interpretation)
        ),
        "missing published source boundaries",
    )
    deny(
        origin.get("original_input_zip_sha256") == SOURCE_SHA
        and origin.get("original_weights_sha256") == MODEL_SHA
        and origin.get("model_runtime") == "independent-port-Torch-2.10.0+cpu-FP32"
        and origin.get("original_experiment_runtime_pytorch_2_5_1_parity_verified")
        is False
        and origin.get("inference_generated_on_github_actions") is False
        and origin.get("github_actions_job_result_qualified") is False,
        "new Reader generation relabelled as hosted canonical parity",
    )
    by_arm = observed.get("by_arm")
    deny(
        isinstance(by_arm, dict) and set(by_arm) == set(ARMS), "six-arm census changed"
    )
    totals = dict(
        calls=0, failed=0, worker=0, choices=0, supported=0, tokens=0, hypotheses=0
    )
    for arm in ARMS:
        s = by_arm[arm]
        deny(isinstance(s, dict), "arm evidence invalid")
        for name in (
            "planned",
            "model_calls",
            "failed",
            "choice_correct",
            "supported_success",
            "full_declared_support",
            "hypotheses",
            "input_tokens",
            "refusals",
            "worker_checks",
            "worker_success",
        ):
            deny(
                type(s.get(name)) is int and 0 <= s[name] <= 100000,
                "invalid finite original count: " + arm + "/" + name,
            )
        deny(
            s["planned"] == s["model_calls"] == 8
            and s["failed"] == 0
            and s["worker_checks"] == 2
            and s["supported_success"] <= s["choice_correct"]
            and s["supported_success"] <= s["full_declared_support"]
            and s["refusals"] <= 8
            and s["worker_success"] <= 2,
            "task or actual program count drift",
        )
        for key, field in (
            ("calls", "model_calls"),
            ("failed", "failed"),
            ("worker", "worker_checks"),
            ("choices", "choice_correct"),
            ("supported", "supported_success"),
            ("tokens", "input_tokens"),
            ("hypotheses", "hypotheses"),
        ):
            totals[key] += s[field]
    deny(
        totals
        == dict(
            calls=48,
            failed=0,
            worker=12,
            choices=28,
            supported=24,
            tokens=19801,
            hypotheses=98,
        ),
        "actual model/typed support/worker census changed",
    )
    deny(
        by_arm["empty"]["choice_correct"] == by_arm["empty"]["supported_success"] == 0
        and by_arm["empty"]["refusals"] == 8
        and by_arm["without_prerequisite"]["choice_correct"] == 4
        and by_arm["without_prerequisite"]["full_declared_support"] == 0
        and by_arm["without_prerequisite"]["supported_success"] == 0,
        "unjustified missing-premise success claim",
    )
    deny(
        observed.get("registered_old_exposed_questions") == 8
        and observed.get("arms") == 6
        and observed.get("original_model_requests") == 48
        and observed.get("original_model_successful_requests") == 48
        and observed.get("original_model_failures") == 0
        and observed.get("actual_neural_forwards") == 732
        and observed.get("original_constrained_program_worker_calls") == 12
        and observed.get("separate_process_original_program_worker_reexecutions") == 12
        and observed.get("independent_process_new_model_calls") == 0,
        "original real model execution or replay inflated",
    )
    deny(
        review.get("recounted_original_model_requests") == 48
        and review.get("recounted_neural_forward_operations") == 732
        and review.get("original_prompt_token_ids_reproduced") is True
        and review.get("source_only_candidate_census_verified") is True
        and review.get("explicit_typed_causal_chain_reconstructed") is True
        and review.get("original_program_worker_execution_replays") == 12
        and review.get("conditional_log_probabilities_independently_recomputed")
        is False
        and review.get("semantic_human_entailment") is False,
        "second-process mechanical replay misrepresented",
    )
    per_arm = ablation.get("by_arm")
    deny(
        isinstance(per_arm, dict)
        and set(per_arm) == set(ARMS)
        and ablation.get("uses_saved_original_logits_only") is True
        and ablation.get("new_model_forwards") == 0
        and ablation.get("safe_refusal_rule_validated") is False,
        "posthoc refusal analysis promoted",
    )
    for arm in ARMS:
        candidate = per_arm[arm]
        # Without delivered candidate values, successful refusal and an exact
        # target-answer hit are two different diagnostics. Do not credit the
        # empty arm with an answer-space win or invent a forced guess.
        if arm == "empty":
            deny(
                candidate["planned"] == 8
                and candidate["fixed_refusal_correct"] == 8
                and candidate["abstentions"] == 8
                and candidate["posthoc_forced_guess_correct"] == 0
                and candidate["correct_suppressed_by_abstention"] == 0
                and candidate["wrong_suppressed_by_abstention"] == 0
                and candidate["guess_unsupported"] == 0
                and candidate["unchanged"] == 0,
                "no-evidence abstention cannot become an answer-space win",
            )
            continue
        deny(
            candidate["planned"] == 8
            and candidate["fixed_refusal_correct"] == by_arm[arm]["choice_correct"]
            and candidate["abstentions"] == by_arm[arm]["refusals"]
            and candidate["posthoc_forced_guess_correct"]
            == candidate["fixed_refusal_correct"]
            + candidate["correct_suppressed_by_abstention"]
            and candidate["correct_suppressed_by_abstention"]
            + candidate["wrong_suppressed_by_abstention"]
            <= candidate["abstentions"],
            "posthoc refusal recomputation detached from observed model",
        )
    deny(
        per_arm["empty"]["posthoc_forced_guess_correct"] == 0
        and per_arm["hybrid"]["posthoc_forced_guess_correct"] == 5
        and all(
            per_arm[a]["posthoc_forced_guess_correct"] == 8
            for a in ("entity_time", "organized", "program_support")
        )
        and per_arm["without_prerequisite"]["guess_unsupported"] == 4
        and per_arm["without_prerequisite"]["posthoc_forced_guess_correct"] == 4,
        "posthoc guessing cannot erase missing prerequisite",
    )
    deny(
        interpretation.get(
            "same_reader_organized_vs_hybrid_descriptive_supported_success_gain"
        )
        == 4
        and interpretation.get(
            "same_reader_organized_vs_complete_entity_time_supported_success_gain"
        )
        == 0
        and interpretation.get(
            "lesioned_gold_value_visible_but_source_chain_incomplete_in_four_cases"
        )
        is True
        and interpretation.get("parametric_memory_gain_established") is False
        and interpretation.get("independent_future_source_families") == 0
        and interpretation.get("actual_autonomous_repository_repair_tasks") == 0
        and interpretation.get("full_lifecycle_cost_usd") is None
        and interpretation.get("production_accepted") is False,
        "scope-cost-production research veto changed",
    )
    return dict(
        schema="hepta.memory.source-delivered-original-local-readonly-disposition.v1",
        model_requests=48,
        independently_recounted_forwards=732,
        original_program_checks=12,
        independent_program_rechecks=12,
        new_model_calls=0,
        reader_origin="isolated local FP32 Torch2.10 unqualified numeric profile",
        on_new_unseen_families=False,
        learner_trained=False,
        human_semantic_citation_precision=None,
        production_qualified=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    deny(
        not args.receipt.is_symlink()
        and args.receipt.is_file()
        and args.receipt.stat().st_size < 32768,
        "regular bounded sanitized receipt required",
    )
    content = json.loads(args.receipt.read_bytes())
    report = replay_published(content)
    deny(
        not args.output.exists() and not args.output.is_symlink(),
        "no overwrite of prior audit",
    )
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
