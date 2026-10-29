"""Independent protocol, source, dataset, selection and checkpoint bindings."""

import hashlib
import json
from pathlib import Path

import numpy as np

from .audit_cell import OBJECTIVE, Q, canonical, hash_text, validate_cell
from .audit_math import (
    boundary_vector,
    close,
    expected_specs,
    reference,
    require,
    rng,
    streams,
)

SEEDS = [2203, 2207, 2213, 2221, 2237, 2239, 2243, 2251]
LEARNED = [
    "fixed_margin",
    "learned_margin",
    "value_margin",
    "value_call",
    "dual_flow",
    "generic_gru",
    "dual_event",
    "elman_mlp",
    "native_sparse",
]
CONTROLS = ["dp", "always_keep", "always_repair", "always_stop"]
ARMS = LEARNED + CONTROLS
PAIRS = [
    {"name": "boundary", "treatment": "value_margin", "control": "learned_margin"},
    {"name": "dual_channels", "treatment": "dual_flow", "control": "value_call"},
    {"name": "signed_structure", "treatment": "dual_flow", "control": "generic_gru"},
    {"name": "flow", "treatment": "dual_flow", "control": "dual_event"},
]
CANDIDATES = [
    {"learning_rate": 0.005, "fixed_boundary": 0.25, "native_ridge": 0.001},
    {"learning_rate": 0.02, "fixed_boundary": 0.65, "native_ridge": 0.01},
    {"learning_rate": 0.05, "fixed_boundary": 1.05, "native_ridge": 0.1},
]
FEATURES = [
    "x_scaled",
    "remaining_windows_scaled",
    "mu_scaled",
    "sigma_scaled",
    "maintenance_cost",
    "failure_cost_scaled",
    "production_scaled",
    "discount_scaled",
    "maintenance_reset_scaled",
    "failure_reset_scaled",
    "window_dt",
    "margin",
    "call",
    "put",
    "current_wait_risk",
    "previous_action_flow",
    "previous_failed",
    "previous_repair",
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "Duplicate JSON object key")
            out[key] = value
        return out

    def invalid(value):
        raise ValueError(f"Nonfinite JSON token: {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def contained(root, relative):
    require(
        isinstance(relative, str)
        and relative
        and not Path(relative).is_absolute()
        and ".." not in Path(relative).parts,
        "Unsafe artifact path",
    )
    target = (root / relative).resolve()
    require(
        target.is_relative_to(root.resolve()) and target.is_file(),
        "Missing or escaped artifact",
    )
    return target


def checked_file(root, relative, identity):
    hash_text(identity, "file")
    path = contained(root, relative)
    require(sha(path.read_bytes()) == identity, f"Artifact digest mismatch: {relative}")
    return path


def read_json(root, relative):
    return strict_json(contained(root, relative).read_bytes())


def verify_protocol(protocol):
    exact = {
        "schema": "hepta.continuous-boundary-policy.protocol.v1",
        "prior_commit": "7bec42aa4f79432f4a724d5295c67f9d69ee5a8d",
        "seeds": SEEDS,
        "arms": ARMS,
        "primary_pairs": PAIRS,
        "train_contexts": 12,
        "train_paths": 8,
        "development_contexts": 8,
        "development_paths": 8,
        "confirmation_contexts_per_split": 8,
        "confirmation_paths": 16,
        "splits": ["test_id", "test_ood"],
        "split_weights": [0.5, 0.5],
        "grid_states": 64,
        "grid_upper": 4.8,
        "features": FEATURES,
        "input_width": 18,
        "persistent_continuous_state": 6,
        "continuous_trainable_scalars": 464,
        "direct_boundary_extra_scalars": 20,
        "epochs": 120,
        "adam_gradient_clip": 5.0,
        "parameter_abs_bound": 8.0,
        "candidates": CANDIDATES,
        "familywise_alpha": 0.05,
        "minimum_effect": 0.005,
        "message_price_per_byte": 1e-6,
        "cpu_price": None,
        "energy_measurement": None,
        "child_cpu_clock_tolerance_seconds": 5e-6,
    }
    require(
        all(protocol.get(key) == value for key, value in exact.items()),
        "Protocol changed a frozen design, sample, information, budget or acceptance gate",
    )


def verify_profile(profile, seed):
    require(
        profile["schema"] == "hepta.continuous-boundary.native-profile.v1"
        and profile["arm_id"] == "native_sparse"
        and profile["stage"] == "act"
        and profile["objective_digest"] == OBJECTIVE,
        "Sparse profile scope mismatch",
    )
    require(
        profile["feature_names"] == FEATURES[:15] + FEATURES[16:]
        and all(
            profile[name] is True for name in ("use_margin", "use_risk", "use_flow")
        ),
        "Sparse feature access changed",
    )
    expected_kernel = {
        "width": 20,
        "top_k": 4,
        "temporal_decay_q24": 3 * Q // 4,
        "activity_decay_q24": 3 * Q // 4,
        "target_activity_q24": Q // 5,
        "threshold_rate_q24": Q // 64,
        "threshold_min_q24": 0,
        "threshold_max_q24": Q // 2,
        "eligibility_decay_q24": Q // 2,
    }
    require(
        profile["kernel"] == expected_kernel
        and profile["risk_ceiling_q24"] == Q
        and profile["maximum_ticks"] == 512
        and profile["tick_micros"] == 10000,
        "Original sparse execution settings changed",
    )
    generator, _ = rng(seed, "common-frozen-encoder")
    matrix = generator.normal(0, 0.16, (20, 20))
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1)
    bias = generator.uniform(-0.1, 0.15, 20)
    require(
        profile["encoder_weights_q24"] == np.rint(matrix * Q).astype(int).tolist()
        and profile["encoder_bias_q24"] == np.rint(bias * Q).astype(int).tolist(),
        "Frozen encoder identity mismatch",
    )
    head, offsets = profile["head_weights_q24"], profile["head_bias_q24"]
    require(
        len(head) == 3 and all(len(row) == 20 for row in head) and len(offsets) == 3,
        "Sparse head shape mismatch",
    )
    require(
        all(
            isinstance(v, int) and not isinstance(v, bool) and abs(v) <= 8 * Q
            for row in head + [offsets]
            for v in row
        ),
        "Sparse head coefficient invalid",
    )
    require(head[2] == [0] * 20 and offsets[2] == 0, "Sparse stop head changed")


