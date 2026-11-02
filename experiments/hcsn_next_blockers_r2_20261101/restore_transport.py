"""Restore a byte-identical archive from verified local or public GitHub parts.

Trust the manifest obtained at a reviewed commit. No archive extraction,
authentication, network retries or scientific model execution is performed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen

CHUNK_BYTES = 512 * 1024


def guard(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError(f"Symlinks are not accepted: {path}")
    return path


def pick(value, *names):
    found = [value[name] for name in names if name in value]
    if not found or any(item != found[0] for item in found[1:]):
        raise ValueError(f"Missing or conflicting manifest fields: {names}")
    return found[0]


def hex_value(value, length):
    if not isinstance(value, str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", value):
        raise ValueError("Invalid digest in manifest")
    return value


def blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data,
                        usedforsecurity=False).hexdigest()


def verify(data, part):
    if (len(data) != part["bytes"] or hashlib.sha256(data).hexdigest() != part["sha256"]
            or blob_sha(data) != part["git_blob_sha"]):
        raise ValueError(f"Part identity mismatch: {part['path']}")


def read_part(path, part):
    path = guard(path)
    if not path.is_file() or path.stat().st_size != part["bytes"]:
        raise ValueError(f"Part size/type mismatch: {path}")
    data = path.read_bytes()
    verify(data, part)
    return data


def normalize(value):
    repository = pick(value, "repository", "repo")
    if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected GitHub owner/repository")
    name = pick(value, "archive_name", "archive_filename")
    if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."} or "\\" in name:
        raise ValueError("Expected an archive basename")
    size = pick(value, "bytes", "archive_bytes")
    chunk = value.get("chunk_bytes", CHUNK_BYTES)
    if type(size) is not int or size <= 0 or type(chunk) is not int or not 0 < chunk <= CHUNK_BYTES:
        raise ValueError("Invalid archive/chunk size")
    parts = value["parts"]
    if not isinstance(parts, list) or not parts:
        raise ValueError("Expected a nonempty ordered parts list")
    result = []
    for index, part in enumerate(parts):
        path = PurePosixPath(part["path"])
        if (path.is_absolute() or ".." in path.parts or "\\" in str(path)
                or str(path) != part["path"] or path.name != f"part-{index:04d}.bin"):
            raise ValueError("Unsafe or out-of-order part path")
        amount = part["bytes"]
        if type(amount) is not int or not 0 < amount <= chunk or (index < len(parts) - 1 and amount != chunk):
            raise ValueError("Unexpected part size/order")
        result.append(dict(path=str(path), bytes=amount, sha256=hex_value(part["sha256"], 64),
                           git_blob_sha=hex_value(pick(part, "git_blob_sha", "git_blob", "gitblobsha"), 40)))
    if len({p["path"] for p in result}) != len(result) or sum(p["bytes"] for p in result) != size:
        raise ValueError("Part inventory disagrees with archive size")
    return dict(repository=repository, archive_name=name, bytes=size,
                sha256=hex_value(pick(value, "sha256", "archive_sha256"), 64), parts=result)


def publish(partial, destination):
    guard(partial); guard(destination)
    # link() creates exclusively; rename() could silently overwrite a racing destination.
    os.link(partial, destination, follow_symlinks=False)
    partial.unlink()


def fetch(part, directory, repository, ref):
    destination = guard(directory / PurePosixPath(part["path"]).name)
    if destination.exists():
        read_part(destination, part)
        return destination, True
    partial = guard(destination.with_name(destination.name + ".partial"))
    if partial.exists():
        # A complete verified partial may be promoted. Incomplete/corrupt bytes
        # stay untouched and stop the run; they are never resumed or retried.
        read_part(partial, part)
        publish(partial, destination)
        return destination, True
    url = f"https://raw.githubusercontent.com/{repository}/{quote(ref, safe='/')}/{quote(part['path'], safe='/')}"
    request = Request(url, headers={"Accept-Encoding": "identity", "User-Agent": "HCSN-evidence-restorer/2"})
    with partial.open("xb") as stream:
        with urlopen(request, timeout=60) as response:
            if response.status != 200:
                raise ValueError(f"Expected HTTP200: {url}")
            announced = response.headers.get("Content-Length")
            if announced is not None and int(announced) != part["bytes"]:
                raise ValueError(f"Unexpected response size: {url}")
            count = 0
            while block := response.read(min(65536, part["bytes"] + 1 - count)):
                stream.write(block); count += len(block)
                if count > part["bytes"]:
                    raise ValueError(f"Response exceeded registered part size: {url}")
        stream.flush(); os.fsync(stream.fileno())
    read_part(partial, part)
    publish(partial, destination)
    return destination, False


def assemble(manifest, paths, output):
    output = guard(output)
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = guard(output.with_name(output.name + ".partial"))
    h = hashlib.sha256(); count = 0
    with partial.open("xb") as stream:
        for part, path in zip(manifest["parts"], paths, strict=True):
            data = read_part(path, part)
            stream.write(data); h.update(data); count += len(data)
        stream.flush(); os.fsync(stream.fileno())
    if count != manifest["bytes"] or h.hexdigest() != manifest["sha256"]:
        raise ValueError(f"Final archive mismatch; partial retained: {partial}")
    publish(partial, output)
    return dict(verified=True, output=str(output), bytes=count, sha256=h.hexdigest(), parts=len(paths))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("TRANSPORT_MANIFEST.json"))
    parser.add_argument("--output", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--parts-dir", type=Path, help="Directory directly containing part-0000.bin, etc.")
    source.add_argument("--ref", help="Explicit reviewed final GitHub commit SHA or branch; commit preferred")
    parser.add_argument("--cache-dir", type=Path, help="Remote mode verified-part cache; never auto-overwrites")
    args = parser.parse_args()
    raw = guard(args.manifest).read_bytes(); manifest = normalize(json.loads(raw))
    output = guard(args.output)
    if output.exists() or guard(output.with_name(output.name + ".partial")).exists():
        raise FileExistsError("Output or its .partial already exists; preserve/move it before restarting")
    if args.parts_dir is not None:
        directory = guard(args.parts_dir)
        if args.cache_dir is not None:
            raise ValueError("--cache-dir is only for public remote mode")
        paths = [directory / PurePosixPath(p["path"]).name for p in manifest["parts"]]
        for part, path in zip(manifest["parts"], paths, strict=True): read_part(path, part)
        reused = len(paths)
    else:
        if (not re.fullmatch(r"[A-Za-z0-9._/-]+", args.ref)
                or args.ref.startswith("/") or ".." in PurePosixPath(args.ref).parts):
            raise ValueError("Invalid explicit GitHub ref")
        directory = guard(args.cache_dir or output.with_name(output.name + ".parts-cache"))
        directory.mkdir(parents=True, exist_ok=True)
        paths = []; reused = 0
        for index, part in enumerate(manifest["parts"]):
            path, old = fetch(part, directory, manifest["repository"], args.ref)
            paths.append(path); reused += old
            if (index + 1) % 16 == 0 or index + 1 == len(manifest["parts"]):
                print(json.dumps(dict(verified_parts=index + 1, total_parts=len(manifest["parts"]))), file=sys.stderr)
    receipt = assemble(manifest, paths, output)
    receipt.update(manifest_sha256=hashlib.sha256(raw).hexdigest(),
                   source_ref=args.ref, verified_parts_reused=reused)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
