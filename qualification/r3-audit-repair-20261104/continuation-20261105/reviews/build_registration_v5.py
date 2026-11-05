"""Build the evidence-only continuation plan without changing published V4."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "hepta-audit-fifth"
PREFIX = "qualification/r3-audit-repair-20261104/continuation-20261105"
items = {}


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def add(local, relative, role, proof=None):
    local = Path(local)
    if not local.is_absolute():
        local = ROOT / local
    actual = identity(local.read_bytes())
    path = relative if relative.startswith(PREFIX + "/") else PREFIX + "/" + relative
    assert path not in items, path
    row = {"repository_path": path, "local_file": str(local), "mode": "100644", **actual, "role": role}
    if proof is not None:
        expected_blob = proof.get("blob", proof.get("git_blob"))
        assert expected_blob == actual["blob"], path
        for key in ("bytes", "sha256"):
            if key in proof:
                assert actual[key] == proof[key], path
        row["prior_object_verification"] = proof
        row["object_verified_by"] = "delegated actual GitHub create and full GET; root local byte identity rechecked"
    items[path] = row


def load(path):
    return json.loads((ROOT / path).read_bytes())


registries = [
    "research-audit/b11-token-mechanism-independent-20261105/registry-plan.json",
    "research-audit/published-5b633-ci-20261105/windows-checkout-locks/registry-plan.json",
    "research-audit/published-5b633-ci-20261105/github-status-20261105T1128/registry-plan.json",
    "research-audit/published-5b633-ci-20261105/immutable-v5-snapshot0030/registry-plan.json",
    "research-audit/r2f1-independent-review-20261105/registry-plan.json",
]
for name in registries:
    doc = load(name)
    for row in doc.get("items", doc.get("rows", [])):
        assert row["actual_create_get"] is True
        add(row["local_path"], row["repository_path"], "complete original evidence or bounded independent review", row)

foundation = "ci-audit/recovered-20261105/b16-ai395-foundation-v7-v2"
for index in range(2, 11):
    name = f"B{index:02d}-priority-bundle.json"
    pin = load(foundation + f"/B{index:02d}-priority-bundle.identity.json")
    # Each original phase was actually created and GET-verified by ci_audit;
    # the root separately decoded and verified all complete original bytes.
    pin["actual_create_get_reported_by_ci_audit"] = True
    add(foundation + "/" + name, "native/b16-ai395-foundation-v7-v2/" + name,
        "complete selected phase originals; expected negative failures remain distinct", pin)
pin = load(foundation + "/terminal-priority-bundle.identity.json")
pin["actual_create_get_reported_by_ci_audit"] = True
add(foundation + "/terminal-priority-bundle.json", "native/b16-ai395-foundation-v7-v2/terminal-priority-bundle.json",
    "sixteen complete original terminal, source, SDK and tool records", pin)
add(foundation + "/archive_priority_phase.py", "native/b16-ai395-foundation-v7-v2/archive_priority_phase.py", "cloud original-byte archiver")

for label, destination in (("foundation-final-metadata", "native/b16-ai395-foundation-v7-v2/final-metadata-original"),
                            ("driver-enable-originals", "native/b16-ai395-driver-v7-v1/launch-request-originals")):
    for path in sorted((OUT / "v5-archives" / label).iterdir()):
        add(path, destination + "/" + path.name, "lossless original-byte archive; raw native paths and bytes retained")

for folder, destination in (("architecture-audit/b16-driver-input-review-20261105", "reviews/b16-driver-exact-inputs"),
                            ("architecture-audit/b16-driver-launcher-template-20261105", "native/b16-ai395-driver-v7-v1/launcher-template")):
    doc = load(folder + "/github-readback-map.json")
    for row in doc.get("files", doc.get("objects", [])):
        if "name" in row:
            local = folder + "/" + row["name"]
            assert row["create_get_exact"] is True
        else:
            local = row["path"]
            assert row["created"] is True and row["get_equal"] is True
        add(local, destination + "/" + Path(local).name, "original driver scope or unchanged disabled launcher review", row)
    add(folder + "/github-readback-map.json", destination + "/github-readback-map.json", "actual Git object readback map")

candidate = "ci-audit/recovered-20261105/b16-ai395-driver-v7-bound-candidate-v1"
for name in ("driver-binding-DISABLED-actual-foundation-v1.json", "actual-foundation-binding-manifest.json", "binding-v2-to-actual-foundation.delta.patch"):
    add(candidate + "/" + name, "native/b16-ai395-driver-v7-v1/bound-candidate/" + name,
        "actual foundation outputs bound to disabled next epoch; no predicted source or locks")
old = "ci-audit/recovered-20261105/b16-ai395-driver-v7-disabled-v1"
for name in ("driver-binding-DISABLED.json", "driver-binding-v1-to-v2.delta.patch", "foundation-to-driver-binding.delta.patch", "launcher-narrow-review.json"):
    add(old + "/" + name, "native/b16-ai395-driver-v7-v1/prior-disabled/" + name, "preserved earlier disabled preparation")

r2f1 = "architecture-audit/b16-next-normal-chain-20261105/r2f1-root-checkpoint-transport"
for row in load(r2f1 + "/github-readback-map.json")["objects"]:
    assert row["created"] is True and row["GET_byte_equal"] is True
    local = Path(row["path"])
    if "b16-driver-bound-review" in str(local):
        destination = "reviews/driver-actual-foundation-independent-review.json"
    else:
        destination = "candidate-next/r2f1-root-checkpoint-transport/" + str(local.relative_to(ROOT / r2f1))
    add(local, destination, "cloud-reviewed candidate only; no native compilation or independent Root acceptance", row)
add(r2f1 + "/github-readback-map.json", "candidate-next/r2f1-root-checkpoint-transport/github-readback-map.json", "actual Git object readback map")

root_inputs = {
    "inputs/foundation-phase-review-through-06.json": "reviews/foundation-phase-review-through-06.json",
    "inputs/foundation-phase-review-through-08.json": "reviews/foundation-phase-review-through-08.json",
    "inputs/foundation-phase-review-through-09.json": "reviews/foundation-phase-review-through-09.json",
    "inputs/foundation-phase-review-through-10.json": "reviews/foundation-phase-review-through-10.json",
    "inputs/foundation-root-live-observation-1121.json": "reviews/foundation-original-live-observation-1121.json",
    "inputs/driver-disabled-root-review.json": "reviews/driver-disabled-root-review.json",
    "inputs/driver-actual-foundation-root-review.json": "reviews/driver-actual-foundation-root-review.json",
    "root-execution-guard-ai395-driver-v7-v1.json": "native/b16-ai395-driver-v7-v1/root-execution-guard.json",
    "driver-binding-ENABLED.json": "native/b16-ai395-driver-v7-v1/driver-binding-ENABLED.json",
    "driver-enablement-receipt.json": "native/b16-ai395-driver-v7-v1/driver-enablement-receipt.json",
    "verify_foundation_phases.py": "reviews/verify_foundation_phases.py",
    "verify_driver_actual_binding.py": "reviews/verify_driver_actual_binding.py",
    "pack_originals_v5.py": "reviews/pack_originals_v5.py",
    "audit-publication-receipt-v4.json": "publication/audit-publication-receipt-v4.json",
    "pr4797-body-after-v4.md": "publication/pr4797-body-after-v4.md",
}
for source, destination in root_inputs.items():
    add(OUT / source, destination, "root independent verification, exact enablement, or preserved publication receipt")

plan = {"schema": "hepta-continuation-fifth-publication-plan-v1", "prefix": PREFIX,
        "base_audit_commit": "be6eddc503d909181ea195612c293f115d0447ea",
        "base_audit_tree": "ca84f1e8ebfeca09d514e11c90f625a70c4cdfbc",
        "code_candidate_commit": "5b6331250ff459033bd44d1a95daec70131277cc",
        "code_candidate_tree": "b26598d0d97d8d51e723bb5582137315f2174d35",
        "scope": "Evidence, documentation and explicitly unqualified next-candidate copies only; no production source/ref/base/main changes.",
        "entry_count": len(items), "items": sorted(items.values(), key=lambda r: r["repository_path"])}
target = OUT / "registration-plan-v5-initial.json"
target.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"plan": str(target), "items": len(items), "already_actual_objects": sum("object_verified_by" in r for r in items.values()),
                  "new_or_pending_object_verifications": sum("object_verified_by" not in r for r in items.values())}))
