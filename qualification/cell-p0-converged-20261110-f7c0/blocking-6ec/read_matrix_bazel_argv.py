"""Read original compact Bazel execution evidence without expanding it to disk."""

import hashlib
import io
import json
from pathlib import Path
import zipfile

import zstandard


def varint(stream):
    value = 0
    for index in range(10):
        byte = stream.read(1)
        if not byte:
            if index == 0:
                return None
            raise ValueError("truncated varint")
        value |= (byte[0] & 127) << (7 * index)
        if not byte[0] & 128:
            return value
    raise ValueError("oversized varint")


def fields(data):
    stream = io.BytesIO(data)
    result = {}
    while (tag := varint(stream)) is not None:
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            value = varint(stream)
        elif wire == 1:
            value = stream.read(8)
        elif wire == 2:
            value = stream.read(varint(stream))
        elif wire == 5:
            value = stream.read(4)
        else:
            raise ValueError(f"unsupported wire type {wire}")
        result.setdefault(number, []).append(value)
    return result


root = Path(__file__).parent
summary = root / "6ec-bazel-matrix-compiler-args.json"
report = json.loads(summary.read_text())
by_digest = {item["args_sha256"]: item for item in report["selected"]}
with zipfile.ZipFile(report["artifact"]) as archive:
    with archive.open(report["member"]) as compressed:
        with zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
            while (size := varint(stream)) is not None:
                data = stream.read(size)
                if len(data) != size:
                    raise ValueError("truncated record")
                entry = fields(data)
                if 7 not in entry:
                    continue
                spawn = fields(entry[7][0])
                arguments = [arg.decode() for arg in spawn.get(1, [])]
                digest = hashlib.sha256(
                    json.dumps(arguments, separators=(",", ":")).encode()
                ).hexdigest()
                if digest in by_digest:
                    by_digest[digest]["original_args"] = arguments
                    by_digest[digest]["parameter_file_args"] = [
                        arg for arg in arguments if arg.startswith("@")
                    ]

assert all("original_args" in item for item in report["selected"])
report["argv_readback_script"] = str(Path(__file__))
summary.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps([
    {
        "target": item["target"],
        "mnemonic": item["mnemonic"],
        "argument_count": len(item["original_args"]),
        "parameter_file_args": item["parameter_file_args"],
    }
    for item in report["selected"]
], indent=2))
