"""Portable preparation/training for the bounded native-entrypoint development run.

This imports already retrieved GitHub evidence. It does not authenticate current
GitHub permissions, establish unseen-data generalization, or qualify production.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_backend import canonical, file_sha, inspect


def retain(path, value):
    data = (
        value
        if isinstance(value, bytes)
        else json.dumps(
            value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        ).encode()
        + b"\n"
    )
    with Path(path).open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def prepare(args):
    root = Path(args.out).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    with tarfile.open(args.archive) as archive:
        data = archive.extractfile("producer/dataset.json").read()
        if hashlib.sha256(data).hexdigest() != args.dataset_sha256:
            raise ValueError("retained dataset bytes differ from explicit pin")
        dataset = json.loads(data)
        selected = [c for c in dataset["cases"] if c["id"] == args.case_id]
        if len(selected) != 1:
            raise ValueError("exact case required")
        case = selected[0]
        for member in archive.getmembers():
            if not member.name.startswith(("producer/", "inputs/ci-incidents/")):
                continue
            path = Path(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not member.isfile()
                or member.size > 4 * 1024 * 1024
            ):
                raise ValueError("bounded regular evidence member required")
            destination = root / "imported" / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            retain(destination, archive.extractfile(member).read())
    for digest, size in dataset["source_inventory"].items():
        path = root / "imported/producer/evidence" / digest
        if path.stat().st_size != size or file_sha(path) != digest:
            raise ValueError("actual imported source evidence differs")
    commit_path = f"imported/inputs/ci-incidents/commit-{case['fixed_commit']}.json"
    commit = json.loads((root / commit_path).read_text())
    if (
        commit["sha"] != case["fixed_commit"]
        or file_sha(root / commit_path) != case["commit_evidence_sha256"]
    ):
        raise ValueError("actual fetched commit differs from producer binding")
    document = {
        "schemaVersion": 1,
        "key": {"role": "procedural", "entity": case["symptom"], "relation": "repair"},
        "value": case["repair_id"],
    }
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    retain(root / "source_document.json", raw)
    retain(
        root / "read_query.json",
        {
            "question": f"What is the {document['key']['relation']} for {document['key']['entity']}?",
            "source_root": hashlib.sha256(raw).hexdigest(),
        },
    )
    retain(
        root / "source_mapping.json",
        {
            "schema": "hepta.memory-cell.native-source-import.v1",
            "case": case,
            "typed_source_sha256": hashlib.sha256(raw).hexdigest(),
            "producer_dataset_sha256": args.dataset_sha256,
            "producer_manifest_sha256": dataset["manifest_sha256"],
            "archive_sha256": file_sha(args.archive),
            "commit_tree": commit["commit"]["tree"]["sha"],
            "github_commit_receipt": commit_path,
            "github_manifest_receipt": "imported/inputs/ci-incidents/manifest.json",
            "github_failure_receipt": f"imported/inputs/ci-incidents/run-{case['failed_run_id']}.log",
            "github_success_receipt": f"imported/inputs/ci-incidents/run-{case['success_run_id']}.log",
            "source_id": "ci/" + case["source_digest"],
            "key_derivation": "procedural role + exact producer symptom + repair relation; server verifies equality",
            "github_permission_authentication": False,
            "native_import_authority": "explicit operator-selected content; external supervisor qualification not established",
        },
    )
    protocol = {
        "schema": "hepta.memory-cell.native-development-protocol.v1",
        "steps": 96,
        "rank": 8,
        "seed": 24031,
        "learning_rate": 0.01,
        "objective": "completion_ce",
        "scope": "native-hnmf-ci-development",
        "templates": ["What is the {relation} for {entity}?"],
        "decoder_queries": 3,
        "native_feature_forwards": 1,
        "read_arms": ["native-fixed-adapter", "research-base", "research-shuffled"],
        "previously_exposed_case": True,
        "confirmation": False,
        "production_qualification": False,
        "parameter_success_gate": None,
        "engineering_requirements": [
            "actual_runtime_run_and_control_socket",
            "owner_current_source",
            "typed_prompt_binding",
            "actual_NeuronModelPort_execution",
            "no_extra_dispatch_on_wrong_key_role_replay_forgery_correction_revocation",
            "model_and_source_receipts_retained",
        ],
    }
    retain(root / "protocol.json", protocol)
    print(
        json.dumps(
            {
                "prepared": str(root),
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "protocol_sha256": file_sha(root / "protocol.json"),
            }
        )
    )


def train(args):
    root = Path(args.run).resolve()
    protocol = json.loads((root / "protocol.json").read_text())
    raw = (root / "source_document.json").read_bytes()
    document = json.loads(raw)
    sys.path.insert(0, str(Path(args.repo).resolve() / "scripts/memory_cell"))
    import torch
    from parametric_model import SourceMemoryCell

    torch.set_num_threads(2)
    started = time.perf_counter()
    cell = SourceMemoryCell(args.model, rank=protocol["rank"], seed=protocol["seed"])
    cell.reset(protocol["scope"])
    fact = {
        "scope": protocol["scope"],
        "entity": document["key"]["entity"],
        "relation": document["key"]["relation"],
        "value": document["value"],
        "source_digest": hashlib.sha256(raw).hexdigest(),
    }
    receipt = cell.fit_sources(
        [fact],
        protocol["steps"],
        protocol["learning_rate"],
        protocol["templates"],
        objective=protocol["objective"],
    )
    manifest = cell.save(root / "checkpoint", receipt)
    retain(
        root / "training.json",
        {
            "receipt": receipt,
            "save": cell.last_save_receipt,
            "manifest_sha256": manifest,
            "wall_seconds": time.perf_counter() - started,
        },
    )
    print(json.dumps({"trained": True, "manifest_sha256": manifest}))


def configure(args):
    root = Path(args.run).resolve()
    protocol = json.loads((root / "protocol.json").read_text())
    pins, metadata = inspect(args.repo, args.model, root / "checkpoint")
    (root / "native-process-receipts").mkdir(mode=0o700)
    config = {
        "python": str(Path(sys.executable).absolute()),
        "repo": str(Path(args.repo).resolve()),
        "model": str(Path(args.model).resolve()),
        "checkpoint": str(root / "checkpoint"),
        "receipt_directory": str(root / "native-process-receipts"),
        "scope": protocol["scope"],
        "model_id": "memory-cell:smollm135m",
        "config_id": "memory-cell:native-ci-v1",
        "generation": 1,
        "rank": protocol["rank"],
        "seed": protocol["seed"],
        "output_width": 4,
        "timeout_millis": 120000,
        "pins": pins,
    }
    retain(root / "native_config.json", config)
    retain(root / "native_inspection.json", metadata)
    print(
        json.dumps(
            {
                "configured": True,
                "config_sha256": file_sha(root / "native_config.json"),
                "pins": pins,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--archive", required=True)
    p.add_argument("--dataset-sha256", required=True)
    p.add_argument("--case-id", required=True)
    p.add_argument("--out", required=True)
    for name in ("train", "configure"):
        p = commands.add_parser(name)
        p.add_argument("--run", required=True)
        p.add_argument("--repo", required=True)
        p.add_argument("--model", required=True)
    args = parser.parse_args()
    {"prepare": prepare, "train": train, "configure": configure}[args.command](args)


if __name__ == "__main__":
    main()
