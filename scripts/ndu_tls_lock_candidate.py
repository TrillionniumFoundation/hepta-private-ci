#!/usr/bin/env python3
"""Generate reviewable Cargo/Bazel lock candidates for the observed TLS advisories.

This runs on a disposable CI checkout and never pushes or promotes a candidate.
The original cargo-deny gate and its complete dependency graph remain unchanged.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tomllib


UPDATES = (
    ("rustls-webpki", "0.103.16", "RUSTSEC-2026-0382"),
    ("webpki-root-certs", "1.0.10", "RUSTSEC-2026-0383"),
    ("webpki-roots", "1.0.10", "RUSTSEC-2026-0381"),
    ("rustls", "0.23.46", "RUSTSEC-2026-0346..0349"),
)


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.repository.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    lock = root / "codex-rs/Cargo.lock"
    record = {
        "schema": "hepta.ci.tls-lock-candidate.v1",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "cargo_lock_before": checksum(lock),
        "bazel_lock_before": checksum(root / "MODULE.bazel.lock"),
        "updates": UPDATES,
        "commands": [],
        "promotion_allowed": False,
        "original_dependency_policy_unchanged": True,
        "validation": "Candidate generation only; normal regression CI and cargo-deny remain required.",
    }
    try:
        for name, version, advisory in UPDATES:
            packages = tomllib.loads(lock.read_text())["package"]
            target = version.split(".")[:2] if version.startswith("0.") else ["1"]
            matching = [
                item
                for item in packages
                if item["name"] == name
                and item["version"].split(".")[: len(target)] == target
            ]
            if len(matching) != 1:
                raise ValueError(f"Ambiguous current {name} dependency: {matching}")
            command = [
                "cargo",
                "update",
                "--manifest-path",
                str(root / "codex-rs/Cargo.toml"),
                "--package",
                f"{name}@{matching[0]['version']}",
                "--precise",
                version,
            ]
            with (output / f"update-{name}.log").open("wb") as stream:
                result = subprocess.run(
                    command, cwd=root, stdout=stream, stderr=subprocess.STDOUT
                )
            record["commands"].append(
                {"command": command, "exit_code": result.returncode}
            )
            if result.returncode:
                raise RuntimeError(
                    f"Dependency resolution failed for {name}; inspect its retained log"
                )
        with (output / "bazel-lock-update.log").open("wb") as stream:
            result = subprocess.run(
                ["just", "bazel-lock-update"],
                cwd=root,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
        record["commands"].append(
            {"command": ["just", "bazel-lock-update"], "exit_code": result.returncode}
        )
        if result.returncode:
            raise RuntimeError(
                "Bazel lock candidate failed; partial resolver evidence retained"
            )
        subprocess.run(["git", "diff", "--check"], cwd=root, check=True)
        packages = tomllib.loads(lock.read_text())["package"]
        for name, version, advisory in UPDATES:
            if not any(p["name"] == name and p["version"] == version for p in packages):
                raise ValueError(
                    f"The requested patched version of {name} did not resolve"
                )
        for path in (lock, root / "MODULE.bazel.lock"):
            shutil.copyfile(path, output / path.name)
        (output / "candidate.patch").write_bytes(
            subprocess.check_output(
                ["git", "diff", "--", "codex-rs/Cargo.lock", "MODULE.bazel.lock"],
                cwd=root,
            )
        )
        record.update(
            status="candidate_generated",
            cargo_lock_after=checksum(lock),
            bazel_lock_after=checksum(root / "MODULE.bazel.lock"),
        )
    except Exception as error:
        record.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        raise
    finally:
        (output / "RESULT.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