def verify_checkpoint(checkpoint, seed, arm):
    require(
        checkpoint.get("seed") == seed and checkpoint.get("arm") == arm,
        "Checkpoint identity mismatch",
    )
    if arm in CONTROLS:
        require(
            checkpoint["schema"] == "hepta.continuous-boundary-policy.control.v1",
            "Control schema mismatch",
        )
        return None
    require(
        checkpoint["schema"] == "hepta.continuous-boundary-policy.checkpoint.v1",
        "Unknown policy checkpoint",
    )
    index = checkpoint["candidate_index"]
    require(
        type(index) is int
        and 0 <= index < 3
        and checkpoint["candidate"] == CANDIDATES[index],
        "Undeclared candidate",
    )
    if arm == "learned_margin":
        weights = np.asarray(checkpoint["boundary_weights"], dtype=float)
        require(
            weights.shape == (20,)
            and np.isfinite(weights).all()
            and checkpoint["boundary_extra_scalars"] == 20,
            "Invalid additional learned boundary budget",
        )
    else:
        require(
            checkpoint["boundary_weights"] is None
            and checkpoint["boundary_extra_scalars"] == 0,
            "Unexpected hidden boundary parameters",
        )
    if arm == "native_sparse":
        require(
            checkpoint["kind"] == "native"
            and checkpoint["model_parameter_count"] == 42
            and checkpoint["frozen_encoder_coefficients"] == 420
            and "model" not in checkpoint,
            "Unmatched native reference budget mislabeled",
        )
        return None
    kind = "gru" if arm == "generic_gru" else "elman" if arm == "elman_mlp" else "dual"
    require(
        checkpoint["kind"] == kind and checkpoint["model_parameter_count"] == 464,
        "Trainable policy budget mismatch",
    )
    return validate_cell(checkpoint["model"], kind)


