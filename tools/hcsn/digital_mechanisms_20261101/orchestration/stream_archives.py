"""Disk-backed archive-v2 transport; fixed buffers, paged indexes, no scientific imports.
Only compact part/page descriptors remain in RAM; restore indexes use disk SQLite.
Pack permits a new basename in an existing directory; restore requires a new
directory and retains incomplete output on failure without emitting success.
"""
import argparse
import base64
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import tarfile
import tempfile
import time


CHUNK, BLOCK = 337500, 1024 * 1024

def safe_path(name, leaf=False):
    if (not isinstance(name, str) or not name or "\\" in name or "\0" in name
            or any(x in ("", ".", "..") for x in name.split("/"))
            or PurePosixPath(name).is_absolute() or ":" in name
            or (leaf and "/" in name)):
        raise ValueError("unsafe or noncanonical archive path")
    return name

def write_json(path, value):
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
    return dict(name=path.name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

def read_json(path):
    with path.open("rb") as stream:
        raw = stream.read(16 * BLOCK + 1)
    if len(raw) > 16 * BLOCK:
        raise ValueError("JSON metadata exceeds 16 MiB")
    return json.loads(raw)

class HashReader:
    def __init__(self, stream):
        self.stream, self.sha, self.count, self.tail = stream, hashlib.sha256(), 0, b""

    def read(self, size):
        raw = self.stream.read(size)
        self.sha.update(raw)
        self.count += len(raw)
        self.tail = (self.tail + raw)[-512:]
        return raw

def file_hash(path):
    with path.open("rb") as stream:
        reader = HashReader(stream)
        while reader.read(BLOCK):
            pass
    return reader.sha.hexdigest()

def walk_files(path):
    if path.name == "__pycache__":
        return
    kind = path.lstat().st_mode
    if stat.S_ISREG(kind):
        yield path
    elif stat.S_ISDIR(kind):
        for child in sorted(path.iterdir()):
            yield from walk_files(child)
    else:
        raise ValueError("source contains a symlink or nonregular file: " + str(path))

def selected_roots(source, fits):
    if fits is None:
        return [source], {}
    if not fits or len(set(fits)) != len(fits) or any(type(n) is not int or n < 0 for n in fits):
        raise ValueError("fit IDs must be distinct nonnegative integers")
    roots, markers = [], {}
    for fit in sorted(fits):
        folder = source / f"fit_{fit}"
        finish = folder / "FINISHED.json"
        receipt = source / "process_receipts" / f"fit_{fit}.json"
        done, process = read_json(finish), read_json(receipt)
        started = read_json(folder / "STARTED.json")
        if (not folder.is_dir() or folder.is_symlink() or done.get("fit") != fit
                or started.get("fit") != fit or process.get("fit") != fit
                or process.get("stage") not in ("train", "confirm")
                or type(process.get("returncode")) is not int or process["returncode"] != 0):
            raise ValueError("selected formal fit lacks successful FINISHED and wait4 receipts")
        logs = [receipt.with_suffix("." + suffix) for suffix in ("json", "stdout", "stderr")]
        required = [finish, folder / "STARTED.json", *logs]
        if process["stage"] == "train":
            if done.get("development") is not False or not done.get("models") or started.get("stage") != "formal_fit":
                raise ValueError("completed formal training fit required")
            if {p.name for p in (folder / "models").iterdir()} != {name + ".json" for name in done["models"]}:
                raise ValueError("selected fit model inventory differs from FINISHED")
            required.append(folder / "extended_data.json.gz")
            for identifier, record in done["models"].items():
                expected = "models/" + safe_path(identifier, leaf=True) + ".json"
                if record["path"] != expected:
                    raise ValueError("unexpected declared model path")
                markers[folder / expected] = record["sha256"]
                required.extend([folder / expected, folder / "training" / (identifier + ".json.gz")])
        else:
            commit = started.get("published_model_commit", "")
            if (not isinstance(commit, str) or len(commit) != 40 or set(commit) - set("0123456789abcdef")
                    or started.get("confirmation_preexisting") is not False):
                raise ValueError("completed confirmation requires published model provenance")
            required.extend(folder / name for name in ("iid_cohort.json", "ood_cohort.json", "iid_episodes.json.gz",
                                                       "ood_episodes.json.gz", "summary.json", "runtime.json"))
        for path in required:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("selected fit is missing a regular required artifact")
            sha = file_hash(path)
            if path in markers and markers[path] != sha:
                raise ValueError("selected fit model differs from FINISHED")
            markers[path] = sha
        roots.extend([folder, *logs])
    return roots, markers

def pack_directory(source, destination, basename="evidence", fits=None):
    source, destination = Path(source).resolve(strict=True), Path(destination).resolve()
    safe_path(basename, leaf=True)
    if not source.is_dir() or source == destination or source in destination.parents:
        raise ValueError("source directory and separate destination required")
    roots, markers = selected_roots(source, fits)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.glob(basename + ".*")):
        raise FileExistsError("archive basename already has artifacts")
    entries, pages, parts, count = [], [], [], 0
    with tempfile.TemporaryFile(dir=destination) as packed:
        with gzip.GzipFile(filename="", fileobj=packed, mode="wb", compresslevel=6, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for root in roots:
                    for path in walk_files(root):
                        name = safe_path(path.relative_to(source).as_posix())
                        with path.open("rb") as stream:
                            before = os.fstat(stream.fileno())
                            if not stat.S_ISREG(before.st_mode):
                                raise ValueError("source changed to nonregular file")
                            reader, info = HashReader(stream), tarfile.TarInfo(name)
                            info.size, info.mtime, info.mode = before.st_size, 0, 0o644
                            archive.addfile(info, reader)
                            archive.members.clear()
                            after = os.fstat(stream.fileno())
                        current = path.lstat()
                        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
                        if (reader.count != before.st_size or (path in markers and reader.sha.hexdigest() != markers[path])
                                or any(getattr(before, f) != getattr(s, f)
                                for f in fields for s in (after, current))):
                            raise ValueError("source changed while packing: " + name)
                        entries.append(dict(path=name, bytes=reader.count, sha256=reader.sha.hexdigest()))
                        count += 1
                        if len(entries) == 500:
                            pages.append(write_json(destination / f"{basename}.files{len(pages):04d}.json", entries))
                            entries = []
        if entries:
            pages.append(write_json(destination / f"{basename}.files{len(pages):04d}.json", entries))
        packed.seek(0)
        archive_hash, archive_bytes = hashlib.sha256(), 0
        while raw := packed.read(CHUNK):
            archive_hash.update(raw)
            archive_bytes += len(raw)
            encoded = base64.b64encode(raw) + b"\n"
            path = destination / f"{basename}.part{len(parts):04d}.b64"
            with path.open("xb") as stream:
                stream.write(encoded)
            parts.append(dict(name=path.name, bytes=len(encoded), sha256=hashlib.sha256(encoded).hexdigest()))
    if any(file_hash(path) != sha for path, sha in markers.items()):
        raise ValueError("selected fit completion/process receipt changed during pack")
    manifest = dict(schema="digital-mechanism-archive-v2", archive_sha256=archive_hash.hexdigest(),
                    archive_bytes=archive_bytes, parts=parts, file_pages=pages, file_count=count,
                    timestamps="not preserved; chronological claims use original explicit receipt UTC only")
    write_json(destination / f"{basename}.manifest.json", manifest)
    return manifest

def verified_blob(parent, entry, limit, referenced):
    name = safe_path(entry["name"], leaf=True)
    if name in referenced or type(entry["bytes"]) is not int or not 0 < entry["bytes"] <= limit:
        raise ValueError("duplicate or invalid archive volume/page")
    referenced.add(name)
    path = parent / name
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("archive volume/page is not a regular file")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError("archive volume/page byte count or hash mismatch")
    return raw

def restore_archive(manifest_path, destination):
    manifest_path, destination = Path(manifest_path), Path(destination)
    manifest, referenced = read_json(manifest_path), set()
    if (manifest["schema"] != "digital-mechanism-archive-v2" or not manifest["parts"]
            or type(manifest["file_count"]) is not int or manifest["file_count"] < 0
            or type(manifest["archive_bytes"]) is not int or manifest["archive_bytes"] <= 0
            or len(manifest["file_pages"]) != (manifest["file_count"] + 499) // 500):
        raise ValueError("invalid archive-v2 manifest")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("restore destination must be new")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        with closing(sqlite3.connect(Path(temporary) / "index.sqlite")) as index:
            index.execute("PRAGMA cache_size=-1024")
            index.execute("CREATE TABLE files(path TEXT PRIMARY KEY, bytes INTEGER, sha TEXT, seen INTEGER DEFAULT 0)")
            count = 0
            for page in manifest["file_pages"]:
                entries = json.loads(verified_blob(manifest_path.parent, page, 16 * BLOCK, referenced))
                if not isinstance(entries, list) or len(entries) != min(500, manifest["file_count"] - count):
                    raise ValueError("file-index page count mismatch")
                for entry in entries:
                    name = safe_path(entry["path"])
                    if (type(entry["bytes"]) is not int or entry["bytes"] < 0
                            or not isinstance(entry["sha256"], str) or len(entry["sha256"]) != 64
                            or set(entry["sha256"]) - set("0123456789abcdef")):
                        raise ValueError("invalid file-index metadata")
                    index.execute("INSERT INTO files(path,bytes,sha) VALUES(?,?,?)", (name, entry["bytes"], entry["sha256"]))
                count += len(entries)
            index.commit()
            archive_hash, archive_bytes = hashlib.sha256(), 0
            packed_path = Path(temporary) / "archive.gz"
            with packed_path.open("xb") as packed:
                for number, part in enumerate(manifest["parts"]):
                    raw = verified_blob(manifest_path.parent, part, 450001, referenced)
                    if (not raw.endswith(b"\n") or len(raw) < 5
                            or (number + 1 < len(manifest["parts"]) and len(raw) != 450001)):
                        raise ValueError("invalid base64 volume framing")
                    decoded = base64.b64decode(raw[:-1], validate=True)
                    if base64.b64encode(decoded) != raw[:-1] or (number + 1 < len(manifest["parts"]) and len(decoded) != CHUNK):
                        raise ValueError("noncanonical or prematurely padded base64 volume")
                    packed.write(decoded)
                    archive_hash.update(decoded)
                    archive_bytes += len(decoded)
            if archive_bytes != manifest["archive_bytes"] or archive_hash.hexdigest() != manifest["archive_sha256"]:
                raise ValueError("compressed archive byte count or hash mismatch")
            destination.mkdir(exist_ok=False)
            seen, end = 0, 0
            with gzip.open(packed_path, "rb") as zipped:
                reader = HashReader(zipped)
                with tarfile.open(fileobj=reader, mode="r|", bufsize=512) as archive:
                    for member in archive:
                        name = safe_path(member.name)
                        entry = index.execute("SELECT bytes,sha,seen FROM files WHERE path=?", (name,)).fetchone()
                        if (not entry or entry[2] or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE)
                                or member.sparse is not None or member.size != entry[0]):
                            raise ValueError("unexpected, duplicate, unsafe, or incorrectly sized tar member")
                        out = destination / name
                        out.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as source, out.open("xb") as target:
                            contents = HashReader(source)
                            while raw := contents.read(BLOCK):
                                target.write(raw)
                        if contents.count != entry[0] or contents.sha.hexdigest() != entry[1]:
                            raise ValueError("restored member byte count or hash mismatch")
                        index.execute("UPDATE files SET seen=1 WHERE path=?", (name,))
                        seen += 1
                        end = member.offset_data + ((member.size + 511) // 512) * 512
                        archive.members.clear()
                if reader.count != end + 512 or reader.tail != bytes(512):
                    raise ValueError("missing tar end marker or unexpected read-ahead")
                padding = 0
                while raw := zipped.read(BLOCK):
                    if any(raw):
                        raise ValueError("nonzero content after tar end marker")
                    padding += len(raw)
                if padding < 512 or padding % 512 or seen != manifest["file_count"]:
                    raise ValueError("incomplete tar end padding or missing members")
    return seen

def main():
    wall, cpu = time.perf_counter(), time.process_time()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("pack", "restore"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--basename", default="evidence")
    parser.add_argument("--fits", type=int, nargs="+")
    args = parser.parse_args()
    receipt = dict(stage=args.stage, source=str(args.source), destination=str(args.destination), success=False)
    try:
        if args.stage == "pack":
            result = pack_directory(args.source, args.destination, args.basename, args.fits)
            receipt.update(files=result["file_count"], parts=len(result["parts"]), archive_bytes=result["archive_bytes"], fits=args.fits)
        else:
            if args.fits is not None:
                raise ValueError("--fits is only valid for pack")
            receipt["files"] = restore_archive(args.source, args.destination)
        receipt["success"] = True
    except Exception as error:
        receipt.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        receipt.update(wall_seconds=time.perf_counter() - wall, process_cpu_seconds=time.process_time() - cpu)
        print(json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
