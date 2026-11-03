"""Run final fix/format only for operator-selected tested source; never test or commit."""

import base64
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
REQUEST = Path(__file__).with_name("FINALIZE_REQUEST.json")
BASE = "0b0b041b6dd8121050c335cb3be73bb1d8cb7904"
PACKAGES = ["codex-hepta-" + name for name in (
    "cognitive-types", "neuron", "memory", "cognitive-store", "learning-artifacts",
    "agent-protocol", "agentd", "context-compiler", "infer-worker-host", "plasticity")]
PYTHON = ["qualification/memory-cell-v7/addressing", "qualification/memory-cell-v6/v6"] + [
    "qualification/memory-cell-v7/" + name for name in (
        "training.py", "training_worker.py", "native_export.py", "population_training.py", "population_worker.py")]
SCOPES = ["codex-rs", "justfile", "scripts/format.py", "scripts/just-shell.py", *PYTHON]


def git(*args, env=None):
    return subprocess.check_output(["git", *args], cwd=ROOT, env=env)


def digest(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate finalization request field")
        result[key] = value
    return result


def file_identity(name):
    path = ROOT / name
    if path.is_symlink():
        return {"kind": "symlink", **digest(os.readlink(path).encode())}
    if not path.exists():
        return {"kind": "deleted"}
    return {"kind": "file", "mode": oct(path.stat().st_mode & 0o777), **digest(path.read_bytes())}


def paths(*args):
    return sorted(path.decode() for path in git(*args).split(b"\0") if path)


def execute(command, log, executions):
    started = time.monotonic()
    log.write("COMMAND " + json.dumps(command) + "\n")
    log.flush()
    code = 127
    try:
        with subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors="replace") as process:
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end="", flush=True)
            code = process.wait()
    finally:
        executions.append({"command": command, "exit_code": code, "wall_seconds": time.monotonic() - started})
        log.write(f"EXIT {code}\n")
        log.flush()
    if code:
        raise RuntimeError(f"command failed with exit {code}: {command[0]}")


def retain(output, receipt):
    patch = git("diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv", "--no-color", "HEAD", "--")
    (output / "generated.patch").write_bytes(patch)
    packed = lzma.compress(patch, preset=6)
    (output / "generated.patch.xz").write_bytes(packed)
    changed = paths("diff", "--name-only", "-z", "HEAD", "--")
    runtime = [name for name in paths("ls-files", "-z", "--", *PYTHON) if name.endswith(".py")]
    write_json(output / "AFTER_FILES.json", {
        "changed_files": {name: file_identity(name) for name in changed},
        "runtime_python": {name: file_identity(name) for name in runtime}})
    # A private index computes the resulting tracked tree; the checkout index
    # is untouched and neither a commit nor a push is ever created.
    index = output / "temporary.index"
    environment = {**os.environ, "GIT_INDEX_FILE": str(index)}
    try:
        git("read-tree", "HEAD", env=environment)
        git("add", "-u", "--", ".", env=environment)
        receipt["after_tracked_tree"] = git("write-tree", env=environment).decode().strip()
    finally:
        index.unlink(missing_ok=True)
    receipt["final_tracked_changes"] = git("status", "--porcelain", "--untracked-files=no").decode().strip()
    write_json(output / "SOURCE.json", {key: receipt.get(key) for key in (
        "source_commit", "source_tree", "tested_commit", "tested_tree", "after_tracked_tree", "request")})
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name in ("generated.patch", "AFTER_FILES.json", "SOURCE.json"):
            data = (output / name).read_bytes()
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime = len(data), 0o644, 0
            tar.addfile(entry, io.BytesIO(data))
    (output / "PATCH.tar.xz").write_bytes(lzma.compress(archive.getvalue(), preset=6))
    encoded = base64.b64encode(packed).decode("ascii")
    parts = [encoded[offset:offset + 3000] for offset in range(0, len(encoded), 3000)]
    artifacts = {name: digest((output / name).read_bytes()) for name in (
        "generated.patch", "generated.patch.xz", "PATCH.tar.xz", "AFTER_FILES.json", "SOURCE.json", "execution.log")}
    write_json(output / "PATCH_INDEX.json", {"schema": "hepta.memory.v7.final-patch-index.v1",
        "artifacts": artifacts, "console_encoding": {"artifact": "generated.patch.xz", "format": "base64",
            "part_chars": 3000, "index_base": 1, "part_count": len(parts),
            "parts": [{"part": number, **digest(part.encode("ascii"))} for number, part in enumerate(parts, 1)]}})
    artifacts["PATCH_INDEX.json"] = digest((output / "PATCH_INDEX.json").read_bytes())
    (output / "SHA256SUMS").write_text("".join(f"{value['sha256']}  {name}\n" for name, value in sorted(artifacts.items())))
    receipt["artifacts"] = {**artifacts, "SHA256SUMS": digest((output / "SHA256SUMS").read_bytes())}
    print("MEMORY_V7_FINAL_PATCH_META:" + json.dumps({**digest(packed), "compression": "xz",
        "parts": len(parts), "index_base": 1, "uncompressed": digest(patch)}, sort_keys=True), flush=True)
    for number, part in enumerate(parts, 1):
        print(f"MEMORY_V7_FINAL_PATCH_PART:{number}:{part}", flush=True)


