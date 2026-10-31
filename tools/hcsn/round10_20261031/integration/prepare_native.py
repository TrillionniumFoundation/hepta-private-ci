"""Build an isolated, hash-verified Hepta workspace from the recorded source.

The original three Cargo manifests and every original Rust source are retained.
Only a small enclosing workspace is generated. This does not modify codex-rs.
Run the generated justfile to build and test; no preserved rlibs are accepted.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare(build, offline_sources=None):
    identity = json.loads((HERE / "UPSTREAM_NATIVE.json").read_text())
    build.mkdir(parents=True, exist_ok=True)

    def restore(item):
        rel = item["path"]
        if offline_sources:
            data = (offline_sources / rel).read_bytes()
        else:
            url = ("https://raw.githubusercontent.com/" + identity["repository"]
                   + "/" + identity["commit"] + "/" + rel)
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != item["git_blob_sha"]:
            raise ValueError((rel, "upstream Git blob mismatch", blob))
        dest = build / rel.removeprefix("codex-rs/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return {"path": rel, "git_blob_sha": blob, "sha256": digest(data)}

    with ThreadPoolExecutor(max_workers=6) as executor:
        restored = list(executor.map(restore, identity["files"]))
    candidates = {
        "hcsn-owner-baseline": ROOT / "tools/hcsn/round9_20261031/native/src/main.rs",
        "hcsn-owner-preread": ROOT / "tools/hcsn/round10_20261031/native/main.rs",
    }
    members = ["hepta-types", "hepta-infer-core", "hepta-neuron"]
    packages = []
    owned = {}
    for name, source in candidates.items():
        if not source.exists():
            continue
        dest = build / name
        dest.mkdir(exist_ok=True)
        manifest = f'''[package]
name = "{name}"
version.workspace = true
edition.workspace = true
license.workspace = true
[[bin]]
name = "{name}"
path = {json.dumps(str(source))}
[dependencies]
codex-hepta-neuron = {{path = "../hepta-neuron"}}
codex-hepta-types = {{path = "../hepta-types"}}
serde = {{workspace = true, features = ["derive"]}}
serde_json.workspace = true
libc = "=0.2.182"
'''
        (dest / "Cargo.toml").write_text(manifest)
        members.append(name)
        packages.append(name)
        for path in sorted(source.parent.rglob("*.rs")):
            owned[str(path.relative_to(ROOT))] = digest(path.read_bytes())
    workspace = '''[workspace]
resolver = "3"
members = MEMBERS
[workspace.package]
version = "0.0.0"
edition = "2024"
license = "Apache-2.0"
[workspace.dependencies]
serde = {version = "=1.0.228", features = ["rc"]}
serde_json = "=1.0.149"
sha2 = "=0.10.9"
pretty_assertions = "=1.4.1"
[workspace.lints.rust]
unsafe_code = "warn"
'''.replace("MEMBERS", json.dumps(members))
    (build / "Cargo.toml").write_text(workspace)
    source_digest = digest(json.dumps({"upstream": restored, "owned": owned},
                                      sort_keys=True).encode())
    selected = " ".join("-p " + name for name in packages)
    justfile = f'''set dotenv-load := false
export HEPTA_TASK_NATIVE_SOURCE_DIGEST := "{source_digest}"
test:
    cargo test --manifest-path {build / 'Cargo.toml'} {selected}
build:
    cargo build --release --manifest-path {build / 'Cargo.toml'} {selected}
'''
    (build / "justfile").write_text(justfile)
    report = {"schema": "hepta.r10.clean-build-inputs.v1",
              "upstream_commit": identity["commit"], "upstream": restored,
              "owned": owned, "source_digest": source_digest,
              "generated_workspace_sha256": digest(workspace.encode()),
              "packages": packages, "fresh_registry_build_required": True,
              "prebuilt_rlibs_used": False}
    (build / "BUILD_INPUTS.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"upstream_files": len(restored), "packages": packages,
                      "source_digest": source_digest}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--offline-sources", type=Path)
    args = parser.parse_args()
    prepare(args.build.resolve(), args.offline_sources)
