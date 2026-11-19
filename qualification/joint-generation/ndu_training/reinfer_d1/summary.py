"""Descriptive all-source readout; never selects or drops a source."""

import numpy as np


def summarize(readouts, states, data, groups):
    ids = sorted(set(data["source_ids"]))
    lookup = {value: i for i, value in enumerate(ids)}
    source = np.asarray([lookup[s] for s in data["source_ids"]])
    result = {}
    for kind in ("iid", "stratified"):
        for seed in (11, 23, 47):
            ak, nk = f"A-{kind}-{seed}", f"N-{kind}-{seed}"
            a, n = readouts[ak], readouts[nk]
            ac, nc = a["greedy_joint_success"], n["greedy_joint_success"]
            became_wrong = ac & ~nc
            rescued = ~ac & nc
            state_a = (a["greedy_text"] == data["labels"]).astype(int) + 2 * (
                a["greedy_image"] == data["labels"]
            )
            state_n = (n["greedy_text"] == data["labels"]).astype(int) + 2 * (
                n["greedy_image"] == data["labels"]
            )
            transition = np.bincount(4 * state_a + state_n, minlength=16).reshape(4, 4)
            all_sources = []
            for i in range(192):
                take = source == i
                all_sources.append(
                    {
                        "source_index": i,
                        "rows": int(take.sum()),
                        "delta_utility": float(
                            (n["task_utility"] - a["task_utility"])[take].mean()
                        ),
                        "greedy_became_wrong": int(became_wrong[take].sum()),
                        "greedy_rescued": int(rescued[take].sum()),
                        "delta_text_true_probability": float(
                            (n["text_true_probability"] - a["text_true_probability"])[
                                take
                            ].mean()
                        ),
                        "delta_image_true_probability": float(
                            (n["image_true_probability"] - a["image_true_probability"])[
                                take
                            ].mean()
                        ),
                    }
                )
            timing = []
            for wave in range(4):
                aa = [b for b in states[ak]["batches"] if b["wave"] == wave]
                nn = [b for b in states[nk]["batches"] if b["wave"] == wave]
                assert len(aa) == len(nn) == 48
                equal = [
                    ci
                    for ci, rows in enumerate(groups)
                    if np.array_equal(
                        states[ak]["choices"][wave, rows],
                        states[nk]["choices"][wave, rows],
                    )
                ]
                timing.append(
                    {
                        "wave": wave,
                        "all_48_cohort_delta_cpu_ns_per_request": float(
                            np.mean(
                                [
                                    nrow["cpu_ns"] - arow["cpu_ns"]
                                    for arow, nrow in zip(aa, nn)
                                ]
                            )
                            / 64
                        ),
                        "delta_output_cpu_ns_per_request": float(
                            np.mean(
                                [
                                    nrow["output_and_ledger_cpu_ns"]
                                    - arow["output_and_ledger_cpu_ns"]
                                    for arow, nrow in zip(aa, nn)
                                ]
                            )
                            / 64
                        ),
                        "identical_output_cohorts_count": len(equal),
                        "identical_output_cohort_delta_cpu_ns_per_request": None
                        if not equal
                        else float(
                            np.mean([nn[i]["cpu_ns"] - aa[i]["cpu_ns"] for i in equal])
                            / 64
                        ),
                    }
                )
            result[f"{kind}-{seed}"] = {
                "all_sources": all_sources,
                "head_transition_counts": transition.tolist(),
                "greedy_became_wrong_rows": np.flatnonzero(became_wrong).tolist(),
                "greedy_rescued_rows": np.flatnonzero(rescued).tolist(),
                "all_row_mean_deltas": {
                    key: float((n[key] - a[key]).mean())
                    for key in (
                        "task_utility",
                        "joint_success",
                        "negative_reward_mass",
                        "text_true_probability",
                        "image_true_probability",
                    )
                },
                "timing_waves": timing,
                "warning": "fixed saved models; matching-output cohorts are descriptive only, primary timing uses all cohorts",
            }
    return result
