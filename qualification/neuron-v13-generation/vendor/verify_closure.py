"""Bounded V13 checkpoint content validation; this module never adopts a model."""

import argparse
from dataclasses import asdict
import hashlib
import io
import json
import math
import platform
import struct
import sys

import numpy as np

from bounded_npz import inspect_npz
from closure_common import (
    ClosureError,
    ClosureLimits,
    REFERENCE_COMMIT,
    REFERENCE_HASHES,
    canonical,
    digest_text,
    integer,
    object_keys,
    read_capped,
    reference,
    sha,
    strict_json,
    text,
)
from closure_inputs import (
    encoder_closure,
    source_snapshot as check_sources,
    training_data,
)


ARRAY_NAMES = {
    f"{group}_{name}" for group in ("params", "m", "v") for name in ("A", "B", "W", "b")
}
CHECKPOINT_NAMES = ARRAY_NAMES | {"sampler_order", "metadata"}


def _metadata(raw, headers, limits):
    metadata = strict_json(raw)
    object_keys(
        metadata,
        {
            "schema",
            "config",
            "encoder_hash",
            "source_version",
            "step",
            "rng_state",
            "sampler",
            "optimizer",
        },
        "checkpoint metadata",
    )
    if metadata["schema"] != "hepta-residual-tanh-adam-v1":
        raise ClosureError("Unsupported V13 checkpoint schema")
    config = metadata["config"]
    object_keys(config, {"input_dim", "num_classes", "rank", "seed"}, "adapter config")
    for key in ("input_dim", "num_classes", "rank"):
        integer(config[key], 1, limits.max_dimension, f"adapter {key}")
    integer(config["seed"], 0, (1 << 128) - 1, "adapter seed")
    d, c, r = config["input_dim"], config["num_classes"], config["rank"]
    if 2 * d * r + d * c + c > limits.max_parameter_elements:
        raise ClosureError("Adapter constructor exceeds the parameter bound")
    shapes = {"A": (d, r), "B": (r, d), "W": (d, c), "b": (c,)}
    for group in ("params", "m", "v"):
        for name, shape in shapes.items():
            header = headers[f"{group}_{name}"]
            if header["shape"] != shape or header["dtype"] != np.dtype("float64"):
                raise ClosureError(
                    "Parameter/Adam dtype or shape differs from the original loader"
                )
    integer(metadata["step"], 0, (1 << 64) - 1, "optimizer step")
    digest_text(metadata["encoder_hash"], "checkpoint encoder")
    digest_text(metadata["source_version"], "checkpoint source cut")
    sampler = metadata["sampler"]
    object_keys(sampler, {"cursor", "epoch", "n", "data_id", "fingerprint"}, "sampler")
    n = integer(sampler["n"], 1, limits.max_examples, "established sampler size")
    integer(sampler["cursor"], 0, n, "sampler cursor")
    integer(sampler["epoch"], 0, (1 << 64) - 1, "sampler epoch")
    text(sampler["data_id"], 4096, "training data identity")
    digest_text(sampler["fingerprint"], "training data fingerprint")
    order = headers["sampler_order"]
    if order["shape"] != (n,) or order["dtype"] != np.dtype("int64"):
        raise ClosureError("Sampler order has the wrong dtype or shape")
    optimizer = metadata["optimizer"]
    object_keys(
        optimizer, {"lr", "batch_size", "beta1", "beta2", "epsilon"}, "Adam optimizer"
    )
    integer(optimizer["batch_size"], 1, limits.max_examples, "Adam batch size")
    if (
        type(optimizer["lr"]) not in (int, float)
        or not math.isfinite(optimizer["lr"])
        or optimizer["lr"] <= 0
    ):
        raise ClosureError("Invalid Adam learning rate")
    for name, value in (("beta1", 0.9), ("beta2", 0.999), ("epsilon", 1e-8)):
        if type(optimizer[name]) not in (int, float) or optimizer[name] != value:
            raise ClosureError("Unsupported Adam optimizer semantics")
    rng = metadata["rng_state"]
    object_keys(rng, {"bit_generator", "state", "has_uint32", "uinteger"}, "RNG state")
    object_keys(rng["state"], {"state", "inc"}, "PCG64 state")
    if rng["bit_generator"] != "PCG64":
        raise ClosureError("The original V13 loader uses PCG64")
    integer(rng["state"]["state"], 0, (1 << 128) - 1, "PCG64 state word")
    increment = integer(rng["state"]["inc"], 1, (1 << 128) - 1, "PCG64 increment")
    if not increment % 2:
        raise ClosureError("PCG64 increment must be odd")
    integer(rng["has_uint32"], 0, 1, "PCG64 cached-word flag")
    integer(rng["uinteger"], 0, (1 << 32) - 1, "PCG64 cached word")
    return metadata


