#!/usr/bin/env python3
"""Offline publisher-metadata and physical-bytes gate for Laya-family shadow trials.

The catalog is an UNSIGNED record of publisher metadata at a pinned revision.
Inspecting it proves neither downloads nor trusted upstream provenance. Local
inspection hashes complete already-materialized bytes, rejects symlinks, checks
Laya configs and tensor shapes without executing the model, and still grants
ZERO deployment or NDU selection authority. No network, HF login or download.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from hepta_neuron_model_trials import (
    InvalidTrial,
    MODEL_IDS,
    is_sha,
    physical_absolute_directory,
    read_json,
    require,
    sha_file,
    sha_tree,
    write_new,
)

SCHEMA = "hepta.neuron.upstream-artifacts.v1"
REPORT = "hepta.neuron.upstream-artifact-preflight.v1"
REPOSITORY = "convaiinnovations/laya"
REVISION = "7b928d828b7b0e022f929d9bd2e44165aa270148"
# Public Hugging Face Xet SHA-256 pointer metadata, not checksums observed locally.
PUBLISHED_WEIGHTS = {
    "laya": ("", "891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c"),
    "typed": (
        "typed-decisions",
        "4fa56de72383a9d3efa9cfa78955733c81b9fc8067a587ca4beb82c78107a24e",
    ),
    "multilingual": (
        "multilingual",
        "9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204",
    ),
}
REQUIRED = (
    "model.safetensors",
    "rl_agent_config.json",
    "encoder/config.json",
    "tokenizer/tokenizer.json",
    "tokenizer/tokenizer_config.json",
)


def verify_catalog(catalog):
    require(
        isinstance(catalog, dict)
        and set(catalog)
        == {
            "schema",
            "repository",
            "revision",
            "variants",
            "licence",
            "source_evidence_urls",
        },
        "unexpected catalog schema/fields",
    )
    require(
        catalog["schema"] == SCHEMA
        and catalog["repository"] == REPOSITORY
        and catalog["revision"] == REVISION
        and catalog["licence"] == "apache-2.0",
        "upstream source is not the frozen Laya family",
    )
    variants = catalog["variants"]
    require(
        isinstance(variants, dict) and set(variants) == set(PUBLISHED_WEIGHTS),
        "missing or extra Laya variants",
    )
    for arm, (subfolder, published_sha) in PUBLISHED_WEIGHTS.items():
        v = variants[arm]
        require(
            isinstance(v, dict)
            and set(v)
            == {
                "model_id",
                "subfolder",
                "weights_sha256",
                "weights_path",
                "required_files",
            },
            f"incomplete {arm} metadata",
        )
        require(
            v["model_id"] == MODEL_IDS[arm]
            and v["subfolder"] == subfolder
            and v["weights_sha256"] == published_sha
            and v["weights_path"] == "model.safetensors"
            and v["required_files"] == list(REQUIRED),
            f"unexpected {arm} upstream bytes/path",
        )
    urls = catalog["source_evidence_urls"]
    require(
        isinstance(urls, dict)
        and set(urls) == set(PUBLISHED_WEIGHTS)
        and all(
            isinstance(x, str)
            and x.startswith("https://huggingface.co/convaiinnovations/laya/")
            for x in urls.values()
        ),
        "source metadata URL missing",
    )
    return catalog


def match_manifest_catalog(manifest, catalog, digest):
    """Check the runner's frozen experiment manifest against all 3 source pins."""
    verify_catalog(catalog)
    require(
        manifest.get("upstream_lock_sha256") == digest,
        "upstream artifact lock bytes differ from experiment manifest",
    )
    family = manifest.get("family")
    require(
        family in ("decisions", "multilingual"), "only Laya families use upstream lock"
    )
    arms = ("laya", "typed") if family == "decisions" else ("laya", "multilingual")
    models = manifest.get("models")
    require(
        isinstance(models, dict) and set(models) == set(arms),
        "full model arm set differs from frozen source lock",
    )
    for arm in arms:
        entry = models[arm]
        frozen = catalog["variants"][arm]
        require(
            entry.get("model_id") == frozen["model_id"]
            and entry.get("revision") == catalog["revision"]
            and entry.get("weights_sha256") == frozen["weights_sha256"]
            and is_sha(entry.get("artifact_tree_sha256")),
            "model manifest differs from publisher-locked model/commit/checksum",
        )
    return True


