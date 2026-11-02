"""Lossless column transport; restores the exact original JSON/gzip bytes.

This post-result packer changes no scientific output. Restoration requires the
recorded Python JSON and zlib serialization and verifies every original hash.
"""

import argparse
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import platform
import struct
import tarfile
import zlib

import numpy as np

HERE = Path(__file__).resolve().parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded_json(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode()


def encode_column(value):
    if isinstance(value[0], str):
        assert all(len(x) == 64 and bytes.fromhex(x).hex() == x for x in value)
        return dict(kind="hex64", count=len(value)), b"".join(bytes.fromhex(x) for x in value)
    array = np.asarray(value)
    if array.dtype.kind == "f":
        small = array.astype("<f4")
        dtype = "<f4" if np.array_equal(small.astype("<f8"), array) else "<f8"
    elif array.dtype.kind in "iu":
        assert array.min() >= 0 and array.max() <= 255
        dtype = "u1"
    elif array.dtype.kind == "b":
        dtype = "?"
    else:
        raise ValueError(array.dtype)
    raw = array.astype(dtype).tobytes(order="C")
    return dict(kind="array", dtype=dtype, shape=list(array.shape)), raw


def decode_column(descriptor, raw):
    if descriptor["kind"] == "hex64":
        assert len(raw) == 32 * descriptor["count"]
        return [raw[i:i + 32].hex() for i in range(0, len(raw), 32)]
    return np.frombuffer(raw, dtype=descriptor["dtype"]).reshape(descriptor["shape"]).tolist()


def pack():
    target = HERE / "transport_confirm_compact"
    target.mkdir(exist_ok=False)
    paths = sorted((HERE / "run_01/confirmation_01").iterdir())
    paths += sorted(HERE.glob("run_01_confirm.*"))
    objects, files = {}, []
    for path in paths:
        if not path.is_file():
            continue
        raw = path.read_bytes()
        row = dict(path=path.relative_to(HERE).as_posix(), bytes=len(raw), sha256=sha(raw))
        if path.name.startswith("raw_") and path.name.endswith(".json.gz"):
            value = json.loads(gzip.decompress(raw))
            columns = {}
            for key, field in value.items():
                descriptor, data = encode_column(field)
                identity = sha(data)
                objects[identity] = data
                columns[key] = dict(descriptor, object=identity)
            reconstructed = {key: decode_column(d, objects[d["object"]]) for key, d in columns.items()}
            restored = gzip.compress(encoded_json(reconstructed), mtime=0)
            assert restored == raw, str(path)
            row.update(codec="column-json-gzip", columns=columns)
        else:
            identity = sha(raw)
            objects[identity] = raw
            row.update(codec="verbatim", object=identity)
        files.append(row)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w", format=tarfile.USTAR_FORMAT) as package:
        for identity, raw in sorted(objects.items()):
            entry = tarfile.TarInfo(identity)
            entry.size, entry.mode, entry.mtime = len(raw), 0o644, 0
            package.addfile(entry, io.BytesIO(raw))
    compressed = gzip.compress(archive.getvalue(), compresslevel=9, mtime=0)
    parts = []
    for index, start in enumerate(range(0, len(compressed), 60000)):
        encoded = base64.b64encode(compressed[start:start + 60000])
        name = f"part_{index:04d}.b64"
        (target / name).write_bytes(encoded)
        parts.append(dict(path=name, bytes=len(encoded), sha256=sha(encoded)))
    manifest = dict(schema="hcsn-lossless-column-transport-v1", files=files,
        objects={identity:len(raw) for identity, raw in sorted(objects.items())},
        archive_sha256=sha(compressed), compressed_bytes=len(compressed),
        logical_bytes=sum(row["bytes"] for row in files), parts=parts,
        runtime=dict(python=platform.python_version(), zlib=zlib.ZLIB_RUNTIME_VERSION,
                     numpy=np.__version__, byteorder="little"),
        exactness="All original gzip bytes reserialized and compared before packing; no precision loss.")
    (target / "MANIFEST.json").write_bytes(encoded_json(manifest) + b"\n")
    print(json.dumps(dict(files=len(files), objects=len(objects), parts=len(parts),
                         logical_bytes=manifest["logical_bytes"], compressed_bytes=len(compressed))))


def restore(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    assert not destination.exists(), "Use a fresh destination; no existing files are replaced"
    manifest = json.loads((source / "MANIFEST.json").read_bytes())
    pieces = []
    for part in manifest["parts"]:
        raw = (source / part["path"]).read_bytes()
        assert len(raw) == part["bytes"] and sha(raw) == part["sha256"]
        pieces.append(base64.b64decode(raw, validate=True))
    archive = b"".join(pieces)
    assert sha(archive) == manifest["archive_sha256"]
    objects = {}
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(archive)), mode="r:") as package:
        for entry in package:
            assert entry.isfile() and entry.name in manifest["objects"]
            assert entry.name not in objects
            raw = package.extractfile(entry).read()
            assert len(raw) == manifest["objects"][entry.name] and sha(raw) == entry.name
            objects[entry.name] = raw
    assert set(objects) == set(manifest["objects"])
    destination.mkdir()
    for row in manifest["files"]:
        relative = PurePosixPath(row["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        if row["codec"] == "verbatim":
            raw = objects[row["object"]]
        else:
            value = {key:decode_column(d, objects[d["object"]]) for key, d in row["columns"].items()}
            raw = gzip.compress(encoded_json(value), mtime=0)
        assert len(raw) == row["bytes"] and sha(raw) == row["sha256"], row["path"]
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    print(json.dumps(dict(verified_original_files=len(manifest["files"]),
                         verified_raw_traces=sum(x["codec"] == "column-json-gzip" for x in manifest["files"]))))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("pack", "restore"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.mode == "pack":
        pack()
    else:
        assert args.source is not None and args.destination is not None
        restore(args.source, args.destination)


if __name__ == "__main__":
    main()