def main():
    output = ROOT / "memory-v7-finalize-output"
    output.mkdir(exist_ok=False)
    receipt = {"schema": "hepta.memory.v7.finalize-receipt.v1", "executions": [],
        "source_commit": git("rev-parse", "HEAD").decode().strip(),
        "source_tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "tests_executed": False, "clippy_compiles_test_targets": True, "automatic_commit": False,
        "cargo_target_dir": os.environ.get("CARGO_TARGET_DIR"),
        "source_gate_paths": SCOPES, "initial_tracked_changes": git("status", "--porcelain", "--untracked-files=no").decode().strip()}
    started = time.monotonic()
    try:
        with (output / "execution.log").open("w") as log:
            request = json.loads(REQUEST.read_text(), object_pairs_hook=unique)
            receipt["request"] = request
            if (not isinstance(request, dict) or set(request) != {"schema", "tested_commit", "format_base", "packages"}
                    or request["schema"] != "hepta.memory.v7.finalize-request.v1"
                    or not isinstance(request["tested_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", request["tested_commit"])
                    or request["format_base"] != BASE or not isinstance(request["packages"], list)
                    or len(request["packages"]) != 10 or sorted(request["packages"]) != sorted(PACKAGES)):
                raise ValueError("invalid finalization request; exact tested commit, base and ten packages required")
            tested = receipt["tested_commit"] = request["tested_commit"]
            receipt["tested_tree"] = git("rev-parse", f"{tested}^{{tree}}").decode().strip()
            if receipt["initial_tracked_changes"] or git("ls-files", "--others", "--exclude-standard", "--", *SCOPES).strip():
                raise ValueError("finalization requires a clean protected source checkout")
            for earlier, later in ((BASE, tested), (tested, "HEAD")):
                execute(["git", "merge-base", "--is-ancestor", earlier, later], log, receipt["executions"])
            execute(["git", "diff", "--exit-code", tested, "HEAD", "--", *SCOPES], log, receipt["executions"])
            receipt["tested_source_gate_passed"] = True
            command = ["just", "fix", "--locked"]
            for package in PACKAGES:
                command.extend(["-p", package])
            execute(command, log, receipt["executions"])
            execute(["just", "fmt", "--base", BASE], log, receipt["executions"])
            execute(["git", "diff", "--exit-code", "HEAD", "--", *PYTHON], log, receipt["executions"])
            if git("ls-files", "--others", "--exclude-standard", "--", *SCOPES).strip():
                raise ValueError("finalization produced an untracked protected source")
            receipt["passed"] = True
    except Exception as error:
        receipt.update(passed=False, error=f"{type(error).__name__}: {error}")
    receipt["wall_seconds"] = time.monotonic() - started
    retain(output, receipt)
    write_json(output / "receipt.json", receipt)
    print("MEMORY_V7_FINAL_RECEIPT:" + json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
