"""Independent byte, public-history and native-receipt verification helpers.

No fitting, model generation, primary evaluator or runtime selection is called.
The original native kernel is replayed through its frozen transport only.
"""

import hashlib
import io
import json

import numpy as np
from PIL import Image
import torch

Q24 = 1 << 24
TRANSFORMS = {"raw": None, "common_standardization_k1": 1,
              "common_standardization_k2": 2, "common_standardization_k4": 4}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def object_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def matrix_sha(value):
    return hashlib.sha256(np.asarray(value, dtype="<f8").tobytes()).hexdigest()


def read_cas(archive, receipt, referenced):
    require(receipt["archive"] == "media.zip", "Unregistered media archive")
    require(set(receipt["paths"]) == set(receipt["sha256"]) == {"image", "text"}, "Media role inventory")
    raw, hashes = {}, {}
    for kind, suffix in (("image", "png"), ("text", "txt")):
        identity = receipt["sha256"][kind]
        require(isinstance(identity, str) and len(identity) == 64 and
                set(identity) <= set("0123456789abcdef"), "Invalid media SHA256")
        name = f"sha256/{identity[:2]}/{identity}.{suffix}"
        require(receipt["paths"][kind] == name, "Media path is not its content address")
        entry = archive.getinfo(name)
        require(not entry.is_dir() and entry.file_size <= 1_000_000, "Invalid media entry size")
        raw[kind] = archive.read(name)
        hashes[kind] = hashlib.sha256(raw[kind]).hexdigest()
        require(hashes[kind] == identity, "Delivered media bytes differ from receipt")
        referenced.add(name)
    require(raw["image"].startswith(b"\x89PNG\r\n\x1a\n"), "Delivered image signature differs")
    with Image.open(io.BytesIO(raw["image"])) as picture:
        require(picture.format == "PNG" and picture.mode == "L" and picture.size == (56, 28),
                "Delivered image profile differs")
        pixels = np.array(picture, dtype=np.uint8, copy=True)
    caption = raw["text"].decode("utf-8", errors="strict")
    require(len(caption) <= 4096, "Delivered caption is oversized")
    return torch.from_numpy(pixels).reshape(1, 1, 28, 56).float() / 255, caption, hashes


def normalise(x, normalizer, width):
    mean, scale = np.asarray(normalizer["mean"]), np.asarray(normalizer["scale"])
    require(mean.shape == scale.shape == (width,) and np.isfinite(mean).all()
            and np.isfinite(scale).all() and np.all(scale >= 1e-6), "Invalid frozen normalizer")
    return (x - mean) / scale


def transformed_inputs(readout, x0, x1):
    x0, x1 = np.asarray(x0, dtype=np.float64), np.asarray(x1, dtype=np.float64)
    require(x0.shape == x1.shape and x0.ndim == 2 and x0.shape[1] == 8 and
            all(np.isfinite(x).all() and np.all((x >= 0) & (x <= 1)) for x in (x0, x1)),
            "Public observation shape or range differs")
    transform = readout["transform"]
    require(transform["name"] in TRANSFORMS and TRANSFORMS[transform["name"]] == transform["k"],
            "Unregistered common input transform")
    if transform["k"] is None:
        return x0, x1
    return tuple((np.clip(normalise(x, transform["normalizer"], 8) / transform["k"], -1, 1) + 1) / 2
                 for x in (x0, x1))


def runtime_features(readout, x0, x1, native=None):
    x0, x1 = np.asarray(x0, dtype=np.float64), np.asarray(x1, dtype=np.float64)
    u0, u1 = transformed_inputs(readout, x0, x1)
    raw = np.column_stack((x0, x1))
    family = readout["family"]
    if family in {"pure_native40", "raw16_native24"}:
        require(readout["representation"] == "native" and native is not None and
                native.shape == (len(x0), 40) and np.isfinite(native).all(), "Native feature family differs")
        if family == "pure_native40":
            return native
        indices = np.asarray(readout["native_selector"]["indices"])
        require(indices.shape == (24,) and np.issubdtype(indices.dtype, np.integer)
                and len(set(indices.tolist())) == 24 and np.all((indices >= 0) & (indices < 40)),
                "Native hybrid coordinate selection differs")
        return np.column_stack((raw, native[:, indices]))
    require(readout["representation"] == "history" and native is None, "History feature family differs")
    if family == "original_history40":
        return np.column_stack((u0, u1, u0**2, u1**2, u1-u0))
    require(family == "raw16_rff24", "Unregistered history family")
    spec = readout["fourier"]
    weights = np.asarray(spec["weights"], dtype=np.float64)
    expected = np.random.default_rng(271029).normal(size=(16, 12)) / np.sqrt(16)
    require(spec["seed"] == 271029 and np.array_equal(weights, expected)
            and matrix_sha(weights) == spec["weight_sha256"], "Fourier basis differs from the registered draw")
    phase = normalise(np.column_stack((u0, u1)), spec["normalizer"], 16) @ weights
    return np.column_stack((raw, np.cos(phase)/np.sqrt(12), np.sin(phase)/np.sqrt(12)))


