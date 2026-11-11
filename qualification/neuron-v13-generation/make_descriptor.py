"""Assemble host-pinned acceptance inputs without running a model or an owner.

The named content receipt supplies expected learning digests. The real worker
revalidates that closure before every inference; this assembler grants no trust
or adoption and does not manufacture a checkpoint, label or optimizer state.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

import proposal_worker as protocol


ROOT = Path(__file__).resolve().parent
SOURCE_PATHS = [
    "codex-rs/hepta-agentd/BUILD.bazel",
    "codex-rs/hepta-agentd/v13_acceptance.bzl",
    "codex-rs/hepta-agentd/examples/neuron_v13_acceptance.rs",
    "codex-rs/hepta-agentd/examples/neuron_v13_acceptance/descriptor.rs",
    "codex-rs/hepta-agentd/examples/neuron_v13_acceptance/lifecycle.rs",
    "codex-rs/hepta-agentd/examples/neuron_v13_acceptance/observations.rs",
    "codex-rs/hepta-agentd/examples/neuron_v13_acceptance/runner.rs",
    "codex-rs/hepta-agentd/src/lib.rs",
    "codex-rs/hepta-agentd/src/runtime.rs",
    "codex-rs/hepta-agentd/src/neuron_generation_process_bootstrap.rs",
    "codex-rs/hepta-agentd/src/neuron_v13_generation_bootstrap.rs",
    "codex-rs/hepta-agentd/src/neuron_v13_generation_bootstrap_tests.rs",
    "codex-rs/hepta-agentd/src/neuron_v13_generation_bootstrap_test_support.rs",
    "codex-rs/hepta-neuron/BUILD.bazel",
    "codex-rs/hepta-neuron/src/lib.rs",
    "codex-rs/hepta-neuron/src/cell_v13_assets.rs",
    "codex-rs/hepta-neuron/src/cell_v13_generation.rs",
    "codex-rs/hepta-neuron/src/cell_v13_process.rs",
    "codex-rs/hepta-neuron/src/cell_v13_process_tests.rs",
    "codex-rs/hepta-neuron/src/cell_v13_protocol.rs",
    "qualification/neuron-v13-generation/proposal_worker.py",
    "qualification/neuron-v13-generation/make_descriptor.py",
    "qualification/neuron-v13-generation/test_proposal_worker.py",
    "qualification/neuron-v13-generation/BUILD.bazel",
    "qualification/neuron-v13-generation/VENDOR.json",
]


def observed(path, maximum):
    path = path.resolve(strict=True)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ValueError("input is not a bounded regular file")
        digest, size = hashlib.sha256(), 0
        while block := stream.read(65536):
            size += len(block)
            if size > maximum:
                raise ValueError("input grew beyond its bound")
            digest.update(block)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if size != before.st_size or any(
        getattr(before, key) != getattr(after, key) for key in fields
    ):
        raise ValueError("input changed while hashing")
    return {"path": str(path), "bytes": size, "sha256": digest.hexdigest()}


def document(path, maximum):
    observation = observed(path, maximum)
    raw = Path(observation["path"]).read_bytes()
    if (
        len(raw) != observation["bytes"]
        or hashlib.sha256(raw).hexdigest() != observation["sha256"]
    ):
        raise ValueError("document changed while reading")
    return protocol.strict_json(raw), observation


def array(value):
    return list(bytes.fromhex(protocol.digest(value)))


def match(actual, expected, reason):
    if protocol.canonical(actual) != protocol.canonical(expected):
        raise ValueError(reason)


def assemble(arguments):
    receipt, receipt_file = document(arguments.closure_receipt, 131072)
    match(
        receipt_file["sha256"],
        protocol.digest(arguments.closure_sha256),
        "content receipt pin differs",
    )
    for key, value in {
        "schema": "hepta.cell-learning.v13.content-binding.v1",
        "authority": "DENY_ALL",
        "verification_mode": "reference",
        "synthetic": False,
        "training_executed": False,
        "inference_executed": False,
        "adoption_performed": False,
    }.items():
        match(receipt[key], value, "unsupported content receipt")
    binding = {
        "kind": "resumable",
        **{
            name: array(receipt["member_sha256"][name])
            for name in protocol.LEARNING_MEMBERS
        },
    }
    match(binding, receipt["binding"], "learning member digests differ from binding")
    closure = {
        "checkpoint_digest": array(receipt["checkpoint"]["sha256"]),
        "state_digest": array(receipt["checkpoint"]["legacy_state_sha256"]),
        "encoder_digest": array(receipt["context"]["encoder_hash"]),
        "source_version": array(receipt["context"]["source_version"]),
        "data_identity": array(receipt["context"]["data_id"]),
        "learning": binding,
    }
    task, task_file = document(arguments.task_file, protocol.MAX_TASK)
    protocol.validate_task(task)
    original = arguments.original_root.resolve(strict=True)
    rows, rows_file = document(original / "train_rows.json", 2 * 1024 * 1024)
    if (
        not isinstance(rows, list)
        or not rows
        or any(
            row["text"] == task["text"]
            or protocol.canonical(row["payload"]) == protocol.canonical(task["payload"])
            for row in rows
        )
    ):
        raise ValueError(
            "acceptance requires text and payload distinct from original training rows"
        )
    named_paths = {
        "model.npz": original / "model.npz",
        "release.json": original / "release-manifest.json",
        "training.npz": original / "train_features.npz",
        "sources.json": arguments.source_snapshot,
        "encoder.json": arguments.encoder_manifest,
    }
    named_paths.update(
        {"vendor/" + name: ROOT / "vendor" / name for name in protocol.SOURCE_HASHES}
    )
    named_paths.update(
        {
            "encoder/" + name: arguments.encoder_root / name
            for name in protocol.ENCODER_SIZES
        }
    )
    limits = {**protocol.expected_files("verify"), **protocol.expected_files("infer")}
    assets = [
        {"name": name, **observed(path, limits[name])}
        for name, path in sorted(named_paths.items())
    ]
    by_name = {asset["name"]: asset for asset in assets}
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
    match(len(expected), 24, "receipt inventory differs")
    match(len(by_name), 24, "actual inventory differs")
    if set(expected) != set(by_name):
        raise ValueError("actual assets differ from complete closure inventory")
    for name, digest in expected.items():
        match(
            by_name[name]["sha256"],
            protocol.digest(digest),
            "asset digest differs from content receipt",
        )
    publication, publication_file = document(original / "CANDIDATE.json", 131072)
    release, _ = document(original / "release-manifest.json", 131072)
    match(
        release,
        receipt["release"]["manifest"],
        "actual release differs from content receipt",
    )
    for key, value in {
        "candidate_file_sha256": receipt["checkpoint"]["sha256"],
        "candidate_artifact": receipt["release"]["artifact_id"],
        "source_version": receipt["context"]["source_version"],
        "state_sha256": receipt["checkpoint"]["legacy_state_sha256"],
        "parent_artifact": release["parent_artifact"],
        "publication": {"epoch": 1, "status": "published"},
    }.items():
        match(
            publication[key],
            value,
            "historical publication differs from content receipt",
        )
    match(
        publication["active_release"]["artifact"],
        receipt["release"]["artifact_id"],
        "historical release differs",
    )
    repository = ROOT.parent.parent
    sources = [
        {"repo_path": name, **observed(repository / name, 131072)}
        for name in SOURCE_PATHS
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
        for item in sorted(sources, key=lambda value: value["repo_path"])
    ]
    source_digest = hashlib.sha256(
        b"hepta.v13.proposal-source.v1\0" + protocol.canonical(source_cut)
    ).hexdigest()
    structure = hashlib.sha256(
        b"hepta.v13.original-structure.v1\0"
        + protocol.canonical(
            {
                "adapter": receipt["context"]["adapter_source_sha256"],
                "config": receipt["context"]["config"],
            }
        )
    ).hexdigest()
    lineage = hashlib.sha256(
        b"hepta.v13.original-lineage.v1\0"
        + protocol.canonical(
            {
                "artifact": receipt["release"]["artifact_id"],
                "parent": release["parent_artifact"],
            }
        )
    ).hexdigest()
    argv0 = arguments.interpreter_argv0.absolute()
    interpreter = observed(argv0, 64 * 1024 * 1024)
    worker = observed(ROOT / "proposal_worker.py", 65536)
    descriptor = {
        "schema": "hepta.v13.owner-acceptance.v1",
        "authority": "DENY_ALL",
        "interpreter_argv0": str(argv0),
        "interpreter": {key: interpreter[key] for key in ("path", "sha256")},
        "worker": {key: worker[key] for key in ("path", "sha256")},
        "assets": [
            {key: asset[key] for key in ("name", "path", "sha256")} for asset in assets
        ],
        "closure": closure,
        "source_digest": array(source_digest),
        "evolution": {
            "structure": array(structure),
            "lineage": array(lineage),
            "source_dependencies": closure["source_version"],
            "adoption_receipt": array(publication_file["sha256"]),
        },
        "historical_publication": {
            key: publication_file[key] for key in ("path", "sha256")
        },
        "task": task,
    }
    inputs = [
        receipt_file,
        task_file,
        rows_file,
        publication_file,
        interpreter,
        worker,
        *assets,
        *sources,
    ]
    for item in inputs:
        match(
            observed(Path(item["path"]), item["bytes"]),
            {key: item[key] for key in ("path", "bytes", "sha256")},
            "assembly input changed",
        )
    output = arguments.output_directory.absolute()
    output.mkdir(parents=False, exist_ok=False)
    raw = protocol.canonical(descriptor) + b"\n"
    with (output / "descriptor.json").open("xb") as stream:
        stream.write(raw)
    record = {
        "schema": "hepta.v13.acceptance-assembly.v1",
        "authority": "DENY_ALL",
        "descriptor_sha256": hashlib.sha256(raw).hexdigest(),
        "inputs": inputs,
        "source_digest": source_digest,
        "source_catalog": source_cut,
        "historical_publication_only": True,
        "current_adoption_performed": False,
        "model_executed": False,
        "training_executed": False,
        "closure_revalidated": False,
        "task_text_and_payload_absent_from_training_rows": True,
        "original_training_rows": len(rows),
        "note": "The worker must revalidate the complete closure; source receipt is an input, not admission.",
    }
    with (output / "ASSEMBLY.json").open("xb") as stream:
        stream.write(json.dumps(record, indent=2, sort_keys=True).encode() + b"\n")
    return {
        "descriptor": str(output / "descriptor.json"),
        "sha256": record["descriptor_sha256"],
        "assets": len(assets),
        "authority": "DENY_ALL",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "closure-receipt",
        "original-root",
        "encoder-root",
        "source-snapshot",
        "encoder-manifest",
        "interpreter-argv0",
        "task-file",
        "output-directory",
    ):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--closure-sha256", required=True)
    print(json.dumps(assemble(parser.parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
