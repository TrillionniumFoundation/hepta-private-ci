"""Fixed development protocol, declared before this study's held-out outputs."""

import hashlib
import json
from pathlib import Path


PROTOCOL = {
    "schema": "hepta.ndu.repair-joint-development.v1",
    "study": "real-v6-joint-001", "seeds": [17, 29, 43],
    "arms": ["frozen", "joint_mean", "joint_entropic"],
    "steps": 120, "batch_size": 16, "scenarios": 2, "gamma": 2.0,
    "learning_rate_core": 0.00008, "learning_rate_gate": 0.0005,
    "gradient_clip": 1.0, "supervised_anchor": 0.1, "distillation_anchor": 0.5,
    "threads": 2, "test_pairs": 128, "retention_pairs": 128,
    "test_offset": 200, "retention_offset": 100,
    "test_corruptions": ["clean", "occlusion", "missing", "heavy_noise"],
    "evaluation_seed": 20261026, "bootstrap_seed": 51026, "bootstrap_samples": 3000,
    "bootstrap_cluster": "disjoint_source_pair_across_corruptions_and_training_seeds",
    "primary": "independent_audit_observer_actual_PNG_UTF8_CE_gamma2",
    "comparisons": ["joint_entropic-frozen", "joint_entropic-joint_mean"],
    "simultaneous_comparison_interval": 0.975,
    "retention_noninferiority_margin": 0.01,
    "acceptance": "both primary lower bounds > 0; retention lower bound >= -0.01; all three seed differences > 0",
    "base_archive_sha256": "ddbdf10b4397c8538183df8fa7c16f08c5fba226a304ff7cb55574ddb97e951e",
    "base": "seed-matched original full002 terminal_entropic_ndu ControlledSnapshot",
    "updated": ["public_encoders", "shared_latent_transitions", "image_decoder", "text_decoder", "plan_gate"],
    "matched_budget": "same minibatches, noise, four two-action plans, decoder/observer calls, anchors, optimizer steps",
    "training_objective": "differentiable soft semantic utility, straight-through 8-bit quantization, plus supervised and teacher anchors",
    "training_is_exact_discrete_output_reward_gradient": False,
    "train_plan_selection": "soft distribution", "deployed_plan_selection": "argmax",
    "parameters_fixed_during_inference": True,
    "audit_observer_exposed_to_training": False,
    "scope": "MNIST-pair text/image development; historical public dataset; no natural audio/video claim",
    "fresh_population_confirmation": False,
}


def freeze(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(PROTOCOL, indent=2, sort_keys=True) + "\n").encode()
    target = directory / "PROTOCOL.json"
    if target.exists() and target.read_bytes() != encoded:
        raise ValueError("A different frozen protocol already exists")
    target.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()