def actions_from_features(readout, features):
    head = readout["head"]
    coefficients = np.asarray(head["coefficient"], dtype=np.float64)
    require(features.shape[1] == 40 and coefficients.shape == (41, 5)
            and np.isfinite(coefficients).all() and head["parameter_count"] == 205,
            "Frozen head dimensions differ")
    x = np.column_stack((normalise(features, head["normalizer"], 40), np.ones(len(features))))
    values = x @ coefficients
    require(np.isfinite(values).all(), "Frozen head produced nonfinite values")
    return values.argmax(axis=1)


def untimed(value):
    if isinstance(value, dict):
        return {key: untimed(item) for key, item in value.items()
                if key not in {"native_ns", "bridge_roundtrip_ns", "ffi_run_ns"}}
    return [untimed(item) for item in value] if isinstance(value, list) else value


def native_request(first, second, prefix, index, reset):
    raw = np.asarray([first, second], dtype="<f8")
    return {"case": f"{prefix}:{index:08d}", "readback_digest": hashlib.sha256(raw.tobytes()).hexdigest(),
            "features_q24": np.rint((2*raw[0]-1)*Q24).astype(np.int64).tolist(),
            "next_features_q24": np.rint((2*raw[1]-1)*Q24).astype(np.int64).tolist(),
            "reset_before_readout": reset}


def native_records(records, u0, u1, prefix, reset, bridge, summary, source_pin):
    require(len(records) == len(u0) == len(u1), "Native receipt count differs")
    native, kernel_ns, roundtrip_ns, ffi_ns = [], 0, 0, 0
    for index, (record, first, second) in enumerate(zip(records, u0, u1, strict=True)):
        request = native_request(first, second, prefix, index, reset)
        require(record["batch_id"] == prefix and record["case_index"] == index and record["request"] == request
                and record["public_feature_sha256"] == request["readback_digest"], "Native request input binding differs")
        require(record["schema"] == "hepta.field-bridge.public-feature-receipt.v1" and
                record["public_feature_byte_encoding"] == "2x8 little-endian float64 row-major, first then second",
                "Native public feature encoding differs")
        receipt = record["native"]
        require(receipt["case"] == request["case"] and receipt["binary_sha256"] == bridge.binary_sha256
                and receipt["source_pin"] == source_pin and receipt["feature_count"] == 8
                and receipt["original_sparse_tick_calls"] == len(receipt["ticks"]) == 2,
                "Native receipt identity or width differs")
        require(receipt["native_owner_integration"] is False and receipt["next_public_observation_provided"] is True
                and receipt["checkpoint_reset_intervention"] == reset, "Native execution boundary differs")
        for stage, tick in enumerate(receipt["ticks"]):
            qs = request["features_q24" if stage == 0 else "next_features_q24"]
            drive = [v for q in qs for v in (max(-q, 0), max(q, 0))] + [Q24//4, 0, 0, 0]
            require(tick["drive_q24"] == drive and tick["stage"] == stage and
                    tick["sequence"] == (1 if reset or stage == 0 else 2) and
                    tick["logical_clock_micros"] == stage+1 and tick["fresh_public_observation"] is True,
                    "Native event/clock mapping differs")
            require(tick["authority"] == "DENY_ALL" and tick["requires_calibration"] is True and
                    tick["native_owner_integration"] is False and all(len(tick[k]) == 20
                    for k in ("activation_q24", "eligibility_q24", "threshold_q24")), "Native authority/state width differs")
        first_tick, second_tick = receipt["ticks"]
        require(second_tick["checkpoint_before"] == first_tick["checkpoint_before" if reset else "checkpoint_after"],
                "Native checkpoint chain differs")
        require(untimed(bridge.tick_pair(**request)) == untimed(receipt), "Native deterministic full-receipt replay differs")
        native.append(np.asarray(second_tick["activation_q24"] + second_tick["eligibility_q24"], dtype=float)/Q24)
        kernel_ns += sum(tick["native_ns"] for tick in receipt["ticks"])
        roundtrip_ns += receipt["bridge_roundtrip_ns"]
        ffi_ns += receipt["ffi_run_ns"]
    native = np.asarray(native)
    require(summary["rows"] == len(records) and summary["original_sparse_tick_calls"] == 2*len(records)
            and summary["feature_width"] == 40 and summary["reset_before_readout"] == reset,
            "Native batch count/profile differs")
    require(summary["native_ns"] == kernel_ns and summary["bridge_roundtrip_ns"] == roundtrip_ns
            and summary["ffi_run_ns"] == ffi_ns and summary["feature_matrix_sha256"] == matrix_sha(native),
            "Native batch state/timing aggregate differs")
    require(summary["target_accesses"] == 0 and summary["authority"] == "DENY_ALL" and
            summary["native_owner_integration"] is False and summary["complete_receipts_written"] is True,
            "Native batch execution boundary differs")
    return native
