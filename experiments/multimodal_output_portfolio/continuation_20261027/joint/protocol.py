"""Prospective development design; qualification is sealed before test scoring."""

import hashlib
import json
from pathlib import Path


PROTOCOL = {
    "schema": "hepta.ndu.continuation-joint.v1",
    "study": "actual-moment-clean-replay-001",
    "baseline_commit": "63f198ad85cfa2aa579032256355f446cfe793a0",
    "base_archive_sha256": "ddbdf10b4397c8538183df8fa7c16f08c5fba226a304ff7cb55574ddb97e951e",
    "seeds": [17, 29, 43],
    "arms": ["frozen", "joint_uniform", "joint_risk"],
    "steps": 600,
    "checkpoints": [200, 400, 600],
    "batch_size": 32,
    "clean_replay_fraction": 0.5,
    "training_corruption_mixture": "clean 1/2, each stress condition 1/6; extra clean replay is a capability-preservation regularizer",
    "evaluation_corruption_mixture": "each of four conditions 1/4; generator proxy is not an unbiased gradient of this qualification distribution",
    "stress_cycle": ["occlusion", "missing", "heavy_noise"],
    "learning_rate_core": 0.00015,
    "learning_rate_gate": 0.001,
    "gradient_clip": 1.0,
    "gamma": 2.0,
    "same_training_budget": "identical batches, latent noise, 4 plans, forced/free decoders, PNG roundtrips, fixed observer calls and optimizer updates",
    "deployed_selection": "deterministic argmax, same as candidate selection used in generator updates",
    "gate_target": "actual PNG/UTF8 exp(-gamma * utility), squared moment prediction error; argmax raw score minimizes the predicted moment",
    "generator_objective": "supervised reconstruction/caption/semantic proxy on selected deployed plan, 0.1 all-plan anchor, 0.3 same-plan teacher distillation on clean replay",
    "risk_weight": "exp(-gamma * actual selected-plan utility), normalized across the whole minibatch and detached",
    "exact_discrete_reward_gradient": False,
    "training_observer_parameters_frozen": True,
    "audit_observer_loaded_only_after_selection_freeze": True,
    "validation_pairs": 64,
    "validation_retention_pairs": 128,
    "validation_retention_offset": 64,
    "validation_retention_tolerance": 0.005,
    "parameter_interpolations": [0.5, 1.0],
    "selection": "maximize actual reward-observer CE on all 4 conditions subject to clean validation CE >= original-0.005; original is eligible; tie favors smaller update then earlier checkpoint",
    "test_pairs": 512,
    "retention_pairs": 512,
    "conditions": ["clean", "occlusion", "missing", "heavy_noise"],
    "fresh_source_seed": 271027,
    "evaluation_seed": 20261027,
    "bootstrap_seed": 62027,
    "bootstrap_replicates": 5000,
    "interval": 0.975,
    "retention_noninferiority_margin": 0.01,
    "primary_generator_gate": "joint_risk-frozen test CE lower bound > 0, every fixed seed positive, retention lower bound >= -0.01",
    "generator_attribution_gate": "joint_risk exceeds an offline target-aware original-generator oracle over all 16 two-action sequences; paired test CE lower bound > 0 and each fixed seed positive",
    "oracle_scope": "offline privileged upper bound for the original generator at the same two-transition depth, same latent noise and final decoder; extra oracle search/target access is not an equal-budget deployed arm",
    "matched_training_gate": "joint_risk-joint_uniform test CE lower bound > 0, every fixed seed positive, retention lower bound >= -0.01",
    "bootstrap_unit": "source image pair, shared across corruptions and fixed seeds; seeds are not a population sample",
    "new_test_sources": "official MNIST test pixels outside every source hash in the restored full002 corpus and historical prior-heldout exclusion",
    "scope": "constructed MNIST pair generation; no writer metadata, natural AV synthesis, production owner or global unrestricted optimality claim",
    "threads": 1,
}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def checksum(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def freeze(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "DEVELOPMENT_PROTOCOL.json"
    write_json(path, PROTOCOL)
    return checksum(path)
