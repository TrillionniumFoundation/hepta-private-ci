"""Rebuild the host adapter with verified production source and a small workspace."""

import argparse
import hashlib
import json
from pathlib import Path
import os
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def build(repo, output, rust_bin, cargo_home):
    identity = json.loads((HERE / "SOURCE_IDENTITY.json").read_text())
    for item in identity["source_files"]:
        data = (repo / item["path"]).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != item["sha"]:
            raise ValueError(f"Production source mismatch: {item['path']}")
    output.mkdir(parents=True, exist_ok=False)
    for crate in ("hepta-neuron", "hepta-infer-core", "hepta-types"):
        shutil.copytree(repo / "codex-rs" / crate, output / "codex-rs" / crate)
    (output / "Cargo.toml").write_text('''[workspace]
members=["codex-rs/hepta-neuron","codex-rs/hepta-infer-core","codex-rs/hepta-types","bridge"]
resolver="2"
[workspace.package]
edition="2024"
license="Apache-2.0"
version="0.0.0"
[workspace.dependencies]
serde={version="=1.0.229",features=["rc"]}
serde_json="=1.0.151"
sha2="=0.10.9"
pretty_assertions="=1.4.1"
[workspace.lints]
''')
    target = output / "bridge"
    (target / "src").mkdir(parents=True)
    (target / "Cargo.toml").write_text('''[package]
name="hcsn-production-bridge-r18"
version="0.1.0"
edition="2024"
[dependencies]
codex-hepta-neuron={path="../codex-rs/hepta-neuron"}
codex-hepta-types={path="../codex-rs/hepta-types"}
''')
    shutil.copyfile(HERE / "bridge.rs", target / "src/main.rs")
    shutil.copyfile(HERE / "Cargo.lock", output / "Cargo.lock")
    env = os.environ.copy()
    env.update(CARGO_HOME=str(cargo_home), RUSTC=str(rust_bin / "rustc"),
               CARGO_TARGET_DIR=str(output / "target"))
    subprocess.run([str(rust_bin / "cargo"), "build", "--offline", "--locked",
                    "--manifest-path", str(output / "Cargo.toml"),
                    "-p", "hcsn-production-bridge-r18"], env=env, check=True)
    print(output / "target/debug/hcsn-production-bridge-r18")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("rust_bin", type=Path)
    parser.add_argument("cargo_home", type=Path)
    a = parser.parse_args()
    build(a.repo.resolve(), a.output.resolve(), a.rust_bin.resolve(), a.cargo_home.resolve())
