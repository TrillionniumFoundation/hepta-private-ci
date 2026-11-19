#!/usr/bin/env python3
"""Recover the published historical Joint descendant; never train or resave it."""

import argparse
from contextlib import contextmanager
import hashlib
import importlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tempfile
import time


SOURCE_SHA = "18dac3ccd30317893ad922792c12400390522f00"
SOURCE_ROOT = "experiments/multimodal_output_portfolio/joint_hepta_20261029"
BUNDLE = SOURCE_ROOT + "/v3/packaging/bundles/open_text_final_20261030"
INDEX_SHA256 = "a2fb1dc26e84eaa99bd0857dea7e2290ed069e4dba5e940430b6bb06315d5f80"
ARCHIVE_SHA256 = "5ce3179ad1cbab559659eb2f36265dc3071af071ee6cfb27dd5f9640e38693dd"
CHECKPOINT_SHA256 = "33c1aa759bddb5e9b33b906e1796de7a6f89e5b5916711f99033584b3cbafb97"
PARENT_SHA256 = "9032b0750ea07c9ad5f9d0fb657d0ce16fd67ccacde1a653908207cbfdb542dc"
PUBLIC_SHA256 = "86c55417fdf2abdd065fc9828c40260aed0ded4a0d607c551e15b2f6b5fd2c00"
SOURCES = ("model.py", "hepta_core.py", "mechanism_data.py", "v3/model.py",
           "v3/native_bridge.py", "v3/open_domain.py")
CHUNK_BYTES = 393_216


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git_bytes(repository, path):
    return subprocess.check_output(["git", "-C", str(repository), "show", f"{SOURCE_SHA}:{path}"])


def checked(data, expected, size=None):
    if digest(data) != expected or (size is not None and len(data) != size):
        raise ValueError("Historical byte identity mismatch")
    return data


def recover_archive(repository):
    index_raw = checked(git_bytes(repository, BUNDLE + "/INDEX.json"), INDEX_SHA256)
    index = json.loads(index_raw)
    if index["chunk_count"] != 8 or index["archive_sha256"] != ARCHIVE_SHA256:
        raise ValueError("Unexpected historical archive inventory")
    chunks, archive = [], bytearray()
    for page in index["chunk_pages"]:
        raw = checked(git_bytes(repository, BUNDLE + "/" + page["path"]), page["sha256"], page["size"])
        chunks.extend(json.loads(raw)["chunks"])
    for chunk in chunks:
        if chunk["offset"] != len(archive) or chunk["size"] > CHUNK_BYTES:
            raise ValueError("Noncontiguous historical chunks")
        archive.extend(checked(git_bytes(repository, BUNDLE + "/" + chunk["path"]),
                               chunk["sha256"], chunk["size"]))
    checked(archive, ARCHIVE_SHA256, index["archive_bytes"])
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as handle:
        manifest = checked(handle.extractfile(".evidence-manifest.json").read(),
                           index["manifest"]["sha256"], index["manifest"]["size"])
        entries = json.loads(manifest)["entries"]
        if any(entry["type"] != "file" or "/" in entry["path"] for entry in entries):
            raise ValueError("Unexpected historical member type/path")
        expected = {".evidence-manifest.json", "payload", *("payload/" + e["path"] for e in entries)}
        if {member.name.rstrip("/") for member in handle.getmembers()} != expected:
            raise ValueError("Unexpected or omitted archive members")
        for entry in entries:
            files[entry["path"]] = checked(handle.extractfile("payload/" + entry["path"]).read(),
                                           entry["sha256"], entry["size"])
    checked(files["adapter.pt"], CHECKPOINT_SHA256, 3_156_046)
    return files, index


