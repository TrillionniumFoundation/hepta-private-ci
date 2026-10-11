#!/usr/bin/env python3
"""Replay the exact three-arm public-weight smoke *diagnostic* receipt bundle.

Checks inter-file byte hashes, immutable catalog, selected source/run identities,
weight and model identities, physical-load declarations, and synthetic forward
observations. Archived JSON and workflow success remain self-reported evidence,
NOT independent host attestation, NDU evaluation, or production admission.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from hepta_neuron_artifact_preflight import REQUIRED, verify_catalog
from hepta_neuron_model_trials import (
    InvalidTrial,
    is_sha,
    read_json,
    require,
    sha_file,
    write_new,
)

SCHEMA = "hepta.neuron.physical-smoke-three-arm-diagnostic.v1"
REPORT = "hepta.neuron.physical-smoke-receipt-replay.v1"
FORWARD = "hepta.neuron.physical-forward-smoke.v1"
MATERIALIZE = "hepta.neuron.weight-materialization.v1"
ARMS = ("laya", "typed", "multilingual")
FILES = tuple(
    item
    for arm in ARMS
    for item in (
        f"hepta-{arm}-materialization.json",
        f"hepta-{arm}-physical-smoke.json",
    )
)
URL_BASE = "https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/"


def _finite_positive_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _false_authority(obj, *, forward=False):
    for name in (
        "production_evidence_verified",
        "ndu_selection_authorized",
        "promotion_authorized",
    ):
        require(obj.get(name) is False, f"false authority field required: {name}")
    if forward:
        for name in (
            "actual_hepta_data_used",
            "target_host_independently_attested",
            "ndu_net_gain_verified",
        ):
            require(
                obj.get(name) is False,
                f"non-production forward flag must be false: {name}",
            )
    else:
        require(
            obj.get("independently_attested_host") is False,
            "metadata cannot attest the host",
        )


def verify_receipts(
    directory: Path,
    catalog_path: Path,
    *,
    expected_run_id: int,
    expected_source_sha: str,
    expected_manifest_sha256: str | None = None,
):
    require(
        type(expected_run_id) is int and expected_run_id > 0,
        "pinned GitHub Actions run ID required",
    )
    require(is_sha(expected_source_sha, 40), "pinned Git source commit required")
    if expected_manifest_sha256 is not None:
        require(is_sha(expected_manifest_sha256), "manifest SHA-256 pin invalid")
    directory = Path(directory)
    require(
        directory.is_absolute() and directory.is_dir() and not directory.is_symlink(),
        "absolute trusted receipt directory required",
    )
    paths = list(directory.iterdir())
    require(
        set(p.name for p in paths) == {*FILES, "manifest.json"},
        "missing, extra or duplicate receipt filenames",
    )
    require(
        all(p.is_file() and not p.is_symlink() for p in paths),
        "receipt entries must be regular non-symlink files",
    )
    manifest_path = directory / "manifest.json"
    manifest_sha = sha_file(manifest_path)
    require(
        expected_manifest_sha256 is None or manifest_sha == expected_manifest_sha256,
        "receipt manifest changed from independent pin",
    )
    manifest = read_json(manifest_path)
    require(isinstance(manifest, dict), "diagnostic manifest must be a JSON object")
    catalog = verify_catalog(read_json(catalog_path))
    catalog_sha = sha_file(catalog_path)
    require(
        manifest.get("schema") == SCHEMA
        and manifest.get("run_id") == expected_run_id
        and manifest.get("run_url") == URL_BASE + str(expected_run_id)
        and manifest.get("source_commit") == expected_source_sha
        and manifest.get("actual_hepta_data_used") is False
        and manifest.get("production_evidence_verified") is False
        and manifest.get("ndu_selection_authorized") is False
        and manifest.get("promotion_authorized") is False
        and isinstance(manifest.get("source"), str)
        and manifest["source"].startswith("untrusted GitHub Actions metadata;")
        and type(manifest.get("artifact_id")) is int
        and manifest["artifact_id"] > 0
        and is_sha(manifest.get("artifact_sha256"))
        and isinstance(manifest.get("limitations"), list)
        and len(manifest["limitations"]) > 0,
        "invalid diagnostic manifest/run or overstated authority",
    )
    indexed = manifest.get("files")
    require(
        isinstance(indexed, dict) and set(indexed) == set(FILES),
        "incomplete artifact file index",
    )
    for name in FILES:
        meta = indexed[name]
        require(
            isinstance(meta, dict)
            and set(meta) == {"bytes", "sha256"}
            and type(meta["bytes"]) is int
            and meta["bytes"] > 0
            and is_sha(meta["sha256"]),
            "invalid file index entry",
        )
        p = directory / name
        require(
            p.stat().st_size == meta["bytes"] and sha_file(p) == meta["sha256"],
            f"archived file changed after manifest: {name}",
        )
    obs_index = manifest.get("observations")
    require(
        isinstance(obs_index, dict) and set(obs_index) == set(ARMS),
        "three-arm manifest observations absent",
    )
    parameters = {}
    sdk_digests = set()
    for arm in ARMS:
        metadata = catalog["variants"][arm]
        m = read_json(directory / f"hepta-{arm}-materialization.json")
        f = read_json(directory / f"hepta-{arm}-physical-smoke.json")
        require(isinstance(m, dict) and isinstance(f, dict), "malformed JSON receipt")
        _false_authority(m)
        _false_authority(f, forward=True)
        tree = m.get("physical_artifact_tree_sha256")
        require(
            m.get("schema") == MATERIALIZE
            and m.get("arm") == arm
            and m.get("model_id") == metadata["model_id"]
            and m.get("catalog_revision") == catalog["revision"]
            and m.get("catalog_sha256") == catalog_sha
            and m.get("local_weight_bytes_verified") is True
            and m.get("tensor_inventory_verified") is True
            and type(m.get("network_permission_used")) is bool
            and is_sha(tree),
            "physical materialization claim incompatible with source lock",
        )
        file_shas = m.get("relative_file_sha256")
        require(
            isinstance(file_shas, dict)
            and set(file_shas) == set(REQUIRED)
            and all(is_sha(x) for x in file_shas.values())
            and file_shas["model.safetensors"] == metadata["weights_sha256"],
            "complete relative source files and pinned weight hash required",
        )
        require(
            f.get("schema") == FORWARD
            and f.get("arm") == arm
            and f.get("model_id") == metadata["model_id"]
            and f.get("repository") == catalog["repository"]
            and f.get("source_revision") == catalog["revision"]
            and f.get("source_catalog_sha256") == catalog_sha
            and f.get("weights_sha256") == metadata["weights_sha256"]
            and f.get("physical_artifact_tree_sha256") == tree
            and f.get("model_forward_executed") is True
            and f.get("synthetic_question_only") is True
            and is_sha(f.get("installed_sdk_python_sha256"))
            and f.get("device") == "cpu"
            and type(f.get("parameters")) is int
            and 1 <= f["parameters"] <= 425_000_000,
            "physical forward claim mismatches materialization or frozen model",
        )
        runtime = f.get("runtime")
        require(
            isinstance(runtime, dict)
            and runtime.get("artifact_tree_sha256") == tree
            and runtime.get("sdk_tree_sha256") == f["installed_sdk_python_sha256"]
            and runtime.get("effective_context") == 512
            and runtime.get("effective_head_budget") == 192
            and isinstance(runtime.get("torch"), str)
            and runtime["torch"],
            "forward runtime/config binding incomplete",
        )
        ob = f.get("synthetic_observation")
        require(
            isinstance(ob, dict)
            and set(ob)
            == {"id", "split", "input_tokens", "latency_ms", "probabilities"}
            and ob.get("id") == "synthetic-no-label-control-1"
            and ob.get("split") == "holdout"
            and type(ob.get("input_tokens")) is int
            and ob["input_tokens"] > 0
            and _finite_positive_number(ob.get("latency_ms")),
            "invalid synthetic forward observation",
        )
        ps = ob.get("probabilities")
        require(
            isinstance(ps, list)
            and len(ps) == 2
            and all(
                type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in ps
            )
            and abs(sum(ps) - 1) <= 0.002,
            "forward probabilities invalid",
        )
        expected = obs_index[arm]
        require(
            isinstance(expected, dict)
            and expected.get("artifact_tree_sha256") == tree
            and expected.get("weights_sha256") == metadata["weights_sha256"]
            and expected.get("model_forward_executed") is True
            and expected.get("device") == f["device"]
            and expected.get("num_parameters") == f["parameters"]
            and expected.get("latency_ms_single_sample") == ob["latency_ms"]
            and expected.get("input_tokens") == ob["input_tokens"],
            "indexed observation differs from model forward receipt",
        )
        sdk_digests.add(f["installed_sdk_python_sha256"])
        parameters[arm] = f["parameters"]
    require(
        len(sdk_digests) == 1
        and parameters["laya"] == parameters["typed"]
        and parameters["multilingual"] < parameters["laya"],
        "SDK or model parameter comparison invalid",
    )
    return {
        "schema": REPORT,
        "diagnostic_only": True,
        "run_id": expected_run_id,
        "source_commit": expected_source_sha,
        "catalog_sha256": catalog_sha,
        "manifest_sha256": manifest_sha,
        "expected_manifest_sha256_was_supplied": expected_manifest_sha256 is not None,
        "all_six_receipts_match_archive_manifest": True,
        "three_upstream_weight_digests_cross_checked": True,
        "synthetic_cpu_forward_claims_cross_checked": True,
        "source_artifact_not_independently_attested": True,
        "actual_hepta_data_used": False,
        "ndu_selection_authorized": False,
        "production_evidence_verified": False,
        "promotion_authorized": False,
        "parameters": parameters,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--expected-run-id", type=int, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        require(
            args.output.is_absolute() and not args.output.exists(),
            "fresh absolute receipt output required",
        )
        write_new(
            args.output,
            verify_receipts(
                args.directory,
                args.catalog,
                expected_run_id=args.expected_run_id,
                expected_source_sha=args.expected_source_sha,
                expected_manifest_sha256=args.expected_manifest_sha256,
            ),
        )
    except (InvalidTrial, ValueError, TypeError, KeyError, OSError) as exc:
        parser.exit(2, f"blocked: {exc}\n")


if __name__ == "__main__":
    main()
