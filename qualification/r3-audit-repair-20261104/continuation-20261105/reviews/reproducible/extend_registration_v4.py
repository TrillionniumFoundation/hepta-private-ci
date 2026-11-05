#!/usr/bin/env python3
"""Extend the verified evidence plan without changing any product source."""
import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "hepta-audit-fifth"
PLAN = OUT / "registration-plan-v4-verified.json"
PREFIX = "qualification/r3-audit-repair-20261104/continuation-20261105"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "blob": hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()}


def main():
    plan = json.loads(PLAN.read_bytes())
    entries = {item["repository_path"]: item for item in plan["items"]}

    def add(local, destination, role, prior=None):
        local = Path(local)
        if not local.is_absolute():
            local = ROOT / local
        raw = local.read_bytes()
        meta = identity(raw)
        assert len(raw) < 512000, (local, len(raw))
        path = destination if destination.startswith(PREFIX + "/") else PREFIX + "/" + destination
        item = {"repository_path": path, "local_file": str(local), "mode": "100644", **meta, "role": role}
        old = entries.get(path)
        if old and all(old[k] == item[k] for k in ("blob", "bytes", "sha256")):
            item = {**old, **item}
        if prior:
            assert prior.get("git_blob", prior.get("blob")) == meta["blob"], (local, prior)
            for key in ("bytes", "sha256"):
                if key in prior:
                    assert prior[key] == meta[key], (local, key)
            item["prior_object_verification"] = prior
            item["object_verified_by"] = "pinned delegated actual create and GET map; local identity rechecked"
        entries[path] = item

    def registry(directory, digest, destination):
        directory = ROOT / directory
        registry_path = directory / "registry-plan.json"
        registry_doc = json.loads(registry_path.read_bytes())
        for row in registry_doc["rows"]:
            assert row["actual_create_get"] is True
            add(row["local_path"], row["repository_path"], row.get("role", "full original PR evidence or fixed-source projection"), row)
        add(registry_path, destination, "actual delegated object registration plan", {"git_blob": digest, "actual_create_get": True})

    registry("research-audit/published-5b633-ci-20261105/immutable-v4-windows-operator-delta",
             "6cb98f8a897a52ca5c3b0e8bdef401f920b32322",
             "generated-evidence/ci-5b633-windows-operator-v4/registry-plan.json")
    registry("research-audit/open-pr-increment-20261105T1013/immutable-delivery",
             "bfc17c0d053b899c806b4314b647c90a4a04da20",
             "generated-evidence/pr-updated-prefix-20261105-1014/registry-plan.json")
    registry("research-audit/published-5b633-ci-20261105/immutable-v5-business-retained",
             "692db8c24e80309e44bf63133eef69711441feb3",
             "generated-evidence/ci-5b633-business-retained-v5/registry-plan.json")

    native = ROOT / "ci-audit/recovered-20261105/b16-ai395-foundation-v7-v2"
    delivery_map = json.loads((native / "actual-git-delivery-map.json").read_bytes())
    for row in delivery_map["objects"]:
        assert row["create_and_get_byte_equal"] is True
        local = Path(row["path"])
        destination = "native/" + "/".join(local.parts[-2:])
        add(local, destination, "frozen prelaunch input or historical transfer receipt", row)
    add(native / "actual-git-delivery-map.json", "native/b16-ai395-foundation-v7-v2/prelaunch-object-readback-map.json",
        "historical prelaunch map; native_not_launched describes its earlier snapshot")

    root_objects = [
        ("inputs/b16-foundation-v7-concrete-root-review.json", "reviews/b16-foundation-v7-concrete-root-review.json", "5931d32457c8e89d6e16d072c5eeccd1a03c8397"),
        ("root-execution-guard-ai395-foundation-v7-v1.json", "native/b16-ai395-foundation-v7-v2/root-execution-guard.json", "9ef6f66dca8ec960aad511a6fb9a973b7c3349a8"),
        ("foundation-binding-ENABLED.json", "native/b16-ai395-foundation-v7-v2/foundation-binding-ENABLED.json", None),
        ("inputs/new-head-ci-v4-root-review.json", "reviews/new-head-ci-v4-root-review.json", None),
    ]
    for local, destination, blob in root_objects:
        add(OUT / local, destination, "root execution binding or independent review", {"git_blob": blob, "actual_create_get": True} if blob else None)
    add("architecture-audit/b16-foundation-ai395-binding-review-20261105/review.json",
        "reviews/b16-foundation-ai395-independent-binding-review.json", "independent concrete native binding review",
        {"git_blob": "a4d4bda4c4ffd0e64440dcb8edbe551be583ea6f", "actual_create_get": True})

    transport = OUT / "foundation-enablement"
    manifest = json.loads((transport / "manifest.json").read_bytes())
    chunks = []
    offset = 0
    for row in manifest["parts"]:
        raw = (transport / row["name"]).read_bytes()
        assert identity(raw) == row["file"]
        assert raw.endswith(b"\n") and b"\n" not in raw[:-1]
        assert row["compressed_offset"] == offset
        decoded = base64.b64decode(raw[:-1], validate=True)
        assert identity(decoded) == row["decoded_chunk"]
        chunks.append(decoded)
        offset += len(decoded)
        add(transport / row["name"], "native/b16-ai395-foundation-v7-v2/enabled-request/" + row["name"], "lossless exact enabled request transport; not test output")
    compressed = b"".join(chunks)
    assert identity(compressed) == manifest["compressed"]
    raw = gzip.decompress(compressed)
    assert identity(raw) == manifest["original"]
    assert raw == (OUT / "foundation-launch-request-ENABLED.json").read_bytes()
    add(transport / "manifest.json", "native/b16-ai395-foundation-v7-v2/enabled-request/manifest.json", "exact enabled request identities and reconstruction instructions")

    bundle_file = native / "launch-first-source-priority-bundle.json"
    bundle = json.loads(bundle_file.read_bytes())
    decoded = {}
    for row in bundle["records"]:
        packed = base64.b64decode(row["data"], validate=True)
        assert len(packed) == row["compressed_bytes"]
        assert hashlib.sha256(packed).hexdigest() == row["compressed_sha256"]
        original = gzip.decompress(packed)
        assert identity(original) == {"bytes": row["bytes"], "sha256": row["sha256"], "blob": row["git_blob"]}
        assert row["relative_path"] not in decoded
        decoded[row["relative_path"]] = original
    assert len(decoded) == 14
    assert sum(map(len, decoded.values())) == 72539
    assert bundle["normal_helpers_exit_code"] == bundle["metadata_exit_code"] == 0
    assert bundle["same_key_reconciliation_response_reused"] is False
    assert bundle["catalog_snapshot_status"] == "in_progress"
    add(bundle_file, "native/b16-ai395-foundation-v7-v2/launch-first-source-priority-bundle.json",
        "14 complete launch/first-source records; catalog progress sample is explicitly nonterminal",
        {"git_blob": "c7d89bd6a17f3e2ec32d3d4ec085ef0ffe9e83b6", "actual_create_get": True})
    add(native / "start-indeterminate-receipt.json", "native/b16-ai395-foundation-v7-v2/start-indeterminate-receipt.json",
        "preserved first tool timeout and bounded read-only reconciliation; no inferred native result",
        {"git_blob": "3c1a3de7545dcea975e805055ca5ce0fb762130f", "actual_create_get": True})
    add(native / "installation-receipt.original.json", "native/b16-ai395-foundation-v7-v2/installation-receipt.original.json", "actual installed runtime and exact enabled binding receipt")
    add(native / "actual-launch-and-first-status.json", "native/b16-ai395-foundation-v7-v2/actual-launch-and-first-status.json", "actual same-key reconciliation and first authoritative running observation")
    add(native / "B01-priority-bundle.json", "native/b16-ai395-foundation-v7-v2/B01-priority-bundle.json",
        "five complete originals of first actual Foundation scope; four selected passes, not whole-workspace qualification",
        {"git_blob": "c06b696277301ac1e9a182b953c534d197579ecf", "actual_create_get": True})
    add("ci-audit/recovered-20261105/main-host-readonly-identity-v1/complete-receipt.json",
        "native/main-host-readonly-identity-v1/complete-receipt.json", "actual read-only ARM host identity; no Intel inference or build lane",
        {"git_blob": "5b312e7d357ddb579339127ea05fcca060edd92c", "actual_create_get": True})

    boundary_dir = ROOT / "architecture-audit/b11-delete-boundary-20261105"
    boundary_map = json.loads((boundary_dir / "github-readback-map.json").read_bytes())
    for row in boundary_map["files"]:
        assert row["created"] and row["get_full_text_equal"]
        add(boundary_dir / row["name"], "reviews/b11-delete-boundary/" + row["name"], "current production boundary and original Windows failure review; no qualified source patch", row)
    add(boundary_dir / "github-readback-map.json", "reviews/b11-delete-boundary/github-readback-map.json", "actual delegated review object delivery map")

    add("research-audit/open-pr-increment-20261105T1013/immutable-delivery/pr4844-accesscheck-scope-addendum.json",
        "generated-evidence/pr-updated-prefix-20261105-1014/pr4844-accesscheck-scope-addendum.json",
        "distinguishes full-restricting AccessCheck control from production-token physical deletion",
        {"git_blob": "abbece8c5df20228a46a83c6000af54e0d794995", "actual_create_get": True})

    for name in ("LATEST.zh-CN.md", "CONTINUATION_PROGRESS_V3.zh-CN.md", "continuation-blocker-progress-v2.json"):
        add(OUT / name, name, "human progress or original blocker ledger; exact original closure conditions preserved")
    add(OUT / "inputs/latest-scopes-root-review.json", "reviews/latest-scopes-root-review.json", "root independent full XML/log/name/ZIP/transport and program-identity verification")
    add(OUT / "verify_latest_scopes.py", "reviews/reproducible/verify_latest_scopes.py", "reproduce latest independent evidence checks without project execution")
    add(Path(__file__), "reviews/reproducible/extend_registration_v4.py", "evidence registration and lossless transport verification")
    plan["items"] = sorted(entries.values(), key=lambda item: item["repository_path"])
    plan["entry_count"] = len(plan["items"])
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"entry_count": len(entries), "verified_objects": sum(bool(item.get("object_verified_by")) for item in entries.values()),
                      "pending_objects": sum(not item.get("object_verified_by") for item in entries.values()),
                      "enabled_request_lossless": True, "launch_bundle_originals": len(decoded), "launch_bundle_original_bytes": sum(map(len, decoded.values()))}))


if __name__ == "__main__":
    main()
