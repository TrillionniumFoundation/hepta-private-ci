#!/usr/bin/env python3
"""Selected FinalUse PQ CI observations; no release or whole-chain qualification."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

import hepta_ci_exec as owner

BRANCH = "fix/hepta-final-use-mldsa65-v2-20261029"
LOCK = "MODULE.bazel.lock"
BUILD_COMMAND = [
    "cargo",
    "build",
    "--manifest-path",
    "codex-rs/Cargo.toml",
    "-p",
    "codex-cli",
    "--bin",
    "codex",
    "--locked",
    "--message-format=json",
]
HOST_CASES = (
    "final_use_authorizer::ml_dsa65_v2::tests::"
    "protected_v2_configuration_real_issuer_and_unix_claim_reach_original_use_entry",
    "final_use_authorizer::ml_dsa65_v2::tests::"
    "pq_unix_profile_refuses_legacy_port_and_real_classical_grant_without_claiming",
    "final_use_authorizer::ml_dsa65_v2::tests::"
    "pq_external_signature_file_courier_uses_the_same_owner_and_cannot_replay",
    "final_use_authorizer::ml_dsa65_v2::tests::"
    "maximum_pq_signature_carrier_and_grant_fit_original_transport_limits",
    "final_use_authorizer::ml_dsa65_v2::tests::"
    "v2_configuration_rejects_unknown_schema_and_classical_key_before_opening_an_owner",
    "native_app_server::tests::pq_final_use::"
    "real_agentd_turn_start_consumes_explicit_pq_config_and_external_mldsa_grant",
)


def pr_source():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    head = event["pull_request"]["head"]
    if (
        os.environ.get("GITHUB_EVENT_NAME") != "pull_request"
        or head["ref"] != BRANCH
        or head["repo"]["full_name"] != os.environ.get("GITHUB_REPOSITORY")
    ):
        raise ValueError(
            "only the explicit same-repository candidate PR may select this gate"
        )
    return head["sha"]


def selection(phase, source, event_source):
    if phase not in ("lock-artifact", "native"):
        raise ValueError("unknown selected FinalUse PQ phase")
    if re.fullmatch(r"[0-9a-f]{40}", source) is None or source != event_source:
        raise ValueError("selected source must equal the actual PR head commit")


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as stream:
        pending = Path(stream.name)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def tracked_inputs(root):
    result = {}
    for name in owner.git("ls-files", "-z", repository=root).split("\0"):
        if not name or name == LOCK:
            continue
        path = root / name
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            content = os.fsencode(os.readlink(path))
            result[name] = ["symlink", hashlib.sha256(content).hexdigest()]
        elif stat.S_ISREG(mode):
            result[name] = [stat.S_IMODE(mode), digest(path)]
        else:
            raise ValueError(f"unsupported tracked input: {name}")
    return result


def require_lock_only(root, before):
    if tracked_inputs(root) != before:
        raise ValueError("lock generation changed another tracked input")
    if owner.git("diff", "--cached", "--name-only", repository=root):
        raise ValueError("lock generation changed the index")
    if owner.git("ls-files", "--others", "--exclude-standard", repository=root):
        raise ValueError("lock generation created an untracked input")
    if any(
        row and (row[0] == "S" or row[0].islower())
        for row in owner.git("ls-files", "-v", "-z", repository=root).split("\0")
    ):
        raise ValueError("lock generation hid a tracked input")
    path = root / LOCK
    if path.is_symlink() or not path.is_file():
        raise ValueError("generated lock must be a regular file")


def lock_artifact(root, output):
    current = owner.identity()
    if current["dirty"] or current["commit"] != os.environ.get("SOURCE_SHA"):
        raise ValueError("lock proposal requires the unchanged selected source")
    record = {
        "schema_version": 1,
        "status": "running",
        "qualification": False,
        "source": current,
        "workflow_event_commit": os.environ.get("GITHUB_SHA"),
        "command": ["just", "bazel-lock-update"],
    }
    write_json(output / "manifest.json", record)
    parent = Path(tempfile.mkdtemp(prefix="hepta-pq-lock-", dir=output.parent))
    worktree = parent / "checkout"
    created = False
    previous_root = os.environ.get("CODEX_REPO_ROOT")
    try:
        owner.git(
            "-c",
            "core.hooksPath=" + os.devnull,
            "worktree",
            "add",
            "--detach",
            str(worktree),
            record["source"]["commit"],
            repository=root,
        )
        created = True
        clean = owner.identity(repository=worktree)
        if clean["dirty"] or clean["commit"] != record["source"]["commit"]:
            raise ValueError("diagnostic worktree differs from selected clean source")
        before = tracked_inputs(worktree)
        record["old_lock_sha256"] = digest(worktree / LOCK)
        os.chdir(worktree)
        os.environ["CODEX_REPO_ROOT"] = str(worktree)
        try:
            record["execution"] = owner.execute_logged(
                record["command"],
                output / "bazel-lock-update.log",
                timeout_seconds=2100,
            )
        finally:
            record["shutdown"] = owner.execute_logged(
                ["bazel", "shutdown"], output / "bazel-shutdown.log", timeout_seconds=60
            )
        require_lock_only(worktree, before)
        shutil.copyfile(worktree / LOCK, output / LOCK)
        record["new_lock_sha256"] = digest(output / LOCK)
        record["other_tracked_inputs_sha256"] = hashlib.sha256(
            json.dumps(before, sort_keys=True).encode()
        ).hexdigest()
        patch = owner.git(
            "diff",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            "--",
            LOCK,
            repository=worktree,
        )
        (output / "MODULE.bazel.lock.patch").write_text(patch + ("\n" if patch else ""))
        for execution in (record["execution"], record["shutdown"]):
            if (
                execution["returncode"]
                or execution["timed_out"]
                or execution["output_limit_exceeded"]
            ):
                raise ValueError(
                    "real Bazel command or shutdown failed; artifact is unqualified"
                )
        record["status"] = "artifact-produced"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        record.update(status="failed", error=str(error))
    finally:
        os.chdir(root)
        if previous_root is None:
            os.environ.pop("CODEX_REPO_ROOT", None)
        else:
            os.environ["CODEX_REPO_ROOT"] = previous_root
        try:
            if created:
                owner.git(
                    "-c",
                    "core.hooksPath=" + os.devnull,
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree),
                    repository=root,
                )
            parent.rmdir()
        except (OSError, subprocess.SubprocessError) as error:
            record.update(status="failed", cleanup_error=str(error))
        write_json(output / "manifest.json", record)
    return 0 if record["status"] == "artifact-produced" else 1


def select_codex(log, root, target):
    selected = []
    finished = []
    for line in log.read_text().splitlines():
        if not line.startswith("{"):
            continue
        row = json.loads(line)
        if row.get("reason") == "build-finished":
            finished.append(row.get("success"))
        if (
            row.get("reason") != "compiler-artifact"
            or row.get("target", {}).get("name") != "codex"
        ):
            continue
        artifact = row["target"]
        package = "path+" + (root / "codex-rs/cli").as_uri() + "#codex-cli@"
        executable = Path(row.get("executable") or "")
        if (
            artifact.get("kind") != ["bin"]
            or row.get("fresh") is not False
            or not row.get("package_id", "").startswith(package)
            or Path(artifact.get("src_path", "")).resolve()
            != root / "codex-rs/cli/src/main.rs"
            or not executable.is_absolute()
            or executable.is_symlink()
            or not executable.resolve().is_relative_to(target.resolve())
            or not executable.is_file()
            or not os.access(executable, os.X_OK)
        ):
            raise ValueError(
                "codex artifact is not the actual selected fresh target executable"
            )
        with executable.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                raise ValueError("native Linux codex artifact must be ELF")
        selected.append(executable.resolve())
    if finished != [True] or len(selected) != 1:
        raise ValueError(
            "one successful build and one unambiguous codex artifact are required"
        )
    return selected[0]


def build_binding(build_record, root, target):
    record = json.loads(build_record.read_text())
    current = owner.identity()
    if (
        current["dirty"]
        or record.get("status") != "passed"
        or record.get("command") != BUILD_COMMAND
        or record.get("command_exit_code") != 0
        or record.get("source_sha") != os.environ.get("SOURCE_SHA")
        or record.get("tested_sha") != current["commit"]
        or record.get("working_directory") != str(root)
        or record.get("before") != current
        or record.get("after") != current
    ):
        raise ValueError("codex build record is not for the unchanged selected source")
    name = record.get("log_file", "")
    if not name or Path(name).name != name:
        raise ValueError("build log must be owned by its execution record")
    log = build_record.parent / name
    if digest(log) != record.get("log_sha256"):
        raise ValueError("codex build log changed")
    executable = select_codex(log, root, target)
    return {
        "source": current,
        "executable": str(executable),
        "sha256": digest(executable),
        "build_record_sha256": digest(build_record),
        "build_log_sha256": digest(log),
        "workflow_event_commit": os.environ.get("GITHUB_SHA"),
    }


def native(root, output, build_record):
    if "RUNFILES_MANIFEST_ONLY" in os.environ:
        raise ValueError("Cargo CI must not select a Bazel runfiles resolver")
    target = Path(os.environ["CARGO_TARGET_DIR"])
    if not target.is_absolute() or target.resolve().is_relative_to(root):
        raise ValueError("selected fresh Cargo target must be outside source")
    binding = build_binding(build_record, root, target)
    write_json(output / "codex-binding.json", binding)
    executable = Path(binding["executable"])
    # The original Cargo/Bazel binary resolver gives this explicit key priority;
    # native_pq_final_use_tests passes its result to CognitiveTestHost::start.
    os.environ["CARGO_BIN_EXE_codex"] = str(executable)
    cases = [
        (
            "contracts",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-contracts",
                "--lib",
                "--test",
                "final_use_linearization",
                "-E",
                "test(final_use) | binary(=final_use_linearization)",
                "--test-threads",
                "1",
            ],
            42,
        ),
        (
            "host-v1",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-infer-worker-host",
                "--lib",
                "-E",
                "test(final_use) & !test(ml_dsa65_v2) & !test(pq_final_use)",
                "--test-threads",
                "1",
            ],
            1,
        ),
    ]
    cases.extend(
        (
            f"host-pq-{index}",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-infer-worker-host",
                "--lib",
                "-E",
                f"test(={case})",
                "--test-threads",
                "1",
            ],
            1,
        )
        for index, case in enumerate(HOST_CASES, 1)
    )
    failed = False
    for label, command, minimum in cases:
        if digest(executable) != binding["sha256"]:
            raise ValueError("selected codex changed before a native test")
        failed |= (
            owner.run(
                output / f"{label}.json",
                command,
                minimum_tests=minimum,
                timeout_seconds=3600,
            )
            != 0
        )
        if digest(executable) != binding["sha256"]:
            raise ValueError("selected codex changed during a native test")
    binaries = [executable]
    for pattern in (
        "codex_hepta_contracts-*",
        "codex_hepta_infer_worker_host-*",
        "final_use_linearization-*",
    ):
        binaries.extend(
            path
            for path in (target / "debug/deps").glob(pattern)
            if path.is_file() and not path.is_symlink() and os.access(path, os.X_OK)
        )
    manifest = []
    for path in binaries:
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        destination = output / (path.name + ".elf.gz")
        with (
            path.open("rb") as source,
            gzip.open(destination, "xb", compresslevel=1) as compressed,
        ):
            shutil.copyfileobj(source, compressed)
        manifest.append(
            {
                "path": str(path),
                "sha256": digest(path),
                "gzip_sha256": digest(destination),
            }
        )
    write_json(output / "binary-artifacts.json", manifest)
    write_json(
        output / "result.json",
        {
            "status": "failed" if failed else "passed",
            "qualification": False,
            "scope": "FinalUse component and mock-provider AppServer observations",
            "whole_pipeline_pq": False,
            "binding": binding,
        },
    )
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("lock-artifact", "native"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-record", type=Path)
    args = parser.parse_args()
    try:
        selection(args.phase, os.environ.get("SOURCE_SHA", ""), pr_source())
        root = Path(owner.git("rev-parse", "--show-toplevel")).resolve()
        if not args.output.is_absolute() or args.output.resolve().is_relative_to(root):
            raise ValueError("PQ observations must be outside the source checkout")
        args.output.mkdir()
        if args.phase == "lock-artifact":
            return lock_artifact(root, args.output)
        if args.build_record is None:
            raise ValueError(
                "native observations require the actual codex build record"
            )
        return native(root, args.output, args.build_record)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"FinalUse PQ observation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
