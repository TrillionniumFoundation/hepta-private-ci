"""Complete new row evidence and fixed TRAIN contrasts; no candidate selection."""

import hashlib
import json
from pathlib import Path

import numpy as np

from independent.learning import CONTENT_PARAMETERS
from ndu_training.cv_train_d2.budget import plan
from ndu_training.reinfer_d1.kernels import request_readout
from ndu_training.run import save_state


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def save(path, arrays):
    with Path(path).open("xb") as stream:
        np.savez(stream, **arrays)


def service_state():
    return {
        "p": np.full((3072, 12), np.nan),
        "q": np.full((3072, 12), np.nan),
        "choices": np.zeros((1, 3072, 2), dtype=np.uint8),
        "payload_sha256": np.zeros((1, 3072, 32), dtype=np.uint8),
        "output_bytes": np.zeros((1, 3072), dtype=np.uint32),
        "completed": np.zeros((1, 48), dtype=bool),
        "batches": [],
    }


def final_candidate(state, arrays, observer, base, group, key, out, ledger):
    model, storage = state["model"], state["service"]
    if not storage["completed"].all():
        raise RuntimeError("incomplete fixed service denominator")
    readout = request_readout(
        storage["p"], storage["q"], arrays["labels"], observer, ledger
    )
    names = (
        "task_utility",
        "joint_success",
        "CE_rho",
        "consistency",
        "pixel_mse",
        "negative_reward_mass",
        "negative_reward_expectation",
        "greedy_joint_success",
        "greedy_reward",
        "text_true_probability",
        "image_true_probability",
    )
    ledger.charge_kernel(
        "final_statistics",
        "whole_and_source_means",
        scalar_ops=(len(names) + 6) * (3072 - 1) + 6 * (3072 - 192),
        div_ops=len(names) + 6 + 192 * 6,
        compare_ops=192 * 3072,
    )
    means = {name: float(readout[name].mean()) for name in names}
    attr = {
        head: readout[head + "_attribute_errors"].mean(0).tolist()
        for head in ("text", "image")
    }
    sources = []
    for source in range(192):
        take = arrays["row_source_index"] == source
        sources.append(
            {
                "source_index": source,
                **{
                    name: float(readout[name][take].mean())
                    for name in (
                        "task_utility",
                        "joint_success",
                        "greedy_joint_success",
                        "negative_reward_mass",
                        "text_true_probability",
                        "image_true_probability",
                    )
                },
            }
        )
    elements = sum(model.params[name].size for name in CONTENT_PARAMETERS)
    ledger.charge_kernel(
        "final_statistics",
        "parameter_changes_and_finite_state",
        scalar_ops=3 * elements - 6,
        sqrt_ops=6,
        compare_ops=3 * elements + 2 * 2496,
    )
    delta = {
        name: float(np.linalg.norm(model.params[name] - base.params[name]))
        for name in CONTENT_PARAMETERS
    }
    finite = all(
        np.isfinite(value).all()
        for value in (
            *model.params.values(),
            *(v for m in model._moments.values() for v in m[:2]),
        )
    )
    if not finite or any(
        not np.array_equal(model.params[name], base.params[name])
        for name in ("decoder", "decoder_bias")
    ):
        raise RuntimeError("nonfinite state or changed fixed decoder")
    save(out / f"requests-{group}-{key}.npz", readout)
    save(
        out / f"service-{group}-{key}.npz",
        {
            name: storage[name]
            for name in ("choices", "payload_sha256", "output_bytes", "completed")
        },
    )
    save_state(model, out / f"final-{group}-{key}", ledger)
    return {
        "steps": state["steps"],
        "stream_sha256": state["stream"].hexdigest(),
        "prefix128_stream_sha256": state["prefix128"],
        "means": means,
        "attribute_error_rates": attr,
        "all_sources": sources,
        "parameter_delta_l2": delta,
        "finite_parameters_and_moments": finite,
        "gradient_norm_trace": state["optimizer"].trace,
        "loss_trace": state["loss_trace"],
        "service_batches": storage["batches"],
        "parameters_sha256": model.digest(),
    }


