"""Stream fixed, unused XNIST writers for H2 admission and owner execution."""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import lzma
from pathlib import Path
import struct
import time

from .sources import sha, FILES as QMNIST_FILES, MANIFEST_SHA
from .xnist_sources import FILES


ROLES = {"calibration": (100, 1), "qualification": (1000, 1), "execution": (64, 2)}
SALT = "hepta-next-native-h2-writer-split-v1"
PREVIOUS_QUALIFICATION_SHA = "c997590bb6c1a95a91d1ba469f6a8f1219764422d572b16f77175cd5e252252f"
PREVIOUS_ACTION_VALUE_SHA = "7675debf5142f07d3f4150d8e986b3827e5cf764547d704520895fc8241a474c"


def metadata(path):
    opener = lzma.open if Path(path).suffix == ".xz" else gzip.open
    with opener(path, "rb") as stream:
        magic, count, columns = struct.unpack(">III", stream.read(12))
        if magic != 0x0c02 or columns != 8:
            raise ValueError("Expected official QMNIST/XNIST int32 metadata")
        for index in range(count):
            yield index, struct.unpack(">8I", stream.read(32))


def pixels(path, selected):
    """Read selected physical source bytes without retaining the 316 MB census."""
    with lzma.open(path, "rb") as stream:
        magic, count, height, width = struct.unpack(">IIII", stream.read(16))
        if magic != 0x0803 or (height, width) != (28, 28):
            raise ValueError("Expected official XNIST image bytes")
        position = 0
        for index in sorted(selected):
            if index < position or index >= count:
                raise ValueError("Invalid or repeated source index")
            remaining = (index - position) * 784
            while remaining:
                block = stream.read(min(remaining, 1024 * 1024))
                if not block:
                    raise ValueError("Truncated source archive")
                remaining -= len(block)
            raw = stream.read(784)
            if len(raw) != 784:
                raise ValueError("Truncated selected source")
            yield index, raw
            position = index + 1


def rank(kind, value):
    return hashlib.sha256(f"{SALT}:{kind}:{value}".encode()).digest()


def register(cache, prior_qualification, prior_action_value, old_manifest, output):
    cache = Path(cache)
    if (sha(prior_qualification) != PREVIOUS_QUALIFICATION_SHA
            or sha(prior_action_value) != PREVIOUS_ACTION_VALUE_SHA or sha(old_manifest) != MANIFEST_SHA):
        raise ValueError("Previously published source allocation identity changed")
    previous = json.loads(Path(prior_qualification).read_text())
    action = json.loads(Path(prior_action_value).read_text())
    for name, expected in {**FILES, **QMNIST_FILES}.items():
        if sha(cache / name) != expected:
            raise ValueError("Official source archive changed")
    old = json.loads(Path(old_manifest).read_text())
    old_hashes = {identity.rsplit(":", 1)[-1] for role in old["roles"].values() for identity in role["source_ids"]}
    with gzip.open(cache / "qmnist-test-images-idx3-ubyte.gz", "rb") as stream:
        if struct.unpack(">IIII", stream.read(16)) != (0x0803, 60000, 28, 28):
            raise ValueError("QMNIST complete test pixel census differs")
        for _ in range(60000):
            raw = stream.read(784)
            if len(raw) != 784:
                raise ValueError("Truncated QMNIST source census")
            old_hashes.add(hashlib.sha256(raw).hexdigest())
    excluded = {row[2] for name in ("qmnist-train-labels-idx2-int.gz", "qmnist-test-labels-idx2-int.gz")
                for _, row in metadata(cache / name)}
    excluded.update(previous["pair_writer_ids"])
    excluded.update(action["pair_writer_ids"])
    groups = defaultdict(list)
    for index, row in metadata(cache / "xnist-labels-idx2-int.xz"):
        if row[2] not in excluded and 0 <= row[0] <= 9 and row[6] == 0:
            groups[row[2]].append((index, row[5]))
    writers = sorted((writer for writer, rows in groups.items() if len(rows) >= 4), key=lambda value: rank("writer", value))
    if len(writers) < sum(count for count, _ in ROLES.values()):
        raise ValueError("Insufficient never-used writers for the fixed H2 studies")
    assigned, offset = {}, 0
    for role, (count, pairs) in ROLES.items():
        selected = writers[offset:offset + count]; offset += count
        assigned[role] = [(index, writer, digit) for writer in selected
                          for index, digit in sorted(groups[writer], key=lambda value: rank("digit", value[1]))[:2 * pairs]]
    hashes = {index: hashlib.sha256(raw).hexdigest()
              for index, raw in pixels(cache / "xnist-images-idx3-ubyte.xz", {row[0] for rows in assigned.values() for row in rows})}
    previous_hashes = set(previous["pixel_sha256"]) | {row["pixel_sha256"] for row in action["source_records"]}
    if len(set(hashes.values())) != len(hashes) or set(hashes.values()) & (previous_hashes | old_hashes):
        raise ValueError("Selected H2 pixel identities overlap a previous source census")
    roles = {}
    for role, rows in assigned.items():
        count, pairs = ROLES[role]
        records = [{"index": index, "writer": writer, "nist_digit": digit, "pixel_sha256": hashes[index],
                    "source_id": f"xnist:{index}:nist:{digit}:writer:{writer}:{hashes[index]}"}
                   for index, writer, digit in rows]
        roles[role] = {"role": "next_native_h2_" + role, "writer_count": count,
                       "pair_count": count * pairs, "pairs_per_writer": pairs,
                       "pair_writer_ids": [row["writer"] for row in records[::2]], "source_records": records}
    record = {"schema": "hepta.next.native-h2-source-allocation.v1", "registered_unix_ns": time.time_ns(),
              "roles": roles, "archive_sha256": FILES, "allocator_sha256": sha(__file__),
              "source_reader_sha256": sha(Path(__file__).with_name("sources.py")),
              "xnist_reader_sha256": sha(Path(__file__).with_name("xnist_sources.py")),
              "prior_qualification_sha256": sha(prior_qualification), "prior_action_value_sha256": sha(prior_action_value),
              "original_mnist_manifest_sha256": MANIFEST_SHA,
              "excluded_writer_count": len(excluded), "remaining_writers": len(writers) - offset,
              "pairwise_writer_overlap": 0, "previous_xnist_selected_pixel_overlap": 0,
              "all_original_mnist_and_qmnist_test_pixel_overlap": 0,
              "selection": "Fixed metadata hashes, valid digit labels and duplicate flag; no outcome or label balancing",
              "model_outcomes_opened": False}
    with Path(output).open("x") as stream:
        json.dump(record, stream, indent=2, sort_keys=True); stream.write("\n")
    return record


