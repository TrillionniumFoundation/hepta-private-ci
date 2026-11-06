#!/usr/bin/env python3
"""Read-only independent checks against the complete frozen v3 source bundle.

Usage: python verify_independent.py PATH_TO_V3_BUNDLE
No Git commands, compiler, network, product code or native actions are executed.
"""
from pathlib import Path
import collections
import hashlib
import json
import re
import sys

OWN = Path(__file__).resolve().parent
ROOT = Path(sys.argv[1]).resolve()
TARGET = "codex-rs/windows-sandbox-rs/src/token_neither_privilege_observation.rs"
BEFORE = "b40b49ce772c402c51ddb16bb98ff73dc78cdb41"
AFTER = "8c16416c185f17871c25139bc16c6fd112b5fd41"
OLD_TREE = "9cb7302777ce018dd022086041c2225d1dd5c8dd"
NEW_TREE = "9a804c7b6e0dd554cdb435f41e06c5c689fffaaf"


def git_object(kind, data):
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def ident(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": git_object("blob", data)}


def read_json(path):
    return json.loads(path.read_bytes())


def merkle(leaves):
    root = {}
    for path, row in leaves.items():
        parts = path.split("/")
        current = root
        for part in parts[:-1]:
            current = current.setdefault(part, {})
            assert isinstance(current, dict)
        assert parts[-1] not in current
        current[parts[-1]] = (row["mode"].lstrip("0"), row["sha"])
    hashes = {}

    def visit(node, path):
        rows = []
        for name, value in node.items():
            directory = isinstance(value, dict)
            mode, sha = ("40000", visit(value, (path + "/" + name).lstrip("/"))) if directory else value
            rows.append((name.encode() + (b"/" if directory else b""),
                         mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha)))
        body = b"".join(row[1] for row in sorted(rows))
        hashes[path] = git_object("tree", body)
        return hashes[path]

    return visit(root, ""), hashes


def parse_hunks(patch):
    lines = patch.splitlines(keepends=True)
    assert lines[:2] == [("--- a/" + TARGET + "\n").encode(), ("+++ b/" + TARGET + "\n").encode()]
    hunks = []
    for line in lines[2:]:
        if line.startswith(b"@@ "):
            match = re.fullmatch(rb"@@ -(\d+),(\d+) \+(\d+),(\d+) @@\n", line)
            assert match
            hunks.append([*map(int, match.groups()), []])
        else:
            assert hunks and line[:1] in (b" ", b"+", b"-")
            hunks[-1][-1].append(line)
    assert len(hunks) == 5
    return hunks


def apply_hunks(data, hunks, reverse=False):
    source = data.splitlines(keepends=True)
    result, previous = [], 0
    for old_start, old_count, new_start, new_count, lines in hunks:
        before = [line[1:] for line in lines if line[:1] != b"+"]
        after = [line[1:] for line in lines if line[:1] != b"-"]
        assert len(before) == old_count and len(after) == new_count
        if reverse:
            old_start, old_count, new_start, before, after = new_start, new_count, old_start, after, before
        start = old_start - 1
        assert start >= previous
        result.extend(source[previous:start])
        assert len(result) + 1 == new_start
        assert source[start:start + old_count] == before
        result.extend(after)
        previous = start + old_count
    result.extend(source[previous:])
    return b"".join(result)


before = (ROOT / "source" / TARGET).read_bytes()
after = (ROOT / "candidate" / TARGET).read_bytes()
assert ident(before)["git_blob"] == BEFORE and ident(after)["git_blob"] == AFTER
assert len(after) == 26205
assert sorted(p.relative_to(ROOT / "candidate").as_posix() for p in (ROOT / "candidate").rglob("*") if p.is_file()) == [TARGET]
patch = (ROOT / "full.patch").read_bytes()
assert patch == (ROOT / "v2-to-v3.patch").read_bytes()
hunks = parse_hunks(patch)
assert apply_hunks(before, hunks) == after and apply_hunks(after, hunks, reverse=True) == before

