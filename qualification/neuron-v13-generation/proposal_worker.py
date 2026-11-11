"""One bounded V13 phase on host-pinned bytes; no owner, training or adoption.

The host invokes verification and inference in separate owned processes. The
inference process cannot receive the source snapshot or training dataset. A
successful standalone inference response does not itself attest learning closure.
"""

import hashlib
import io
import json
from pathlib import Path
import resource
import struct
import sys
import tempfile
import time
import types


SCHEMA = "hepta.v13.process.v1"
RESULT_SCHEMA = "hepta.v13.process-result.v1"
MAX_HEADER = 32768
MAX_TRANSFER = 512 * 1024 * 1024
MAX_TASK = 8192
MAX_TEXT = 4096
MAX_RESULT = 65536
MAX_RESPONSE = 131072
SOURCE_HASHES = {
    "bounded_npz.py": "b9041cf4fa777396a1a8492e404e3a655016c347cddb90b3af00aeefaf23ca48",
    "closure_common.py": "7c552c5ff7b961f52eb9509909a203ddacc50aad99e62b66dfa2e8bbacf8a6fe",
    "closure_inputs.py": "6b05e2bc74e9f1de883f7e79b9bde603ce7e62fefb22e9133ca3757899d0e6c0",
    "closure_io.py": "24d7f1bfe01a9c2900521f84f271fbb8f652af0bded2654de43fc1fc060a4ce3",
    "verify_closure.py": "eccb2715aabbc06f0a578175e52ce105905a8326c1258190089aba519f238876",
    "PROVENANCE.json": "243f653290d76778ffeab9f2d44534a5a11e22f386d7d20b1f6f024e66eb341a",
    "reference/adapter.py.source": "f4c3b03dd22c4a5e7a27459348ba673842060624c6f983e9211112a49bfccba9",
    "reference/backend.py.source": "47b18cca113cf50ee47bb67032083abb39c44fe151410be792888d3abea55a53",
    "reference/download_model.py.source": "fd0a7e1ba831c4f2929ee8d29d22495c61ecfdbf7ceee3daec9f5110ff09c0f7",
    "reference/lifecycle.py.source": "0cb9ce6a732f5fa3156ebc5c28776e3eb241153f7ade3286938965317b9c50eb",
    "reference/tasks.py.source": "b2e9942631aa645b3e9e2d77ecd7bb8092fa4c7a2a3fa96efae0b9e6bbb49b54",
}
ENCODER_SIZES = {
    "onnx/model.onnx": 90405214,
    "tokenizer.json": 466247,
    "config.json": 612,
    "sentence_bert_config.json": 53,
    "modules.json": 349,
    "1_Pooling/config.json": 190,
    "tokenizer_config.json": 350,
    "special_tokens_map.json": 112,
}
LEARNING_MEMBERS = {"weights", "optimizer", "rng", "sampler", "training_cursor"}
INFERENCE_SOURCES = {
    f"reference/{name}.py.source"
    for name in ("adapter", "backend", "download_model", "tasks")
}
LAST_NATIVE_CLOCK = 0


class NativeDeadline(TimeoutError):
    pass


