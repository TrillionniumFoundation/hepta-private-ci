"""Reproducible isolated native replay build; not full-workspace qualification."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tomllib

CRATES = ("hepta-types", "hepta-contracts", "hepta-ndu")
DEPENDENCIES = ("sha2", "ed25519-dalek", "rustix", "serde", "serde_json", "zeroize")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def toml_value(value):
    if isinstance(value, dict):
        return "{" + ", ".join(f"{json.dumps(k)} = {toml_value(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(map(toml_value, value)) + "]"
    return json.dumps(value, ensure_ascii=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New scratch directory outside repository")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--cargo", default=shutil.which("cargo"))
    parser.add_argument("--clippy", action="store_true")
    args = parser.parse_args()
    repo, output = args.repo.resolve(strict=True), args.output.resolve()
    if (args.output.is_symlink() or output.exists() or output == repo or repo in output.parents
            or output in repo.parents or not output.parent.is_dir()):
        parser.error("output must be a new directory outside repository with an existing parent")
    if not args.cargo:
        parser.error("cargo unavailable; supply --cargo")
    cargo = str(Path(shutil.which(args.cargo) or args.cargo).absolute())
    if not Path(cargo).is_file():
        parser.error("cargo executable not found")
    # Inspect every input before copying; reject links rather than following them.
    inputs = [repo / "codex-rs/Cargo.toml", repo / "codex-rs/rust-toolchain.toml"]
    for crate in CRATES:
        source = repo / "codex-rs" / crate
        if source.is_symlink() or not source.is_dir():
            parser.error(f"missing/nonregular source crate: {crate}")
        for path in sorted(source.rglob("*")):
            if path.is_symlink() or (not path.is_dir() and not path.is_file()):
                parser.error(f"nonregular source rejected: {path}")
            if path.is_file():
                inputs.append(path)
    if any(path.is_symlink() or not path.is_file() for path in inputs):
        parser.error("regular source manifests and toolchain file required")
    hashes = {str(path.relative_to(repo)): sha(path) for path in inputs}
    root = tomllib.loads((repo / "codex-rs/Cargo.toml").read_text())["workspace"]
    output.mkdir(mode=0o700)
    for crate in CRATES:
        shutil.copytree(repo / "codex-rs" / crate, output / crate, symlinks=True)
        if any(path.is_symlink() for path in (output / crate).rglob("*")):
            raise ValueError("source changed to a symlink during copying")
        manifest = output / crate / "Cargo.toml"
        text = manifest.read_text()
        # Only dev dependencies are removed; production sources/dependencies stay exact.
        if "[dev-dependencies]" in text:
            before, after = text.split("[dev-dependencies]", 1)
            if any(line.startswith("[") for line in after.splitlines()):
                raise ValueError("unexpected manifest sections after dev dependencies")
            manifest.write_text(before)
    shutil.copyfile(repo / "codex-rs/rust-toolchain.toml", output / "rust-toolchain.toml")
    tables = {"workspace.package": root["package"],
              "workspace.dependencies": {key: root["dependencies"][key] for key in DEPENDENCIES},
              "workspace.lints": root["lints"]}
    manifest = '[workspace]\nmembers = ["hepta-types", "hepta-contracts", "hepta-ndu"]\nresolver = "3"\n'
    for name, values in tables.items():
        manifest += f"\n[{name}]\n" + "\n".join(f"{k} = {toml_value(v)}" for k, v in values.items()) + "\n"
    (output / "Cargo.toml").write_text(manifest)
    # Verify copies against the frozen original byte hashes; manifests are the only exceptions.
    for relative, expected in hashes.items():
        parts = Path(relative).parts
        if len(parts) > 2 and parts[1] in CRATES and parts[2:] != ("Cargo.toml",):
            if sha(output.joinpath(*parts[1:])) != expected:
                raise ValueError(f"source copy changed bytes: {relative}")
    (output / "source-hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
    receipt = dict(schema="hepta.ndu.isolated-native-build.v1", source_sha256=hashes,
                   build_script_sha256=sha(Path(__file__)),
                   scope="isolated native replay; exact source copies with generated minimal manifests",
                   repository_dependencies_modified=False, original_repository_lockfile_used=False,
                   full_workspace_qualification=False, production_owner_integrated=False,
                   general_fbsde_solved=False, commands=[], clippy_requested=args.clippy)

    def run(command, name):
        result = subprocess.run(command, cwd=output, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=1200)
        (output / f"{name}.log").write_text(result.stdout)
        receipt["commands"].append(dict(command=command, returncode=result.returncode, log=f"{name}.log"))
        print(result.stdout, end="", flush=True)
        result.check_returncode()
        return result.stdout.strip()

    try:
        receipt["cargo"] = run([cargo, "--version"], "cargo-version")
        rustc = str(Path(cargo).with_name("rustc"))
        receipt["rustc"] = run([rustc, "--version", "--verbose"], "rustc-version")
        run([cargo, "generate-lockfile"], "resolve")
        run([cargo, "build", "--locked", "--target-dir", str(output / "target"),
             "-p", "codex-hepta-ndu", "--bin", "ndu-group-replay"], "build")
        if args.clippy:
            run([cargo, "clippy", "--locked", "--target-dir", str(output / "target"),
                 "-p", "codex-hepta-ndu", "--bin", "ndu-group-replay",
                 "--", "-D", "warnings"], "clippy")
        binary = output / "target/debug/ndu-group-replay"
        if not binary.is_file():
            binary = binary.with_suffix(".exe")
        receipt.update(build_passed=True, binary=str(binary), binary_sha256=sha(binary))
    except (OSError, subprocess.SubprocessError) as error:
        receipt.update(build_passed=False, error_type=type(error).__name__)
        raise
    finally:
        generated = [output / "Cargo.toml", output / "Cargo.lock", output / "rust-toolchain.toml"]
        generated += [output / crate / "Cargo.toml" for crate in CRATES]
        receipt["generated_sha256"] = {str(path.relative_to(output)): sha(path) for path in generated if path.is_file()}
        (output / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"Isolated native replay binary: {receipt['binary']}")


if __name__ == "__main__":
    main()