def verify_contexts(root):
    references = {}
    for seed in SEEDS:
        for phase, count in (
            ("training", 12),
            ("development", 8),
            ("test_id", 8),
            ("test_ood", 8),
        ):
            saved = read_json(root, f"contexts/{seed}/{phase}.json")
            require(
                saved["seed"] == seed
                and saved["phase"] == phase
                and len(saved["contexts"]) == count,
                "Task context schedule mismatch",
            )
            for index, (row, expected) in enumerate(
                zip(saved["contexts"], expected_specs(seed, phase, count))
            ):
                require(
                    row["id"] == f"{seed}.{phase}.context{index}"
                    and row["index"] == index
                    and row["spec"] == expected,
                    "Task parameters disagree with frozen phase stream",
                )
                ref = reference(expected)
                require(
                    sha(ref["q"].tobytes()) == row["dp_sha256"],
                    "Independent finite Bellman teacher digest mismatch",
                )
                references[seed, phase, index] = ref
                for name in ("model_build_cost", "planning_cost"):
                    require(
                        all(
                            np.isfinite(row[name][key]) and row[name][key] >= 0
                            for key in ("wall_seconds", "cpu_seconds")
                        ),
                        "Invalid shared solver clock",
                    )
    return references


def verify_training_dataset(root, seed, references):
    metadata = read_json(root, f"datasets/{seed}/training.json")
    path = checked_file(root, metadata["path"], metadata["sha256"])
    require(
        metadata["phase"] == "training"
        and metadata["seed"] == seed
        and metadata["contexts"] == expected_specs(seed, "training", 12),
        "Training data phase mismatch",
    )
    design, targets = [], []
    with np.load(path, allow_pickle=False) as data:
        for index in range(12):
            ref = references[seed, "training", index]
            model = ref["model"]
            initial, slots, _ = streams(seed, "training", index, 8, ref)
            prefix = f"context_{index}_"
            states, rem = data[prefix + "states"], data[prefix + "remaining"]
            require(
                states.shape == (12, 8)
                and rem.tolist() == list(range(12, 0, -1))
                and np.array_equal(states[0], initial),
                "Training state/deadline roster mismatch",
            )
            require(
                np.array_equal(data[prefix + "uniforms"], slots)
                and np.array_equal(data[prefix + "actions"], slots[:, :, 0] < 0.2),
                "Training exploration used different innovations",
            )
            require(
                np.array_equal(states[1:], data[prefix + "next_states"][:-1]),
                "Training physical chain broken",
            )
            for elapsed in range(12):
                require(
                    np.all((states[elapsed] >= 0) & (states[elapsed] < 64)),
                    "Invalid training state",
                )
                expected_q = ref["q"][11 - elapsed, states[elapsed], :2] / 8
                close(
                    data[prefix + "target_q"][elapsed],
                    expected_q,
                    "training DP labels",
                    atol=2e-12,
                )
            for remaining, boundary in enumerate(ref["boundaries"], 1):
                design.append(boundary_vector(vars(model.spec), remaining))
                targets.append(boundary)
    design, targets = np.asarray(design), np.asarray(targets)
    regularizer = 0.001 * np.eye(20)
    regularizer[0, 0] = 0
    weights = np.linalg.lstsq(
        design.T @ design + regularizer, design.T @ targets, rcond=None
    )[0]
    saved = read_json(root, f"datasets/{seed}/BOUNDARY.json")
    close(saved["weights"], weights, "training-only boundary regression", atol=2e-9)
    require(
        saved["training_tasks"] == 12
        and saved["training_rows"] == 144
        and saved["skipped_non_threshold_rows"] == 0,
        "Boundary training scope changed",
    )
    return saved["weights"]


