"""Expose only binaries reported by this invocation's official Nextest build.

Nextest exposes a package's binaries to its own integration tests. Some workspace
tests also use another selected package's helper. Build the identical selection
with Nextest's binaries-only listing, then pass the reported paths to the original
run command. The original double-build path can reuse its cache, but is not
guaranteed to perform no compilation or artifact replacement.

For the scoped metadata path, a supported command executes the official listed
binaries without a second Cargo build. Build selectors remain on the original
listing command; test options remain on the execution command. Unsupported
options retain the original command and its strict whole-command observations.
There is no target-directory search, required helper list or executable-format
assumption. Explicit archive/reuse invocations retain their original behavior,
without adding cross-package identities that a fresh build did not establish.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import uuid


class BinaryEnvironmentError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise BinaryEnvironmentError(message)


# Pinned Nextest 0.9.103 run/list CLI. Unknown flags are forwarded to the original
# command, with an explicit notice, rather than approximated or silently removed.
SHARED_FLAGS = {
    "--workspace",
    "--all",
    "--lib",
    "--bins",
    "--examples",
    "--tests",
    "--benches",
    "--all-targets",
    "--all-features",
    "--no-default-features",
    "--release",
    "-r",
    "--frozen",
    "--locked",
    "--offline",
    "--cargo-quiet",
    "--cargo-verbose",
    "--ignore-rust-version",
    "--future-incompat-report",
    "--ignore-default-filter",
    "--override-version-check",
    "--verbose",
    "-v",
}
SHARED_VALUES = {
    "--package",
    "-p",
    "--exclude",
    "--bin",
    "--example",
    "--test",
    "--bench",
    "--features",
    "-F",
    "--build-jobs",
    "--cargo-profile",
    "--target",
    "--target-dir",
    "--manifest-path",
    "--config",
    "-Z",
    "--run-ignored",
    "--partition",
    "--platform-filter",
    "--filterset",
    "--filter-expr",
    "-E",
    "--config-file",
    "--tool-config-file",
    "--profile",
    "-P",
    "--color",
}
RUN_FLAGS = {
    "--no-run",
    "--fail-fast",
    "--ff",
    "--no-fail-fast",
    "--nff",
    "--no-capture",
    "--nocapture",
    "--hide-progress-bar",
    "--no-output-indent",
    "--no-input-handler",
}
RUN_VALUES = {
    "--test-threads",
    "--jobs",
    "-j",
    "--retries",
    "--max-fail",
    "--no-tests",
    "--stress-count",
    "--stress-duration",
    "--failure-output",
    "--success-output",
    "--status-level",
    "--final-status-level",
    "--message-format",
    "--message-format-version",
}
REUSE_OPTIONS = {
    "--archive-file",
    "--archive-format",
    "--extract-to",
    "--extract-overwrite",
    "--persist-extract-tempdir",
    "--binaries-metadata",
    "--workspace-remap",
    "--target-dir-remap",
}


def listing_arguments(args, *, internal_metadata=False):
    """Return exact shared arguments, or an explicit original-path reason.

    Values, positional filters and everything after -- are opaque. They are
    never scanned as options or used to alter the original run arguments.
    """
    shared = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            shared.extend(args[index:])
            break
        option, equal, _value = arg.partition("=")
        if option in REUSE_OPTIONS or (
            option == "--cargo-metadata" and not internal_metadata
        ):
            return (
                None,
                "explicit build reuse retains its original metadata/environment",
            )
        if option in {"--help", "-h", "--version", "-V", "--unit-graph"}:
            return None, "informational/build-graph invocation"
        if option in SHARED_FLAGS or option == "--timings":
            shared.append(arg)
        elif option in SHARED_VALUES or (
            option == "--cargo-metadata" and internal_metadata
        ):
            shared.append(arg)
            if not equal:
                index += 1
                if index >= len(args) or args[index] == "--":
                    return None, f"missing value for {option}; original parser decides"
                shared.append(args[index])
        elif option in RUN_FLAGS:
            pass
        elif option in RUN_VALUES:
            if not equal:
                index += 1
                if index >= len(args) or args[index] == "--":
                    return None, f"missing value for {option}; original parser decides"
        elif any(
            arg.startswith(short) and len(arg) > 2
            for short in ("-p", "-F", "-E", "-P", "-Z")
        ):
            shared.append(arg)
        elif arg.startswith("-j") and len(arg) > 2:
            pass
        elif arg.startswith("-"):
            return None, f"unrecognized option {arg!r}; original parser decides"
        else:
            shared.append(arg)
        index += 1
    separator = shared.index("--") if "--" in shared else len(shared)
    shared[separator:separator] = [
        "--list-type",
        "binaries-only",
        "--message-format",
        "json",
    ]
    return shared, None


def ownership_metadata_arguments(args):
    """Metadata is only an ownership inventory, never Nextest's dependency graph."""
    result = ["cargo", "metadata", "--no-deps", "--format-version=1"]
    index = 0
    while index < len(args) and args[index] != "--":
        arg = args[index]
        option, equal, _value = arg.partition("=")
        if option in {"--locked", "--offline", "--frozen"}:
            result.append(arg)
        elif option in {"--manifest-path", "--config", "-Z"}:
            result.append(arg)
            if not equal:
                index += 1
                require(index < len(args), f"missing {option} metadata value")
                result.append(args[index])
        elif arg.startswith("-Z") and len(arg) > 2:
            result.append(arg)
        elif option in SHARED_VALUES | RUN_VALUES | {"--cargo-metadata"} and not equal:
            index += 1
        index += 1
    return result


