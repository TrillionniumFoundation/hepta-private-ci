"""Exact existing native linear-Head framing, with no Rust parser changes."""

import hashlib
import io
import json
import math
import struct
import zipfile


MAGIC = b"HEPTA-CELL-HEAD-BUNDLE-V1\0"
FEATURE_HASHES = ("encoder_digest", "checkpoint_digest", "preprocessing_digest",
                  "scope_digest", "purpose_digest")
PIN_HASHES = ("manifest_digest", "weights_digest", "source_frontier_digest",
              "training_dataset_digest", "calibration_dataset_digest",
              "training_code_digest", "runtime_tuple_digest", "trained_tensor_digest")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def npz_tensors(raw, shapes):
    """Match native STORED ZIP / exact NPY-v1-f32 bounds before decoding data."""
    require(22 <= len(raw) <= 16 * 1024 * 1024 and raw[:4] == b"PK\x03\x04", "archive boundary")
    trailer = struct.unpack("<4sHHHHIIH", raw[-22:])
    require(trailer[:5] == (b"PK\x05\x06", 0, 0, len(shapes), len(shapes))
            and trailer[-1] == 0 and trailer[5] + trailer[6] == len(raw) - 22,
            "bounded archive directory")
    offset = trailer[6]
    for _ in shapes:
        header = raw[offset:offset + 46]
        require(len(header) == 46 and header[:4] == b"PK\x01\x02", "central header")
        flags, method = struct.unpack_from("<HH", header, 8)
        name_size, extra_size, comment_size = struct.unpack_from("<HHH", header, 28)
        require(flags == method == 0 and 1 <= name_size <= 64, "native ZIP flags or storage")
        offset += 46 + name_size + extra_size + comment_size
        require(offset <= len(raw) - 22, "central header length")
    require(offset == len(raw) - 22, "extra directory data")
    values = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) == len(shapes)
                and {entry.filename for entry in entries} == {name + ".npy" for name in shapes},
                "tensor inventory")
        require(sum(entry.file_size for entry in entries) <= 16 * 1024 * 1024, "expanded NPZ budget")
        for name, shape in sorted(shapes.items()):
            info = archive.getinfo(name + ".npy")
            require(info.compress_type == zipfile.ZIP_STORED and info.flag_bits == 0
                    and info.compress_size == info.file_size
                    and ((info.external_attr >> 16) & 0o170000) in (0, 0o100000),
                    "stored regular tensor required")
            encoded = archive.read(info)
            require(len(encoded) >= 10 and encoded[:8] == b"\x93NUMPY\x01\x00", "NPY v1 required")
            length = struct.unpack_from("<H", encoded, 8)[0]
            require(1 <= length <= 1024 and len(encoded) >= 10 + length, "NPY header bound")
            dimensions = ", ".join(map(str, shape)) + ("," if len(shape) == 1 else "")
            prefix = ("{'descr': '<f4', 'fortran_order': False, 'shape': (" + dimensions + "), }").encode()
            header = encoded[10:10 + length]
            require(header.startswith(prefix) and header[-1:] == b"\n"
                    and header[len(prefix):-1].strip(b" ") == b"", "native NPY header")
            data = encoded[10 + length:]
            require(len(data) == math.prod(shape) * 4
                    and all(math.isfinite(value) for value, in struct.iter_unpack("<f", data)),
                    "tensor size or finite values")
            values[name] = data
    return values


def verify_weights(weights, report):
    config, width = report["config"], report["feature_width"]
    require((width, config["task_count"], config["state_width"], config["adapter_rank"])
            == (384, 4, 8, 4) and config["mode"] == "linear", "fixed procedural linear profile")
    shapes = {"gate.weight": (1, width + 8), "gate.bias": (1,),
              "down.weight": (4, width), "up.weight": (width, 4)}
    for name, count in (("task_head", 4), ("action_head", 4), ("value_head", 1), ("uncertainty_head", 1)):
        shapes[name + ".weight"], shapes[name + ".bias"] = (count, width), (count,)
    values = npz_tensors(weights, shapes)
    require(all(value == 0.0 for value, in struct.iter_unpack("<f", values["up.weight"])),
            "native linear profile requires exactly zero up.weight")
    digest = hashlib.sha256()
    for name, data in sorted(values.items()):
        digest.update(canonical([name, list(shapes[name]), "float32"]))
        digest.update(data)
    require(digest.hexdigest() == report["trained_tensor_sha256"], "trained tensor digest")
    require(sum(len(value) // 4 for value in values.values()) == report["resident_parameter_count"] == 7315,
            "resident parameter accounting")
    return {name: {"shape": shapes[name], "bytes": len(data), "sha256": sha(data)}
            for name, data in sorted(values.items())}


def feature_identity(identity, width):
    return {"encoder_digest": identity["encoder_sha256"],
            "checkpoint_digest": sha(identity["checkpoint_revision"].encode()),
            "preprocessing_digest": identity["preprocess_sha256"],
            "scope_digest": sha(identity["scope_id"].encode()),
            "purpose_digest": sha(identity["purpose"].encode()),
            "generation": identity["generation"], "revocation_epoch": identity["revocation_epoch"],
            "width": width}


def source_records_digest(sources):
    return sha(b"hepta.cell-head-input-sources.v1\0" + struct.pack("<Q", len(sources))
               + b"".join(bytes.fromhex(source) for source in sources))


def frame_bundle(manifest, weights, feature, pins):
    require(0 < len(manifest) <= 2 * 1024 * 1024 and 0 < len(weights) <= 16 * 1024 * 1024,
            "native payload budget")
    require(pins["manifest_digest"] == sha(manifest) and pins["weights_digest"] == sha(weights),
            "payload pins")
    feature_bytes = b"".join(bytes.fromhex(feature[key]) for key in FEATURE_HASHES)
    feature_bytes += struct.pack("<QQQ", feature["generation"], feature["revocation_epoch"], feature["width"])
    bundle = (MAGIC + feature_bytes + b"".join(bytes.fromhex(pins[key]) for key in PIN_HASHES)
              + struct.pack("<QQ", len(manifest), len(weights)) + manifest + weights)
    return bundle, {"feature": feature, **pins, "artifact_digest": sha(bundle),
                    "compatibility_digest": sha(b"hepta.cell-head-feature.v1\0" + feature_bytes),
                    "schema_profile_digest": sha(MAGIC)}
