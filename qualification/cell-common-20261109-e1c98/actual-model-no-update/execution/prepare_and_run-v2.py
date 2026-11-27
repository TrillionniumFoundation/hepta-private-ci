"""One create-only preparation and one original-gate research model attempt."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def source_state(source):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=source, text=True).strip()

    return {"head": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
            "status": git("status", "--porcelain=v1", "--untracked-files=all")}


def verify_source_and_gates(plan):
    for name, expected_value in {
        "CODEX_REPO_ROOT": plan["source"], "CARGO_TARGET_DIR": plan["target"],
        "RUSTUP_TOOLCHAIN": "1.96.0",
    }.items():
        if os.environ.get(name) != expected_value:
            raise RuntimeError(f"outer recorder environment mismatch: {name}")
    expected = {"head": plan["source_commit"], "tree": plan["source_tree"], "status": ""}
    if source_state(plan["source"]) != expected:
        raise RuntimeError("exact clean source no longer matches frozen preparation")
    receipts = []
    for path in plan["native_gate_records"]:
        receipt = json.loads(Path(path).read_text())
        if (receipt.get("exit_code") != 0 or receipt.get("source_before") != expected
                or receipt.get("source_after") != expected or receipt.get("source_unchanged") is not True):
            raise RuntimeError(f"native preparation prerequisite did not pass: {path}")
        receipts.append({"path": path, "sha256": digest(path), "receipt": receipt})
    return receipts


def verify_materials(plan):
    observed = []
    for item in plan["material_pins"]:
        path = Path(item["path"])
        actual = digest(path)
        if actual != item["sha256"]:
            raise RuntimeError(f"pinned input changed: {path}")
        observed.append({"path": str(path), "resolved": str(path.resolve()),
                         "sha256": actual, "bytes": path.stat().st_size})
    driver = Path(plan["source"]) / "scripts/research/smollm_learning_process_v1.py"
    if digest(driver) != plan["driver_sha256"]:
        raise RuntimeError("final source driver differs from frozen Python input controls")
    return observed


def file_receipt(path):
    path = Path(path)
    return {"path": str(path), "resolved": str(path.resolve(strict=True)),
            "sha256": digest(path), "bytes": path.stat().st_size}


def binary_paths(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "binary-path" and isinstance(child, str):
                yield child
            else:
                yield from binary_paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from binary_paths(child)


def python_environment(plan):
    value = json.loads(subprocess.check_output([
        plan["model_environment"]["HEPTA_REAL_MODEL_PYTHON"], "-c",
        "import importlib.metadata as m,json,sys; print(json.dumps({'python':sys.version,'packages':"
        "{p:m.version(p) for p in ['torch','transformers','safetensors','numpy']}}))",
    ], text=True))
    if value["packages"] != plan["expected_python_packages"]:
        raise RuntimeError("model Python package versions changed from original materials")
    return value


def prepare(plan, payload_path):
    gates = verify_source_and_gates(plan)
    materials = verify_materials(plan)
    root = Path(plan["root"])
    root.mkdir()  # Existing attempts are evidence; never overwrite or silently resume.
    prep = root / "preparation"
    prep.mkdir()
    (root / "tmp").mkdir()
    with (root / "model-config.json").open("x") as stream:
        stream.write(plan["config_text"])
    if digest(root / "model-config.json") != plan["config_sha256"]:
        raise RuntimeError("config byte binding differs")
    write_json(prep / "plan.json", plan)
    write_json(prep / "native-prerequisites.json", gates)
    write_json(prep / "materials-before.json", materials)
    source = Path(plan["source"])
    tool_commands = {
        "rustc": ["rustc", "-vV"], "cargo": ["cargo", "--version"],
        "nextest": ["cargo", "nextest", "--version"], "just": ["just", "--version"],
    }
    tool_versions = {name: subprocess.check_output(command, cwd=source / "codex-rs", text=True)
                     for name, command in tool_commands.items()}
    tool_files = [{"name": name, **file_receipt(shutil.which(name))}
                  for name in ("rustc", "cargo", "cargo-nextest", "just")]
    toolchain_files = {
        name: file_receipt(subprocess.check_output(["rustup", "which", name],
                                                   cwd=source / "codex-rs", text=True).strip())
        for name in ("rustc", "cargo")
    }
    write_json(prep / "tools.json", {"versions": tool_versions, "files": tool_files,
                                     "actual_toolchain_files": toolchain_files,
                                     "model_python": python_environment(plan)})
    source_archive = prep / "source.tar.gz"
    subprocess.run(["git", "archive", "--format=tar.gz", "--output", str(source_archive),
                    plan["source_commit"]], cwd=source, check=True)
    archive = prep / "native-nextest.tar.zst"
    command = [sys.executable, str(source / "scripts/hepta_ci_v8.py"), "--run", "cargo",
               "nextest", "archive", *plan["archive_build_args"], "--archive-file", str(archive)]
    write_json(prep / "archive-command.json", {"argv": command, "test_execution": False})
    environment = os.environ.copy()
    environment.update({"NEXTEST_PROFILE": "local", "RUST_MIN_STACK": "8388608"})
    subprocess.run(command, cwd=source, env=environment, check=True)
    metadata = prep / "binaries.json"
    (prep / "list-extracted").mkdir(mode=0o700)
    list_command = ["cargo", "nextest", "list", "--archive-file", str(archive),
                    "--workspace-remap", str(source / "codex-rs"), "--extract-to",
                    str(prep / "list-extracted"), "--list-type", "binaries-only", "--message-format", "json"]
    write_json(prep / "list-command.json", {"argv": list_command, "test_execution": False})
    with metadata.open("xb") as output:
        subprocess.run(list_command, cwd=source / "codex-rs", env=environment,
                       stdout=output, check=True)
    binaries = []
    for path in sorted(set(binary_paths(json.loads(metadata.read_text())))):
        relative = Path(path).relative_to(plan["target"])
        extracted = file_receipt(prep / "list-extracted/target" / relative)
        if extracted["sha256"] != digest(path):
            raise RuntimeError("archived binary differs from the just-built native binary")
        binaries.append({**extracted, "build_path": path})
    if not any("hepta_agentd" in Path(item["path"]).name for item in binaries):
        raise RuntimeError("archived agentd test binary not found in actual metadata")
    verify_source_and_gates(plan)
    verify_materials(plan)
    model_environment = dict(plan["model_environment"])
    model_environment.update({
        "HEPTA_REAL_MODEL_DRIVER": str(source / "scripts/research/smollm_learning_process_v1.py"),
        "HEPTA_REAL_MODEL_SOURCE_COMMIT": plan["source_commit"],
        "HEPTA_REAL_MODEL_SOURCE_TREE": plan["source_tree"],
        "LD_LIBRARY_PATH": "/usr/lib/llvm-21/lib:/home/qq/.rustup/toolchains/1.96.0-x86_64-unknown-linux-gnu/lib",
    })
    write_json(root / "model-environment.json", model_environment)
    write_json(prep / "RESULT.json", {
        "schema": "hepta.common.actual-model-preparation.v1", "prepared_unix_ns": time.time_ns(),
        "source_commit": plan["source_commit"], "source_tree": plan["source_tree"],
        "payload": file_receipt(payload_path), "controller": file_receipt(__file__),
        "outer_recorder": file_receipt(plan["outer_recorder"]),
        "tools": file_receipt(prep / "tools.json"),
        "source_archive": file_receipt(source_archive), "nextest_archive": file_receipt(archive),
        "binary_metadata": file_receipt(metadata), "binaries": binaries,
        "environment": file_receipt(root / "model-environment.json"),
        "model_execution_started": False, "independent_confirmation_tasks": 0,
        "prior_tasks_and_outcomes_exposed": True, "scientific_status": "HOLD",
    })
    print(json.dumps({"prepared": str(prep / "RESULT.json"), "model_execution_started": False}), flush=True)


def execute(plan, payload_path):
    verify_source_and_gates(plan)
    verify_materials(plan)
    root = Path(plan["root"])
    receipt = json.loads((root / "preparation/RESULT.json").read_text())
    for item in [receipt[key] for key in ("payload", "controller", "outer_recorder", "tools", "source_archive", "nextest_archive", "environment")]:
        if digest(item["path"]) != item["sha256"]:
            raise RuntimeError(f"prepared input changed: {item['path']}")
    if receipt["payload"]["path"] != str(payload_path) or receipt["source_commit"] != plan["source_commit"]:
        raise RuntimeError("preparation identity mismatch")
    if digest(root / "model-config.json") != plan["config_sha256"]:
        raise RuntimeError("config changed after preparation")
    tools = json.loads(Path(receipt["tools"]["path"]).read_text())
    for item in tools["files"]:
        if shutil.which(item["name"]) != item["path"] or digest(item["path"]) != item["sha256"]:
            raise RuntimeError(f"execution tool selection changed: {item['name']}")
    for item in tools["actual_toolchain_files"].values():
        if digest(item["path"]) != item["sha256"]:
            raise RuntimeError("actual Rust toolchain changed after archiving")
    if python_environment(plan) != tools["model_python"]:
        raise RuntimeError("model Python environment changed after preparation")
    (root / "run-extracted").mkdir(mode=0o700)
    command = ["just", "test", "--archive-file", receipt["nextest_archive"]["path"],
               "--workspace-remap", str(Path(plan["source"]) / "codex-rs"),
               "--extract-to", str(root / "run-extracted"), "--run-ignored", "only",
               "--retries", "0", "--no-tests", "fail", "--no-capture", "-E",
               "test(actual_smollm_training_no_update_native_next_use_and_cold_readback)"]
    environment = os.environ.copy()
    environment.update(json.loads((root / "model-environment.json").read_text()))
    write_json(root / "EXECUTION_STARTED.json", {
        "argv": command, "started_unix_ns": time.time_ns(), "source_commit": plan["source_commit"],
        "source_tree": plan["source_tree"], "nextest_archive": receipt["nextest_archive"],
        "original_test_watchdog_seconds": 60, "outer_owned_job_budget_seconds": 240,
        "independent_confirmation_tasks": 0, "ordinary_daemon_task_loop": False,
        "research_operator_custody": True, "scientific_status": "HOLD",
    })
    os.chdir(plan["source"])
    os.execvpe(command[0], command, environment)


phase, payload_name, expected_payload = sys.argv[1:]
payload_path = Path(payload_name)
if digest(payload_path) != expected_payload:
    raise RuntimeError("preparation payload hash mismatch")
plan = json.loads(payload_path.read_text())
if phase == "prepare":
    prepare(plan, payload_path)
elif phase == "execute":
    execute(plan, payload_path)
else:
    raise RuntimeError("expected prepare or execute")