def listed_execution_arguments(command, binaries):
    """Separate known build selectors only after an official scoped build.

    No full-graph metadata is invented from the ownership inventory. The caller
    must already have supplied its current --cargo-metadata; custom Cargo
    configuration/target runners and unknown options keep the original path.
    """
    build_flags = {
        "--workspace",
        "--all",
        "--lib",
        "--bins",
        "--examples",
        "--tests",
        "--benches",
        "--all-targets",
        "--all-features",
        "--no-default-features",
        "--release",
        "-r",
        "--frozen",
        "--locked",
        "--offline",
        "--cargo-quiet",
        "--cargo-verbose",
        "--ignore-rust-version",
        "--future-incompat-report",
    }
    build_values = {
        "--package",
        "-p",
        "--exclude",
        "--bin",
        "--example",
        "--test",
        "--bench",
        "--features",
        "-F",
        "--build-jobs",
        "--cargo-profile",
        "--target-dir",
    }
    run_flags = RUN_FLAGS | {
        "--ignore-default-filter",
        "--override-version-check",
        "--verbose",
        "-v",
    }
    run_values = RUN_VALUES | {
        "--run-ignored",
        "--partition",
        "--platform-filter",
        "--filterset",
        "--filter-expr",
        "-E",
        "--profile",
        "-P",
        "--color",
    }
    execution = command[:3]
    metadata = []
    index = 3
    while index < len(command):
        arg = command[index]
        if arg == "--":
            execution.extend(command[index:])
            break
        option, equal, value = arg.partition("=")
        if option in build_flags:
            if equal:
                return None, None, "build flag with a value retains the original parser"
        elif option in build_values | run_values | {"--cargo-metadata"}:
            consumed = [arg]
            if not equal:
                index += 1
                if index >= len(command) or command[index] == "--":
                    return None, None, "missing value retains the original parser"
                value = command[index]
                consumed.append(value)
            if option == "--cargo-metadata":
                metadata.append(value)
            if option not in build_values:
                execution.extend(consumed)
        elif option in run_flags or (arg.startswith("-j") and len(arg) > 2):
            execution.append(arg)
        elif any(arg.startswith(short) and len(arg) > 2 for short in ("-p", "-F")):
            pass
        elif any(arg.startswith(short) and len(arg) > 2 for short in ("-E", "-P")):
            execution.append(arg)
        elif arg.startswith("-"):
            return (
                None,
                None,
                f"unsupported execution split {arg!r}; original command retained",
            )
        else:
            execution.append(arg)
        index += 1
    if len(metadata) != 1:
        return None, None, "one existing scoped cargo metadata input is required"
    separator = execution.index("--") if "--" in execution else len(execution)
    execution[separator:separator] = ["--binaries-metadata", str(binaries)]
    return execution, metadata[0], None


