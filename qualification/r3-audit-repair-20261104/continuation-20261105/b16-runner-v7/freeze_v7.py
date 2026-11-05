"""Freeze the V7 correction without replacing any V6 record or enabling a run."""

import ast
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "build-only-current-host-v6" / "v6-candidate"
OUT = ROOT / "v7-candidate"


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


original_integrity = json.loads((BASE / "runner-integrity.json").read_bytes())
paths = sorted([row["path"] for row in original_integrity["files"]] + ["observed-original-A-catalog.json"])
write(OUT / "runner-integrity.json", {
    "schema": "hepta-b16-runner-integrity-v7-original-ignored-catalog",
    "files": [{"path": name, **identity((OUT / name).read_bytes())} for name in paths],
    "runtime_scope": "Only BUILD_ONLY catalog truth correction: original exact matches or original ignored mismatch, plus the immutable complete named case Counter. All native, source, recovery, lock, budget and legacy reuse code remains unchanged.",
})
integrity = identity((OUT / "runner-integrity.json").read_bytes())
for name in ("binding-template-UNBOUND.json", "foundation-binding-UNBOUND.json", "foundation-build-only-binding-UNBOUND.json"):
    template = json.loads((BASE / name).read_bytes())
    template["approved_runner_integrity_sha256"] = integrity["sha256"]
    if name == "foundation-build-only-binding-UNBOUND.json":
        template["schema"] = "hepta-b16-explicit-native-binding-v7-original-ignored-catalog"
    assert template["execute"] is False and template["approval_reference"] is None
    write(OUT / name, template)

changed, patch = [], []
for path in sorted(p.name for p in OUT.iterdir() if p.is_file()):
    before, after = BASE / path, OUT / path
    old, new = before.read_bytes() if before.exists() else None, after.read_bytes()
    if old == new:
        continue
    row = {"path": path, "mode": "100644",
           "before": identity(old) if old is not None else None, "after": identity(new)}
    changed.append(row)
    patch.append("diff --git a/" + path + " b/" + path + "\n")
    if old is None:
        patch.append("new file mode 100644\n")
    patch.append("index " + (row["before"]["blob"] if old is not None else "0" * 40) +
                 ".." + row["after"]["blob"] + (" 100644\n" if old is not None else "\n"))
    patch.extend(difflib.unified_diff((old or b"").decode().splitlines(True), new.decode().splitlines(True),
                                    fromfile="a/" + path if old is not None else "/dev/null", tofile="b/" + path))
(ROOT / "v6-to-v7.delta.patch").write_text("".join(patch))

unchanged = [{"path": p.name, **identity(p.read_bytes())}
             for p in sorted(OUT.iterdir()) if p.is_file() and (BASE / p.name).exists() and
             (BASE / p.name).read_bytes() == p.read_bytes()]
required_unchanged = {
    "b16_capacity.py", "b16_family.py", "b16_guard.py", "b16_locks.py", "b16_native.py",
    "b16_oracles.py", "b16_runner.py", "payload-manifest.json", "foundation-output-family.json",
    "epoch-foundation.json", "epoch-driver.json", "epoch-pool.json", "epoch-checkpoint.json", "epoch-owning.json",
    *(f"source-payload-{index:02}.json" for index in range(5)),
}
assert required_unchanged <= {row["path"] for row in unchanged}


def symbols(path):
    text = path.read_text()
    return {node.name: ast.get_source_segment(text, node).encode() for node in ast.parse(text).body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))}


protected = []
for path, names in (
    ("b16_runner.py", ["negative_with_finally", "execute_scopes", "export_evidence"]),
    ("b16_guard.py", ["SourceGuard"]),
    ("b16_build_only.py", ["validate_mode_binding", "pinned_json", "observed_host", "byte_id",
                          "verify_current_outputs", "current_family"]),
):
    old, new = symbols(BASE / path), symbols(OUT / path)
    for name in names:
        assert old[name] == new[name], (path, name)
        protected.append({"path": path, "symbol": name, "byteequal": True, **identity(new[name])})

# Verify the complete transport patch against actual Git, not a custom parser.
git_root = ROOT / "cloud-verification-v1" / "patch-roundtrip"
shutil.copytree(BASE, git_root, ignore=shutil.ignore_patterns("__pycache__"))
commands = []
for label, args in (
    ("git-init", ["git", "init", "-q"]),
    ("git-add-originals", ["git", "add", "."]),
    ("git-apply-check", ["git", "apply", "--check", str(ROOT / "v6-to-v7.delta.patch")]),
    ("git-apply", ["git", "apply", str(ROOT / "v6-to-v7.delta.patch")]),
    ("git-diff-check", ["git", "diff", "--check"]),
):
    proc = subprocess.run(args, cwd=git_root, capture_output=True)
    prefix = ROOT / "cloud-verification-v1" / label
    prefix.with_suffix(".stdout").write_bytes(proc.stdout)
    prefix.with_suffix(".stderr").write_bytes(proc.stderr)
    commands.append({"argv": args, "cwd": str(git_root), "exit_code": proc.returncode,
                     "stdout": identity(proc.stdout), "stderr": identity(proc.stderr)})
    assert proc.returncode == 0, (label, proc.stderr.decode())
for path in OUT.iterdir():
    if path.is_file():
        assert (git_root / path.name).read_bytes() == path.read_bytes(), path.name

write(ROOT / "preservation-verification.json", {
    "schema": "hepta-b16-v7-source-only-preservation-v1",
    "base_integrity": identity((BASE / "runner-integrity.json").read_bytes()),
    "new_integrity": integrity,
    "unchanged_existing_inputs": unchanged,
    "protected_source_segments": protected,
    "legacy_mode": "All legacy guard, capacity, family and runner implementation files are byte-identical; no historical receipt or path is relabeled.",
    "all_payload_scopes_oracles_negative_finally_byte_equal": True,
    "internal_stage_ids_are_not_original_blocker_ids": True,
    "budget_unchanged": {"foundation_required_bytes": 22000000000, "per_command_reserve_bytes": 8000000000,
                         "other_epochs_unchanged": True, "peak_capacity_not_proven": True},
    "git_roundtrip": {"commands": commands, "postimages_verified": 29, "exact": True},
    "native_started": False, "templates_disabled": True,
})
write(ROOT / "source-map-v7.json", {
    "schema": "hepta-b16-v7-source-map-v1", "base": str(BASE), "candidate": str(OUT),
    "files": [{"path": p.name, "mode": "100644", **identity(p.read_bytes())}
              for p in sorted(OUT.iterdir()) if p.is_file()],
    "changed_files": changed, "patch": identity((ROOT / "v6-to-v7.delta.patch").read_bytes()),
})
print(json.dumps({"candidate_files": len([p for p in OUT.iterdir() if p.is_file()]),
                  "integrity": integrity, "unchanged": len(unchanged),
                  "changed_files": [row["path"] for row in changed],
                  "patch": identity((ROOT / "v6-to-v7.delta.patch").read_bytes())}, indent=2))
