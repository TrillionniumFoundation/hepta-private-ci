"""Lossless numeric source/replay archives and strong exact-codec controls.

Parameter reads remain separate. A residual archive reconstructs the exact
canonical int32 source only with its matching model. External-model mode lets
the deployed artifact and replay archive share one charged model instance.
"""

import hashlib
import json
import lzma
import struct
import time
import zlib

import numpy as np

from .factor_cell import (
    FactorBank,
    MAX_ARTIFACT_BYTES,
    MAX_COLUMNS,
    MAX_ROWS,
    MAX_VALUES,
    canonical_matrix,
)


MAGIC = b"HMRCD3\0\0"
HEADER = struct.Struct("<8sI")
MAX_RAW_BYTES = MAX_ARTIFACT_BYTES + 10 * MAX_VALUES + 65536
METHODS = ("raw", "zlib", "lzma")


def source_digest(matrix, mask):
    return hashlib.sha256(
        matrix.tobytes(order="C")
        + np.packbits(mask.ravel(), bitorder="little").tobytes()
    ).hexdigest()


def compress_bytes(payload, method="best"):
    if method not in METHODS + ("best",):
        raise ValueError("unknown archive compressor")
    candidates = []
    for candidate in METHODS if method == "best" else (method,):
        body = (
            payload
            if candidate == "raw"
            else zlib.compress(payload, 9)
            if candidate == "zlib"
            else lzma.compress(payload, preset=6)
        )
        candidates.append(bytes([METHODS.index(candidate)]) + body)
    return min(candidates, key=len)


def decompress_bytes(payload, maximum=MAX_RAW_BYTES):
    if not isinstance(payload, bytes) or not payload or len(payload) > maximum + 1:
        raise ValueError("invalid archive envelope")
    method, body = payload[0], payload[1:]
    if method == 0:
        result = body
    elif method == 1:
        decoder = zlib.decompressobj()
        result = decoder.decompress(body, maximum + 1)
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError("truncated, trailing, or oversized zlib archive")
    elif method == 2:
        decoder = lzma.LZMADecompressor(memlimit=128 * 1024 * 1024)
        result = decoder.decompress(body, max_length=maximum + 1)
        if not decoder.eof or decoder.unused_data:
            raise ValueError("truncated, trailing, or oversized LZMA archive")
    else:
        raise ValueError("unknown archive compressor tag")
    if len(result) > maximum:
        raise ValueError("archive expansion exceeds bound")
    return result


def signed_varints(values):
    result = bytearray()
    for value in np.asarray(values).ravel():
        integer = int(value)
        number = -2 * integer - 1 if integer < 0 else 2 * integer
        if number >= 1 << 64:
            raise ValueError("residual exceeds signed-varint contract")
        while number >= 128:
            result.append((number & 127) | 128)
            number >>= 7
        result.append(number)
    return bytes(result)


