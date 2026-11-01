"""Materialize the reviewed dependency candidate into an exact disposable checkout."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import urllib.parse
import urllib.request


HERE = Path(__file__).resolve().parent


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def check(raw, expected, label):
    if identity(raw) != {key: expected[key] for key in ("bytes", "sha256")}:
        raise ValueError("byte identity mismatch: " + label)


def relative_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts or str(path) != value:
        raise ValueError("noncanonical relative path")
    return path


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          timeout=30).stdout


def download(entry, archive_directory):
    parsed = urllib.parse.urlsplit(entry["url"])
    if parsed.scheme != "https" or parsed.hostname not in {
        "static.crates.io", "raw.githubusercontent.com",
    } or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("unexpected source download URL")
    request = urllib.request.Request(entry["url"], headers={"User-Agent": "hepta-security-source/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read(entry["bytes"] + 1)
    check(raw, entry, entry.get("path", entry.get("name", "source")))
    (archive_directory / entry["sha256"]).write_bytes(raw)
    return raw


def extract_archive(raw, entry, root):
    destination = root / relative_path(entry["destination"])
    if destination.exists() or destination.is_symlink():
        raise ValueError("vendor destination is not new")
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = archive.getmembers()
        if len(members) > 10000 or sum(member.size for member in members) > 64 * 1024 * 1024:
            raise ValueError("source archive exceeds extraction budget")
        seen = set()
        for member in members:
            path = relative_path(member.name.rstrip("/"))
            if path.parts[0] != entry["source_prefix"] or not (member.isfile() or member.isdir()):
                raise ValueError("unexpected source archive member")
            tail = PurePosixPath(*path.parts[1:])
            if str(tail) == ".":
                if not member.isdir():
                    raise ValueError("archive root is not a directory")
                continue
            if str(tail) in seen:
                raise ValueError("duplicate source archive member")
            seen.add(str(tail))
            output = destination / tail
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, output.open("xb") as target:
                    target.write(source.read())
                output.chmod(0o755 if member.mode & 0o111 else 0o644)


def current_population(root, plan):
    # Derive exact third_party package roots directly rather than scanning the repository.
    roots = {"/".join(PurePosixPath(path).parts[:3]) for path in plan["candidate_files"]
             if path.startswith("codex-rs/third_party/")}
    actual = {"codex-rs/Cargo.toml"}
    for name in roots:
        for path in (root / name).rglob("*"):
            if path.is_symlink():
                raise ValueError("symlink in candidate source")
            if path.is_file():
                actual.add(path.relative_to(root).as_posix())
    return actual


def prepare(root, output):
    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents:
        raise ValueError("evidence must be outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)
    archives = output / "upstream"
    archives.mkdir()
    plan_raw = (HERE / "INPUTS.json").read_bytes()
    plan = json.loads(plan_raw)
    receipt = {"schema": "hepta.dependency-security-preparation.1", "status": "in_progress",
               "input_plan": identity(plan_raw), "source_head": git(root, "rev-parse", "HEAD").decode().strip(),
               "source_base": plan["source_base"], "scientific_sources_modified": False,
               "policy_modified": False, "qualification": False}
    (output / "INPUTS.json").write_bytes(plan_raw)
    try:
        if git(root, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError("checkout is not clean before candidate preparation")
        tree = git(root, "rev-parse", "HEAD:codex-rs").decode().strip()
        if tree != plan["base_codex_rs_git_tree"]:
            raise ValueError("Rust source tree does not match the registered base")
        receipt["base_codex_rs_git_tree"] = tree
        for path, expected in plan["base_files"].items():
            check((root / relative_path(path)).read_bytes(), expected, path)
        for name in {"/".join(PurePosixPath(path).parts[:3]) for path in plan["candidate_files"]
                     if path.startswith("codex-rs/third_party/")}:
            destination = root / name
            if destination.exists() or destination.is_symlink():
                raise ValueError("candidate vendor root already exists: " + name)
        for entry in plan["archives"]:
            raw = download(entry, archives)
            extract_archive(raw, entry, root)
        for entry in plan["prior_files"]:
            path = root / relative_path(entry["path"])
            if path.exists() or path.is_symlink():
                raise ValueError("reviewed backport destination already exists")
            raw = download(entry, archives)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        for entry in plan["patches"]:
            path = root / relative_path(entry["path"])
            check(path.read_bytes(), entry["before"], entry["path"])
            patch = HERE / relative_path(entry["patch"])
            check(patch.read_bytes(), entry["patch_identity"], entry["patch"])
            stat = git(root, "apply", "--numstat", str(patch)).decode().splitlines()
            if len(stat) != 1 or stat[0].split("\t")[-1] != entry["path"]:
                raise ValueError("patch touches an unregistered path")
            git(root, "apply", "--check", str(patch))
            git(root, "apply", str(patch))
            check(path.read_bytes(), entry["after"], entry["path"])
        for entry in plan["new_files"]:
            raw = (HERE / relative_path(entry["source"])).read_bytes()
            check(raw, entry, entry["source"])
            destination = root / relative_path(entry["path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as target:
                target.write(raw)
        if current_population(root, plan) != set(plan["candidate_files"]):
            raise ValueError("candidate file population differs from the review manifest")
        for path, expected in plan["candidate_files"].items():
            check((root / path).read_bytes(), expected, path)
        matrix = plan["matrix_upstream_fix"]
        patch = HERE / relative_path(matrix["patch"])
        check(patch.read_bytes(), matrix["patch_identity"], "official Matrix security patch")
        source = next(entry for entry in plan["archives"] if entry["name"] == "matrix-sdk-crypto")
        raw = (archives / source["sha256"]).read_bytes()
        check(raw, source, "original Matrix registry archive")
        extract_archive(raw, {**source, "destination": "matrix-oracle"}, output)
        oracle = output / "matrix-oracle"
        git(oracle, "apply", "--check", str(patch))
        git(oracle, "apply", str(patch))
        for path in matrix["files"]:
            if (oracle / path).read_bytes() != (root / source["destination"] / path).read_bytes():
                raise ValueError("Matrix candidate differs from the literal official fix")
        receipt["matrix_literal_upstream_patch"] = {
            "commit": matrix["commit"], "patch_identity": matrix["patch_identity"],
            "files": {path: identity((oracle / path).read_bytes()) for path in matrix["files"]},
            "passed": True, "panic_regression_execution_still_required": True,
        }
        for path in plan["policy_files_unchanged"] + [
            "codex-rs/keyring-store/Cargo.toml", "codex-rs/keyring-store/src/lib.rs",
        ]:
            check((root / path).read_bytes(), plan["base_files"][path], path)
        receipt["status"] = "complete"
        receipt["candidate_files"] = plan["candidate_files"]
        receipt["candidate_file_count"] = len(plan["candidate_files"])
        receipt["git_diff_stat"] = git(root, "diff", "--stat").decode()
    except BaseException as error:
        receipt["status"] = "failed"
        receipt["error_type"] = type(error).__name__
        receipt["error"] = str(error)
        raise
    finally:
        (output / "PREPARATION.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = prepare(args.repo, args.output)
    print(json.dumps({"status": receipt["status"], "candidate_files": receipt["candidate_file_count"],
                      "qualification": False}))


if __name__ == "__main__":
    main()
