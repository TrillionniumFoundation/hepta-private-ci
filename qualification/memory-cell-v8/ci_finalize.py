"""Finalize exactly verified V8 sources without tests, fitting, commits or pushes."""

import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time


ROOT = Path(__file__).resolve().parents[2]
REQUEST = Path(__file__).with_name("FINALIZE_REQUEST.json")
BASE = "0b0b041b6dd8121050c335cb3be73bb1d8cb7904"
RAW_PATCH_LIMIT = 512_000
PACKAGE_NAMES = ("cognitive-types", "neuron", "memory", "cognitive-store", "learning-artifacts",
                 "agent-protocol", "agentd", "context-compiler", "infer-worker-host", "plasticity")
PACKAGES = ["codex-hepta-" + name for name in PACKAGE_NAMES]
FIX_ROOTS = tuple("codex-rs/hepta-" + name + "/" for name in PACKAGE_NAMES)
PYTHON_ROOTS = ("qualification/memory-cell-v6", "qualification/memory-cell-v7", "qualification/memory-cell-v8")
SOURCE_SCOPES = [
    "codex-rs", "justfile", "scripts/format.py", "scripts/just-shell.py", "scripts/run-nextest.py",
    "scripts/pyproject.toml", "scripts/uv.lock", ".github/actions/setup-ci",
    ".github/workflows/memory-cell-v8.yml", ".github/workflows/memory-cell-v8-finalize.yml",
    "qualification/memory-cell-v6/v6", "qualification/memory-cell-v7/addressing",
    "qualification/memory-cell-v7/fixtures", "qualification/memory-cell-v8/addressing",
    "qualification/memory-cell-v8/learning", "qualification/memory-cell-v8/fixtures",
    "evaluation_preflight.py",
]


