"""Allocate QMNIST digits and writers absent from all 70,000 old MNIST sources.

Only source metadata and exact pixel hashes determine eligibility. No observer,
generator, or candidate outcome is loaded during registration. Four digits from
one writer are not independent writers: inference must cluster by writer ID.
"""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import struct
import time


COMMIT = "94061367ec2e099ea18c553c75727ecf849ddb9b"
FILES = {
    "qmnist-test-images-idx3-ubyte.gz": "43fc22bf7498b8fc98de98369d72f752d0deabc280a43a7bcc364ab19e57b375",
    "qmnist-test-labels-idx2-int.gz": "9fbcbe594c3766fdf4f0b15c5165dc0d1e57ac604e01422608bb72c906030d06",
    "qmnist-train-labels-idx2-int.gz": "2c05dc77f6b916b38e455e97ab129a42a444f3dbef09b278a366f82904e0dd9f",
}
MANIFEST_SHA = "60c24d44e12eb3defb3b1b8146d91879b84918b057e0524117137d7e4f793058"
SALT = "hepta-next-20261025-new-writers-v1"
# (number of writers, disjoint pairs per writer). These are fixed before outputs.
ROLES = {"control": (128, 4), "native": (24, 4), "media": (32, 4),
         "joint": (32, 4), "native_calibration": (12, 8)}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rank(kind, value):
    return hashlib.sha256(f"{SALT}:{kind}:{value}".encode()).digest()


def _metadata(raw):
    if struct.unpack(">III", raw[:12]) != (3074, 60000, 8) or len(raw) != 12 + 60000 * 32:
        raise ValueError("Unexpected QMNIST metadata shape")
    rows = tuple(struct.iter_unpack(">8I", raw[12:]))
    if any(row[0] > 9 or row[6] != 0 for row in rows):
        raise ValueError("Invalid class or duplicate marker")
    return rows


def _read(cache):
    cache = Path(cache)
    for name, expected in FILES.items():
        if sha(cache / name) != expected:
            raise ValueError("Author data checksum differs: " + name)
    pixels = gzip.decompress((cache / "qmnist-test-images-idx3-ubyte.gz").read_bytes())
    if struct.unpack(">IIII", pixels[:16]) != (2051, 60000, 28, 28) or len(pixels) != 16 + 60000 * 784:
        raise ValueError("Unexpected QMNIST image shape")
    return (pixels[16:],
            _metadata(gzip.decompress((cache / "qmnist-test-labels-idx2-int.gz").read_bytes())),
            _metadata(gzip.decompress((cache / "qmnist-train-labels-idx2-int.gz").read_bytes())))


