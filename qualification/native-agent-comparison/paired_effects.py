"""Descriptive, same-task A/B/C pairing; NEVER evidence of independent efficacy.

The caller must first verify complete source-pinned observations for all arms.
Differences use Native C minus A/B: positive quality means better native,
negative resource cost means cheaper native. No task-family independence,
physical measurement or statistical significance is inferred by this module.
"""
from __future__ import annotations


QUALITY_FIELDS = ("task_success", "tool_correct", "recovery_pass")
COST_FIELDS = ("wall_ms", "peak_rss_bytes", "input_tokens", "output_tokens", "tool_calls")


def paired_effects_by_scale(tasks: list[dict], actual: dict, scales: tuple[int, ...]) -> dict:
    if not tasks:
        raise ValueError("paired effects require nonempty frozen task cohort")
    result = {}
    for scale in scales:
        per_mode = {}
        for reference in ("A", "B"):
            pairs = [
                (
                    actual[(task["task_id"], task["seed"], scale, "C")],
                    actual[(task["task_id"], task["seed"], scale, reference)],
                )
                for task in tasks
            ]
            count = len(pairs)
            quality = {}
            regressions = False
            for name in QUALITY_FIELDS:
                native_only = sum(bool(native[name]) and not bool(peer[name]) for native, peer in pairs)
                reference_only = sum(not bool(native[name]) and bool(peer[name]) for native, peer in pairs)
                quality[name] = {
                    "native_only_passes": native_only,
                    "reference_only_passes": reference_only,
                    "paired_delta_percentage_points": 100.0 * (native_only - reference_only) / count,
                }
                regressions |= reference_only > 0
            per_mode[f"C_vs_{reference}"] = {
                "cases": count,
                "quality": quality,
                "mean_resource_delta_C_minus_reference": {
                    name: sum(native[name] - peer[name] for native, peer in pairs) / count
                    for name in COST_FIELDS
                },
                "any_paired_quality_regression": regressions,
                "statistical_significance_proven": False,
                "independent_measurement_proven": False,
            }
        result[str(scale)] = per_mode
    return result
