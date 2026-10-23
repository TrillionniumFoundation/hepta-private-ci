"""Preserve frozen evidence while giving archived Rust files inert suffixes."""
import argparse
import hashlib
import json
from pathlib import Path

ORIGINAL_MANIFEST = "48180760e9f2771f859e80cfd1df057a4fdfc19572403520cec47024172d1170"
ORIGINAL_SUMS = "9c8486ca465e1bcc2d83b3add942b5664e2817557036279ed94c8b5c932561be"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"


def package(source, target):
    source, target = Path(source), Path(target)
    if target.exists() or not target.parent.is_dir():
        raise ValueError("new external destination required")
    original = (source / "manifest.json").read_bytes()
    original_sums = (source / "SHA256SUMS").read_bytes()
    if sha(original) != ORIGINAL_MANIFEST or sha(original_sums) != ORIGINAL_SUMS:
        raise ValueError("original package identity differs")
    manifest = json.loads(original)
    if {p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()} != set(manifest["files"]) | {"manifest.json", "SHA256SUMS"}:
        raise ValueError("original inventory differs")
    target.mkdir(mode=0o700)
    entries, mapping = {}, {}

    def put(name, raw, record):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        entries[name] = dict(record, bytes=len(raw), sha256=sha(raw))

    for name, record in manifest["files"].items():
        path = source / name
        raw = path.read_bytes()
        if path.is_symlink() or sha(raw) != record["sha256"] or len(raw) != record["bytes"]:
            raise ValueError("original payload differs: " + name)
        destination = name + ".source" if name.startswith("source-snapshot/") and name.endswith(".rs") else name
        if name == "README.md":
            destination = "original-notes/initial-package-README.md"
        if destination != name:
            mapping[name] = destination
        put(destination, raw, record)
    for name, raw in (("manifest.json", original), ("SHA256SUMS", original_sums)):
        put("checks/initial-package-" + name, raw, {
            "kind": "unchanged-initial-package-index", "original_source": str(source / name)})
    note = (source / "README.md").read_bytes() + b"\n## Repository publication paths\n\nThe archived Rust snapshots use `.rs.source` suffixes so repository formatters\ndo not rewrite historical evidence with a different configuration. Their bytes\nand original Git blob identities are unchanged. The initial package README and\nindexes are retained separately; the current `manifest.json` and `SHA256SUMS`\ncover the publication paths. Run the original packager followed by\n`checks/publication_package.py` to reproduce this mechanical transformation.\nNo original measurement, timing sample, trained weight or test log is changed.\n"
    put("README.md", note, {"kind": "publication-documentation", "original_source": "initial package README plus path explanation"})
    put("checks/publication_package.py", Path(__file__).read_bytes(), {
        "kind": "publication-packaging-script", "original_source": str(Path(__file__).resolve())})
    manifest.update(schema="hepta.p41-evidence-package.v2", files=entries,
        payload_file_count=len(entries), payload_bytes=sum(v["bytes"] for v in entries.values()),
        publication_normalization={"initial_manifest_sha256": ORIGINAL_MANIFEST,
            "initial_sha256sums_sha256": ORIGINAL_SUMS, "path_mapping": mapping,
            "original_payload_bytes_modified": False, "benchmark_rerun": False})
    current_manifest = encode(manifest)
    (target / "manifest.json").write_bytes(current_manifest)
    sums = {name: record["sha256"] for name, record in entries.items()}
    sums["manifest.json"] = sha(current_manifest)
    current_sums = "".join(f"{sums[name]}  {name}\n" for name in sorted(sums)).encode()
    (target / "SHA256SUMS").write_bytes(current_sums)
    for name, pin in sums.items():
        if sha((target / name).read_bytes()) != pin:
            raise ValueError("published package differs: " + name)
    return {"schema": "hepta.p41-publication-package-receipt.v1", "files": len(sums) + 1,
        "bytes": sum(p.stat().st_size for p in target.rglob("*") if p.is_file()),
        "manifest_sha256": sha(current_manifest), "sha256sums_sha256": sha(current_sums),
        "original_payload_bytes_modified": False, "path_mapping": mapping,
        "benchmark_rerun": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.source, args.target), sort_keys=True))