def file_observation(path, *, executable=False):
    """Observe actual bytes and identity; no ELF/PE/Mach-O-specific assumption."""
    path = Path(path)
    canonical = path.resolve(strict=True)
    before = path.stat()
    require(stat.S_ISREG(before.st_mode), f"not a regular file: {path}")
    if executable and os.name != "nt":
        require(
            os.access(path, os.X_OK), f"reported artifact is not executable: {path}"
        )
    digest = hashlib.sha256()
    git_digest = (
        None
        if executable
        else hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0")
    )
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            if git_digest is not None:
                git_digest.update(block)
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mode", "st_mtime_ns", "st_ctime_ns")
    require(
        all(getattr(before, key) == getattr(after, key) for key in fields)
        and path.resolve(strict=True) == canonical,
        f"file changed while reading: {path}",
    )
    result = {
        "path": str(path),
        "canonical_path": str(canonical),
        "sha256": digest.hexdigest(),
        "bytes": after.st_size,
        "mode": stat.S_IMODE(after.st_mode),
        "device": after.st_dev,
        "inode": after.st_ino,
        "mtime_ns": after.st_mtime_ns,
        "ctime_ns": after.st_ctime_ns,
    }
    if git_digest is not None:
        result["git_blob"] = git_digest.hexdigest()
    return result


def source_observation(metadata):
    """Track Git's source identity/dirty delta and declared Cargo input bytes.

    Dirty developer workspaces are valid. This does not claim that Git describes
    external/generated build inputs, or give a source archive an invented SHA.
    """
    workspace = Path(metadata["workspace_root"]).resolve(strict=True)
    paths = {workspace / "Cargo.toml", workspace / "Cargo.lock"}
    members = set(metadata["workspace_members"])
    for package in metadata["packages"]:
        if package["id"] in members:
            paths.add(Path(package["manifest_path"]))
            paths.update(Path(target["src_path"]) for target in package["targets"])
    files = [file_observation(path) for path in sorted(paths) if path.is_file()]
    record = {"workspace_root": str(workspace), "declared_files": files, "git": None}
    try:
        top = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=workspace,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return record

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=top)

    record["git"] = {
        "root": top,
        "head": git("rev-parse", "HEAD").decode().strip(),
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "tracked_delta_sha256": hashlib.sha256(
            git("diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--")
        ).hexdigest(),
        "status_sha256": hashlib.sha256(
            git("status", "--porcelain=v1", "--untracked-files=no")
        ).hexdigest(),
    }
    return record


def environment_key(key, windows=False):
    return key.upper() if windows else key


def validate_official_build_source(before, after):
    """Allow only the official build's first creation of this workspace's lock.

    --no-deps metadata does not create Cargo.lock in a fresh workspace. Existing
    lock changes, tracked deletion restoration and all other observed source
    changes remain errors. The returned new-file observation is kept in the
    receipt, separately from both complete source snapshots.
    """
    if before == after:
        return None
    lock_path = str(Path(before["workspace_root"]) / "Cargo.lock")
    require(
        not any(item["path"] == lock_path for item in before["declared_files"]),
        "source changed during the official build",
    )
    added = [item for item in after["declared_files"] if item["path"] == lock_path]
    require(
        len(added) == 1 and added[0]["canonical_path"] == lock_path,
        "source changed during the official build",
    )
    without_new_lock = {
        **after,
        "declared_files": [
            item for item in after["declared_files"] if item["path"] != lock_path
        ],
    }
    require(without_new_lock == before, "source changed during the official build")
    return added[0]


