#!/usr/bin/env python3
"""Independent offline byte/tree review; starts no product or native process."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def unwrap(raw):
    if "structuredContent" in raw:
        return raw["structuredContent"]
    return json.loads(next(x["text"] for x in raw["content"] if x["type"] == "text"))


def merkle(document):
    rows = {r["path"]: r for r in document["tree"]}
    assert not document["truncated"] and len(rows) == len(document["tree"])
    children = {"": []}
    for path, row in rows.items():
        parent, _, name = path.rpartition("/")
        children.setdefault(parent, []).append((name, row))
        if row["type"] == "tree":
            children.setdefault(path, [])
    computed = {}
    for directory in sorted(children, key=lambda p: (p.count("/") + bool(p), p), reverse=True):
        body = b""
        for name, row in sorted(children[directory], key=lambda p: (p[0] + ("/" if p[1]["type"] == "tree" else "")).encode()):
            path = directory + "/" + name if directory else name
            sha = computed[path] if row["type"] == "tree" else row["sha"]
            if row["type"] == "tree":
                assert sha == row["sha"], path
            mode = "40000" if row["type"] == "tree" else row["mode"]
            body += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha)
        computed[directory] = hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).hexdigest()
    assert computed[""] == document["sha"]
    return {p: (r["mode"], r["type"], r["sha"]) for p, r in rows.items() if r["type"] != "tree"}, len(computed)


def section(text, start, end):
    return text[text.index(start):text.index(end, text.index(start))].rstrip() + "\n"


def main(root, receipts):
    prefix = "codex-rs/windows-sandbox-rs/src/"
    source_map = json.loads((root / "source-map.json").read_bytes())
    before = json.loads((root / "evidence/intended-full-tree.json").read_bytes())
    after = json.loads((root / "intended-full-candidate-tree.json").read_bytes())
    old, old_dirs = merkle(before)
    new, new_dirs = merkle(after)
    assert before["sha"] == "9a804c7b6e0dd554cdb435f41e06c5c689fffaaf"
    assert after["sha"] == "fbaf12d56a9702d927ae6f71cb9f3abc0cf31cae"
    added = sorted(set(new) - set(old))
    changed = sorted(p for p in set(old) & set(new) if old[p] != new[p])
    assert not set(old) - set(new)
    assert added == [prefix + "acl_control_test_support.rs"]
    assert changed == [prefix + n for n in ["lib.rs", "token_tests.rs", "unified_exec/delete_permission_tests.rs"]]
    assert len(old) == 10589 and len(new) == 10590 and old_dirs == new_dirs == 1571
    authority = json.loads((root / "evidence/commit-ref-actual.json").read_bytes())["actualCommit"]
    merge = json.loads((root / "evidence/actual-merge-commit.json").read_bytes())["response"]
    assert authority["sha"] == "87b8603f21e52063ed54ce89cba26756a3efaab7" and authority["tree"]["sha"] == before["sha"]
    assert merge["sha"] == "09960fe697c9c181e4a7d624e29b49360877b687"
    assert merge["tree"]["sha"] == before["sha"]
    assert [r["sha"] for r in merge["parents"]] == ["67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed", authority["sha"]]
    source_rows = []
    for row in source_map["source_files"]:
        raw = (root / row["path"]).read_bytes()
        got = identity(raw)
        assert all(got[k] == row[k] for k in got)
        assert old[row["path"].removeprefix("source/")][2] == got["git_blob"]
        source_rows.append({"path": row["path"], **got})
    candidate_rows = []
    for row in source_map["candidate_files"]:
        raw = (root / row["path"]).read_bytes()
        got = identity(raw)
        assert all(got[k] == row[k] for k in got)
        response = unwrap(json.loads((receipts / (got["git_blob"] + ".json")).read_bytes()))
        assert response["content"].encode() == raw
        assert new[row["path"].removeprefix("candidate/")][2] == got["git_blob"]
        candidate_rows.append({"path": row["path"], **got, "independent_full_GET_byte_equal": True})
    pre = root / "source" / prefix
    post = root / "candidate" / prefix
    with tempfile.TemporaryDirectory(prefix="b11-acl-v2-review-") as tmp:
        temporary = Path(tmp)
        for name in changed:
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((root / "source" / name).read_bytes())
        for reverse in [False, True]:
            result = subprocess.run(["git", "apply", "--unsafe-paths", *(["-R"] if reverse else []), str((root / "full.patch").resolve())], cwd=temporary, capture_output=True)
            assert result.returncode == 0, result.stderr
            expected = changed if reverse else sorted(changed + added)
            actual = sorted(p.relative_to(temporary).as_posix() for p in temporary.rglob("*") if p.is_file())
            assert actual == expected
            for name in expected:
                assert (temporary / name).read_bytes() == (root / ("source" if reverse else "candidate") / name).read_bytes()
    old_token, new_token = [(p / "token_tests.rs").read_text() for p in [pre, post]]
    old_cmd, new_cmd = [(p / "unified_exec/delete_permission_tests.rs").read_text() for p in [pre, post]]
    token_marker = '    eprintln!("delete_matrix host_native_errors={host_errors:?}");'
    cmd_marker = '        eprintln!("delete_matrix host_cmd_status={status} output={host_log:?}");'
    assert old_token[old_token.index(token_marker):] == new_token[new_token.index(token_marker):]
    assert old_cmd[old_cmd.index(cmd_marker):] == new_cmd[new_cmd.index(cmd_marker):]
    assert section(old_cmd, "fn matrix_script(", "#[test]") == section(new_cmd, "fn matrix_script(", "#[test]")
    token_name = "fn workspace_capability_delete_routes_require_the_capability_in_all_four_cells()"
    assert old_token[:old_token.index(token_name)] == new_token[:new_token.index(token_name)]
    for old_text, new_text in [(old_token, new_token), (old_cmd, new_cmd)]:
        assert re.findall(r"(?m)^\s*(?:async )?fn (\w+)", old_text) == re.findall(r"(?m)^\s*(?:async )?fn (\w+)", new_text)
        assert old_text.count("#[test]") == new_text.count("#[test]")
    helper = (post / "acl_control_test_support.rs").read_text()
    donor = (pre / "token_neither_privilege_observation.rs").read_text()
    probe = (pre / "token_integrity_probe_tests.rs").read_text()
    assert section(helper, "// A bounded, aligned native result.", "struct OwnedChild") == section(donor, "// A bounded, aligned native result.", "fn physical(")
    assert section(helper, "struct OwnedChild", "/// Only the enabled privilege set") == section(donor, "struct OwnedChild", "fn cmd_observation(")
    assert section(helper, "#[derive(Debug, PartialEq, Eq, Serialize)]", "// A bounded, aligned native result.") == section(probe, "#[derive(Debug, PartialEq, Eq, Serialize)]", "fn full_restricting_read_token(")
    assert helper.count("/*dwmilliseconds*/ 5_000") == 3
    assert "WaitForSingleObject(child.as_raw_handle() as _, /*dwmilliseconds*/ 5_000)" in old_cmd
    assert "setlocal EnableExtensions DisableDelayedExpansion\\r\\n" in helper
    assert '"echo ACL_CONTROL_INPUT_RELEASED\\r\\n", "endlocal\\r\\n"' in helper
    assert 'env.retain(|name, _| !name.eq_ignore_ascii_case("B11_RELEASE"));' in helper
    gate = helper.index("let command = vec!")
    actual = helper.index('actual["identity"] == self.expected["identity"]', gate)
    release = helper.index("fswin::WriteFile(release.0", actual)
    wait = helper.index("WaitForSingleObject(child.process.0", release)
    cleanup = helper.index("accounting.ActiveProcesses == 0", wait)
    assert gate < actual < release < wait < cleanup
    assert '"/d".to_owned(),\n            "/c".to_owned()' in helper
    assert '"/e:' not in helper and '"/v:' not in helper
    assert "AdjustTokenPrivileges(" not in helper and "SetTokenInformation(" not in helper
    assert 'let flags = DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED;' in (pre / "token.rs").read_text()
    assert 'sandbox token has no restricting SIDs' in (pre / "desktop.rs").read_text()
    assert new[prefix + "token_neither_privilege_observation.rs"][2] == "8c16416c185f17871c25139bc16c6fd112b5fd41"
    assert new[prefix + "token_integrity_probe_tests.rs"][2] == "fc9faa6d47ac5fdefa216affceb51a586f8e6b81"
    result = {
        "decision": "STATIC_ACCEPT_EXACT_V2_NOT_COMPILE_OR_NATIVE_QUALIFICATION",
        "blocking_findings": [], "B11": "OPEN", "source_commit": authority["sha"],
        "source_tree": before["sha"], "candidate_tree_computed": after["sha"],
        "source_leaves": len(old), "candidate_leaves": len(new), "directory_nodes": old_dirs,
        "added": added, "changed": changed, "removed": [], "unchanged_prior_leaves": len(old) - len(changed),
        "all_directory_Merkle_hashes_equal": True, "forward_and_reverse_patch_full_byte_equal": True,
        "host_assertions_and_both_strict_suffixes_entire_byte_equal": True,
        "matrix_script_and_test_function_rosters_equal": True,
        "native_donor_blocks_entire_byte_equal": True,
        "production_desktop_token_and_prior_probe_unchanged": True,
        "source_files": source_rows, "candidate_files": candidate_rows,
        "native_run": False, "product_compile": False, "formatter": False, "ref_mutation": False,
        "scope": "Only prerequisite subject correction for two existing host ACL controls; no production isolation repair or assertion weakening."
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--receipts", type=Path, default=Path(__file__).resolve().parent / "full-GET-originals")
    args = parser.parse_args()
    main(args.root.resolve(), args.receipts.resolve())
