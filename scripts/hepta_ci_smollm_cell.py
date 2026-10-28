"""Bind the original Cell replica experiment to the original Hepta model inputs.

This module neither loads a model nor grants installation or FinalUse authority.
Both generations must cross actual publisher/replica/consumer processes. The
original native Hepta owners consume only the resulting pinned consumer bytes.
"""

import importlib
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

if __package__:
    from .hepta_ci_smollm_common import (
        DENIED,
        parent,
        read,
        require,
        run_context,
        save,
        sha,
        source_pair,
    )
else:
    from hepta_ci_smollm_common import (
        DENIED,
        parent,
        read,
        require,
        run_context,
        save,
        sha,
        source_pair,
    )


def transport_module(chain):
    module = importlib.import_module("run_smollm_cell_replica_research")
    require(
        Path(module.__file__).resolve()
        == chain / "scripts/run_smollm_cell_replica_research.py",
        "foreign Cell transport implementation",
    )
    return module


def positive(value):
    return type(value) is int and value > 0


def acquisition_counts(value, release, connections, response_bytes):
    for key in ("cells", "payload_bytes", "chunks"):
        require(positive(release[key]), "invalid declared Cell release denominator")
        require(positive(value[key]), "invalid actual Cell acquisition denominator")
    for key in ("release", "cells", "payload_bytes", "chunks"):
        require(value[key] == release[key], "Cell acquisition omitted a dependency")
    require(
        type(value["cached_chunks"]) is int and value["cached_chunks"] == 0,
        "fresh consumer cannot reuse a preexisting cache",
    )
    require(
        type(value["downloaded_chunks"]) is int
        and value["downloaded_chunks"] == release["chunks"],
        "all declared chunks must actually cross the network",
    )
    require(
        positive(value["connection_attempts"])
        and value["connection_attempts"] <= connections
        and positive(value["received_response_bytes"])
        and value["received_response_bytes"] <= response_bytes,
        "Cell transfer exceeded or omitted its original network accounting",
    )


def relocated_parent(original, acquired, directory):
    require(
        acquired == dict(original, directory=str(directory)),
        "Cell acquisition may relocate only the directory, never the model identity",
    )


