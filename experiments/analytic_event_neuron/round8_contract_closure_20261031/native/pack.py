"""Byte-preserving native executable/build-receipt bundle with small GitHub-safe parts.

This packages build receipts, source identities and exact qualified executables.
The root experiment packages raw task/owner evidence separately, avoiding a second
copy. Originals remain intact. Reassembly and every tar member are verified.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

MAX_PART = 384000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def verify(bundle):
    manifest = json.loads((bundle / "MANIFEST.json").read_text())
    inventory = []
    for part in manifest["inventory_parts"]:
        data = (bundle / part["path"]).read_bytes()
        if len(data) != part["bytes"] or sha(data) != part["sha256"]:
            raise ValueError("inventory part mismatch")
        inventory.extend(json.loads(data))
    stream = bytearray()
    for part in manifest["archive_parts"]:
        data = (bundle / part["path"]).read_bytes()
        if len(data) != part["bytes"] or sha(data) != part["sha256"]:
            raise ValueError("archive part mismatch")
        stream.extend(data)
    if sha(stream) != manifest["gzip_sha256"]:
        raise ValueError("reassembled archive identity mismatch")
    expected = {row["path"]: row for row in inventory}
    if len(expected) != len(inventory):
        raise ValueError("duplicate archive member")
    checked = []
    with tarfile.open(fileobj=io.BytesIO(stream), mode="r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if not member.isfile() or path.is_absolute() or ".." in path.parts or member.name not in expected:
                raise ValueError(("unexpected archive member", member.name))
            data = archive.extractfile(member).read()
            row = expected[member.name]
            if len(data) != row["bytes"] or sha(data) != row["sha256"]:
                raise ValueError(("member mismatch", member.name))
            checked.append(member.name)
    if sorted(checked) != sorted(expected):
        raise ValueError("incomplete bundle")
    return dict(verified_members=len(checked), gzip_sha256=manifest["gzip_sha256"],
                part_count=len(manifest["archive_parts"]), total_input_bytes=sum(r["bytes"] for r in inventory))


def pack(args):
    args.output.mkdir(parents=True, exist_ok=False)
    paths = []
    for label, root in (("build", args.build_evidence),):
        paths += [(label + "/" + p.relative_to(root).as_posix(), p) for p in sorted(root.rglob("*")) if p.is_file()]
    report = json.loads((args.build_evidence / "BUILD_ATTEMPT03.json").read_text())
    for name in ("binary", "tests"):
        path = Path(report[name])
        if sha(path.read_bytes()) != report[name + "_sha256"]:
            raise ValueError("qualified executable changed")
        paths.append(("executables/" + path.name, path))
    inventory, buffer = [], io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0, compresslevel=9) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|") as archive:
            for name, path in sorted(paths):
                if path.is_symlink():
                    raise ValueError("evidence symlink refused")
                data = path.read_bytes()
                inventory.append(dict(path=name, bytes=len(data), sha256=sha(data)))
                member = tarfile.TarInfo(name)
                member.size = len(data)
                member.mode = 0o755 if name.startswith("executables/") else 0o600
                member.mtime = 0
                archive.addfile(member, io.BytesIO(data))
    data = buffer.getvalue()
    parts = []
    for index, offset in enumerate(range(0, len(data), MAX_PART)):
        part = data[offset:offset + MAX_PART]
        filename = f"native-evidence.tar.gz.part{index:03d}"
        (args.output / filename).write_bytes(part)
        parts.append(dict(path=filename, bytes=len(part), sha256=sha(part)))
    inventory_parts, pending = [], []
    for row in inventory:
        if pending and len(encoded(pending + [row])) > MAX_PART:
            payload = encoded(pending)
            filename = f"inventory{len(inventory_parts):03d}.json"
            (args.output / filename).write_bytes(payload)
            inventory_parts.append(dict(path=filename, bytes=len(payload), sha256=sha(payload)))
            pending = []
        pending.append(row)
    if pending:
        payload = encoded(pending)
        filename = f"inventory{len(inventory_parts):03d}.json"
        (args.output / filename).write_bytes(payload)
        inventory_parts.append(dict(path=filename, bytes=len(payload), sha256=sha(payload)))
    manifest = dict(schema="hepta.native-evidence-bundle.v1", archive_format="concatenated binary parts of one gzip tar stream",
        gzip_sha256=sha(data), gzip_bytes=len(data), archive_parts=parts, inventory_parts=inventory_parts,
        member_count=len(inventory), total_input_bytes=sum(r["bytes"] for r in inventory),
        original_local_files_retained=True,
        source_build_receipt="build/BUILD_ATTEMPT03.json", qualified_binary="executables/r7-native-policy",
        raw_task_and_owner_evidence="Packaged by the root experiment separately; not duplicated here.")
    (args.output / "MANIFEST.json").write_bytes(encoded(manifest))
    checked = verify(args.output)
    (args.output / "READBACK.json").write_bytes(encoded(checked))
    print(json.dumps(checked))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    p = sub.add_parser("pack")
    for name in ("build-evidence", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p = sub.add_parser("verify")
    p.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "pack": pack(args)
    else: print(json.dumps(verify(args.bundle)))
