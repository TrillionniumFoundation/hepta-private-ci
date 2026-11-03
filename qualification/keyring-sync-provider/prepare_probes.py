"""Create isolated old/new consumers of the exact production wrapper source."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-crate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    archive = args.official_crate.read_bytes()
    assert (
        sha(archive)
        == "eebcc3aff044e5944a8fbaf69eb277d11986064cba30c468730e8b9909fb551c"
    )
    args.output.mkdir(parents=True, exist_ok=False)
    official = args.output / "official"
    official.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as members:
        for member in members:
            path = Path(member.name)
            assert member.isfile() and path.parts[0] == "keyring-3.6.3"
            assert ".." not in path.parts
            target = official / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(members.extractfile(member).read())
    wrapper = repo / "codex-rs/keyring-store/src/lib.rs"
    candidate = repo / "codex-rs/third_party/keyring-3.6.3"
    inputs = {str(wrapper.relative_to(repo)): sha(wrapper.read_bytes())}
    inputs.update(
        {
            str(p.relative_to(repo)): sha(p.read_bytes())
            for p in candidate.rglob("*")
            if p.is_file()
        }
    )
    for label, provider, features in [
        (
            "baseline",
            official / "keyring-3.6.3",
            ["crypto-rust", "linux-native-async-persistent"],
        ),
        ("candidate", candidate, ["crypto-rust-sync", "linux-native-sync-persistent"]),
    ]:
        project = args.output / label
        (project / "src").mkdir(parents=True)
        shutil.copyfile(wrapper, project / "src/production_keyring_store.rs")
        shutil.copyfile(Path(__file__).with_name("probe.rs"), project / "src/main.rs")
        manifest = f"""[package]
name = "hepta-keyring-{label}-probe"
version = "0.0.0"
edition = "2024"
[workspace]
[dependencies]
keyring = {{ path = {json.dumps(str(provider))}, default-features = false, features = {json.dumps(features)} }}
tracing = "=0.1.44"
"""
        (project / "Cargo.toml").write_text(manifest)
        if label == "baseline":
            lock = subprocess.check_output(
                [
                    "git",
                    "show",
                    "4b1a326ec50c28e8803d390e81d2f03457cc7499:codex-rs/Cargo.lock",
                ],
                cwd=repo,
            )
            (project / "Cargo.lock").write_bytes(lock)
        else:
            shutil.copyfile(repo / "codex-rs/Cargo.lock", project / "Cargo.lock")
    (args.output / "inputs-before.json").write_text(json.dumps(inputs, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "inputs": len(inputs),
                "scope": "exact production wrapper; separate official old and patched new providers; no provider override",
            }
        )
    )


if __name__ == "__main__":
    main()
