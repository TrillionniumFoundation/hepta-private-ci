"""Retain real source bytes and detect exact reuse; never certify independence.

The baseline mode only records already exposed sources. Later freezes require
pinned prior ledgers, including their original images. Unlisted history, related
templates, near duplicates and provenance authenticity remain unverified.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import unicodedata

import PIL
from PIL import Image

JSON_LIMIT = 4 * 1024 * 1024
IMAGE_BYTE_LIMIT = 16 * 1024 * 1024
IMAGE_PIXEL_LIMIT = 16 * 1024 * 1024
TOTAL_ORIGINAL_BYTE_LIMIT = 32 * 1024 * 1024
ROLES = ("train", "dev", "confirmation")
DECODER = {
    "library": "Pillow",
    "version": PIL.__version__,
    "pixels": "RGB8-no-EXIF-transpose-v1",
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pin(value):
    require(
        type(value) is str
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value),
        "invalid SHA256",
    )
    return value


def exact(value, keys):
    require(
        type(value) is dict and set(value) == set(keys.split()),
        "unknown or missing fields",
    )


def label(value):
    require(
        type(value) is str
        and 0 < len(value.encode()) <= 512
        and value.strip() == value
        and all(ord(c) >= 32 for c in value),
        "invalid source/group label",
    )
    return unicodedata.normalize("NFKC", value).casefold()


def read_bytes(path, expected=None, limit=IMAGE_BYTE_LIMIT):
    """Pin one regular descriptor; reject observed in-place edits and links.

    This is not a filesystem snapshot against a malicious same-user writer.
    Exact byte pins and cold readback remain necessary.
    """
    path = Path(path)
    require(not path.is_symlink(), "symlink refused")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
    )
    with os.fdopen(os.open(path, flags), "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and 0 < before.st_size <= limit,
            "invalid source file or byte limit",
        )
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    require(
        len(raw) == before.st_size
        and all(getattr(before, k) == getattr(after, k) for k in fields),
        "file changed during read",
    )
    require(
        expected is None or digest(raw) == pin(expected), "source byte pin mismatch"
    )
    return raw


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("nonfinite JSON constant")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def pixels(raw):
    with Image.open(io.BytesIO(raw)) as image:
        width, height = image.size
        require(
            0 < width * height <= IMAGE_PIXEL_LIMIT
            and getattr(image, "n_frames", 1) == 1,
            "image/frame bound",
        )
        rgb = image.convert("RGB").tobytes()
    return width, height, digest(struct.pack("<II", width, height) + rgb)


def validate_sources(sources):
    require(type(sources) is list and 0 < len(sources) <= 64, "source count bound")
    ids, groups, raw_ids, pixel_ids = set(), {}, set(), set()
    for source in sources:
        exact(
            source,
            "source_id group split image_sha256 rgb_sha256 width height bytes path",
        )
        source_id, group = label(source["source_id"]), label(source["group"])
        require(source_id not in ids, "duplicate or aliased source ID")
        ids.add(source_id)
        require(source["split"] in ROLES, "invalid split")
        if group in groups:
            require(
                groups[group] == (source["group"], source["split"]),
                "group alias or cross-split source",
            )
        groups[group] = (source["group"], source["split"])
        for key, seen in (("image_sha256", raw_ids), ("rgb_sha256", pixel_ids)):
            require(
                pin(source[key]) not in seen, "duplicate source bytes or decoded pixels"
            )
            seen.add(source[key])
        require(
            source["path"] == "originals/" + source["image_sha256"] + ".image",
            "noncanonical original path",
        )
        require(
            all(
                type(source[k]) is int and source[k] > 0
                for k in ("width", "height", "bytes")
            )
            and source["bytes"] <= IMAGE_BYTE_LIMIT
            and source["width"] * source["height"] <= IMAGE_PIXEL_LIMIT,
            "source dimensions/size bound",
        )
    require(
        sum(s["bytes"] for s in sources) <= TOTAL_ORIGINAL_BYTE_LIMIT,
        "total original byte limit",
    )


def read_ledger(path, expected):
    path = Path(path)
    require(not path.parent.is_symlink(), "ledger directory symlink refused")
    value = parse(read_bytes(path, pin(expected), JSON_LIMIT))
    exact(
        value,
        "schema mode status input_sha256 decoder priors sources overlap scientific_qualified production_qualified prior_registry_complete independence_verified adoption",
    )
    require(
        value["schema"] == "perc1.source-freeze.v1" and value["decoder"] == DECODER,
        "ledger schema or decoder changed",
    )
    require(
        value["mode"] in ("baseline", "candidate")
        and value["status"]
        in ("BASELINE_EXPOSURE_ONLY", "HOLD_REUSED_SOURCE", "NO_EXACT_REUSE_OBSERVED"),
        "invalid ledger status",
    )
    pin(value["input_sha256"])
    require(
        all(
            value[k] is False
            for k in (
                "scientific_qualified",
                "production_qualified",
                "prior_registry_complete",
                "independence_verified",
            )
        )
        and value["adoption"] == "NoUpdate",
        "ledger overclaims authority",
    )
    require(
        type(value["priors"]) is list
        and len(value["priors"]) <= 32
        and all(type(p) is str for p in value["priors"])
        and len(set(value["priors"])) == len(value["priors"]),
        "invalid prior inventory",
    )
    for item in value["priors"]:
        pin(item)
    require(
        (value["mode"] == "baseline") == (not value["priors"]),
        "baseline/prior mismatch",
    )
    validate_sources(value["sources"])
    spec = parse(
        read_bytes(path.parent / "input.json", value["input_sha256"], JSON_LIMIT)
    )
    exact(spec, "schema sources")
    require(
        spec["schema"] == "perc1.source-freeze-input.v1"
        and type(spec["sources"]) is list
        and len(spec["sources"]) == len(value["sources"]),
        "retained input inventory mismatch",
    )
    for original, source in zip(spec["sources"], value["sources"]):
        exact(original, "source_id group split image_path image_sha256")
        require(
            type(original["image_path"]) is str
            and all(
                original[k] == source[k]
                for k in ("source_id", "group", "split", "image_sha256")
            ),
            "retained input binding mismatch",
        )
    require(
        type(value["overlap"]) is list
        and len(value["overlap"]) <= len(value["sources"]),
        "invalid overlap inventory",
    )
    overlap_ids = set()
    for entry in value["overlap"]:
        exact(entry, "source_id matches")
        require(
            entry["source_id"] in {s["source_id"] for s in value["sources"]}
            and entry["source_id"] not in overlap_ids,
            "invalid overlap source",
        )
        overlap_ids.add(entry["source_id"])
        require(
            type(entry["matches"]) is list
            and entry["matches"]
            and all(type(k) is str for k in entry["matches"])
            and len(set(entry["matches"])) == len(entry["matches"])
            and set(entry["matches"]) <= {"group", "image_sha256", "rgb_sha256"},
            "invalid overlap reasons",
        )
    expected_status = (
        "BASELINE_EXPOSURE_ONLY"
        if value["mode"] == "baseline"
        else "HOLD_REUSED_SOURCE"
        if value["overlap"]
        else "NO_EXACT_REUSE_OBSERVED"
    )
    require(
        value["status"] == expected_status
        and (value["mode"] != "baseline" or not value["overlap"]),
        "status/overlap mismatch",
    )
    require(
        not (path.parent / "originals").is_symlink(),
        "original directory symlink refused",
    )
    for source in value["sources"]:
        raw = read_bytes(path.parent / source["path"], source["image_sha256"])
        require(
            len(raw) == source["bytes"]
            and pixels(raw)
            == (source["width"], source["height"], source["rgb_sha256"]),
            "retained original/pixel mismatch",
        )
    return value


def freeze(input_path, priors, output, *, baseline=False):
    """Create an exposure ledger and original copies; reused inputs remain HOLD.

    A disjoint result says only that no exact reuse was found in the supplied
    ledgers. Failed candidates are valid exposure history for later freezes.
    """
    require(
        type(baseline) is bool and type(priors) is list and len(priors) <= 32,
        "invalid freeze mode/priors",
    )
    require(
        bool(priors) != baseline,
        "candidate requires pinned history; empty history is baseline only",
    )
    old, pins, ancestors = [], [], set()
    for entry in priors:
        require(
            type(entry) in (list, tuple) and len(entry) == 2, "invalid prior pin pair"
        )
        path, expected = entry
        require(pin(expected) not in pins, "duplicate prior ledger")
        previous = read_ledger(path, expected)
        old.extend(previous["sources"])
        ancestors.update(previous["priors"])
        pins.append(expected)
    require(ancestors <= set(pins), "incomplete supplied prior history")
    raw_input = read_bytes(input_path, limit=JSON_LIMIT)
    spec = parse(raw_input)
    exact(spec, "schema sources")
    require(
        spec["schema"] == "perc1.source-freeze-input.v1"
        and type(spec["sources"]) is list
        and 0 < len(spec["sources"]) <= 64,
        "invalid input schema/source count",
    )
    sources, originals = [], []
    for item in spec["sources"]:
        exact(item, "source_id group split image_path image_sha256")
        require(type(item["image_path"]) is str, "invalid image path")
        path = Path(item["image_path"])
        path = path if path.is_absolute() else Path(input_path).parent / path
        raw = read_bytes(path, pin(item["image_sha256"]))
        width, height, rgb_sha = pixels(raw)
        sources.append(
            {k: item[k] for k in ("source_id", "group", "split", "image_sha256")}
            | {
                "rgb_sha256": rgb_sha,
                "width": width,
                "height": height,
                "bytes": len(raw),
                "path": "originals/" + digest(raw) + ".image",
            }
        )
        originals.append(raw)
        require(
            sum(map(len, originals)) <= TOTAL_ORIGINAL_BYTE_LIMIT,
            "total original byte limit",
        )
    validate_sources(sources)
    seen = {
        k: {label(s[k]) if k == "group" else s[k] for s in old}
        for k in ("group", "image_sha256", "rgb_sha256")
    }
    overlap = []
    for source in sources:
        reasons = [
            k
            for k in seen
            if (label(source[k]) if k == "group" else source[k]) in seen[k]
        ]
        if reasons:
            overlap.append({"source_id": source["source_id"], "matches": reasons})
    value = dict(
        schema="perc1.source-freeze.v1",
        mode="baseline" if baseline else "candidate",
        status="BASELINE_EXPOSURE_ONLY"
        if baseline
        else "HOLD_REUSED_SOURCE"
        if overlap
        else "NO_EXACT_REUSE_OBSERVED",
        input_sha256=digest(raw_input),
        decoder=DECODER,
        priors=pins,
        sources=sources,
        overlap=overlap,
        scientific_qualified=False,
        production_qualified=False,
        prior_registry_complete=False,
        independence_verified=False,
        adoption="NoUpdate",
    )
    output = Path(output)
    output.mkdir(mode=0o700)  # Existing output, including a dangling symlink, fails.
    (output / "originals").mkdir(mode=0o700)
    retained = [(output / "input.json", raw_input)] + [
        (output / s["path"], raw) for s, raw in zip(sources, originals)
    ]
    for path, raw in retained:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with (output / "ledger.json").open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    require(
        read_ledger(output / "ledger.json", digest(encoded)) == value,
        "cold ledger readback changed",
    )
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument(
        "--prior", nargs=2, action="append", default=[], metavar=("LEDGER", "SHA256")
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    result = freeze(args.input, args.prior, args.output, baseline=args.baseline)
    print(json.dumps(result, sort_keys=True))
    return 2 if result["status"] == "HOLD_REUSED_SOURCE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
