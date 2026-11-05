import datetime
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
source_map = json.loads((ROOT / "source-map.json").read_text())
patch = ROOT / "read-readiness.patch"


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def section(text, start, end):
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


def read_data(path):
    return json.loads(path.read_text())["structuredContent"]


rows = source_map["files"]
for row in rows:
    assert identity(Path(row["local_postimage"]).read_bytes()) == row["postimage"]
    if row["preimage"] is not None:
        assert identity(Path(row["local_preimage"]).read_bytes()) == row["preimage"]

directory_bindings = {}
for name in ("source-api-0.json", "binding-api-0.json", "binding-api-1.json"):
    data = read_data(ROOT / "originals" / name)
    entries = json.loads(data["content"])
    assert isinstance(entries, list)
    assert len({entry["path"] for entry in entries}) == len(entries)
    directory_bindings[name] = {"entries": len(entries), "paths": {entry["path"]: entry["sha"] for entry in entries}}
for row in rows:
    bindings = directory_bindings["source-api-0.json" if "/win/" in row["path"] else "binding-api-0.json"]["paths"]
    if row["preimage"]:
        assert bindings[row["path"]] == row["preimage"]["blob"]
    else:
        assert row["path"] not in bindings

before = Path(rows[0]["local_preimage"]).read_text()
after = Path(rows[0]["local_postimage"]).read_text()
preservations = []
for title, start, end in (
    ("Payload and SetupMode wire schema", "#[derive(Debug, Clone, Deserialize, Serialize)]", "fn log_line("),
    ("read roots, RX shortcuts, per-root ACL operations and error collection", "struct ReadAclSubjects", "fn lock_sandbox_dir("),
    ("directory ACL helper, actual entrypoint and marker order", "fn lock_sandbox_dir(", "fn run_read_acl_only("),
    ("provision-only and common provisioning operations", "fn provision_and_hide_sandbox_users(", "fn run_setup_full("),
):
    old = section(before, start, end)
    new = section(after, start, end)
    assert old == new, title
    preservations.append({"name": title, "equal": True, **identity(old.encode())})

old_read = section(before, "    let sandbox_group_sid = resolve_sandbox_users_group_sid()?;", "    if !refresh_errors.is_empty() {")
new_read = section(after, "    let sandbox_group_sid = resolve_sandbox_users_group_sid()?;", "    if !refresh_errors.is_empty() {")
assert old_read == new_read
preservations.append({"name": "read ACL SID resolution, masks, inheritance, actual operation and cleanup", "equal": True, **identity(old_read.encode())})

old_tail = before[before.index("    if refresh_only {\n        setup_runtime_bin::"):]
new_tail = after[after.index("    if refresh_only {\n        setup_runtime_bin::"):]
new_tail = new_tail.replace("write roots after read ACL stage; errors={:?}", "write roots (read roots delegated); errors={:?}")
assert old_tail == new_tail
preservations.append({"name": "remaining Full runtime/write/deny operations and all original helper tests, excluding only truthful progress log", "equal": True, **identity(old_tail.encode())})

old_test_block = before[before.index('#[cfg(test)]\n#[path = "win_acl_tests.rs"]'):]
new_test_block = after[after.index('#[cfg(test)]\n#[path = "win_acl_tests.rs"]'):]
assert old_test_block == new_test_block
old_test_names = re.findall(r"#\[test\]\s+fn ([a-zA-Z0-9_]+)", old_test_block)
assert old_test_names
new_test = Path(rows[2]["local_postimage"]).read_text()
new_test_names = re.findall(r"#\[test\]\s+fn ([a-zA-Z0-9_]+)", new_test)
assert new_test_names == ["existing_read_acl_mutex_is_not_a_completion_receipt"]
assert "#[ignore" not in new_test
assert "#[test]" in new_test

mutex_before = Path(rows[1]["local_preimage"]).read_text()
mutex_after = Path(rows[1]["local_postimage"]).read_text()
assert section(mutex_before, "pub(super) struct ReadAclMutexGuard", "pub(super) fn read_acl_mutex_exists") == section(mutex_after, "pub(super) struct ReadAclMutexGuard", "pub(super) fn acquire_read_acl_mutex")
assert 'const READ_ACL_MUTEX_NAME: &str = "Local\\\\CodexSandboxReadAcl";' in mutex_after
assert "spawn_read_acl_helper" not in after
assert "read_acl_mutex_exists" not in after + mutex_after
assert "run_read_acl_only(payload, log)?;" in after
assert 'if payload.refresh_only {\n            anyhow::bail!("read ACL run had errors")' not in after

commands = []
roundtrip = []
with tempfile.TemporaryDirectory(prefix="isolated-git-apply-", dir=ROOT) as work:
    work = Path(work)
    for row in rows:
        if row["preimage"]:
            dst = work / row["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(Path(row["local_preimage"]).read_bytes())
    for args in (
        ["git", "apply", "--check", "--whitespace=error-all", str(patch)],
        ["git", "apply", "--whitespace=error-all", str(patch)],
        ["git", "apply", "--reverse", "--check", "--whitespace=error-all", str(patch)],
        ["git", "apply", "--reverse", "--whitespace=error-all", str(patch)],
    ):
        result = subprocess.run(args, cwd=work, capture_output=True, text=True, check=False)
        commands.append({"argv": args, "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        assert result.returncode == 0, commands[-1]
        if args[1:3] == ["apply", "--whitespace=error-all"]:
            for row in rows:
                actual = identity((work / row["path"]).read_bytes())
                assert actual == row["postimage"]
                roundtrip.append({"phase": "applied", "path": row["path"], "identity": actual})
    for row in rows:
        path = work / row["path"]
        if row["preimage"] is None:
            assert not path.exists()
        else:
            assert identity(path.read_bytes()) == row["preimage"]
        roundtrip.append({"phase": "restored", "path": row["path"], "identity": row["preimage"]})

diff_lines = patch.read_text().splitlines()
added = sum(line.startswith("+") and not line.startswith("+++") for line in diff_lines)
removed = sum(line.startswith("-") and not line.startswith("---") for line in diff_lines)
assert added + removed < 500
receipt = {
    "kind": "isolated-source-and-git-patch-verification",
    "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "base_head": source_map["base_head"],
    "base_tree": source_map["base_tree"],
    "patch": identity(patch.read_bytes()),
    "diff": {"paths": len(rows), "added": added, "removed": removed, "changed": added + removed},
    "directory_bindings": directory_bindings,
    "preserved_source_regions": preservations,
    "all_original_win_rs_inline_test_names_byte_preserved": old_test_names,
    "all_original_win_rs_test_region": identity(old_test_block.encode()),
    "new_test_names": new_test_names,
    "mutex_guard_body_and_production_name_preserved": True,
    "git_commands": commands,
    "roundtrip": roundtrip,
    "rust_formatted": False,
    "rust_compiled": False,
    "project_or_windows_tests_executed": False,
    "shared_source_index_target_or_refs_changed": False,
    "limitations": ["This verifies patch bytes and named preserved regions, not Rust typechecking or runtime behavior.", "The new actual Win32 mutex control is source only and has not executed.", "Library tests alone do not select the setup-binary test module."],
}
(ROOT / "static-verification.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({"status": "PASS_STATIC_ONLY", "receipt": identity((ROOT / "static-verification.json").read_bytes()), "diff": receipt["diff"], "old_win_rs_tests": len(old_test_names), "new_tests": len(new_test_names)}, indent=2))
