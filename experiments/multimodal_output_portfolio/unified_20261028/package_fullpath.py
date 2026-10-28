"""Package pinned full-path artifacts and verify every archived member byte."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build(root, baseline, output):
    root, baseline, output = map(Path, (root, baseline, output))
    if output.exists():
        raise FileExistsError("Preserve existing archives")
    if checksum(baseline) != "508931a0cb780d413bc39de83b8de91aeab68b33cfe1b384f176cb8e8f004ee6":
        raise ValueError("Original strong checkpoint changed")
    entries = []
    for name in ("fullpath-development-003", "fullpath-qualification-001"):
        for path in sorted((root / name).rglob("*")):
            if path.is_file() and not path.is_symlink():
                entries.append((path, str(path.relative_to(root))))
    assets = root / "assets/historical"
    for path in sorted((assets / "ndu-data").glob("*.gz")):
        entries.append((path, "assets/" + str(path.relative_to(assets))))
    for name in ("protocol.json", "reward-observer.pt", "audit-observer.pt"):
        path = assets / "ndu-runs/full-002" / name
        entries.append((path, "assets/" + str(path.relative_to(assets))))
    entries.append((baseline, "assets/strong-baseline.pt"))
    entries.append((root / "FULLPATH_ARCHIVE_README.json", "FULLPATH_ARCHIVE_README.json"))
    source = Path(__file__).resolve().parent
    experiment = source.parent
    for directory in (source, experiment / "v6", experiment / "continuation_20261027/joint",
                      experiment / "repair_20261026/joint"):
        for path in sorted(directory.glob("*.py")):
            entries.append((path, "source/experiments/multimodal_output_portfolio/" + str(path.relative_to(experiment))))
    for name in ("allocate_admission_sources.py", "SOURCE_ALLOCATION.json", "CONTROL_ADMISSION_SOURCE_ALLOCATION.json"):
        path = experiment / "closure_v2_20261027" / name
        entries.append((path, "source/experiments/multimodal_output_portfolio/" + str(path.relative_to(experiment))))
    for path in sorted((source / "results").glob("FULLPATH*.json")):
        entries.append((path, "independent-results/" + path.name))
    rows = [{"path": name, "bytes": path.stat().st_size, "sha256": checksum(path)} for path, name in entries]
    if len({row["path"] for row in rows}) != len(rows):
        raise ValueError("Duplicate archive member")
    manifest = {"schema": "hepta.ndu.fullpath-archive.v1", "files": rows,
                "raw_qualification_media_preserved": True,
                "compressed_json_restores_exact_bytes": True,
                "native_and_natural_studies_saved_separately": True}
    payload = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    with tarfile.open(output, "w:gz", compresslevel=6) as archive:
        item = tarfile.TarInfo("MANIFEST.json")
        item.size = len(payload)
        archive.addfile(item, io.BytesIO(payload))
        for path, name in entries:
            item = tarfile.TarInfo(name)
            item.size = path.stat().st_size
            item.mode = 0o644
            with path.open("rb") as stream:
                archive.addfile(item, stream)
    expected = {row["path"]: row for row in rows}
    verified = 0
    with tarfile.open(output, "r:gz") as archive:
        for item in archive:
            data = archive.extractfile(item).read()
            if item.name == "MANIFEST.json":
                if data != payload:
                    raise ValueError("Archive manifest changed")
                continue
            row = expected.pop(item.name)
            if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Archived member differs from pinned evidence")
            verified += 1
    if expected:
        raise ValueError("Archive lost members")
    return {"archive": output.name, "bytes": output.stat().st_size,
            "sha256": checksum(output), "verified_members": verified,
            "verification": "all tar member bytes re-read and checked against source SHA256",
            "manifest_sha256": hashlib.sha256(payload).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("root", "baseline", "output", "receipt"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = build(args.root, args.baseline, args.output)
    args.receipt.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result))