def observation(directory, original_path, materials, family, inherited):
    report_path = directory / "transport-report.json"
    report = read(report_path)
    original = read(original_path)
    require(
        report["scope"]
        == "one-host-controlled-native-TCL4-complete-model-and-LoRA-replica",
        "foreign Cell observation scope",
    )
    for key in (
        "original_hepta_installed",
        "hepta_final_use",
        "independent_operators",
        "pq_authenticated_transport",
    ):
        require(report[key] is False, "transport cannot grant application authority")
    require(
        report["authority"] == inherited.NO_AUTHORITY
        and all(value is False for value in report["authority"].values()),
        "Cell transport authority changed",
    )
    expected = {
        "base/" + name: (materials / name, directory / "consumer-materials" / name)
        for name in sorted(family["material_pins"]["files"])
    }
    expected["base/material-manifest.json"] = (
        materials / "material-manifest.json",
        directory / "consumer-materials/material-manifest.json",
    )
    for name in (
        "target-contract.json",
        "wrapped-adapter.json",
        "artifact.safetensors",
    ):
        expected["adapter/" + name] = (
            Path(original["directory"]) / name,
            directory / "consumer-parent" / name,
        )
    members = report["members"]
    require(
        type(members) is list
        and len(members) == len(expected)
        and {member["name"] for member in members} == set(expected),
        "missing, duplicate or additional model dependency",
    )
    payload_bytes, chunks = 0, 0
    for member in members:
        source, destination = expected[member["name"]]
        require(
            member["source"] == str(source)
            and member["destination"] == str(destination),
            "Cell dependency path changed",
        )
        packed, materialized = member["pack"], member["materialization"]
        require(
            positive(packed["bytes"])
            and positive(packed["chunks"])
            and packed["bytes"] == source.stat().st_size == destination.stat().st_size
            and packed["payload_sha256"] == sha(source) == sha(destination),
            "retrieved model bytes differ from the retained original bytes",
        )
        require(
            all(
                type(materialized[key]) is int and materialized[key] == 0
                for key in (
                    "downloaded_chunks",
                    "connection_attempts",
                    "received_response_bytes",
                )
            )
            and type(materialized["cached_chunks"]) is int
            and materialized["cached_chunks"] == packed["chunks"],
            "materialization must use only the verified consumer cache",
        )
        payload_bytes += packed["bytes"]
        chunks += packed["chunks"]
    release = report["release"]
    require(
        release["cells"] == len(expected)
        and release["payload_bytes"] == payload_bytes
        and release["chunks"] == chunks,
        "Cell release denominator differs from its complete member set",
    )
    connections = 2 * (chunks + len(expected))
    response_bytes = 2 * payload_bytes + len(expected) * 1_048_576 + 9 * connections
    require(
        report["connection_budget"] == connections
        and report["response_byte_budget"] == response_bytes,
        "original Cell transfer budget changed",
    )
    for name in ("replica_acquisition", "consumer_acquisition"):
        acquisition_counts(report[name], release, connections, response_bytes)
    for name in ("publisher", "replica"):
        process = read(directory / (name + "-process.json"))
        require(
            process == report[name]
            and positive(process["pid"])
            and process["stopped"] is True
            and type(process["returncode"]) is int,
            "actual Cell peer must have terminated before model execution",
        )
    negative = report["offline_publisher_negative"]
    negative_command = read(directory / "offline-publisher-negative-command.json")
    require(
        type(negative["returncode"]) is int
        and negative["returncode"] != 0
        and negative["returncode"] == negative_command["returncode"]
        and negative["no_completion_file"] is True
        and not (directory / "offline-publisher-negative.tcr1").exists()
        and negative_command["argv"][negative_command["argv"].index("--peers") + 1]
        == report["publisher"]["address"],
        "actual stopped publisher refusal is missing",
    )
    completion = directory / "source-release.tcr1"
    require(
        report["release_sha256"]
        == sha(completion)
        == sha(directory / "publisher-to-replica.tcr1")
        == sha(directory / "replica-to-consumer.tcr1"),
        "Cell completion markers differ from the original full release",
    )
    descriptor = directory / "consumer-parent/parent-material.json"
    relocated_parent(original, read(descriptor), descriptor.parent)
    inherited.read_parent(read(descriptor))
    require(
        report["all_model_dependencies_rehashed"] is True
        and report["parent_sha256"] == sha(descriptor)
        and report["consumer_parent"] == str(descriptor)
        and report["consumer_materials"] == str(directory / "consumer-materials"),
        "Cell report does not bind the consumed model",
    )
    raw = sorted(
        path
        for path in directory.iterdir()
        if path.name.endswith(("-command.json", "-process.json", ".log", ".tcr1"))
    )
    return {
        "source_parent_sha256": sha(original_path),
        "consumer_parent_sha256": sha(descriptor),
        "transport_report_sha256": sha(report_path),
        "release_sha256": sha(completion),
        "payload_bytes": payload_bytes,
        "chunks": chunks,
        "cells": len(expected),
        "raw_files": {path.name: sha(path) for path in raw},
    }


