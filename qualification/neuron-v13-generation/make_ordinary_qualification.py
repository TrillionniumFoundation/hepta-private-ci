"""Pin a historical parent for a single real ordinary-CLI qualification.

This hashes inputs only. It never trains, runs a model, adopts a release, or
turns the historical source cut into current source-owner authority.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

import make_descriptor as common
import proposal_worker as protocol


ROOT = Path(__file__).resolve().parent
TASK = {
    "schema": "hepta.v13.task-input.v1",
    "text": (
        "For the incoming batch in this qualification run, sort these decimal strings "
        "by their numeric value, keeping duplicates."
    ),
    "payload": ["17.5", "-6.25", "17.5", "0.03125"],
}
EXPECTED_VALUE = ["-6.25", "0.03125", "17.5", "17.5"]
EXTRA_SOURCES = [
    "codex-rs/hepta-agentd/src/main.rs",
    "codex-rs/hepta-agentd/src/neuron_generation_process_bootstrap_files.rs",
    "codex-rs/hepta-agentd/src/neuron_v13_generation_process_bootstrap.rs",
    "codex-rs/hepta-agentd/tests/neuron_v13_generation_process_tests.rs",
    "codex-rs/hepta-agentd/tests/support/neuron_v13_generation.rs",
    "codex-rs/hepta-agentd/tests/support/neuron_v13_positive_input.rs",
    "codex-rs/hepta-agentd/tests/support/neuron_v13_positive_tests.rs",
    "qualification/neuron-v13-generation/make_ordinary_qualification.py",
    "qualification/neuron-v13-generation/test_ordinary_qualification.py",
]


def parent_closure(bootstrap):
    for key, value in {"phase": "bootstrap", "status": "completed"}.items():
        common.match(bootstrap[key], value, "original bootstrap was not completed")
    result = bootstrap["result"]
    common.match(result["engineering_passed"], True, "original bootstrap failed")
    common.match(result["epoch"], 1, "original parent epoch differs")
    receipt = result["closure"]
    for key, value in {
        "schema": "hepta.cell-learning.v13.content-binding.v1",
        "authority": "DENY_ALL",
        "verification_mode": "reference",
        "synthetic": False,
        "training_executed": False,
        "inference_executed": False,
        "adoption_performed": False,
    }.items():
        common.match(receipt[key], value, "unsupported parent content receipt")
    common.match(result["artifact"], receipt["release"]["artifact_id"], "parent differs")
    binding = {
        "kind": "resumable",
        **{
            name: common.array(receipt["member_sha256"][name])
            for name in protocol.LEARNING_MEMBERS
        },
    }
    common.match(binding, receipt["binding"], "parent learning binding differs")
    return receipt, {
        "checkpoint_digest": common.array(receipt["checkpoint"]["sha256"]),
        "state_digest": common.array(receipt["checkpoint"]["legacy_state_sha256"]),
        "encoder_digest": common.array(receipt["context"]["encoder_hash"]),
        "source_version": common.array(receipt["context"]["source_version"]),
        "data_identity": common.array(receipt["context"]["data_id"]),
        "learning": binding,
    }


def check_assets(receipt, assets):
    expected = {
        "model.npz": receipt["checkpoint"]["sha256"],
        "release.json": receipt["release"]["artifact_id"],
        "training.npz": receipt["training_data"]["artifact_sha256"],
        "sources.json": receipt["source"]["snapshot_sha256"],
        "encoder.json": receipt["encoder"]["manifest_file_sha256"],
        **{"vendor/" + name: digest for name, digest in protocol.SOURCE_HASHES.items()},
        **{
            "encoder/" + name: item["sha256"]
            for name, item in receipt["encoder"]["manifest"]["files"].items()
        },
    }
    actual = {asset["name"]: asset["sha256"] for asset in assets}
    catalog = set(protocol.expected_files("verify")) | set(protocol.expected_files("infer"))
    if (
        len(assets) != 24
        or len(expected) != 24
        or set(actual) != set(expected)
        or set(actual) != catalog
    ):
        raise ValueError("complete unique 24-asset closure is required")
    for name, digest in expected.items():
        common.match(
            actual[name], protocol.digest(digest), "parent asset pin differs: " + name
        )


def check_new_task(rows):
    protocol.validate_task(TASK)
    if (
        not isinstance(rows, list)
        or not rows
        or any(
            row["text"] == TASK["text"]
            or protocol.canonical(row["payload"]) == protocol.canonical(TASK["payload"])
            for row in rows
        )
    ):
        raise ValueError("fixed task text and payload must both be new to training rows")


def write_new(path, value):
    raw = protocol.canonical(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def assemble(arguments):
    original = arguments.historical_run.resolve(strict=True)
    bootstrap, bootstrap_file = common.document(
        original / "phase_results/bootstrap.json", 131072
    )
    common.match(
        bootstrap_file["sha256"],
        protocol.digest(arguments.bootstrap_sha256),
        "bootstrap pin differs",
    )
    receipt, closure = parent_closure(bootstrap)
    inputs = original / "inputs"
    rows, rows_file = common.document(inputs / "train_rows.json", 2 * 1024 * 1024)
    check_new_task(rows)
    release, _ = common.document(inputs / "parent/manifest.json", 131072)
    common.match(release, receipt["release"]["manifest"], "actual parent release differs")
    paths = {
        "model.npz": inputs / "parent/model.npz",
        "release.json": inputs / "parent/manifest.json",
        "sources.json": inputs / "parent-snapshot.json",
        "training.npz": inputs / "train_features.npz",
        "encoder.json": inputs / "encoder.json",
        **{"vendor/" + name: ROOT / "vendor" / name for name in protocol.SOURCE_HASHES},
        **{
            "encoder/" + name: arguments.encoder_root / name
            for name in protocol.ENCODER_SIZES
        },
    }
    limits = {**protocol.expected_files("verify"), **protocol.expected_files("infer")}
    assets = [
        {"name": name, **common.observed(path, limits[name])}
        for name, path in sorted(paths.items())
    ]
    check_assets(receipt, assets)
    argv0 = arguments.interpreter_argv0.absolute()
    interpreter = common.observed(argv0, 64 * 1024 * 1024)
    common.match(
        interpreter["sha256"],
        protocol.digest(arguments.interpreter_sha256),
        "interpreter pin differs",
    )
    worker = common.observed(ROOT / "proposal_worker.py", 65536)
    sources = [
        {"repo_path": name, **common.observed(ROOT.parent.parent / name, 131072)}
        for name in sorted(set(common.SOURCE_PATHS + EXTRA_SOURCES))
    ]
    sources.extend(
        {
            "repo_path": "qualification/neuron-v13-generation/" + item["name"],
            **{key: item[key] for key in ("path", "bytes", "sha256")},
        }
        for item in assets
        if item["name"].startswith("vendor/")
    )
    source_cut = [
        {key: item[key] for key in ("repo_path", "bytes", "sha256")}
        for item in sorted(sources, key=lambda item: item["repo_path"])
    ]
    source_digest = hashlib.sha256(
        b"hepta.v13.ordinary-qualification-source.v1\0" + protocol.canonical(source_cut)
    ).hexdigest()
    evolution = {
        "structure": common.array(
            hashlib.sha256(
                b"hepta.v13.original-structure.v1\0"
                + protocol.canonical({
                    "adapter": receipt["context"]["adapter_source_sha256"],
                    "config": receipt["context"]["config"],
                })
            ).hexdigest()
        ),
        "lineage": common.array(
            hashlib.sha256(
                b"hepta.v13.original-lineage.v1\0"
                + protocol.canonical({
                    "artifact": receipt["release"]["artifact_id"],
                    "parent": release["parent_artifact"],
                })
            ).hexdigest()
        ),
        "source_dependencies": closure["source_version"],
        "adoption_receipt": common.array(
            hashlib.sha256(
                b"hepta.v13.deny-all-parent-fixture.v1\0"
                + bytes.fromhex(bootstrap_file["sha256"])
            ).hexdigest()
        ),
    }
    def pinned(item):
        return {key: item[key] for key in ("path", "sha256")}

    descriptor = {
        "schema": "hepta.v13.ordinary-qualification.v1",
        "authority": "DENY_ALL",
        "interpreter_argv0": str(argv0),
        "interpreter": pinned(interpreter),
        "worker": pinned(worker),
        "assets": [{"name": asset["name"], **pinned(asset)} for asset in assets],
        "closure": closure,
        "source_digest": common.array(source_digest),
        "evolution": evolution,
        "historical_bootstrap": pinned(bootstrap_file),
        "task": TASK,
        "expected_skill": "sort_numeric",
        "expected_value": EXPECTED_VALUE,
    }
    observations = [bootstrap_file, rows_file, interpreter, worker, *assets, *sources]
    for item in observations:
        common.match(
            common.observed(Path(item["path"]), item["bytes"]),
            {key: item[key] for key in ("path", "bytes", "sha256")},
            "assembly input changed",
        )
    output = arguments.output_directory.absolute()
    output.mkdir(parents=False, exist_ok=False)
    digest = write_new(output / "qualification-input.json", descriptor)
    write_new(
        output / "ASSEMBLY.json",
        {
            "schema": "hepta.v13.ordinary-qualification-assembly.v1",
            "authority": "DENY_ALL",
            "input_sha256": digest,
            "observations": observations,
            "source_digest": source_digest,
            "source_catalog": source_cut,
            "source_catalog_is_full_compilation_closure": False,
            "historical_parent_fixture_only": True,
            "current_source_owner_checked": False,
            "live_adoption": False,
            "model_executed": False,
            "training_executed": False,
            "closure_revalidated": False,
            "statistical_quality_claim": False,
            "task_text_and_payload_absent_from_training_rows": True,
            "original_training_rows": len(rows),
            "expected_runtime": receipt["runtime"],
            "expected_packages": receipt["encoder"]["manifest"]["packages"],
            "note": "Real worker validation and the explicitly selected ignored native test are still required.",
        },
    )
    return {
        "input": str(output / "qualification-input.json"),
        "sha256": digest,
        "assets": len(assets),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("historical-run", "encoder-root", "interpreter-argv0", "output-directory"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("bootstrap-sha256", "interpreter-sha256"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(assemble(parser.parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
