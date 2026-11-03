"""Build the pinned CLI and an observed in-process facade in an isolated checkout.

No networking, checkout creation, source reset, toolchain installation or model
calls are performed by this script. Cargo may fetch pinned dependencies. A
failed build leaves its complete log and modified isolated source for review.
"""

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import tomllib

HERE = Path(__file__).resolve().parent
COMMIT = "6ff1e1ca3b30fc8b914720681fcf5fe62e95f856"
TAG = "rust-v0.166.0"
VERSION = "0.166.0"


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def git(source, *args):
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def normalize_local_lock(source):
    """Repair only release-tag local workspace versions; external graph is exact."""
    workspace = tomllib.loads((source / "codex-rs/Cargo.toml").read_text())
    if workspace["workspace"]["package"]["version"] != VERSION:
        raise ValueError("the actual workspace is not the pinned release")
    names = set()
    for relative in git(source, "ls-files", "codex-rs/**/Cargo.toml").splitlines():
        package = tomllib.loads((source / relative).read_text()).get("package", {})
        if package.get("version") == {"workspace": True}:
            names.add(package["name"])
    path = source / "codex-rs/Cargo.lock"
    original = path.read_text()
    blocks = original.split("[[package]]")
    changed = []
    for index, block in enumerate(blocks[1:], 1):
        package = tomllib.loads("[[package]]" + block)["package"][0]
        if "source" not in package and package["name"] in names:
            old = package["version"]
            if old not in ("0.0.0", VERSION):
                raise ValueError("unexpected local lock version: " + package["name"])
            if old != VERSION:
                blocks[index], count = re.subn(r'(?m)^version = "0\.0\.0"$',
                    'version = "' + VERSION + '"', block, count=1)
                if count != 1:
                    raise ValueError("local lock version rewrite was ambiguous")
                changed.append({"name": package["name"], "from": old, "to": VERSION})
    replacement = "[[package]]".join(blocks)
    before, after = [tomllib.loads(text)["package"] for text in (original, replacement)]
    if [p for p in before if "source" in p] != [p for p in after if "source" in p]:
        raise ValueError("external dependency lock changed")
    path.write_text(replacement)
    patch = "".join(difflib.unified_diff(original.splitlines(True), replacement.splitlines(True),
        fromfile="a/codex-rs/Cargo.lock", tofile="b/codex-rs/Cargo.lock"))
    return changed, patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=lambda p: Path(p).resolve(), required=True)
    parser.add_argument("--output", type=lambda p: Path(p).resolve(), required=True)
    parser.add_argument("--target-dir", type=lambda p: Path(p).resolve(), required=True)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--profile", choices=("dev", "release"), default="dev")
    parser.add_argument("--build-timeout", type=int, default=3600)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 8 or not 1 <= args.build_timeout <= 7200:
        raise ValueError("explicit bounded build jobs and timeout required")
    if args.output == args.source or args.source in args.output.parents:
        raise ValueError("build evidence must be outside the isolated source checkout")
    if git(args.source, "rev-parse", "HEAD") != COMMIT:
        raise ValueError("source HEAD is not the official 0.166.0 commit")
    if git(args.source, "rev-parse", TAG + "^{commit}") != COMMIT:
        raise ValueError("release tag does not resolve to the pinned commit")
    if git(args.source, "status", "--porcelain"):
        raise ValueError("source must begin clean; do not reuse a dirty prior attempt")
    pin = json.loads((HERE / "SOURCE_PIN.json").read_bytes())
    if pin.get("source_commit") != COMMIT or pin.get("release") != VERSION or pin.get("tag") != TAG:
        raise ValueError("qualification source pin changed")
    for name, expected in pin["qualification_sources_sha256"].items():
        if Path(name).name != name or sha256(HERE / name) != expected:
            raise ValueError("qualification adapter differs from the pinned source: " + name)
    toolchain = tomllib.loads((args.source / "codex-rs/rust-toolchain.toml").read_text())["toolchain"]["channel"]
    if toolchain != "1.95.0":
        raise ValueError("pinned upstream toolchain changed")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "bin").mkdir()
    environment = dict(os.environ, CARGO_TARGET_DIR=str(args.target_dir),
        CARGO_INCREMENTAL="0", CARGO_PROFILE_DEV_DEBUG="0")
    record = {"schema": "hepta.codex-build.v2", "release": VERSION, "tag": TAG,
        "source_commit": COMMIT, "source": str(args.source), "initial_tracked_and_untracked_clean": True,
        "upstream_declared_toolchain": toolchain, "qualification_toolchain_override": None,
        "profile": args.profile, "target_cache": str(args.target_dir), "jobs": args.jobs,
        "environment_overrides": {key: environment[key] for key in
            ("CARGO_TARGET_DIR", "CARGO_INCREMENTAL", "CARGO_PROFILE_DEV_DEBUG")},
        "started_ns": time.time_ns(), "commands": [], "build_succeeded": False,
        "qualification_variant": "CLI with local lock-version repair; facade additionally exposes the real initialize result"}
    save(args.output / "BUILD_STARTED.json", record)

    def build(argv, label):
        command = {"argv": argv, "cwd": str(args.source / "codex-rs"), "started_ns": time.time_ns()}
        record["commands"].append(command)
        log = args.output / (label + ".log")
        with log.open("xb") as stream:
            try:
                run = subprocess.run(argv, cwd=args.source / "codex-rs", env=environment,
                    stdout=stream, stderr=subprocess.STDOUT, timeout=args.build_timeout, check=False)
                command["exit_code"] = run.returncode
                if run.returncode:
                    raise RuntimeError(label + " failed; inspect " + str(log))
            finally:
                command["finished_ns"] = time.time_ns()
                command["log_sha256"] = sha256(log)

    try:
        record["rustc"] = subprocess.check_output(["rustup", "run", toolchain, "rustc", "-vV"], text=True)
        changes, lock_patch = normalize_local_lock(args.source)
        record["local_lock_versions_repaired"] = changes
        record["external_lock_packages_unchanged"] = True
        (args.output / "lock-local-versions.patch").write_text(lock_patch)
        common = ["cargo", "+" + toolchain, "build", "--locked", "--profile", args.profile,
            "--jobs", str(args.jobs)]
        build(common + ["-p", "codex-cli", "--bin", "codex"], "cli-build")
        target_profile = "debug" if args.profile == "dev" else "release"
        shutil.copy2(args.target_dir / target_profile / "codex", args.output / "bin/codex")
        record["cli_source_changes"] = ["codex-rs/Cargo.lock"] if changes else []
        patch = HERE / "bootstrap-observability.patch"
        subprocess.run(["git", "-C", str(args.source), "apply", "--check", str(patch)], check=True)
        subprocess.run(["git", "-C", str(args.source), "apply", str(patch)], check=True)
        wrapper = args.source / "codex-rs/app-server-client/examples/hepta_facade.rs"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        if wrapper.exists():
            raise ValueError("the isolated source already contains a facade wrapper")
        shutil.copyfile(HERE / "hepta_facade.rs", wrapper)
        build(common + ["-p", "codex-app-server-client", "--example", "hepta_facade"], "facade-build")
        shutil.copy2(args.target_dir / target_profile / "examples/hepta_facade", args.output / "bin/hepta_facade")
        record["version_stdout"] = subprocess.check_output([str(args.output / "bin/codex"), "--version"], text=True)
        if record["version_stdout"].strip() != "codex-cli " + VERSION:
            raise ValueError("the compiled CLI reports a different release")
        for name in ("bootstrap-observability.patch", "hepta_facade.rs", "SOURCE_PIN.json"):
            shutil.copyfile(HERE / name, args.output / name)
        record["provenance_files"] = {name: sha256(args.output / name) for name in
            ("bootstrap-observability.patch", "hepta_facade.rs", "SOURCE_PIN.json", "lock-local-versions.patch")}
        record["binaries"] = {name: {"path": str(args.output / "bin" / name),
            "sha256": sha256(args.output / "bin" / name), "bytes": (args.output / "bin" / name).stat().st_size}
            for name in ("codex", "hepta_facade")}
        record["final_tracked_diff_sha256"] = hashlib.sha256(subprocess.check_output([
            "git", "-C", str(args.source), "diff", "--binary", "HEAD"])).hexdigest()
        record["facade_source_changes"] = git(args.source, "status", "--porcelain").splitlines()
        record["build_succeeded"] = True
        record["finished_ns"] = time.time_ns()
        save(args.output / "OFFICIAL_BUILD.json", record)
    except BaseException as error:
        record.update(error=repr(error), finished_ns=time.time_ns())
        save(args.output / "BUILD_FAILED.json", record)
        raise


if __name__ == "__main__":
    main()
