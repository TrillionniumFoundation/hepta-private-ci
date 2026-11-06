"""Research-only, same-census source-memory candidate triage.

Consume independently recomputed *outcomes*, never generate more answers or
upgrade the sample size. A perfect organized baseline has no observable
accuracy headroom; answering differently is not an increment.
"""

from research_disposition import decide


COMPARISONS = {
    "learned_policy": {
        "hybrid": "policy_vs_hybrid",
        "organized": "policy_vs_organized",
        "initial": "policy_vs_initialization",
    },
    "knowledge": {
        "hybrid": "knowledge_vs_hybrid",
        "organized": "knowledge_vs_same_evidence",
    },
    "parameter_only": {
        "empty": "parameter_only_vs_empty",
        "organized": "parameter_only_vs_organized",
    },
}


def research_dispositions(contrasts, structure, planned):
    """Interpret all frozen controls; never certify held-out or production gain."""
    if (
        type(planned) is not int
        or not 1 <= planned <= 20000
        or type(contrasts) is not dict
        or type(structure) is not dict
        or structure.get("production_accepted") is not False
        or structure.get("independently_adjudicated_precision") is not None
    ):
        raise ValueError("complete unqualified source-effect census required")
    by_arm = structure.get("by_arm")
    if not isinstance(by_arm, dict):
        raise ValueError("missing original citation census")
    results = {}
    for candidate, names in COMPARISONS.items():
        pairs = {}
        for control, comparison in names.items():
            if comparison not in contrasts or "all" not in contrasts[comparison]:
                raise ValueError("required strongest-control contrast missing")
            pairs[control] = contrasts[comparison]["all"]
        finding = decide(candidate, pairs, planned)
        candidate_arm = "policy" if candidate == "learned_policy" else candidate
        stats = by_arm.get(candidate_arm)
        if not isinstance(stats, dict):
            raise ValueError("missing original arm citation census")
        invalid = stats.get("markers_without_delivered_labels")
        no_evidence = stats.get("markers_without_any_sources")
        if (
            type(invalid) is not int
            or type(no_evidence) is not int
            or not 0 <= no_evidence <= invalid
        ):
            raise ValueError("invalid unsupported original citations")
        organized = pairs["organized"]
        finding.update(
            strongest_control="deterministic_organized",
            strongest_control_baseline_successes=organized[
                "baseline_successes_on_complete_pairs"
            ],
            strongest_control_observed_headroom=organized[
                "observed_baseline_success_headroom"
            ],
            strongest_control_saturated=organized[
                "baseline_saturated_on_all_planned_pairs"
            ],
            unsupported_citation_occurrences=invalid,
            citations_without_any_evidence=no_evidence,
            unsupported_citations_require_separate_semantic_review=invalid > 0,
            new_pretrained_generations=0,
            independent_source_families_confirmed=None,
            statistical_superiority=False,
            use_as_selected_production_memory=False,
        )
        if candidate == "parameter_only":
            finding["research_next_step"] = (
                "new-source paraphrase and relation-binding with prequery freeze"
            )
        else:
            finding["research_next_step"] = (
                "registered independent families with non-saturated "
                "strong-reader and deterministic-organizer controls"
            )
        results[candidate] = finding
    return dict(
        schema="hepta.source-write.research-dispositions.v1",
        originating_source_effects_verified_by_caller=True,
        model_answer_changes_are_not_accuracy_gains=True,
        formal_semantic_citation_precision=None,
        fresh_prospective_confirmations=0,
        no_new_model_calls=True,
        production_accepted=False,
        candidates=results,
    )
