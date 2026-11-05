"""Foundation-only output-family checks; no compiler peak guarantee."""
import hashlib
import json
from pathlib import Path

from b16_guard import need


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def metadata_projection(metadata):
    return {
        "workspace_root": metadata["workspace_root"],
        "target_directory": metadata["target_directory"],
        "workspace_members": sorted(metadata["workspace_members"]),
        "workspace_default_members": sorted(metadata["workspace_default_members"]),
        "nodes": sorted(({
            "id": row["id"], "features": sorted(row["features"]),
            "deps": sorted(row.get("deps", []), key=lambda dep: (dep["name"], dep["pkg"])),
        } for row in metadata["resolve"]["nodes"]), key=lambda row: row["id"]),
        "packages": sorted(({
            "id": row["id"], "manifest_path": row["manifest_path"],
            "features": row["features"], "targets": row["targets"],
        } for row in metadata["packages"]), key=lambda row: row["id"]),
    }


def relative_output(path, target):
    path, target = Path(path), Path(target)
    need(path.is_absolute() and target.is_absolute(), "output-family paths must be absolute")
    relative = path.relative_to(target)
    need(".." not in relative.parts, "output-family path escaped the target")
    return relative.as_posix()


def catalog_layout(catalog):
    target = catalog["rust-build-meta"]["target-directory"]
    return [{
        "binary_id": binary_id, "binary_name": row["binary-name"],
        "package_name": row["package-name"],
        "package_id_sha256": hashlib.sha256(row["package-id"].encode()).hexdigest(),
        "kind": row["kind"], "build_platform": row["build-platform"],
        "relative_path": relative_output(row["binary-path"], target),
    } for binary_id, row in sorted(catalog["rust-suites"].items())]


def normal_helper_layout(rows, target):
    return sorted(({
        "target": row["target"]["name"] if isinstance(row["target"], dict) else row["target"],
        "package_id_sha256": hashlib.sha256(row["package_id"].encode()).hexdigest(),
        "features": sorted(row["features"]),
        "relative_path": relative_output(row["path"], target),
    } for row in rows), key=lambda row: row["target"])


def helper_layout(rows, target):
    return sorted(relative_output(row["path"], target) for row in rows)


def load_family(binding):
    path = Path(__file__).resolve().parent / "foundation-output-family.json"
    raw = path.read_bytes()
    need(hashlib.sha256(raw).hexdigest() == binding.get("approved_foundation_output_family_sha256"),
         "foundation-only family identity needs explicit approval")
    family = json.loads(raw)
    need(family["schema"] == "hepta-b16-foundation-output-family-v1", "unknown family contract")
    need(family["last_tested_A_tree"] == binding["last_tested_A_tree"], "family belongs to another tested source")
    need(family["last_tested_A_artifact_sha256"] == binding["last_tested_A_artifacts"]["sha256"],
         "family and original full artifact receipt differ")
    if binding.get("target_reuse_mode") == "BUILD_ONLY_CURRENT_HOST":
        from b16_build_only import current_family
        return current_family(binding, family)
    return family


def verify_metadata(family, metadata):
    need(digest(metadata_projection(metadata)) == family["complete_metadata_projection_sha256"],
         "foundation changed full targets, declared/active features, dependencies or source/target paths")


def verify_catalog(family, catalog):
    need(catalog_layout(catalog) == family["complete_catalog_layout"],
         "foundation created or moved a catalog output unit")
    need(digest(catalog["rust-build-meta"]) == family["complete_rust_build_meta_sha256"],
         "foundation build paths/platform configuration differ")


def verify_normal_helpers(family, rows, target):
    need(normal_helper_layout(rows, target) == family["normal_six_helper_layout"],
         "foundation changed normal-helper output paths or feature sets")


def verify_helpers(family, rows, target):
    need(helper_layout(rows, target) == family["complete_helper_relative_paths"],
         "foundation helper output paths differ")


def validate_foundation_reuse(binding, metadata, manifest, operations, artifact):
    need(binding["authorized_epoch"] == "foundation", "family exception is foundation-only")
    family = load_family(binding)
    need(binding["approved_payload_sha256"] == family["payload_sha256"], "family uses a different payload")
    labels = []
    for operation in operations:
        need(operation["kind"] in ("apply", "scopes", "negative"), "foundation added an adoption/generator stage")
        labels.extend(operation.get("before", []))
        if operation["kind"] == "apply":
            labels.append(operation["delta"])
        if operation.get("restore"):
            labels.append(operation["restore"])
    need(labels == family["foundation_delta_order"], "foundation source/restore sequence differs")
    paths = sorted({row["path"] for label in labels for row in manifest["deltas"][label]["files"]})
    need(paths == family["foundation_source_paths"] and len(paths) == 16 and
         all(path.endswith(".rs") and "/bin/" not in path and
             path.startswith(("codex-rs/state/src/", "codex-rs/hepta-memory/src/")) for path in paths),
         "family exception requires only the exact 16 approved source paths")
    need(binding["environment"].get("CARGO_BUILD_JOBS") == "4", "retain the observed four-build-job capacity premise")
    budget = binding["capacity_plan"]
    need(budget["additional_executable_families"] == 0 and
         budget["other_cargo_growth_bytes"] == 12000000000 and
         budget["bazel_growth_bytes"] == 0 and budget["evidence_growth_bytes"] == 2000000000 and
         binding["min_free_bytes"] == 8000000000, "foundation-only 12+2+8 GB planning allowance changed")
    verify_metadata(family, metadata)
    verify_helpers(family, artifact["helpers_after_catalog_before_just"], binding["target_directory"])
    target = Path(binding["target_directory"]).resolve()
    paths = {row["relative_path"] for row in family["complete_catalog_layout"]}
    paths.update(family["complete_helper_relative_paths"])
    for relative in paths:
        output = target / relative
        need(output.is_file() and output.resolve().is_relative_to(target) and output.stat().st_mode & 0o111,
             "the complete existing output family is missing or outside the target: " + relative)
    result = {"family_sha256": binding["approved_foundation_output_family_sha256"],
            "existing_catalog_units": len(family["complete_catalog_layout"]),
            "existing_helper_paths": len(family["complete_helper_relative_paths"]),
            "existing_executable_paths_checked": len(paths), "foundation_source_paths": family["foundation_source_paths"],
            "full_metadata_projection_equal": True,
            "limit": "Output-path reuse supports this conditional allowance, not a measured 12 GB compiler/linker peak. Fresh per-phase metadata, normal helpers, full catalog and complete helper path checks remain mandatory."}
    if binding.get("target_reuse_mode") == "BUILD_ONLY_CURRENT_HOST":
        result.update({"family_sha256": digest(family), "role": "BUILD_ONLY_CURRENT_HOST",
                       "current_host_build_only_baseline": binding["current_host_build_only_baseline"],
                       "tests_executed": False, "test_qualification": False})
    return result
