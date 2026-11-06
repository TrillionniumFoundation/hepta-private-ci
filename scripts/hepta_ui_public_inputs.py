#!/usr/bin/env python3
"""Generate review-only UI dependency inputs; execute no product tests."""

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import time
import tomllib
import traceback
from pathlib import Path

UI_MANIFEST = "apps/hepta-control-ui/rust/robrix-ui/Cargo.toml"
UI_ROOT = "apps/hepta-control-ui/rust/Cargo.toml"
UI_LOCK = "apps/hepta-control-ui/rust/Cargo.lock"
MAKEPAD = "337566c8b25d47f7e4fff6a202157b65bf183330"
GIT_SOURCE = f"git+https://github.com/kevinaboos/makepad?rev={MAKEPAD}#{MAKEPAD}"
REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def blob(data, kind="blob"):
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def validate_lock(before, after):
    require({k: v for k, v in before.items() if k != "package"} ==
            {k: v for k, v in after.items() if k != "package"}, "lock metadata changed")
    key = lambda item: (item["name"], item["version"], item.get("source"))
    old = {key(item): item for item in before["package"]}
    new = {key(item): item for item in after["package"]}
    require(len(old) == len(before["package"]) and len(new) == len(after["package"]), "duplicate package identity")
    require(old.keys() <= new.keys(), "existing locked package removed or changed version")
    for identity, original in old.items():
        expected = dict(original)
        actual = dict(new[identity])
        if identity == ("hepta-robrix-ui", "0.1.0", None):
            expected["dependencies"] = sorted([*original.get("dependencies", []), "pretty_assertions"])
            actual["dependencies"] = sorted(actual.get("dependencies", []))
        require(actual == expected, f"unrelated package change: {identity}")
    added = [new[key] for key in new.keys() - old.keys()]
    require(len(added) == 3 and {p["name"] for p in added} == {"pretty_assertions", "diff", "yansi"}, "unexpected new packages")
    require(all(p.get("source") == REGISTRY and re.fullmatch("[0-9a-f]{64}", p.get("checksum", "")) for p in added), "unexpected new source")
    pretty = next(p for p in added if p["name"] == "pretty_assertions")
    require(pretty["version"] == "1.4.1" and pretty["checksum"] == "3ae130e2f271fbc2ac3a40fb1d07180839cdbbe443c7a27e1e3c13c5cac0116d", "pretty_assertions identity changed")
    require(pretty.get("dependencies") == ["diff", "yansi"], "pretty_assertions dependency edges changed")
    require(all(not p.get("dependencies") for p in added if p["name"] != "pretty_assertions"), "unexpected new dependency edges")
    return sorted(added, key=lambda p: p["name"])


