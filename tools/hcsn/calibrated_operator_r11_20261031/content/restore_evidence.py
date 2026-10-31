"""Deterministic bounded archival and exact, exclusive-create restoration.

Packing may retire only verified duplicate files in this workstream's evidence
directory. Every original member remains addressed by path, bytes and SHA256.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

HERE = Path(__file__).resolve().parent
MAX_BYTES = 400000
KEEP = {"PROTOCOL.json", "REGISTRATION.json", "FREEZE.json", "RESULTS.json",
        "SUMMARY.json", "READ_ONLY_REVIEW.json", "CONTENT_AUDIT.json"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def pack(root):
    if root.parent != HERE/"evidence" or (root/"INDEX.json").exists():
        raise ValueError("Packing is restricted to a fresh direct evidence child")
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if any(p.is_symlink() for p in root.rglob("*")):
        raise ValueError("Symlinks are not evidence members")
    keep = {str(p.relative_to(root)): dict(bytes=p.stat().st_size, sha256=sha(p.read_bytes())) for p in files if str(p.relative_to(root)) in KEEP}
    payload = [p for p in files if str(p.relative_to(root)) not in keep]
    members, archives = {}, {}

    def emit(group):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for path in group:
                raw = path.read_bytes(); name = str(path.relative_to(root))
                item = tarfile.TarInfo(name); item.size = len(raw); item.mode = 0o644; item.mtime = 0
                archive.addfile(item, io.BytesIO(raw))
        compressed = gzip.compress(buffer.getvalue(), mtime=0)
        if len(compressed) > MAX_BYTES:
            if len(group) == 1:
                raise ValueError(("Member exceeds archive limit", str(group[0])))
            middle = len(group)//2; emit(group[:middle]); emit(group[middle:]); return
        name = f"raw_part{len(archives):04d}.tar.gz"
        with (root/name).open("xb") as stream:
            stream.write(compressed)
        archives[name] = dict(bytes=len(compressed), sha256=sha(compressed))
        with tarfile.open(root/name, "r:gz") as archive:
            for item in archive.getmembers():
                if not item.isfile():
                    raise ValueError("Non-file archive member")
                raw = archive.extractfile(item).read(); original = (root/item.name).read_bytes()
                if raw != original:
                    raise ValueError(("Readback mismatch", item.name))
                members[item.name] = dict(archive=name, bytes=len(raw), sha256=sha(raw))

    pending, count = [], 0
    for path in payload:
        pending.append(path); count += path.stat().st_size
        if count >= 1000000:
            emit(pending); pending, count = [], 0
    if pending:
        emit(pending)
    if len(members) != len(payload):
        raise ValueError("Incomplete original member inventory")
    index = dict(schema="hcsn.r11.content.archive.v1", maximum_archive_bytes=MAX_BYTES,
        archives=archives, members=members, kept=keep,
        original_files=len(files), original_bytes=sum(p.stat().st_size for p in files),
        readback_verified_before_retiring_duplicates=True)
    save(root/"INDEX.json", index)
    # Only exact, independently read-back duplicates of this study are retired.
    for path in payload:
        spec = members[str(path.relative_to(root))]
        if sha(path.read_bytes()) != spec["sha256"]:
            raise ValueError("Original changed between verification and retirement")
        path.unlink()
    final = [p for p in root.rglob("*") if p.is_file()]
    save(root/"PACKAGING_RECEIPT.json", dict(completed_at=datetime.now(timezone.utc).isoformat(),
        retired_verified_duplicate_count=len(payload), kept_original_count=len(keep), archives=len(archives),
        archive_bytes=sum(v["bytes"] for v in archives.values()), largest_archive=max(v["bytes"] for v in archives.values()),
        files_before_this_receipt=len(final), index_sha256=sha((root/"INDEX.json").read_bytes())))
    return index


def restore(root, destination):
    index = json.loads((root/"INDEX.json").read_text())
    destination.mkdir(parents=True, exist_ok=False)
    count, total = 0, 0
    for name, spec in index["kept"].items():
        raw = (root/name).read_bytes()
        if len(raw) != spec["bytes"] or sha(raw) != spec["sha256"]:
            raise ValueError(("Kept source changed", name))
        with (destination/name).open("xb") as stream:
            stream.write(raw)
        count += 1; total += len(raw)
    seen = set()
    for name, spec in index["archives"].items():
        path = root/name
        if path.stat().st_size != spec["bytes"] or sha(path.read_bytes()) != spec["sha256"]:
            raise ValueError(("Archive identity mismatch", name))
        with tarfile.open(path, "r:gz") as archive:
            for item in archive.getmembers():
                relative = PurePosixPath(item.name)
                if relative.is_absolute() or ".." in relative.parts or not item.isfile() or item.name in seen:
                    raise ValueError("Invalid archive member")
                member = index["members"][item.name]
                raw = archive.extractfile(item).read()
                if member["archive"] != name or len(raw) != member["bytes"] or sha(raw) != member["sha256"]:
                    raise ValueError(("Original member identity mismatch", item.name))
                output = destination/relative
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("xb") as stream:
                    stream.write(raw)
                seen.add(item.name); count += 1; total += len(raw)
    if seen != set(index["members"]) or count != index["original_files"] or total != index["original_bytes"]:
        raise ValueError("Incomplete restore")
    return dict(files_restored=count, bytes_restored=total, index_sha256=sha((root/"INDEX.json").read_bytes()), all_member_hashes_verified=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("mode", choices=["pack", "restore"])
    parser.add_argument("root", type=Path); parser.add_argument("--destination", type=Path)
    args = parser.parse_args(); root = args.root.resolve()
    if args.mode == "pack":
        result = pack(root)
        print(json.dumps(dict(members=len(result["members"]), archives=len(result["archives"]), kept=len(result["kept"]))))
    else:
        if args.destination is None:
            raise ValueError("An exclusive fresh restoration destination is required")
        print(json.dumps(restore(root, args.destination.resolve())))