source_map = read_json(ROOT / "source-map.json")
tree = read_json(ROOT / "evidence/published-intended-full-tree.json")
assert tree["sha"] == OLD_TREE and tree["truncated"] is False
leaves = {row["path"]: row for row in tree["tree"] if row["type"] != "tree"}
assert len(leaves) == 10589 and leaves[TARGET]["sha"] == BEFORE
actual_root, directory_hashes = merkle(leaves)
assert actual_root == OLD_TREE and len(directory_hashes) == 1571
assert all(directory_hashes[row["path"]] == row["sha"] for row in tree["tree"] if row["type"] == "tree")
for commit in ("2980fa274c599bd07437a2f5915b86d858f89bcc", "53766cb836b198e2f928b949f148d7a2a10c0d21"):
    authority = json.loads(read_json(OWN / f"authority-{commit}.original.json")["api_content"])
    assert authority["sha"] == commit and authority["tree"]["sha"] == actual_root

readbacks = read_json(OWN / "source-readbacks.json")["original_sources"]
readback_by_path = {row["repository_path"]: row for row in readbacks}
assert len(readbacks) == len(source_map["original_sources"]) == 14
for row in source_map["original_sources"]:
    path = row["repository_path"]
    identity = ident((ROOT / "source" / path).read_bytes())
    assert all(identity[key] == row[key] for key in identity)
    receipt = readback_by_path[path]
    assert identity["git_blob"] == leaves[path]["sha"] == receipt["actual_blob_sha"]
    assert identity["sha256"] == receipt["sha256"] and receipt["independent_complete_GET_equal"] is True
post = read_json(OWN / "candidate-postimage-independent-readback.json")
assert post["actual_blob_sha"] == AFTER and post["independent_actual_full_GET_byte_equal"] is True
assert post["bytes"] == len(after) and post["sha256"] == ident(after)["sha256"]
updated = dict(leaves)
updated[TARGET] = dict(leaves[TARGET], sha=AFTER)
new_root, new_directories = merkle(updated)
assert new_root == NEW_TREE and len(new_directories) == 1571

old, new = before.decode(), after.decode()
run = "pub(super) fn run() -> Result<()> {"
assert old[old.index(run):] == new[new.index(run):]
start, end = "// A bounded, aligned native result.", "struct OwnedChild {"
assert old[old.index(start):old.index(end)] == new[new.index(start):new.index(end)]
old_cmd = old[old.index("fn cmd_observation("):old.index(run)]
new_cmd = new[new.index("fn cmd_observation("):new.index(run)]
old_begin = old_cmd.index("    // The existing backend assigns its real Job")
old_end = old_cmd.index("    drop(input);", old_begin)
new_begin = new_cmd.index("    // Both subjects use this identical test-only path.")
new_end = new_cmd.index("    drop(input);", new_begin)
restored = (new_cmd[:new_begin] + old_cmd[old_begin:old_end] + new_cmd[new_end:]).replace("child.job", "child.created.job")
assert restored == old_cmd
assert old.count("/*dwmilliseconds*/ 5_000") == new.count("/*dwmilliseconds*/ 5_000") == 3
assert "#[test]" not in new and "#[ignore" not in new
desktop = (ROOT / "source/codex-rs/windows-sandbox-rs/src/desktop.rs").read_text()
token = (ROOT / "source/codex-rs/windows-sandbox-rs/src/token.rs").read_text()
assert 'if groups.GroupCount == 0 {' in desktop and 'sandbox token has no restricting SIDs' in desktop
assert '#[cfg(test)]\n#[path = "token_integrity_probe_tests.rs"]\nmod integrity_probe;' in token
assert ident((ROOT / "source/codex-rs/windows-sandbox-rs/src/token_integrity_probe_tests.rs").read_bytes())["git_blob"] == "fc9faa6d47ac5fdefa216affceb51a586f8e6b81"
launcher = new[new.index("fn spawn_observation_child("):new.index("fn cmd_observation(")]
for required in ("JobObject::create()", "ProcThreadAttributeList::new(2)?", "attrs.set_job(",
                 "attrs.set_handle_list(inherited_handles)?", "to_wide(argv_to_command_line(argv))",
                 "make_env_block(env)", 'to_wide(r"Winsta0\\Default")',
                 "threading::CREATE_UNICODE_ENVIRONMENT", "threading::EXTENDED_STARTUPINFO_PRESENT",
                 "threading::CREATE_NO_WINDOW", "/*binherithandles*/ 1", "Ok(OwnedChild {",
                 "process: Handle(process_info.hProcess)", "_thread: Handle(process_info.hThread)"):
    assert required in launcher
