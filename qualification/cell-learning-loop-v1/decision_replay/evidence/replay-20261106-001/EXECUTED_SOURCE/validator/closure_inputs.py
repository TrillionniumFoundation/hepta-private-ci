"""Validate the concrete source, encoder files and original training inputs."""

import hashlib
import io
import json
from pathlib import Path, PurePosixPath

import numpy as np

from bounded_npz import inspect_npz
from closure_common import (
    ClosureError,
    canonical,
    digest_text,
    integer,
    object_keys,
    read_capped,
    sha,
    strict_json,
    text,
)


def source_snapshot(value, limits):
    if not isinstance(value, dict):
        value = strict_json(read_capped(value, limits.max_source_bytes))
    object_keys(value, {"cut", "records"}, "source snapshot")
    cut, records = value["cut"], value["records"]
    object_keys(cut, {"scope", "records"}, "source cut")
    text(cut["scope"], 4096, "source scope")
    if (
        not isinstance(records, list)
        or not isinstance(cut["records"], list)
        or not 1 <= len(records) <= limits.max_source_records
        or len(records) != len(cut["records"])
    ):
        raise ClosureError("Invalid source record inventory")
    for record in cut["records"]:
        object_keys(
            record, {"source_id", "revision", "body_sha256"}, "source-cut record"
        )
        text(record["source_id"], 4096, "source-cut identity")
        integer(record["revision"], 1, (1 << 63) - 1, "source-cut revision")
        digest_text(record["body_sha256"], "source-cut body")
    checked = []
    total = 0
    for record in records:
        object_keys(
            record,
            {"scope", "source_id", "revision", "body", "body_sha256", "active"},
            "source record",
        )
        text(record["source_id"], 4096, "source identity")
        integer(record["revision"], 1, (1 << 63) - 1, "source revision")
        if (
            record["scope"] != cut["scope"]
            or type(record["active"]) is not int
            or record["active"] != 1
        ):
            raise ClosureError("Source is outside the cut or revoked in this snapshot")
        if (
            not isinstance(record["body"], str)
            or len(record["body"]) > limits.max_source_body_bytes
        ):
            raise ClosureError("Source body is not text")
        body = record["body"].encode("utf-8")
        total += len(body)
        if len(body) > limits.max_source_body_bytes or total > limits.max_source_bytes:
            raise ClosureError("Source bodies exceed the content bound")
        if sha(body) != digest_text(record["body_sha256"], "source body"):
            raise ClosureError("Source body hash mismatch")
        checked.append(
            {key: record[key] for key in ("source_id", "revision", "body_sha256")}
        )
    checked.sort(key=lambda record: record["source_id"])
    if (
        len({record["source_id"] for record in checked}) != len(checked)
        or checked != cut["records"]
    ):
        raise ClosureError("Source cut does not match the complete body snapshot")
    encoded = canonical(value)
    if len(encoded) > limits.max_source_bytes:
        raise ClosureError("Source snapshot exceeds the serialized bound")
    return {
        "cut": cut,
        "source_version": sha(canonical(cut)),
        "snapshot_sha256": sha(encoded),
    }


def _encoder_file(root, name, identity, limits):
    text(name, 256, "encoder member path")
    path_name = PurePosixPath(name)
    if (
        not name
        or path_name.is_absolute()
        or ".." in path_name.parts
        or "\\" in name
        or len(name.encode()) > 256
        or path_name.as_posix() != name
    ):
        raise ClosureError("Invalid encoder member path")
    object_keys(
        identity,
        {"bytes", "sha256", "source_digest", "source_digest_kind"},
        "encoder file",
    )
    size = integer(
        identity["bytes"], 1, limits.max_encoder_file_bytes, "encoder file length"
    )
    digest_text(identity["sha256"], "encoder file")
    kind = identity["source_digest_kind"]
    if kind == "sha256":
        digest_text(identity["source_digest"], "encoder source")
        original = hashlib.sha256()
    elif kind == "git":
        source = identity["source_digest"]
        if (
            not isinstance(source, str)
            or len(source) != 40
            or any(char not in "0123456789abcdef" for char in source)
        ):
            raise ClosureError("Invalid encoder Git blob identity")
        original = hashlib.sha1(f"blob {size}\0".encode(), usedforsecurity=False)
    else:
        raise ClosureError("Unsupported encoder digest kind")
    path = root.joinpath(*path_name.parts)
    parents = [
        path,
        root,
        *[parent for parent in path.parents if parent.is_relative_to(root)],
    ]
    if (
        any(parent.is_symlink() for parent in parents)
        or not path.is_file()
        or not path.resolve().is_relative_to(root.resolve())
    ):
        raise ClosureError("Missing or linked encoder member")
    measured, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while block := stream.read(min(1024 * 1024, size - count + 1)):
            count += len(block)
            if count > size:
                raise ClosureError("Encoder file exceeded its declared bound")
            measured.update(block)
            original.update(block)
    if (
        count != size
        or measured.hexdigest() != identity["sha256"]
        or original.hexdigest() != identity["source_digest"]
    ):
        raise ClosureError("Encoder file contents differ from the manifest")
    return size


