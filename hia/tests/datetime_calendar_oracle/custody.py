"""Compile the original locked Chrono API and bind every consumed registry source."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tomllib


def require(condition, message):
    if not condition:
        raise ValueError(message)


def binding(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def compile_original(producer, original_lock, cargo, rustc, output, contract,
                     oracle_directory="hia/tests/datetime_calendar_oracle"):
    reference = binding(original_lock)
    require(reference["sha256"] == contract["reference"]["workspace_lock_sha256"],
            "original workspace lock differs from its immutable reference")
    oracle = (producer / oracle_directory).resolve(strict=True)
    require(oracle.is_relative_to(producer), "original observer must remain inside its source checkout")
    source_inputs = [binding(oracle / name) for name in ("Cargo.toml", "Cargo.lock", "src/main.rs")]
    locked = tomllib.loads((oracle / "Cargo.lock").read_text())["package"]
    original = tomllib.loads(original_lock.read_text())["package"]
    key = lambda row: (row["name"], row["version"], row.get("source"))
    reference_rows = {key(row): row for row in original}
    registry = {key(row): row for row in locked if row.get("source")}
    require(len(registry) == contract["reference"]["oracle_registry_packages"], "oracle dependency count differs")
    for identity, row in registry.items():
        require(identity in reference_rows and row["checksum"] == reference_rows[identity]["checksum"],
                "oracle dependency differs from the original workspace: " + str(identity))
    require(any(row["name"] == "chrono" and row["version"] == contract["reference"]["version"]
                and row["checksum"] == contract["reference"]["checksum"] for row in registry.values()),
            "original Chrono package identity is missing")
    env = dict(os.environ)
    require(not env.get("RUSTFLAGS") and not env.get("CARGO_ENCODED_RUSTFLAGS")
            and not env.get("CARGO_BUILD_TARGET"), "external rustc flags or cross targets are not admitted")
    env.update(RUSTC=str(rustc), CARGO_TARGET_DIR=str(output / "target"),
               CARGO_BUILD_JOBS="1", CARGO_INCREMENTAL="0", CARGO_PROFILE_DEV_DEBUG="0")
    toolchain = {"cargo": binding(cargo), "rustc": binding(rustc),
                 "cargo_version": subprocess.check_output([str(cargo), "--version"], text=True),
                 "rustc_version": subprocess.check_output([str(rustc), "-vV"], text=True),
                 "jobs": 1, "debug_info": 0}
    commands = []

    def run(name, arguments):
        command = [str(cargo), *arguments, "--manifest-path", str(oracle / "Cargo.toml"), "--locked"]
        result = subprocess.run(command, env=env, capture_output=True, timeout=300)
        stdout, stderr = output / (name + ".stdout"), output / (name + ".stderr")
        stdout.write_bytes(result.stdout)
        stderr.write_bytes(result.stderr)
        commands.append({"argv": command, "returncode": result.returncode,
                         "stdout": binding(stdout), "stderr": binding(stderr)})
        (output / "cargo-commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        require(result.returncode == 0, "original oracle Cargo command failed: " + name)
        return result.stdout

    metadata = json.loads(run("metadata", ["metadata", "--format-version=1"]))
    packages = {row["id"]: row for row in metadata["packages"]}
    messages = [json.loads(line) for line in run("build", ["build", "--message-format=json"]).splitlines()]
    require(messages[-1] == {"reason": "build-finished", "success": True}, "Cargo did not finish successfully")
    artifacts = [row for row in messages if row.get("reason") == "compiler-artifact"]
    executables = [row for row in artifacts if row.get("executable")]
    require(len(executables) == 1 and not executables[0]["fresh"], "original observer must be freshly compiled")
    executable = Path(executables[0]["executable"]).resolve(strict=True)
    require(executable.is_relative_to(output / "target"), "oracle executable is outside its owned target")
    consumed = []
    for package_id in sorted({row["package_id"] for row in artifacts}):
        package = packages[package_id]
        if not package["source"]:
            continue
        source = Path(package["manifest_path"]).parent
        archive = source.parents[2] / "cache" / source.parent.name / (source.name + ".crate")
        archive_binding = binding(archive)
        require(archive_binding["sha256"] == registry[key(package)]["checksum"], "registry archive checksum differs")
        files = []
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                if member.isdir():
                    continue
                require(member.isfile(), "registry archive contains a non-regular source entry")
                relative = Path(member.name).relative_to(source.name)
                require(".." not in relative.parts, "registry source escapes its package")
                path = source / relative
                data = tar.extractfile(member).read()
                require(not path.is_symlink() and path.read_bytes() == data, "consumed registry source differs: " + str(path))
                files.append({"relative": str(relative), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        consumed.append({"package_id": package_id, "archive": archive_binding, "source_root": str(source), "files": files})
    require(all(binding(Path(row["path"])) == row for row in source_inputs), "original observer source changed")
    receipt = {"reference_lock": reference, "locked_registry_packages": len(registry), "source_inputs": source_inputs,
               "toolchain": toolchain, "commands": commands, "executable": binding(executable),
               "consumed_registry_sources": consumed}
    (output / "original-custody.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return executable, receipt
