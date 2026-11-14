"""Build a readback probe against unchanged repository perception/type sources.

This is a standalone observation validator, not the Cell daemon or an admission
owner. The source files are compiled by absolute path; validation is not copied.
"""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

RUST = r"""#![allow(dead_code)]
#[path = @PERCEPTION_SOURCE@]
mod perception_source;
#[path = @PERCEPTION@]
mod perception;

use codex_hepta_types::Digest32;
use perception::{PerceptionEncoderBindingV1, PerceptionObservationV1, PerceptionRepresentationV1};
use perception_source::{PerceptionActorSourceV1, PerceptionSourcePinV1};
use serde::Deserialize;
use std::{error::Error, fs, io::Write};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Expected {
    scope_digest: [u8; 32],
    source_frontier: [u8; 32],
    encoder_digest: [u8; 32],
    latent_model_digest: [u8; 32],
    representation: PerceptionRepresentationV1,
    feature_dimension: usize,
    source_pin: PerceptionSourcePinV1,
}

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 4 {
        return Err("usage: probe observation.json raster.rgb expected.json result.json".into());
    }
    let wire = fs::read(&args[0])?;
    let raster = fs::read(&args[1])?;
    let expected: Expected = serde_json::from_slice(&fs::read(&args[2])?)?;
    let observation = PerceptionObservationV1::decode(&wire)?;
    if observation.scope_digest != expected.scope_digest || observation.source_frontier != expected.source_frontier {
        return Err("scope/frontier mismatch".into());
    }
    let binding = PerceptionEncoderBindingV1 {
        encoder_digest: Digest32::from_array(expected.encoder_digest),
        latent_model_digest: Digest32::from_array(expected.latent_model_digest),
        residual_predictor_digest: None,
        representation: expected.representation,
        feature_dimension: expected.feature_dimension,
    };
    let actor = PerceptionActorSourceV1::new(expected.source_pin, &raster)?;
    observation.validate(&binding, &[actor])?;
    let encoded = observation.encode()?;
    if encoded != wire {
        return Err("native/Python canonical wire bytes differ".into());
    }
    let result = serde_json::json!({
        "schema": "perc1.native-readback.v1", "status": "PASS",
        "scope": "unchanged native observation decode/validate/encode; no Cell owner admission",
        "representation": observation.representation,
        "evidence_count": observation.evidence.len(),
        "feature_scalars": binding.feature_dimension,
        "wire_bytes": wire.len(), "actor_raster_bytes": raster.len(),
        "evidence_raw_bytes": observation.evidence.iter().map(|e| e.raw_bytes.len()).sum::<usize>(),
        "wire_sha256": Digest32::of_bytes(&wire).to_string(),
        "raster_sha256": Digest32::of_bytes(&raster).to_string(),
        "evidence_set_digest": observation.evidence_digest()?.to_string(),
        "canonical_roundtrip_equal": true
    });
    let mut output = fs::OpenOptions::new().write(true).create_new(true).open(&args[3])?;
    output.write_all(&serde_json::to_vec_pretty(&result)?)?;
    output.write_all(b"\n")?;
    Ok(())
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    root, target = args.repo.resolve(), args.build_dir.resolve()
    files = [
        root / "codex-rs/hepta-neuron/src/perception.rs",
        root / "codex-rs/hepta-neuron/src/perception_source.rs",
    ]
    files += sorted((root / "codex-rs/hepta-types/src").glob("*.rs"))
    source_hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    target.mkdir(parents=True, exist_ok=False)
    (target / "types").mkdir()
    (target / "src").mkdir()
    (target / "Cargo.toml").write_text("""[workspace]
members = ["types"]
resolver = "3"
[package]
name = "perc1-native-probe"
version = "0.0.0"
edition = "2024"
[dependencies]
codex-hepta-types = { path = "types" }
serde = { version = "=1.0.229", features = ["derive"] }
serde_json = "=1.0.154"
[profile.dev]
debug = 0
""")
    types_path = json.dumps(
        str(root / "codex-rs/hepta-types/src/lib.rs"), ensure_ascii=False
    )
    (target / "types/Cargo.toml").write_text(
        """[package]
name = "codex-hepta-types"
version = "0.0.0"
edition = "2024"
[lib]
name = "codex_hepta_types"
path = """
        + types_path
        + """
[dependencies]
sha2 = "=0.10.9"
"""
    )
    source = RUST.replace(
        "@PERCEPTION@", json.dumps(str(files[0]), ensure_ascii=False)
    ).replace("@PERCEPTION_SOURCE@", json.dumps(str(files[1]), ensure_ascii=False))
    (target / "src/main.rs").write_text(source)
    command = [args.cargo, "build", "--manifest-path", str(target / "Cargo.toml")]
    if args.offline:
        command.append("--offline")
    env = dict(os.environ, RUSTC=args.rustc)
    completed = subprocess.run(command, env=env, capture_output=True, text=True)
    (target / "build.stdout.log").write_text(completed.stdout)
    (target / "build.stderr.log").write_text(completed.stderr)
    record = {
        "schema": "perc1.native-probe-build.v1",
        "command": command,
        "returncode": completed.returncode,
        "sources": source_hashes,
        "rustc": subprocess.check_output([args.rustc, "--version"], text=True).strip(),
        "sources_unchanged": all(
            hashlib.sha256((root / path).read_bytes()).hexdigest() == pin
            for path, pin in source_hashes.items()
        ),
        "probe_source_sha256": hashlib.sha256(source.encode()).hexdigest(),
    }
    lock = target / "Cargo.lock"
    if lock.exists():
        record["cargo_lock_sha256"] = hashlib.sha256(lock.read_bytes()).hexdigest()
    binary = target / "target/debug/perc1-native-probe"
    if binary.exists():
        record["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
    (target / "build.json").write_text(json.dumps(record, indent=2) + "\n")
    if completed.returncode or not record["sources_unchanged"]:
        raise RuntimeError(
            "native build/source check failed; retained logs identify the attempt"
        )
    print(binary)


if __name__ == "__main__":
    main()
