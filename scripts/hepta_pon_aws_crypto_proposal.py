#!/usr/bin/env python3
"""Generate a hosted AWS crypto source/lock proposal; never qualify a dirty tree.

The local static entry point only reads and hashes source data. Cargo, Rust and
Bazel execution is restricted to the exact-source hosted workflow. Final native
qualification must run again after a reviewed import commits every source file
and both actual generated locks together.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib

from hepta_pon_aws_crypto_source import (
    INPUTS,
    REGISTRY,
    VENDOR,
    change_workspace,
    identity,
    require,
    retain_files,
    source_proposal,
    static_review,
)

from hepta_pon_dependency_proposal import (
    ROOT,
    TARGETS as PREVIOUS_TARGETS,
    git,
    interrupted_stages,
    now,
    require_hosted,
    write_json,
)


TARGETS = {
    **PREVIOUS_TARGETS,
    "aws-sigv4": (
        "1.6.4",
        "f385da9b7757ed4c8214797ad663ff534fb622006143530aa80e21f8e06ff85c",
    ),
    "p256": (
        "0.14.0",
        "d2c9239b2dbc807adbbe147e8cf72ea7450c3a0aabe62cb8e75ff4ec22e1f72a",
    ),
    "crypto-bigint": (
        "0.7.10",
        "9c035cb64cba03dad2fb921f3e218785e8cf9a41790da5eb3a1400f62fa2be11",
    ),
}
COMMANDS = (
    ("cargo-version", ".", ["cargo", "+1.96.0", "--version", "--verbose"]),
    ("bazel-version", ".", ["bazel", "--version"]),
    ("just-version", ".", ["just", "--version"]),
    ("source-preflight", ".", ["python3", "-B", "scripts/hepta_workspace.py"]),
    (
        "cargo-update-sigv4",
        "codex-rs",
        ["cargo", "+1.96.0", "update", "--package", "aws-sigv4", "--precise", "1.6.4"],
    ),
    (
        "cargo-update-bigint",
        "codex-rs",
        [
            "cargo",
            "+1.96.0",
            "update",
            "--package",
            "crypto-bigint",
            "--precise",
            "0.7.10",
        ],
    ),
    (
        "cargo-fmt-provider",
        "codex-rs",
        [
            "cargo",
            "+1.96.0",
            "fmt",
            "--package",
            "aws-config",
            "--",
            "--config",
            "imports_granularity=Item",
        ],
    ),
    (
        "cargo-metadata-all-features",
        "codex-rs",
        [
            "cargo",
            "+1.96.0",
            "metadata",
            "--locked",
            "--all-features",
            "--format-version",
            "1",
        ],
    ),
    (
        "cargo-metadata-sigv4a",
        "codex-rs/aws-auth",
        [
            "cargo",
            "+1.96.0",
            "metadata",
            "--locked",
            "--features",
            "aws-sigv4/sigv4a",
            "--format-version",
            "1",
        ],
    ),
    ("bazel-lock-update", ".", ["just", "bazel-lock-update"]),
    ("bazel-lock-check", ".", ["just", "bazel-lock-check"]),
)


def prepare(output, source):
    require_hosted(source, output)
    require(not output.exists(), "refusing to combine or overwrite proposals")
    require(
        not git("status", "--porcelain", "--untracked-files=normal"),
        "source checkout must start clean",
    )
    output.mkdir(parents=True)
    (output / "logs").mkdir()
    record = {
        "schema": "hepta-aws-crypto-hosted-proposal-v1",
        "source": source,
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "github_run_sha": os.environ.get("GITHUB_SHA"),
        "github_event_name": os.environ.get("GITHUB_EVENT_NAME"),
        "github_ref": os.environ.get("GITHUB_REF"),
        "started_at_utc": now(),
        "proposal_only": True,
        "committed_source_qualified": False,
        "bigint_blocker_closed": False,
        "all_advisories_closed": False,
        "native_builds_or_tests_requested": False,
        "hosted_rustfmt_requested": True,
        "timeout_policy": "GitHub step timeout; no PID killing; interrupted outcome remains unknown",
        "original": {},
        "state": "preparing",
        "stages": [
            {
                "name": name,
                "cwd": cwd,
                "command": command,
                "state": "not_started",
                "exit_code": None,
            }
            for name, cwd, command in COMMANDS
        ],
    }
    write_json(output / "record.json", record)
    for name in INPUTS:
        path = ROOT / name
        require(
            path.is_file() and not path.is_symlink(),
            "original input must be a regular file",
        )
        raw = path.read_bytes()
        retain_files(output / "original", {name: raw})
        record["original"][name] = identity(raw)
        write_json(output / "record.json", record)
    record["static_source_review"] = static_review()
    require(not (ROOT / VENDOR).exists(), "provider patch path already exists")
    _, _, proposed = source_proposal()
    retain_files(output / "prepared-vendor", proposed)
    record["prepared_vendor"] = {
        name: identity(raw) for name, raw in sorted(proposed.items())
    }
    record["state"] = "prepared"
    write_json(output / "record.json", record)


def run(output, source):
    require_hosted(source, output)
    record = json.loads((output / "record.json").read_text())
    require(
        record["source"] == source and record["state"] == "prepared",
        "not an untouched prepared source",
    )
    require(
        not git("status", "--porcelain", "--untracked-files=normal"),
        "checkout changed after preparation",
    )
    static_review()
    for name, expected in record["original"].items():
        require(
            identity((ROOT / name).read_bytes()) == expected,
            "prepared original changed",
        )
    _, _, proposed = source_proposal()
    require(
        not (ROOT / VENDOR).exists() and not (ROOT / VENDOR).is_symlink(),
        "provider destination appeared after preparation",
    )
    retain_files(ROOT / VENDOR, proposed)
    manifest = ROOT / INPUTS[0]
    manifest.write_bytes(change_workspace(manifest.read_bytes()))
    record["state"] = "running"
    write_json(output / "record.json", record)
    for stage in record["stages"]:
        stage.update(state="running", started_at_utc=now())
        write_json(output / "record.json", record)
        started = time.monotonic()
        with (
            (output / "logs" / (stage["name"] + ".stdout.txt")).open("wb") as stdout,
            (output / "logs" / (stage["name"] + ".stderr.txt")).open("wb") as stderr,
        ):
            try:
                code = subprocess.run(
                    stage["command"],
                    cwd=ROOT / stage["cwd"],
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                ).returncode
            except OSError as error:
                stage.update(
                    state="launch_failed",
                    launch_error=str(error),
                    exit_code=None,
                    wall_seconds=time.monotonic() - started,
                    finished_at_utc=now(),
                )
                record["state"] = "failed"
                write_json(output / "record.json", record)
                return 1
        stage.update(
            state="succeeded" if code == 0 else "failed",
            exit_code=code,
            wall_seconds=time.monotonic() - started,
            finished_at_utc=now(),
        )
        if code:
            record["state"] = "failed"
            write_json(output / "record.json", record)
            return code if code > 0 else 1
        write_json(output / "record.json", record)
    record["state"] = "generated"
    write_json(output / "record.json", record)
    return 0


def check_lock(raw):
    packages = tomllib.loads(raw.decode())["package"]
    selected = {}
    for name, (version, checksum) in TARGETS.items():
        matches = [package for package in packages if package["name"] == name]
        require(len(matches) == 1, "duplicate or missing target: " + name)
        package = matches[0]
        require(
            package["version"] == version
            and package.get("checksum") == checksum
            and package.get("source") == REGISTRY,
            "unreviewed resolved package: " + name,
        )
        selected[name] = {
            key: package[key] for key in ("version", "source", "checksum")
        }
    configs = [package for package in packages if package["name"] == "aws-config"]
    require(
        len(configs) == 1
        and configs[0]["version"] == "1.8.12"
        and not configs[0].get("source")
        and not configs[0].get("checksum"),
        "provider must resolve to the single explicit path patch",
    )
    return selected


def check_metadata(raw, sigv4a):
    metadata = json.loads(raw)
    packages = {package["id"]: package for package in metadata["packages"]}
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    configs = [
        package for package in packages.values() if package["name"] == "aws-config"
    ]
    require(len(configs) == 1, "metadata provider identity is ambiguous")
    config = configs[0]
    require(
        config["manifest_path"] == str(ROOT / VENDOR / "Cargo.toml")
        and config["id"] in metadata["workspace_members"],
        "provider source or workspace ownership differs",
    )
    features = set(nodes[config["id"]]["features"])
    require(
        {
            "credentials-login",
            "credentials-process",
            "default",
            "default-https-client",
            "rt-tokio",
            "sso",
        }
        <= features,
        "provider feature regression",
    )
    signing = [
        package for package in packages.values() if package["name"] == "aws-sigv4"
    ]
    require(
        len(signing) == 1
        and signing[0]["version"] == "1.6.4"
        and signing[0]["source"] == REGISTRY,
        "metadata signer identity differs",
    )
    signer_features = nodes[signing[0]["id"]]["features"]
    if sigv4a:
        require(
            "sigv4a" in signer_features,
            "explicit SigV4a metadata did not activate SigV4a",
        )
    for name, (version, _) in TARGETS.items():
        require(
            [
                package["version"]
                for package in packages.values()
                if package["name"] == name
            ]
            == [version],
            "metadata legacy or duplicate target: " + name,
        )
    return {
        "packages": len(packages),
        "nodes": len(nodes),
        "workspace_members": len(metadata["workspace_members"]),
        "provider_features": sorted(features),
        "signer_features": sorted(signer_features),
        "full_graph_import_review_pending": True,
    }


def finalize(output, source):
    require_hosted(source, output)
    record = json.loads((output / "record.json").read_text())
    require(record["source"] == source, "finalizer source mismatch")
    record["interrupted_or_unknown_stages"] = interrupted_stages(record["stages"])
    record["workflow_proposal_step_outcome"] = os.environ.get(
        "PROPOSAL_STEP_OUTCOME", "unknown"
    )
    record["finalized_at_utc"] = now()
    errors = []
    _, _, prepared = source_proposal()
    changed = git("diff", "--name-only").splitlines()
    record["changed_tracked_paths"] = changed
    current_vendor = {}
    try:
        require(record["state"] != "preparing", "source preparation incomplete")
        require(
            set(changed) <= set(INPUTS) and not git("diff", "--cached", "--name-only"),
            "unapproved tracked or staged mutation",
        )
        require(
            all(
                path.startswith(VENDOR + "/")
                for path in git(
                    "ls-files", "--others", "--exclude-standard"
                ).splitlines()
            ),
            "unexpected untracked source",
        )
        for name, expected in record["original"].items():
            require(
                identity((output / "original" / name).read_bytes()) == expected,
                "retained original changed",
            )
        require(
            (ROOT / INPUTS[0]).read_bytes()
            == change_workspace((output / "original" / INPUTS[0]).read_bytes()),
            "workspace mutation outside declared scope",
        )
        for path in (ROOT / VENDOR).rglob("*"):
            require(not path.is_symlink(), "unexpected vendor symlink")
            if path.is_file():
                current_vendor[path.relative_to(ROOT / VENDOR).as_posix()] = (
                    path.read_bytes()
                )
        require(set(current_vendor) == set(prepared), "vendor file inventory changed")
        rust_changes = []
        for name, raw in current_vendor.items():
            if raw != prepared[name]:
                require(
                    name.endswith(".rs"), "non-Rust vendor content changed: " + name
                )
                rust_changes.append(name)
        record["hosted_rustfmt_changed_source_files"] = sorted(rust_changes)
        record["hosted_rustfmt_semantics_review_pending"] = bool(rust_changes)
        record["selected_locked_targets"] = check_lock((ROOT / INPUTS[1]).read_bytes())
        record["metadata"] = {
            name: check_metadata(
                (output / "logs" / (name + ".stdout.txt")).read_bytes(), sigv4a
            )
            for name, sigv4a in (
                ("cargo-metadata-all-features", False),
                ("cargo-metadata-sigv4a", True),
            )
        }
    except (ValueError, KeyError, OSError) as error:
        errors.append(str(error))
    for name in INPUTS:
        target = output / "proposal" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            require(not (ROOT / name).is_symlink(), "symlink proposal input")
            shutil.copyfile(ROOT / name, target)
        except (OSError, ValueError) as error:
            errors.append(str(error))
    retain_files(output / "proposal" / VENDOR, current_vendor)
    (output / "workspace-and-locks.patch").write_bytes(
        subprocess.check_output(["git", "diff", "--binary", "--", *INPUTS], cwd=ROOT)
    )
    record["review_errors"] = errors
    record["ready_for_review"] = (
        record["state"] == "generated"
        and not errors
        and not record["interrupted_or_unknown_stages"]
    )
    record["full_graph_and_formatted_source_review_required"] = True
    write_json(output / "record.json", record)
    entries = [
        {"path": path.relative_to(output).as_posix(), **identity(path.read_bytes())}
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "files.json"
    ]
    write_json(
        output / "files.json",
        {"schema": "hepta-aws-crypto-proposal-files-v1", "files": entries},
    )
    print(
        json.dumps(
            {
                "state": record["state"],
                "ready_for_review": record["ready_for_review"],
                "committed_source_qualified": False,
                "bigint_blocker_closed": False,
                "errors": errors,
            }
        )
    )
    return 0 if record["ready_for_review"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("static", "prepare", "run", "finalize"))
    parser.add_argument("--source")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "static":
            require(
                args.source is None and args.output is None,
                "static mode accepts no hosted source/output",
            )
            print(json.dumps(static_review(), indent=2))
            return 0
        require(
            args.source is not None and args.output is not None,
            "hosted modes require source and output",
        )
        output = args.output.resolve()
        if args.mode == "prepare":
            prepare(output, args.source)
            return 0
        if args.mode == "run":
            return run(output, args.source)
        return finalize(output, args.source)
    except (
        ValueError,
        KeyError,
        OSError,
        subprocess.CalledProcessError,
        tarfile.TarError,
    ) as error:
        print("AWS crypto proposal rejected: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
