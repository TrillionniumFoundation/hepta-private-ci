#!/usr/bin/env python3
"""Build a review artifact with actual Cargo/Bazel locks; never commit or update a ref."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import traceback
import urllib.request

from pin_utils_proposal_evidence import ProposalError, collect, identity, require
from pin_utils_lock_guards import module_guard, verify_external_source

HERE = Path(__file__).resolve().parent
SPEC = json.loads((HERE / "pin-utils-backport-spec.json").read_bytes())
ADDITIONS = {
    ".github/workflows/hepta-pin-utils-backport-proposal.yml",
    ".github/scripts/propose_pin_utils_backport.py",
    ".github/scripts/pin_utils_proposal_evidence.py",
    ".github/scripts/pin-utils-backport-spec.json",
    ".github/scripts/pin_utils_lock_guards.py",
}
CHANGED = {"codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "MODULE.bazel.lock"}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def git(root, *args, env=None):
    return subprocess.run(["git", *args], cwd=root, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout


def tree_hash(leaves):
    root = {}
    for path, (mode, sha) in leaves.items():
        node = root
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (mode, sha)

    def tree(node):
        entries = []
        for name, value in node.items():
            directory = isinstance(value, dict)
            mode, sha = ("40000", tree(value)) if directory else value
            entries.append(((name + ("/" if directory else "")).encode(), mode.encode() + b" "
                            + name.encode() + b"\0" + bytes.fromhex(sha)))
        raw = b"".join(value for _, value in sorted(entries))
        return hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    return tree(root)


def source_guard(root):
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())["pull_request"]
    head = git(root, "rev-parse", "HEAD").decode().strip()
    require(os.environ.get("GITHUB_EVENT_NAME") == "pull_request", "WRONG_EVENT")
    require(event["head"]["repo"]["full_name"] == event["base"]["repo"]["full_name"]
            == "TrillionniumFoundation/hepta-private-ci", "WRONG_REPOSITORY")
    require(event["base"]["sha"] == SPEC["base_head"] and event["base"]["ref"] == SPEC["base_ref"],
            "BASE_MOVED")
    require(head == event["head"]["sha"] == os.environ["CANDIDATE_SHA"], "HEAD_MISMATCH")
    require(git(root, "show", "-s", "--format=%P", "HEAD").decode().strip() == SPEC["base_head"],
            "PARENT_MISMATCH")
    require(not git(root, "status", "--porcelain=v1", "--untracked-files=all"), "DIRTY_INITIAL_SOURCE")
    leaves = {}
    for row in git(root, "ls-tree", "-rz", "--full-tree", "HEAD").split(b"\0"):
        if row:
            metadata, path = row.split(b"\t", 1)
            mode, kind, sha = metadata.decode().split()
            require(kind == "blob", "UNEXPECTED_GITLINK")
            leaves[path.decode()] = (mode, sha)
    require(ADDITIONS <= leaves.keys(), "MISSING_PROPOSAL_FILES")
    original = {p: v for p, v in leaves.items() if p not in ADDITIONS}
    require(len(original) == SPEC["original_product_leaves"] and tree_hash(original) == SPEC["base_tree"],
            "ORIGINAL_PRODUCT_TREE_CHANGED")
    require(all(original[p][1] == sha for p, sha in SPEC["baseline_blobs"].items()), "PIN_MISMATCH")
    require(all(leaves[p][0] == "100644" for p in ADDITIONS), "PROPOSAL_MODE_MISMATCH")
    return {"head": head, "tree": tree_hash(leaves), "base": SPEC["base_head"],
            "base_tree": SPEC["base_tree"], "original_leaves_unchanged": len(original),
            "added_paths": sorted(ADDITIONS), "clean": True}


def private_dir():
    path = Path(os.environ["PRIVATE_EVIDENCE_DIR"])
    require(not path.is_symlink() and path.name.startswith("pin-utils-proposal.")
            and path.parent.resolve(strict=True) == Path(os.environ["RUNNER_TEMP"]).resolve(strict=True),
            "INVALID_PRIVATE_DIRECTORY")
    return path.resolve(strict=True)


def unpack_and_patch(crate, raw, root):
    require(len(raw) == crate["archive_bytes"] and identity(raw)["sha256"] == crate["checksum"],
            "ARCHIVE_CHECKSUM_MISMATCH")
    expected = {}
    directory = crate["name"] + "-" + crate["version"]
    edits = {x["path"]: x for x in crate["edits"]}
    originals = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            require(not member.name.startswith("/") and "\\" not in member.name and ".." not in parts
                    and parts and parts[0] == directory and len(parts) > 1, "UNSAFE_ARCHIVE_PATH")
            require(member.isfile() and member.size <= 16 * 1024 * 1024, "NON_REGULAR_ARCHIVE_MEMBER")
            relative = "/".join(parts[1:])
            require(member.name == directory + "/" + relative, "NON_CANONICAL_ARCHIVE_PATH")
            require(relative not in originals, "DUPLICATE_ARCHIVE_MEMBER")
            data = archive.extractfile(member).read()
            require(len(data) == member.size, "TRUNCATED_ARCHIVE_MEMBER")
            originals[relative] = data
            if relative in edits:
                edit = edits[relative]
                require(identity(data)["sha256"] == edit["before_sha256"], "PATCH_PREIMAGE_MISMATCH")
                for old, new, count in edit["replace"]:
                    require(data.count(old.encode()) == count, "PATCH_OCCURRENCE_MISMATCH")
                    data = data.replace(old.encode(), new.encode())
                require(identity(data)["sha256"] == edit["after_sha256"], "PATCH_POSTIMAGE_MISMATCH")
            path = crate["vendor"] + "/" + relative
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(data)
            mode = 0o755 if member.mode & 0o111 else 0o644
            target.chmod(mode)
            expected[path] = {**identity(data), "mode": "100755" if mode == 0o755 else "100644"}
    require(len(originals) == crate["archive_regular_files"] and edits.keys() <= originals.keys(),
            "ARCHIVE_ROSTER_MISMATCH")
    for name, digest in crate["licenses"].items():
        require(identity(originals[name]) == digest and (root / crate["vendor"] / name).read_bytes() == originals[name],
                "LICENSE_CHANGED")
    for filename in ("Cargo.toml", "Cargo.toml.orig"):
        before = tomllib.loads(originals[filename].decode())
        after = tomllib.loads((root / crate["vendor"] / filename).read_text())
        before["dependencies"].pop("pin-utils")
        if crate["name"] == "loom":
            before["features"]["pin-utils"] = []
            before["package"]["rust-version"] = "1.68"
        if crate["name"] == "hyper":
            before["features"]["http1"].remove("dep:pin-utils")
        require(before == after, "UNEXPECTED_MANIFEST_DRIFT")
    note = ("# Hepta private pin-utils backport\n\n" + crate["source_scope"] + "\n\n"
            "The official archive checksum and exact edits are recorded in HEPTA-PATCH-PROVENANCE.json. "
            "Cargo.toml and Cargo.toml.orig carry the same dependency/feature change. "
            "All other archive files, including the license and any historical vendored Cargo.lock, are preserved. "
            "The workspace Cargo.lock is the dependency authority. No crate version is advanced.\n")
    provenance = {"schema": "hepta-private-pin-backport-v1", "crate": crate, "upstream": SPEC["upstream"]}
    for filename, data in [("HEPTA-PATCHES.md", note.encode()),
                           ("HEPTA-PATCH-PROVENANCE.json", (json.dumps(provenance, indent=2) + "\n").encode())]:
        target = root / crate["vendor"] / filename
        with target.open("xb") as output:
            output.write(data)
        target.chmod(0o644)
        expected[target.relative_to(root).as_posix()] = {**identity(data), "mode": "100644"}
    return expected


def graph_guard(before_raw, after_raw):
    before, after = (tomllib.loads(b.decode()) for b in (before_raw, after_raw))
    expected = copy.deepcopy(before)
    require([p for p in expected["package"] if p["name"] == "pin-utils"] == [SPEC["pin_utils"]],
            "PIN_UTILS_IDENTITY_MISMATCH")
    expected["package"].remove(SPEC["pin_utils"])
    names = {c["name"]: c for c in SPEC["crates"]}
    removed = []
    for package in expected["package"]:
        if package["name"] in names:
            crate = names[package["name"]]
            require(package["version"] == crate["version"] and package["checksum"] == crate["checksum"]
                    and package["source"] == "registry+https://github.com/rust-lang/crates.io-index",
                    "ORIGINAL_CRATE_IDENTITY_MISMATCH")
            package.pop("source")
            package.pop("checksum")
            require(package["dependencies"].count("pin-utils") == 1, "PIN_UTILS_EDGE_MISMATCH")
            package["dependencies"].remove("pin-utils")
            removed.append(package["name"])
    require(set(removed) == set(names) and len(removed) == 5, "CRATE_ROSTER_MISMATCH")
    def canonical(lock):
        result = copy.deepcopy(lock)
        for package in result["package"]:
            if "dependencies" in package:
                package["dependencies"].sort()
        result["package"].sort(key=lambda p: (p["name"], p["version"], p.get("source", "")))
        return result
    require(canonical(after) == canonical(expected), "UNEXPECTED_LOCK_GRAPH_DRIFT")
    return {"original_packages": len(before["package"]), "after_packages": len(after["package"]),
            "only_five_path_source_changes_and_five_removed_edges": sorted(removed),
            "all_other_package_fields_and_dependency_IDs_identical": True,
            "all_top_level_lock_fields_identical": True}


def workspace_patch(before):
    text = before.decode()
    require(text.count("[patch.crates-io]\n") == 1 and text.startswith("[workspace]\n"), "WORKSPACE_PREIMAGE")
    paths = [c["vendor"].removeprefix("codex-rs/") for c in SPEC["crates"]]
    additions = "# Pin-only private backports; retain the five existing crate versions.\n" + "".join(
        c["name"] + ' = { path = "' + p + '" }\n' for c, p in zip(SPEC["crates"], paths))
    text = text.replace("[patch.crates-io]\n", "[patch.crates-io]\n" + additions, 1)
    expected = tomllib.loads(before.decode())
    excludes = expected["workspace"]["exclude"]
    require(excludes == ["third_party/aws-config-1.8.12"], "ORIGINAL_EXCLUDES_MISMATCH")
    old_line = "exclude = " + json.dumps(excludes) + "\n"
    require(text.count(old_line) == 1 and not set(excludes).intersection(paths), "EXCLUDE_PREIMAGE_MISMATCH")
    text = text.replace(old_line, "exclude = " + json.dumps(excludes + paths) + "\n", 1)
    expected["workspace"]["exclude"] = excludes + paths
    for c, p in zip(SPEC["crates"], paths):
        require(c["name"] not in expected["patch"]["crates-io"], "EXISTING_PATCH_WOULD_BE_REPLACED")
        expected["patch"]["crates-io"][c["name"]] = {"path": p}
    require(tomllib.loads(text) == expected, "WORKSPACE_PATCH_DRIFT")
    return text.encode()


class CommandFailed(ProposalError):
    def __init__(self, code):
        self.code = code
        super().__init__("ORIGINAL_COMMAND_FAILED")


def generate(root, private):
    payload = private / "payload"
    commands = []
    result = {"schema": "pin-utils-lock-proposal-result-v1", "proposal_validated": False,
              "automatic_commit_or_ref_update": False, "command_exits": commands}
    before_source = source_guard(root)
    require(before_source == json.loads((payload / "source-before.json").read_bytes()), "SOURCE_CHANGED")
    def run(label, argv, cwd=root, must_succeed=True, env=None, separate_stderr=False):
        logfile = payload / "logs" / (label + ".log")
        logfile.parent.mkdir(parents=True, exist_ok=True)
        with logfile.open("xb") as stream:
            if separate_stderr:
                with (payload / "logs" / (label + ".stderr.log")).open("xb") as stderr:
                    proc = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                          stdout=stream, stderr=stderr, check=False)
            else:
                proc = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=stream,
                                      stderr=subprocess.STDOUT, check=False)
        commands.append({"stage": label, "argv": argv, "cwd": str(cwd.relative_to(root)) or ".",
                         "exit_code": proc.returncode})
        write_json(payload / "result.json", result)
        print(json.dumps({"stage": label, "exit_code": proc.returncode}), flush=True)
        if must_succeed and proc.returncode:
            raise CommandFailed(proc.returncode if 0 < proc.returncode < 256 else 1)
        return logfile.read_bytes()
    try:
        for name, argv, expected in [
            ("cargo-version", ["cargo", "+1.96.0", "--version"], [b"cargo", b"1.96.0"]),
            ("rustc-version", ["rustc", "+1.96.0", "--version"], [b"rustc", b"1.96.0"]),
            ("deny-version", ["cargo", "+1.96.0", "deny", "--version"], [b"cargo-deny", b"0.19.0"]),
            ("just-version", ["just", "--version"], [b"just", b"1.51.0"]),
            ("bazel-version", ["bazel", "--version"], [b"bazel", b"9.0.0"]),
        ]:
            require(run(name, argv, separate_stderr=True).strip().split()[:2] == expected, "TOOLCHAIN_VERSION_MISMATCH")
        metadata_argv = ["cargo", "+1.96.0", "metadata", "--locked", "--no-deps", "--format-version", "1"]
        before_members = json.loads(run("workspace-before", metadata_argv, root / "codex-rs", separate_stderr=True))["workspace_members"]
        old_lock = (root / "codex-rs/Cargo.lock").read_bytes()
        for name in CHANGED:
            target = payload / "before" / Path(name).name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((root / name).read_bytes())
        run("baseline-bazel-lock-check", ["./scripts/check-module-bazel-lock.sh"], must_succeed=False)
        expected_files = {}
        receipts = []
        for crate in SPEC["crates"]:
            require(not (root / crate["vendor"]).exists(), "VENDOR_DESTINATION_EXISTS")
            with urllib.request.urlopen(crate["url"], timeout=60) as response:
                require(response.status == 200 and response.geturl() == crate["url"], "UNEXPECTED_ARCHIVE_RESPONSE")
                raw = response.read(crate["archive_bytes"] + 1)
                receipt = {"url": crate["url"], "status": response.status, "final_url": response.geturl(),
                           "headers": {k: response.headers[k] for k in ("Content-Type", "Content-Length", "ETag", "Last-Modified", "Date") if k in response.headers}}
            expected_files.update(unpack_and_patch(crate, raw, root))
            archive = payload / "archives" / (crate["name"] + "-" + crate["version"] + ".crate")
            archive.parent.mkdir(exist_ok=True)
            archive.write_bytes(raw)
            receipts.append({**receipt, "actual": identity(raw), "original_Cargo_lock_checksum": crate["checksum"]})
            write_json(payload / "archive-receipts.json", receipts)
        manifest = root / "codex-rs/Cargo.toml"
        new_manifest = workspace_patch(manifest.read_bytes())
        manifest.write_bytes(new_manifest)
        cargo = ["cargo", "+1.96.0", "update", "--workspace"]
        run("cargo-lock-update", cargo, root / "codex-rs")
        new_lock = (root / "codex-rs/Cargo.lock").read_bytes()
        write_json(payload / "lock-graph-proof.json", graph_guard(old_lock, new_lock))
        run("cargo-lock-repeat", cargo, root / "codex-rs")
        require((root / "codex-rs/Cargo.lock").read_bytes() == new_lock, "CARGO_LOCK_NOT_REPEATABLE")
        after_members = json.loads(run("workspace-after", metadata_argv, root / "codex-rs", separate_stderr=True))["workspace_members"]
        require(before_members == after_members, "WORKSPACE_MEMBERS_CHANGED")
        run("bazel-lock-update", ["just", "bazel-lock-update"])
        run("bazel-lock-check", ["./scripts/check-module-bazel-lock.sh"])
        module_lock = (root / "MODULE.bazel.lock").read_bytes()
        module_proof = module_guard((payload / "before/MODULE.bazel.lock").read_bytes(), module_lock, SPEC)
        module_proof["verified_external_source"] = verify_external_source(SPEC)
        write_json(payload / "module-lock-proof.json", module_proof)
        run("bazel-lock-repeat", ["just", "bazel-lock-update"])
        run("bazel-lock-check-repeat", ["./scripts/check-module-bazel-lock.sh"])
        require((root / "MODULE.bazel.lock").read_bytes() == module_lock, "BAZEL_LOCK_NOT_REPEATABLE")
        run("cargo-deny-original", ["cargo-deny", "--log-level", "warn", "--manifest-path", "./codex-rs/Cargo.toml", "--all-features", "check"])
        require((root / "codex-rs/Cargo.lock").read_bytes() == new_lock, "CARGO_LOCK_CHANGED_AFTER_CHECKS")
        require((root / "MODULE.bazel.lock").read_bytes() == module_lock, "MODULE_LOCK_CHANGED_AFTER_CHECKS")
        require(manifest.read_bytes() == new_manifest, "WORKSPACE_MANIFEST_CHANGED_AFTER_PATCH")
        require(git(root, "rev-parse", "HEAD").decode().strip() == before_source["head"], "HEAD_CHANGED")
        changed = {p.decode() for p in git(root, "diff", "--name-only", "-z", "HEAD").split(b"\0") if p}
        require(changed <= CHANGED, "UNEXPECTED_TRACKED_CHANGE")
        untracked = {p.decode() for p in git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if p}
        require(untracked <= expected_files.keys(), "UNEXPECTED_UNTRACKED_FILE")
        for crate in SPEC["crates"]:
            entries = list((root / crate["vendor"]).rglob("*"))
            require(all(not p.is_symlink() for p in entries), "VENDOR_SYMLINK_ADDED")
            actual = {p.relative_to(root).as_posix() for p in entries if not p.is_dir()}
            require(actual == {p for p in expected_files if p.startswith(crate["vendor"] + "/")}, "VENDOR_ROSTER_CHANGED")
        for name, expected in expected_files.items():
            path = root / name
            require(not path.is_symlink() and identity(path.read_bytes()) == {k: v for k, v in expected.items() if k != "mode"},
                    "VENDOR_CONTENT_CHANGED")
            require(bool(path.stat().st_mode & 0o111) == (expected["mode"] == "100755"), "VENDOR_MODE_CHANGED")
        env = {**os.environ, "GIT_INDEX_FILE": str(private / "proposal.index")}
        git(root, "read-tree", "HEAD", env=env)
        git(root, "add", "-f", "--", *sorted(CHANGED | expected_files.keys()), env=env)
        patch = git(root, "diff", "--cached", "--binary", "HEAD", env=env)
        require({p.decode() for p in git(root, "diff", "--cached", "--name-only", "-z", "HEAD", env=env).split(b"\0") if p}
                == changed | expected_files.keys(), "PATCH_PATH_SET_MISMATCH")
        for name, raw in [("codex-rs/Cargo.toml", new_manifest), ("codex-rs/Cargo.lock", new_lock), ("MODULE.bazel.lock", module_lock)]:
            require(git(root, "show", ":" + name, env=env) == raw, "INDEX_LOCK_CAPTURE_MISMATCH")
        proposal_tree = git(root, "write-tree", env=env).decode().strip()
        replay_env = {**os.environ, "GIT_INDEX_FILE": str(private / "replay.index")}
        git(root, "read-tree", "HEAD", env=replay_env)
        patchpath = private / "checked.patch"
        patchpath.write_bytes(patch)
        git(root, "apply", "--cached", str(patchpath), env=replay_env)
        require(git(root, "write-tree", env=replay_env).decode().strip() == proposal_tree, "PATCH_FORWARD_MISMATCH")
        git(root, "apply", "--cached", "--reverse", str(patchpath), env=replay_env)
        require(git(root, "write-tree", env=replay_env).decode().strip() == before_source["tree"], "PATCH_REVERSE_MISMATCH")
        (payload / "proposal.patch").write_bytes(patch)
        write_json(payload / "vendor-file-manifest.json", expected_files)
        result.update(proposal_validated=True, proposal_tree_including_only_the_original_proposal_tools=proposal_tree,
                      two_actual_locks_repeat_byte_equal=True, original_cargo_deny_passed=True,
                      forward_and_reverse_patch_replayed=True, workspace_members_not_expanded=True,
                      validated_payload_identities={"proposal.patch": identity(patch), "after/Cargo.toml": identity(new_manifest),
                                                    "after/Cargo.lock": identity(new_lock), "after/MODULE.bazel.lock": identity(module_lock)})
    except CommandFailed as error:
        result["error_code"] = str(error)
        result["original_exit_code"] = error.code
        raise
    except Exception:
        result["error_code"] = "PROPOSAL_GENERATION_OR_GUARD_FAILED"
        failure = payload / "logs/proposal-failure.log"
        failure.parent.mkdir(parents=True, exist_ok=True)
        failure.write_text(traceback.format_exc())
        raise
    finally:
        for name in CHANGED:
            target = payload / "after" / Path(name).name
            try:
                if (root / name).is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((root / name).read_bytes())
            except Exception:
                result["output_capture_failed"] = True
                result["proposal_validated"] = False
        try:
            write_json(payload / "source-after.json", {
                "head": git(root, "rev-parse", "HEAD").decode().strip(),
                "committed_tree": git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
                "tracked_changes": [p.decode() for p in git(root, "diff", "--name-only", "-z", "HEAD").split(b"\0") if p],
                "proposal_generation_attempted": True,
                "proposal_validated": result["proposal_validated"],
            })
        except Exception:
            result["source_after_capture_failed"] = True
            result["proposal_validated"] = False
        if not result["proposal_validated"] and (payload / "proposal.patch").exists():
            # Preserve raw logs even when final source custody prevents publishing a proposal.
            try:
                (payload / "proposal.patch").replace(private / "unvalidated-proposal.patch")
                result["unvalidated_patch_withheld_from_upload"] = True
            except Exception:
                result["unvalidated_patch_withhold_failed"] = True
        try:
            write_json(payload / "result.json", result)
        except Exception:
            result["proposal_validated"] = False
            print(json.dumps({"error_code": "FINAL_RECEIPT_WRITE_FAILED"}), flush=True)
    require(result["proposal_validated"], "FINAL_CAPTURE_FAILED")


def main():
    root = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    phase = sys.argv[1]
    if phase == "preflight":
        source = source_guard(root)
        private = Path(tempfile.mkdtemp(prefix="pin-utils-proposal.", dir=os.environ["RUNNER_TEMP"]))
        write_json(private / "payload/source-before.json", source)
        write_json(private / "payload/backport-spec.json", SPEC)
        write_json(private / "payload/result.json", {"proposal_validated": False, "error_code": "GENERATION_NOT_STARTED"})
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("private_dir=" + str(private) + "\n")
        print(json.dumps(source))
    elif phase == "generate":
        generate(root, private_dir())
    elif phase == "collect":
        original = git(root, "show", SPEC["base_head"] + ":codex-rs/Cargo.toml")
        collect(private_dir(), SPEC, original, workspace_patch(original))
    else:
        raise ProposalError("INVALID_PHASE")


if __name__ == "__main__":
    try:
        main()
    except CommandFailed as error:
        print(json.dumps({"proposal_validated": False, "error_code": "ORIGINAL_COMMAND_FAILED", "exit_code": error.code}))
        raise SystemExit(error.code) from None
    except ProposalError as error:
        print(json.dumps({"proposal_validated": False, "error_code": str(error)}))
        raise SystemExit(1) from None
    except Exception:
        print(json.dumps({"proposal_validated": False, "error_code": "PROPOSAL_FAILURE"}))
        raise SystemExit(1) from None
