"""Lossless archives for a quiescent Linux run tree; no source files are changed.

Observed inode/metadata stability is not an atomic snapshot or owner authentication.
"""

import argparse
from collections import defaultdict
from functools import lru_cache
import hashlib
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tempfile

CHUNK = 300000
ASSET_LIMIT = 450000
BATCH_BYTES = 8 * 1024**2
TAR_LIMIT = 9 * 1024**2
MANIFEST_LIMIT = 256 * 1024**2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    ).encode()


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    return json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda value: require(False, "non-finite JSON"),
    )


def signature(value):
    keys = "dev ino mode size mtime_ns ctime_ns nlink".split()
    return [getattr(value, "st_" + key) for key in keys]


def relative(name):
    require(isinstance(name, str) and name, "empty or non-text path")
    path = PurePosixPath(name)
    require(
        str(path) == name
        and not path.is_absolute()
        and "\\" not in name
        and all(p not in {".", ".."} for p in path.parts),
        "noncanonical path",
    )
    name.encode("utf-8", errors="strict")
    return path.parts


def directory(path):
    path = Path(path).absolute()
    for item in reversed([path, *path.parents]):
        require(stat.S_ISDIR(item.lstat().st_mode), "symlink or non-directory ancestor")
    return path.resolve(strict=True)


def open_file(root_fd, name):
    parts = relative(name)
    fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        result = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
        )
    finally:
        os.close(fd)
    return result


def snapshot(root_fd):
    rows = {"": {"kind": "directory", "stat": signature(os.fstat(root_fd))}}

    def visit(fd, prefix):
        before = signature(os.fstat(fd))
        with os.scandir(fd) as stream:
            names = sorted(entry.name for entry in stream)
        for entry in names:
            name = "/".join((*prefix, entry))
            relative(name)
            value = os.stat(entry, dir_fd=fd, follow_symlinks=False)
            kind = "directory" if stat.S_ISDIR(value.st_mode) else "file"
            require(
                kind == "directory" or stat.S_ISREG(value.st_mode),
                "symlink or nonregular source: " + name,
            )
            rows[name] = {"kind": kind, "stat": signature(value)}
            if kind == "directory":
                child = os.open(
                    entry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                )
                try:
                    require(
                        signature(os.fstat(child)) == rows[name]["stat"],
                        "directory replaced",
                    )
                    visit(child, (*prefix, entry))
                finally:
                    os.close(child)
        require(
            signature(os.fstat(fd)) == before, "directory changed during enumeration"
        )

    visit(root_fd, ())
    return rows


def binding(name, raw):
    return {
        "path": name,
        "bytes": len(raw),
        "sha256": sha(raw),
        "git_blob_sha1": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def pack(output, prefix, payloads):
    assets, locations, group, budget = [], {}, [], 0

    def flush(batch):
        if not batch:
            return
        buffer = io.BytesIO()
        with tarfile.open(
            fileobj=buffer, mode="w:xz", format=tarfile.USTAR_FORMAT, preset=6
        ) as stream:
            for member, raw in batch:
                info = tarfile.TarInfo(member)
                info.size, info.mode, info.mtime = len(raw), 0o444, 0
                stream.addfile(info, io.BytesIO(raw))
        raw = buffer.getvalue()
        if len(raw) >= ASSET_LIMIT:
            require(len(batch) > 1, "single chunk exceeds asset limit")
            middle = len(batch) // 2
            flush(batch[:middle])
            flush(batch[middle:])
            return
        name = f"{prefix}-{len(assets) + 1:05d}.tar.xz"
        with (output / name).open("xb") as stream:
            stream.write(raw)
        assets.append(binding(name, raw))
        for member, data in batch:
            locations[member] = {
                "asset": name,
                "member": member,
                "bytes": len(data),
                "sha256": sha(data),
            }

    for member, raw in payloads:
        require(len(raw) <= CHUNK, "payload exceeds chunk bound")
        if group and (budget + len(raw) > BATCH_BYTES or len(group) == 256):
            flush(group)
            group, budget = [], 0
        group.append((member, raw))
        budget += len(raw)
    flush(group)
    return assets, locations


def read_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode) and before.st_size < ASSET_LIMIT, "bad asset"
        )
        raw = stream.read(ASSET_LIMIT)
        require(
            signature(before) == signature(os.fstat(stream.fileno())), "asset changed"
        )
    return raw


