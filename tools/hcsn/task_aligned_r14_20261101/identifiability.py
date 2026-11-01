"""Flow-only identifiability audit for the exact R13 financial cell.

With emissions held fixed, its generator and prior depend on the three named
physical parameters only through sigma and the scalar financial boundary b.
Liquidity and maturity can therefore move along an equal-boundary curve while
every causal raw-symbol law stays unchanged. Financial reward and READ fees
need not stay unchanged. An observed fee or labeled terminal reward is extra
training information; it must not silently become an inference feature.

Fixing maturity selects one representative; it does not estimate that maturity
from flow. Physical-only and joint derivative ranks are separate local results
for an explicit observation design, not global parameter-recovery theorems.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import brentq

from ..unified_cell_r12_20261031.cell import (
    Cell, DEFAULT_EMISSIONS, DEFAULT_THETA, PHYSICAL_LOWER, PHYSICAL_UPPER,
)


DESIGNS = (
    ((.15, "READ"),),
    ((.45, "READ"),),
    ((1.05, "READ"),),
    ((.15, "READ"), (.45, "READ")),
    ((.15, "READ"), (.45, "READ"), (1.05, "READ")),
    ((.15, "RESET"), (.45, "READ"), (1.05, "READ")),
)
PROFILE_MATURITIES = (1., 1.15, 1.3, 1.45, 1.65, 1.8)
PARAMETER_NAMES = ("sigma", "liquidity", "maturity")
FIXED_MATURITY = 1.3
SOURCE_PARENT = "b0802dc314251f5332bd026cb2984a0b5c75f768"


def reduced_cell(sigma, liquidity, emission_logits=None):
    """Build the fixed-maturity representative and remove emission row gauges.

    This fixes a modeling convention; it does not recover maturity from flow.
    Centering the rows leaves every emission probability unchanged.
    """
    logits = np.log(DEFAULT_EMISSIONS) if emission_logits is None else np.asarray(emission_logits, dtype=float)
    if logits.size != 12 or not np.isfinite(logits).all():
        raise ValueError("Expected twelve finite active emission logits")
    logits = logits.reshape(2, 6)
    emission_logits = logits - logits.mean(axis=1, keepdims=True)
    return Cell([sigma, liquidity, FIXED_MATURITY], emission_logits)


def observable_table(cell, designs=DESIGNS, parameterization="physical"):
    """Enumerate raw-symbol laws and forward physical Jacobians.

    Each design is a public open-loop sequence of (duration, READ/WAIT/RESET).
    RESET applies the actual R and then consumes the full duration. Only READ
    reveals an endpoint symbol. No latent phase, content label or sampled fee
    enters the table. Concatenated laws are separate normalized experiments.
    Returned Jacobian has rows for raw outcomes and columns sigma/liquidity/m.
    With parameterization="joint", the twelve emission-logit columns follow.
    """
    if parameterization not in ("physical", "joint"):
        raise ValueError("Unknown derivative parameterization")
    derivatives_by_name = cell.parameter_jacobians() if parameterization == "joint" else {
        "prior": cell.dprior, "E": cell.dE,
    }
    parameter_count = derivatives_by_name["prior"].shape[0]
    values, derivatives = [], []
    for design in designs:
        probability = cell.prior[None, :].copy()
        derivative = derivatives_by_name["prior"][None, :, :].copy()
        for duration, action in design:
            if action not in ("READ", "WAIT", "RESET"):
                raise ValueError("Observation design has an unknown action")
            if action == "RESET":
                probability = probability @ cell.R
                derivative = derivative @ cell.R
            transition, dtransition = cell.transition(duration, with_grad=True)
            if parameterization == "joint":
                dtransition = np.concatenate((dtransition, np.zeros((12, *transition.shape))))
            derivative = derivative @ transition + np.einsum(
                "ni,kij->nkj", probability, dtransition)
            probability = probability @ transition
            if action == "READ":
                derivative = (
                    derivative[:, None, :, :] * cell.E.T[None, :, None, :]
                    + probability[:, None, None, :] * derivatives_by_name["E"].transpose(2, 0, 1)[None, :]
                ).reshape(-1, parameter_count, cell.state_count)
                probability = (
                    probability[:, None, :] * cell.E.T[None, :, :]
                ).reshape(-1, cell.state_count)
        values.append(probability.sum(axis=-1))
        derivatives.append(derivative.sum(axis=-1))
    return np.concatenate(values), np.concatenate(derivatives)


def _spectrum(jacobian, scales):
    scaled = np.asarray(jacobian) * np.asarray(scales)[None, :]
    _, singular, right = np.linalg.svd(scaled, full_matrices=False)
    tolerance = float(singular[0] * 1e-8)
    return {
        "singular_values_scaled": singular.tolist(),
        "rank_relative_tolerance": 1e-8,
        "rank": int(np.count_nonzero(singular > tolerance)),
        "nonzero_condition_number": float(singular[0] / singular[singular > tolerance][-1]) if np.any(singular > tolerance) else None,
        "right_smallest_vector_scaled_coordinates": right[-1].tolist(),
    }


def equal_boundary_profile(reference, maturities=PROFILE_MATURITIES):
    """Profile an exact observable-equivalence curve, retaining infeasibility.

    This is a population-likelihood profile, not a fitted-data confidence set.
    Liquidity is solved using only the scalar boundary equality. Residuals are
    independently evaluated with complete Cell objects and raw-symbol laws.
    """
    target, _ = observable_table(reference)
    profile = []
    for maturity in maturities:
        def residual(liquidity):
            candidate = Cell([reference.theta[0], liquidity, maturity], reference.emission_logits)
            return candidate.boundary - reference.boundary

        lower, upper = float(PHYSICAL_LOWER[1]), float(PHYSICAL_UPPER[1])
        endpoints = residual(lower), residual(upper)
        if endpoints[0] * endpoints[1] > 0:
            profile.append({"maturity": float(maturity), "status": "outside_liquidity_box",
                            "boundary_residual_at_box_ends": list(endpoints)})
            continue
        liquidity = brentq(residual, lower, upper, xtol=1e-14)
        candidate = Cell([reference.theta[0], liquidity, maturity], reference.emission_logits)
        law, _ = observable_table(candidate)
        support = target > 0
        # The uncentered sum can be slightly negative from roundoff at equality.
        cross_entropy_change = float(np.sum(target[support] * np.log(target[support] / law[support])))
        profile.append({
            "status": "equivalent_flow", "theta": candidate.theta.tolist(),
            "boundary_abs_error": abs(candidate.boundary - reference.boundary),
            "generator_max_abs_error": float(np.max(np.abs(candidate.Q - reference.Q))),
            "prior_max_abs_error": float(np.max(np.abs(candidate.prior - reference.prior))),
            "raw_law_max_abs_error": float(np.max(np.abs(law - target))),
            "population_nll_change_sum_across_designs": cross_entropy_change,
            "reward_max_abs_difference": float(np.max(np.abs(candidate.reward - reference.reward))),
            "read_fee_max_abs_difference": float(np.max(np.abs(candidate.read_cost - reference.read_cost))),
        })
    return profile


def run_audit():
    """Return a deterministic, JSON-safe structural and numerical audit."""
    cell = Cell()
    law, jacobian = observable_table(cell)
    scales = PHYSICAL_UPPER - PHYSICAL_LOWER
    # Changes in liquidity and maturity affect flow only through b. This
    # tangent annihilates b exactly to first order; no SVD tuning defines it.
    null = np.array([0., cell.dboundary[2], -cell.dboundary[1]])
    null /= np.linalg.norm(null)
    flow_derivative = np.concatenate((cell.dQ.reshape(3, -1), cell.dprior,
                                      cell.dE.reshape(3, -1)), axis=1).T
    finite_difference = np.empty_like(jacobian)
    for parameter, scale in enumerate(scales):
        step = scale * 1e-5
        plus, minus = cell.theta.copy(), cell.theta.copy()
        plus[parameter] += step
        minus[parameter] -= step
        finite_difference[:, parameter] = (
            observable_table(Cell(plus))[0] - observable_table(Cell(minus))[0]
        ) / (2 * step)

    shifted_logits = cell.emission_logits + np.array([[1.25], [-2.5]])
    shifted = Cell(cell.theta, shifted_logits)
    swapped = Cell(cell.theta, cell.emission_logits[::-1])
    emission_jacobian = cell.dE_logits.reshape(12, -1).T
    emission_gauges = np.zeros((12, 2))
    emission_gauges[:6, 0] = 1.
    emission_gauges[6:, 1] = 1.
    full_spectrum = _spectrum(jacobian, scales)
    reduced_spectrum = _spectrum(jacobian[:, :2], scales[:2])
    joint_law, joint_jacobian = observable_table(cell, parameterization="joint")
    joint_difference = np.empty_like(joint_jacobian)
    joint_difference[:, :3] = finite_difference
    for parameter in range(12):
        step = 1e-5
        plus, minus = cell.emission_logits.ravel().copy(), cell.emission_logits.ravel().copy()
        plus[parameter] += step
        minus[parameter] -= step
        joint_difference[:, 3 + parameter] = (
            observable_table(Cell(cell.theta, plus))[0] - observable_table(Cell(cell.theta, minus))[0]
        ) / (2 * step)
    # Five logits per row, with the final logit anchored to zero, remove the
    # two continuous softmax gauges. Label swapping remains a discrete symmetry.
    reduced_columns = [0, 1, *range(3, 8), *range(9, 14)]
    joint_scales = np.r_[scales, np.ones(12)]
    reduced_joint_scales = np.r_[scales[:2], np.ones(10)]
    supported = law > 0
    fisher_weights = np.sqrt(len(DESIGNS) * law[supported])
    reduced_fisher = _spectrum(jacobian[supported, :2] / fisher_weights[:, None], scales[:2])
    joint_reduced = _spectrum(joint_jacobian[:, reduced_columns], reduced_joint_scales)
    profile = equal_boundary_profile(cell)
    observation_count = [7 ** sum(action == "READ" for _, action in design) for design in DESIGNS]
    split_laws = np.split(law, np.cumsum(observation_count)[:-1])
    result = {
        "schema": "hcsn-r14-flow-identifiability-v2",
        "source_parent": SOURCE_PARENT,
        "parameter_names": list(PARAMETER_NAMES), "theta": DEFAULT_THETA.tolist(),
        "designs": [[{"dt": dt, "action": action} for dt, action in d] for d in DESIGNS],
        "observations_per_design": observation_count,
        "observation_probability_sums": [float(p.sum()) for p in split_laws],
        "physical_scales": scales.tolist(), "full_physical_spectrum": full_spectrum,
        "fixed_maturity_spectrum": reduced_spectrum,
        "joint_observation_spectra": {
            "physical_plus_twelve_logits": _spectrum(joint_jacobian, joint_scales),
            "fixed_maturity_plus_ten_logit_coordinates": joint_reduced,
            "joint_and_physical_raw_law_max_abs_difference": float(np.max(np.abs(joint_law - law))),
            "forward_vs_central_joint_jacobian_max_abs_error": float(np.max(np.abs(joint_jacobian - joint_difference))),
            "reduced_columns_in_fifteen_parameter_order": reduced_columns,
            "reduced_coordinate_scales": reduced_joint_scales.tolist(),
            "scope": "Local raw-law derivative rank at the stated parameters and six observation designs; the discrete bit-label symmetry remains. This is not a global recovery or finite-data precision theorem.",
        },
        "fixed_maturity_fisher_design": {
            "weighted_jacobian_spectrum": reduced_fisher,
            "interpretation": "Equal-probability randomization over the six designs. Squared weighted singular values are per-trial Fisher eigenvalues in scaled coordinates, conditional on known emissions.",
        },
        "boundary": cell.boundary, "boundary_derivative": cell.dboundary.tolist(),
        "analytic_null_direction_physical_units": null.tolist(),
        "generator_prior_emission_null_residual_max": float(np.max(np.abs(flow_derivative @ null))),
        "raw_law_null_residual_max": float(np.max(np.abs(jacobian @ null))),
        "forward_vs_central_jacobian_max_abs_error": float(np.max(np.abs(jacobian - finite_difference))),
        "equal_boundary_profile": profile,
        "emission_gauge": {
            "softmax_shift_max_abs_error": float(np.max(np.abs(shifted.E - cell.E))),
            "two_row_shift_jacobian_residual_max": float(np.max(np.abs(emission_jacobian @ emission_gauges))),
            "bit_label_swap_raw_law_max_abs_error": float(np.max(np.abs(observable_table(swapped)[0] - law))),
            "interpretation": "Two row offsets are unidentifiable softmax gauges. Unlabeled raw symbols also admit the bit-label permutation. Labeled training outcomes can anchor the bit semantics.",
        },
        "admitted_parameterization": {
            "free_physical_parameters": ["sigma", "liquidity"], "fixed_maturity": FIXED_MATURITY,
            "meaning": "Maturity is specified by the experiment, not estimated from raw flow.",
            "emission_gauge_rule": "Use five logits per row with the last fixed to zero, or center each six-logit row. Anchor bit names by labeled training outcomes.",
        },
        "scope": "Local finite-model raw-symbol identifiability at a declared observation design and units. Conditional physical and joint derivative ranks are reported separately. Neither is a global recovery theorem or a continuum result.",
        "cost_warning": "Equal flow does not fix state reward/READ fees. Learn them from actual training outcomes or specify task prices externally; evaluator-only costs cannot enter actor history.",
    }
    result["checks"] = {
        "raw_laws_normalized": bool(all(abs(p.sum() - 1.) < 1e-12 for p in split_laws)),
        "three_parameter_flow_rank_is_two": full_spectrum["rank"] == 2,
        "fixed_maturity_local_rank_is_two": reduced_spectrum["rank"] == 2,
        "analytic_flow_null_verified": result["generator_prior_emission_null_residual_max"] < 1e-10,
        "forward_observable_derivatives_verified": result["forward_vs_central_jacobian_max_abs_error"] < 2e-7,
        "forward_joint_observable_derivatives_verified": result["joint_observation_spectra"]["forward_vs_central_joint_jacobian_max_abs_error"] < 2e-7,
        "fixed_maturity_gauge_removed_joint_rank_is_twelve": joint_reduced["rank"] == 12,
        "equivalent_flows_have_different_task_fees": any(
            item.get("raw_law_max_abs_error", 1.) < 1e-10 and item.get("read_fee_max_abs_difference", 0.) > 1e-4
            for item in profile),
    }
    root = Path(__file__).resolve().parents[3]
    result["source_sha256"] = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            Path(__file__).resolve(),
            Path(__file__).with_name("test_identifiability.py").resolve(),
            root / "tools/hcsn/unified_cell_r12_20261031/cell.py",
            root / "tools/hcsn/unified_cell_r12_20261031/PROTOCOL.json",
            root / "tools/hcsn/calibrated_operator_r11_20261031/numerics/kernel.py",
        )
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    payload = json.dumps(run_audit(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