def _tensor_inventory(weights):
    """Read safe tensor metadata only; never instantiate 421M/322M model weights."""
    try:
        from safetensors import safe_open
    except ImportError as error:
        raise InvalidTrial(
            "safetensors is mandatory for physical tensor preflight"
        ) from error
    total = 0
    dtype_counts = {}
    with safe_open(str(weights), framework="pt", device="cpu") as handle:
        keys = handle.keys()
        require(bool(keys), "empty weights tensor inventory")
        for key in keys:
            shape = handle.get_slice(key).get_shape()
            require(
                isinstance(shape, list)
                and all(type(x) is int and x >= 0 for x in shape),
                "invalid tensor dimensions",
            )
            count = math.prod(shape)
            require(count > 0, "empty tensor")
            total += count
    require(total > 0, "zero parameter count")
    return total, len(keys)


def inspect_local(catalog, arm, artifact_dir):
    verify_catalog(catalog)
    require(arm in PUBLISHED_WEIGHTS, "unknown model arm")
    root = Path(artifact_dir)
    require(
        physical_absolute_directory(root),
        "artifact directory must be a real absolute local directory",
    )
    # Do not resolve paths before checking links. A linked model root would
    # otherwise become indistinguishable from an original physical directory.
    children = list(root.rglob("*"))
    require(not any(path.is_symlink() for path in children), "symlink in artifact tree")
    require(
        all(
            (root / file).is_file() and not (root / file).is_symlink()
            for file in REQUIRED
        ),
        "incomplete local Encoder/Tokenizer/weights bundle",
    )
    config = read_json(root / "rl_agent_config.json")
    expected_encoder = (
        "jhu-clsp/mmBERT-base"
        if arm == "multilingual"
        else "answerdotai/ModernBERT-large"
    )
    require(
        isinstance(config, dict)
        and type(config.get("head_layers")) is int
        and config["head_layers"] == 2
        and type(config.get("max_len")) is int
        and config["max_len"] >= 512
        and config.get("encoder") == expected_encoder,
        "incompatible Laya model config",
    )
    # Local config/tokenizer content is still self-described, not independently
    # certified; digest binds these bytes to the run's frozen manifest.
    for file in ("encoder/config.json", "tokenizer/tokenizer_config.json"):
        require(
            isinstance(read_json(root / file), dict),
            "invalid local model/tokenizer config",
        )
    weights = root / "model.safetensors"
    # This exact full-file digest, not the Xet chunk hash, must match.
    observed = sha_file(weights)
    require(
        observed == catalog["variants"][arm]["weights_sha256"],
        "local model weights do not match pinned publisher SHA-256",
    )
    params, tensor_count = _tensor_inventory(weights)
    minimum, maximum = (
        (315_000_000, 330_000_000)
        if arm == "multilingual"
        else (415_000_000, 425_000_000)
    )
    require(
        minimum <= params <= maximum,
        "actual tensor inventory outside frozen model family",
    )
    return {
        "schema": REPORT,
        "arm": arm,
        "model_id": catalog["variants"][arm]["model_id"],
        "source_repository": catalog["repository"],
        "source_revision": catalog["revision"],
        "source_subfolder": catalog["variants"][arm]["subfolder"],
        "weights_sha256": observed,
        "artifact_tree_sha256": sha_tree(root),
        "num_parameters_from_safetensors": params,
        "tensor_count": tensor_count,
        "config_sha256": sha_file(root / "rl_agent_config.json"),
        "tokenizer_sha256": sha_file(root / "tokenizer/tokenizer.json"),
        "encoder_config_sha256": sha_file(root / "encoder/config.json"),
        "local_weight_bytes_verified": True,
        "model_forward_executed": False,
        "source_publisher_independently_authenticated": False,
        "production_evidence_verified": False,
        "ndu_selection_authorized": False,
        "promotion_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("catalog", "local"))
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--arm", choices=tuple(PUBLISHED_WEIGHTS))
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        catalog = verify_catalog(read_json(args.catalog))
        if args.mode == "local":
            require(
                args.arm is not None and args.artifact_dir is not None,
                "physical model dir and arm mandatory",
            )
            result = inspect_local(catalog, args.arm, args.artifact_dir)
        else:
            require(
                args.arm is None and args.artifact_dir is None,
                "catalog mode does not inspect physical files",
            )
            result = {
                "schema": REPORT,
                "upstream_catalog_sha256": sha_file(args.catalog),
                "revision": catalog["revision"],
                "variants": list(PUBLISHED_WEIGHTS),
                "publisher_metadata_checked": True,
                "local_weight_bytes_verified": False,
                "source_publisher_independently_authenticated": False,
                "model_forward_executed": False,
                "production_evidence_verified": False,
                "ndu_selection_authorized": False,
                "promotion_authorized": False,
            }
        write_new(args.output, result)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"blocked: {error}\n")


if __name__ == "__main__":
    main()