def bind_environment(listing, metadata, inherited, *, windows=None):
    windows = os.name == "nt" if windows is None else windows
    require(
        "RUNFILES_MANIFEST_ONLY" not in inherited,
        "Cargo helper metadata cannot replace a Bazel runfiles environment",
    )
    build = listing["rust-build-meta"]
    target = Path(build["target-directory"])
    require(target.is_absolute(), "official Nextest target directory is not absolute")
    target = target.resolve(strict=True)
    packages = {package["id"]: package for package in metadata["packages"]}
    members = set(metadata["workspace_members"])
    artifacts, aliases = {}, {}
    for package_id, entries in build["non-test-binaries"].items():
        for artifact in entries:
            if artifact["kind"] != "bin-exe":
                continue
            name = artifact["name"]
            require(name not in artifacts, f"ambiguous binary name: {name}")
            for alias in {name, name.replace("-", "_")}:
                key = environment_key(alias, windows)
                require(
                    key not in aliases or aliases[key] == name,
                    f"ambiguous binary alias: {alias}",
                )
                aliases[key] = name
            artifacts[name] = (package_id, artifact)
    child = dict(inherited)
    inherited_keys = {}
    for key in inherited:
        normalized = environment_key(key, windows)
        require(normalized not in inherited_keys, f"ambiguous environment key: {key}")
        inherited_keys[normalized] = key
    evidence = []
    for name, (package_id, artifact) in sorted(artifacts.items()):
        require(
            package_id in members and package_id in packages,
            f"reported binary is not a current workspace member: {name}",
        )
        package = packages[package_id]
        targets = [
            entry
            for entry in package["targets"]
            if entry["name"] == name and "bin" in entry["kind"]
        ]
        require(len(targets) == 1, f"no unique Cargo binary target for {name}")
        relative = Path(artifact["path"])
        require(
            not relative.is_absolute() and ".." not in relative.parts,
            f"invalid official artifact path: {name}",
        )
        observation = file_observation(target / relative, executable=True)
        canonical = Path(observation["canonical_path"])
        require(
            canonical.is_relative_to(target),
            f"artifact escapes reported target: {name}",
        )
        keys = {
            environment_key(prefix + alias, windows)
            for prefix in ("CARGO_BIN_EXE_", "NEXTEST_BIN_EXE_")
            for alias in {name, name.replace("-", "_")}
        }
        preserved, added = [], []
        for key in sorted(keys):
            if key not in inherited_keys:
                continue
            original_key = inherited_keys[key]
            prior = Path(inherited[original_key])
            require(
                prior.is_absolute()
                and prior.is_file()
                and prior.resolve() == canonical,
                f"existing explicit binary environment has another identity: {original_key}",
            )
            require(
                file_observation(prior, executable=True)["sha256"]
                == observation["sha256"],
                f"existing binary bytes differ: {original_key}",
            )
            preserved.append(original_key)
        for alias in sorted({name, name.replace("-", "_")}):
            key = environment_key("NEXTEST_BIN_EXE_" + alias, windows)
            if key not in inherited_keys:
                child[key] = str(target / relative)
                added.append(key)
        evidence.append(
            {
                "name": name,
                "package_id": package_id,
                "package_name": package["name"],
                "cargo_target": targets[0],
                "manifest": file_observation(package["manifest_path"]),
                "target_source": file_observation(targets[0]["src_path"]),
                "official_artifact": artifact,
                "executable": observation,
                "preserved_keys": preserved,
                "added_keys": added,
            }
        )
    return child, evidence