def load_registered(cache, allocation, protocol, study):
    import torch
    from ..v6.data import SourceCorpus, SourceSplit

    record = json.loads(Path(allocation).read_text())
    spec = json.loads(Path(protocol).read_text())
    role_name = study.removeprefix("native_h2_")
    pins = spec.get("frozen_candidate_sha256", {})
    if (study != "native_h2_" + role_name or role_name not in ROLES or spec.get("study") != study
            or spec.get("source_allocation_sha256") != sha(allocation)
            or record["allocator_sha256"] != sha(__file__) or not pins
            or record["source_reader_sha256"] != sha(Path(__file__).with_name("sources.py"))
            or record["xnist_reader_sha256"] != sha(Path(__file__).with_name("xnist_sources.py"))
            or record["prior_qualification_sha256"] != PREVIOUS_QUALIFICATION_SHA
            or record["prior_action_value_sha256"] != PREVIOUS_ACTION_VALUE_SHA
            or any(not Path(path).is_absolute() or sha(path) != expected for path, expected in pins.items())):
        raise ValueError("The exact prospective H2 candidate and source allocation must be frozen")
    cache = Path(cache)
    for name, expected in record["archive_sha256"].items():
        if sha(cache / name) != expected:
            raise ValueError("Official XNIST source bytes changed")
    role = record["roles"][role_name]
    selected = {row["index"]: row for row in role["source_records"]}
    actual_meta = {index: row for index, row in metadata(cache / "xnist-labels-idx2-int.xz") if index in selected}
    actual_pixels = dict(pixels(cache / "xnist-images-idx3-ubyte.xz", selected))
    images, labels, ids, hashes, writers = [], [], [], [], []
    for entry in role["source_records"]:
        index = entry["index"]; row, raw = actual_meta[index], actual_pixels[index]
        digest = hashlib.sha256(raw).hexdigest()
        identity = f"xnist:{index}:nist:{row[5]}:writer:{row[2]}:{digest}"
        if (identity != entry["source_id"] or digest != entry["pixel_sha256"] or row[2] != entry["writer"]
                or row[5] != entry["nist_digit"] or not 0 <= row[0] <= 9 or row[6] != 0):
            raise ValueError("Selected H2 source identity or label is invalid")
        images.append(torch.frombuffer(bytearray(raw), dtype=torch.uint8).reshape(1, 28, 28))
        labels.append(row[0]); ids.append(identity); hashes.append(digest); writers.append(row[2])
    count, pairs = ROLES[role_name]
    if (len(ids) != count * pairs * 2 or len(set(ids)) != len(ids) or len(set(writers)) != count
            or writers[::2] != role["pair_writer_ids"] or writers[1::2] != role["pair_writer_ids"]
            or set(Counter(writers).values()) != {2 * pairs}):
        raise ValueError("H2 source census changed")
    return SourceCorpus({role["role"]: SourceSplit(torch.stack(images), torch.tensor(labels), tuple(ids), tuple(hashes))}, record)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("cache", "prior-qualification", "prior-action-value", "old-manifest", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    result = register(a.cache, a.prior_qualification, a.prior_action_value, a.old_manifest, a.output)
    print(json.dumps({"allocation_sha256": sha(a.output), "roles": {key: {name: value[name] for name in ("writer_count", "pair_count")}
                                                                 for key, value in result["roles"].items()},
                      "remaining_writers": result["remaining_writers"]}))
