#!/usr/bin/env python3
"""Verify fixed evidence and the recorded offline replay; never run Rust or CI."""
from pathlib import Path
import argparse
import hashlib
import json


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}


def merkle(leaves):
    root = {}
    for path, entry in leaves.items():
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node
        node[parts[-1]] = (entry["mode"].lstrip("0"), entry["sha"])
    result = {}
    def visit(node, prefix):
        raw = b""
        for name, value in sorted(node.items(), key=lambda x: (x[0] + ("/" if isinstance(x[1], dict) else "")).encode()):
            mode, sha = ("40000", visit(value, prefix + name + "/")) if isinstance(value, dict) else value
            raw += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha)
        result[prefix.rstrip("/")] = hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        return result[prefix.rstrip("/")]
    visit(root, "")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    r = p.parse_args().root.resolve()
    a = r / "frozen-author"
    freeze = json.loads((a / "FREEZE.json").read_bytes())
    assert len(freeze["files"]) == len({x["path"] for x in freeze["files"]}) == 23
    for item in freeze["files"]:
        assert identity((a / item["path"]).read_bytes()) == {k: item[k] for k in ("bytes", "git_blob", "sha256")}
    assert sum(x["bytes"] for x in freeze["files"]) == 5117370
    base = json.loads((a / "authority/base-full-tree.json").read_bytes())
    leaves = {x["path"]: {k: x[k] for k in ("path", "mode", "type", "sha")} for x in base["tree"] if x["type"] != "tree"}
    assert len(leaves) == 10802 and not base["truncated"]
    old = merkle(leaves)
    assert old[""] == base["sha"] == freeze["base_tree"] == "66552bda88637403f4f1d72a5be8592e07a8a308"
    assert all(old[x["path"]] == x["sha"] for x in base["tree"] if x["type"] == "tree")
    observed = json.loads((r / "replay-01.stdout.json").read_bytes())
    assert (r / "replay-01.stderr.txt").read_bytes() == b""
    assert (r / "replay-01.stdout.json").read_bytes() == (a / "verification-01.stdout.json").read_bytes()
    for name in ("VERIFICATION.json", "candidate.patch", "intended-full-tree.json"):
        assert (r / "replay-01" / name).read_bytes() == (a / "verification-01" / name).read_bytes()
    sources = json.loads((r / "source-full-GET.original.json").read_bytes())
    by_sha = {x["sha"]: x["raw"] for x in sources}
    assert len(by_sha) == 3
    for item in observed["changed_paths"]:
        path = item["path"]
        before = (a / "preimage" / path).read_bytes()
        after = (a / "candidate" / path).read_bytes()
        assert identity(before) == item["preimage"] and identity(after) == item["postimage"]
        assert leaves[path]["sha"] == item["preimage"]["git_blob"]
        raw = by_sha[item["postimage"]["git_blob"]]
        assert not raw.get("isError") and raw["structuredContent"]["content"].encode() == after
        leaves[path] = {**leaves[path], "sha": item["postimage"]["git_blob"]}
    new = merkle(leaves)
    assert new[""] == observed["expected_tree"] == freeze["actual_candidate_tree"] == "c24f6910e0af5a3ebf809c29f1fb06dafbd94146"
    intended = json.loads((r / "replay-01/intended-full-tree.json").read_bytes())
    assert {x["path"]: x for x in intended["tree"] if x["type"] != "tree"} == leaves
    assert all(new[x["path"]] == x["sha"] for x in intended["tree"] if x["type"] == "tree")
    actual = json.loads((r / "candidate-root-full-GET.original.json").read_bytes())
    assert not actual.get("isError")
    actual = json.loads(actual["structuredContent"]["content"])
    assert actual["sha"] == new[""] and not actual["truncated"] and len(actual["tree"]) == 53
    assert {x["path"]: (x["mode"], x["type"], x["sha"]) for x in actual["tree"]} == {x["path"]: (x["mode"], x["type"], x["sha"]) for x in intended["tree"] if "/" not in x["path"]}
    context = json.loads((r / "context/SOURCE-MAP.json").read_bytes())
    for item in context:
        raw = (r / "context" / Path(item["path"]).name).read_bytes()
        assert identity(raw) == {k: item[k] for k in ("bytes", "git_blob", "sha256")}
        assert item["bound_tree"] == base["sha"] and item["git_blob"] == leaves[item["path"]]["sha"]
    lib = (r / "context/lib.rs").read_text()
    process = (r / "context/process.rs").read_text()
    io = (a / "candidate/codex-rs/utils/pty/src/unix_io.rs").read_text()
    diag = (a / "candidate/codex-rs/utils/pty/src/unix_io_diagnostics.rs").read_text()
    assert '#[cfg(unix)]\nmod unix_io;' in lib
    assert '#[cfg(test)]\n#[path = "unix_io_diagnostics.rs"]\nmod diagnostics;' in io
    assert '#[cfg(all(test, unix))]\n    pub(crate) fn pty_io_diagnostic_snapshot' in process
    assert '#[cfg(test)]\n        let writer_diagnostics = Arc::clone(&diagnostics);' in io
    assert '#[cfg(test)] diagnostics: &PtyIoDiagnostics' in io
    assert 'fd: Weak<AsyncFd<File>>' in diag and 'Arc<AsyncFd<File>>' not in diag
    assert diag.count('writer_diagnostics') == 0
    assert observed["test_source"]["complete_original_token_sequence_equal_after_erasing_only_four_logs_and_two_error_inspections"]
    assert observed["io_source"]["reader_task_full_bytes_equal"]
    primary = json.loads((r / "primary/rust-clippy-1.95.0-needless-else.original.json").read_bytes())
    assert not primary.get("isError")
    text = primary["structuredContent"]["content"]
    assert 'Ignore else blocks that contain comments or #[cfg]s' in text
    assert "!src.contains(['/', '#'])" in text
    print(json.dumps({"decision": "ACCEPT_AS_TEST_OBSERVATION_CANDIDATE_ONLY", "base_head": freeze["base_head"], "base_tree": base["sha"], "actual_candidate_tree": new[""], "freeze": identity((a / "FREEZE.json").read_bytes()), "frozen_files": 23, "frozen_bytes": 5117370, "full_tree_leaves": len(leaves), "unchanged_leaves": 10799, "changed_paths": observed["changed_paths"], "actual_three_source_GET_full_bytes_equal": True, "fresh_root_full_GET_53_entries_equal": True, "independent_recorded_replay_stdout": identity((r / "replay-01.stdout.json").read_bytes()), "replay_matches_all_three_author_products": True, "context_sources_bound_to_base": context, "qualification": "Source and lexical/offline checks only; no Rust parsing/typecheck/codegen equivalence, formatter/Clippy run or native Intel success. Relaxed observations do not establish root cause or B21 closure."}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
