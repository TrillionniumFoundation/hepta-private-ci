"""Read the 36 sealed contribution packets once; compare exact representations."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import traceback

from .pft_statistics import canonical, digest
from .pft_statistics_codec import decode_packet, encode_packet


PROTOCOL_COMMIT = "b537c9e791450afc3a006942eb9784ab8108a23a"
INPUTS_SHA256 = "2df80f19ad925fe494f4c6306e5c84ea7ccce8ba4c7e1e7f8186611de08745ab"


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def read(fixture, entry):
    path = (fixture / entry["path"]).resolve()
    if not path.is_relative_to(fixture.resolve()):
        raise ValueError("input escapes fixture root")
    raw = path.read_bytes()
    if len(raw) != entry["size"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError("historical input bytes differ")
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    here = Path(__file__).parent
    raw = (here / "pft_lossless_codec/INPUTS.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != INPUTS_SHA256:
        raise ValueError("input inventory changed")
    source = {name:hashlib.sha256((here/name).read_bytes()).hexdigest() for name in
              ("pft_statistics_codec.py", "pft_statistics_codec_tests.py", "pft_statistics_codec_qualification.py", "pft_statistics.py", "pft_linear.py")}
    write(args.output / "SOURCE_FROZEN.json", dict(protocol_commit=PROTOCOL_COMMIT, source=source, inputs_sha256=INPUTS_SHA256))
    rows, errors = [], []
    try:
        for parent in json.loads(raw)["parents"]:
            candidate = read(args.fixture_root, parent["candidate"])
            packets = read(args.fixture_root, parent["contributions"])
            expected = json.loads(candidate["head_material_canonical_json"])["batches"]
            if len(packets) != 4 or [[p["body"]["batch_id"], p["payload_sha256"]] for p in packets] != expected:
                raise ValueError("contributions differ from sealed head")
            material = dict(contract_sha256=candidate["contract_sha256"], batches=[])
            for index, packet in enumerate(packets):
                before = time.perf_counter()
                encoded = encode_packet(packet, candidate["contract"])
                encoded_at = time.perf_counter()
                decoded = decode_packet(encoded, candidate["contract"])
                decoded_at = time.perf_counter()
                if decoded != packet or canonical(decoded) != canonical(packet):
                    raise ValueError("packet object or canonical bytes differ")
                for key in ("gram", "rhs", "yty"):
                    for left, right in zip(packet["body"][key], decoded["body"][key], strict=True):
                        if struct.pack(f"<{len(left)}d", *left) != struct.pack(f"<{len(right)}d", *right):
                            raise ValueError("float64 bits differ")
                material["batches"].append([decoded["body"]["batch_id"], decoded["payload_sha256"]])
                path = args.output / f"{parent['parent']}-shard{index}.bin"
                with path.open("xb") as stream:
                    stream.write(encoded)
                row = dict(parent=parent["parent"], shard=index, passed=True, payload_sha256=packet["payload_sha256"],
                           canonical_sha256=hashlib.sha256(canonical(packet)).hexdigest(), binary_sha256=hashlib.sha256(encoded).hexdigest(),
                           canonical_json_bytes=len(canonical(packet)), binary_bytes=len(encoded), flags=encoded[8],
                           encode_seconds=encoded_at-before, decode_seconds=decoded_at-encoded_at)
                rows.append(row)
                write(args.output / f"{parent['parent']}-shard{index}.json", row)
            if canonical(material).decode() != candidate["head_material_canonical_json"] or digest(material) != candidate["head"]:
                raise ValueError("decoded contributions change the sealed head")
            print(json.dumps(dict(parent=parent["parent"], roundtrips=4, head_unchanged=True)), flush=True)
    except Exception as error:
        errors.append(dict(error=repr(error), traceback=traceback.format_exc(), completed_packets=len(rows)))
    original_bytes = sum(r["canonical_json_bytes"] for r in rows)
    binary_bytes = sum(r["binary_bytes"] for r in rows)
    summary = dict(schema="pft-codec-historical-roundtrip-v1", expected=36, passed=len(rows) if not errors else 0,
                   completed_packets=len(rows), errors=errors, rows=rows, canonical_json_bytes=original_bytes,
                   binary_bytes=binary_bytes, ratio=binary_bytes/original_bytes if original_bytes else None,
                   seconds=time.perf_counter()-started, model_training=False, network_speedup_measured=False,
                   positive_semidefiniteness_verified=False, source_authentication=False, useful_work_verified=False)
    write(args.output / "RESULTS.json", summary)
    raise SystemExit(0 if summary["passed"] == 36 else 1)


if __name__ == "__main__":
    main()