def run(command, metadata=None):
    """Run the original command unchanged, with a verified child-only environment."""
    require(command[:3] == ["cargo", "nextest", "run"], "unexpected Nextest command")
    args, reason = listing_arguments(
        command[3:], internal_metadata=metadata is not None
    )
    if args is None:
        print(f"[hepta-nextest] no cross-package additions: {reason}", file=sys.stderr)
        return subprocess.call(command)
    receipt_path = None
    receipt = {
        "command": command,
        "cost": "official binaries-only build/check, then original run build/check",
        "observation_scope": "Source and payloads before/after commands; not an exclusive filesystem authority",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="hepta-nextest-binaries-") as directory:
            directory = Path(directory)
            if metadata is None:
                metadata_path = directory / "ownership.json"
                metadata_command = ownership_metadata_arguments(command[3:])
                with metadata_path.open("wb") as output:
                    status = subprocess.call(metadata_command, stdout=output)
                if status:
                    return status
                metadata = json.loads(metadata_path.read_text())
            before = source_observation(metadata)
            listing_path = directory / "binaries.json"
            list_command = ["cargo", "nextest", "list", *args]
            with listing_path.open("wb") as output:
                status = subprocess.call(list_command, stdout=output)
            if status:
                return status
            raw = listing_path.read_bytes()
            listing = json.loads(raw)
            after_build = source_observation(metadata)
            generated_lock = validate_official_build_source(before, after_build)
            child, helpers = bind_environment(listing, metadata, os.environ)
            target = Path(listing["rust-build-meta"]["target-directory"])
            evidence_dir = target / "hepta-nextest" / str(uuid.uuid4())
            evidence_dir.mkdir(parents=True, exist_ok=False)
            receipt_path = evidence_dir / "receipt.json"
            (evidence_dir / "binaries.json").write_bytes(raw)
            (evidence_dir / "ownership.json").write_text(
                json.dumps(metadata, sort_keys=True) + "\n"
            )
            receipt.update(
                source_before_build=before,
                source_after_build=after_build,
                generated_workspace_lock=generated_lock,
                official_listing_sha256=hashlib.sha256(raw).hexdigest(),
                list_command=list_command,
                platforms=listing["rust-build-meta"].get("platforms"),
                target_platforms=listing["rust-build-meta"].get("target-platforms"),
                helpers=helpers,
                status="RUNNING",
            )
            execution, cargo_metadata, split_reason = (
                listed_execution_arguments(command, evidence_dir / "binaries.json")
                if helpers
                else (None, None, "no cross-package helpers")
            )
            execution_inputs = []
            if execution is not None:
                cargo_raw = Path(cargo_metadata).read_bytes()
                require(
                    json.loads(cargo_raw) == metadata,
                    "scoped metadata file no longer matches the supplied inventory",
                )
                expected_inputs = [
                    {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                    for data in (raw, cargo_raw)
                ]
                receipt["execution_input_expected"] = expected_inputs
                cargo_evidence = evidence_dir / "execution-cargo-metadata.json"
                cargo_evidence.write_bytes(cargo_raw)
                saved_cargo = file_observation(cargo_evidence)
                receipt["execution_cargo_metadata"] = saved_cargo
                require(
                    all(
                        saved_cargo[key] == expected_inputs[1][key]
                        for key in ("bytes", "sha256")
                    ),
                    "preserved scoped cargo metadata differs from validated bytes",
                )
                execution_inputs = [
                    file_observation(evidence_dir / "binaries.json"),
                    file_observation(cargo_metadata),
                ]
                receipt["execution_inputs_before"] = execution_inputs
                require(
                    all(
                        item["bytes"] == expected["bytes"]
                        and item["sha256"] == expected["sha256"]
                        for item, expected in zip(execution_inputs, expected_inputs)
                    ),
                    "official execution metadata differs from validated bytes",
                )
            receipt.update(
                execution_command=execution or command,
                execution_mode="official-listed-binaries"
                if execution is not None
                else "original-command",
                cost="official binaries-only build/check, then listed-binary execution"
                if execution is not None
                else receipt["cost"],
                execution_split_reason=split_reason,
                execution_inputs_before=execution_inputs,
            )
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
            print(
                f"[hepta-nextest] {len(helpers)} official helpers; receipt: {receipt_path}",
                file=sys.stderr,
            )
            status = (
                subprocess.call(execution or command, env=child)
                if helpers
                else subprocess.call(command)
            )
            receipt["command_exit_code"] = status
            receipt["source_after"] = source_observation(metadata)
            receipt["payloads_after"] = [
                file_observation(item["executable"]["path"], executable=True)
                for item in helpers
            ]
            require(
                receipt["source_after"] == after_build,
                "source changed during the original run",
            )
            require(
                receipt["payloads_after"] == [item["executable"] for item in helpers],
                "reported helper identity/bytes changed during the original run",
            )
            receipt["execution_inputs_after"] = [
                file_observation(item["path"]) for item in execution_inputs
            ]
            require(
                receipt["execution_inputs_after"] == execution_inputs,
                "official execution metadata identity/bytes changed during the run",
            )
            if execution is not None:
                receipt["execution_cargo_metadata_after"] = file_observation(
                    saved_cargo["path"]
                )
                require(
                    receipt["execution_cargo_metadata_after"] == saved_cargo,
                    "preserved scoped cargo metadata identity/bytes changed during the run",
                )
            receipt["status"] = (
                "LISTED_BINARIES_TERMINAL_OBSERVATIONS_MATCH"
                if execution is not None
                else "ORIGINAL_COMMAND_TERMINAL_OBSERVATIONS_MATCH"
            )
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
            return status
    except (
        BinaryEnvironmentError,
        OSError,
        ValueError,
        KeyError,
        subprocess.CalledProcessError,
    ) as error:
        receipt.update(status="BINARY_IDENTITY_REJECTED", error=str(error))
        if receipt_path is not None:
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"[hepta-nextest] {error}", file=sys.stderr)
        return 1
