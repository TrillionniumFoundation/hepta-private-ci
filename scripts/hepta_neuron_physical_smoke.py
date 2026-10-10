#!/usr/bin/env python3
"""One genuine pinned Laya forward on a synthetic question; NO efficacy claim.

A target-host operator must explicitly materialize exact checked weights first.
This offline diagnostic never loads labels, NDU data, production routes or tools.
The immutable forward receipt cannot authorize shadow/canary/production promotion.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from hepta_neuron_artifact_preflight import inspect_local, verify_catalog
from hepta_neuron_model_trials import (
    MODEL_IDS,
    InvalidTrial,
    is_sha,
    read_json,
    require,
    run_laya,
    sha_file,
    sha_tree,
    write_new,
)

SCHEMA = "hepta.neuron.physical-forward-smoke.v1"
QUESTION = {
    "type": "choice",
    "instructions": "Which queue handles a routine invoice?",
    "criteria": {
        "billing": "invoice and payment queries",
        "safety": "urgent incident reports",
    },
}


def run_smoke(
    catalog_path: Path,
    arm: str,
    artifact_dir: Path,
    expected_sdk_sha256: str,
    device: str,
):
    require(
        is_sha(expected_sdk_sha256) and arm in MODEL_IDS,
        "pinned SDK SHA and supported Laya arm required",
    )
    require(
        device == "cpu" or (device.startswith("cuda:") and device[5:].isdigit()),
        "explicit device cpu or cuda:N required; no implicit CPU fallback",
    )
    catalog_path = Path(catalog_path)
    catalog = verify_catalog(read_json(catalog_path))
    require(arm in catalog["variants"], "unknown locked model variant")
    require(
        Path(artifact_dir).is_absolute(), "local model must use an absolute directory"
    )
    physical = inspect_local(catalog, arm, Path(artifact_dir))
    require(
        physical["local_weight_bytes_verified"] is True,
        "physical weight integrity prerequisite absent",
    )
    # No implicit HF resolution, downloads, user credentials, or network in
    # model construction/forward. Stage model and SDK on this host beforehand.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["USE_TF"] = "0"
    import laya

    installed_sdk_sha = sha_tree(Path(laya.__file__).parent, only_python=True)
    require(
        installed_sdk_sha == expected_sdk_sha256,
        "installed Laya SDK source does not match pinned checkout",
    )
    model = catalog["variants"][arm]
    family = "multilingual" if arm == "multilingual" else "decisions"
    manifest = {
        "family": family,
        "parameter_cap": 425_000_000,
        "max_len": 512,
        "sdk_tree_sha256": expected_sdk_sha256,
        "models": {
            arm: {
                "model_id": MODEL_IDS[arm],
                "revision": catalog["revision"],
                "weights_sha256": model["weights_sha256"],
                "artifact_tree_sha256": physical["artifact_tree_sha256"],
            }
        },
    }
    row = {
        "id": "synthetic-no-label-control-1",
        "split": "holdout",
        "option_order": ["billing", "safety"],
        "state": "Synthetic record: invoice total requires a standard payment receipt.",
        "question": QUESTION,
    }
    parameters, weights, observations, runtime = run_laya(
        manifest,
        [row],
        arm,
        artifact_dir,
        Path("model.safetensors"),
        device,
        expected_sdk_sha256,
    )
    require(
        len(observations) == 1 and observations[0]["id"] == row["id"],
        "model did not produce one synthetic forward result",
    )
    return {
        "schema": SCHEMA,
        "arm": arm,
        "repository": catalog["repository"],
        "source_revision": catalog["revision"],
        "source_catalog_sha256": sha_file(catalog_path),
        "model_id": model["model_id"],
        "weights_sha256": weights,
        "physical_artifact_tree_sha256": physical["artifact_tree_sha256"],
        "installed_sdk_python_sha256": installed_sdk_sha,
        "device": device,
        "parameters": parameters,
        "runtime": runtime,
        "synthetic_observation": observations[0],
        "model_forward_executed": True,
        "synthetic_question_only": True,
        "actual_hepta_data_used": False,
        "target_host_independently_attested": False,
        "ndu_net_gain_verified": False,
        "production_evidence_verified": False,
        "ndu_selection_authorized": False,
        "promotion_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument(
        "--arm", choices=("laya", "typed", "multilingual"), required=True
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--sdk-python-sha256", required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        require(
            args.output.is_absolute() and not args.output.exists(),
            "forward receipt must be a fresh absolute file",
        )
        write_new(
            args.output,
            run_smoke(
                args.catalog,
                args.arm,
                args.artifact_dir,
                args.sdk_python_sha256,
                args.device,
            ),
        )
    except (InvalidTrial, ValueError, OSError, TypeError, KeyError, ImportError) as exc:
        parser.exit(2, f"blocked: {exc}\n")


if __name__ == "__main__":
    main()
