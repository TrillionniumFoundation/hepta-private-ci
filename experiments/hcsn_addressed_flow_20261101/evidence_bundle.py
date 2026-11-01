"""Portable, content-verified packaging for the complete additive experiment.

Run from the repository root. Packing excludes its own artifacts directory.
Restoring refuses links, path escapes, duplicate members and conflicting files.
This tool does not execute saved models or mutate scientific protocols.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile


EXPERIMENT = Path("experiments/hcsn_addressed_flow_20261101")
PART_BYTES = 512 * 1024


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("Unsafe archive path: " + value)
    if not path.parts or path.parts[:2] != tuple(EXPERIMENT.parts):
        raise ValueError("Path is outside the additive experiment: " + value)
    return path


def build(root, name):
    experiment = root / EXPERIMENT
    artifacts = experiment / "artifacts"
    artifacts.mkdir(exist_ok=True)
    files = sorted(p for p in experiment.rglob("*") if p.is_file()
                   and "artifacts" not in p.relative_to(experiment).parts
                   and "__pycache__" not in p.parts
                   and p.suffix != ".pyc")
    archive = artifacts / (name + ".tar.gz")
    records = []
    with archive.open("xb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as tar:
                for path in files:
                    relative = path.relative_to(root).as_posix()
                    safe_path(relative)
                    if path.is_symlink():
                        raise ValueError("Symlinks are not supported: " + relative)
                    before = sha(path)
                    info = tar.gettarinfo(str(path), arcname=relative)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    info.mode = 0o644
                    with path.open("rb") as stream:
                        tar.addfile(info, stream)
                    if sha(path) != before:
                        raise ValueError("File changed during packaging: " + relative)
                    records.append(dict(path=relative, bytes=info.size, sha256=before))
    parts = []
    with archive.open("rb") as stream:
        index = 0
        while block := stream.read(PART_BYTES):
            part = Path(str(archive) + ".part%03d" % index)
            with part.open("xb") as output:
                output.write(block)
            parts.append(dict(path=part.relative_to(root).as_posix(), bytes=len(block),
                              sha256=hashlib.sha256(block).hexdigest()))
            index += 1
    manifest = dict(schema="hcsn.complete-evidence.v1", archive_sha256=sha(archive),
                    bytes=archive.stat().st_size, files=records, parts=parts,
                    scope="Complete additive experiment excluding recursive artifact bundles and bytecode; raw media is separately reproducible from pinned URLs and SHA256 receipts",
                    dependencies="Baseline source is inherited from commit 7226bd94c6f30d113b2abb8dcf3678e63eb81f38; see BASELINE_VERIFICATION.json")
    manifest_path = artifacts / (name.upper() + "_MANIFEST.json")
    with manifest_path.open("x") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return dict(manifest=str(manifest_path), files=len(records), parts=len(parts),
                bytes=manifest["bytes"], archive_sha256=manifest["archive_sha256"])


def verify_or_restore(root, manifest_path, destination):
    manifest = json.loads(manifest_path.read_text())
    expected = {row["path"]: row for row in manifest["files"]}
    if len(expected) != len(manifest["files"]):
        raise ValueError("Duplicate manifest member")
    for name in expected:
        safe_path(name)
    with tempfile.TemporaryDirectory(prefix="hcsn-evidence-") as temporary:
        archive = Path(temporary) / "evidence.tar.gz"
        with archive.open("wb") as target:
            for part in manifest["parts"]:
                safe_path(part["path"])
                path = root / part["path"]
                if path.stat().st_size != part["bytes"] or sha(path) != part["sha256"]:
                    raise ValueError("Part identity mismatch: " + part["path"])
                with path.open("rb") as stream:
                    shutil.copyfileobj(stream, target)
        if archive.stat().st_size != manifest["bytes"] or sha(archive) != manifest["archive_sha256"]:
            raise ValueError("Archive identity mismatch")
        seen = set()
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar:
                safe_path(member.name)
                if not member.isfile() or member.name in seen or member.name not in expected:
                    raise ValueError("Unexpected archive member: " + member.name)
                seen.add(member.name)
                record = expected[member.name]
                stream = tar.extractfile(member)
                payload = stream.read()
                if len(payload) != record["bytes"] or hashlib.sha256(payload).hexdigest() != record["sha256"]:
                    raise ValueError("Member identity mismatch: " + member.name)
                if destination is not None:
                    path = destination / member.name
                    if not path.resolve().is_relative_to(destination.resolve()):
                        raise ValueError("Destination path escape")
                    if path.exists():
                        if not path.is_file() or sha(path) != record["sha256"]:
                            raise ValueError("Refusing conflicting existing file: " + str(path))
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        with path.open("xb") as output:
                            output.write(payload)
        if seen != set(expected):
            raise ValueError("Missing archive members")
    return dict(verified=True, members=len(seen), parts=len(manifest["parts"]),
                archive_sha256=manifest["archive_sha256"], restored_to=str(destination) if destination else None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("build", "verify", "restore"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--name", default="complete_evidence")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.mode == "build":
        result = build(args.root.resolve(), args.name)
    else:
        if not args.manifest or (args.mode == "restore" and not args.destination):
            parser.error("verify requires --manifest; restore also requires --destination")
        result = verify_or_restore(args.root.resolve(), args.manifest,
                                   args.destination.resolve() if args.mode == "restore" else None)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
