"""Archive immutable fullpath evidence in bounded, independently verified parts.

No model execution. A part is produced only when its predecessor has a durable
receipt and its local archive has been removed. Raw evidence is never deleted.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


PAYLOAD_LIMIT = 45_000_000
ARCHIVE_LIMIT = 60_000_000
EXCLUDED = {"PHASE_INDEX.json", "PHASE_RECEIPT.json"}


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def plan(package, runs, staging):
    files = []
    sources = [(p, "sources/" + p.name) for p in sorted(package.glob("fullpath_*.py"))]
    sources += [(p, "sources/" + p.name) for p in sorted(package.glob("fullpath_*.md"))]
    sources += [(p, "results/" + p.name) for p in sorted((package / "fullpath_results").glob("*.json")) if p.name not in EXCLUDED]
    for run in runs:
        sources += [(p, "runs/" + run.name + "/" + str(p.relative_to(run))) for p in sorted(run.rglob("*")) if p.is_file()]
    for source, member in sources:
        if source.is_symlink():
            raise ValueError("symlink evidence is not accepted: " + str(source))
        size = source.stat().st_size
        if size > PAYLOAD_LIMIT:
            raise ValueError("one evidence file exceeds the part budget")
        files.append({"source": str(source), "member": member, "bytes": size, "sha256": sha(source)})
    if len({x["member"] for x in files}) != len(files):
        raise ValueError("duplicate archive member")
    parts, current, size = [], [], 0
    for item in files:
        if current and size + item["bytes"] > PAYLOAD_LIMIT:
            parts.append(current)
            current, size = [], 0
        current.append(item)
        size += item["bytes"]
    if current:
        parts.append(current)
    return {"schema": "hepta.ndu.fullpath.evidence-parts.v1", "study_status": "development gate failed; no qualification predictions",
            "payload_limit_bytes": PAYLOAD_LIMIT, "archive_limit_bytes": ARCHIVE_LIMIT,
            "staging_directory": str(staging), "raw_files_will_not_be_deleted": True,
            "file_count": len(files), "payload_bytes": sum(x["bytes"] for x in files),
            "parts": [{"part": i + 1, "archive": f"closure-fullpath-lax-phase-001-part-{i + 1:02d}.tar.gz", "files": rows, "payload_bytes": sum(x["bytes"] for x in rows)} for i, rows in enumerate(parts)]}


def build(index, number, receipt):
    entry = index["parts"][number - 1]
    staging = Path(index["staging_directory"])
    staging.mkdir(parents=True, exist_ok=True)
    if list(staging.glob("*.tar.gz")):
        raise ValueError("persist and remove the preceding local part before producing another")
    if number > 1 and not receipt["parts"].get(str(number - 1), {}).get("durable_copy"):
        raise ValueError("preceding part needs a durable-copy receipt")
    if str(number) in receipt["parts"]:
        raise ValueError("part already has a verified receipt")
    destination = staging / entry["archive"]
    manifest = json.dumps(entry, sort_keys=True, indent=2).encode() + b"\n"
    with destination.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|") as archive:
                info = tarfile.TarInfo("INDEX_PART.json")
                info.size, info.mtime, info.mode = len(manifest), 0, 0o644
                archive.addfile(info, io.BytesIO(manifest))
                for row in entry["files"]:
                    content = Path(row["source"]).read_bytes()
                    if len(content) != row["bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
                        raise ValueError("source changed after freezing archive index: " + row["source"])
                    info = tarfile.TarInfo(row["member"])
                    info.size, info.mtime, info.mode = len(content), 0, 0o644
                    archive.addfile(info, io.BytesIO(content))
    if destination.stat().st_size > ARCHIVE_LIMIT:
        raise ValueError("archive exceeds requested size bound")
    with tarfile.open(destination, "r:gz") as archive:
        expected = {x["member"]: x for x in entry["files"]}
        observed = archive.getnames()
        if len(observed) != len(expected) + 1 or set(observed) != {"INDEX_PART.json", *expected}:
            raise ValueError("archive member set mismatch")
        if archive.extractfile("INDEX_PART.json").read() != manifest:
            raise ValueError("embedded manifest mismatch")
        for name, row in expected.items():
            content = archive.extractfile(name).read()
            if len(content) != row["bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
                raise ValueError("archive payload verification failed: " + name)
    return {"path": str(destination), "archive_bytes": destination.stat().st_size,
            "archive_sha256": sha(destination), "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "payload_bytes": entry["payload_bytes"], "verified_payload_files": len(entry["files"]),
            "all_member_hashes_verified": True, "durable_copy": None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--part", type=int, required=True)
    args = parser.parse_args()
    result = args.package / "fullpath_results"
    index_path, receipt_path = result / "PHASE_INDEX.json", result / "PHASE_RECEIPT.json"
    if index_path.exists():
        index = json.loads(index_path.read_text())
        if index["staging_directory"] != str(args.staging):
            raise ValueError("staging directory differs from frozen index")
    else:
        index = plan(args.package, args.runs, args.staging)
        save(index_path, index)
    if not 1 <= args.part <= len(index["parts"]):
        raise ValueError("part outside frozen index")
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {
        "schema": "hepta.ndu.fullpath.evidence-parts-receipt.v1", "index_sha256": sha(index_path), "parts": {}}
    if receipt["index_sha256"] != sha(index_path):
        raise ValueError("archive index changed")
    entry = build(index, args.part, receipt)
    receipt["parts"][str(args.part)] = entry
    receipt["all_parts_verified"] = len(receipt["parts"]) == len(index["parts"])
    receipt["all_parts_durable"] = all(receipt["parts"].get(str(i + 1), {}).get("durable_copy") for i in range(len(index["parts"])))
    save(receipt_path, receipt)
    print(json.dumps({"part": args.part, "total_parts": len(index["parts"]), "index_sha256": receipt["index_sha256"], **entry}, indent=2), flush=True)


if __name__ == "__main__":
    main()