def git(*arguments, env=None):
    return subprocess.check_output(["git", *arguments], cwd=ROOT, env=env)


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write_json(path, value):
    with path.open("xb") as handle:
        handle.write((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate finalization evidence field")
        result[key] = value
    return result


def read_json(path, maximum):
    if any(item.is_symlink() for item in (path, *path.parents)) or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("unsafe or oversized finalization evidence")
    raw = path.read_bytes()
    return raw, json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite evidence number")))


def paths(*arguments):
    return sorted(os.fsdecode(path) for path in git(*arguments).split(b"\0") if path)


def python_inventory(revision):
    return [name for name in paths("ls-tree", "-r", "--name-only", "-z", revision, "--", *PYTHON_ROOTS,
                                   "evaluation_preflight.py") if name.endswith(".py")]


def file_identity(name):
    path = ROOT / name
    if path.is_symlink():
        return {"kind": "symlink", **identity(os.fsencode(os.readlink(path)))}
    if not path.exists():
        return {"kind": "deleted"}
    return {"kind": "file", "mode": oct(path.stat().st_mode & 0o777), **identity(path.read_bytes())}


def tracked_tree(output):
    # Only this private index is updated. The checkout index and branch stay put.
    index = output / "temporary.index"
    environment = {**os.environ, "GIT_INDEX_FILE": str(index)}
    try:
        git("read-tree", "HEAD", env=environment)
        git("add", "-u", "--", ".", env=environment)
        return git("write-tree", env=environment).decode().strip()
    finally:
        index.unlink(missing_ok=True)


def patch_bytes(revision):
    return git("diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv", "--no-color",
               "--no-renames", revision, "--")


def retain_patch(output, name, raw):
    compressed = name + ".xz"
    with (output / compressed).open("xb") as handle:
        handle.write(lzma.compress(raw, preset=6))
    direct = name if len(raw) <= RAW_PATCH_LIMIT else None
    if direct is not None:
        with (output / direct).open("xb") as handle:
            handle.write(raw)
    return {"uncompressed": identity(raw), "compressed": {"path": compressed, **identity((output / compressed).read_bytes())},
            "standalone_uncompressed_path": direct,
            "transport": "compressed artifact only; never console/base64 or direct Git blob" if direct is None else "artifact files",
            "raw_patch_limit_bytes": RAW_PATCH_LIMIT}


def execute(command, output, log, executions):
    number = len(executions) + 1
    command_path = output / "commands" / f"{number:02}.output.log"
    command_path.parent.mkdir(exist_ok=True)
    entry = {"command": command, "exit_code": None, "raw_output_path": str(command_path.relative_to(output))}
    executions.append(entry)
    started = time.monotonic()
    log.write(("COMMAND " + json.dumps(command) + "\n").encode())
    log.flush()
    try:
        with command_path.open("xb") as raw_log, subprocess.Popen(
                command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
            while data := process.stdout.read1(65_536):
                raw_log.write(data)
                raw_log.flush()
                log.write(data)
                log.flush()
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            entry["exit_code"] = process.wait()
    except OSError as error:
        entry["spawn_or_io_error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        entry["wall_seconds"] = time.monotonic() - started
        if command_path.exists():
            entry["raw_output"] = identity(command_path.read_bytes())
        log.write(("\nEXIT " + json.dumps(entry["exit_code"]) + "\n").encode())
        log.flush()
    if entry["exit_code"] != 0:
        raise RuntimeError(f"command failed with exit {entry['exit_code']}: {command[0]}")


def retain_stage(output, receipt, name, before_tree):
    after_tree = tracked_tree(output)
    stage = {"stage": name, "before_tracked_tree": before_tree, "after_tracked_tree": after_tree,
             "incremental_patch": retain_patch(output, name + ".patch", patch_bytes(before_tree)),
             "cumulative_patch": retain_patch(output, name + ".from-head.patch", patch_bytes("HEAD"))}
    receipt["stages"].append(stage)
    write_json(output / (name + ".json"), stage)
    return after_tree


def freeze_check(receipt):
    current = {name: file_identity(name) for name in receipt["frozen_python"]}
    if current != receipt["frozen_python"]:
        raise ValueError("final fix/format changed frozen Python bytes or modes")
    untracked = paths("ls-files", "--others", "--exclude-standard", "-z", "--", *SOURCE_SCOPES, *PYTHON_ROOTS)
    if untracked:
        raise ValueError("untracked protected source appeared: " + json.dumps(untracked))


def verify_request(output, receipt, log):
    raw, request = read_json(REQUEST, 65_536)
    with (output / "FINALIZE_REQUEST.json").open("xb") as handle:
        handle.write(raw)
    receipt["request"], receipt["request_identity"] = request, identity(raw)
    if (not isinstance(request, dict)
            or set(request) != {"schema", "tested_commit", "format_base", "packages", "verification_receipt"}
            or request["schema"] != "hepta.memory.v8.finalize-request.v1"
            or not isinstance(request["tested_commit"], str) or re.fullmatch(r"[0-9a-f]{40}", request["tested_commit"]) is None
            or request["format_base"] != BASE or not isinstance(request["packages"], list)
            or len(request["packages"]) != len(PACKAGES) or set(request["packages"]) != set(PACKAGES)):
        raise ValueError("exact tested commit, fixed V6 format base, receipt binding and ten scoped packages required")
    declared = request["verification_receipt"]
    if (not isinstance(declared, dict) or set(declared) != {"path", "bytes", "sha256"}
            or not isinstance(declared["path"], str) or not declared["path"]
            or type(declared["bytes"]) is not int or not 1 <= declared["bytes"] <= 8_000_000
            or not isinstance(declared["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", declared["sha256"]) is None):
        raise ValueError("invalid exact verification receipt declaration")
    relative = Path(declared["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("verification receipt must be within the checkout")
    evidence_raw, evidence = read_json(ROOT / relative, 8_000_000)
    with (output / "TESTED_VERIFICATION_RECEIPT.json").open("xb") as handle:
        handle.write(evidence_raw)
    tested = receipt["tested_commit"] = request["tested_commit"]
    receipt["tested_tree"] = git("rev-parse", f"{tested}^{{tree}}").decode().strip()
    if (identity(evidence_raw) != {key: declared[key] for key in ("bytes", "sha256")}
            or not isinstance(evidence, dict) or evidence.get("schema") != "hepta.memory.v8.product-ci-receipt.v1"
            or evidence.get("passed") is not True or evidence.get("source_commit") != tested
            or evidence.get("source_tree") != receipt["tested_tree"]
            or evidence.get("initial_tracked_changes") != "" or evidence.get("final_tracked_changes") != ""
            or evidence.get("missing_required_receipts") != []):
        raise ValueError("successful V8 CI receipt does not bind the exact tested source and clean checkout")
    executions = evidence.get("executions")
    if (not isinstance(executions, list) or not executions
            or any(not isinstance(item, dict) or item.get("exit_code") != 0
                   or item.get("test_discovery_nonempty", True) is not True for item in executions)):
        raise ValueError("verification receipt contains incomplete or failed commands")
    test_commands = [item.get("command") for item in executions
                     if isinstance(item.get("command"), list) and item["command"][:2] == ["just", "test"]]
    if not any("--run-ignored" not in command for command in test_commands) or not any(
            "--run-ignored" in command and "only" in command for command in test_commands):
        raise ValueError("both ordinary and actual ignored native tests must have completed before finalization")
    receipt["verification_receipt_identity"] = {"path": declared["path"], **identity(evidence_raw)}
    frozen = sorted(set(python_inventory(tested)) | set(python_inventory("HEAD")))
    receipt["source_gate_paths"] = sorted(set(SOURCE_SCOPES) | set(frozen))
    if receipt["initial_tracked_changes"] or paths("ls-files", "--others", "--exclude-standard", "-z", "--",
                                                   *SOURCE_SCOPES, *PYTHON_ROOTS):
        raise ValueError("finalization requires a clean protected source checkout")
    for earlier, later in ((BASE, tested), (tested, "HEAD")):
        execute(["git", "merge-base", "--is-ancestor", earlier, later], output, log, receipt["executions"])
    execute(["git", "diff", "--exit-code", "--quiet", tested, "HEAD", "--", *receipt["source_gate_paths"]],
            output, log, receipt["executions"])
    receipt["frozen_python"] = {name: file_identity(name) for name in frozen}
    receipt["tested_source_gate_passed"] = True
    write_json(output / "BEFORE_FILES.json", {"frozen_python": receipt["frozen_python"],
                                               "source_gate_paths": receipt["source_gate_paths"]})


def retain(output, receipt):
    patch = patch_bytes("HEAD")
    receipt["final_patch"] = retain_patch(output, "generated.patch", patch)
    receipt["after_tracked_tree"] = tracked_tree(output)
    changed = paths("diff", "--name-only", "--no-renames", "-z", "HEAD", "--")
    write_json(output / "AFTER_FILES.json", {
        "changed_files": {name: file_identity(name) for name in changed},
        "frozen_python": {name: file_identity(name) for name in receipt.get("frozen_python", {})}})
    receipt["final_tracked_changes"] = git("status", "--porcelain", "--untracked-files=no").decode().strip()
    write_json(output / "SOURCE.json", {key: receipt.get(key) for key in (
        "source_commit", "source_tree", "tested_commit", "tested_tree", "after_tracked_tree",
        "tested_source_gate_passed", "verification_receipt_identity", "request_identity", "request")})
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, data in [("generated.patch", patch), *[(name, (output / name).read_bytes())
                           for name in ("AFTER_FILES.json", "SOURCE.json")]]:
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime = len(data), 0o644, 0
            tar.addfile(entry, io.BytesIO(data))
    with (output / "PATCH.tar.xz").open("xb") as handle:
        handle.write(lzma.compress(archive.getvalue(), preset=6))
    artifacts = {path.relative_to(output).as_posix(): identity(path.read_bytes())
                 for path in sorted(output.rglob("*")) if path.is_file()}
    write_json(output / "PATCH_INDEX.json", {"schema": "hepta.memory.v8.final-patch-index.v1",
        "artifacts": artifacts, "stages": receipt["stages"], "final_patch": receipt["final_patch"],
        "console_patch_payloads": False, "tests_executed_after_fix_or_format": False})
    artifacts["PATCH_INDEX.json"] = identity((output / "PATCH_INDEX.json").read_bytes())
    with (output / "SHA256SUMS").open("xb") as handle:
        handle.write("".join(f"{value['sha256']}  {name}\n" for name, value in sorted(artifacts.items())).encode())
    receipt["artifacts"] = {**artifacts, "SHA256SUMS": identity((output / "SHA256SUMS").read_bytes())}


def main():
    output = ROOT / "memory-v8-finalize-output"
    output.mkdir(exist_ok=False)
    receipt = {"schema": "hepta.memory.v8.finalize-receipt.v1", "executions": [], "stages": [],
        "source_commit": git("rev-parse", "HEAD").decode().strip(),
        "source_tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "initial_tracked_changes": git("status", "--porcelain", "--untracked-files=no").decode().strip(),
        "tests_executed": False, "clippy_compiles_test_targets": True, "fitting_performed": False,
        "automatic_commit": False, "automatic_push": False, "research_gates_implied_by_test_success": False,
        "cargo_target_dir": os.environ.get("CARGO_TARGET_DIR"), "format_base": BASE, "passed": False}
    started = time.monotonic()
    try:
        with (output / "execution.log").open("xb") as log:
            verify_request(output, receipt, log)
            target = Path(os.environ["CARGO_TARGET_DIR"])
            if not target.is_absolute():
                raise ValueError("absolute existing CI target configuration required")
            command = ["just", "fix", "--locked"]
            for package in PACKAGES:
                command.extend(["-p", package])
            try:
                execute(command, output, log, receipt["executions"])
            finally:
                before_format = retain_stage(output, receipt, "after-fix", receipt["source_tree"])
            freeze_check(receipt)
            changed = paths("diff", "--name-only", "--no-renames", "-z", "HEAD", "--")
            if any(not name.startswith(FIX_ROOTS) or not name.endswith(".rs") for name in changed):
                raise ValueError("scoped Clippy fix modified a file outside the ten Hepta Rust packages")
            try:
                execute(["just", "fmt", "--base", BASE], output, log, receipt["executions"])
            finally:
                retain_stage(output, receipt, "after-format", before_format)
            freeze_check(receipt)
            receipt["passed"] = True
    except Exception as error:
        receipt.update(passed=False, error=f"{type(error).__name__}: {error}")
    receipt["wall_seconds"] = time.monotonic() - started
    try:
        if "frozen_python" in receipt:
            freeze_check(receipt)
        receipt["frozen_python_unchanged"] = "frozen_python" in receipt
    except Exception as error:
        receipt.update(passed=False, frozen_python_unchanged=False, frozen_python_error=f"{type(error).__name__}: {error}")
    try:
        retain(output, receipt)
    except Exception as error:
        receipt.update(passed=False, retention_error=f"{type(error).__name__}: {error}")
    write_json(output / "receipt.json", receipt)
    print("MEMORY_V8_FINAL_RECEIPT:" + json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
