"""Build and test the research adapter against unchanged native owner sources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
NAME = "hepta-first-passage-owner-bridge"


def build(source_root, output, toolchain_bin, tools_bin):
    source_root, output = Path(source_root).resolve(), Path(output).resolve()
    manifest = json.loads((HERE / "native/SOURCE_IDENTITY.json").read_text())
    for item in manifest["files"]:
        payload = (source_root / item["path"]).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
        if actual != item["git_blob_sha"]:
            raise ValueError("Original owner source mismatch: " + item["path"])
    output.mkdir(parents=True, exist_ok=True)
    sources = {}
    for name in ("owner_bridge.rs", "owner_bridge_tests.rs", "execution_state.rs", "task_journal.rs"):
        payload = (HERE / "native" / name).read_bytes()
        sources[name] = hashlib.sha256(payload).hexdigest()
        (output / name).write_bytes(payload)
    identity = {"owner_manifest":manifest, "adapter_sources":sources}
    source_digest = hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    cargo = f'[package]\nname = "{NAME}"\nversion = "0.1.0"\nedition = "2024"\npublish = false\n[workspace]\n[[bin]]\nname = "{NAME}"\npath = "owner_bridge.rs"\n[dependencies]\n'
    for crate in ("hepta-neuron", "hepta-types"):
        cargo += f'codex-{crate} = {{ path = {json.dumps(str(source_root / "codex-rs" / crate))} }}\n'
    cargo += 'serde = { version = "1", features = ["derive"] }\nserde_json = "1"\n[profile.dev]\ndebug = 0\nincremental = false\n'
    (output / "Cargo.toml").write_text(cargo)
    frozen_lock=HERE / "native/owner-Cargo.lock"
    if frozen_lock.exists():
        shutil.copyfile(frozen_lock,output / "Cargo.lock")
    env = dict(os.environ)
    env.update({"PATH":os.pathsep.join([str(toolchain_bin),str(tools_bin),env["PATH"]]),
                "HEPTA_FPT_NATIVE_SOURCE_DIGEST":source_digest,
                "HEPTA_FPT_OWNER_SOURCE_COMMIT":manifest["source_commit"],
                "CARGO_HOME":str(output / "cargo-home"),"CARGO_TARGET_DIR":str(output / "target"),
                "CARGO_BUILD_JOBS":"2","CARGO_INCREMENTAL":"0"})
    commands = ([] if frozen_lock.exists() else [["cargo","generate-lockfile","--manifest-path",str(output / "Cargo.toml")]]) + [
        ["cargo","build","--locked","--manifest-path",str(output / "Cargo.toml")],
        ["just","--justfile",str(source_root / "justfile"),"test","-p",NAME,
         "--manifest-path",str(output / "Cargo.toml"),"--locked","--profile","default"],
    ]
    for command in commands:
        subprocess.run(command,cwd=source_root,env=env,check=True)
    binary = output / NAME
    shutil.copyfile(output / "target/debug" / NAME,binary)
    binary.chmod(0o755)
    result = {"schema":"hepta.fpt-adaptive.native-build.v1","owner_source_commit":manifest["source_commit"],
        "adapter_sources":sources,"source_digest":source_digest,"binary":str(binary),
        "binary_sha256":hashlib.sha256(binary.read_bytes()).hexdigest(),
        "lock_sha256":hashlib.sha256((output / "Cargo.lock").read_bytes()).hexdigest(),
        "rustc":subprocess.check_output(["rustc","--version"],env=env,text=True).strip(),
        "commands":commands,"test_status":"passed","original_owner_source_changed":False,
        "fpt_state_profile":"research-task external state; owner V1 sparse checkpoint remains distinct",
        "production_activation":False}
    (output / "NATIVE_BUILD.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    for name in ("source-root","output","toolchain-bin","tools-bin"):
        parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    build(args.source_root,args.output,args.toolchain_bin,args.tools_bin)
