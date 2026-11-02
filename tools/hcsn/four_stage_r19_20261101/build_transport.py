"""Package selected evidence directories as deterministic, deduplicated objects."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile

from restore_evidence import relative


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--component", required=True)
    parser.add_argument("--include", nargs="+", required=True)
    parser.add_argument("--roundtrip", type=Path, required=True)
    parser.add_argument("--upload-list", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    component = repo / relative(args.component)
    if args.roundtrip.exists() or (component / "EVIDENCE_TRANSPORT.json").exists():
        raise ValueError("new roundtrip and transport destinations required")
    rows, objects, ignored = [], {}, []
    prefixes = [relative(value) for value in args.include]
    selected = set()
    for prefix in prefixes:
        folder = component / prefix
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("input must be a regular directory")
        for path in sorted(folder.rglob("*")):
            if path.is_symlink():
                raise ValueError("symlink input")
            if not path.is_file():
                continue
            name = path.relative_to(component).as_posix()
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                ignored.append(name)
                continue
            data = path.read_bytes()
            if data.startswith(b"\x7fELF") or (path.suffix.lower() == ".exe" and data.startswith(b"MZ")):
                ignored.append(name)
                continue
            if name in selected:
                raise ValueError("overlapping selected directories")
            selected.add(name)
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode not in (0o600, 0o644, 0o700, 0o755):
                raise ValueError("unsupported input permissions")
            sha = digest(data)
            objects[sha] = data
            rows.append(dict(path=name, size=len(data), sha256=sha, mode=mode))
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for sha, data in sorted(objects.items()):
            member = tarfile.TarInfo("objects/" + sha)
            member.size, member.mode, member.mtime = len(data), 0o644, 0
            member.uid = member.gid = 0
            member.uname = member.gname = ""
            tar.addfile(member, io.BytesIO(data))
    raw_tar = buffer.getvalue()
    zipped = io.BytesIO()
    with gzip.GzipFile(fileobj=zipped, filename="", mode="wb", mtime=0, compresslevel=9) as output:
        output.write(raw_tar)
    compressed = zipped.getvalue()
    transport = component / "transport"
    transport.mkdir(exist_ok=False)
    parts = []
    for index, offset in enumerate(range(0, len(compressed), 450000)):
        data = compressed[offset:offset + 450000]
        name = f"transport/{index:04}.part"
        (component / name).write_bytes(data)
        parts.append(dict(path=name, size=len(data), sha256=digest(data)))
    manifest = dict(schema="hcsn-evidence-transport-v1", component=args.component,
                    included_directories=args.include, excluded_transients=ignored,
                    archive=dict(gzip_bytes=len(compressed), gzip_sha256=digest(compressed),
                                 tar_bytes=len(raw_tar), tar_sha256=digest(raw_tar)),
                    parts=parts, files=sorted(rows, key=lambda row:row["path"]))
    (component / "EVIDENCE_TRANSPORT.json").write_text(json.dumps(manifest, indent=2)+"\n")
    shutil.copyfile(Path(__file__).with_name("restore_evidence.py"), component / "restore_evidence.py")
    command = [sys.executable, str(component / "restore_evidence.py"), "--destination", str(args.roundtrip)]
    restored = subprocess.run(command, capture_output=True, check=True)
    for row in rows:
        source, target = component / relative(row["path"]), args.roundtrip / relative(row["path"])
        if source.read_bytes() != target.read_bytes():
            raise ValueError("roundtrip mismatch")
    receipt = dict(passed=True, files=len(rows), unique_objects=len(objects), command=command,
                   archive_sha256=digest(compressed), stdout=restored.stdout.decode(), stderr=restored.stderr.decode(),
                   originals_unchanged=True)
    (component / "TRANSPORT_ROUNDTRIP.json").write_text(json.dumps(receipt, indent=2)+"\n")
    doc = f"# Exact evidence restoration\n\nBefore running existing audits, restore the bundled `{', '.join(args.include)}` trees from the component directory:\n\n```sh\npython {args.component}/restore_evidence.py\n```\n\nRun that command from the repository root. Parts, compressed archive, every tar object and every restored file are checked by size and SHA256. The restorer rejects path traversal, linked members, symlink paths and any existing file with different bytes. Identical files are retained, so the command is idempotent. Original artifact manifests become directly checkable after restoration. The archive stores one `objects/<sha256>` payload per distinct byte string; duplicate evidence paths are restored separately. No scientific source, original report, original manifest or original evidence bytes were modified. Packaging is a transport operation and supplies no new scientific or cost claim.\n"
    (component / "TRANSPORT.md").write_text(doc)
    upload = []
    for path in sorted(component.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        name = path.relative_to(component).as_posix()
        if name in selected or any(relative(name).is_relative_to(prefix) for prefix in prefixes):
            continue
        if path.stat().st_size > 512000:
            raise ValueError(f"oversized top-level upload {name}")
        upload.append(path.relative_to(repo).as_posix())
    args.upload_list.write_text(json.dumps(dict(component=args.component, upload_files=upload,
                                               bundled_files=len(rows), unique_objects=len(objects), parts=len(parts)), indent=2)+"\n")
    print(json.dumps(dict(component=args.component, bundled_files=len(rows), unique_objects=len(objects),
                          compressed_bytes=len(compressed), parts=len(parts), upload_files=len(upload)), sort_keys=True))


if __name__ == "__main__":
    main()
