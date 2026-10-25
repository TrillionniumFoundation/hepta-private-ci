"""Bounded prior-evidence inventory, including directly scanned archive metadata."""

from collections import defaultdict
import hashlib
import os
from pathlib import Path, PurePosixPath
import tarfile
import zipfile

from .io import identity


SKIP = {".git", ".venv", "venv", "target", "node_modules", "__pycache__"}
TEXT_TYPES = {".json", ".jsonl", ".txt", ".log", ".md", ".csv", ".tsv", ".py", ".rs", ".sh", ".toml", ".yaml", ".yml"}
ARCHIVE_ENDINGS = (".tar.gz", ".tar.xz", ".tgz", ".zip", ".tar", ".tar.bz2", ".tbz2", ".tar.zst", ".7z", ".rar")
MAX_FILE = 256 << 20
MAX_EXPANDED = 2 << 30


def inventory(roots):
    files, archives, opaque, excluded = set(), set(), set(), {}

    def walk_error(error):
        raise error

    for base in roots:
        if Path(base).is_symlink() or not Path(base).is_dir():
            raise ValueError("old evidence root is missing or a symlink")
        for directory, names, leaves in os.walk(base, followlinks=False, onerror=walk_error):
            retained = []
            for name in sorted(names):
                path = Path(directory) / name
                if path.is_symlink():
                    raise ValueError("old evidence directory symlink requires explicit ordinary-root resolution: " + str(path))
                if name in SKIP:
                    excluded[str(path)] = "declared tooling directory; explicit review required"
                else:
                    retained.append(name)
            names[:] = retained
            if len(Path(directory).relative_to(base).parts) > 16:
                raise ValueError("old evidence depth exceeds declared inventory bound")
            for name in leaves:
                path = Path(directory) / name
                if path.is_symlink() or not path.is_file():
                    raise ValueError("old evidence file is not an ordinary file: " + str(path))
                target = archives if name.endswith(ARCHIVE_ENDINGS) else files if path.suffix in TEXT_TYPES else opaque
                target.add(str(path))
                if len(files) + len(archives) + len(opaque) > 100000:
                    raise ValueError("old evidence exceeds declared file bound")
    return {"files": sorted(files), "archives": sorted(archives), "opaque": sorted(opaque), "excluded_directories": excluded}


def scan_archive(path, parse_payload):
    """Never extract or execute an archive member; hash all, parse bounded metadata."""
    path = Path(path)
    before = identity(path)
    records, pixels, total, seen = {}, set(), 0, set()

    def consume(name, size, stream):
        nonlocal total
        member = PurePosixPath(name)
        if member.is_absolute() or ".." in member.parts or str(member) in seen or len(seen) >= 50000:
            raise ValueError("unsafe, duplicate or excessive prior archive member")
        if size < 0 or size > MAX_FILE or total + size > MAX_EXPANDED:
            raise ValueError("prior archive expanded size exceeds scan bound")
        seen.add(str(member))
        total += size
        hashed, data, read = hashlib.sha256(), [], 0
        parse = member.suffix in TEXT_TYPES
        while True:
            part = stream.read(1 << 20)
            if not part:
                break
            read += len(part)
            if read > size:
                raise ValueError("prior archive member expanded beyond declared size")
            hashed.update(part)
            if parse:
                data.append(part)
        if read != size:
            raise ValueError("prior archive member is truncated")
        found = parse_payload(b"".join(data), member.suffix) if parse else set()
        pixels.update(found)
        records[str(member)] = {"sha256": hashed.hexdigest(), "bytes": size,
                               "parsed_metadata": parse, "source_pixel_count": len(found)}

    if path.name.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("prior ZIP contains a symlink")
                with archive.open(member) as stream:
                    consume(member.filename, member.file_size, stream)
    elif path.name.endswith((".tar.gz", ".tar.xz", ".tgz", ".tar", ".tar.bz2", ".tbz2")):
        with tarfile.open(path, "r:*") as archive:
            for member in archive:
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError("prior archive contains a nonregular member")
                with archive.extractfile(member) as stream:
                    consume(member.name, member.size, stream)
    else:
        raise ValueError("unsupported prior archive format must be resolved before freezing: " + str(path))
    if not records or identity(path) != before:
        raise ValueError("empty or changed prior archive")
    return {**before, "members": records, "expanded_bytes": total, "source_pixel_count": len(pixels)}, pixels


def opaque_groups(census):
    groups = defaultdict(list)
    for path in census["opaque_files"]:
        groups[Path(path).suffix or "<no-suffix>"].append(path)
    for archive, record in census["archives"].items():
        for name, member in record["members"].items():
            if not member["parsed_metadata"]:
                groups[PurePosixPath(name).suffix or "<no-suffix>"].append(archive + "!" + name)
    return dict(groups)


def verify_opaque_review(census, attestation):
    groups = opaque_groups(census)
    resolutions = attestation.get("opaque_suffix_resolutions", {})
    if set(resolutions) != set(groups):
        raise ValueError("every opaque prior-evidence format needs explicit source-metadata coverage review")
    metadata = set(census["files"])
    metadata.update(archive + "!" + name for archive, record in census["archives"].items()
                    for name, member in record["members"].items() if member["parsed_metadata"])
    for suffix, review in resolutions.items():
        if (review.get("file_count") != len(groups[suffix]) or review.get("all_source_exposures_covered_by_metadata") is not True
                or len(review.get("reason", "")) < 20 or not review.get("metadata_evidence")
                or not set(review["metadata_evidence"]).issubset(metadata)):
            raise ValueError("opaque format lacks a bound, explained source-identity coverage resolution")
    skipped = attestation.get("excluded_directory_resolutions", {})
    if set(skipped) != set(census["excluded_directories"]):
        raise ValueError("every excluded tooling directory needs explicit scope review")
    for resolution in skipped.values():
        if resolution.get("not_experiment_evidence") is not True or len(resolution.get("reason", "")) < 20:
            raise ValueError("excluded directory scope remains unresolved")
