"""Preserve complete native development evidence with an explicit publication allowlist."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def package():
    items = []
    for folder in ("qualification", "qualification_dev03", "attempts"):
        for path in (HERE/folder).rglob("*"):
            if (path.is_file() and "__pycache__" not in path.parts
                    and not (path.name.startswith("native-stderr-") and path.stat().st_size == 0)):
                items.append(path)
    for pattern in ("BUILD*.json", "FORMAT*.json", "*.rs", "*.py", "*.toml", "*.lock", "README.md", "SOURCE_IDENTITY.json"):
        items.extend(HERE.glob(pattern))
    items = sorted(set(items))
    rows = [dict(path=str(path.relative_to(HERE)), bytes=path.stat().st_size,
                 sha256=sha(path.read_bytes())) for path in items]
    manifest = json.dumps(dict(schema="hepta.task.native-evidence.content.v1", files=rows),
                          sort_keys=True, separators=(",", ":")).encode()+b"\n"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path, row in zip(items, rows):
            raw = path.read_bytes()
            info = tarfile.TarInfo(row["path"])
            info.size, info.mode, info.mtime = len(raw), 0o644, 0
            archive.addfile(info, io.BytesIO(raw))
        info = tarfile.TarInfo("CONTENTS.json")
        info.size, info.mode, info.mtime = len(manifest), 0o644, 0
        archive.addfile(info, io.BytesIO(manifest))
    path = HERE/"native-development-evidence.tar.gz"
    with path.open("xb") as stream:
        stream.write(gzip.compress(buffer.getvalue(), mtime=0))
    summary = dict(schema="hepta.task.native-evidence.archive.v1", archive=path.name,
        sha256=sha(path.read_bytes()), bytes=path.stat().st_size, file_count=len(rows),
        uncompressed_file_bytes=sum(row["bytes"] for row in rows), contents_manifest_sha256=sha(manifest),
        omitted="Only empty native-stderr files and Python bytecode; every journal/witness, nonempty stderr, packet, receipt, model, failed attempt and source retained",
        native_physics_executed=False, production_activation=False)
    save(HERE/"EVIDENCE_ARCHIVE.json", summary)
    public = []
    for pattern in ("*.rs", "*.py", "*.toml", "*.lock", "README.md", "SOURCE_IDENTITY.json",
                    "BUILD_Q24_PROFILE.json", "FORMAT_Q24_PROFILE.json", "EVIDENCE_ARCHIVE.json",
                    "native-development-evidence.tar.gz"):
        public.extend(HERE.glob(pattern))
    public.extend(HERE/path for path in ("qualification_dev03/selected_checkpoint.json",
        "qualification_dev03/calibration.json", "qualification_dev03/result/REPORT.json",
        "qualification_dev03/profile_result/REPORT.json", "qualification_dev03/task_parity_cached/REPORT.json"))
    listing = dict(schema="hepta.task.native-publication.v1",
        scope="Recommended repository source/report files plus one raw-evidence archive. No publication performed by this lane.",
        files=[dict(path=str(path.relative_to(HERE)), bytes=path.stat().st_size,
                    sha256=sha(path.read_bytes()), binary=path.suffix == ".gz") for path in sorted(set(public))],
        source_ready=True, compiled_source_digest="52df63ce0650c0e806e890b69c88b9202244422a1d1b7304a7af571ab5a1b2b5",
        native_physics_executed=False, production_activation=False)
    save(HERE/"PUBLICATION_MANIFEST.json", listing)
    print(json.dumps(dict(archive=summary, public_files=len(listing["files"]),
        public_text_bytes=sum(row["bytes"] for row in listing["files"] if not row["binary"])), indent=2))


if __name__ == "__main__":
    package()