@contextmanager
def donor_modules(repository):
    """Import unchanged pinned source in an isolated package, without run()."""
    with tempfile.TemporaryDirectory(prefix="hepta-joint-donor-") as temporary:
        root = Path(temporary)
        package = root / "historical_joint"
        (package / "v3").mkdir(parents=True)
        (package / "__init__.py").write_bytes(b"")
        (package / "v3/__init__.py").write_bytes(b"")
        hashes = {}
        for name in SOURCES:
            data = git_bytes(repository, SOURCE_ROOT + "/" + name)
            (package / name).write_bytes(data)
            hashes[name] = digest(data)
        sys.path.insert(0, str(root))
        try:
            yield {
                "model": importlib.import_module("historical_joint.v3.model"),
                "parent": importlib.import_module("historical_joint.model"),
                "data": importlib.import_module("historical_joint.mechanism_data"),
                "bridge": importlib.import_module("historical_joint.v3.native_bridge"),
                "hashes": hashes,
            }
        finally:
            sys.path.remove(str(root))
            for name in list(sys.modules):
                if name == "historical_joint" or name.startswith("historical_joint."):
                    del sys.modules[name]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", required=True, type=Path)
    parser.add_argument("--work-directory", required=True, type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    import torch

    torch.set_num_threads(1)
    args.work_directory.mkdir(parents=True, exist_ok=False)
    files, index = recover_archive(args.source_repository)
    (args.work_directory / "adapter.pt").write_bytes(files["adapter.pt"])
    report, protocol = (json.loads(files[name]) for name in ("report.json", "protocol.json"))
    payload = torch.load(io.BytesIO(files["adapter.pt"]), map_location="cpu", weights_only=True)
    expected_config = {"width": 32, "depth": 1, "mode": "dual", "boundary": "direct", "verify_mode": "allow"}
    if payload["config"] != expected_config or report["base_checkpoint_sha256"] != PARENT_SHA256:
        raise ValueError("Historical model or parent identity differs")
    if protocol["updates"] != 16 or len(report["losses"]) != 16:
        raise ValueError("Historical update receipt differs")
    state = payload["state_dict"]
    if len(state) != 67 or sum(value.numel() for value in state.values()) != 596_985:
        raise ValueError("Historical complete Joint state inventory differs")
    if not all(torch.isfinite(value).all().item() for value in state.values()):
        raise ValueError("Nonfinite historical parameter")
    with donor_modules(args.source_repository) as donor:
        for name, expected in protocol["source_files"].items():
            if donor["hashes"][name] != expected:
                raise ValueError("Training protocol source identity differs")
        tensor_digest = donor["parent"].tensor_digest
        if tensor_digest(state) != report["final_hepta_sha256"]:
            raise ValueError("Complete Joint tensor digest differs")
        if tensor_digest(payload["prefix_state_dict"]) != report["final_prefix_sha256"]:
            raise ValueError("Historical prefix tensor digest differs")
        model = donor["model"].JointGenerator(**payload["config"]).eval()
        model.load_state_dict(state, strict=True)
        public, _ = donor["data"].batch([3], "v3-native-implementation")
        weights_path, public_path, export = donor["bridge"].export_model(
            model, public, args.work_directory / "export")
        if tensor_digest(model.state_dict()) != report["final_hepta_sha256"]:
            raise ValueError("Export mutated the recovered model")
        weights, public_bytes = weights_path.read_bytes(), public_path.read_bytes()
        checked(public_bytes, PUBLIC_SHA256)
        source_hashes = donor["hashes"]
    repository = Path(__file__).resolve().parents[2]
    fixtures = repository / "codex-rs/hepta-neuron/tests/fixtures"
    chunks = []
    for offset in range(0, len(weights), CHUNK_BYTES):
        data = weights[offset:offset + CHUNK_BYTES]
        name = f"joint-trained-weights-{len(chunks):03}.bin"
        (fixtures / name).write_bytes(data)
        chunks.append({"path": name, "offset": offset, "bytes": len(data), "sha256": digest(data)})
    (fixtures / "joint-trained-public.hps").write_bytes(public_bytes)
    manifest = {
        "schema": "hepta.historical-joint-descendant-fixture.v1", "synthetic_weights": False,
        "source_sha": SOURCE_SHA, "source_root": SOURCE_ROOT, "source_files": source_hashes,
        "archive": {"path": BUNDLE, "index_sha256": INDEX_SHA256, "sha256": ARCHIVE_SHA256,
                    "bytes": index["archive_bytes"], "chunks": 8},
        "checkpoint": {"sha256": CHECKPOINT_SHA256, "bytes": len(files["adapter.pt"]),
                       "parent_sha256_from_training_receipt": PARENT_SHA256,
                       "parent_bytes_recovered": False, "historical_updates": 16,
                       "new_training_updates": 0, "training_resume_qualified": False,
                       "joint_tensor_sha256": report["final_hepta_sha256"],
                       "prefix_tensor_sha256": report["final_prefix_sha256"]},
        "export": export, "weight_chunks": chunks,
        "public": {"path": "joint-trained-public.hps", "bytes": len(public_bytes),
                   "sha256": digest(public_bytes), "generator": "mechanism_data.batch",
                   "ids": [3], "split": "v3-native-implementation",
                   "scope": "Exact historical synthetic mechanism input; no natural-task evidence."},
        "historical_receipts": {name: digest(files[name]) for name in ("report.json", "protocol.json")},
        "historical_fixed_fact_passes": report["fixed_fact_passes_by_arm"],
        "qualification": "Asset recovery only. Agentd lifecycle and actual helper numeric results are separate evidence.",
        "excluded": ["Original parent byte recovery", "Optimizer resume", "Frozen LM/prefix execution",
                     "Natural multimodal quality", "Adoption benefit", "Complete historical training cost"],
    }
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    (fixtures / "joint-trained-v1.json").write_bytes(encoded)
    destination = Path(__file__).resolve().parent
    for name in ("report.json", "protocol.json"):
        (destination / ("historical-" + name)).write_bytes(files[name])
    receipt = {"schema": "hepta.joint-trained-recovery.v1", "status": "recovered_verified_exported",
               "fixture_manifest_sha256": digest(encoded), "checkpoint_sha256": CHECKPOINT_SHA256,
               "python": platform.python_version(), "torch": str(torch.__version__),
               "new_training_updates": 0, "wall_seconds": time.perf_counter() - started,
               "process_cpu_seconds": time.process_time() - cpu,
               "scope": "Historical archive read/hash/decode, strict tensor load and same-source export; no inference or training."}
    (destination / "RECOVERY.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"fixture": manifest, "recovery": receipt}))


if __name__ == "__main__":
    main()