def acquire(chain, output, materials, runtime, inherited):
    binary = Path(os.environ["HEPTA_PON_CELL_BINARY"])
    digest = os.environ["HEPTA_PON_CELL_SHA256"]
    require(
        binary.is_absolute() and os.access(binary, os.X_OK),
        "native Cell binary required",
    )
    require(sha(binary) == digest, "native Cell binary differs from retained build")
    module = transport_module(chain)
    pair = source_pair(chain)
    save(
        output / "cell-precommit.json",
        {
            "schema": "hepta-cell-smollm-acquisition-v1",
            "source_pair": pair,
            "run_context": run_context(),
            "binary": str(binary),
            "binary_sha256": digest,
            "transport_source_sha256": sha(Path(module.__file__)),
            "planned_generations": [2, 3],
            "experiment_retries": 0,
            "independent_operators": False,
            **dict.fromkeys(DENIED, False),
        },
    )
    family = runtime.verify_family(runtime.read_json(runtime.FAMILY_PATH))
    records = {}
    for generation in (2, 3):
        original_path, original = parent(output, generation, inherited)
        directory = output / f"cell-gen{generation}"
        started = time.monotonic()
        try:
            module.transport(
                SimpleNamespace(materials=materials, cell_bin=binary),
                original,
                directory,
            )
        except (subprocess.SubprocessError, OSError, ValueError) as error:
            failure = {
                "status": "failed",
                "generation": generation,
                "completed_generations": sorted(records),
                "planned_generations": [2, 3],
                "elapsed_seconds": time.monotonic() - started,
                "error_type": type(error).__name__,
                "error": str(error),
                "adoption": "no-update",
                **dict.fromkeys(DENIED, False),
            }
            if isinstance(error, subprocess.TimeoutExpired):
                failure.update(
                    command=[str(part) for part in error.cmd], timeout=error.timeout
                )
                for stream in ("stdout", "stderr"):
                    raw = getattr(error, stream) or b""
                    if isinstance(raw, str):
                        raw = raw.encode()
                    path = output / ("cell-timeout-" + stream + ".log")
                    with path.open("xb") as retained:
                        retained.write(raw)
                    failure[stream + "_sha256"] = sha(path)
            save(output / "cell-failure.json", failure)
            raise
        records[str(generation)] = observation(
            directory,
            original_path,
            materials,
            family,
            inherited,
        )
        require(sha(binary) == digest, "Cell binary changed during acquisition")
        require(source_pair(chain) == pair, "source pair changed during acquisition")
    save(output / "cell-acquired.json", {"generations": records})
    return verify_acquisition(chain, output, materials, runtime, inherited)


def verify_acquisition(chain, output, materials, runtime, inherited):
    precommit = read(output / "cell-precommit.json")
    require(
        precommit["schema"] == "hepta-cell-smollm-acquisition-v1"
        and precommit["source_pair"] == source_pair(chain)
        and precommit["run_context"] == run_context()
        and precommit["planned_generations"] == [2, 3]
        and type(precommit["experiment_retries"]) is int
        and precommit["experiment_retries"] == 0
        and precommit["independent_operators"] is False
        and all(precommit[key] is False for key in DENIED),
        "Cell experiment identity, denominator or authority changed",
    )
    require(
        precommit["binary"] == os.environ["HEPTA_PON_CELL_BINARY"]
        and precommit["binary_sha256"]
        == os.environ["HEPTA_PON_CELL_SHA256"]
        == sha(Path(precommit["binary"]))
        and precommit["transport_source_sha256"]
        == sha(chain / "scripts/run_smollm_cell_replica_research.py"),
        "Cell source or native binary changed",
    )
    acquired = read(output / "cell-acquired.json")["generations"]
    require(set(acquired) == {"2", "3"}, "both actual model generations are required")
    family = runtime.verify_family(runtime.read_json(runtime.FAMILY_PATH))
    paths = {}
    for generation in (2, 3):
        original_path, _ = parent(output, generation, inherited)
        directory = output / f"cell-gen{generation}"
        require(
            acquired[str(generation)]
            == observation(
                directory,
                original_path,
                materials,
                family,
                inherited,
            ),
            "Cell observations changed after acquisition",
        )
        runtime.verify_materials(directory / "consumer-materials")
        paths[generation] = directory / "consumer-parent/parent-material.json"
    return paths, output / "cell-gen3/consumer-materials"
