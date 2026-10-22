"""Fail-closed source/lock provenance for the one-branch a32 diagnostic."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tomllib
import tempfile

from a32_sshsig_source_bytes import check_full_bytes

BASE = "a32d73f00cfc292ff1ed4ac5cef958ca9f238020"
MANIFEST = ".github/fixtures/a32-sshsig-qualification/source-manifest.json"
LOCKS = ("codex-rs/Cargo.lock", "MODULE.bazel.lock")
PACKAGES = ("codex-utils-path", "codex-state", "codex-hepta-memory", "codex-hepta-operator-acceptance")
MEMORY_CASES = (
    "exact_current_cut_recovers_writable_generation_and_persists_activation",
    "post_rename_publication_failure_is_indeterminate_and_retains_candidate",
    "predecessor_witness_is_rejected_and_current_witness_recovers",
    "revoked_owner_profile_and_witness_checks_precede_recovery_admission",
    "writable_recovery_requires_exclusive_store_fence",
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def git(root, *args, data=None, env=None):
    return subprocess.check_output(["git", "--no-replace-objects", *args], cwd=root, input=data, env=env)


def names(raw):
    return {part.decode() for part in raw.split(b"\0") if part}


def check_index_flags(root):
    # -v exposes assume-unchanged; -f also exposes fsmonitor-valid. S is
    # skip-worktree. Reject the flags themselves, even when bytes are clean.
    entries = git(root, "ls-files", "-v", "-f", "-z").split(b"\0")
    hidden = [entry.decode(errors="replace") for entry in entries if entry and not entry.startswith(b"H ")]
    require(not hidden, f"hidden or nonordinary index flags are forbidden: {hidden}")


def check_worktree_bytes(root, reference="HEAD", exclude=()):
    commit = git(root, "rev-parse", reference).decode().strip()
    tree = git(root, "rev-parse", reference + "^{tree}").decode().strip()
    return check_full_bytes(root, commit, tree, exclude)


def check_clean(root):
    check_index_flags(root)
    check_worktree_bytes(root)
    require(not git(root, "status", "--porcelain", "--untracked-files=all"),
            "tracked/index/untracked source changes are forbidden")


def check_delta(root, original, allowed):
    check_index_flags(root)
    check_worktree_bytes(root, original, exclude=allowed)
    require(not git(root, "diff", "--cached", "--name-only"), "unexpected staged change")
    require(not git(root, "ls-files", "--others", "--exclude-standard"), "unexpected untracked file")
    changed = names(git(root, "diff", "--name-only", "-z", original))
    require(changed <= set(allowed), f"unexpected source changes: {sorted(changed)}")
    git(root, "diff", "--check", original)
    return sorted(changed)


def verify_input(root, source_sha, branch):
    require(git(root, "rev-parse", "HEAD").decode().strip() == source_sha, "wrong input HEAD")
    check_index_flags(root)
    manifest = json.loads(git(root, "show", f"{source_sha}:{MANIFEST}"))
    require(manifest.get("schema") == "a32.sshsig-qualification-source.v1", "wrong frozen manifest schema")
    require(manifest.get("status") == "frozen-for-native-review", "proposal manifest is not executable")
    require(manifest["base"] == BASE, "manifest must bind exact a32 base")
    require(branch == manifest["branch"], "wrong diagnostic branch")
    parents = git(root, "rev-list", "--parents", "-n", "1", source_sha).decode().split()
    require(parents == [source_sha, manifest["base"]], "input must have only the exact a32 parent")
    require(git(root, "rev-parse", manifest["base"] + "^{tree}").decode().strip()
            == manifest["base_tree"], "wrong a32 tree")
    source_paths = {f["path"] for f in manifest["files"]}
    auxiliary_paths = set(manifest["auxiliary_paths"])
    require(len(source_paths) == len(manifest["files"]) and len(auxiliary_paths) == len(manifest["auxiliary_paths"])
            and not source_paths.intersection(auxiliary_paths) and MANIFEST in auxiliary_paths,
            "duplicate/overlapping/incomplete source identities")
    require(len(manifest["auxiliary_files"]) == len(auxiliary_paths) - 1, "duplicate auxiliary hash identity")
    expected = source_paths | auxiliary_paths
    actual = names(git(root, "diff", "--name-only", "-z", manifest["base"], source_sha))
    require(actual == expected, f"input changed-file allowlist mismatch: {actual ^ expected}")
    for item in manifest["files"]:
        path = item["path"]
        base = git(root, "ls-tree", manifest["base"], "--", path).decode().strip()
        require((base.split()[2] if base else None) == item["base_blob"], f"wrong preimage {path}")
        mode = base.split()[0] if base else "100644"
        current = git(root, "ls-tree", source_sha, "--", path).decode().split()
        require(current[:2] == [mode, "blob"], f"wrong mode/type {path}")
        data = git(root, "show", f"{source_sha}:{path}")
        require(blob(data) == item["candidate_blob"], f"wrong postimage {path}")
        require(digest(data) == item["candidate_sha256"], f"wrong digest {path}")
        require((root / path).read_bytes() == data, f"noncanonical reviewed worktree bytes: {path}")
    for path in manifest["auxiliary_paths"]:
        require(not git(root, "ls-tree", manifest["base"], "--", path), f"auxiliary overwrites a32: {path}")
        require(git(root, "ls-tree", source_sha, "--", path).decode().split()[:2]
                == ["100644", "blob"], f"wrong auxiliary mode/type {path}")
    for item in manifest["auxiliary_files"]:
        require(item["path"] in manifest["auxiliary_paths"] and item["path"] != MANIFEST,
                "bad auxiliary digest identity")
        require(digest(git(root, "show", f"{source_sha}:{item['path']}")) == item["sha256"],
                "auxiliary source differs from frozen hash")
    require({x["path"] for x in manifest["auxiliary_files"]} == set(manifest["auxiliary_paths"]) - {MANIFEST},
            "auxiliary digest set incomplete")
    # Reconstruct only the product tree without self-referential manifest hashing.
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(folder) / "index"))
        git(root, "read-tree", source_sha, env=env)
        git(root, "update-index", "--force-remove", "--", *manifest["auxiliary_paths"], env=env)
        product = git(root, "write-tree", env=env).decode().strip()
    require(product == manifest["expected_product_tree"], "wrong full product tree")
    check_clean(root)
    return manifest


def cargo_delta(before_bytes, after_bytes):
    """Only the new acceptance consumer edges; Memory edges already in input."""
    before = tomllib.loads(before_bytes.decode())
    after = tomllib.loads(after_bytes.decode())
    old_packages, new_packages = before.pop("package"), after.pop("package")
    require(before == after, "Cargo lock header/metadata changed")
    key = lambda p: (p["name"], p["version"], p.get("source", ""))
    old = {key(p): p for p in old_packages}; new = {key(p): p for p in new_packages}
    require(len(old) == len(old_packages) and len(new) == len(new_packages), "duplicate lock package")
    require(old.keys() == new.keys(), "package/version/source set changed")
    additions = {"codex-utils-path", "windows-sys 0.52.0"}
    changed = []
    for identity, original in old.items():
        wanted = dict(original)
        if identity[0] == "codex-hepta-operator-acceptance" and not identity[2]:
            deps = wanted.get("dependencies", [])
            require(not additions.intersection(deps), "expected new acceptance edges already present")
            wanted["dependencies"] = sorted([*deps, *additions]); changed.append(identity[0])
        require(new[identity] == wanted, f"unexpected lock identity/checksum/edge delta: {identity}")
    require(changed == ["codex-hepta-operator-acceptance"], "missing sole acceptance consumer")
    return sorted(additions)


def local_candidate(root, source_sha):
    """Local detached commit only: preserve existing clean-worktree control oracles."""
    changed = check_delta(root, source_sha, LOCKS)
    require("codex-rs/Cargo.lock" in changed, "real Cargo resolution did not add acceptance edges")
    git(root, "add", "--", *LOCKS)
    check_index_flags(root)
    staged = names(git(root, "diff", "--cached", "--name-only", "-z"))
    require(staged == set(changed), "unexpected index delta before local candidate")
    tree = git(root, "write-tree").decode().strip()
    timestamp = git(root, "show", "-s", "--format=%ct", source_sha).decode().strip()
    env = dict(os.environ)
    env.update(GIT_AUTHOR_NAME="a32 SSHSIG diagnostic (local only)",
               GIT_COMMITTER_NAME="a32 SSHSIG diagnostic (local only)",
               GIT_AUTHOR_EMAIL="a32-diagnostic@invalid", GIT_COMMITTER_EMAIL="a32-diagnostic@invalid",
               GIT_AUTHOR_DATE=f"@{timestamp} +0000", GIT_COMMITTER_DATE=f"@{timestamp} +0000")
    commit = git(root, "commit-tree", tree, "-p", source_sha, env=env,
                 data=b"Local-only genuine SSHSIG resolver locks; never publish automatically\n").decode().strip()
    git(root, "checkout", "--detach", commit)
    check_clean(root)
    require(names(git(root, "diff", "--name-only", "-z", source_sha, commit)) == set(changed),
            "generated candidate contains non-lock change")
    return {"commit": commit, "tree": tree, "changed_paths": changed,
            "input_head_qualified": False, "published": False}


def inventory(directory, exclude=()):
    return {p.relative_to(directory).as_posix(): {"bytes": p.stat().st_size,
            "sha256": digest(p.read_bytes())} for p in sorted(directory.rglob("*"))
            if p.is_file() and p.relative_to(directory).as_posix() not in exclude}


def verify_bundle(directory, identity, expected_manifest_sha256=None):
    require(not any(p.is_symlink() for p in directory.rglob("*")), "bundle symlink forbidden")
    manifest_bytes = (directory / "manifest.json").read_bytes()
    if expected_manifest_sha256 is not None:
        require(digest(manifest_bytes) == expected_manifest_sha256, "bundle differs from resolver step output")
    files = inventory(directory, ("manifest.json",))
    require(set(files) == set(LOCKS), "bundle files are not exactly the two generated locks")
    manifest = json.loads(manifest_bytes)
    require(manifest["identity"] == identity, "bundle is not from this source/run/attempt")
    require(manifest["files"] == files, "bundle hash/length mismatch")
    require(manifest["resolver_gates_passed"] is True, "resolver gates did not pass")
    return manifest


def verify_pass_cases(output, cases):
    import re
    # Fail closed on missing, skipped or failed case; never accept a test listing.
    for case in cases:
        require(re.search(r"(?m)^\s*PASS\b[^\n]*::" + re.escape(case) + r"\s*$", output),
                f"required native PASS observation missing: {case}")