def verify_study_bindings(root, repository):
    protocol = read_json(root, "PROTOCOL.json")
    verify_protocol(protocol)
    manifest, environment = (
        read_json(root, "MANIFEST.json"),
        read_json(root, "ENVIRONMENT.json"),
    )
    selection, source = (
        read_json(root, "SELECTION_SEAL.json"),
        read_json(root, "SOURCE_SEAL.json"),
    )
    require(
        manifest["schema"] == "hepta.continuous-boundary-policy.manifest.v1"
        and selection["schema"] == "hepta.continuous-boundary-policy.selection.v1"
        and source["schema"] == "hepta.continuous-boundary-policy.source-seal.v1",
        "Unknown study binding schema",
    )
    for filename, key in (
        ("PROTOCOL.json", "protocol_sha256"),
        ("SOURCE_SEAL.json", "source_seal_sha256"),
    ):
        identity = sha((root / filename).read_bytes())
        require(
            manifest[key] == selection[key] == environment[key] == identity,
            "Phase identity changed",
        )
    require(
        manifest["selection_seal_sha256"]
        == sha((root / "SELECTION_SEAL.json").read_bytes()),
        "Selection seal changed",
    )
    for relative, identity in source["source_files"].items():
        checked_file(repository, relative, identity)
    required_source = {
        f"experiments/continuous_boundary_policy/{name}"
        for name in (
            "cells.py",
            "features.py",
            "execution.py",
            "training.py",
            "study.py",
            "common.py",
            "audit.py",
            "audit_math.py",
            "audit_cell.py",
            "audit_integrity.py",
            "audit_stats.py",
            "native/decision.rs",
            "native/protocol.rs",
        )
    }
    require(
        required_source <= set(source["source_files"]),
        "Scientific source seal omits critical implementation",
    )
    prior = repository / "experiments/continuous_boundary_flow/SOURCE_SEAL.json"
    require(
        source["prior_source_seal_sha256"] == sha(prior.read_bytes()),
        "Prior study source binding changed",
    )
    actual = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
        and "host" not in path.relative_to(root).parts
        and "confirmation_hosts" not in path.relative_to(root).parts
        and path.name != "MANIFEST.json"
    }
    require(
        actual == set(manifest["files"]), "Manifest omits or invents experiment files"
    )
    for relative, identity in manifest["files"].items():
        checked_file(root, relative, identity)
    for relative, identity in selection["training_files"].items():
        require(
            manifest["files"].get(relative) == identity,
            "Training evidence changed after selection",
        )
        require(
            "shards" not in Path(relative).parts
            and "test_id.json" not in relative
            and "test_ood.json" not in relative,
            "Confirmation artifacts entered selection seal",
        )
    prefix = (root / "costs.jsonl").read_bytes()[
        : selection["training_costs_prefix_bytes"]
    ]
    require(
        sha(prefix) == selection["training_costs_prefix_sha256"],
        "Training costs changed after selection",
    )
    external = read_json(root, "EXTERNAL_SELECTION.json")
    require(
        external["selection_seal_sha256"] == manifest["selection_seal_sha256"]
        and external["confirmation_started_after_publication"] is True,
        "Missing preconfirmation selection commitment",
    )
    for commit in (environment["publication_commit"], external["selection_commit"]):
        require(
            isinstance(commit, str)
            and len(commit) == 40
            and all(c in "0123456789abcdef" for c in commit)
            and commit != "0" * 40,
            "Malformed external commitment",
        )
    require(
        selection["native_binary_sha256"] == environment["binary_sha256"]["native"]
        and selection["score_binary_sha256"] == environment["binary_sha256"]["score"],
        "Native binaries changed between phases",
    )
    for identity in environment["binary_sha256"].values():
        hash_text(identity, "native binary")
    require(manifest["expected_episodes"] == 26624, "Scheduled sample count changed")
    return protocol, manifest, selection, environment


def verify_training_receipt(
    receipt, seed, arm, *, candidate_indices=(0, 1, 2), epochs=120, development_count=64
):
    """Check training/development arithmetic; optional budgets are diagnostic-only."""
    require(
        receipt["seed"] == seed
        and receipt["arm"] == arm
        and receipt["test_data_used"] is False,
        "Training receipt identity/data-scope mismatch",
    )
    require(
        [r["candidate_index"] for r in receipt["candidates"]]
        == list(candidate_indices),
        "Candidate selection budget changed",
    )
    for item in receipt["candidates"]:
        index = item["candidate_index"]
        require(item["candidate"] == CANDIDATES[index], "Undeclared training candidate")
        values = np.asarray(item["development_returns"], dtype=float)
        require(
            values.shape == (development_count,) and np.isfinite(values).all(),
            "Incomplete development selection returns",
        )
        close(
            item["development_mean_net_utility"],
            values.mean(),
            "development selection mean",
            atol=1e-12,
        )
        fit = item["fit"]
        if arm != "native_sparse":
            require(
                fit["epochs"] == epochs
                and fit["gradient_evaluations"] == epochs + 1
                and fit["learning_rate"] == CANDIDATES[index]["learning_rate"]
                and fit["gradient_clip_norm"] == 5
                and fit["coefficient_bound"] == 8,
                "Unequal optimizer schedule or parameter bounds",
            )
            losses = np.asarray(fit["epoch_loss"], dtype=float)
            require(
                losses.shape == (epochs,) and np.isfinite(losses).all(),
                "Incomplete BPTT training ledger",
            )
        else:
            require(
                fit["head_scalars"] == 42, "Native reference fitted head budget changed"
            )
    winner = max(
        receipt["candidates"],
        key=lambda row: (row["development_mean_net_utility"], -row["candidate_index"]),
    )
    require(
        receipt["selected_index"] == winner["candidate_index"],
        "Selected index does not maximize registered development objective",
    )
    return winner


