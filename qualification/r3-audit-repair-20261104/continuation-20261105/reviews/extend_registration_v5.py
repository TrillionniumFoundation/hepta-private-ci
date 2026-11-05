"""Append verified original-byte and candidate registries to the current V5 plan."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "hepta-audit-fifth/registration-plan-v5-verified-extended.json"
PREFIX = "qualification/r3-audit-repair-20261104/continuation-20261105/"


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def extend():
    plan = json.loads(PLAN.read_bytes())
    entries = {r["repository_path"]: r for r in plan["items"]}
    initial = len(entries)

    def add(path, dest, expected, role, proof):
        path = Path(path)
        if not path.is_absolute():
            path = ROOT / path
        actual = identity(path)
        assert actual["blob"] == (expected.get("blob") or expected.get("git_blob"))
        for field in ("bytes", "sha256"):
            if field in expected:
                assert actual[field] == expected[field]
        repo_path = dest if dest.startswith(PREFIX) else PREFIX + dest
        row = {"repository_path": repo_path, "local_file": str(path), "mode": "100644",
               **actual, "role": role, "prior_object_verification": proof,
               "object_verified_by": "delegated actual create/full GET and root local identity; registry or map independently fetched by root"}
        if repo_path in entries:
            assert entries[repo_path]["blob"] == actual["blob"]
        else:
            entries[repo_path] = row

    maps = [
        ("ci-audit/recovered-20261105/b16-ai395-foundation-v7-v2/complete-archive/git-delivery-map.json",
         "ca2edaaf5b814885830bffbefa661245cc2dc6d2", "files",
         "native/b16-ai395-foundation-v7-v2/complete-archive/",
         "Complete original Foundation bytes; no driver or other platform qualification"),
        ("architecture-audit/pr-increment-20261105T1204/frozen/github-readback-map.json",
         "c4cca93e1f038510aa762dd43d2ba020148dee10", "objects",
         "generated-evidence/pr-increment-20261105T1204/",
         "Bounded original API increment: 13 window updates and 4 new PR numbers; not a fresh full inventory"),
        ("architecture-audit/b16-refused-commit-pool-20261105/github-readback-map.json",
         "dc59161e12e74864a588402499082360980464f1", "objects",
         "candidate-next/b16-refused-commit-pool/",
         "Static candidate and preserved original evidence; no compilation or native red/green result")]
    for relative, blob, key, dest, role in maps:
        path = ROOT / relative
        data = json.loads(path.read_bytes())
        add(path, dest + path.name, {"blob": blob}, role,
            {"root_full_GET_equals_local": True, "map_blob": blob})
        for row in data[key]:
            assert (row.get("actual_create") or row.get("create_succeeded")) is True
            assert (row.get("actual_get_equal") or row.get("get_byte_equal")) is True
            local = ROOT / row["path"]
            suffix = str(local.relative_to(path.parent))
            add(local, dest + suffix, row, role, row)

    registries = [
        ("research-audit/published-5b633-ci-20261105/immutable-v5-windows-core-lifecycle/registry-plan.json",
         "124436a5c24d33e6e8c66478d34d28edb588f609",
         "generated-evidence/ci-5b633-windows-core-lifecycle-v5/",
         "Original source-head Windows Core failure, original normal sharding and complete case-level scope"),
        ("research-audit/published-5b633-ci-20261105/immutable-v5-snapshot0033/registry-plan.json",
         "deb69643e8e47afbca3ea54e4eca4b55d421fedc",
         "generated-evidence/ci-5b633-snapshot0033-v5/",
         "Immutable historical CI snapshot 0033; subsequent terminal results are separate")]
    for relative, blob, dest, role in registries:
        path = ROOT / relative
        data = json.loads(path.read_bytes())
        add(path, dest + path.name, {"blob": blob}, role,
            {"root_full_GET_equals_local": True, "registry_blob": blob})
        for row in data["items"]:
            assert row["create_succeeded"] and row["get_succeeded"] and row["get_content_equal"]
            assert row["created_sha"] == row["blob"]
            add(row["local_path"], row["repo_path"], row, role, row)

    plan["items"] = sorted(entries.values(), key=lambda r: r["repository_path"])
    plan["entry_count"] = len(entries)
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"before": initial, "after": len(entries), "added": len(entries) - initial,
                      "plan": str(PLAN), **identity(PLAN)}))


if __name__ == "__main__":
    extend()
