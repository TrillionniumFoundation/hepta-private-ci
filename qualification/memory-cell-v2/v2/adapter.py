"""Train v1 numerical heads on v2 features without mislabelling their encoder."""

import io
import json
from pathlib import Path
import re
import zipfile

import numpy as np

from memory_cells.model import MemoryCell
from .encoder import canonical, sha


def _identities(source_commit, support_digest):
    if (
        not isinstance(source_commit, str)
        or not re.fullmatch(r"[0-9a-f]{40}", source_commit)
        or not isinstance(support_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", support_digest)
    ):
        raise ValueError("invalid source or support identity")


def _encoder_contract(manifest, input_dim):
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("dimension")) is not int
        or manifest["dimension"] != input_dim
        or not isinstance(manifest.get("schema"), str)
        or not 1 <= len(manifest["schema"]) <= 128
        or len(canonical(manifest)) > 32768
    ):
        raise ValueError("encoder shape or metadata contract mismatch")


def save_cell(cell, directory, encoder_manifest, *, source_commit, support_digest):
    _identities(source_commit, support_digest)
    _encoder_contract(encoder_manifest, cell.input_dim)
    encoder_manifest = json.loads(canonical(encoder_manifest))
    if (
        type(cell.total_steps) is not int
        or cell.total_steps < 0
        or cell.A.shape != (cell.input_dim, cell.rank)
        or cell.B.shape != (cell.rank, cell.num_classes)
        or any(
            array.dtype != np.dtype("float64") or not np.isfinite(array).all()
            for array in (cell.A, cell.B)
        )
    ):
        raise ValueError("invalid adapter numeric state")
    buffer = io.BytesIO()
    np.savez_compressed(buffer, A=cell.A.astype("<f8"), B=cell.B.astype("<f8"))
    tensors = buffer.getvalue()
    manifest = {
        "schema": "memory-cell-v2.adapter.v1",
        "encoder": encoder_manifest,
        "encoder_digest": sha(canonical(encoder_manifest)),
        "source_commit": source_commit,
        "support_digest": support_digest,
        "input_dim": cell.input_dim,
        "rank": cell.rank,
        "num_classes": cell.num_classes,
        "seed": cell.seed,
        "total_steps": cell.total_steps,
        "parameter_bytes": cell.parameter_bytes,
        "tensor_bytes": len(tensors),
        "tensor_sha256": sha(tensors),
        "dtype": "float64",
    }
    manifest["manifest_sha256"] = sha(canonical(manifest))
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=False)
    (path / "tensors.npz").write_bytes(tensors)
    (path / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return manifest


def load_cell(directory, *, expected_encoder_digest):
    if not isinstance(expected_encoder_digest, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_encoder_digest
    ):
        raise ValueError("invalid expected encoder identity")
    requested_path = Path(directory)
    if requested_path.is_symlink():
        raise ValueError("symlinked adapter directory")
    path = requested_path.resolve(strict=True)
    if not path.is_dir():
        raise ValueError("adapter must be a directory")
    if {p.name for p in path.iterdir()} != {"manifest.json", "tensors.npz"}:
        raise ValueError("unexpected adapter files")
    for name in ("manifest.json", "tensors.npz"):
        if (path / name).is_symlink() or not (path / name).is_file():
            raise ValueError("adapter files must be regular files without symlinks")
    if (path / "manifest.json").stat().st_size > 65536:
        raise ValueError("oversized adapter manifest")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate adapter manifest field")
            result[key] = value
        return result

    manifest = json.loads(
        (path / "manifest.json").read_bytes(), object_pairs_hook=unique
    )
    required = {
        "schema",
        "encoder",
        "encoder_digest",
        "source_commit",
        "support_digest",
        "input_dim",
        "rank",
        "num_classes",
        "seed",
        "total_steps",
        "parameter_bytes",
        "tensor_bytes",
        "tensor_sha256",
        "dtype",
        "manifest_sha256",
    }
    if (
        not isinstance(manifest, dict)
        or set(manifest) != required
        or manifest["schema"] != "memory-cell-v2.adapter.v1"
    ):
        raise ValueError("unsupported adapter manifest")
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if sha(canonical(body)) != manifest["manifest_sha256"]:
        raise ValueError("adapter manifest identity mismatch")
    if (
        manifest["encoder_digest"] != expected_encoder_digest
        or sha(canonical(manifest["encoder"])) != expected_encoder_digest
    ):
        raise ValueError("adapter encoder identity mismatch")
    _identities(manifest["source_commit"], manifest["support_digest"])
    _encoder_contract(manifest["encoder"], manifest["input_dim"])
    cell = MemoryCell(
        manifest["input_dim"],
        manifest["rank"],
        manifest["num_classes"],
        manifest["seed"],
    )
    if (
        manifest["dtype"] != "float64"
        or type(manifest["parameter_bytes"]) is not int
        or manifest["parameter_bytes"] != cell.parameter_bytes
    ):
        raise ValueError("adapter numeric contract mismatch")
    tensor_path = path / "tensors.npz"
    if (
        type(manifest["tensor_bytes"]) is not int
        or tensor_path.stat().st_size != manifest["tensor_bytes"]
        or not 0 < manifest["tensor_bytes"] <= cell.parameter_bytes + 65536
    ):
        raise ValueError("invalid adapter tensor size")
    raw = tensor_path.read_bytes()
    if sha(raw) != manifest["tensor_sha256"]:
        raise ValueError("adapter tensor identity mismatch")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if (
                sorted(archive.namelist()) != ["A.npy", "B.npy"]
                or sum(entry.file_size for entry in entries)
                > cell.parameter_bytes + 2048
                or any(
                    entry.flag_bits & 1
                    or entry.compress_type
                    not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    for entry in entries
                )
            ):
                raise ValueError("invalid adapter tensor inventory")
            for name, expected_shape in (("A", cell.A.shape), ("B", cell.B.shape)):
                with archive.open(name + ".npy") as stream:
                    if np.lib.format.read_magic(stream) != (1, 0):
                        raise ValueError("unsupported adapter tensor encoding")
                    shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
                    data_bytes = 8 * int(np.prod(expected_shape))
                    if (
                        shape != expected_shape
                        or fortran
                        or dtype.str != "<f8"
                        or archive.getinfo(name + ".npy").file_size
                        != stream.tell() + data_bytes
                    ):
                        raise ValueError("invalid adapter array header")
                    # Validate the header before allocation, then read exactly the
                    # declared small tensor instead of trusting np.load's shape.
                    payload = stream.read(data_bytes + 1)
                if len(payload) != data_bytes:
                    raise ValueError("invalid adapter array byte count")
                data = np.frombuffer(payload, dtype="<f8").reshape(expected_shape)
                if not np.isfinite(data).all():
                    raise ValueError("nonfinite adapter weights")
                setattr(cell, name, data.astype(np.float64, copy=True))
    except (zipfile.BadZipFile, EOFError) as error:
        raise ValueError("invalid adapter tensor encoding") from error
    if type(manifest["total_steps"]) is not int or manifest["total_steps"] < 0:
        raise ValueError("invalid training step count")
    cell.total_steps = manifest["total_steps"]
    return cell, manifest