def _member(name, context, values, arrays):
    # Each frame is length-prefixed. Arrays use named dtype/shape + C-order bytes.
    digest = hashlib.sha256()
    for frame in (
        b"hepta.cell-learning.v13.resumable.v1",
        name.encode(),
        canonical(context),
        canonical(values),
    ):
        digest.update(struct.pack("<Q", len(frame)))
        digest.update(frame)
    for key, array in sorted(arrays.items()):
        descriptor = canonical(
            {"name": key, "dtype": array.dtype.str, "shape": list(array.shape)}
        )
        raw = np.ascontiguousarray(array).tobytes()
        for frame in (descriptor, raw):
            digest.update(struct.pack("<Q", len(frame)))
            digest.update(frame)
    return digest.hexdigest()


def _release(path, artifact, state_hash, sources, encoder, limits):
    if path is None:
        return None
    raw = read_capped(path, limits.max_source_bytes)
    manifest = strict_json(raw)
    object_keys(
        manifest,
        {
            "schema",
            "scope",
            "source_cut",
            "source_version",
            "encoder_sha256",
            "parent_artifact",
            "state_sha256",
            "model_sha256",
        },
        "SourceOwner release",
    )
    expected = {
        "schema": "hepta.memory.adapter-release.v13",
        "scope": sources["cut"]["scope"],
        "source_cut": sources["cut"],
        "source_version": sources["source_version"],
        "encoder_sha256": encoder["encoder_hash"],
        "state_sha256": state_hash,
        "model_sha256": artifact,
    }
    if any(
        canonical(manifest[key]) != canonical(value) for key, value in expected.items()
    ) or raw != canonical(manifest):
        raise ClosureError(
            "Release manifest differs from the verified checkpoint closure"
        )
    if manifest["parent_artifact"] is not None:
        digest_text(manifest["parent_artifact"], "parent artifact reference")
    return {
        "artifact_id": sha(raw),
        "manifest": manifest,
        "parent_content_verified": False,
        "publication_checked": False,
    }


