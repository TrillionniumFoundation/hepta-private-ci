"""Lossless byte-chunk gzip packaging, with every repository file below 480 KB."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def verify(index, restore=None):
    for member in index["members"]:
        raw = bytearray()
        for row in member["chunks"]:
            compressed = (ROOT / row["path"]).read_bytes()
            assert len(compressed) == row["compressed_bytes"] <= 480000
            assert digest(compressed) == row["compressed_sha256"]
            part = gzip.decompress(compressed)
            assert len(raw) == row["offset"]
            assert len(part) == row["raw_bytes"] and digest(part) == row["raw_sha256"]
            raw.extend(part)
        assert len(raw) == member["bytes"] and digest(raw) == member["sha256"]
        json.loads(raw)
        if restore is not None:
            if Path(member["member"]).name != member["member"]:
                raise ValueError("Unsafe member name")
            restore.mkdir(parents=True, exist_ok=True)
            with (restore / member["member"]).open("xb") as stream:
                stream.write(raw)


def package(index_name="EVIDENCE_ARCHIVE.json", selected_members=None):
    index_path = ROOT / index_name
    if index_path.exists():
        verify(json.loads(index_path.read_text()))
        return
    directory = ROOT / "runtimearchive_chunks"
    directory.mkdir(exist_ok=True)
    members, by_digest = [], {}
    large = sorted(path for path in ROOT.glob("*.json") if path.stat().st_size > 480000
                   and (selected_members is None or path.name in selected_members))
    for path in large:
        raw = path.read_bytes()
        whole_sha = digest(raw)
        chunks = by_digest.get(whole_sha)
        if chunks is None:
            chunks, offset, number = [], 0, 0
            while offset < len(raw):
                length = min(2000000, len(raw) - offset)
                part = raw[offset:offset + length]
                compressed = gzip.compress(part, mtime=0)
                while len(compressed) > 480000:
                    length //= 2
                    part = raw[offset:offset + length]
                    compressed = gzip.compress(part, mtime=0)
                target = directory / f"{path.stem.lower()}.part{number:04d}.bytes.gz"
                with target.open("xb") as stream:
                    stream.write(compressed)
                chunks.append(dict(path=str(target.relative_to(ROOT)), offset=offset, raw_bytes=len(part),
                                   raw_sha256=digest(part), compressed_bytes=len(compressed), compressed_sha256=digest(compressed)))
                offset += length
                number += 1
            by_digest[whole_sha] = chunks
        members.append(dict(member=path.name, bytes=len(raw), sha256=whole_sha, chunks=chunks))
    index = dict(metadata=dict(schema="hcsn-full-hx-byte-chunks-v1", format="independent gzip of consecutive original UTF-8 byte ranges",
                               reconstruction="decompress chunks in order, concatenate, verify member SHA-256, then parse JSON",
                               maximum_chunk_file_bytes=480000, lossless_readback_verified=True), members=members)
    verify(index)
    with index_path.open("x") as stream:
        json.dump(index, stream, indent=2)
        stream.write("\n")
    for path in large:
        path.unlink()
    print(json.dumps(dict(members=len(members), unique_chunks=len(list(directory.glob("*.gz"))),
                         max_chunk_bytes=max((p.stat().st_size for p in directory.glob("*.gz")), default=0)), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore", type=Path)
    parser.add_argument("--index", default="EVIDENCE_ARCHIVE.json")
    parser.add_argument("--members", nargs="+")
    args = parser.parse_args()
    if args.restore is not None:
        verify(json.loads((ROOT / args.index).read_text()), args.restore)
    else:
        package(args.index, args.members)
