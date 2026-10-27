"""Copy only hash-verified recovered numeric assets and unchanged V3 readers."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


DOMAINS = ("co2", "temperature", "sunspots", "unemployment")
LEGACY_MODULES = ("__init__.py", "factor_cell.py", "numeric_graph.py", "learned_graph.py", "semantic_router.py", "codec.py", "codec_reader.py")
OLD_PREFIX = "qualification/memory-cell-v4/results/20261026-v4-frozen/joint/seed-401/"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def copy_assets(export_json, export_root, legacy_source, project):
    export_json, export_root = Path(export_json), Path(export_root)
    legacy_source, project = Path(legacy_source), Path(project)
    export_raw = export_json.read_bytes()
    exported = json.loads(export_raw)
    if exported["commit"] != "3c509f9bb9a9724cddbe6a917c728e022582fefe":
        raise ValueError("unexpected recovered V4 artifact commit")
    records = {row["path"]: row for row in exported["files"]}
    wanted = ["layout/model/manifest.json", "layout/model/weights.bin"]
    for domain in DOMAINS:
        wanted.extend(f"numeric-memories/{domain}/primary/{name}" for name in ("addresses.json", "memory.factor"))
        wanted.extend(f"numeric-memories/{domain}/codecs/{name}" for name in ("addresses.json", "receipt.json", "residual.archive", "strong-exact.archive"))
    prepared = {}
    for relative in wanted:
        name = OLD_PREFIX + relative
        record = records[name]
        path = export_root / name
        if path.is_symlink() or record["mode"] != "100644" or record["symlink_materialized_as_regular_bytes"]:
            raise ValueError("linked or nonregular recovered artifact")
        raw = path.read_bytes()
        git_oid = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if identity(raw) != {key: record[key] for key in ("bytes", "sha256")} or git_oid != record["oid"]:
            raise ValueError("recovered bytes differ from original Git blob binding")
        prepared[relative] = (raw, {**identity(raw), "git_blob_oid": git_oid, "original_path": name, "object_origin": record["object_origin"]})
    vendor = {name: (legacy_source / name).read_bytes() for name in LEGACY_MODULES}
    assets, legacy = project / "assets", project / "legacy_v3"
    assets.mkdir(parents=True, exist_ok=False)
    legacy.mkdir(parents=True, exist_ok=False)
    for relative, (raw, _) in prepared.items():
        destination = assets.joinpath(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(raw)
    for name, raw in vendor.items():
        with (legacy / name).open("xb") as stream:
            stream.write(raw)
    receipt = {"schema": "hepta.memory.v5.reused-assets.v1", "source_commit": exported["commit"],
               "source_tree_oid": exported["tree_oid"], "recovery_export_identity": identity(export_raw),
               "domains": list(DOMAINS), "files": {name: row for name, (_, row) in prepared.items()},
               "original_v4_full_run_recovered": False, "retail_weights_recovered": False,
               "new_numeric_or_graph_training": False,
               "object_origin_preserved": True, "full_pack_checksum_not_claimed": True}
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    (assets / "ASSETS.json").write_bytes(encoded)
    vendor_receipt = {"schema": "hepta.memory.v5.unchanged-vendor.v1", "source_directory": str(legacy_source.resolve()),
                      "files": {"legacy_v3/" + name: identity(raw) for name, raw in vendor.items()},
                      "byte_identical_copy": True, "not_new_v5_training_code": True}
    (project / "VENDOR.json").write_text(json.dumps(vendor_receipt, sort_keys=True, indent=2) + "\n")
    return {"asset_files": len(prepared), "asset_bytes": sum(len(raw) for raw, _ in prepared.values()),
            "binding": identity(encoded), "vendor_files": len(vendor)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-json", required=True, type=Path)
    parser.add_argument("--export-root", required=True, type=Path)
    parser.add_argument("--legacy-source", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(copy_assets(args.export_json, args.export_root, args.legacy_source, args.project), sort_keys=True))
