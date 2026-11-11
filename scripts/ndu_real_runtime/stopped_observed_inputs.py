"""Transfer the five already registered public sources without the full corpus.

The explicit manifest pin authenticates an extracted subset. Upstream parquet
verification happened at extraction; remote admission does not re-read it.
"""

import hashlib
import json
from pathlib import Path, PurePosixPath

from ndu_real_materials.common import binding, read_bound, write_json
from .stopped_diagnostics import validate_registration

SCHEMA = "ndu.stopped.observed-inputs.v1"
ROOT_FILES = {"registration.json", "prospective-selection.json", "prepared-cases.json"}


def save_inputs(root, cases, dataset):
    root = Path(root)
    write_json(root / "prepared-cases.json", cases)
    paths = sorted(path for path in (root / "materials").rglob("*") if path.is_file())
    paths += sorted(root / name for name in ROOT_FILES)
    manifest = {
        "schema": SCHEMA,
        "dataset": dataset,
        "provenance": "fixed upstream parquet verified at extraction; exact transferred subset",
        "files": [binding(path, root) for path in paths],
    }
    write_json(root / "input-manifest.json", manifest)
    return hashlib.sha256((root / "input-manifest.json").read_bytes()).hexdigest()


def load_inputs(source, destination, expected_sha256, dataset):
    source, destination = Path(source), Path(destination)
    manifest_bytes = read_bound(
        source,
        {
            "path": "input-manifest.json",
            "sha256": expected_sha256,
            "bytes": (source / "input-manifest.json").stat().st_size,
        },
        limit=65536,
    )
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != SCHEMA or manifest.get("dataset") != dataset:
        raise ValueError("Prepared subset has another schema or upstream source pin")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
        raise ValueError("Prepared subset exceeds its bounded file inventory")
    names, payloads, total = set(), [], 0
    for item in entries:
        name = item.get("path")
        path = PurePosixPath(name) if isinstance(name, str) else PurePosixPath("/")
        if (
            path.is_absolute()
            or ".." in path.parts
            or name in names
            or (
                name not in ROOT_FILES
                and (not path.parts or path.parts[0] != "materials")
            )
        ):
            raise ValueError(
                "Prepared subset contains an unrecognized or duplicate path"
            )
        raw = read_bound(source, item, limit=32 * 1024 * 1024)
        total += len(raw)
        if total > 64 * 1024 * 1024:
            raise ValueError("Prepared subset exceeds its 64 MiB transfer bound")
        names.add(name)
        payloads.append((path, raw))
    if not ROOT_FILES <= names:
        raise ValueError("Prepared subset lacks prospective registration inputs")
    by_name = {str(path): raw for path, raw in payloads}
    registration = validate_registration(json.loads(by_name["registration.json"]))
    cases = json.loads(by_name["prepared-cases.json"])
    roster = [
        group
        for role in ("fit", "calibration", "diagnostic")
        for group in registration[role + "_source_groups"]
    ]
    if (
        not isinstance(cases, list)
        or len(cases) != 5
        or [case["source_id"] for case in cases] != roster
    ):
        raise ValueError("Prepared cases differ from the frozen five-source roster")
    # Validate all input bytes and roles before writing any transferred data.
    for path, raw in payloads:
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
    with (destination / "input-manifest.json").open("xb") as stream:
        stream.write(manifest_bytes)
    return destination / "materials", cases
