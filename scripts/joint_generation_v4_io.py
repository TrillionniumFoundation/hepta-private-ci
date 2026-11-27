"""Canonical native tensor/owner packets for the explicit joint-generator v4.

These helpers serialize data, not authority. Production owner fields come from
the admitted Cell request; qualification callers must label their own fixtures.
"""

from dataclasses import dataclass
import hashlib
import math
import struct

import torch


TOTAL_UNITS = (16, 1024, 4, 128)
OBSERVATION_FEATURES = 68
PROFILES = {
    "kind": "joint-generator-weights-v4",
    "observation_profile": "owner-prefix-budget-v1",
    "text_profile": "utf8-byte256-scalar128-v1",
    "media_profile": "ppm-wav16000-y4m4-v1",
    "numeric_profile": "fp64-linux-libm-v1",
}


def packet_bytes(metadata, tensors):
    """Encode the existing HEPTAPK3 transport with versioned v4 metadata."""
    output = bytearray(b"HEPTAPK3")

    def number(value):
        output.extend(struct.pack("<I", value))

    def string(value):
        data = value.encode("utf-8")
        number(len(data))
        output.extend(data)

    number(len(metadata))
    for key, value in sorted(metadata.items()):
        string(key)
        string(str(value))
    number(len(tensors))
    for key, tensor in sorted(tensors.items()):
        tensor = tensor.detach().to(device="cpu", dtype=torch.float64).contiguous()
        if not bool(torch.isfinite(tensor).all()):
            raise ValueError(f"Nonfinite tensor: {key}")
        string(key)
        number(tensor.ndim)
        for dimension in tensor.shape:
            number(dimension)
        number(tensor.numel())
        output.extend(tensor.numpy().astype("<f8", copy=False).tobytes())
    if len(output) > 64 * 1024 * 1024:
        raise ValueError("Packet exceeds native bound")
    output.extend(hashlib.sha256(output).hexdigest().encode("ascii"))
    return bytes(output)


def read_packet(data):
    if len(data) < 76 or len(data) > 64 * 1024 * 1024 + 64:
        raise ValueError("Invalid packet size")
    if hashlib.sha256(data[:-64]).hexdigest().encode("ascii") != data[-64:]:
        raise ValueError("Packet checksum mismatch")
    offset = 8
    if data[:8] != b"HEPTAPK3":
        raise ValueError("Unknown packet format")

    def take(length):
        nonlocal offset
        if length < 0 or offset + length > len(data) - 64:
            raise ValueError("Truncated packet")
        value = data[offset : offset + length]
        offset += length
        return value

    def number():
        return struct.unpack("<I", take(4))[0]

    def string():
        length = number()
        if length > 8192:
            raise ValueError("String bound")
        return take(length).decode("utf-8")

    metadata, tensors = {}, {}
    count = number()
    if count > 256:
        raise ValueError("Metadata bound")
    for _ in range(count):
        key, value = string(), string()
        if key in metadata:
            raise ValueError("Duplicate metadata")
        metadata[key] = value
    count = number()
    if count > 512:
        raise ValueError("Tensor bound")
    for _ in range(count):
        key, dimensions = string(), number()
        if key in tensors or dimensions > 8:
            raise ValueError("Tensor inventory")
        shape = tuple(number() for _ in range(dimensions))
        size = number()
        if math.prod(shape) != size or size > 4_000_000:
            raise ValueError("Tensor shape")
        values = struct.unpack(f"<{size}d", take(8 * size))
        tensor = torch.tensor(values, dtype=torch.float64).reshape(shape)
        if not bool(torch.isfinite(tensor).all()):
            raise ValueError("Nonfinite tensor")
        tensors[key] = tensor
    if offset != len(data) - 64:
        raise ValueError("Packet trailing bytes")
    if packet_bytes(metadata, tensors) != data:
        raise ValueError("Noncanonical packet")
    return metadata, tensors