def verify_selection(root, selection, references):
    checkpoints, cells, profiles, training = {}, {}, {}, {}
    roster = {(seed, arm) for seed in SEEDS for arm in ARMS}
    for item in selection["checkpoints"]:
        key = item["seed"], item["arm"]
        require(
            key in roster and key not in checkpoints,
            "Missing/duplicate checkpoint identity",
        )
        path = checked_file(root, item["path"], item["sha256"])
        checkpoint = strict_json(path.read_bytes())
        cells[key] = verify_checkpoint(checkpoint, *key)
        checkpoints[key] = (checkpoint, item["sha256"])
        if key[1] == "native_sparse":
            profile_path = checked_file(
                root, checkpoint["profile_path"], checkpoint["profile_sha256"]
            )
            profiles[key] = strict_json(profile_path.read_bytes())
            verify_profile(profiles[key], key[0])
    require(set(checkpoints) == roster, "Incomplete selected checkpoint schedule")
    for seed in SEEDS:
        boundary = verify_training_dataset(root, seed, references)
        teacher_identity, full_features, flow_resets = None, {}, {}
        for arm in LEARNED:
            receipt = read_json(root, f"training/{seed}/{arm}/TRAINING.json")
            winner = verify_training_receipt(receipt, seed, arm)
            for item in receipt["candidates"]:
                index = item["candidate_index"]
                candidate = strict_json(
                    checked_file(root, item["path"], item["sha256"]).read_bytes()
                )
                verify_checkpoint(candidate, seed, arm)
                require(
                    candidate["candidate"] == item["candidate"] == CANDIDATES[index],
                    "Candidate metadata mismatch",
                )
                if arm == "learned_margin":
                    require(
                        candidate["boundary_weights"] == boundary,
                        "Boundary used nontraining coefficients",
                    )
                if arm == "native_sparse":
                    profile = strict_json(
                        checked_file(
                            root, candidate["profile_path"], candidate["profile_sha256"]
                        ).read_bytes()
                    )
                    verify_profile(profile, seed)
                if teacher_identity is None:
                    teacher_identity = item["teacher_sha256"]
                require(
                    item["teacher_sha256"] == teacher_identity,
                    "Different public teacher across methods/candidates",
                )
                for name in ("feature_sha256", "reset_sha256", "teacher_sha256"):
                    hash_text(item[name], name)
                if arm in {
                    "dual_flow",
                    "generic_gru",
                    "dual_event",
                    "elman_mlp",
                    "native_sparse",
                }:
                    full_features.setdefault(index, item["feature_sha256"])
                    require(
                        full_features[index] == item["feature_sha256"],
                        "Full-information comparison received different feature arrays",
                    )
                if arm in {"dual_flow", "generic_gru"}:
                    flow_resets.setdefault(index, item["reset_sha256"])
                    require(
                        flow_resets[index] == item["reset_sha256"],
                        "Structure pair received different reset signals",
                    )
                if arm != "native_sparse":
                    fit = item["fit"]
                    observed = fit["coordinates_with_nonzero_gradient"]
                    parameters = candidate["model"]["params"]
                    require(
                        set(observed) == set(parameters)
                        and all(
                            type(observed[name]) is int
                            and 0 <= observed[name] <= np.asarray(value).size
                            for name, value in parameters.items()
                        ),
                        "Invalid empirical gradient participation ledger",
                    )
            selected_checkpoint, selected_sha = checkpoints[seed, arm]
            require(
                receipt["selected_index"]
                == winner["candidate_index"]
                == selected_checkpoint["candidate_index"]
                and selected_sha == winner["sha256"],
                "Selected checkpoint does not match declared development winner",
            )
            training[seed, arm] = receipt
    return checkpoints, cells, profiles, training
