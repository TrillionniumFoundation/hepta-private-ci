#!/usr/bin/env python3
"""Retain exact-source evidence for scoped runtime repairs and generated locks."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys


def git(*args):
    return subprocess.check_output(["git", *args])


def digest(path):
    data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def snapshot():
    files = {}
    for entry in git("ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, blob, stage = metadata.decode().split()
        if stage != "0" or mode not in {"100644", "100755", "120000"}:
            raise RuntimeError("unsupported or unmerged tracked entry")
        path = os.fsdecode(raw_path)
        actual_mode = Path(path).lstat().st_mode
        files[path] = {
            "mode": mode,
            "blob": blob,
            "file_type": stat.S_IFMT(actual_mode),
            "permissions": stat.S_IMODE(actual_mode),
            "sha256": digest(Path(path)),
        }
    return {
        "head": git("rev-parse", "HEAD").decode().strip(),
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "status": git("status", "--porcelain=v1", "--untracked-files=all").decode(),
        "files": files,
    }


def write_json(output, name, value):
    (output / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def run_command(output, label, command):
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"Running {label}: {command}", flush=True)
    error = None
    try:
        if label == "cargo-metadata":
            with (
                (output / f"{label}.stdout").open("wb") as stdout,
                (output / f"{label}.stderr").open("wb") as stderr,
            ):
                status = subprocess.run(
                    command, stdout=stdout, stderr=stderr
                ).returncode
        else:
            with (output / f"{label}.log").open("wb") as log:
                with subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
                ) as process:
                    for line in process.stdout:
                        log.write(line)
                        log.flush()
                        sys.stdout.buffer.write(line)
                        sys.stdout.buffer.flush()
                    status = process.wait()
    except OSError as exc:
        status = None
        error = str(exc)
    receipt = {
        "command": command,
        "started": started,
        "finished": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "exit_code": status,
        "error": error,
    }
    write_json(output, f"{label}.json", receipt)
    return status == 0


def verify_graph(output):
    metadata = json.loads((output / "cargo-metadata.stdout").read_bytes())
    packages = metadata["packages"]
    matches = [p for p in packages if p["name"] == "i18n-config"]
    expected = Path("codex-rs/third_party/i18n-config-0.4.8/Cargo.toml").resolve()
    if (
        len(matches) != 1
        or matches[0]["source"] is not None
        or Path(matches[0]["manifest_path"]).resolve() != expected
        or any(p["name"] == "basic-toml" for p in packages)
    ):
        raise RuntimeError("maintained i18n path patch is not the resolved graph")
    nodes = {n["id"]: n for n in metadata["resolve"]["nodes"]}
    toml = [
        p
        for p in packages
        if p["name"] == "toml" and p["version"] == "1.1.8+spec-1.1.0"
    ]
    if len(toml) != 1 or toml[0]["id"] not in nodes[matches[0]["id"]]["dependencies"]:
        raise RuntimeError("i18n-config does not use the existing maintained TOML")
    write_json(
        output,
        "resolved-parser.json",
        {
            "i18n_config": matches[0],
            "toml": toml[0],
            "toml_features": nodes[toml[0]["id"]]["features"],
            "metadata_sha256": digest(output / "cargo-metadata.stdout"),
        },
    )


def run_scope(output, scope):
    commands = [("rustc-version", ["rustc", "--version", "--verbose"])]
    if scope == "lock":
        commands += [
            ("bazel-version", ["bazel", "--version"]),
            (
                "cargo-metadata",
                [
                    "cargo",
                    "metadata",
                    "--manifest-path",
                    "codex-rs/Cargo.toml",
                    "--locked",
                    "--all-features",
                    "--format-version=1",
                ],
            ),
            ("bazel-lock-update", ["just", "bazel-lock-update"]),
            ("bazel-lock-check", ["just", "bazel-lock-check"]),
        ]
    else:
        package = {
            "operator": "codex-hepta-operator-acceptance",
            "secrets": "codex-secrets",
        }[scope]
        commands += [
            ("nextest-version", ["cargo", "nextest", "--version"]),
            (
                "original-tests",
                [
                    "just",
                    "test",
                    "-p",
                    package,
                    "--lib",
                    "--locked",
                    "--no-tests=fail",
                    "--retries",
                    "0",
                ],
            ),
            ("original-lint-fix", ["just", "fix", "-p", package]),
            ("original-format", ["just", "fmt"]),
        ]
    completed = []
    for label, command in commands:
        if not run_command(output, label, command):
            raise RuntimeError(f"scoped command failed: {label}")
        completed.append(label)
        if label == "cargo-metadata":
            verify_graph(output)
    write_json(output, "commands-complete.json", {"scope": scope, "stages": completed})


def finalize(output, scope):
    before = json.loads((output / "source-before.json").read_bytes())
    after = snapshot()
    allowed = {"MODULE.bazel.lock"} if scope == "lock" else set()
    changed = {
        path
        for path in before["files"] | after["files"]
        if before["files"].get(path) != after["files"].get(path)
    }
    changed.update(
        os.fsdecode(path)
        for path in git("diff", "HEAD", "--name-only", "-z").split(b"\0")
        if path
    )
    lock_shape_unchanged = all(
        {key: value for key, value in before["files"][path].items() if key != "sha256"}
        == {
            key: value for key, value in after["files"][path].items() if key != "sha256"
        }
        for path in allowed
    )
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").decode()
    complete = (output / "commands-complete.json").is_file()
    qualified = (
        before["head"] == after["head"] == os.environ["SOURCE_HEAD"]
        and before["tree"] == after["tree"]
        and set(before["files"]) == set(after["files"])
        and not before["status"]
        and not untracked
        and changed <= allowed
        and lock_shape_unchanged
        and complete
        and os.environ.get("SCOPE_OUTCOME") == "success"
    )
    if scope == "lock":
        for name, path in [
            ("MODULE.bazel.lock", "MODULE.bazel.lock"),
            ("Cargo.lock", "codex-rs/Cargo.lock"),
        ]:
            shutil.copyfile(path, output / name)
    write_json(output, "source-after.json", after)
    write_json(
        output,
        "result.json",
        {
            "scope": scope,
            "head": after["head"],
            "tree": after["tree"],
            "allowed_changes": sorted(allowed),
            "changed": sorted(changed),
            "lock_shape_unchanged": lock_shape_unchanged,
            "untracked": untracked,
            "all_commands_completed": complete,
            "scoped_commands_and_source_conservation_passed": qualified,
            "full_pr_qualification": False,
        },
    )
    records = {
        path.name: digest(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "artifact-sha256.json"
    }
    write_json(output, "artifact-sha256.json", records)
    if not qualified:
        raise RuntimeError("scoped commands or exact-source conservation incomplete")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["freeze", "run", "finalize"])
    parser.add_argument("scope", choices=["lock", "operator", "secrets"])
    args = parser.parse_args()
    output = Path(os.environ["EVIDENCE_DIR"])
    if args.operation == "freeze":
        output.mkdir(parents=True)
        before = snapshot()
        if before["head"] != os.environ["SOURCE_HEAD"] or before["status"]:
            raise RuntimeError("checkout must be the exact clean source head")
        write_json(output, "source-before.json", before)
    elif args.operation == "run":
        run_scope(output, args.scope)
    else:
        finalize(output, args.scope)


if __name__ == "__main__":
    main()
