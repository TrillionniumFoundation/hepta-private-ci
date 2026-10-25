"""Paired speaker-group inference for the registered AV transport experiment."""

import numpy as np

from .temporal_transport import FEEDBACK, FIXED, risk_loss


def interval(values):
    return [float(value) for value in np.quantile(values, [.025, .975])]


def risk_by_replicate(values):
    scaled = 4 * values
    maximum = scaled.max(axis=(1, 2), keepdims=True)
    return -(maximum[:, 0, 0] + np.log(np.exp(scaled - maximum).mean(axis=(1, 2)))) / 4


def summarize(rows, speakers, fixed_comparison, replicates=4000, seed=9037007):
    policies = FIXED + (FEEDBACK,)
    lookup = {(row["speaker"], row["scenario"], row["policy"]): row for row in rows}
    expected = {(speaker, scenario, policy) for speaker in speakers for scenario in range(4) for policy in policies}
    if len(lookup) != len(rows) or set(lookup) != expected:
        raise ValueError("Every registered speaker/scenario/policy cell must be retained exactly once")
    cubes = {name: np.array([[[lookup[(speaker, scenario, policy)][name] for policy in policies]
                              for scenario in range(4)] for speaker in speakers], dtype=np.float64)
             for name in ("loss", "joint_delivery_completion")}
    rng = np.random.default_rng(seed)
    resamples = rng.integers(0, len(speakers), size=(replicates, len(speakers)))
    baseline, feedback = policies.index(fixed_comparison), policies.index(FEEDBACK)
    ndu_difference = (risk_by_replicate(cubes["loss"][resamples, :, feedback])
                      - risk_by_replicate(cubes["loss"][resamples, :, baseline]))
    coverage_difference = (cubes["joint_delivery_completion"][resamples, :, feedback]
                           - cubes["joint_delivery_completion"][resamples, :, baseline]).mean(axis=(1, 2))
    summaries = {}
    for index, policy in enumerate(policies):
        selected = [row for row in rows if row["policy"] == policy]
        costs = {}
        for name in ("service_wall_seconds", "service_cpu_seconds", "policy_wall_seconds", "policy_cpu_seconds"):
            values = [row.get(name) for row in selected if row.get(name) is not None]
            costs[name] = {"n_measured": len(values), "mean": float(np.mean(values)) if values else None,
                           "p50": float(np.quantile(values, .50)) if values else None,
                           "p95": float(np.quantile(values, .95)) if values else None}
        delivery = [value for row in selected for value in row.get("simulated_delivery_latency_seconds", [])]
        summaries[policy] = {"NDU": -risk_loss(cubes["loss"][:, :, index]),
                             "mean_loss": float(cubes["loss"][:, :, index].mean()),
                             "p95_loss": float(np.quantile(cubes["loss"][:, :, index], .95)),
                             "joint_delivery_completion": float(cubes["joint_delivery_completion"][:, :, index].mean()),
                             "video_delivery_coverage": float(np.mean([row["q_video"] for row in selected])),
                             "audio_delivery_coverage": float(np.mean([row["q_audio"] for row in selected])),
                             "valid_alignment_coverage": float(np.mean([row["valid_alignment_coverage"] for row in selected])),
                             "maximum_valid_clock_error_seconds": max((row["valid_clock_error_seconds"] for row in selected
                                                                         if row["valid_clock_error_seconds"] is not None), default=None),
                             "system_failures": sum(not row["completed_and_fidelity_passed"] for row in selected),
                             "actual_costs": costs,
                             "simulated_delivery_seconds": {"n_packet_commits": len(delivery),
                                "mean": float(np.mean(delivery)) if delivery else None,
                                "p50": float(np.quantile(delivery, .5)) if delivery else None,
                                "p95": float(np.quantile(delivery, .95)) if delivery else None,
                                "maximum": max(delivery, default=None)}}
    ndu_ci, coverage_ci = interval(ndu_difference), interval(coverage_difference)
    complete = all(row["completed_and_fidelity_passed"] for row in rows)
    return {"independent_speaker_groups": len(speakers), "repeated_scenarios_per_speaker": 4,
            "policy_episode_count": len(rows), "bootstrap_replicates": replicates, "bootstrap_seed": seed,
            "bootstrap_unit": "speaker with all paired policies and four scenarios retained",
            "fit_selected_fixed_comparison": fixed_comparison, "policy_summaries": summaries,
            "feedback_minus_fixed_NDU": summaries[FEEDBACK]["NDU"] - summaries[fixed_comparison]["NDU"],
            "feedback_minus_fixed_NDU_95CI": ndu_ci,
            "feedback_minus_fixed_joint_completion_95CI": coverage_ci,
            "complete_census_and_fidelity": complete,
            "engineering_transport_benefit_gate_passed": complete and ndu_ci[0] > 0 and coverage_ci[0] >= -.02,
            "clock_zero_is_structural_for_correctly_matched_source_pts": True,
            "independent_lip_sync_or_semantic_generation_claim": False}