def encoder_closure(manifest_path, root, mode, pins, limits):
    raw = read_capped(manifest_path, limits.max_metadata_bytes)
    manifest = strict_json(raw)
    object_keys(
        manifest,
        {
            "schema",
            "model_id",
            "revision",
            "files",
            "backend",
            "pooling",
            "max_length",
            "embedding_dimension",
            "intra_op_threads",
            "inter_op_threads",
            "packages",
        },
        "encoder manifest",
    )
    if manifest["schema"] != "hepta-frozen-encoder-v1":
        raise ClosureError("Unsupported encoder manifest schema")
    integer(
        manifest["embedding_dimension"], 1, limits.max_dimension, "encoder dimension"
    )
    integer(manifest["max_length"], 2, 256, "encoder token limit")
    integer(manifest["intra_op_threads"], 1, 64, "encoder thread count")
    if (
        type(manifest["inter_op_threads"]) is not int
        or manifest["inter_op_threads"] != 1
    ):
        raise ClosureError("Unexpected encoder inter-op configuration")
    object_keys(
        manifest["packages"],
        {"numpy", "onnxruntime", "tokenizers"},
        "encoder package identities",
    )
    for version in manifest["packages"].values():
        text(version, 128, "encoder package version")
    if mode == "reference":
        if (
            manifest["model_id"] != pins["MODEL_ID"]
            or manifest["revision"] != pins["REVISION"]
            or manifest["backend"] != "onnxruntime-cpu"
            or manifest["pooling"] != "attention-masked-mean-then-l2"
            or manifest["embedding_dimension"] != 384
            or not isinstance(manifest["files"], dict)
            or set(manifest["files"]) != set(pins["FILES"])
        ):
            raise ClosureError("Encoder does not match the fixed V13 MiniLM profile")
        for name, (size, kind, expected) in pins["FILES"].items():
            identity = manifest["files"][name]
            if not isinstance(identity, dict) or (
                identity.get("bytes"),
                identity.get("source_digest_kind"),
                identity.get("source_digest"),
            ) != (size, kind, expected):
                raise ClosureError("Encoder reference pin mismatch")
    elif mode == "synthetic-fixture":
        if (
            manifest["model_id"] != "synthetic-v13-closure-fixture"
            or manifest["revision"] != "fixture-v1"
            or manifest["backend"] != "synthetic-no-inference"
            or manifest["pooling"] != "synthetic-features-supplied"
        ):
            raise ClosureError(
                "Synthetic verification requires an explicitly synthetic encoder"
            )
    else:
        raise ClosureError("Unknown verification mode")
    files = manifest["files"]
    if not isinstance(files, dict) or not 1 <= len(files) <= 8:
        raise ClosureError("Invalid encoder file inventory")
    total = 0
    for name, identity in sorted(files.items()):
        total += _encoder_file(Path(root).absolute(), name, identity, limits)
        if total > limits.max_encoder_total_bytes:
            raise ClosureError("Encoder closure exceeds the total byte bound")
    # Match FrozenEncoder.manifest_hash exactly (its JSON uses ensure_ascii=True).
    identity_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode()
    return {
        "manifest": manifest,
        "encoder_hash": sha(identity_bytes),
        "manifest_file_sha256": sha(raw),
        "verified_file_bytes": total,
        "execution_performed": False,
    }


def training_data(path, metadata, limits):
    raw = read_capped(path, limits.max_dataset_bytes)
    headers, _ = inspect_npz(raw, {"X", "y"}, limits)
    n, dimension = metadata["sampler"]["n"], metadata["config"]["input_dim"]
    if (
        headers["X"]["shape"] != (n, dimension)
        or headers["y"]["shape"] != (n,)
        or headers["X"]["dtype"] not in {np.dtype("float32"), np.dtype("float64")}
        or headers["y"]["dtype"].kind not in "iu"
        or n * dimension > limits.max_dataset_elements
    ):
        raise ClosureError("Training data shape/dtype exceeds the adapter contract")
    with np.load(io.BytesIO(raw), allow_pickle=False) as saved:
        features, labels = saved["X"], saved["y"]
        if (
            not np.isfinite(features).all()
            or labels.min() < 0
            or labels.max() >= metadata["config"]["num_classes"]
        ):
            raise ClosureError("Invalid training feature or label contents")
        fingerprint = hashlib.sha256()
        fingerprint.update(
            json.dumps([features.shape, labels.shape], separators=(",", ":")).encode()
        )
        fingerprint.update(np.ascontiguousarray(features, dtype="<f8").tobytes())
        fingerprint.update(np.ascontiguousarray(labels, dtype="<i8").tobytes())
    if fingerprint.hexdigest() != metadata["sampler"]["fingerprint"]:
        raise ClosureError("Training data fingerprint differs from the checkpoint")
    return {
        "artifact_sha256": sha(raw),
        "artifact_bytes": len(raw),
        "fingerprint": fingerprint.hexdigest(),
        "examples": n,
        "dimension": dimension,
        "data_id": metadata["sampler"]["data_id"],
        "embedding_derivation_executed": False,
    }
