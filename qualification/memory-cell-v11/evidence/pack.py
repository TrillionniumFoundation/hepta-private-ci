"""Create deterministic evidence archives or wrap existing immutable tar.xz bytes."""

import argparse
import base64
import hashlib
import json
import lzma
from pathlib import Path
import shutil
import tarfile
import tempfile

from restore import CHUNK_BYTES, SCHEMA, canonical_json, inspect_archive, relative_name, sha256_file


def directory_archive(source, destination):
    """Normalize outer tar metadata; scientific file contents remain unchanged."""
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("source must be a real evidence directory")
    source = source.resolve()
    destination = destination.resolve()
    if destination.is_relative_to(source) or destination.exists() or destination.is_symlink():
        raise ValueError("archive must be a new file outside the source directory")
    entries = sorted(source.rglob("*"), key=lambda p: p.relative_to(source).as_posix())
    for entry in entries:
        if entry.is_symlink() or not (entry.is_file() or entry.is_dir()):
            raise ValueError("evidence contains a symlink or special file")
        relative_name(entry.relative_to(source).as_posix())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as raw:
        with lzma.LZMAFile(raw, "w", format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC64, preset=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for entry in entries:
                    name = entry.relative_to(source).as_posix()
                    info = tarfile.TarInfo(name)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    if entry.is_dir():
                        info.type, info.mode, info.size = tarfile.DIRTYPE, 0o755, 0
                        archive.addfile(info)
                    else:
                        info.type, info.mode, info.size = tarfile.REGTYPE, 0o644, entry.stat().st_size
                        with entry.open("rb") as stream:
                            archive.addfile(info, stream)
    inventory = inspect_archive(destination)
    for member in inventory["members"]:
        if member["type"] == "file":
            original = source.joinpath(*member["path"].split("/"))
            if original.stat().st_size != member["bytes"] or sha256_file(original) != member["sha256"]:
                raise ValueError("source changed during archival; do not publish this archive")
    return inventory


def package_archive(archive, output, *, metadata_mode="preserved original archive", source_manifests=()):
    archive, output = Path(archive), Path(output).absolute()
    if archive.is_symlink() or not archive.is_file() or output.exists() or output.is_symlink():
        raise ValueError("archive must exist and package output must be new")
    archive = archive.resolve()
    if archive.is_relative_to(output):
        raise ValueError("archive cannot be inside its package")
    inventory = inspect_archive(archive)
    archive_identity = dict(name=archive.name, bytes=archive.stat().st_size, sha256=sha256_file(archive),
                            compression="xz", metadata_mode=metadata_mode)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".evidence-pack-", dir=output.parent) as temporary:
        staging = Path(temporary) / "package"
        staging.mkdir()
        inventory_bytes = canonical_json(inventory)
        (staging / "INVENTORY.json").write_bytes(inventory_bytes)
        parts = []
        actual_digest = hashlib.sha256()
        with archive.open("rb") as stream:
            for index, block in enumerate(iter(lambda: stream.read(CHUNK_BYTES), b"")):
                name = f"part-{index:05d}.b64"
                text = base64.b64encode(block) + b"\n"
                (staging / name).write_bytes(text)
                actual_digest.update(block)
                parts.append(dict(path=name, binary_bytes=len(block), binary_sha256=hashlib.sha256(block).hexdigest(),
                                  text_bytes=len(text), text_sha256=hashlib.sha256(text).hexdigest()))
        if actual_digest.hexdigest() != archive_identity["sha256"]:
            raise ValueError("archive changed while packaging")
        attached = []
        for source in source_manifests:
            source = Path(source)
            name = relative_name(source.name)
            destination = staging / "source-manifests" / name
            destination.parent.mkdir(exist_ok=True)
            if destination.exists() or source.is_symlink() or not source.is_file():
                raise ValueError("duplicate or invalid source manifest")
            shutil.copyfile(source, destination)
            attached.append(dict(path=destination.relative_to(staging).as_posix(), bytes=destination.stat().st_size,
                                 sha256=sha256_file(destination)))
        manifest = dict(schema=SCHEMA, archive=archive_identity, chunk_bytes=CHUNK_BYTES, parts=parts,
                        inventory=dict(path="INVENTORY.json", bytes=len(inventory_bytes),
                                       sha256=hashlib.sha256(inventory_bytes).hexdigest()),
                        source_manifests=attached, includes_all_declared_archive_members=True,
                        external_assets="No external pretrained assets are fetched or followed; only declared archive members are packaged.",
                        tool_sha256={name: sha256_file(Path(__file__).with_name(name)) for name in ("pack.py", "restore.py")})
        (staging / "MANIFEST.json").write_bytes(canonical_json(manifest))
        (staging / "ARCHIVE.sha256").write_text(f"{archive_identity['sha256']}  {archive.name}\n")
        readme = f"""# {output.name} immutable evidence package

This directory contains the complete original archive as base64 text parts.
Each full part decodes to {CHUNK_BYTES} bytes (128 KiB); its text is 174,765 bytes.
The original tar.xz is **not** duplicated in Git. Optimizer states, SQLite files,
checkpoints, source snapshots, and all failed or negative results present in the
declared archive are retained. No external pretrained model is fetched, and
directory packaging refuses symlinks and special files.

- Archive: `{archive.name}`
- Archive bytes: {archive_identity['bytes']}
- Archive SHA-256: `{archive_identity['sha256']}`
- Files: {inventory['file_count']}; total file bytes: {inventory['total_file_bytes']}
- Parts: {len(parts)}; tar metadata: {metadata_mode}

From `qualification/memory-cell-v11/evidence`:

```bash
python restore.py --package archives/{output.name} --verify-only
python restore.py --package archives/{output.name} --output restored/{output.name}
```

The output directory must not exist. Add `--archive-output path/to/{archive.name}`
to retain the reconstructed tar.xz as well. Restore verifies every text part,
decoded part, whole archive, member file byte count and SHA-256 before publishing
the restored directory. It rejects absolute paths, traversal, duplicate paths,
symlinks, hardlinks, devices, and file/directory conflicts. It never uses
`tar.extractall`. The default uncompressed bound is 512 MiB.

`INVENTORY.json` is the complete member inventory. `SHA256SUMS` checks all uploaded
text files except itself; `ARCHIVE.sha256` applies to the reconstructed archive.
Original manifests inside the tar are preserved byte-for-byte. Any explicitly
supplied side manifests are copied into `source-manifests/` without modification.
The checksums establish integrity relative to this package; the Git commit or an
independently retained archive SHA is the identity anchor.

For directory inputs, file order is lexical and tar uid/gid/mtime are zero,
user/group names empty, and modes 0644/0755. Repacking unchanged files with these
scripts produces identical tar.xz bytes. Existing tar.xz inputs are never
recompressed or rewritten.
"""
        (staging / "README.md").write_text(readme)
        checksums = [f"{sha256_file(p)}  {p.relative_to(staging).as_posix()}\n"
                     for p in sorted(staging.rglob("*")) if p.is_file()]
        (staging / "SHA256SUMS").write_text("".join(checksums))
        staging.rename(output)
    return dict(package=str(output), archive=archive_identity, parts=len(parts),
                files=inventory["file_count"], file_bytes=inventory["total_file_bytes"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--source", type=Path)
    inputs.add_argument("--archive", type=Path)
    parser.add_argument("--archive-out", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, action="append", default=[])
    arguments = parser.parse_args()
    if arguments.source:
        if arguments.archive_out is None:
            parser.error("--source requires --archive-out outside the source directory")
        if arguments.output.resolve().is_relative_to(arguments.source.resolve()):
            parser.error("package output cannot be inside the evidence source")
        directory_archive(arguments.source, arguments.archive_out)
        archive, mode = arguments.archive_out, "lexical order; uid=gid=mtime=0; modes=0644/0755"
    else:
        if arguments.archive_out is not None:
            parser.error("--archive-out is only for directory input")
        archive, mode = arguments.archive, "preserved original archive"
    print(json.dumps(package_archive(archive, arguments.output, metadata_mode=mode,
                                    source_manifests=arguments.source_manifest), sort_keys=True))
