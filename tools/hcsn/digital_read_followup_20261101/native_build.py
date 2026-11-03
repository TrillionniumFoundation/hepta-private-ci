"""Build the inherited real owner with an auditable structured-terminal overlay.

All unchanged Rust modules come from the adjacent pinned 20261031 namespace.
No inherited source is edited. The original repository fmt/test entry points
are invoked; unavailable nextest is reported separately from direct test runs.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "digital_read_before_20261031"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--upstream-root", type=Path, required=True)
    p.add_argument("--work-dir", type=Path, required=True)
    p.add_argument("--rust-bin", type=Path, required=True)
    p.add_argument("--tools-bin", type=Path, required=True)
    p.add_argument("--cargo-home", type=Path, required=True)
    p.add_argument("--receipt", type=Path, required=True)
    a = p.parse_args()
    spec = importlib.util.spec_from_file_location("inherited_native_build", BASE / "build_native.py")
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    work, upstream = a.work_dir.resolve(), a.upstream_root.resolve()
    if work == upstream or work.is_relative_to(HERE):
        raise ValueError("independent scratch build directory required")
    work.mkdir(parents=True, exist_ok=True)
    ident = json.loads((BASE / "native/UPSTREAM_SOURCE_IDENTITY.json").read_text())
    source_files = [*ident["files"], *[dict(path=k, git_blob_sha=v) for k, v in old.HELPERS.items()]]
    for item in source_files:
        data = (upstream / item["path"]).read_bytes()
        if old.git_blob(data) != item["git_blob_sha"]:
            raise ValueError(f"pinned inherited source mismatch: {item['path']}")
        old.write(work / item["path"], data)
    old.write(work / "codex-rs/Cargo.toml", old.WORKSPACE)
    crate = work / "codex-rs/digital-read-before-native"
    old.write(crate / "Cargo.toml", old.CRATE)
    old.write(work / "codex-rs/.config/nextest.toml", '[profile.local]\ninherits = "default"\nretries = 0\n')
    old.write(work / ".gitignore", "/codex-rs/target/\n/logs/\n")
    for path in sorted((BASE / "native").glob("*.rs")):
        old.write(crate / "src" / path.name, path.read_bytes())
    old.write(crate / "src/policy.rs", (HERE / "native/policy.rs").read_bytes())
    patches = {
        "main.rs": [
            ('        "value" => policy::Controller::Value,', '        "value" => policy::Controller::Value,\n        "structured_value" => policy::Controller::StructuredValue,'),
            ('controller must be fixed or value', 'controller must be fixed, value or structured_value'),
            ('mod tests;', 'mod tests;\n#[cfg(test)]\nmod structured_tests;'),
        ],
        "port.rs": [('        let selection_start = Instant::now();', '        let scores = scores.for_controller(self.controller);\n        let selection_start = Instant::now();')],
    }
    for name, replacements in patches.items():
        path = crate / "src" / name
        text = path.read_text()
        for before, after in replacements:
            if text.count(before) != 1:
                raise ValueError(f"overlay anchor mismatch: {name}")
            text = text.replace(before, after)
        path.write_text(text)
    old.write(crate / "src/structured_tests.rs", (HERE / "native_policy_tests.rs").read_bytes())
    old.write(work / "codex-rs/Cargo.lock", (HERE / "native/Cargo.lock").read_bytes())
    env = dict(os.environ, CARGO_NET_OFFLINE="true", CARGO_HOME=str(a.cargo_home.resolve()), RUST_MIN_STACK="8388608")
    env["PATH"] = os.pathsep.join([str(a.rust_bin.resolve()), str(a.tools_bin.resolve()), env.get("PATH", "")])
    if a.rust_bin.resolve().parent.parent.name == "toolchains":
        env["RUSTUP_HOME"] = str(a.rust_bin.resolve().parents[2])
        env["RUSTUP_TOOLCHAIN"] = a.rust_bin.resolve().parent.name
    commands = []
    def run(command, cwd=work, required=True):
        start = time.perf_counter()
        result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)
        output = result.stdout + result.stderr
        log = work / "logs" / f"{len(commands):02d}.log"
        old.write(log, output)
        receipt = dict(command=command, cwd=str(cwd), returncode=result.returncode, wall_seconds=time.perf_counter()-start, log_sha256=digest(output.encode()), log=str(log))
        commands.append(receipt)
        print(json.dumps(receipt), flush=True)
        if required and result.returncode:
            raise RuntimeError(output[-10000:])
        return result
    if not (work / ".git").exists():
        run(["git", "init", "-q"])
        run(["git", "add", "."])
        run(["git", "commit", "-qm", "Pin scoped inherited native sources"])
    run(["just", "fmt"])
    run(["just", "fmt", "--check"])
    run(["cargo", "fmt", "--all"] , work / "codex-rs")
    run(["cargo", "fmt", "--all", "--", "--check"], work / "codex-rs")
    generated = [dict(path=str(x.relative_to(work)), sha256=digest(x.read_bytes())) for x in sorted((crate / "src").glob("*.rs"))]
    inherited_native = [dict(path=x.name, git_blob_sha=old.git_blob(x.read_bytes()))
                        for x in sorted((BASE / "native").glob("*.rs"))]
    binding = dict(upstream=ident, generated_sources=generated,
                   base_commit="012bcf3505cb9306d9cef094a1acc3ca34c978be", inherited_native=inherited_native,
                   inherited_helpers=old.HELPERS,
                   inherited_builder_sha256=digest((BASE / "build_native.py").read_bytes()),
                   builder_sha256=digest(Path(__file__).read_bytes()),
                   workspace_sha256=digest(old.WORKSPACE.encode()), crate_sha256=digest(old.CRATE.encode()),
                   cargo_lock_sha256=digest((work / "codex-rs/Cargo.lock").read_bytes()))
    source_digest = digest(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode())
    env["HEPTA_TASK_NATIVE_SOURCE_DIGEST"] = source_digest
    cargo = work / "codex-rs"
    run(["cargo", "build", "--offline", "--locked", "--release", "-p", "hepta-digital-read-before-native"], cargo)
    packages = ["hepta-digital-read-before-native", "codex-hepta-neuron", "codex-hepta-infer-core", "codex-hepta-types"]
    flags = [z for name in packages for z in ("-p", name)]
    gate = run(["just", "test", "--offline", "--locked", *flags], required=False)
    direct = []
    if gate.returncode:
        built = run(["cargo", "build", "--offline", "--locked", "--tests", "--message-format=json", *flags], cargo)
        for line in built.stdout.splitlines():
            item = json.loads(line)
            if item.get("reason") == "compiler-artifact" and item.get("profile", {}).get("test") and item.get("executable"):
                run([item["executable"], "--test-threads=1"], cargo)
                direct.append(item["executable"])
    binary = cargo / "target/release/hepta-digital-read-before-native"
    versions = {name: subprocess.check_output(command, env=env, text=True).strip()
                for name, command in {"rustc": ["rustc", "-Vv"], "cargo": ["cargo", "-V"], "just": ["just", "--version"]}.items()}
    receipt = dict(schema="digital-structured-native-build-v1", source_digest=source_digest, binding=binding, commands=commands, versions=versions, binary=str(binary), binary_sha256=digest(binary.read_bytes()), original_just_test_passed=gate.returncode == 0, direct_test_executables=direct, full_repository_ci=False, production_activation=False)
    old.write(a.receipt, json.dumps(receipt, indent=2)+"\n")
    print(json.dumps(dict(binary=str(binary), receipt=str(a.receipt))), flush=True)


if __name__ == "__main__":
    main()
