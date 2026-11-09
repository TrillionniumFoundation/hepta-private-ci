"""Train-only PCA compression baseline; it makes no task-benefit claim."""

import time
from pathlib import Path

import numpy as np

from .schema import digest, exact, integer, require, sha, string


def fit_projection(features, *, captures, groups, backbone_sha256, dimension=16):
    """Fit on actual features and explicit train capture/group identities.

    Each captures entry is {sha256, split}; repeated captures for different crops
    are allowed, but the same capture cannot be assigned to two source groups.
    The caller remains responsible for authenticating the declared split.
    """
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    values = np.asarray(features, dtype=np.float64)
    require(values.ndim == 2 and values.shape[1] == 576, "expected N x 576 features")
    require(
        2 <= len(values) <= 10000 and np.isfinite(values).all(),
        "invalid training features",
    )
    require(
        1 <= integer(dimension, 1) <= min(len(values) - 1, 576),
        "invalid projection dimension",
    )
    require(
        type(captures) is list
        and type(groups) is list
        and len(captures) == len(groups) == len(values),
        "training identities do not cover rows",
    )
    digest(backbone_sha256)
    seen = {}
    for capture, group in zip(captures, groups):
        exact(capture, "sha256 split")
        digest(capture["sha256"])
        require(capture["split"] == "train", "projection accepts train captures only")
        require(len(string(group)) <= 256, "source group too long")
        require(
            seen.setdefault(capture["sha256"], group) == group,
            "capture crosses source groups",
        )
    mean = values.mean(axis=0)
    _, singular, vectors = np.linalg.svd(values - mean, full_matrices=False)
    components = vectors[:dimension].copy()
    for component in components:
        if component[np.argmax(np.abs(component))] < 0:
            component *= -1
    scale = np.maximum(singular[:dimension] / np.sqrt(len(values) - 1), 1e-6)
    return {
        "schema": "perc1.projection.v1",
        "kind": "train_pca_compression_baseline",
        "backbone_sha256": backbone_sha256,
        "input_dimension": 576,
        "dimension": dimension,
        "mean": mean.tolist(),
        "components": components.tolist(),
        "scale": scale.tolist(),
        "normalization": "tanh(centered_projection / (3 * train_std))",
        "training": {
            "split": "train",
            "rows": len(values),
            "source_groups": sorted(set(groups)),
            "captures_sha256": sha(captures),
            "row_groups_sha256": sha(groups),
            "features_f64le_sha256": sha(values.astype("<f8").tobytes()),
            "code_sha256": sha(Path(__file__).read_bytes()),
            "numpy": np.__version__,
            "wall_ns": time.perf_counter_ns() - started,
            "cpu_ns": time.process_time_ns() - cpu,
            "scientific_qualified": False,
        },
    }


def project(features, projection, backbone_sha256):
    exact(
        projection,
        "schema kind backbone_sha256 input_dimension dimension mean components scale normalization training",
    )
    require(
        projection["schema"] == "perc1.projection.v1"
        and projection["kind"] == "train_pca_compression_baseline",
        "unknown projection",
    )
    require(
        digest(projection["backbone_sha256"]) == digest(backbone_sha256),
        "projection backbone mismatch",
    )
    require(
        projection["input_dimension"] == 576
        and projection["normalization"]
        == "tanh(centered_projection / (3 * train_std))",
        "projection semantics mismatch",
    )
    dimension = integer(projection["dimension"], 1)
    training = exact(
        projection["training"],
        "split rows source_groups captures_sha256 row_groups_sha256 features_f64le_sha256 code_sha256 numpy wall_ns cpu_ns scientific_qualified",
    )
    require(
        dimension <= 576
        and training["split"] == "train"
        and training["scientific_qualified"] is False,
        "invalid projection training identity",
    )
    rows = integer(training["rows"], 2)
    require(dimension < rows <= 10000, "invalid training row count")
    groups = training["source_groups"]
    require(
        type(groups) is list
        and 0 < len(groups) <= rows
        and all(type(group) is str and 0 < len(group) <= 256 for group in groups)
        and groups == sorted(set(groups)),
        "invalid training source groups",
    )
    for name in (
        "captures_sha256",
        "row_groups_sha256",
        "features_f64le_sha256",
        "code_sha256",
    ):
        require(digest(training[name]) != "0" * 64, "unbound training metadata")
    string(training["numpy"])
    integer(training["wall_ns"])
    integer(training["cpu_ns"])
    values = np.asarray(features, dtype=np.float64)
    mean = np.asarray(projection["mean"], dtype=np.float64)
    components = np.asarray(projection["components"], dtype=np.float64)
    scale = np.asarray(projection["scale"], dtype=np.float64)
    require(
        values.ndim == 2
        and values.shape[1] == 576
        and mean.shape == (576,)
        and components.shape == (dimension, 576)
        and scale.shape == (dimension,),
        "projection shape mismatch",
    )
    require(
        all(np.isfinite(value).all() for value in (values, mean, components, scale))
        and (scale > 0).all(),
        "invalid projection numbers",
    )
    result = np.tanh(((values - mean) @ components.T) / (3 * scale))
    require(np.isfinite(result).all(), "nonfinite projected output")
    return result
