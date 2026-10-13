"""Build exact native sources in an isolated research composition workspace.

This does not compile the complete agentd product, grant runtime installation,
or satisfy Four-Gate. Native crate files and the adapter are copied unchanged;
only the temporary workspace member list and harness manifest are generated.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib


CRATES = ("hepta-types", "hepta-learning-artifacts", "hepta-contracts",
          "hepta-infer-core", "utils/cargo-bin")
HARNESS = Path("qualification/neuron-stem/native-rule-use")
PACKAGE = "codex-native-rule-use-research"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inline_toml(value):
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return "[" + ", ".join(map(inline_toml, value)) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{key} = {inline_toml(item)}"
                                 for key, item in value.items()) + " }"
    return str(value)


def inherited_dependencies(manifest):
    names = set()
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        for name, value in manifest.get(section, {}).items():
            if isinstance(value, dict) and value.get("workspace"):
                names.add(name)
    for target in manifest.get("target", {}).values():
        names.update(inherited_dependencies(target))
    return names


def stage(repo, output):
    output.mkdir(parents=True, exist_ok=True)
    inputs = []

    def copy(relative):
        source, target = repo / relative, output / relative
        source_digest = sha256(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha256(target) != source_digest or sha256(source) != source_digest:
            raise RuntimeError(f"source changed while copying {relative}")
        inputs.append({"path": relative.as_posix(), "sha256": source_digest})

    root_path = repo / "codex-rs/Cargo.toml"
    root_text = root_path.read_text()
    root = tomllib.loads(root_text)
    dependencies = {"ed25519-dalek", "serde_json"}
    for crate in CRATES:
        relative = Path("codex-rs") / crate
        dependencies.update(inherited_dependencies(tomllib.loads(
            (repo / relative / "Cargo.toml").read_text())))
        target = output / relative
        if target.exists():
            shutil.rmtree(target)
        for source in sorted((repo / relative).rglob("*")):
            if source.is_file():
                copy(source.relative_to(repo))
    for relative in (HARNESS / "main.rs", HARNESS / "fixture.rs", HARNESS / "revision.rs",
                     Path("codex-rs/hepta-agentd/src/rule_artifact.rs"),
                     Path("codex-rs/Cargo.lock"), Path("codex-rs/rust-toolchain.toml")):
        copy(relative)
    inputs.append({"path": "codex-rs/Cargo.toml", "sha256": sha256(root_path)})
    workspace = ["[workspace]", "members = " + inline_toml(
        [*CRATES, "../" + HARNESS.as_posix()]), 'resolver = "2"',
        "", "[workspace.package]"]
    workspace.extend(f"{name} = {inline_toml(value)}"
                     for name, value in root["workspace"]["package"].items())
    workspace.extend(("", "[workspace.dependencies]"))
    workspace.extend(f"{name} = {inline_toml(root['workspace']['dependencies'][name])}"
                     for name in sorted(dependencies))
    # Preserve the repository's lint and build profile declarations verbatim.
    workspace.append(root_text[root_text.index("[workspace.lints]"):
                               root_text.index("[workspace.metadata.cargo-shear]")])
    workspace.append(root_text[root_text.index("[profile.dev]"):
                               root_text.index("[patch.crates-io]")])
    (output / "codex-rs/Cargo.toml").write_text("\n".join(workspace) + "\n")
    harness_manifest = ['[package]', f'name = "{PACKAGE}"',
                        'workspace = "../../../codex-rs"',
                        'version.workspace = true', 'edition.workspace = true',
                        'license.workspace = true', 'publish = false', '',
                        '[[bin]]', 'name = "native-rule-use"', 'path = "main.rs"',
                        '', '[dependencies]']
    harness_manifest.extend(f'codex-{crate} = {{ path = "../../../codex-rs/{crate}" }}'
                            for crate in CRATES if not crate.startswith("utils/"))
    harness_manifest.extend(('ed25519-dalek.workspace = true',
                             'serde_json.workspace = true'))
    (output / HARNESS / "Cargo.toml").write_text("\n".join(harness_manifest) + "\n")
    return inputs


def verify_lock(repo, output):
    def packages(path):
        return {(item["name"], item["version"], item.get("source"))
                for item in tomllib.loads(path.read_text())["package"]}
    original = packages(repo / "codex-rs/Cargo.lock")
    selected = packages(output / "codex-rs/Cargo.lock")
    unexpected = {item for item in selected if item[0] != PACKAGE} - original
    if unexpected:
        raise RuntimeError(f"shadow changed dependency identity: {sorted(unexpected)}")
    return [dict(name=name, version=version, source=source)
            for name, version, source in sorted(selected)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    repo, output = args.repo.resolve(), args.output.resolve()
    if repo == output or repo in output.parents or output in repo.parents:
        parser.error("output must be separate from the repository")
    inputs = stage(repo, output)
    cargo = shutil.which("cargo") or str(Path("/root/.cargo/bin/cargo"))
    command = [cargo, "build", "-p", PACKAGE]
    if args.offline:
        command.append("--offline")
    if args.release:
        command.append("--release")
    root = output / "codex-rs"
    print(json.dumps({"command": command, "cwd": str(root)}), flush=True)
    subprocess.run(command, cwd=root, check=True)
    selected = verify_lock(repo, output)
    target = Path(os.environ.get("CARGO_TARGET_DIR", "target"))
    if not target.is_absolute():
        target = root / target
    suffix = ".exe" if os.name == "nt" else ""
    binary = target / ("release" if args.release else "debug") / ("native-rule-use" + suffix)
    report = {"scope": "exact-source isolated native research composition; not full agentd qualification",
              "source_inputs": inputs, "dependency_identities": selected,
              "command": command, "binary": str(binary.resolve()),
              "binary_sha256": sha256(binary),
              "toolchain": subprocess.check_output([cargo, "--version"], cwd=root, text=True).strip()}
    rustc = shutil.which("rustc") or str(Path(cargo).with_name("rustc"))
    report["rustc"] = subprocess.check_output([rustc, "--version"], cwd=root, text=True).strip()
    (output / "provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"binary": report["binary"], "provenance": str(output / "provenance.json")}), flush=True)


if __name__ == "__main__":
    main()
