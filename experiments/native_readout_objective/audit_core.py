"""Independent identities, mathematical replay, and registered inference.

The inherited auditor is a separate implementation of Bellman induction,
first-passage checks, causal features, primitive rewards and Q24 readout.
It never imports the new study driver or head optimizer. The numerical grid
constructor remains a shared source-bound dependency; no second sparse-core
emulator is claimed.
"""

import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
from scipy.stats import t

from experiments.continuous_boundary_policy.audit import audit_episode as prior_episode
from experiments.continuous_boundary_policy.audit_integrity import (
    checked_file,
    strict_json,
    verify_profile as prior_profile,
)
from experiments.continuous_boundary_policy.audit_math import (
    close,
    expected_features,
    expected_specs,
    reference,
    require,
    streams,
)
from experiments.continuous_boundary_policy.audit_stats import (
    COUNTERS,
    inspect_native_cost,
    summarize,
    verify_context_counters,
)

SEEDS = [
    3301,
    3307,
    3313,
    3319,
    3323,
    3329,
    3331,
    3343,
    3347,
    3359,
    3361,
    3371,
    3373,
    3389,
    3391,
    3407,
]
LEARNED = ("ridge_reference", "iterative_q_mse", "policy_regret")
ARMS = LEARNED + ("finite_grid_dp",)
Q = 1 << 24


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def read(root, path):
    return strict_json((Path(root) / path).read_bytes())


def source_commit(repository, commit, relative, expected, remote_ref=None):
    require(
        isinstance(commit, str)
        and len(commit) == 40
        and all(c in "0123456789abcdef" for c in commit),
        "Invalid published commit",
    )
    raw = subprocess.check_output(
        ["git", "show", f"{commit}:{relative}"], cwd=repository
    )
    require(raw == expected, "Published artifact differs from exact frozen bytes")
    if remote_ref is not None:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, remote_ref],
            cwd=repository,
            check=True,
            capture_output=True,
        )


def verify_protocol(protocol):
    require(protocol["planned_seeds"] == SEEDS, "Independent seed roster changed")
    require(
        [r["name"] for r in protocol["arms"]] == list(LEARNED)
        and protocol["controls"] == ["finite_grid_dp"],
        "Arm roster changed",
    )
    primary = protocol["primary_pair"]
    require(
        primary["treatment"] == "policy_regret"
        and primary["control"] == "iterative_q_mse"
        and primary["minimum_mean_net_utility"] == 0.005
        and primary["confidence"] == 0.95
        and primary["family_size"] == 1,
        "Primary estimand or acceptance gate changed",
    )
    native = protocol["fixed_native"]
    require(
        [
            native[k]
            for k in ("width", "top_k", "frozen_encoder_scalars", "readout_scalars")
        ]
        == [20, 4, 420, 42],
        "Native parameter budget changed",
    )
    train = protocol["matched_iterative_training"]
    expected = {
        "beta1": 0.9,
        "beta2": 0.999,
        "epsilon": 1e-8,
        "updates": 120,
        "learning_rate_candidates": [0.005, 0.02, 0.05],
        "gradient_norm_bound": 5,
        "coefficient_abs_bound": 7.5,
        "regularization": 1e-4,
    }
    require(
        all(train[k] == value for k, value in expected.items()),
        "Matched training budget changed",
    )
    plan = protocol["data_plan"]
    counts = {
        "train_contexts_per_seed": 12,
        "train_paths_per_context": 8,
        "development_contexts_per_seed": 8,
        "development_paths_per_context": 8,
        "confirmation_contexts_per_split_per_seed": 8,
        "confirmation_paths_per_context": 16,
        "grid_states": 64,
        "grid_upper": 4.8,
        "planned_confirmation_episodes_per_arm": 4096,
        "planned_confirmation_episodes_including_dp": 16384,
    }
    require(
        all(plan[k] == value for k, value in counts.items())
        and plan["confirmation_splits"] == ["test_id", "test_ood"]
        and plan["split_weights"] == [0.5, 0.5],
        "Data/weighting budget changed",
    )
    require(
        protocol["costs"]["numeric_bytes_per_decision"] == 160
        and protocol["costs"]["price_per_numeric_byte"] == 1e-6
        and protocol["costs"]["energy_measurement"] is None,
        "Cost contract changed",
    )
    panel = protocol["diagnostics"]["same_state_panel_contract"]
    require(
        [
            panel[k]
            for k in (
                "contexts_per_seed",
                "paths_per_context",
                "windows_per_path",
                "domain",
            )
        ]
        == [4, 8, 12, "ID"],
        "Common-state diagnostic data budget changed",
    )


