"""Package selected evidence directories as deterministic, deduplicated objects."""
import argparse
import gzip
import hashlib
import io
import json
import os
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
    parser.add_argument("--include-file", nargs="*", default=[])
    parser.add_argument("--roundtrip", type=Path, required=True)
    parser.add_argument("--upload-list", type=Path, required=True)
    parser.add_argument("--rejected-fixture-links", type=Path)
    parser.add_argument("--delivery-component")
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    component = repo / relative(args.component)
    delivery = repo / relative(args.delivery_component) if args.delivery_component else component
    if args.delivery_component:
        if delivery == component or delivery.is_relative_to(component) or delivery.exists():
            raise ValueError("fresh separate delivery component required")
        delivery.mkdir(parents=True, exist_ok=False)
    if args.roundtrip.exists() or (delivery / "EVIDENCE_TRANSPORT.json").exists():
        raise ValueError("new roundtrip and transport destinations required")
    rows, objects, ignored, elf_aliases = [], {}, [], []
    rejected_links = {}
    if args.rejected_fixture_links:
        supplied = json.loads(args.rejected_fixture_links.read_text())["links"]
        if len(supplied) > 64:
            raise ValueError("rejected link fixture capacity")
        for row in supplied:
            name = relative(row["path"]).as_posix()
            if name in rejected_links or not isinstance(row["target"], str):
                raise ValueError("rejected link fixture metadata")
            rejected_links[name] = row["target"]
    prefixes = [relative(value) for value in args.include]
    selected = set()
    inputs = []
    for prefix in prefixes:
        folder = component / prefix
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("input must be a regular directory")
        inputs.extend(sorted(folder.rglob("*")))
    inputs.extend(component / relative(value) for value in args.include_file)
    for path in inputs:
        if path.is_symlink():
            name = path.relative_to(component).as_posix()
            if rejected_links.get(name) != os.readlink(path):
                raise ValueError("undeclared or changed symlink input")
            continue
        if not path.is_file():
            continue
        name = path.relative_to(component).as_posix()
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            ignored.append(name)
            continue
        data = path.read_bytes()
        if data.startswith(b"\x7fELF") or (path.suffix.lower() == ".exe" and data.startswith(b"MZ")):
            elf_aliases.append(name)
            continue
        if name in selected:
            raise ValueError("overlapping selected inputs")
        selected.add(name)
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode not in (0o600, 0o644, 0o700, 0o755):
            raise ValueError("unsupported input permissions")
        sha = digest(data)
        objects[sha] = data
        rows.append(dict(path=name, size=len(data), sha256=sha, mode=mode))
    if len(rows) > 65536 or sum(row["size"] for row in rows) > 512 * 1024**2:
        raise ValueError("logical restore capacity")
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
    def write_parts(data, folder):
        target = delivery / folder
        target.mkdir(exist_ok=False)
        parts = []
        for index, offset in enumerate(range(0, len(data), 450000)):
            content = data[offset:offset+450000]
            name = f"{folder}/{index:04}.part"
            (delivery / name).write_bytes(content)
            parts.append(dict(path=name, size=len(content), sha256=digest(content)))
        return parts
    parts = write_parts(compressed, "transport")
    map_raw = json.dumps(dict(files=sorted(rows, key=lambda row:row["path"]),
                              excluded_transients=ignored, excluded_native_elf_aliases=elf_aliases,
                              rejected_fixture_links_as_metadata=rejected_links),
                         separators=(",", ":")).encode()
    map_buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=map_buffer, filename="", mode="wb", mtime=0, compresslevel=9) as output:
        output.write(map_raw)
    map_gzip = map_buffer.getvalue()
    map_parts = write_parts(map_gzip, "map_transport")
    manifest = dict(schema="hcsn-evidence-transport-v2", component=args.component,
                    delivery_component=args.delivery_component,
                    included_directories=args.include, included_files=args.include_file,
                    file_count_cap=65536, logical_bytes_cap=512*1024**2,
                    archive=dict(gzip_bytes=len(compressed), gzip_sha256=digest(compressed),
                                 raw_bytes=len(raw_tar), raw_sha256=digest(raw_tar), parts=parts),
                    file_map=dict(gzip_bytes=len(map_gzip), gzip_sha256=digest(map_gzip),
                                  raw_bytes=len(map_raw), raw_sha256=digest(map_raw), parts=map_parts))
    (delivery / "EVIDENCE_TRANSPORT.json").write_text(json.dumps(manifest, indent=2)+"\n")
    shutil.copyfile(Path(__file__).with_name("restore_evidence.py"), delivery / "restore_evidence.py")
    command = [sys.executable, str(delivery / "restore_evidence.py"), "--destination", str(args.roundtrip)]
    restored = subprocess.run(command, capture_output=True, check=True)
    for row in rows:
        source, target = component / relative(row["path"]), args.roundtrip / relative(row["path"])
        if source.read_bytes() != target.read_bytes():
            raise ValueError("roundtrip mismatch")
    receipt = dict(passed=True, files=len(rows), unique_objects=len(objects), command=command,
                   archive_sha256=digest(compressed), stdout=restored.stdout.decode(), stderr=restored.stderr.decode(),
                   originals_unchanged=True)
    (delivery / "TRANSPORT_ROUNDTRIP.json").write_text(json.dumps(receipt, indent=2)+"\n")
    doc = f"# Exact evidence restoration\n\nBefore running existing audits, restore the bundled `{', '.join(args.include)}` trees from the component directory:\n\n```sh\npython {args.component}/restore_evidence.py\n```\n\nRun that command from the repository root. Parts, compressed archive, every tar object and every restored file are checked by size and SHA256. The restorer rejects path traversal, linked members, symlink paths and any existing file with different bytes. Identical files are retained, so the command is idempotent. Original artifact manifests become directly checkable after restoration. The archive stores one `objects/<sha256>` payload per distinct byte string; duplicate evidence paths are restored separately. The separately compressed file map is verified before bounded object extraction; file count is capped at 65,536 and restored bytes at 512 MiB. Actual native ELF aliases, when present, are restored separately using the component exact-binary instructions. No scientific source, original report, original manifest or original evidence bytes were modified. Packaging is a transport operation and supplies no new scientific or cost claim.\n"
    if args.delivery_component:
        doc = doc.replace(f"python {args.component}/restore_evidence.py", f"python {args.delivery_component}/restore_evidence.py --destination {args.component}")
        doc += "\nThe carrier is separate from the scientific component and supplies no additional scientific samples or adoption claim. Restore explicitly into the original component path shown above.\n"
    (delivery / "TRANSPORT.md").write_text(doc)
    upload = []
    for path in sorted(component.rglob("*")):
        if path.is_symlink():
            name = path.relative_to(component).as_posix()
            if rejected_links.get(name) != os.readlink(path):
                raise ValueError("undeclared or changed upload symlink")
            continue
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        name = path.relative_to(component).as_posix()
        if name in selected or any(relative(name).is_relative_to(prefix) for prefix in prefixes):
            continue
        if path.stat().st_size > 512000:
            raise ValueError(f"oversized top-level upload {name}")
        upload.append(path.relative_to(repo).as_posix())
    if delivery != component:
        for path in sorted(delivery.rglob("*")):
            if path.is_symlink():
                raise ValueError("symlink delivery output")
            if path.is_file():
                if path.stat().st_size > 512000:
                    raise ValueError("oversized delivery output")
                upload.append(path.relative_to(repo).as_posix())
    args.upload_list.write_text(json.dumps(dict(component=args.component, upload_files=upload,
                                               bundled_files=len(rows), unique_objects=len(objects), parts=len(parts)+len(map_parts)), indent=2)+"\n")
    print(json.dumps(dict(component=args.component, bundled_files=len(rows), unique_objects=len(objects),
                          compressed_bytes=len(compressed), map_raw_bytes=len(map_raw), map_gzip_bytes=len(map_gzip), parts=len(parts)+len(map_parts), upload_files=len(upload)), sort_keys=True))


if __name__ == "__main__":
    main()
