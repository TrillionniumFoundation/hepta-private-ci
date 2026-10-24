"""Stage a bounded actual-source owner check, not a full Agentd build.

Copies the three real dependency crates unchanged and imports the actual
Agentd module by path. No predictor/type substitution or private assets.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tomllib


def prepare(destination):
    root = Path(__file__).resolve().parents[1]
    destination.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for crate in ("hepta-types", "hepta-infer-core", "hepta-neuron"):
        source = root / "codex-rs" / crate
        shutil.copytree(source, destination / crate)
        for path in sorted(source.rglob("*")):
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                copied = destination / crate / path.relative_to(source)
                if hashlib.sha256(copied.read_bytes()).hexdigest() != digest:
                    raise ValueError("source copy mismatch")
                hashes[str(path.relative_to(root))] = digest
    workspace = tomllib.loads((root / "codex-rs/Cargo.toml").read_text())["workspace"]
    dependencies = workspace["dependencies"]
    manifest = """[workspace]
members=["owner","hepta-types","hepta-infer-core","hepta-neuron"]
resolver="2"
[workspace.package]
"""
    for name in ("version", "edition", "license"):
        manifest += f"{name}={json.dumps(workspace['package'][name])}\n"
    manifest += "[workspace.dependencies]\n"
    for name in ("serde", "serde_json", "sha2", "pretty_assertions"):
        value = dependencies[name]
        if isinstance(value, dict) and set(value) <= {"version", "features"}:
            encoded = (
                "{"
                + ",".join(f"{key}={json.dumps(item)}" for key, item in value.items())
                + "}"
            )
        elif isinstance(value, str):
            encoded = json.dumps(value)
        else:
            raise ValueError(f"review isolated dependency declaration: {name}")
        manifest += f"{name}={encoded}\n"
    manifest += "[workspace.lints.rust]\n[profile.dev]\ndebug=0\nincremental=false\n"
    (destination / "Cargo.toml").write_text(manifest)
    (destination / "owner/src").mkdir(parents=True)
    (destination / "owner/Cargo.toml").write_text("""[package]
name="research-task-head-owner-check"
version="0.0.0"
edition="2024"
[dependencies]
codex-hepta-neuron={path="../hepta-neuron"}
codex-hepta-types={path="../hepta-types"}
serde={workspace=true,features=["derive"]}
serde_json={workspace=true}
""")
    owner = root / "codex-rs/hepta-agentd/src/research_task_head_owner.rs"
    (destination / "owner/src/lib.rs").write_text(
        f"#[path={json.dumps(str(owner))}]\npub mod research_task_head_owner;\n"
    )
    for path in (owner, owner.with_name("research_task_head_owner_tests.rs")):
        hashes[str(path.relative_to(root))] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    shutil.copyfile(
        root / "qualification/research-task-head-check/dependencies.lock",
        destination / "Cargo.lock",
    )
    (destination / "justfile").write_text(
        'set positional-arguments\ntest *args:\n    cargo nextest run --no-fail-fast "$@"\n'
    )
    (destination / "source-sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(
        f"Staged real owner/dependencies; {len(hashes)} source files hashed; full Agentd NOT built"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    prepare(parser.parse_args().destination)
