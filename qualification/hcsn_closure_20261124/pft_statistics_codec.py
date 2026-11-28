"""Lossless research packet representation; no PSD, provenance or authority claim."""

import math
import re
import struct

from .pft_statistics import checked_contract, digest, valid_digest


MAGIC = b"HPFTB001"
MAX_PACKET_BYTES = 8 * 1024 * 1024
_HEADER = struct.Struct("<8sBHHIB32s32s32s")
_FIELDS = {
    "contract_sha256",
    "batch_id",
    "source_sha256",
    "sample_ids",
    "count",
    "gram",
    "rhs",
    "yty",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _matrix(value, rows, columns):
    _require(type(value) is list and len(value) == rows, "matrix row count")
    encoded = []
    for row in value:
        _require(type(row) is list and len(row) == columns, "matrix column count")
        _require(
            all(type(v) is float and math.isfinite(v) for v in row),
            "plain finite float entries required",
        )
        encoded.append(struct.pack(f"<{columns}d", *row))
    return b"".join(encoded)


def _square(data, size):
    # Native integer interpretation is used only for equality of eight-byte words.
    words = memoryview(data).cast("Q")
    symmetric = all(
        words[i * size + j] == words[j * size + i]
        for i in range(size)
        for j in range(i + 1, size)
    )
    if symmetric:
        return True, b"".join(
            data[(i * size + i) * 8 : (i + 1) * size * 8] for i in range(size)
        )
    return False, data


def encode_packet(packet, contract):
    """Encode producer plain-float matrices without changing their canonical hash."""
    contract = checked_contract(contract)
    _require(
        type(packet) is dict and set(packet) == {"body", "payload_sha256"},
        "packet fields",
    )
    body = packet["body"]
    _require(type(body) is dict and set(body) == _FIELDS, "body fields")
    _require(
        all(
            type(v) is str and valid_digest(v)
            for v in (
                body["contract_sha256"],
                body["source_sha256"],
                packet["payload_sha256"],
            )
        ),
        "hash syntax",
    )
    _require(body["contract_sha256"] == digest(contract), "contract identity")
    batch = body["batch_id"]
    _require(
        type(batch) is str and re.fullmatch("[A-Za-z0-9_.-]{1,128}", batch) is not None,
        "batch identifier",
    )
    count, ids = body["count"], body["sample_ids"]
    _require(type(count) is int and 1 <= count <= 100000, "count bound")
    _require(type(ids) is list and len(ids) == count, "sample count")
    _require(all(type(v) is str and valid_digest(v) for v in ids), "sample identifier")
    _require(
        all(ids[i] < ids[i + 1] for i in range(count - 1)), "sample order or duplicates"
    )
    d, m = contract["dimension"], contract["outputs"]
    triangular_g, gram = _square(_matrix(body["gram"], d, d), d)
    rhs = _matrix(body["rhs"], d, m)
    triangular_t, yty = _square(_matrix(body["yty"], m, m), m)
    _require(packet["payload_sha256"] == digest(body), "payload identity")
    flags = int(triangular_g) | (int(triangular_t) << 1)
    batch_bytes = batch.encode("ascii")
    length = (
        _HEADER.size + len(batch_bytes) + 32 * count + len(gram) + len(rhs) + len(yty)
    )
    _require(length <= MAX_PACKET_BYTES, "encoded packet exceeds 8 MiB")
    header = _HEADER.pack(
        MAGIC,
        flags,
        d,
        m,
        count,
        len(batch_bytes),
        bytes.fromhex(body["contract_sha256"]),
        bytes.fromhex(body["source_sha256"]),
        bytes.fromhex(packet["payload_sha256"]),
    )
    return b"".join(
        (header, batch_bytes, b"".join(bytes.fromhex(v) for v in ids), gram, rhs, yty)
    )


def _read_matrix(raw, offset, rows, columns, triangular):
    if triangular:
        value = [[0.0] * columns for _ in range(rows)]
        for i in range(rows):
            values = struct.unpack_from(f"<{columns - i}d", raw, offset)
            offset += 8 * (columns - i)
            for j, number in enumerate(values, i):
                value[i][j] = value[j][i] = number
    else:
        value = []
        for _ in range(rows):
            value.append(list(struct.unpack_from(f"<{columns}d", raw, offset)))
            offset += 8 * columns
    return value, offset


def decode_packet(raw, contract):
    """Decode only canonical, bounded packets; downstream admission stays separate."""
    _require(
        type(raw) is bytes and _HEADER.size <= len(raw) <= MAX_PACKET_BYTES,
        "encoded length bound",
    )
    (
        magic,
        flags,
        d,
        m,
        count,
        batch_length,
        contract_hash,
        source_hash,
        payload_hash,
    ) = _HEADER.unpack_from(raw)
    contract = checked_contract(contract)
    _require(magic == MAGIC and flags & ~3 == 0, "magic or flags")
    _require(
        d == contract["dimension"] and m == contract["outputs"], "contract dimensions"
    )
    _require(contract_hash.hex() == digest(contract), "contract identity")
    _require(1 <= count <= 100000 and 1 <= batch_length <= 128, "count or batch bound")
    g_count = d * (d + 1) // 2 if flags & 1 else d * d
    t_count = m * (m + 1) // 2 if flags & 2 else m * m
    length = _HEADER.size + batch_length + 32 * count + 8 * (g_count + d * m + t_count)
    _require(len(raw) == length, "truncated or trailing bytes")
    offset = _HEADER.size
    batch = raw[offset : offset + batch_length].decode("ascii")
    offset += batch_length
    ids = [raw[offset + 32 * i : offset + 32 * (i + 1)].hex() for i in range(count)]
    offset += 32 * count
    gram, offset = _read_matrix(raw, offset, d, d, bool(flags & 1))
    rhs, offset = _read_matrix(raw, offset, d, m, False)
    yty, offset = _read_matrix(raw, offset, m, m, bool(flags & 2))
    body = dict(
        contract_sha256=contract_hash.hex(),
        source_sha256=source_hash.hex(),
        batch_id=batch,
        count=count,
        sample_ids=ids,
        gram=gram,
        rhs=rhs,
        yty=yty,
    )
    packet = dict(body=body, payload_sha256=payload_hash.hex())
    # This verifies producer types, finite values, identities and canonical modes.
    _require(encode_packet(packet, contract) == raw, "noncanonical binary encoding")
    return packet