def verify_checkpoint(
    npz_path,
    *,
    source_snapshot,
    encoder_manifest_path,
    encoder_root,
    dataset_npz_path,
    expected_data_id,
    mode="reference",
    limits=None,
    release_manifest_path=None,
):
    """Return verified content identities only. SourceOwner retains adoption/CAS.

    Inputs are bounded files, plus a SourceOwner ``{cut, records}`` snapshot.
    Synthetic fixtures require explicit mode and a synthetic encoder identity.
    No train, prediction, encoder execution, download or publication is invoked.
    """
    limits = ClosureLimits() if limits is None else limits
    if type(limits) is not ClosureLimits:
        raise ClosureError("Limits must be a checked ClosureLimits instance")
    try:
        raw = read_capped(npz_path, limits.max_checkpoint_bytes)
        headers, metadata_bytes = inspect_npz(raw, CHECKPOINT_NAMES, limits)
        metadata = _metadata(metadata_bytes, headers, limits)
        adapter_type, provenance, pins = reference()
        sources = check_sources(source_snapshot, limits)
        encoder = encoder_closure(
            encoder_manifest_path, encoder_root, mode, pins, limits
        )
        text(expected_data_id, 4096, "expected training data identity")
        if (
            metadata["encoder_hash"] != encoder["encoder_hash"]
            or metadata["source_version"] != sources["source_version"]
            or metadata["sampler"]["data_id"] != expected_data_id
            or metadata["config"]["input_dim"]
            != encoder["manifest"]["embedding_dimension"]
        ):
            raise ClosureError("Checkpoint/source/encoder/data binding mismatch")
        data = training_data(dataset_npz_path, metadata, limits)
        # Reuse the exact loader on the same bounded bytes inspected above.
        model = adapter_type.load(
            io.BytesIO(raw),
            expected_encoder_hash=encoder["encoder_hash"],
            expected_source_version=sources["source_version"],
            expected_data_id=expected_data_id,
        )
        if canonical(model.rng.bit_generator.state) != canonical(metadata["rng_state"]):
            raise ClosureError("The loader normalized an unsupported RNG state")
        context = {
            "schema": metadata["schema"],
            "adapter_source_sha256": REFERENCE_HASHES["adapter.py"],
            "config": model.config,
            "encoder_hash": model.encoder_hash,
            "source_version": model.source_version,
            "data_id": model.sampler["data_id"],
            "data_fingerprint": model.sampler["fingerprint"],
        }
        members = {
            "weights": _member("weights", context, {}, model.params),
            "optimizer": _member(
                "optimizer",
                context,
                {"step": model.step, "optimizer": model.optimizer},
                {
                    f"{group}_{key}": value
                    for group in ("m", "v")
                    for key, value in getattr(model, group).items()
                },
            ),
            "rng": _member("rng", context, model.rng.bit_generator.state, {}),
            "sampler": _member(
                "sampler",
                context,
                {key: model.sampler[key] for key in ("n", "data_id", "fingerprint")},
                {"order": model.sampler["order"]},
            ),
        }
        members["training_cursor"] = _member(
            "training_cursor",
            context,
            {
                "step": model.step,
                "cursor": model.sampler["cursor"],
                "epoch": model.sampler["epoch"],
                "n": model.sampler["n"],
                "batch_size": model.optimizer["batch_size"],
                "sampler_digest": members["sampler"],
            },
            {},
        )
        state_hash, artifact = model.state_hash(), sha(raw)
        release = _release(
            release_manifest_path, artifact, state_hash, sources, encoder, limits
        )
        binding = {
            "kind": "resumable",
            **{key: list(bytes.fromhex(value)) for key, value in members.items()},
        }
        return {
            "schema": "hepta.cell-learning.v13.content-binding.v1",
            "authority": "DENY_ALL",
            "verification_mode": mode,
            "synthetic": mode == "synthetic-fixture",
            "binding": binding,
            "member_sha256": members,
            "context": context,
            "checkpoint": {
                "sha256": artifact,
                "bytes": len(raw),
                "legacy_state_sha256": state_hash,
            },
            "source": sources,
            "encoder": encoder,
            "training_data": data,
            "release": release,
            "reference": {
                "source_commit": REFERENCE_COMMIT,
                "files": provenance["files"],
            },
            "runtime": {"python": platform.python_version(), "numpy": np.__version__},
            "limits": asdict(limits),
            "training_executed": False,
            "inference_executed": False,
            "adoption_performed": False,
            "live_source_frontier_checked": False,
            "executable_quality_evaluation_performed": False,
        }
    except ClosureError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        UnicodeError,
        OverflowError,
        RecursionError,
    ) as error:
        raise ClosureError("Invalid V13 learning closure") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint")
    parser.add_argument("--source-snapshot", required=True)
    parser.add_argument("--encoder-manifest", required=True)
    parser.add_argument("--encoder-root", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--data-id", required=True)
    parser.add_argument(
        "--mode", choices=("reference", "synthetic-fixture"), default="reference"
    )
    parser.add_argument("--release-manifest")
    args = parser.parse_args()
    try:
        receipt = verify_checkpoint(
            args.checkpoint,
            source_snapshot=args.source_snapshot,
            encoder_manifest_path=args.encoder_manifest,
            encoder_root=args.encoder_root,
            dataset_npz_path=args.dataset,
            expected_data_id=args.data_id,
            mode=args.mode,
            release_manifest_path=args.release_manifest,
        )
    except ClosureError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(
        json.dumps(
            receipt, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
