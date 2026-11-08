"""Deterministic Mean-law mirror of native v4 commits, including STOP flush.

Bytes and codec quantization are discrete, so no gradient is claimed through
this boundary. Continuous generator state remains connected to its graph.
This deliberately does not implement the native SplitMix sampler profile.
"""

from dataclasses import replace
import math
import struct

import torch

from scripts.joint_generation_v4_io import TOTAL_UNITS
from scripts.joint_generation_v4_model import MODALITIES, valid_utf8_next


PPM_HEADER = b"P6\n16 16\n255\n"
Y4M_HEADER = b"YUV4MPEG2 W16 H16 F4:1 Ip A1:1 C444\n"
WAVE_HEADER = (
    b"RIFF"
    + struct.pack("<I", 36 + 2048)
    + b"WAVEfmt "
    + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
    + b"data"
    + struct.pack("<I", 2048)
)


def _sigmoid(value):
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1 + exponential)


def _media_payload(generator, state, modality, start, units):
    values = generator.outputs(state)[MODALITIES[modality]].detach().flatten().tolist()
    if modality == 1:
        samples = [round(math.tanh(value) * 32767) for value in values]
        raw = struct.pack(f"<{len(samples)}h", *samples)
        return (WAVE_HEADER if start == 0 else b"") + raw[
            2 * start : 2 * (start + units)
        ]
    samples = [round(_sigmoid(value) * 255) for value in values]
    frames = 4 if modality == 2 else 1
    raw = bytes(
        samples[frame * 768 + channel * 256 + pixel]
        for frame in range(frames)
        for pixel in range(256)
        for channel in range(3)
    )
    if modality == 0:
        return (PPM_HEADER if start == 0 else b"") + raw[
            48 * start : 48 * (start + units)
        ]
    output = bytearray(Y4M_HEADER if start == 0 else b"")
    for frame in range(start, start + units):
        output.extend(b"FRAME\n")
        planes = bytearray(768)
        for pixel in range(256):
            offset = frame * 768 + 3 * pixel
            red, green, blue = (value / 255 for value in raw[offset : offset + 3])
            planes[pixel] = min(
                235, max(16, round(16 + 65.481 * red + 128.553 * green + 24.966 * blue))
            )
            planes[256 + pixel] = min(
                240, max(16, round(128 - 37.797 * red - 74.203 * green + 112 * blue))
            )
            planes[512 + pixel] = min(
                240, max(16, round(128 + 112 * red - 93.786 * green - 18.214 * blue))
            )
        output.extend(planes)
    return bytes(output)


def _text_payload(generator, state, units):
    output = bytearray()
    for _ in range(units):
        scalar = bytearray()
        while True:
            logits = generator.emissions["text"](
                torch.cat((state.shared, state.text_hidden), -1)
            )
            legal = [index for index in range(256) if valid_utf8_next(scalar, index)]
            values = logits.detach().flatten().tolist()
            byte = max(legal, key=values.__getitem__)  # First maximum, as in Rust.
            state = generator.consume_byte(state, byte)
            scalar.append(byte)
            try:
                scalar.decode("utf-8")
            except UnicodeDecodeError:
                if len(scalar) == 4:
                    raise ValueError("Invalid UTF-8 transition")
            else:
                break
        output.extend(scalar)
        state = replace(state, text_units=state.text_units + 1)
    return state, bytes(output)


def commit_mean(generator, state, observation, modality, units):
    """Return the immutable successor and a genuine HGC2 standard-codec frame."""
    if type(modality) is not int or not 0 <= modality < 4 or type(units) is not int:
        raise ValueError("Commit domain")
    start = observation.cursors[modality]
    if (
        not (observation.required_mask | observation.optional_mask) & (1 << modality)
        or units <= 0
        or start + units > TOTAL_UNITS[modality]
    ):
        raise ValueError("Commit outside admitted output")
    with torch.no_grad():
        if modality == 3:
            if (
                start != state.text_units
                or len(observation.committed[3]) != state.text_bytes
            ):
                raise ValueError("Text decoder/prefix mismatch")
            state, payload = _text_payload(generator, state, units)
        else:
            payload = _media_payload(generator, state, modality, start, units)
    cursors, committed = list(observation.cursors), list(observation.committed)
    cursors[modality] += units
    committed[modality] += payload
    observation = replace(
        observation, cursors=tuple(cursors), committed=tuple(committed)
    )
    frame = (
        b"HGC2" + struct.pack("<BIII", modality, start, units, len(payload)) + payload
    )
    return state, observation, frame


def flush_mean(generator, state, observation):
    """Flush required modalities and optional modalities already committed."""
    delta = bytearray()
    for index, total in enumerate(TOTAL_UNITS):
        if (
            not observation.required_mask & (1 << index)
            and observation.cursors[index] == 0
        ):
            continue
        units = total - observation.cursors[index]
        if units:
            state, observation, frame = commit_mean(
                generator, state, observation, index, units
            )
            delta.extend(frame)
    return state, observation, bytes(delta)
