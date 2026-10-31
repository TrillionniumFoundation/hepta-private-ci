"""Build a deterministic, explicitly enumerated V3 local evidence archive.

The separate archive_integrity verifier must validate the finished archive.
No network, scientific execution, directory discovery or implicit inclusion.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import time

from archive_integrity import publish_no_replace, validate_manifest


ROOTS = {"run", "repository", "freezes", "native", "assets"}


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def header(name, size):
    item = tarfile.TarInfo(name)
    item.size, item.mode, item.mtime = size, 0o644, 0
    item.uid, item.gid, item.uname, item.gname = 0, 0, "", ""
    item.type = tarfile.REGTYPE
    item.tobuf(format=tarfile.USTAR_FORMAT)
    return item


class CheckedReader:
    def __init__(self, stream):
        self.stream, self.hasher, self.count = stream, hashlib.sha256(), 0

    def read(self, size):
        data = self.stream.read(size)
        self.hasher.update(data)
        self.count += len(data)
        return data


def build(index_path, output, receipt):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    index_path, output, receipt = map(lambda p: Path(p).resolve(), (index_path, output, receipt))
    partial = output.with_name(output.name + ".partial")
    require(not output.exists() and not partial.exists() and not receipt.exists(), "Refusing to overwrite an archive attempt")
    index = json.loads(index_path.read_text())
    require(index["schema"] == "hepta.field-bridge.v3.archive-input-index.1", "Unknown explicit input index")
    rows, sources, names = [], {}, set()
    for entry in sorted(index["entries"], key=lambda row: row["path"]):
        require(set(entry) == {"source", "path"}, "Unknown input entry field")
        name, source = entry["path"], Path(entry["source"]).resolve()
        path = PurePosixPath(name)
        require(not path.is_absolute() and path.parts and path.parts[0] in ROOTS
                and all(part not in ("", ".", "..") for part in path.parts)
                and str(path) == name and "\\" not in name and "\x00" not in name,
                "Unsafe archive payload name")
        require(name.casefold() not in names, "Duplicate or case-colliding archive name")
        require(Path(entry["source"]).is_absolute() and not Path(entry["source"]).is_symlink()
                and source.is_file(), "Every explicitly selected source must be a regular file")
        require(source not in (output, partial, receipt), "Archive outputs cannot be payload inputs")
        names.add(name.casefold())
        row = {"path": name, "bytes": source.stat().st_size, "sha256": digest(source)}
        header(name, row["bytes"])
        rows.append(row)
        sources[name] = source
    require(rows, "Empty evidence payload")
    by_name = {row["path"]: row for row in rows}
    provenance = index["provenance"]
    expected = [provenance["protocol"], *({"path": name, "sha256": value}
                for key in ("source_files", "receipts") for name, value in provenance[key].items())]
    require(all(row["path"] in by_name and by_name[row["path"]]["sha256"] == row["sha256"]
                for row in expected), "A provenance identity does not match its actual payload")
    manifest = {"schema": "hepta.field-bridge.v3.evidence-archive-manifest.1",
                "provenance": provenance, "members": rows}
    validate_manifest(manifest)
    data = (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
                archive.addfile(header("MANIFEST.json", len(data)), io.BytesIO(data))
                for position, row in enumerate(rows, 1):
                    source = sources[row["path"]]
                    require(source.stat().st_size == row["bytes"], "An input size changed before archiving")
                    with source.open("rb") as stream:
                        checked = CheckedReader(stream)
                        archive.addfile(header(row["path"], row["bytes"]), checked)
                        require(checked.count == row["bytes"] and checked.hasher.hexdigest() == row["sha256"]
                                and not stream.read(1), "An input changed while archiving")
                    if position % 200 == 0:
                        print(json.dumps({"archived_files": position, "total_files": len(rows)}), flush=True)
    output_hash = digest(partial)
    publish_no_replace(partial, output)
    result = {"schema": "hepta.field-bridge.v3.archive-build.1", "built": True,
        "independent_integrity_verification_still_required": True,
        "archive": str(output), "archive_bytes": output.stat().st_size, "archive_sha256": output_hash,
        "manifest_sha256": hashlib.sha256(data).hexdigest(), "manifest_bytes": len(data),
        "payload_files": len(rows), "regular_members_including_manifest": len(rows) + 1,
        "payload_bytes": sum(row["bytes"] for row in rows), "input_index_sha256": digest(index_path),
        "builder_sha256": digest(__file__), "compression": "gzip level6, mtime0; USTAR regular files only",
        "provenance": provenance, "network_requests": 0, "generator_or_observer_calls": 0,
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu}
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("archive", "archive_bytes", "archive_sha256",
                     "manifest_sha256", "payload_files", "payload_bytes")}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    build(args.index, args.output, args.receipt)
