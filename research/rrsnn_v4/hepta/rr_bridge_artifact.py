"""Freeze an explicitly selected parameter artifact for a feature-only bridge."""
import argparse
import hashlib
import platform
from pathlib import Path
import struct
import sys
import shutil

from rr_bridge_backend import HERE, WORKSPACE, canonical, digest, read, sha, write


def create(args):
    sys.path.insert(0, str(WORKSPACE))
    import numpy as np
    import torch
    from rrsnn_v4.models import RRPolicy
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    if args.development:
        if args.artifact is not None:
            raise ValueError("DevelopmentAndTrainedArtifactAreDistinct")
        torch.manual_seed(88219)
        model = RRPolicy()
        artifact = args.output.parent / "development-only-weights.pt"
        if artifact.exists():
            raise ValueError("DevelopmentArtifactAlreadyExists")
        torch.save({"state_dict": model.state_dict(), "variant": "rr_full", "metadata": model.metadata(),
                    "development_only": True}, artifact)
        training = selection = None
    else:
        if not all([args.artifact, args.training_receipt, args.selection, args.selection_pin]):
            raise ValueError("SelectedCompletedTrainingReceiptRequired")
        artifact = args.artifact.resolve()
        training = read(args.training_receipt)
        if (training.get("status") != "completed" or training.get("variant") != "rr_full"
                or training.get("seed") != 101 or training.get("checkpoint_sha256") != sha(artifact)):
            raise ValueError("CompletedFixedCandidateIdentityMismatch")
        if sha(args.selection) != args.selection_pin:
            raise ValueError("ExternalSelectionPinMismatch")
        if args.training_receipt.resolve() != artifact.with_name("training.json"):
            raise ValueError("TrainingReceiptPathMismatch")
        # These frozen helpers validate candidate membership, training receipt
        # pin, both protocol links and checkpoint run identity. They do not load
        # heldout tasks or call evaluate_checkpoint.
        from rrsnn_v4.evaluate import load_policy, validate_selection
        checked = validate_selection(artifact, args.selection, args.freeze)
        model, blob = load_policy(artifact, checked["training_protocol_sha256"])
        if blob["variant"] != "rr_full" or blob["seed"] != 101:
            raise ValueError("FixedCandidateRunIdentityMismatch")
        selection = {"path": str(args.selection.resolve()), "sha256": args.selection_pin,
                     "pre_data_freeze_sha256": sha(args.freeze),
                     "training_protocol_sha256": checked["training_protocol_sha256"]}
    model.eval()
    tensor_hash = hashlib.sha256(b"rrsnn.v4.exact-tensor-state.v1\0")
    for name, tensor in sorted(model.state_dict().items()):
        array = tensor.detach().cpu().contiguous().numpy()
        header = canonical({"name": name, "dtype": array.dtype.str, "shape": list(array.shape)})
        data = array.tobytes()
        tensor_hash.update(struct.pack(">Q", len(header)) + header + struct.pack(">Q", len(data)) + data)
    sources = ["rrsnn_v4/models.py", "rrsnn_v4/operators.py", "rrsnn_v4/evaluate.py", "rrsnn_v4/__init__.py",
               "rrsnn_v4/hepta/rr_bridge_backend.py", "rrsnn_v4/hepta/rr_bridge_worker.py",
               "rrsnn_v4/hepta/rr_bridge_native/src/main.rs"]
    source_sha = {name: sha(WORKSPACE / name) for name in sources}
    export = {"output": "8 Q24 values from tanh(actual exponential RR spike trace)",
              "prediction": "8 zeros; no prediction-quality claim", "head81": "computed by RRPolicy.step but not routed",
              "scope": "separate research feature backend; native V1 sparse state remains distinct"}
    manifest = {"schema": "rrsnn.v4.research-feature-model-manifest.v1", "model_id": "research.rr-v4.feature8.seed101" if not args.development else "research.rr-v4.feature8.development",
        "artifact_path": str(artifact.resolve()), "artifact_sha256": sha(artifact),
        "weights_digest": tensor_hash.hexdigest(), "source_sha256": source_sha,
        "metadata": model.metadata(), "export": export, "development_only": args.development,
        "training_receipt_sha256": None if args.development else sha(args.training_receipt),
        "selection": selection, "torch_version": str(torch.__version__), "numpy_version": np.__version__,
        "native_binary_sha256": sha(args.native), "native_binary_path": str(args.native.resolve()),
        "python_executable_sha256": sha(sys.executable),
        "native_time_origin_micros": 1_000_000,
        "production_qualified": False, "production_cell": False, "dot_verified": False,
        "registered_production_model": False, "effect_authority": False}
    manifest["model_manifest_digest"] = digest({"metadata": manifest["metadata"], "export": export,
                                               "artifact_sha256": manifest["artifact_sha256"]})
    for field, value in {
        "encoder_digest": {"weights": manifest["weights_digest"], "RRPolicy": source_sha["rrsnn_v4/models.py"]},
        "head_digest": export, "tokenizer_digest": "numeric features; tokenizer not applicable",
        "preprocessor_digest": "explicit Q24/2^24 to float32 observation, host-bound dt and event mask",
        "quantization_digest": "float32 weights; float64 CTMC paths; nearest-even Q24 exported trace features",
        "normalization_digest": "bounded tanh actual spike trace; prediction zeros",
        "runtime_digest": {"python": sys.version, "torch": str(torch.__version__), "numpy": np.__version__,
                           "native_binary": sha(args.native), "source_sha256": source_sha},
        "device_digest": {"platform": platform.platform(), "machine": platform.machine(),
                          "cpu_identity_sha256": sha('/proc/cpuinfo'), "verified_dot": False},
    }.items():
        manifest[field] = digest(value)
    write(args.output, manifest)
    for name, expected in source_sha.items():
        destination = args.output.parent / "source_snapshot" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WORKSPACE / name, destination)
        if sha(destination) != expected:
            raise ValueError("SourceSnapshotIdentityChanged")
    return {"manifest_sha256": sha(args.output), "artifact_sha256": manifest["artifact_sha256"],
            "development_only": args.development}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--training-receipt", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--selection-pin")
    parser.add_argument("--freeze", type=Path, default=WORKSPACE / "rrsnn_v4/pre_data_freeze.json")
    arguments = parser.parse_args()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    import json
    print(json.dumps(create(arguments)))