def check_clock(header):
    global LAST_NATIVE_CLOCK
    now = time.clock_gettime_ns(time.CLOCK_BOOTTIME) // 1000
    if (
        now <= 0
        or now < header["clock"]["admitted_at_micros"]
        or now < LAST_NATIVE_CLOCK
    ):
        raise ValueError("native monotonic epoch differs")
    LAST_NATIVE_CLOCK = now
    if now >= header["clock"]["deadline_micros"]:
        raise NativeDeadline("native entry deadline expired")


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("non-finite JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError("unexpected fields")


def digest(value):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("invalid digest")
    return value


def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid integer bound")
    return value


def exact(stream, length):
    chunks = bytearray()
    while len(chunks) < length:
        block = stream.read(min(65536, length - len(chunks)))
        if not block:
            raise ValueError("truncated phase input")
        chunks.extend(block)
    return bytes(chunks)


def expected_files(mode):
    names = SOURCE_HASHES.keys() if mode == "verify" else INFERENCE_SOURCES
    result = {"vendor/" + name: 65536 for name in names}
    if mode == "verify":
        del result["vendor/reference/tasks.py.source"]
    result.update({"encoder/" + name: size for name, size in ENCODER_SIZES.items()})
    result.update({"model.npz": 64 * 1024 * 1024, "encoder.json": 131072})
    if mode == "verify":
        result.update(
            {
                "sources.json": 2 * 1024 * 1024,
                "training.npz": 128 * 1024 * 1024,
                "release.json": 131072,
            }
        )
    return result


def validate_task(task):
    keys(task, {"schema", "text", "payload"})
    if task["schema"] != "hepta.v13.task-input.v1":
        raise ValueError("unsupported task schema")
    if (
        not isinstance(task["text"], str)
        or not 1 <= len(task["text"].encode()) <= MAX_TEXT
    ):
        raise ValueError("text exceeds bound")
    if len(canonical(task)) > MAX_TASK or len(canonical(task["payload"])) > 16384:
        raise ValueError("task exceeds bound")


def read_phase(stream, directory, progress, received):
    length = struct.unpack("<I", exact(stream, 4))[0]
    integer(length, 1, MAX_HEADER)
    header = strict_json(exact(stream, length))
    keys(
        header,
        {
            "schema",
            "mode",
            "request_digest",
            "binding",
            "task",
            "limits",
            "assets",
            "clock",
        },
    )
    if header["schema"] != SCHEMA or header["mode"] not in ("verify", "infer"):
        raise ValueError("unsupported phase")
    digest(header["request_digest"])
    keys(header["clock"], {"admitted_at_micros", "deadline_micros"})
    admitted = integer(header["clock"]["admitted_at_micros"], 1, (1 << 64) - 1)
    integer(header["clock"]["deadline_micros"], admitted + 1, (1 << 64) - 1)
    received["header"] = header
    binding = header["binding"]
    keys(
        binding,
        {
            "checkpoint_sha256",
            "state_sha256",
            "encoder_hash",
            "source_version",
            "data_id",
            "learning",
        },
    )
    for name in set(binding) - {"learning"}:
        digest(binding[name])
    keys(binding["learning"], LEARNING_MEMBERS)
    for value in binding["learning"].values():
        digest(value)
    limits = header["limits"]
    keys(limits, {"cpu_seconds", "address_space_bytes"})
    cpu = integer(limits["cpu_seconds"], 1, 60)
    address = integer(limits["address_space_bytes"], 1, 4 * 1024**3)
    for kind, value in (
        (resource.RLIMIT_CPU, cpu),
        (resource.RLIMIT_AS, address),
        (resource.RLIMIT_FSIZE, 128 * 1024**2),
        (resource.RLIMIT_CORE, 0),
    ):
        _, inherited = resource.getrlimit(kind)
        ceiling = (
            value if inherited == resource.RLIM_INFINITY else min(value, inherited)
        )
        resource.setrlimit(kind, (ceiling, ceiling))
    check_clock(header)
    allowed = expected_files(header["mode"])
    if not isinstance(header["assets"], list) or len(header["assets"]) != len(allowed):
        raise ValueError("asset inventory differs")
    seen, total = set(), 0
    for asset in header["assets"]:
        keys(asset, {"name", "bytes", "sha256"})
        name = asset["name"]
        if name not in allowed or name in seen:
            raise ValueError("unknown or repeated asset")
        seen.add(name)
        size = integer(asset["bytes"], 1, allowed[name])
        expected = digest(asset["sha256"])
        if name.startswith("vendor/") and expected != SOURCE_HASHES[name[7:]]:
            raise ValueError("reference source pin differs")
        total += size
        if total > MAX_TRANSFER:
            raise ValueError("input transfer exceeds bound")
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        hashed, left = hashlib.sha256(), size
        with target.open("xb") as output:
            while left:
                check_clock(header)
                block = exact(stream, min(left, 65536))
                output.write(block)
                hashed.update(block)
                left -= len(block)
                progress["staged_bytes"] += len(block)
        if hashed.hexdigest() != expected:
            raise ValueError("asset bytes differ")
    if seen != set(allowed) or stream.read(1):
        raise ValueError("incomplete inventory or trailing bytes")
    if header["mode"] == "verify":
        if header["task"] is not None:
            raise ValueError("verification cannot receive a task")
    else:
        validate_task(header["task"])
    return header


def check_binding(closure, expected):
    actual = {
        "checkpoint_sha256": closure["checkpoint"]["sha256"],
        "state_sha256": closure["checkpoint"]["legacy_state_sha256"],
        "encoder_hash": closure["context"]["encoder_hash"],
        "source_version": closure["context"]["source_version"],
        "data_id": closure["context"]["data_id"],
        "learning": closure["member_sha256"],
    }
    if (
        canonical(actual) != canonical(expected)
        or closure["synthetic"]
        or closure["authority"] != "DENY_ALL"
    ):
        raise ValueError("complete learning closure differs")


def verify(directory, header):
    check_clock(header)
    sys.path.insert(0, str(directory / "vendor"))
    from verify_closure import verify_checkpoint

    closure = verify_checkpoint(
        directory / "model.npz",
        source_snapshot=directory / "sources.json",
        encoder_manifest_path=directory / "encoder.json",
        encoder_root=directory / "encoder",
        dataset_npz_path=directory / "training.npz",
        expected_data_id=header["binding"]["data_id"],
        release_manifest_path=directory / "release.json",
    )
    check_binding(closure, header["binding"])
    check_clock(header)
    return {"closure": closure, "closure_validation_performed": True}


def modules(directory):
    loaded = {}
    for name in ("adapter", "download_model", "backend", "tasks"):
        path = directory / "vendor/reference" / (name + ".py.source")
        raw = path.read_bytes()
        if (
            hashlib.sha256(raw).hexdigest()
            != SOURCE_HASHES["reference/" + name + ".py.source"]
        ):
            raise ValueError("execution reference changed")
        module = types.ModuleType(name)
        module.__file__ = str(path)
        sys.modules[name] = module
        exec(compile(raw, str(path), "exec"), module.__dict__)
        loaded[name] = module
    return loaded


def measured(phases, stage, function):
    wall, cpu = time.monotonic_ns(), time.process_time_ns()
    value = function()
    phases.append(
        {
            "stage": stage,
            "wall_micros": (time.monotonic_ns() - wall) // 1000,
            "cpu_micros": (time.process_time_ns() - cpu) // 1000,
        }
    )
    return value


def infer(directory, header, phases):
    # The infer inventory excludes the training NPZ, source bodies and rows.
    loaded = modules(directory)
    import numpy as np

    binding = header["binding"]
    raw = (directory / "model.npz").read_bytes()
    if hashlib.sha256(raw).hexdigest() != binding["checkpoint_sha256"]:
        raise ValueError("checkpoint differs from verified content")
    model = loaded["adapter"].Adapter.load(
        io.BytesIO(raw),
        expected_encoder_hash=binding["encoder_hash"],
        expected_source_version=binding["source_version"],
        expected_data_id=binding["data_id"],
    )
    before = model.state_hash()
    if (
        before != binding["state_sha256"]
        or model.config["input_dim"] != 384
        or model.config["num_classes"] != 12
    ):
        raise ValueError("unsupported original task model")
    manifest = strict_json((directory / "encoder.json").read_bytes())
    (directory / "encoder/manifest.json").write_bytes(
        canonical(
            {key: manifest[key] for key in ("schema", "model_id", "revision", "files")}
        )
    )

    def encode():
        check_clock(header)
        encoder = loaded["backend"].FrozenEncoder(
            directory / "encoder",
            batch_size=1,
            max_length=manifest["max_length"],
            threads=manifest["intra_op_threads"],
        )
        if (
            canonical(encoder.manifest) != canonical(manifest)
            or encoder.manifest_hash != binding["encoder_hash"]
        ):
            raise ValueError("actual encoder runtime differs")
        original_session = encoder._session

        class NativeEntry:
            def get_inputs(self):
                return original_session.get_inputs()

            def run(self, outputs, feeds):
                check_clock(header)
                return original_session.run(outputs, feeds)

        encoder._session = NativeEntry()
        features = encoder.encode([header["task"]["text"]])
        if (
            features.shape != (1, 384)
            or features.dtype != np.dtype("float32")
            or not np.isfinite(features).all()
        ):
            raise ValueError("new-task feature contract differs")
        return features, encoder.stats

    features, stats = measured(phases, "encoder", encode)
    check_clock(header)
    selected = measured(phases, "inference", lambda: int(model.predict(features)[0]))
    check_clock(header)
    value = measured(
        phases,
        "codec",
        lambda: loaded["tasks"].execute(selected, header["task"]["payload"]),
    )
    after = model.state_hash()
    if after != before:
        raise ValueError("frozen inference changed learning state")
    check_clock(header)
    task_result = {
        "schema": "hepta.v13.task-output.v1",
        "request_digest": header["request_digest"],
        "skill_index": selected,
        "skill": loaded["tasks"].SKILLS[selected],
        "value": value,
    }
    if len(canonical(task_result)) + 1 > MAX_RESULT:
        raise ValueError("unpublished result exceeds bound")
    return {
        "result": task_result,
        "state_before": before,
        "state_after": after,
        "features": {
            "shape": [1, 384],
            "dtype": "<f4",
            "sha256": hashlib.sha256(features.tobytes(order="C")).hexdigest(),
        },
        "encoder_stats": stats,
        "closure_validation_performed": False,
        "training_data_received": False,
        "task_rows_received": False,
    }


def main():
    started, progress, phases = time.monotonic_ns(), {"staged_bytes": 0}, []
    header, details, status, received = None, {}, "rejected", {}
    try:
        with tempfile.TemporaryDirectory(prefix="hepta-v13-proposal-") as temporary:
            directory = Path(temporary)
            header = read_phase(sys.stdin.buffer, directory, progress, received)
            if header["mode"] == "verify":
                details = verify(directory, header)
                status = "verified"
            else:
                details = infer(directory, header, phases)
                status = "succeeded"
    except (Exception, KeyboardInterrupt) as error:
        header = received.get("header")
        details = {"error_type": type(error).__name__}
        status = (
            "deadline"
            if isinstance(error, NativeDeadline)
            else (
                "rejected" if header is None or header["mode"] == "verify" else "failed"
            )
        )
    response = {
        "schema": RESULT_SCHEMA,
        "authority": "DENY_ALL",
        "status": status,
        "mode": None if header is None else header["mode"],
        "request_digest": None if header is None else header["request_digest"],
        "wall_micros": (time.monotonic_ns() - started) // 1000,
        "cpu_micros": time.process_time_ns() // 1000,
        "enforced_resources": {
            name: list(resource.getrlimit(kind))
            for name, kind in (
                ("cpu_seconds", resource.RLIMIT_CPU),
                ("address_space_bytes", resource.RLIMIT_AS),
                ("file_bytes", resource.RLIMIT_FSIZE),
                ("core_bytes", resource.RLIMIT_CORE),
            )
        },
        "phases": phases,
        "progress": progress,
        "details": details,
    }
    raw = canonical(response)
    if len(raw) > MAX_RESPONSE:
        response.update(status="failed", details={"error_type": "ResponseCapacity"})
        raw = canonical(response)
    sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
