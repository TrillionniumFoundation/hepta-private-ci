"""Development protocol; no new qualification outputs may tune this study."""

import hashlib
import json
from pathlib import Path


PROTOCOL = {
    "schema": "hepta.ndu.direct-delivery-latent-gradient.v1",
    "baseline_commit": "fb9281e4a7ccfc4034281ed6310adea7e50f4474",
    "base": "prior validation-selected joint_uniform, separately pinned per fixed seed",
    "seeds": [17, 29, 43],
    "arms": ["original", "noise_control", "direct_mean", "direct_risk"],
    "dimensions": 12,
    "hidden": 48,
    "sigma": 0.15,
    "steps": 600,
    "checkpoints": [200, 400, 600],
    "batch_size": 16,
    "directions": 8,
    "gamma": 2.,
    "learning_rate": 0.0005,
    "gradient_clip": 2.,
    "clean_kl_coefficient": 0.0002,
    "training_mixture": "equal probability of clean, occlusion, missing and heavy_noise; same as test",
    "conditions": ["clean", "occlusion", "missing", "heavy_noise"],
    "basis": "top 12 centered terminal-state PCA directions on 512 historical training examples; target labels unused",
    "generator_parameterization": "learned public-state mean in a fixed Gaussian latent residual, decoded to actual PNG and UTF8 by frozen original neural decoder",
    "direct_mean_objective": "E[-U(delivered PNG,UTF8)] plus explicit clean Gaussian KL",
    "direct_risk_objective": "E[(exp(-2U(delivered PNG,UTF8))-1)/2] plus the same clean Gaussian KL",
    "gradient": "antithetic likelihood-ratio derivative of the actual stochastic deployed distribution; no reward observer derivative or straight-through quantizer",
    "claims": "exact unbiased reward gradient estimator before gradient clipping; finite Monte Carlo and optimizer do not imply global optimality",
    "trainable_scope": "latent generator mean network only; original encoder/transitions/decoder/gate remain frozen",
    "selection": "validation actual-output CE subject to clean CE >= original-0.005; zero actor eligible; identical checkpoint grid and full training budget for both arms",
    "validation_pairs": 96,
    "validation_retention_pairs": 128,
    "validation_retention_offset": 96,
    "validation_retention_tolerance": 0.005,
    "evaluation_seed": 271028,
    "test_pairs": 512,
    "retention_pairs": 256,
    "bootstrap_replicates": 5000,
    "bootstrap_seed": 771028,
    "interval": 0.975,
    "retention_noninferiority_margin": 0.01,
    "test_selection_allowed": False,
    "scope": "finite constructed MNIST image/text generation; no natural audio/video or unrestricted Merton/NDU optimality claim",
    "threads": 1,
}


def checksum(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