@dataclass(frozen=True)
class DeliveryObservation:
    required_mask: int
    optional_mask: int
    budget_total: int
    budget_remaining: int
    task_digest: bytes
    cursors: tuple = (0, 0, 0, 0)
    committed: tuple = (b"", b"", b"", b"")

    def __post_init__(self):
        if (
            any(
                type(value) is not int
                for value in (
                    self.required_mask,
                    self.optional_mask,
                    self.budget_total,
                    self.budget_remaining,
                    *self.cursors,
                )
            )
            or type(self.task_digest) is not bytes
            or any(type(data) is not bytes for data in self.committed)
        ):
            raise ValueError("Owner observation types")
        selected = self.required_mask | self.optional_mask
        if (
            self.required_mask & self.optional_mask
            or not 0 < selected < 16
            or not 0 < self.budget_total < 2**64
            or not 0 <= self.budget_remaining <= self.budget_total
            or len(self.task_digest) != 32
            or not any(self.task_digest)
            or len(self.cursors) != 4
            or len(self.committed) != 4
            or sum(map(len, self.committed)) > 262144
        ):
            raise ValueError("Invalid owner observation")
        for index, (cursor, total) in enumerate(
            zip(self.cursors, TOTAL_UNITS, strict=True)
        ):
            if not 0 <= cursor <= total or (cursor and not selected & (1 << index)):
                raise ValueError("Prefix contradicts obligations")

    @property
    def remaining_fraction(self):
        return self.budget_remaining / self.budget_total

    def features(self):
        result = []
        required_units = required_remaining = 0
        for index, data in enumerate(self.committed):
            required = bool(self.required_mask & (1 << index))
            optional = bool(self.optional_mask & (1 << index))
            mean = sum(value / 255 for value in data) / max(1, len(data))
            variance = sum((value / 255 - mean) ** 2 for value in data) / max(
                1, len(data)
            )
            checksum = 2166136261
            for byte in data:
                checksum = ((checksum ^ byte) * 16777619) & 0xFFFFFFFF
            result.extend(
                (
                    self.cursors[index] / TOTAL_UNITS[index],
                    float(required),
                    float(optional),
                    len(data) / 262144,
                    mean,
                    variance,
                    checksum / 0xFFFFFFFF if data else 0,
                    float(bool(data)),
                )
            )
            suffix = data[-8:]
            result.extend([0.0] * (8 - len(suffix)))
            result.extend(value / 255 for value in suffix)
            if required:
                required_units += TOTAL_UNITS[index]
                required_remaining += TOTAL_UNITS[index] - self.cursors[index]
        result.extend(
            (
                self.remaining_fraction,
                1 - self.remaining_fraction,
                math.log1p(self.budget_total) / math.log1p(2**64 - 1),
                required_remaining / max(1, required_units),
            )
        )
        return result

    def wire(self):
        return (
            struct.pack(
                "<BBQQ",
                self.required_mask,
                self.optional_mask,
                self.budget_total,
                self.budget_remaining,
            )
            + self.task_digest
        )


def request_bytes(weights, public, state, prefix, command, observation):
    output = bytearray(b"HJREQV02" + b"\x05" * 32 + observation.wire())
    for blob in (weights, public, state, prefix):
        output.extend(struct.pack("<I", len(blob)))
        output.extend(blob)
    output.extend(command)
    return bytes(output)


def read_response(data):
    if len(data) < 145 or data[:8] != b"HJRESV01":
        raise ValueError("Response format")
    if hashlib.sha256(data[:-64]).hexdigest().encode("ascii") != data[-64:]:
        raise ValueError("Response checksum")
    offset = 73
    blobs = []
    for _ in range(2):
        if offset + 4 > len(data) - 64:
            raise ValueError("Truncated response length")
        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if length > 65536 or offset + length > len(data) - 64:
            raise ValueError("Response blob bound")
        blobs.append(data[offset : offset + length])
        offset += length
    if offset != len(data) - 64 or data[40] not in (0, 1):
        raise ValueError("Response trailing bytes or disposition")
    return {
        "state": blobs[0],
        "delta": blobs[1],
        "stopped": bool(data[40]),
        "phase_micros": struct.unpack_from("<4Q", data, 41),
    }


def framed_media(prefix):
    """Read v4 frames; concatenate each modality into its standard media file."""
    offset, cursors, content = 0, [0] * 4, [bytearray() for _ in range(4)]
    while offset < len(prefix):
        if prefix[offset : offset + 4] != b"HGC2" or offset + 17 > len(prefix):
            raise ValueError("Frame format")
        modality, start, units, length = struct.unpack_from("<BIII", prefix, offset + 4)
        offset += 17
        if (
            modality >= 4
            or not units
            or start != cursors[modality]
            or start + units > TOTAL_UNITS[modality]
            or offset + length > len(prefix)
        ):
            raise ValueError("Frame range")
        content[modality].extend(prefix[offset : offset + length])
        cursors[modality] += units
        offset += length
    return tuple(cursors), tuple(bytes(data) for data in content)
