"""Fresh private paid-feedback trajectories with disjoint research namespaces."""

from pathlib import Path

import numpy as np


SEEDS = (3407, 3613, 3821, 4001, 4219)
DATA_OFFSET = 660000000
SMOKE_OFFSET = 760000000
SMOKE_SEED = 95003
DOMAINS = ("nominal", "drift", "student_t")
ARMS = ("event", "direct", "float", "gaussian", "probit", "analytic", "numeric", "history", "uncalibrated")
LEARNED = ("analytic", "numeric", "history")
SPLITS = {"train": 1, "development": 2, "confirmation": 3, "qualification": 4}
ACTUAL_NOISE_SCALE = 1.75


def dataset(seed, n, split, domain="nominal", *, smoke=False):
    """Return private environment data, never an inference feature dictionary."""
    if (type(seed) is not int or seed < 0 or type(n) is not int or n < 1
            or split not in SPLITS or domain not in DOMAINS or type(smoke) is not bool):
        raise ValueError("Declared seed, row count, split, domain and namespace required")
    if (smoke and seed != SMOKE_SEED) or (not smoke and seed not in SEEDS):
        raise ValueError("Seed is outside the declared namespace")
    if split in ("train", "development") and domain != "nominal":
        raise ValueError("Only nominal training and development are registered")
    if smoke and split == "confirmation" and (n > 8 or domain != "nominal"):
        raise ValueError("Development smoke confirmation is bounded to eight nominal rows")
    offset = SMOKE_OFFSET if smoke else DATA_OFFSET
    random_seed = offset + 1000 * seed + 100 * DOMAINS.index(domain) + SPLITS[split]
    rng = np.random.default_rng(random_seed)
    initial = rng.normal(size=n)
    weights, means, variances = ([.4, .6], [-.15, 1.05], [.12, .48]) if domain == "drift" else (
        [.65, .35], [-.45, .85], [.09, .36])
    components = rng.choice(2, n, p=weights)
    innovation = rng.standard_t(5, n) * np.sqrt(3 / 5) if domain == "student_t" else rng.normal(size=n)
    error = np.asarray(means)[components] + np.sqrt(np.asarray(variances)[components]) * innovation
    variance = rng.choice([.04, .36, 1.44], n)
    wait_variance = rng.choice([.04, .16, .64], n)
    target = initial + error
    namespace = "smoke" if smoke else "registered"
    return {
        "initial_output": initial,
        "self_evaluation": target + np.sqrt(ACTUAL_NOISE_SCALE * variance) * rng.normal(size=n),
        "wait_evaluation": target + np.sqrt(ACTUAL_NOISE_SCALE * wait_variance) * rng.normal(size=n),
        "sensor_variance": variance, "wait_variance": wait_variance,
        "repair_cost": rng.choice([.03, .12, .48], n),
        "wait_cost": rng.choice([.01, .04, .12], n), "target": target,
        "ids": np.asarray([f"feedback6:{namespace}:{domain}:{split}:{seed}:{i}" for i in range(n)]),
        "seed": seed, "split": split, "domain": domain,
        "law": "private-mixture-error-paid-gaussian-sensors.v6",
    }


def load_data(path):
    """Private data loader for training, broker and post-execution scoring only."""
    with np.load(Path(path), allow_pickle=False) as source:
        return {name: source[name].item() if source[name].ndim == 0 else source[name]
                for name in source.files}


def native_paths(run_dir):
    root = Path(run_dir) / "native"
    return root / "analytic_event", root / "BUILD_RECEIPT.json"