def register(cache, old_manifest, output):
    if sha(old_manifest) != MANIFEST_SHA:
        raise ValueError("Old manifest changed")
    old = json.loads(Path(old_manifest).read_text())
    old_hashes = {v.rsplit(":", 1)[1] for r in old["roles"].values() for v in r["source_ids"]}
    if len(old_hashes) != 70000:
        raise ValueError("Expected every original MNIST pixel identity")
    pixels, test, train = _read(cache)
    old_rows = train + test[:10000]
    old_digits, old_writers = {r[5] for r in old_rows}, {r[2] for r in old_rows}
    if len(old_digits) != 70000:
        raise ValueError("Original MNIST reconstruction IDs are not unique")
    candidates, excluded_pixels = defaultdict(list), 0
    all_extra_hashes = set()
    for index in range(10000, len(test)):
        row = test[index]
        digest = hashlib.sha256(pixels[index * 784:(index + 1) * 784]).hexdigest()
        if row[5] in old_digits:
            raise ValueError("Extended source overlaps an original MNIST digit")
        if digest in old_hashes or digest in all_extra_hashes:
            excluded_pixels += 1
            continue
        all_extra_hashes.add(digest)
        if row[2] not in old_writers:
            candidates[row[2]].append((index, row[5], digest))
    writers = sorted(candidates, key=lambda w: _rank("writer", w))
    if len(writers) < sum(count for count, _ in ROLES.values()):
        raise ValueError("Not enough completely new writers for the fixed plan")
    roles, cursor = {}, 0
    for study, (count, pairs) in ROLES.items():
        group = writers[cursor:cursor + count]
        cursor += count
        selected, pair_writers = [], []
        for writer in group:
            ordered = sorted(candidates[writer], key=lambda r: _rank("digit", r[1]))
            if len(ordered) < pairs * 2:
                raise ValueError("A writer has insufficient unused digits")
            selected.extend(ordered[:pairs * 2])
            pair_writers.extend([writer] * pairs)
        ids = [f"qmnist:test:{idx}:nist:{nist}:writer:{test[idx][2]}:{digest}"
               for idx, nist, digest in selected]
        roles[study] = {"role": "next_" + study, "pair_count": len(pair_writers),
                        "writer_count": len(group), "writer_ids": group,
                        "pair_writer_ids": pair_writers, "source_ids": ids,
                        "indices": [r[0] for r in selected],
                        "nist_digit_ids": [r[1] for r in selected],
                        "pixel_sha256": [r[2] for r in selected],
                        "source_ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest()}
    result = {"schema": "hepta.next.source-allocation.v1", "registered_unix_ns": time.time_ns(),
              "dataset": "QMNIST extended testing digits", "author_commit": COMMIT,
              "author_url": f"https://github.com/facebookresearch/qmnist/tree/{COMMIT}",
              "archive_sha256": FILES, "old_manifest_sha256": MANIFEST_SHA,
              "allocator_sha256": sha(__file__), "salt": SALT, "roles": roles,
              "old_nist_digit_count": len(old_digits), "old_writer_count": len(old_writers),
              "eligible_new_writer_count": len(writers), "old_digit_overlap": 0,
              "old_writer_overlap": 0, "exact_duplicate_pixels_excluded": excluded_pixels,
              "reserved_writer_ids": writers[cursor:], "outcomes_opened": False,
              "selection": "Metadata-only hash ordering; no label balancing or quality filtering",
              "inference_unit": "NIST writer; several distinct pairs share one writer",
              "scope": "Original source IDs and all available MNIST roles; unknown external use not attested"}
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with Path(output).open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return result


def load_registered(cache, allocation, protocol, study="control"):
    """Open a role only with exact source allocation and frozen candidate files.

    Formal roles must never train parameters. ``native_calibration`` is a
    separately allocated fitting role; its writers cannot enter confirmation.
    This guard checks identities, not Python sandbox isolation.
    """
    import torch
    from ..v6.data import SourceCorpus, SourceSplit

    record = json.loads(Path(allocation).read_text())
    specification = json.loads(Path(protocol).read_text())
    pins = specification.get("frozen_candidate_sha256", {})
    if (study not in ROLES or specification.get("study") != study or not pins
            or specification.get("source_allocation_sha256") != sha(allocation)
            or record.get("allocator_sha256") != sha(__file__)
            or record.get("old_manifest_sha256") != MANIFEST_SHA):
        raise ValueError("Require exact prospective role, allocation and candidate registration")
    for path, expected in pins.items():
        if not Path(path).is_absolute() or sha(path) != expected:
            raise ValueError("Frozen candidate changed: " + path)
    pixels, test, train = _read(cache)
    role = record["roles"][study]
    old_rows = train + test[:10000]
    old_digits, old_writers = {r[5] for r in old_rows}, {r[2] for r in old_rows}
    images, labels, ids, hashes = [], [], [], []
    for index, expected_id, expected_hash in zip(role["indices"], role["source_ids"], role["pixel_sha256"]):
        row, raw = test[index], pixels[index * 784:(index + 1) * 784]
        digest = hashlib.sha256(raw).hexdigest()
        identity = f"qmnist:test:{index}:nist:{row[5]}:writer:{row[2]}:{digest}"
        if (index < 10000 or row[5] in old_digits or row[2] in old_writers
                or digest != expected_hash or identity != expected_id):
            raise ValueError("Source, writer, or pixel identity differs")
        images.append(torch.frombuffer(bytearray(raw), dtype=torch.uint8).reshape(1, 28, 28))
        labels.append(row[0]); ids.append(identity); hashes.append(digest)
    writers = [test[i][2] for i in role["indices"]]
    count, pairs = ROLES[study]
    if (len(ids) != count * pairs * 2 or len(set(ids)) != len(ids)
            or writers[::2] != role["pair_writer_ids"] or writers[1::2] != role["pair_writer_ids"]
            or len(set(writers)) != count):
        raise ValueError("Pair assignment or writer count differs")
    split = SourceSplit(torch.stack(images), torch.tensor(labels), tuple(ids), tuple(hashes))
    return SourceCorpus({role["role"]: split}, record)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--old-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    allocation = register(args.cache, args.old_manifest, args.output)
    print(json.dumps({"allocation_sha256": sha(args.output), "new_writers": allocation["eligible_new_writer_count"],
                      "roles": {k: {f: v[f] for f in ("pair_count", "writer_count")} for k, v in allocation["roles"].items()}}))