def verify_checkpoint(root, checkpoint, seed, arm):
    require(
        checkpoint["seed"] == seed and checkpoint["arm"] == arm,
        "Checkpoint identity mismatch",
    )
    if arm == "finite_grid_dp":
        require(
            checkpoint
            == {
                "schema": "hepta.native-readout-objective.control.v1",
                "seed": seed,
                "arm": arm,
            },
            "Unexpected DP control parameters",
        )
        return None
    require(
        arm in LEARNED
        and type(checkpoint["candidate_index"]) is int
        and checkpoint["candidate_index"] in (0, 1, 2),
        "Unknown head/candidate",
    )
    index = checkpoint["candidate_index"]
    require(
        checkpoint["schema"] == "hepta.native-readout-objective.checkpoint.v1"
        and checkpoint["kind"] == "native"
        and checkpoint["model_parameter_count"] == 42
        and checkpoint["frozen_encoder_coefficients"] == 420
        and checkpoint["boundary_weights"] is None
        and "model" not in checkpoint
        and checkpoint["candidate"]
        == {
            "learning_rate": [0.005, 0.02, 0.05][index],
            "native_ridge": [0.001, 0.01, 0.1][index],
            "fixed_boundary": 0.65,
        },
        "Head/candidate/common-boundary parameter budget changed",
    )
    coefficients = np.asarray(checkpoint["head_coefficients"], dtype=float)
    require(
        coefficients.shape == (21, 2)
        and np.isfinite(coefficients).all()
        and np.max(np.abs(coefficients)) <= 7.5 + 1e-12,
        "Head shape/domain changed",
    )
    profile = strict_json(
        checked_file(
            root, checkpoint["profile_path"], checkpoint["profile_sha256"]
        ).read_bytes()
    )
    prior_profile(profile, seed)
    expected = np.rint(coefficients * Q).astype(np.int64)
    require(
        profile["head_weights_q24"] == expected[:-1].T.tolist() + [[0] * 20]
        and profile["head_bias_q24"] == expected[-1].tolist() + [0],
        "Float checkpoint does not bind the native head",
    )
    return profile


def episode(record, checkpoint, ref, profile, expected_initial, expected_slots):
    require(
        record.get("schema") == "hepta.native-readout-objective.episode.v1"
        and record["arm"] in ARMS,
        "New episode identity mismatch",
    )
    arm = record["arm"]
    mapped = "native_sparse" if arm in LEARNED else "dp"
    copy = dict(
        record, arm=mapped, schema="hepta.continuous-boundary-policy.episode.v1"
    )
    ckpt = None if arm == "finite_grid_dp" else dict(checkpoint, arm=mapped)
    return prior_episode(
        copy,
        ckpt,
        ref,
        "",
        profile=profile,
        expected_initial=expected_initial,
        expected_slots=expected_slots,
    )


def paired_statistics(deltas, failures=0):
    values = np.asarray(deltas, dtype=float)
    require(
        values.shape == (16,) and np.isfinite(values).all(),
        "Primary inference requires exactly sixteen paired seeds",
    )
    require(type(failures) is int and failures >= 0, "Invalid stability failure count")
    mean = float(values.mean())
    sem = float(values.std(ddof=1) / np.sqrt(16))
    radius = float(t.ppf(0.975, 15)) * sem
    bounds = [mean - radius, mean + radius]
    return {
        "treatment": "policy_regret",
        "control": "iterative_q_mse",
        "seed_deltas": values.tolist(),
        "n_independent_seeds": 16,
        "mean_delta": mean,
        "standard_error": sem,
        "confidence": 0.95,
        "interval": bounds,
        "df": 15,
        "family_size": 1,
        "minimum_effect": 0.005,
        "stability_failures": failures,
        "benefit_gate_passed": bool(bounds[0] > 0.005 and failures == 0),
    }
