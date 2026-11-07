#!/usr/bin/env python3
"""Build or verify pinned test helpers from Cargo's executable metadata."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


HELPERS = {
    "codex-cli": ("codex",),
    "codex-exec": ("codex-exec",),
    "codex-app-server": ("codex-app-server", "exec-server"),
    "codex-code-mode-host": ("codex-code-mode-host",),
    "codex-rmcp-client": ("test_stdio_server", "test_streamable_http_server"),
    "codex-linux-sandbox": ("codex-linux-sandbox",),
    "codex-shell-escalation": ("codex-execve-wrapper",),
    "codex-hepta-infer-worker-host": ("hepta-joint-propose",),
}


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_command(package):
    command = [
        "cargo",
        "build",
        "--locked",
        "--message-format=json-render-diagnostics",
        "-p",
        package,
    ]
    for binary in HELPERS[package]:
        command.extend(["--bin", binary])
    return command


def source_snapshot(root):
    def git(*arguments):
        return subprocess.check_output(
            ["git", "--no-optional-locks", *arguments], cwd=root, text=True
        ).strip()

    return {
        "head": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "status": git("status", "--porcelain=v1", "--untracked-files=all"),
    }


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_identity(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def verify_helpers(root, output, requested_packages):
    """Observe existing preparation evidence without building or rewriting it."""
    report = {
        "schema_version": 1,
        "mode": "verify-only",
        "manifest": str(output / "manifest.json"),
        "env": str(output / "env.json"),
        "source_before": None,
        "source_after": None,
        "selected_packages": [],
        "artifacts": {},
        "complete": False,
        "exit_code": 1,
    }
    try:
        report["source_before"] = source_snapshot(root)
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        environment = json.loads((output / "env.json").read_text(encoding="utf-8"))
        require(isinstance(manifest, dict), "helper manifest must be an object")
        require(
            type(manifest.get("schema_version")) is int
            and manifest["schema_version"] == 1,
            "unsupported helper manifest schema",
        )
        require(
            manifest.get("complete") is True
            and type(manifest.get("exit_code")) is int
            and manifest["exit_code"] == 0,
            "helper preparation is not complete",
        )
        require(
            report["source_before"]["status"] == ""
            and manifest.get("source_status_before") == ""
            and manifest.get("source_status_after") == "",
            "source is not clean at preparation and verification",
        )
        require(
            manifest.get("source_sha")
            == manifest.get("source_sha_after")
            == report["source_before"]["head"],
            "source HEAD differs from helper preparation",
        )
        require(
            manifest.get("workspace") == str(root / "codex-rs"),
            "helper workspace differs from the current source",
        )
        selected = manifest.get("selected_packages")
        require(
            isinstance(selected, list)
            and selected
            and all(
                isinstance(package, str) and package in HELPERS for package in selected
            )
            and len(selected) == len(set(selected)),
            "helper package selection is empty, duplicated, or unknown",
        )
        report["selected_packages"] = selected
        require(
            requested_packages == selected,
            "requested helper packages differ from preparation",
        )
        expected = {
            binary: package for package in selected for binary in HELPERS[package]
        }
        artifacts = manifest.get("artifacts")
        require(
            isinstance(artifacts, dict) and set(artifacts) == set(expected),
            "helper artifact set differs from the complete selected binary set",
        )
        builds = manifest.get("builds")
        require(
            isinstance(builds, list)
            and len(builds) == len(selected)
            and all(isinstance(build, dict) for build in builds),
            "helper build receipts are incomplete",
        )
        for package, build in zip(selected, builds, strict=True):
            require(
                build.get("package") == package
                and build.get("binaries") == list(HELPERS[package])
                and build.get("command") == build_command(package)
                and build.get("complete") is True
                and build.get("cargo_finished") is True
                and type(build.get("exit_code")) is int
                and build["exit_code"] == 0,
                f"helper build receipt is not complete for {package}",
            )
        expected_environment = {}
        for binary, package in expected.items():
            artifact = artifacts[binary]
            require(isinstance(artifact, dict), f"invalid artifact metadata: {binary}")
            require(
                artifact.get("package") == package
                and isinstance(artifact.get("package_id"), str)
                and artifact["package_id"]
                and isinstance(artifact.get("profile"), dict),
                f"artifact package metadata differs: {binary}",
            )
            compiler_path = artifact.get("compiler_executable")
            executable = artifact.get("executable")
            require(
                isinstance(compiler_path, str)
                and Path(compiler_path).is_absolute()
                and isinstance(executable, str)
                and not any(c in compiler_path + executable for c in "\r\n"),
                f"invalid compiler or pinned executable path: {binary}",
            )
            suffix = ".exe" if Path(compiler_path).suffix == ".exe" else ""
            pinned = output / "bin" / f"{binary}{suffix}"
            require(
                executable == str(pinned)
                and pinned.resolve(strict=True) == pinned
                and pinned.is_file(),
                f"executable is not the pinned attempt copy: {binary}",
            )
            digest, size = hashlib.sha256(), 0
            with pinned.open("rb") as snapshot:
                before = os.fstat(snapshot.fileno())
                require(stat.S_ISREG(before.st_mode), f"helper is not a file: {binary}")
                for block in iter(lambda: snapshot.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
                after = os.fstat(snapshot.fileno())
            observed = {
                "package": package,
                "compiler_executable": compiler_path,
                "executable": str(pinned),
                "sha256": digest.hexdigest(),
                "bytes": size,
                "match": False,
            }
            report["artifacts"][binary] = observed
            path_after = pinned.stat()
            require(
                file_identity(before)
                == file_identity(after)
                == file_identity(path_after)
                and size == before.st_size,
                f"pinned helper changed during verification: {binary}",
            )
            require(
                type(artifact.get("bytes")) is int
                and artifact["bytes"] > 0
                and artifact["bytes"] == size
                and artifact.get("sha256") == observed["sha256"],
                f"pinned helper content differs from preparation: {binary}",
            )
            require(
                not stat.S_IMODE(after.st_mode) & 0o222 and os.access(pinned, os.X_OK),
                f"pinned helper is writable or not executable: {binary}",
            )
            for name in sorted({binary, binary.replace("-", "_")}):
                expected_environment[f"CARGO_BIN_EXE_{name}"] = str(pinned)
            observed["match"] = True
        require(
            isinstance(environment, dict) and environment == expected_environment,
            "exported helper environment differs from the exact pinned copies",
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            report["source_after"] = source_snapshot(root)
            require(
                report["source_before"] == report["source_after"]
                and report["source_after"]["status"] == "",
                "source changed during helper verification",
            )
        except Exception as error:
            report.setdefault("error", f"{type(error).__name__}: {error}")
    if "error" not in report:
        report.update(complete=True, exit_code=0)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--package", action="append", choices=tuple(HELPERS))
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify existing pinned helpers without building or rewriting evidence",
    )
    args = parser.parse_args()
    selected_packages = args.package or list(HELPERS)
    if len(selected_packages) != len(set(selected_packages)):
        parser.error("a helper package may be selected only once")
    root = Path(__file__).resolve().parents[1]
    workspace = root / "codex-rs"
    output = args.output_dir.resolve()
    if args.verify_only:
        if args.github_env is not None:
            parser.error("--github-env cannot be written in --verify-only mode")
        report = verify_helpers(root, output, selected_packages)
        print(json.dumps(report, indent=2), flush=True)
        return report["exit_code"]
    output.mkdir(parents=True, exist_ok=True)
    if (output / "manifest.json").exists() or (output / "env.json").exists():
        parser.error(
            "output directory already contains helper evidence; use a new directory"
        )
    manifest = {
        "schema_version": 1,
        "source_sha": None,
        "source_sha_after": None,
        "source_status_before": None,
        "source_status_after": None,
        "workspace": str(workspace),
        "selected_packages": selected_packages,
        "builds": [],
        "artifacts": {},
        "complete": False,
        "exit_code": 1,
    }
    environment = {}

    def git(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=root, text=True).strip()

    def checkpoint():
        save_json(output / "env.json", environment)
        save_json(output / "manifest.json", manifest)

    checkpoint()
    try:
        manifest["source_sha"] = git("rev-parse", "HEAD")
        manifest["source_status_before"] = git(
            "status", "--porcelain=v1", "--untracked-files=all"
        )
        if manifest["source_status_before"]:
            raise RuntimeError(
                "source has tracked or untracked changes before helper builds"
            )
        for package in selected_packages:
            binaries = HELPERS[package]
            command = build_command(package)
            stdout_path = output / f"{package}.jsonl"
            stderr_path = output / f"{package}.stderr.log"
            build = {
                "package": package,
                "binaries": list(binaries),
                "command": command,
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
                "exit_code": None,
                "cargo_finished": None,
                "complete": False,
            }
            manifest["builds"].append(build)
            checkpoint()
            print(f"Building test helpers: {package}", flush=True)
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                result = subprocess.run(
                    command, cwd=workspace, stdout=stdout, stderr=stderr, check=False
                )
            build["exit_code"] = result.returncode
            found = set()
            with stdout_path.open(encoding="utf-8") as stdout:
                for line in stdout:
                    message = json.loads(line)
                    if message.get("reason") == "build-finished":
                        build["cargo_finished"] = message.get("success")
                    target = message.get("target", {})
                    binary = target.get("name")
                    if (
                        message.get("reason") != "compiler-artifact"
                        or binary not in binaries
                        or "bin" not in target.get("kind", [])
                        or not message.get("executable")
                    ):
                        continue
                    executable = Path(message["executable"])
                    if not executable.is_absolute():
                        executable = workspace / executable
                    if not executable.is_file() or any(
                        c in str(executable) for c in "\r\n"
                    ):
                        raise RuntimeError(
                            f"invalid executable reported by Cargo: {executable}"
                        )
                    # Cargo can relink the same top-level binary during a later
                    # test build. Pin these exact compiler-reported bytes to
                    # this attempt before exporting runtime helper metadata.
                    binary_dir = output / "bin"
                    binary_dir.mkdir(mode=0o700, exist_ok=True)
                    suffix = ".exe" if executable.suffix == ".exe" else ""
                    pinned = binary_dir / f"{binary}{suffix}"
                    digest, size = hashlib.sha256(), 0
                    with executable.open("rb") as artifact:
                        before = os.fstat(artifact.fileno())
                        with pinned.open("xb") as snapshot:
                            for block in iter(lambda: artifact.read(1024 * 1024), b""):
                                snapshot.write(block)
                                digest.update(block)
                                size += len(block)
                            snapshot.flush()
                            os.fsync(snapshot.fileno())
                        after = os.fstat(artifact.fileno())
                    if (
                        file_identity(before) != file_identity(after)
                        or size != before.st_size
                    ):
                        raise RuntimeError(
                            f"helper changed while copying: {executable}"
                        )
                    pinned.chmod(stat.S_IMODE(before.st_mode) & ~0o222)
                    with pinned.open("rb") as snapshot:
                        pinned_digest = hashlib.file_digest(
                            snapshot, "sha256"
                        ).hexdigest()
                    if (
                        pinned.stat().st_size != size
                        or pinned_digest != digest.hexdigest()
                    ):
                        raise RuntimeError(
                            f"helper copy failed content verification: {pinned}"
                        )
                    manifest["artifacts"][binary] = {
                        "package": package,
                        "package_id": message["package_id"],
                        "compiler_executable": str(executable),
                        "executable": str(pinned),
                        "profile": message["profile"],
                        "sha256": digest.hexdigest(),
                        "bytes": size,
                    }
                    found.add(binary)
            if result.returncode != 0:
                raise RuntimeError(
                    f"{package} build exited {result.returncode}; see raw logs"
                )
            if build["cargo_finished"] is not True:
                raise RuntimeError(
                    f"{package} has no successful Cargo build-finished record"
                )
            if found != set(binaries):
                raise RuntimeError(
                    f"{package} missing executable metadata: {sorted(set(binaries) - found)}"
                )
            for binary in binaries:
                for name in sorted({binary, binary.replace("-", "_")}):
                    for prefix in ("CARGO_BIN_EXE", "NEXTEST_BIN_EXE"):
                        environment[f"{prefix}_{name}"] = manifest["artifacts"][binary][
                            "executable"
                        ]
            build["complete"] = True
            checkpoint()
        manifest["source_sha_after"] = git("rev-parse", "HEAD")
        manifest["source_status_after"] = git(
            "status", "--porcelain=v1", "--untracked-files=all"
        )
        if manifest["source_status_after"]:
            raise RuntimeError(
                "source has tracked or untracked changes after helper builds"
            )
        if manifest["source_sha_after"] != manifest["source_sha"]:
            raise RuntimeError("source commit changed during helper builds")
        if args.github_env is not None:
            with args.github_env.open("a", encoding="utf-8") as github_env:
                github_env.write(
                    "".join(
                        f"{key}={value}\n" for key, value in sorted(environment.items())
                    )
                )
        manifest.update(complete=True, exit_code=0)
    except KeyboardInterrupt:
        manifest.update(error="interrupted", exit_code=130)
    except Exception as error:
        manifest["error"] = f"{type(error).__name__}: {error}"
    finally:
        checkpoint()
    print(
        json.dumps(
            {
                "manifest": str(output / "manifest.json"),
                "complete": manifest["complete"],
                "exit_code": manifest["exit_code"],
            }
        ),
        flush=True,
    )
    return manifest["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