def main():
    require(platform.system() == "Linux" and os.environ.get("GITHUB_ACTIONS") == "true", "hosted Linux scope required")
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    require(event_name in ("workflow_dispatch", "pull_request"), "manual or same-repository PR scope required")
    repository = "TrillionniumFoundation/hepta-private-ci"
    require(os.environ.get("GITHUB_REPOSITORY") == repository, "repository identity mismatch")
    require(os.environ.get("HEPTA_INPUT_SET") == "ui-inputs", "explicit reusable UI input scope required")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    require(event.get("repository", {}).get("full_name") == repository, "event repository mismatch")
    if event_name == "pull_request":
        pull = event.get("pull_request", {})
        head = pull.get("head", {})
        require(head.get("repo", {}).get("full_name") == repository and pull.get("base", {}).get("repo", {}).get("full_name") == repository, "only same-repository PR source is admitted")
        expected_head = head.get("sha")
        source_kind = "same-repository-pr-head"
    else:
        require(event.get("inputs", {}).get("input_set") == "ui-inputs", "explicit manual UI input scope required")
        expected_head = os.environ.get("GITHUB_SHA")
        source_kind = "manual-workflow-sha"
    require(isinstance(expected_head, str) and re.fullmatch("[0-9a-f]{40}", expected_head), "invalid expected source SHA")
    repo = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    own = Path(os.environ["RUNNER_TEMP"]).resolve() / "hepta-ui-public-inputs"
    own.mkdir(mode=0o700)
    out = own / "evidence"
    out.mkdir(mode=0o700)
    cargo_home = own / "cargo-home"
    rustup_home = own / "rustup-home"
    cargo_home.mkdir(mode=0o700)
    rustup_home.mkdir(mode=0o700)
    env = os.environ.copy()
    env.update({"CARGO_HOME": str(cargo_home), "RUSTUP_HOME": str(rustup_home), "RUSTUP_TOOLCHAIN": "1.95.0", "CARGO_TARGET_DIR": str(own / "target"), "CARGO_BUILD_JOBS": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1"})
    require(not any(env.get(key) for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_INDEX_FILE")), "unexpected inherited Git object override")
    receipt = {"schema": "hepta.ui-public-inputs.v3", "status": "PREPARING", "authorityGranted": False, "productTestsExecuted": False, "commands": [], "runId": os.environ["GITHUB_RUN_ID"], "runAttempt": os.environ["GITHUB_RUN_ATTEMPT"], "started": time.time(), "postErrors": []}

    def save():
        temporary = out / "receipt.tmp"
        temporary.write_text(json.dumps(receipt, indent=2) + "\n")
        temporary.replace(out / "receipt.json")

    def run(name, args, cwd=repo):
        require(name not in [row["name"] for row in receipt["commands"]], "duplicate command label")
        row = {"name": name, "argv": [str(x) for x in args], "cwd": str(cwd), "started": time.time()}
        receipt["commands"].append(row)
        save()
        with (out / f"{name}.stdout").open("xb") as stdout, (out / f"{name}.stderr").open("xb") as stderr:
            child = subprocess.Popen(row["argv"], cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
            row["pid"] = child.pid
            save()
            row["exit"] = child.wait()
        row["finished"] = time.time()
        for stream in ("stdout", "stderr"):
            path = out / f"{name}.{stream}"
            row[stream] = {"bytes": path.stat().st_size, "sha256": sha(path)}
        save()
        require(row["exit"] == 0, f"{name} failed with {row['exit']}; original streams retained")
        return (out / f"{name}.stdout").read_bytes()

    def git(name, args, cwd=repo):
        return run(name, ["git", "--no-lazy-fetch", *args], cwd)

    def tracked(name, cwd, revision, allowed=()):
        records = git(name + "-ls-tree", ["ls-tree", "-rz", "--full-tree", revision], cwd)
        rows = []
        for raw in records.split(b"\0"):
            if not raw:
                continue
            left, path = raw.split(b"\t", 1)
            mode, kind, oid = left.decode().split()
            relative = os.fsdecode(path)
            require(kind == "blob" and mode in ("100644", "100755", "120000"), "unsupported tracked object")
            require(not Path(relative).is_absolute() and ".." not in Path(relative).parts, "invalid tracked path")
            actual = cwd / relative
            info = actual.lstat()
            if mode == "120000":
                require(stat.S_ISLNK(info.st_mode), relative)
                data = os.fsencode(os.readlink(actual))
            else:
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and bool(info.st_mode & stat.S_IXUSR) == (mode == "100755"), relative)
                data = actual.read_bytes()
            require(relative in allowed or blob(data) == oid, f"tracked bytes differ: {relative}")
            rows.append({"path": relative, "mode": mode, "gitBlob": oid, "actualBlob": blob(data), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        (out / f"{name}-index.json").write_text(json.dumps(rows, indent=2) + "\n")
        return rows

    def export_registry(packages):
        selected = [p for p in packages if p.get("source") == REGISTRY]
        caches = list((cargo_home / "registry/cache").iterdir())
        require(len(caches) == 1 and caches[0].is_dir() and not caches[0].is_symlink(), "ambiguous public registry cache")
        cache = caches[0]
        wanted = {f"{p['name']}-{p['version']}.crate": p for p in selected}
        require({p.name for p in cache.iterdir()} == set(wanted), "registry archives differ from actual lock")
        config_path = cargo_home / "registry/index" / cache.name / "config.json"
        require(config_path.is_file() and not config_path.is_symlink() and config_path.resolve().is_relative_to(cargo_home), "public registry configuration missing or escaped own cache")
        config = json.loads(config_path.read_bytes())
        require(set(config) <= {"dl", "api", "auth-required"} and config.get("dl") == "https://static.crates.io/crates" and config.get("api") == "https://crates.io" and config.get("auth-required", False) is False, "unapproved public registry configuration")
        exports = {config_path.relative_to(cargo_home).as_posix(): config_path}
        for filename, package in wanted.items():
            archive = cache / filename
            require(archive.is_file() and not archive.is_symlink() and sha(archive) == package["checksum"], filename)
            exports[archive.relative_to(cargo_home).as_posix()] = archive
            name = package["name"]
            suffix = name if len(name) <= 2 else (f"3/{name[0]}/{name}" if len(name) == 3 else f"{name[:2]}/{name[2:4]}/{name}")
            if len(name) <= 2:
                suffix = f"{len(name)}/{name}"
            entry = cargo_home / "registry/index" / cache.name / ".cache" / suffix
            require(entry.is_file() and not entry.is_symlink(), "public sparse entry missing")
            versions = [json.loads(x) for x in entry.read_bytes().split(b"\0") if x.startswith(b"{")]
            matches = [x for x in versions if x.get("name") == name and x.get("vers") == package["version"]]
            require(len(matches) == 1 and matches[0]["cksum"] == package["checksum"], "sparse entry disagrees with lock")
            exports[entry.relative_to(cargo_home).as_posix()] = entry
        index = [{"path": name, "bytes": path.stat().st_size, "sha256": sha(path)} for name, path in sorted(exports.items())]
        archive = out / "registry-public-inputs.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for name, path in sorted(exports.items()):
                tar.add(path, arcname=name, recursive=False)
        with tarfile.open(archive, "r:gz") as tar:
            require([m.name for m in tar.getmembers()] == [r["path"] for r in index], "registry archive member drift")
            for row in index:
                member = tar.getmember(row["path"])
                require(member.isfile() and hashlib.sha256(tar.extractfile(member).read()).hexdigest() == row["sha256"], "registry archive payload mismatch")
        (out / "registry-public-index.json").write_text(json.dumps(index, indent=2) + "\n")
        receipt["publicRegistryPackages"] = len(selected)

    code = 1
    before = None
    try:
        receipt["host"] = {"platform": platform.platform(), "machine": platform.machine(), "uid": os.geteuid()}
        receipt["invocation"] = {"event": event_name, "sourceKind": source_kind, "expectedHead": expected_head, "githubContextSha": os.environ.get("GITHUB_SHA"), "workflowRef": os.environ.get("GITHUB_WORKFLOW_REF"), "workflowSha": os.environ.get("GITHUB_WORKFLOW_SHA")}
        receipt["freeDiskBefore"] = shutil.disk_usage(own).free
        require(receipt["freeDiskBefore"] >= 8 * 1024**3, "insufficient space for dependency inputs")
        head = git("source-head", ["rev-parse", "HEAD"]).decode().strip()
        require(head == expected_head, "checkout SHA differs from the admitted exact source")
        receipt["head"] = head
        receipt["tree"] = git("source-tree", ["rev-parse", "HEAD^{tree}"]).decode().strip()
        require(not git("source-status", ["status", "--porcelain", "--untracked-files=no"]).strip(), "checkout not clean")
        before = tracked("source-before", repo, "HEAD")
        original_manifest = (repo / UI_MANIFEST).read_bytes()
        original_lock = (repo / UI_LOCK).read_bytes()
        require(hashlib.sha256(original_manifest).hexdigest() == "533a4af9311e5688b2bb9cec96e859c936a1c6c3564715afe692c4bcee965be4", "UI manifest preimage changed")
        require(hashlib.sha256(original_lock).hexdigest() == "99d22c4031512530e66b1e1cbec256d069e6e613e158f37d247d9307de265734", "UI lock preimage changed")
        old_lock = tomllib.loads(original_lock.decode())
        require({p.get("source") for p in old_lock["package"] if p.get("source")} == {REGISTRY, GIT_SOURCE}, "unapproved dependency source")
        (out / "Cargo.toml.before").write_bytes(original_manifest)
        (out / "Cargo.lock.before").write_bytes(original_lock)
        rustup = shutil.which("rustup")
        require(rustup is not None, "original hosted rustup unavailable")
        run("toolchain-install", [rustup, "toolchain", "install", "1.95.0", "--profile", "minimal"])
        cargo = Path(run("cargo-path", [rustup, "which", "--toolchain", "1.95.0", "cargo"]).decode().strip())
        rustc = Path(run("rustc-path", [rustup, "which", "--toolchain", "1.95.0", "rustc"]).decode().strip())
        require(cargo.is_relative_to(rustup_home) and rustc.is_relative_to(rustup_home), "compiler escaped own toolchain")
        version = run("rustc-version", [rustc, "-vV"]).decode()
        require(version.startswith("rustc 1.95.0 (59807616e 2026-04-14)\n"), "wrong compiler")
        run("cargo-version", [cargo, "-vV"])
        receipt["tools"] = {"cargo": str(cargo), "cargoSha256": sha(cargo), "rustc": str(rustc), "rustcSha256": sha(rustc), "rustup": rustup, "rustupSha256": sha(Path(rustup))}
        env["RUSTC"] = str(rustc)
        run("baseline-locked-fetch", [cargo, "fetch", "--locked", "--manifest-path", UI_ROOT])
        require((repo / UI_LOCK).read_bytes() == original_lock, "baseline fetch changed the lock")
        post_manifest = original_manifest + b'\n[dev-dependencies]\npretty_assertions = "=1.4.1"\n'
        require(hashlib.sha256(post_manifest).hexdigest() == "c9dfe8c84739132f73f74d54f18c95d62ce732e6d5ebd71bf73da00ea2145a4d", "unexpected manifest postimage")
        (repo / UI_MANIFEST).write_bytes(post_manifest)
        metadata = json.loads(run("full-metadata-generate", [cargo, "metadata", "--format-version", "1", "--manifest-path", UI_ROOT]))
        require(isinstance(metadata.get("resolve"), dict) and metadata["resolve"].get("nodes"), "full resolution missing")
        generated_lock = (repo / UI_LOCK).read_bytes()
        after = tomllib.loads(generated_lock.decode())
        receipt["addedPackages"] = validate_lock(old_lock, after)
        run("locked-offline-metadata", [cargo, "metadata", "--locked", "--offline", "--format-version", "1", "--manifest-path", UI_ROOT])
        require((repo / UI_LOCK).read_bytes() == generated_lock, "locked metadata changed generated bytes")
        export_registry(after["package"])
        checkouts = list((cargo_home / "git/checkouts").glob("*/*/.git"))
        require(len(checkouts) == 1, "ambiguous Makepad checkout")
        checkout = checkouts[0].parent
        require(checkout.resolve().is_relative_to(cargo_home), "Makepad checkout escaped own cache")
        git_dir = Path(git("makepad-git-dir", ["rev-parse", "--absolute-git-dir"], checkout).decode().strip()).resolve(strict=True)
        require(git_dir.is_relative_to(cargo_home), "Makepad Git directory escaped own cache")
        alternate_file = git_dir / "objects/info/alternates"
        alternates = []
        if alternate_file.exists():
            require(alternate_file.is_file() and not alternate_file.is_symlink(), "invalid alternate object file")
            for line in alternate_file.read_bytes().splitlines():
                target = (git_dir / "objects" / os.fsdecode(line)).resolve(strict=True)
                require(target.is_dir() and target.is_relative_to(cargo_home / "git/db"), "Makepad alternate escaped own public cache")
                alternates.append(str(target))
        require(git("makepad-head", ["rev-parse", "HEAD"], checkout).decode().strip() == MAKEPAD, "wrong Makepad revision")
        raw = git("makepad-commit", ["cat-file", "commit", MAKEPAD], checkout)
        require(blob(raw, "commit") == MAKEPAD, "Makepad commit bytes differ")
        tree = raw.splitlines()[0].split()[1].decode()
        require(git("makepad-tree", ["rev-parse", "HEAD^{tree}"], checkout).decode().strip() == tree, "wrong Makepad tree")
        receipt["makepad"] = {"commit": MAKEPAD, "tree": tree, "trackedFiles": len(tracked("makepad", checkout, MAKEPAD)), "gitDir": str(git_dir), "alternates": alternates}
        bundle = out / "makepad-source.bundle"
        git("makepad-bundle", ["bundle", "create", str(bundle), "HEAD"], checkout)
        git("makepad-bundle-verify", ["bundle", "verify", str(bundle)], checkout)
        heads = git("makepad-bundle-heads", ["bundle", "list-heads", str(bundle)], checkout).decode().splitlines()
        require(heads == [MAKEPAD + " HEAD"], "Makepad bundle identity mismatch")
        verification = own / "bundle-verification.git"
        git("bundle-empty-repo", ["init", "--bare", str(verification)], own)
        git("bundle-empty-verify", ["bundle", "verify", str(bundle)], verification)
        git("bundle-local-import", ["fetch", "--no-tags", str(bundle), "HEAD:refs/heads/pinned-makepad"], verification)
        require(git("bundle-import-head", ["rev-parse", "refs/heads/pinned-makepad"], verification).decode().strip() == MAKEPAD, "imported bundle revision differs")
        git("bundle-import-fsck", ["fsck", "--strict", "--full"], verification)
        receipt["status"] = "MINIMAL_UI_LOCK_AND_PUBLIC_INPUTS_GENERATED_REVIEW_REQUIRED"
        code = 0
    except Exception:
        receipt["error"] = traceback.format_exc()
        receipt["status"] = "INPUT_PREPARATION_FAILED"
    finally:
        try:
            git("all-tracked-diff", ["diff", "--binary", "--no-ext-diff", "HEAD", "--"])
            changed = git("changed-paths", ["diff", "--name-only", "HEAD", "--"]).decode().splitlines()
            require(set(changed) <= {UI_MANIFEST, UI_LOCK}, "unrelated tracked changes")
            require(not git("staged-diff", ["diff", "--cached", "--name-only"]).strip(), "staged changes")
            require(git("source-head-after", ["rev-parse", "HEAD"]).decode().strip() == receipt.get("head"), "source HEAD moved")
            if before is not None:
                rows = tracked("source-after", repo, "HEAD", {UI_MANIFEST, UI_LOCK})
                require(len(rows) == len(before), "tracked source count changed")
            for relative, name in [(UI_MANIFEST, "Cargo.toml.generated"), (UI_LOCK, "Cargo.lock.generated")]:
                shutil.copyfile(repo / relative, out / name)
            receipt["actualLockSha256"] = sha(repo / UI_LOCK)
            if code == 0:
                require((repo / UI_MANIFEST).read_bytes() == post_manifest and (repo / UI_LOCK).read_bytes() == generated_lock, "generated UI inputs changed after resolution")
        except Exception:
            receipt["postErrors"].append(traceback.format_exc())
            receipt["status"] = "POST_OBSERVATION_FAILED"
            code = 1
        receipt["finished"] = time.time()
        receipt["exit"] = code
        save()
        rows = [{"path": p.relative_to(out).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p)} for p in sorted(out.rglob("*")) if p.is_file()]
        (out / "INDEX.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(json.dumps({"status": receipt["status"], "exit": code, "receiptSha256": sha(out / "receipt.json")}), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
