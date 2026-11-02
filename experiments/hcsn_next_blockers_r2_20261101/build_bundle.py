"""Audit final component bytes, then build a reproducible, self-contained R2 ZIP.

Run only after every scientific lane has frozen its manifest. No experiments,
downloads, Library writes or remote publication are performed by this script.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREDECESSOR = "HCSN_Addressed_Followup_20261101_source_evidence.zip"
PREDECESSOR_SHA = "9c7fb471af01515f1617f8973de438c56d3deed91479ec0e8cf948915fe7b4ea"
SPECIAL = {HERE.name, "hcsn_policy_population_r2_20261101"}
REQUIRED = {f"hcsn_{name}_r2_20261101" for name in (
    "audio_pretrained", "cpu_envelope", "distribution_value", "exact_transport",
    "grid_frontend", "missing_reliability", "read_repair",
    "video_pretrained_feasibility", "video_raw")}
FINAL_RECEIPTS = {"BUNDLE_RECEIPT.json", "BUNDLE_PUBLICATION.json",
                  "LIBRARY_RECEIPT.json", "TRANSPORT_RECEIPT.json", "TRANSPORT_MANIFEST.json"}
STAMP = (2026, 11, 1, 0, 0, 0)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                       allow_nan=False) + "\n").encode()


def safe(name):
    value = PurePosixPath(name)
    if value.is_absolute() or ".." in value.parts or "\\" in name:
        raise ValueError(f"Unsafe archive path: {name}")
    return value


def verify_predecessor(path, references):
    if path.stat().st_size != 43_572_900 or digest(path) != PREDECESSOR_SHA:
        raise ValueError("Predecessor archive identity changed")
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
        expected = {e["path"] for e in manifest["files"]}
        old_entries = {e["path"]: e["sha256"] for e in manifest["files"]}
        if any(old_entries.get(name) != wanted for name, wanted in references):
            raise ValueError("A frozen R1 dependency is absent or different in the predecessor")
        if set(archive.namelist()) != expected | {"PACKAGE_MANIFEST.json"}:
            raise ValueError("Predecessor archive inventory mismatch")
        for entry in manifest["files"]:
            safe(entry["path"])
            content = archive.read(entry["path"])
            if len(content) != entry["bytes"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
                raise ValueError(f"Predecessor member changed: {entry['path']}")
    return len(expected)


def verify_component(directory):
    path = directory / "ARTIFACT_MANIFEST.json"
    if not path.is_file():
        if directory.name not in SPECIAL:
            raise FileNotFoundError(f"Scientific lane not finalized: {path}")
        return None
    manifest = json.loads(path.read_text())
    seen = set()
    members = manifest.get("files", manifest.get("entries"))
    if not isinstance(members, (list, dict)):
        raise ValueError(f"Unsupported component inventory: {path}")
    if "files" in manifest and "entries" in manifest and manifest["files"] != manifest["entries"]:
        raise ValueError(f"Conflicting component inventories: {path}")
    if isinstance(members, dict):
        members = [dict(path=name, **value) for name, value in members.items()]
    for entry in members:
        relative = str(safe(entry["path"]))
        prefix = directory.relative_to(ROOT).as_posix() + "/"
        if relative.startswith(prefix):
            relative = relative[len(prefix):]
        if relative in seen:
            raise ValueError(f"Duplicate component member: {path}:{relative}")
        seen.add(relative)
        target = directory / relative
        if target.is_symlink() or target.stat().st_size != entry["bytes"] or digest(target) != entry["sha256"]:
            raise ValueError(f"Frozen component member changed: {target}")
    if manifest.get("file_count", len(seen)) != len(seen):
        raise ValueError(f"Component count mismatch: {path}")
    for relative in manifest.get("required_absent", []):
        if (directory / safe(relative)).exists():
            raise ValueError(f"Forbidden held-out artifact exists: {directory / relative}")
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(path), "files_checked": len(seen)}


RESTORE = r'''"""Verify this extracted bundle and restore the pinned predecessor into repo/."""
import hashlib, json, stat, zipfile
from pathlib import Path, PurePosixPath
base = Path(__file__).resolve().parent
sha = lambda data: hashlib.sha256(data).hexdigest()
manifest = json.loads((base / 'BUNDLE_MANIFEST.json').read_text())
def safe_target(name, root=base):
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or '\\' in str(relative): raise ValueError('Unsafe path')
    target = root / str(relative)
    if any(p.is_symlink() for p in [target, *target.parents] if p == base or base in p.parents): raise ValueError('Symlink ancestor')
    return target
for entry in manifest['files']:
    path = safe_target(entry['path'])
    if path.is_symlink() or path.stat().st_size != entry['bytes']:
        raise ValueError('Bundle size/type mismatch: ' + entry['path'])
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''): h.update(block)
    if h.hexdigest() != entry['sha256']: raise ValueError('Bundle hash mismatch: ' + entry['path'])
archive_path = safe_target(manifest['predecessor']['path'])
with zipfile.ZipFile(archive_path) as archive:
    old = json.loads(archive.read('PACKAGE_MANIFEST.json'))
    expected = {e['path'] for e in old['files']}
    if set(archive.namelist()) != expected | {'PACKAGE_MANIFEST.json'}: raise ValueError('Old inventory')
    for entry in old['files']:
        name = PurePosixPath(entry['path']); info = archive.getinfo(str(name))
        target = safe_target(str(name), base / 'repo')
        if stat.S_ISLNK(info.external_attr >> 16): raise ValueError('Old symlink')
        content = archive.read(str(name))
        if len(content) != entry['bytes'] or sha(content) != entry['sha256']: raise ValueError('Old hash')
        if target.exists():
            if target.is_symlink() or sha(target.read_bytes()) != entry['sha256']: raise FileExistsError(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream: stream.write(content)
print('All bundle payload hashes verified; predecessor restored under repo/. No downloads or model runs performed.')
'''

README = (HERE / "README_BOOTSTRAP.md").read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--predecessor", type=Path, default=ROOT.parent / "deliverables" / PREDECESSOR)
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--exclude-receipt", action="append", default=[], help="Extra final integration JSON receipt basename")
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(ROOT):
        raise ValueError("Write the bundle outside the repository to avoid self-inclusion")
    if not (HERE / "REPORT_ZH.md").is_file():
        raise FileNotFoundError("Final integration REPORT_ZH.md is required")
    final = FINAL_RECEIPTS | set(args.exclude_receipt)
    if any(Path(n).name != n or not n.endswith(".json") for n in final):
        raise ValueError("Final receipt exclusions must be simple JSON basenames")
    directories = sorted((ROOT / "experiments").glob("hcsn_*r2_20261101"))
    if not REQUIRED <= {p.name for p in directories}:
        raise ValueError("Missing a required scientific lane")
    checks = [check for p in directories if (check := verify_component(p)) is not None]
    references = set()
    def collect(value):
        for key, item in value.items():
            if isinstance(item, str) and key.startswith("experiments/") and "_r2_" not in key and len(item) == 64 and all(c in "0123456789abcdef" for c in item):
                references.add((key, item))
        return value
    for directory in directories:
        for path in directory.rglob("*.json"):
            try: json.loads(path.read_text(), object_hook=collect)
            except (json.JSONDecodeError, UnicodeDecodeError): pass
    count = verify_predecessor(args.predecessor, references)
    payload = {}; generated = {"restore.py": RESTORE.encode(), "README_BOOTSTRAP.md": README.encode()}
    for directory in directories:
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"No symlinks in evidence: {path}")
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if directory == HERE and path.parent == HERE and path.name in final:
                continue
            if directory == HERE and path.is_relative_to(HERE / "evidence_parts"):
                continue
            if path.suffix.lower() in {".flv", ".mpg", ".mpeg", ".mp4", ".avi"}:
                raise ValueError(f"Raw media entered a scientific directory: {path}")
            payload["repo/" + str(path.relative_to(ROOT))] = path
    identity = json.loads((ROOT / "experiments/hcsn_video_pretrained_feasibility_r2_20261101/SOURCE_IDENTITY.json").read_text())
    upstream = ROOT.parent / "upstream_lipreading_tcn"
    for name, wanted in identity["upstream_files_sha256"].items():
        path = upstream / str(safe(name))
        if path.is_symlink() or digest(path) != wanted:
            raise ValueError(f"Upstream source identity changed: {path}")
        payload["upstream_lipreading_tcn/" + name] = path
    payload["upstream_lipreading_tcn/README.md"] = upstream / "README.md"
    external = []
    for lane, size, wanted, location in (
        ("video_pretrained_feasibility", 145630317, "c72c9d494ffdcb8616ce183b92393b17a8bdf1ad8b523c9ac42b0507824c214f", "pretrained_lipreading_weights/resnet18_mstcn_video.pth"),
        ("audio_pretrained", 377664473, "488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d", "upstream_audio/wav2vec2_fairseq_base_ls960_asr_ls960.pth")):
        receipt = ROOT / f"experiments/hcsn_{lane}_r2_20261101/CHECKPOINT.json"
        value = json.loads(receipt.read_text())
        if value["bytes"] != size or value["sha256"] != wanted:
            raise ValueError(f"External checkpoint receipt changed: {receipt}")
        path = ROOT.parent / location
        if path.exists() and (path.is_symlink() or path.stat().st_size != size or digest(path) != wanted):
            raise ValueError(f"Local external checkpoint disagrees with receipt: {path}")
        external.append(dict(lane=lane, bytes=size, sha256=wanted, sibling_path=location,
            receipt="repo/" + str(receipt.relative_to(ROOT)), receipt_sha256=digest(receipt),
            local_bytes_verified=path.exists(), included_in_zip=False))
    generated["EXTERNAL_INPUTS.json"] = encoded(dict(weights=external, raw_media_included=False))
    payload["predecessor/" + PREDECESSOR] = args.predecessor
    entries = [{"path": name, "bytes": path.stat().st_size, "sha256": digest(path)} for name, path in payload.items()]
    entries += [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in generated.items()]
    packed = {entry["path"]: entry["sha256"] for entry in entries}
    if any(packed["repo/" + check["path"]] != check["sha256"] for check in checks):
        raise ValueError("A component manifest changed during inventory")
    manifest = dict(schema="hcsn.r2.bundle.v1", files=sorted(entries, key=lambda e: e["path"]),
        scientific_directories=[p.name for p in directories], component_manifest_checks=checks,
        predecessor=dict(path="predecessor/" + PREDECESSOR, sha256=PREDECESSOR_SHA, restored_files=count, frozen_dependency_identities_checked=len(references)),
        compression=dict(method="ZIP_DEFLATED", level=6, zlib_version=zlib.ZLIB_RUNTIME_VERSION),
        exclusions=["__pycache__", "*.pyc", "raw public media", "third-party weights", "BUNDLE_MANIFEST.json", "integration/evidence_parts/"] + sorted(final),
        all_blockers_closed=False, production_activation=False)
    if args.inventory_only:
        print(encoded(manifest).decode(), end=""); return
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.output.with_suffix(args.output.suffix + ".inventory.json").exists():
        raise FileExistsError("Inventory output already exists")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    partial = args.output.with_suffix(args.output.suffix + ".partial")
    with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, strict_timestamps=True) as archive:
        for entry in manifest["files"] + [{"path": "BUNDLE_MANIFEST.json"}]:
            name = entry["path"]; info = zipfile.ZipInfo(name, STAMP)
            info.create_system = 3; info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED; info._compresslevel = 6
            with archive.open(info, "w", force_zip64=True) as target:
                if name in payload:
                    with payload[name].open("rb") as source: shutil.copyfileobj(source, target, 1 << 20)
                else: target.write(encoded(manifest) if name == "BUNDLE_MANIFEST.json" else generated[name])
    with zipfile.ZipFile(partial) as archive:
        for entry in manifest["files"]:
            h = hashlib.sha256(); size = 0
            with archive.open(entry["path"]) as stream:
                for block in iter(lambda: stream.read(1 << 20), b""): h.update(block); size += len(block)
            if size != entry["bytes"] or h.hexdigest() != entry["sha256"]:
                raise ValueError(f"Input changed during build: {entry['path']}; partial retained")
    if checks != [check for p in directories if (check := verify_component(p)) is not None]:
        raise ValueError("A scientific component changed during build; partial retained")
    partial.rename(args.output)
    receipt = dict(path=str(args.output), bytes=args.output.stat().st_size, sha256=digest(args.output),
        payload_files=len(entries), payload_bytes=sum(e["bytes"] for e in entries), component_manifests_checked=len(checks))
    with args.output.with_suffix(args.output.suffix + ".inventory.json").open("x") as stream:
        stream.write(encoded(dict(receipt=receipt, manifest=manifest)).decode())
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
