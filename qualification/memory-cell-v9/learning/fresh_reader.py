"""Independent Python readback of real V9 artifacts, never a native-runtime claim.

``qualify --demo --output NEW_DIR`` runs the separate development qualification.
``read`` accepts one bounded JSON request on stdin containing an artifact path,
its digest, a support digest, and queries with no expected values. This branch
does not import a trainer. After NumPy initialization, an audit hook permits
data-file reads only from the named artifact. This is an auditable Python I/O
boundary, not an operating-system security sandbox.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sys
import time

import numpy as np


LIMIT = 16 * 1024 * 1024
NAMES = ("input_weights", "hidden_bias", "output_weights", "output_bias")
COMMON = {"schema", "kind", "address_profile", "numeric_profile", "dimension", "hidden",
          "threshold", "supports", "lineage_sources", "arrays", "parameter_sha256",
          "training_receipt_sha256"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate-json-field")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("nonfinite-json-value")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def valid_digest(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value) and value != "0" * 64)


def typed(kind, value):
    def integer(number, lower, upper):
        return type(number) is int and lower <= number <= upper

    if kind == "semantic":
        valid = (isinstance(value, dict) and set(value) == {"factor", "label"}
                 and integer(value["factor"], -1_000_000, 1_000_000)
                 and isinstance(value["label"], str) and 0 < len(value["label"].encode()) <= 256
                 and "\x00" not in value["label"])
    else:
        valid = (isinstance(value, dict) and set(value) == {"opcode", "bias", "limit"}
                 and value["opcode"] in ("identity", "add_bias", "multiply", "affine", "clamp")
                 and integer(value["bias"], -1_000_000, 1_000_000)
                 and integer(value["limit"], 0, 1_000_000))
    require(valid, "invalid-typed-value")


def model(raw):
    wire = decode(raw)
    require(isinstance(wire, dict), "invalid-artifact-object")
    byte = wire.get("schema") == "hepta.memory.byte-native.v9"
    if wire.get("schema") == "hepta.memory.associative-native.v1" and "catalog" not in wire:
        raise ValueError("value-catalog-required")
    extra = {"max_value_bytes"} if byte else {"catalog", "acceptance_enabled", "original_artifact_sha256"}
    require(set(wire) == COMMON | extra, "unexpected-artifact-fields")
    expected_schema = "hepta.memory.byte-native.v9" if byte else "hepta.memory.associative-native.v1"
    expected_profile = "hepta.memory.f32-f64-tanh-bytebits.v9" if byte else "hepta.memory.f32-weights-f64-tanh-softmax.v1"
    require(wire["schema"] == expected_schema and wire["numeric_profile"] == expected_profile
            and wire["address_profile"] == "hepta.memory.sha256-shake256-f64.v1"
            and wire["kind"] in ("semantic", "procedure"), "unknown-model-profile")
    dimension, hidden = wire["dimension"], wire["hidden"]
    require(type(dimension) is int and 8 <= dimension <= 256
            and type(hidden) is int and 1 <= hidden <= 64, "model-dimension-bound")
    require(type(wire["threshold"]) in (int, float) and math.isfinite(wire["threshold"])
            and 0.5 <= wire["threshold"] <= 1, "threshold-bound")
    supports = wire["supports"]
    require(isinstance(supports, dict) and 1 <= len(supports) <= 4096, "support-bound")
    for address, sources in supports.items():
        require(valid_digest(address) and isinstance(sources, list) and 1 <= len(sources) <= 128
                and all(valid_digest(source) for source in sources)
                and sources == sorted(set(sources)), "support-provenance-invalid")
    require(wire["lineage_sources"] == sorted({s for sources in supports.values() for s in sources})
            and valid_digest(wire["training_receipt_sha256"]), "lineage-invalid")
    if byte:
        require(type(wire["max_value_bytes"]) is int and wire["max_value_bytes"] == 128, "byte-bound")
        output = 1040
    else:
        require(isinstance(wire["catalog"], list) and 1 <= len(wire["catalog"]) <= 4096
                and type(wire["acceptance_enabled"]) is bool
                and valid_digest(wire["original_artifact_sha256"]), "catalog-bound")
        for value in wire["catalog"]:
            typed(wire["kind"], value)
        output = len(wire["catalog"])
    shapes = ((dimension, hidden), (hidden,), (hidden, output), (output,))
    require(isinstance(wire["arrays"], dict) and set(wire["arrays"]) == set(NAMES), "tensor-inventory")
    arrays = []
    for name, shape in zip(NAMES, shapes):
        values = wire["arrays"][name]
        require(isinstance(values, list) and len(values) == math.prod(shape)
                and all(type(v) in (int, float) for v in values), "tensor-shape")
        array = np.asarray(values, dtype="<f4").reshape(shape)
        require(np.isfinite(array).all(), "nonfinite-tensor")
        arrays.append(array)
    require(digest(b"".join(a.tobytes() for a in arrays)) == wire["parameter_sha256"], "parameter-digest-mismatch")
    return wire, [a.astype(np.float64) for a in arrays]


def predict(wire, arrays, key):
    address = digest(key.encode())
    result = {"value": None, "confidence": 0.0, "support_ids": [], "abstain": "outside-written-support"}
    if address not in wire["supports"]:
        return result
    raw = hashlib.shake_256(bytes.fromhex(address)).digest(wire["dimension"])
    x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 127.5) / 73.9002706355 / np.sqrt(wire["dimension"])
    A, a, B, b = arrays
    logits = np.tanh(x @ A + a) @ B + b
    result["abstain"] = "below-selection-threshold"
    if "catalog" in wire:
        probabilities = np.exp(logits - logits.max())
        probabilities /= probabilities.sum()
        index = int(probabilities.argmax())
        result["confidence"] = float(probabilities[index])
        if not wire["acceptance_enabled"] or result["confidence"] < wire["threshold"]:
            return result
        value = wire["catalog"][index]
    else:
        result["confidence"] = float((1 / (1 + np.exp(-np.abs(logits)))).min())
        if result["confidence"] < wire["threshold"]:
            return result
        data = np.packbits((logits >= 0).astype(np.uint8)).tobytes()
        length = int.from_bytes(data[:2], "big")
        result["abstain"] = "invalid-typed-bytes"
        if not 1 <= length <= 128 or any(data[2 + length:]):
            return result
        try:
            value = decode(data[2:2 + length])
            typed(wire["kind"], value)
            canonical_utf8 = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
            if canonical_utf8 != data[2:2 + length]:
                return result
        except (ValueError, TypeError, UnicodeError):
            return result
    result.update(value=value, support_ids=wire["supports"][address], abstain=None)
    return result


def validate_request(frame):
    require(isinstance(frame, dict) and set(frame) == {
        "schema", "artifact_path", "artifact_sha256", "support_sha256", "queries"}, "reader-request-fields")
    require(frame["schema"] == "hepta.memory.fresh-python-read.v1"
            and valid_digest(frame["artifact_sha256"]) and valid_digest(frame["support_sha256"]), "reader-request-binding")
    require(isinstance(frame["artifact_path"], str) and Path(frame["artifact_path"]).is_absolute(), "artifact-absolute-path")
    require(isinstance(frame["queries"], list) and 1 <= len(frame["queries"]) <= 128, "query-count-bound")
    for query in frame["queries"]:
        require(isinstance(query, dict) and set(query) == {"id", "key"}, "reader-query-fields")
        require(all(isinstance(query[k], str) and 0 < len(query[k].encode()) <= 4096 for k in ("id", "key")), "query-text-bound")
    require(len({query["id"] for query in frame["queries"]}) == len(frame["queries"]), "duplicate-query-id")


def serve():
    began, cpu = time.monotonic_ns(), time.process_time_ns()
    raw = sys.stdin.buffer.read(262145)
    receipt = {"schema": "hepta.memory.fresh-python-read-result.v1", "pid": os.getpid(),
               "parent_pid": os.getppid(), "started_monotonic_ns": began,
               "execution_path": "independent-python-f64-mirror", "native_runtime_executed": False,
               "request_sha256": digest(raw), "request_bytes": len(raw), "data_files_read": []}
    try:
        require(0 < len(raw) <= 262144, "reader-request-bound")
        frame = decode(raw)
        validate_request(frame)
        artifact = Path(frame["artifact_path"]).resolve(strict=True)
        require(artifact.is_file() and 0 < artifact.stat().st_size <= LIMIT, "artifact-file-bound")

        def audit(event, args):
            if event == "open":
                path, _mode, flags = args
                if isinstance(path, int):
                    raise PermissionError("reader-open-file-descriptor-forbidden")
                if Path(os.fsdecode(path)).absolute() != artifact or flags & os.O_ACCMODE != os.O_RDONLY:
                    raise PermissionError("reader-data-file-not-allowlisted")
                receipt["data_files_read"].append(str(artifact))

        sys.addaudithook(audit)
        load_started = time.monotonic_ns()
        with artifact.open("rb") as handle:
            data = handle.read(LIMIT + 1)
        require(0 < len(data) <= LIMIT, "artifact-file-bound")
        require(digest(data) == frame["artifact_sha256"], "artifact-digest-mismatch")
        wire, arrays = model(data)
        require(digest(canonical(wire["supports"])) == frame["support_sha256"], "support-digest-mismatch")
        loaded = time.monotonic_ns()
        readouts = [{"id": q["id"], "key": q["key"], **predict(wire, arrays, q["key"])} for q in frame["queries"]]
        receipt.update(artifact_admitted=True, artifact_sha256=digest(data), artifact_bytes=len(data),
                       parameter_sha256=wire["parameter_sha256"], support_sha256=frame["support_sha256"],
                       kind=wire["kind"], catalog_contains_explicit_values="catalog" in wire,
                       parameter_bytes=sum(a.size * 4 for a in arrays),
                       source_support_entries=len(wire["supports"]), readouts=readouts,
                       load_wall_ns=loaded-load_started, compute_wall_ns=time.monotonic_ns()-loaded)
    except (OSError, ValueError, TypeError, KeyError) as error:
        receipt.update(artifact_admitted=False, rejection=str(error), readouts=[])
    receipt.update(wall_ns_before_response=time.monotonic_ns()-began, cpu_ns_before_response=time.process_time_ns()-cpu,
                   peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   peak_rss_unit="bytes" if sys.platform == "darwin" else "KiB",
                   training_modules_loaded=any(n == "training" or n.startswith(("learning.", "v6.")) for n in sys.modules),
                   target_fields_allowed=False, filesystem_security_sandbox=False)
    sys.stdout.buffer.write(canonical(receipt) + b"\n")
    return 0 if receipt["artifact_admitted"] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("read", "qualify", "train"))
    args, remaining = parser.parse_known_args()
    if args.mode == "read":
        require(not remaining, "read-mode-has-no-extra-inputs")
        return serve()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fresh_reader_support import main as support_main
    return support_main(args.mode, remaining)


if __name__ == "__main__":
    raise SystemExit(main())