def read_signed_varints(payload, count):
    if not 0 <= count <= MAX_VALUES:
        raise ValueError("varint count exceeds memory limit")
    result = np.empty(count, dtype=np.int64)
    number = shift = position = 0
    for byte in payload:
        if position >= count or shift >= 64 or (shift == 63 and byte > 1):
            raise ValueError("oversized or trailing varint")
        number |= (byte & 127) << shift
        if byte & 128:
            shift += 7
        else:
            if shift and byte == 0:
                raise ValueError("noncanonical varint")
            result[position] = -(number // 2) - 1 if number & 1 else number // 2
            number = shift = 0
            position += 1
    if position != count or shift:
        raise ValueError("truncated varints")
    return result


def container(metadata, parts, method):
    header = json.dumps(
        metadata, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return compress_bytes(
        HEADER.pack(MAGIC, len(header)) + header + b"".join(parts), method
    )


def parse_container(payload, expected_sha256=None):
    if (
        expected_sha256 is not None
        and hashlib.sha256(payload).hexdigest() != expected_sha256
    ):
        raise ValueError("source archive digest mismatch")
    expanded = decompress_bytes(payload)
    if len(expanded) < HEADER.size:
        raise ValueError("truncated source archive")
    magic, count = HEADER.unpack_from(expanded)
    if magic != MAGIC or count > 65536 or HEADER.size + count > len(expanded):
        raise ValueError("invalid source archive header")
    metadata = json.loads(expanded[HEADER.size : HEADER.size + count])
    if not isinstance(metadata, dict) or metadata.get("schema") != 1:
        raise ValueError("unknown source archive schema")
    shape = metadata.get("shape")
    if (
        not isinstance(shape, list)
        or len(shape) != 2
        or any(type(x) is not int or x <= 0 for x in shape)
        or shape[0] > MAX_ROWS
        or shape[1] > MAX_COLUMNS
        or shape[0] * shape[1] > MAX_VALUES
    ):
        raise ValueError("invalid source archive shape")
    return metadata, expanded[HEADER.size + count :]


def encode_factor(bank, matrix, *, model_storage="external", method="best"):
    started = time.perf_counter()
    values, mask = canonical_matrix(matrix, bank.mask)
    if values.shape != bank.shape or model_storage not in ("external", "embedded"):
        raise ValueError("source/model schema mismatch")
    model = bank.to_bytes()
    residual = signed_varints(values[mask].astype(np.int64) - bank.reconstruct()[mask])
    included = model if model_storage == "embedded" else b""
    metadata = {
        "schema": 1,
        "kind": "factor-residual",
        "shape": list(values.shape),
        "model_storage": model_storage,
        "model_length": len(included),
        "required_model_length": len(model),
        "model_sha256": bank.digest,
        "residual_count": int(mask.sum()),
        "residual_length": len(residual),
        "source_sha256": source_digest(values, mask),
    }
    payload = container(metadata, [included, residual], method)
    receipt = {
        "schema": "memory-cell-v3.lossless-source-codec.v1",
        "source_values": int(mask.sum()),
        "archive_bytes": len(payload),
        "required_model_bytes": len(model),
        "model_storage": model_storage,
        "complete_standalone_bytes": len(payload)
        + (len(model) if model_storage == "external" else 0),
        "archive_sha256": hashlib.sha256(payload).hexdigest(),
        "model_sha256": bank.digest,
        "source_sha256": metadata["source_sha256"],
        "residual_uncompressed_bytes": len(residual),
        "selected_compressor": METHODS[payload[0]],
        "compression_search": list(METHODS) if method == "best" else [method],
        "encode_seconds": time.perf_counter() - started,
        "parameter_only_readout": False,
        "shared_model_must_be_charged_once": True,
    }
    return payload, receipt


def decode_factor(payload, *, model=None, expected_sha256=None):
    metadata, body = parse_container(payload, expected_sha256)
    keys = {
        "schema",
        "kind",
        "shape",
        "model_storage",
        "model_length",
        "required_model_length",
        "model_sha256",
        "residual_count",
        "residual_length",
        "source_sha256",
    }
    if set(metadata) != keys or metadata["kind"] != "factor-residual":
        raise ValueError("not a factor-residual archive")
    length, residual_length = metadata["model_length"], metadata["residual_length"]
    if (
        type(length) is not int
        or type(residual_length) is not int
        or length < 0
        or residual_length < 0
        or length + residual_length != len(body)
    ):
        raise ValueError("invalid source archive component lengths")
    if metadata["model_storage"] == "embedded":
        if model is not None or length != metadata["required_model_length"]:
            raise ValueError("ambiguous embedded model binding")
        bank = FactorBank.from_bytes(body[:length], metadata["model_sha256"])
    elif metadata["model_storage"] == "external":
        if (
            length
            or not isinstance(model, FactorBank)
            or model.digest != metadata["model_sha256"]
            or len(model.to_bytes()) != metadata["required_model_length"]
        ):
            raise ValueError("missing or mismatched external model")
        bank = model
    else:
        raise ValueError("unknown model storage mode")
    if (
        list(bank.shape) != metadata["shape"]
        or int(bank.mask.sum()) != metadata["residual_count"]
    ):
        raise ValueError("model/source address or availability mismatch")
    residual = read_signed_varints(body[length:], metadata["residual_count"])
    values = np.zeros(bank.shape, dtype=np.int64)
    values[bank.mask] = bank.reconstruct()[bank.mask] + residual
    restored, mask = canonical_matrix(values, bank.mask)
    if source_digest(restored, mask) != metadata["source_sha256"]:
        raise ValueError("source reconstruction digest mismatch")
    return restored, mask


def exact_matrix_archives(matrix, mask=None):
    """Return actual artifacts for 12 fixed, reversible exact baselines."""
    values, observed = canonical_matrix(matrix, mask)
    mask_bytes = (
        b""
        if observed.all()
        else np.packbits(observed.ravel(), bitorder="little").tobytes()
    )
    minimum = int(values[observed].min())
    width = (int(values[observed].max()) - minimum).bit_length()
    offsets = values[observed].astype(np.int64) - minimum
    flags = (
        (offsets.astype(np.uint64)[:, None] >> np.arange(width, dtype=np.uint64)) & 1
    ).astype(np.uint8)
    packed = np.packbits(flags.ravel(), bitorder="little").tobytes()
    forms = {
        "int32": values[observed].tobytes(),
        "offset-bits": packed,
        "delta-row": signed_varints(
            np.diff(
                values.astype(np.int64),
                axis=0,
                prepend=np.zeros((1, values.shape[1]), dtype=np.int64),
            )
        ),
        "delta-column": signed_varints(
            np.diff(
                values.astype(np.int64),
                axis=1,
                prepend=np.zeros((values.shape[0], 1), dtype=np.int64),
            )
        ),
    }
    archives = {}
    for form, data in forms.items():
        metadata = {
            "schema": 1,
            "kind": "exact",
            "shape": list(values.shape),
            "format": form,
            "mask_length": len(mask_bytes),
            "data_length": len(data),
            "minimum": minimum if form == "offset-bits" else None,
            "width": width if form == "offset-bits" else None,
            "source_sha256": source_digest(values, observed),
        }
        for method in METHODS:
            archives[form + "/" + method] = container(
                metadata, [mask_bytes, data], method
            )
    return archives


def decode_exact(payload, expected_sha256=None):
    metadata, body = parse_container(payload, expected_sha256)
    keys = {
        "schema",
        "kind",
        "shape",
        "format",
        "mask_length",
        "data_length",
        "minimum",
        "width",
        "source_sha256",
    }
    if set(metadata) != keys or metadata["kind"] != "exact":
        raise ValueError("not an exact baseline archive")
    n, d = metadata["shape"]
    mask_length = metadata["mask_length"]
    if (
        type(mask_length) is not int
        or type(metadata["data_length"]) is not int
        or mask_length not in (0, (n * d + 7) // 8)
        or metadata["data_length"] != len(body) - mask_length
    ):
        raise ValueError("baseline component length mismatch")
    if mask_length:
        flags = np.unpackbits(
            np.frombuffer(body[:mask_length], dtype=np.uint8), bitorder="little"
        )
        if flags[n * d :].any():
            raise ValueError("nonzero availability padding")
        mask = flags[: n * d].reshape(n, d).astype(bool)
    else:
        mask = np.ones((n, d), dtype=bool)
    encoded = body[mask_length:]
    count = int(mask.sum())
    form = metadata["format"]
    values = np.zeros((n, d), dtype=np.int64)
    if form == "int32":
        if len(encoded) != count * 4:
            raise ValueError("baseline int32 byte length mismatch")
        values[mask] = np.frombuffer(encoded, dtype="<i4")
    elif form == "offset-bits":
        width, minimum = metadata["width"], metadata["minimum"]
        if (
            type(width) is not int
            or not 0 <= width <= 32
            or type(minimum) is not int
            or len(encoded) != (count * width + 7) // 8
        ):
            raise ValueError("invalid offset-bit representation")
        flags = np.unpackbits(np.frombuffer(encoded, dtype=np.uint8), bitorder="little")
        if flags[count * width :].any():
            raise ValueError("nonzero value padding")
        offsets = flags[: count * width].reshape(count, width).astype(np.uint64) @ (
            np.uint64(1) << np.arange(width, dtype=np.uint64)
        )
        values[mask] = offsets.astype(np.int64) + minimum
    elif form in ("delta-row", "delta-column"):
        deltas = read_signed_varints(encoded, n * d).reshape(n, d)
        values = np.cumsum(deltas, axis=0 if form == "delta-row" else 1, dtype=np.int64)
    else:
        raise ValueError("unknown exact baseline representation")
    restored, availability = canonical_matrix(values, mask)
    if source_digest(restored, availability) != metadata["source_sha256"]:
        raise ValueError("baseline reconstruction digest mismatch")
    return restored, availability