def contrasts(results, old, ledger):
    ledger.charge_kernel(
        "final_statistics", "fixed_contrasts", scalar_ops=58, compare_ops=63, div_ops=2
    )
    comparisons, prefixes = {}, []
    for kind in ("iid", "stratified"):
        comparisons[kind] = []
        for seed in (11, 23, 47):
            key = f"{kind}-{seed}"
            cells = {
                group: results[group]["candidates"][key] for group in plan()["groups"]
            }
            prefix = {cell["prefix128_stream_sha256"] for cell in cells.values()}
            if len(prefix) != 1 or None in prefix:
                raise RuntimeError(
                    "four groups lack the same 128-step minibatch prefix"
                )
            prefixes.append(
                {"candidate": key, "common_prefix_sha256": next(iter(prefix))}
            )
            u = {group: cell["means"]["task_utility"] for group, cell in cells.items()}
            greedy = {
                group: cell["means"]["greedy_joint_success"]
                for group, cell in cells.items()
            }
            strong = {}
            for estimator in ("plain", "CV"):
                for sampler in ("iid", "stratified"):
                    name = f"A-{estimator}-{sampler}"
                    strong[name] = results[f"A-{estimator}"]["candidates"][
                        f"{sampler}-{seed}"
                    ]["means"]
            for sampler in ("iid", "stratified"):
                strong[f"A-original-{sampler}"] = old["systems"]["A"]["candidates"][
                    f"{sampler}-{seed}"
                ]["train"]
            best_raw = max(cell["task_utility"] for cell in strong.values())
            best_greedy = max(cell["greedy_joint_success"] for cell in strong.values())
            comparisons[kind].append(
                {
                    "seed": seed,
                    "utility": u,
                    "greedy": greedy,
                    "N_minus_A_plain": u["N-plain"] - u["A-plain"],
                    "N_minus_A_CV": u["N-CV"] - u["A-CV"],
                    "interaction": (u["N-CV"] - u["A-CV"])
                    - (u["N-plain"] - u["A-plain"]),
                    "CV_minus_plain_N": u["N-CV"] - u["N-plain"],
                    "CV_minus_plain_A": u["A-CV"] - u["A-plain"],
                    "all_six_strong_A": {
                        name: {
                            metric: cell[metric]
                            for metric in ("task_utility", "greedy_joint_success")
                        }
                        for name, cell in strong.items()
                    },
                    "N_CV_minus_strongest_A_raw": u["N-CV"] - best_raw,
                    "N_CV_minus_strongest_A_greedy": greedy["N-CV"] - best_greedy,
                }
            )
    primary = comparisons["stratified"]
    return {
        "same_128_step_prefixes": prefixes,
        "all_seed_sampler_contrasts": comparisons,
        "primary_mean_N_CV_minus_strongest_A_raw": float(
            np.mean([x["N_CV_minus_strongest_A_raw"] for x in primary])
        ),
        "primary_mean_interaction": float(np.mean([x["interaction"] for x in primary])),
        "greedy_retained_all_seeds": all(
            x["N_CV_minus_strongest_A_greedy"] >= -0.02 for x in primary
        ),
        "TRAIN_only_no_formal_inference": True,
        "warning": "three fixed seeds and shared TRAIN; no cross-training-block or held-out claim; tail/greedy losses retained",
    }


def draw_digest(draw):
    idx, weights, full = draw
    return (
        idx.astype("<i8").tobytes()
        + (b"IID" if weights is None else weights.astype("<f8").tobytes())
        + full.tobytes()
    )


def file_manifest(out):
    return {
        str(path.relative_to(out)): {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(out.rglob("*"))
        if path.is_file()
    }