def asset_members(output, record, expected):
    name = record["path"]
    require(relative(name) == (name,), "asset path must be a basename")
    raw = read_regular(output / name)
    require(binding(name, raw) == record, "asset binding mismatch")
    decoder = lzma.LZMADecompressor(memlimit=128 * 1024**2)
    unpacked = decoder.decompress(raw, max_length=TAR_LIMIT + 1)
    require(
        decoder.eof and not decoder.unused_data and len(unpacked) <= TAR_LIMIT,
        "tar expansion bound or trailing compressed stream",
    )
    found, offset = {}, 0
    with tarfile.open(fileobj=io.BytesIO(unpacked), mode="r:") as stream:
        for member in stream:
            require(
                member.offset == offset
                and member.offset_data == offset + 512
                and member.type == tarfile.REGTYPE
                and member.sparse is None,
                "noncanonical tar header or hidden extension",
            )
            require(
                member.name in expected
                and member.name not in found
                and member.isfile()
                and not member.pax_headers
                and member.size == expected[member.name]["bytes"]
                and 0 <= member.size <= CHUNK,
                "unexpected or malformed tar member",
            )
            data = stream.extractfile(member).read(CHUNK + 1)
            require(
                len(data) == member.size
                and sha(data) == expected[member.name]["sha256"],
                "member hash mismatch",
            )
            found[member.name] = data
            offset = member.offset_data + ((member.size + 511) // 512) * 512
            require(
                not any(unpacked[member.offset_data + member.size : offset]),
                "nonzero member padding",
            )
    require(
        len(unpacked) >= offset + 1024
        and len(unpacked) % tarfile.RECORDSIZE == 0
        and not any(unpacked[offset:]),
        "missing or nonzero tar trailer",
    )
    require(found.keys() == expected.keys(), "missing tar members")
    return found


def reader(output, records, rows):
    assets = {item["path"]: item for item in records}
    require(len(assets) == len(records), "asset duplication")
    expected = defaultdict(dict)
    for row in rows:
        name, member = row["asset"], row["member"]
        require(name in assets and member not in expected[name], "bad member identity")
        expected[name][member] = row
    require(expected.keys() == assets.keys(), "unreferenced asset")

    @lru_cache(maxsize=4)
    def content(name):
        return asset_members(output, assets[name], expected[name])

    for name in assets:
        content(name)
    return content


def verify(output, index=None):
    output = directory(output)
    published = index is None
    if published:
        index = strict_json(read_regular(output / "INDEX.json"))
    require(
        index["schema"] == "hepta.mem5.raw-archive-index.v1", "unknown archive index"
    )
    descriptor = index["manifest"]
    require(
        type(descriptor["bytes"]) is int and 0 < descriptor["bytes"] <= MANIFEST_LIMIT,
        "manifest exceeds bound",
    )
    content = reader(output, descriptor["assets"], descriptor["parts"])
    manifest_raw = b"".join(
        content(p["asset"])[p["member"]] for p in descriptor["parts"]
    )
    require(
        len(manifest_raw) == descriptor["bytes"]
        and sha(manifest_raw) == descriptor["sha256"],
        "manifest hash mismatch",
    )
    manifest = strict_json(manifest_raw)
    require(manifest["schema"] == "hepta.mem5.raw-manifest.v1", "unknown manifest")
    content = reader(output, manifest["assets"], manifest["chunks"].values())
    referenced_chunks = set()
    for key, value in manifest["objects"].items():
        checksum, count = hashlib.sha256(), 0
        for chunk_id in value["chunks"]:
            chunk = manifest["chunks"][chunk_id]
            require(chunk_id == chunk["sha256"], "bad chunk identity")
            raw = content(chunk["asset"])[chunk["member"]]
            checksum.update(raw)
            count += len(raw)
            referenced_chunks.add(chunk_id)
        require(
            count == value["bytes"] and checksum.hexdigest() == key,
            "object reconstruction mismatch",
        )
    require(referenced_chunks == manifest["chunks"].keys(), "unreferenced chunk")
    referenced = set()
    for name, value in manifest["files"].items():
        relative(name)
        key = value["sha256"]
        require(
            key == value["object_sha256"]
            and key in manifest["objects"]
            and value["bytes"] == manifest["objects"][key]["bytes"],
            "logical file mismatch",
        )
        referenced.add(key)
    require(referenced == manifest["objects"].keys(), "unreferenced object")
    names = [x["path"] for x in descriptor["assets"] + manifest["assets"]]
    require(len(names) == len(set(names)), "duplicate asset path")
    require(
        set(p.name for p in output.iterdir())
        == set(names) | ({"INDEX.json"} if published else set()),
        "unexpected archive output entry",
    )
    return {
        "status": "verified",
        "logical_files": len(manifest["files"]),
        "logical_bytes": sum(v["bytes"] for v in manifest["files"].values()),
        "unique_objects": len(manifest["objects"]),
        "unique_chunks": len(manifest["chunks"]),
        "assets": len(names),
        "manifest_sha256": descriptor["sha256"],
        "all_logical_files_reconstructible": True,
        "source_owner_authenticated": False,
    }


def archive(source, output):
    source, output = directory(source), Path(output).absolute()
    parent = directory(output.parent)
    output = parent / output.name
    require(
        source != output and source not in output.parents, "output lies inside source"
    )
    require(not output.exists() and not output.is_symlink(), "output must be fresh")
    output.mkdir()
    root_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        initial, files, objects, chunks = snapshot(root_fd), {}, {}, {}
        with tempfile.TemporaryDirectory(
            prefix=output.name + ".stage-", dir=parent
        ) as temporary:
            staging = Path(temporary)
            for name, record in sorted(initial.items()):
                if record["kind"] != "file":
                    continue
                fd = open_file(root_fd, name)
                checksum, count, sequence = hashlib.sha256(), 0, []
                with os.fdopen(fd, "rb") as stream:
                    require(
                        signature(os.fstat(stream.fileno())) == record["stat"],
                        "source file replaced",
                    )
                    while raw := stream.read(CHUNK):
                        checksum.update(raw)
                        count += len(raw)
                        chunk_id = sha(raw)
                        if chunk_id not in chunks:
                            (staging / chunk_id).write_bytes(raw)
                            chunks[chunk_id] = {"bytes": len(raw), "sha256": chunk_id}
                        else:
                            require(
                                (staging / chunk_id).read_bytes() == raw,
                                "chunk collision",
                            )
                        sequence.append(chunk_id)
                    require(
                        signature(os.fstat(stream.fileno())) == record["stat"]
                        and count == record["stat"][3],
                        "source file changed",
                    )
                key, value = checksum.hexdigest(), {"bytes": count, "chunks": sequence}
                require(key not in objects or objects[key] == value, "object collision")
                objects[key] = value
                files[name] = {"bytes": count, "sha256": key, "object_sha256": key}
            assets, locations = pack(
                output,
                "objects",
                (
                    ("chunks/" + key, (staging / key).read_bytes())
                    for key in sorted(chunks)
                ),
            )
        chunks = {key: locations["chunks/" + key] for key in chunks}
        manifest = {
            "schema": "hepta.mem5.raw-manifest.v1",
            "source_root": str(source),
            "source_root_stat": initial[""]["stat"],
            "source_entry_count": len(initial),
            "source_roster_sha256": sha(encoded(initial)),
            "files": files,
            "objects": objects,
            "chunks": chunks,
            "assets": assets,
            "all_regular_files_included": True,
            "source_owner_authenticated": False,
        }
        raw = encoded(manifest)
        require(len(raw) <= MANIFEST_LIMIT, "manifest exceeds bound")
        parts = [
            (f"manifest-parts/{offset // CHUNK:05d}", raw[offset : offset + CHUNK])
            for offset in range(0, len(raw), CHUNK)
        ]
        index_assets, index_locations = pack(output, "manifest", parts)
        index = {
            "schema": "hepta.mem5.raw-archive-index.v1",
            "source_root": str(source),
            "manifest": {
                "bytes": len(raw),
                "sha256": sha(raw),
                "assets": index_assets,
                "parts": [index_locations[name] for name, _ in parts],
            },
            "all_regular_files_included": True,
            "source_unchanged_around_archive": True,
            "source_owner_authenticated": False,
        }
        result = verify(output, index)
        require(snapshot(root_fd) == initial, "source tree changed during archival")
        require(
            signature(source.lstat()) == initial[""]["stat"], "source root replaced"
        )
        raw = encoded(index)
        require(len(raw) < ASSET_LIMIT, "index exceeds asset bound")
        with (output / "INDEX.json").open("xb") as stream:
            stream.write(raw)
        return result
    finally:
        os.close(root_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    require(args.verify or args.source is not None, "--source is required for creation")
    print(
        json.dumps(
            verify(args.output) if args.verify else archive(args.source, args.output),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
