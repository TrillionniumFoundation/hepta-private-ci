#!/usr/bin/env python3
"""Offline proof of exactly three added parameter comments; no Rust/CI run."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from static_helpers import identity, merkle


PRODUCTION = "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs"
TESTS = "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file_tests.rs"
OLD_TREE = "7c18622c5c1b69826f7103dd2b2fec5bf572ae3a"
NEW_TREE = "605720504e547296dca1c78914fee5ed6d29844d"
CHANGES = [
    ("owner(store, None)", "owner(store, /*minimum*/ None)"),
    ('recover(file, digest("binding"), None)', 'recover(file, digest("binding"), /*minimum*/ None)'),
    ('recover(temp.open(), digest("binding"), None)', 'recover(temp.open(), digest("binding"), /*minimum*/ None)'),
]


def read_json(path):
    return json.loads(path.read_bytes())


def original_body(path):
    value = read_json(path)
    assert not value.get("isError")
    return value["structuredContent"]["content"]


def verify_patch(root, patch, old_files):
    with tempfile.TemporaryDirectory(prefix="holdout-v2-patch-") as temporary:
        temporary = Path(temporary)
        for path, data in old_files.items():
            p = temporary / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        for flags, expected in [([], None), (["--reverse"], old_files)]:
            run = subprocess.run(["git", "apply", *flags, str(root / patch)], cwd=temporary, capture_output=True)
            assert run.returncode == 0 and run.stderr == b"", run.stderr
            for path in old_files:
                data = (root / "candidate" / path).read_bytes() if expected is None else expected[path]
                assert (temporary / path).read_bytes() == data


def main(root, source_archive):
    v1 = root / "v1"
    freeze_data = (v1 / "freeze-manifest.json").read_bytes()
    assert identity(freeze_data)["git_blob"] == "b86d33c1f8f550decc9f15020142880dcf2f9bb7"
    freeze = json.loads(freeze_data)
    assert len(freeze["files"]) == freeze["members"] == 108
    for entry in freeze["files"]:
        assert identity((v1 / entry["path"]).read_bytes()) == {k: entry[k] for k in ["bytes", "git_blob", "sha256"]}
    old_registry = (root / "v1-registration/registry.actual.json").read_bytes()
    assert identity(old_registry)["git_blob"] == "6b1f56cdb8a80535a916a7ed23e09d1bd5108824"
    assert original_body(root / "v1-registration/registry.full-GET.original.json").encode() == old_registry
    argv = [sys.executable, str(v1 / "verify_candidate.py"), str(v1)]
    if source_archive is not None:
        argv += ["--source-archive", str(source_archive)]
    old_replay = subprocess.run(argv, cwd=v1, capture_output=True)
    assert old_replay.returncode == 0 and old_replay.stderr == b"", old_replay.stderr
    assert old_replay.stdout == (v1 / "static-final.stdout.json").read_bytes()

    production = (root / "candidate" / PRODUCTION).read_bytes()
    assert production == (v1 / "candidate" / PRODUCTION).read_bytes()
    assert identity(production)["git_blob"] == "603d36b01f6f8fe7472c72588e793f8ef169a08b"
    old = (v1 / "candidate" / TESTS).read_bytes()
    new = (root / "candidate" / TESTS).read_bytes()
    base = (v1 / "source" / TESTS).read_bytes()
    assert len(base) == 10243 and old.startswith(base) and new.startswith(base)
    assert identity(old)["git_blob"] == "2c451a3c110288ca06eb43724329c48c39bb8f1e"
    assert identity(new)["git_blob"] == "c71e4a086dd33514d72bf7acb15d1c7e0f621636"
    tail = old[len(base):].decode()
    for before, after in CHANGES:
        assert tail.count(before) == 1
        tail = tail.replace(before, after, 1)
    assert base + tail.encode() == new
    assert tail.count("/*minimum*/ None") == tail.count("None") == 3
    assert tail.replace("/*minimum*/ ", "") == old[len(base):].decode()
    assert len(new) - len(old) == 36
    assert "minimum: Option<FinalHoldoutCasAnchorV1>" in base.decode()
    assert "minimum: Option<FinalHoldoutCasAnchorV1>" in production.decode()
    assert sorted(str(p.relative_to(root / "candidate")) for p in (root / "candidate").rglob("*") if p.is_file()) == sorted([PRODUCTION, TESTS])

    expected_delta = "".join(difflib.unified_diff(old.decode().splitlines(keepends=True), new.decode().splitlines(keepends=True), fromfile="a/" + TESTS, tofile="b/" + TESTS))
    assert expected_delta == (root / "v1-to-v2.patch").read_text()
    expected_full = ""
    for path in [PRODUCTION, TESTS]:
        a = (v1 / "source" / path).read_text()
        b = (root / "candidate" / path).read_text()
        expected_full += "".join(difflib.unified_diff(a.splitlines(keepends=True), b.splitlines(keepends=True), fromfile="a/" + path, tofile="b/" + path))
    assert expected_full == (root / "full.patch").read_text()
    verify_patch(root, "v1-to-v2.patch", {TESTS: old})
    verify_patch(root, "full.patch", {path: (v1 / "source" / path).read_bytes() for path in [PRODUCTION, TESTS]})

    base_tree = read_json(v1 / "authority/main67-full-tree.json")
    base_leaves = {x["path"]: x for x in base_tree["tree"] if x["type"] != "tree"}
    old_leaves = {p: dict(v) for p, v in base_leaves.items()}
    old_leaves[PRODUCTION]["sha"] = identity(production)["git_blob"]
    old_leaves[TESTS]["sha"] = identity(old)["git_blob"]
    assert merkle(old_leaves)[0] == OLD_TREE
    new_leaves = {p: dict(v) for p, v in old_leaves.items()}
    new_leaves[TESTS]["sha"] = identity(new)["git_blob"]
    assert merkle(new_leaves)[0] == NEW_TREE
    assert [p for p in new_leaves if new_leaves[p] != old_leaves[p]] == [TESTS]
    assert len(new_leaves) == 10582

    created = read_json(root / "authority/candidate-tree.create.original.json")
    assert not created.get("isError") and created["structuredContent"]["sha"] == NEW_TREE
    actual_tree = json.loads(original_body(root / "authority/candidate-tree.full-GET.original.json"))
    assert actual_tree["sha"] == NEW_TREE and not actual_tree["truncated"]
    ordered = sorted(actual_tree["tree"], key=lambda x: (x["path"] + ("/" if x["type"] == "tree" else "")).encode())
    raw = b"".join(("40000" if x["type"] == "tree" else x["mode"]).encode() + b" " + x["path"].encode() + b"\0" + bytes.fromhex(x["sha"]) for x in ordered)
    assert hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == NEW_TREE
    assert original_body(root / "authority/candidate-tests.full-GET.original.json").encode() == new

    review = (root / "review-input/REVIEW.md").read_bytes()
    assert identity(review)["git_blob"] == "103b7adedab463bc4b63fee4ccded5722644d1bf"
    assert original_body(root / "review-input/REVIEW.full-GET.original.json").encode() == review
    lint_files = []
    for p in sorted((root / "review-input/lint-source").rglob("*")):
        if p.is_file():
            path = str(p.relative_to(root / "review-input/lint-source"))
            assert identity(p.read_bytes())["git_blob"] == base_leaves[path]["sha"]
            lint_files.append(path)
    aspect = (root / "review-input/lint-source/tools/argument-comment-lint/lint_aspect.bzl").read_text()
    assert "-Duncommented-anonymous-literal-argument" in aspect
    transition = read_json(root / "old-to-new.identity.json")
    assert transition["new_test"] == identity(new) and transition["old_test"] == identity(old)
    assert transition["production_unchanged"] == identity(production)
    assert transition["new_full_tree_computed"] == NEW_TREE

    return {
        "decision": "NARROW_COMMENT_REVISION_READY_FOR_REVIEW",
        "old_frozen_members_unchanged": 109,
        "old_registry": identity(old_registry),
        "old_static_replay": {"exit_code": 0, "stdout": identity(old_replay.stdout), "stderr_bytes": 0},
        "production_unchanged": identity(production),
        "old_test": identity(old),
        "new_test_actual_full_GET": identity(new),
        "comments_added": 3,
        "bytes_added": 36,
        "original_test_prefix_bytes_unchanged": 10243,
        "all_assertions_and_noncomment_bytes_unchanged": True,
        "both_patches_forward_reverse_exact": True,
        "old_tree": OLD_TREE,
        "new_tree_actual_create_full_root_GET": NEW_TREE,
        "leaves_unchanged_from_v1": 10581,
        "leaves_unchanged_from_main67": 10580,
        "review_input_actual_full_GET": identity(review),
        "fixed_lint_source_files_verified": lint_files,
        "original_Mac_cause_proven": False,
        "Rust_project_tests_argument_lint_formatter_executed": False,
        "new_OS_mechanism_execution": False,
        "refs_PR_CI_mutated": False,
        "independent_v2_review": "PENDING; v1 review is not automatic v2 acceptance",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--source-archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(main(args.root.resolve(), args.source_archive), indent=2, sort_keys=True))
