#!/usr/bin/env python3
"""Build test helpers and retain Cargo's executable metadata for qualification."""

import argparse
import hashlib
import json
from pathlib import Path
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--package", action="append", choices=tuple(HELPERS))
    args = parser.parse_args()
    selected_packages = args.package or list(HELPERS)
    if len(selected_packages) != len(set(selected_packages)):
        parser.error("a helper package may be selected only once")
    root = Path(__file__).resolve().parents[1]
    workspace = root / "codex-rs"
    output = args.output_dir.resolve()
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
            command = [
                "cargo",
                "build",
                "--locked",
                "--message-format=json-render-diagnostics",
                "-p",
                package,
            ]
            for binary in binaries:
                command.extend(["--bin", binary])
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
                    digest, size = hashlib.sha256(), 0
                    with executable.open("rb") as artifact:
                        for block in iter(lambda: artifact.read(1024 * 1024), b""):
                            digest.update(block)
                            size += len(block)
                    manifest["artifacts"][binary] = {
                        "package": package,
                        "package_id": message["package_id"],
                        "executable": str(executable),
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
