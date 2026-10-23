"""Source/table-only architecture accounting. Never infer, train, sample or render."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from independent.accounting import DEFAULT_PRICES, WorkLedger
from independent.learning import step_work


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/content-joint-architecture-analysis-v1-20261023"
PRIOR = ROOT / "runs/content-control-train-r2-20261023"
PROBE = ROOT / "runs/content-reconcile-probe-v1-20261023"
D, H, K, PIXELS, BATCH = 202, 32, 12, 192, 64


def add(*parts):
    result = {}
    for part in parts:
        for key, value in part.items():
            result[key] = result.get(key, 0) + int(value)
    return result


def units(work):
    return sum(DEFAULT_PRICES[key] * value for key, value in work.items())


def single_head_parts(m, arm, n=BATCH):
    """Prospective kernel inventory, NOT a receipt for implemented training."""
    elements, arrays = D * H + H + (H + 1) * m, 4
    forward = dict(macs=n * (D * H + H * m),
                   scalar_ops=n * H + 3 * n * m - n,
                   compare_ops=n * (m - 1), exp_ops=n * m,
                   div_ops=n * m, tanh_ops=n * H)
    backward = dict(macs=n * (D * H + 2 * H * m),
                    scalar_ops=4 * n * H + (n - 1) * (H + m))
    optimizer = dict(scalar_ops=13 * elements + 4 * arrays,
                     div_ops=3 * elements + 1, sqrt_ops=elements + 1,
                     pow_ops=2 * arrays, compare_ops=2)
    checks = dict(compare_ops=n * D + 2 * n + elements
                  + (K * PIXELS + PIXELS if arm in ("A", "N") else 0))
    if m == K:
        # One marginal CE, since the two marginals are the same distribution.
        anchor = dict(scalar_ops=3 * n * m + 3 * n,
                      compare_ops=n, log_ops=n, div_ops=n * m + 1)
    else:
        # Preserve original average modality-marginal CE, not pair NLL.
        anchor = dict(scalar_ops=3 * n * m + 2 * n * K * (K - 1) + 6 * n,
                      compare_ops=2 * n, log_ops=2 * n,
                      div_ops=n * m + 2 * n * K + 1)
    utility = {}
    if arm == "A":
        utility = dict(macs=n * m, scalar_ops=4 * n * m + 3 * n,
                       div_ops=n * m + 1)
    elif arm == "N":
        utility = dict(macs=n * m, scalar_ops=5 * n * m + 4 * n,
                       div_ops=2 * n * m + n + 2, log_ops=n)
    return dict(forward=forward, backward=backward, optimizer=optimizer,
                checks=checks, anchor=anchor, utility=utility)


def service_quote(m):
    f = single_head_parts(m, "H", 1)["forward"]
    sample = dict(scalar_ops=2 * m - 1 + 2 * PIXELS,
                  compare_ops=m + 1 + 2 * PIXELS)
    # The general joint index needs explicit quotient/remainder unpacking.
    if m == K * K:
        sample["div_ops"] = 2
    ledger = WorkLedger("quote")
    ledger.decoder("quote", rows=1, pixels=PIXELS)
    return dict(forward=units(f), sample_and_quantize=units(sample),
                decoder=ledger.consumed_units,
                total=units(f) + units(sample) + ledger.consumed_units,
                actual_CPU="unmeasured; includes future full setup/return/export")


def main():
    started = time.process_time()
    OUT.mkdir(parents=True, exist_ok=False)
    paths = [ROOT / name for name in (
        "model.py", "data.py", "utility.py", "independent/data_v2.py",
        "independent/learning.py", "independent/accounting.py",
        "independent/native_adam.py", "independent/native.c",
        "independent/evaluation.py", "content_reconcile/RESULTS.md",
    )]
    paths += [PRIOR / "build.json", PRIOR / "train-result.json",
              PROBE / "evidence/audit-result.json",
              PROBE / "evidence/descriptive-decomposition.json"]
    for seed in (11, 23, 47):
        paths += [PROBE / f"R-{seed}.npz", PRIOR / f"base-{seed}.npz"]
        paths += [PRIOR / f"{family}-{seed}-0.01/model.npz"
                  for family in ("S", "H", "A")]
    paths += [Path(__file__), Path(__file__).with_name("ARCHITECTURE.md"),
              Path(__file__).with_name("TRAIN_PROTOCOL_DRAFT.md")]
    bindings = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in paths}
    semantic = {}
    for seed in (11, 23, 47):
        with np.load(PROBE / f"R-{seed}.npz", allow_pickle=False) as data:
            text, image = data["text_sem"], data["image_sem"]
            r, distances = data["reward"], data["distances"]
            assert np.array_equal(text, np.arange(K))
            assert np.array_equal(image, np.arange(K))
            off_t, off_i = np.where(~np.eye(K, dtype=bool))
            # Compare same-image TRUST_IMAGE with every original mismatch,
            # for every possible target, with the already recorded R.
            gain = r[:, off_i, off_i] - r[:, off_t, off_i]
            margin = np.partition(distances, 1, axis=1)[:, 1] - distances.min(1)
            best = r.reshape(K, K * K).argmax(1)
            semantic[str(seed)] = dict(
                text_sem=text.tolist(), image_sem=image.tolist(),
                nearest_template_margin_min=float(margin.min()),
                quantization_pairwise_margin_bound=1 / 255,
                quantization_identity_certified=bool(margin.min() > 1 / 255),
                decoded_correct_code_mse_minmax=[float(np.diag(distances).min()),
                                                float(np.diag(distances).max())],
                same_image_agreement_reward_gain_minmax=[float(gain.min()), float(gain.max())],
                checked_target_offdiagonal_comparisons=int(gain.size),
                unrestricted_best_pair_is_target_diagonal=bool(
                    np.array_equal(best, np.arange(K) * (K + 1))),
            )
    costs = {}
    for name, m in (("native12", K), ("joint144", K * K)):
        trainable = D * H + H + (H + 1) * m
        by_arm = {}
        for arm in ("S", "H", "A", "N"):
            parts = single_head_parts(m, arm)
            by_arm[arm] = dict(parts=parts, operators=add(*parts.values()),
                               quoted_units=units(add(*parts.values())))
        costs[name] = dict(head_parameters=(H + 1) * m,
                          trainable_parameters=trainable,
                          total_parameters_including_fixed_decoder=trainable + K * PIXELS + PIXELS,
                          parameter_gradient_two_moment_bytes=32 * trainable,
                          per_batch_head_probability_bytes=8 * BATCH * m,
                          training=by_arm, service=service_quote(m),
                          status="prospective inventory; no executable training or CPU measurement")
    old = {}
    for arm in ("S", "H", "A", "N"):
        work = step_work((D, K, PIXELS, H), arm, BATCH)
        assert units(work) == WorkLedger("verify").estimate_kernel(**work)
        old[arm] = dict(operators=work, units=units(work))
    build = json.loads((PRIOR / "build.json").read_text())
    combined = json.loads((PROBE / "evidence/audit-result.json").read_text())["costs"]
    costs["independent24"] = dict(head_parameters=2 * (H + 1) * K,
        trainable_parameters=D * H + H + 2 * (H + 1) * K,
        total_parameters_including_fixed_decoder=9784,
        parameter_gradient_two_moment_bytes=32 * 7288,
        per_batch_head_probability_bytes=8 * BATCH * 2 * K, training=old,
        service=dict(total=19236, status="original implemented inventory"))
    common_units = build["shared_ledger"]["consumed_units"]
    train_quota = (12_000_000_000 - common_units - 500_000_000) // 6
    budget = dict(
        status="NEW TRAIN protocol proposal only; NOT a reset of any old ledger",
        old_shared_preparation_CPU=build["common_cpu"],
        old_shared_preparation_units=common_units,
        minimum_future_shared_units=common_units,
        preparation_note="New adapter compilation, hash checks, import and allocation costs must be added",
        paired_models_per_objective_family=6,
        reserve_CPU=2.0, reserve_units=500_000_000,
        upper_bound_training_units_per_model_before_new_setup=train_quota,
        upper_bound_training_CPU_per_model_before_new_setup=(10 - build["common_cpu"] - 2) / 6,
        unit_only_update_upper_bounds={
            arm: dict(independent=train_quota // old[arm]["units"],
                      native12=train_quota // costs["native12"]["training"][arm]["quoted_units"])
            for arm in ("S", "H", "A", "N")
        },
        existing_probe_ledger_costs=combined,
        existing_H_A_ledgers_cannot_be_reset=True,
        historical_reference_models_not_free_selectable_candidates=True,
    )
    result = dict(scope="source and saved TRAIN table analysis only",
                  input_and_source_sha256=bindings, semantic_checks=semantic,
                  prices=dict(DEFAULT_PRICES), dimensions=[D, K, PIXELS, H],
                  quoted_architectures=costs, budget_proposal=budget,
                  training_runs=0, model_forward_calls=0, decoder_forward_calls=0,
                  sampling_draws=0, rendered_images=0, formal_data_opened=False,
                  descriptive_analysis_CPU_before_receipt=time.process_time() - started)
    (OUT / "analysis.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(costs={key: {
        "parameters": value["trainable_parameters"],
        "step_units": {a: v.get("quoted_units", v.get("units"))
                       for a, v in value["training"].items()},
        "service_units": value["service"]["total"]}
        for key, value in costs.items()}, semantic=semantic, budget_upper_bound=train_quota), indent=2))


if __name__ == "__main__":
    main()