assert "release" not in launcher
assert not any(name in launcher for name in ("LaunchDesktop::prepare", "AssignProcessToJobObject", "CreateProcessW(", "CreateProcessWithLogonW", "AdjustTokenPrivileges"))
binding = (ROOT / "primary/windows-sys-0.52.0-System-Threading.rs.source.txt").read_text()
declaration = next(line for line in binding.splitlines() if "fn CreateProcessAsUserW(" in line)
for token_name in ("lpprocessattributes : *const", "lpthreadattributes : *const", "lpenvironment : *const", "lpstartupinfo : *const STARTUPINFOW", "lpprocessinformation : *mut PROCESS_INFORMATION"):
    assert token_name in declaration

native11 = (ROOT / "evidence/native11-full-job.original.log").read_bytes()
assert ident(native11)["sha256"] == "29c7b0343a5f8865bd2bf8088e3108e2c3db3b3f89f93c0aaa72b89834d685bc"
observations = collections.defaultdict(list)
for line in native11.decode().splitlines():
    marker = "PROBE_OBSERVATION_ONLY neither_privileges "
    if marker in line:
        kind, _, payload = line.split(marker, 1)[1].partition(" ")
        observations[kind].append(json.loads(payload))
assert {key: len(value) for key, value in observations.items()} == {"filesystem": 1, "subjects": 1, "rust_before": 3, "rust_physical": 3}
subjects = observations["subjects"][0]
assert subjects["ordinary"]["identity"]["restricted_sids"] == []
assert subjects["ordinary"]["identity"] == subjects["disable_max_privilege"]["identity"]
assert native11.count(b"GetTokenInformation(TokenRestrictedSids) size query failed: 122") == 2

result = {
    "schema": "b11-host-neither-v3-independent-static-review-v1",
    "decision": "STATIC_ACCEPT_EXACT_CANDIDATE_NOT_COMPILE_OR_NATIVE_QUALIFICATION",
    "before": ident(before), "after": ident(after), "patch": ident(patch),
    "single_changed_source_path": TARGET, "patch_hunks": 5,
    "forward_and_reverse_full_bytes_equal": True,
    "actual_authority_root": actual_root, "expected_candidate_root": new_root,
    "directory_count_including_root": 1571, "leaf_count": 10589, "unchanged_leaves": 10588,
    "independent_full_GET_originals": 14, "independent_full_GET_candidate": True,
    "source_map": ident((ROOT / "source-map.json").read_bytes()),
    "full_tree_evidence": ident((ROOT / "evidence/published-intended-full-tree.json").read_bytes()),
    "all_five_matrix_run_body_exactly_preserved": True,
    "token_record_effective_record_exactly_preserved": True,
    "cmd_body_preserved_except_launcher_and_job_access": True,
    "production_desktop_token_guard_unchanged": True,
    "original_probe_fc9_unchanged": True,
    "test_only_module_guard_preserved": True,
    "new_test_or_ignore_attributes": 0,
    "wait_values_ms": [5000, 5000, 5000],
    "native11_original": ident(native11),
    "native11_observation_record_counts": {key: len(value) for key, value in observations.items()},
    "native11_cmd_contexts_observed": 0,
    "native11_needed_TokenRestrictedSids_buffer_bytes": None,
    "native11_v2_omission": "The observation used the production LaunchDesktop path although both ordinary/privilege-only subjects had empty restricting SID lists. The production precondition rejected that input before CreateProcessAsUserW; the earlier v2 review missed this. The guard is retained and only the test observation launcher changes.",
    "manual_FFI_and_cleanup_review": "Passed for the exact after blob. See REVIEW.zh-CN.md for ownership transitions, paired launch assembly, child-token gate, cleanup failure cases and runtime limits.",
    "product_compilation_performed": False, "native_execution_performed": False,
    "formatting_tool_performed": False, "new_CI_poll_or_dispatch": False,
    "ref_mutations": False, "B11": "OPEN"
}
print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
