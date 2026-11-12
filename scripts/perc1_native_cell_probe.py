"""Build the real native Cell encoder with three unchanged repository libraries.

The standalone manifests exclude unrelated workspace packages, not implementation
code. This exercises PerceptionCellEncoderV1 and its real Cell/type contracts;
it does not execute native Cell state ownership, inference, or daemon admission.
All repository source files must match the explicitly selected Git tree.
"""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

BASELINE = "72569fba94a38f7bb0628409cbb05b62fa6c9627"
CRATES = ("hepta-types", "hepta-infer-core", "hepta-neuron")
RUST = r"""use codex_hepta_neuron::{
    CellEncodedInputV1, CellEncodingRequestV1, CellExecutionError, CellInputEncoderV1,
    CellScopeV1, PerceptionActorSourceV1, PerceptionCellEncoderV1, PerceptionEncoderBindingV1,
    PerceptionObservationV1, PerceptionRepresentationV1, PerceptionSourcePinV1,
    canonical_feature_vector_digest_v1,
};
use codex_hepta_types::{Digest32, StableId};
use serde::Deserialize;
use std::{error::Error, fs, io::{Read, Write}, path::Path};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ScopeInput {
    agent_id: String,
    cell_id: String,
    run_id: String,
    principal_digest: [u8; 32],
}
impl ScopeInput {
    fn into_scope(self) -> Result<CellScopeV1, Box<dyn Error>> {
        let principal_digest = Digest32::from_array(self.principal_digest);
        if principal_digest.is_zero() { return Err("empty principal binding".into()); }
        Ok(CellScopeV1 {
            agent_id: StableId::new(self.agent_id)?,
            cell_id: StableId::new(self.cell_id)?,
            run_id: StableId::new(self.run_id)?,
            principal_digest,
        })
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Expected {
    scope: ScopeInput,
    source_frontier: [u8; 32],
    encoder_digest: [u8; 32],
    latent_model_digest: [u8; 32],
    representation: PerceptionRepresentationV1,
    feature_dimension: usize,
    source_pin: PerceptionSourcePinV1,
}
fn read(path: &Path, limit: usize) -> Result<Vec<u8>, Box<dyn Error>> {
    let file = fs::File::open(path)?;
    if !file.metadata()?.is_file() { return Err("regular input required".into()); }
    let mut bytes = Vec::new();
    file.take((limit + 1) as u64).read_to_end(&mut bytes)?;
    if bytes.is_empty() || bytes.len() > limit { return Err("input byte bound exceeded".into()); }
    Ok(bytes)
}
fn write(path: &Path, value: &serde_json::Value) -> Result<(), Box<dyn Error>> {
    let mut file = fs::OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(&serde_json::to_vec_pretty(value)?)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}
fn different(value: Digest32) -> Digest32 {
    let mut bytes = value.into_array();
    bytes[0] ^= 1;
    if bytes == [0; 32] { bytes[31] = 1; }
    Digest32::from_array(bytes)
}
fn consume(args: &[std::ffi::OsString]) -> Result<(), Box<dyn Error>> {
    if args.len() != 4 { return Err("consume WIRE RASTER EXPECTED RESULT".into()); }
    let wire = read(Path::new(&args[0]), 65_536)?;
    let raster = read(Path::new(&args[1]), 64 * 1024 * 1024)?;
    let expected: Expected = serde_json::from_slice(&read(Path::new(&args[2]), 65_536)?)?;
    let scope = expected.scope.into_scope()?;
    let frontier = Digest32::from_array(expected.source_frontier);
    let binding = PerceptionEncoderBindingV1 {
        encoder_digest: Digest32::from_array(expected.encoder_digest),
        latent_model_digest: Digest32::from_array(expected.latent_model_digest),
        residual_predictor_digest: None,
        representation: expected.representation,
        feature_dimension: expected.feature_dimension,
    };
    let actor = PerceptionActorSourceV1::new(expected.source_pin.clone(), &raster)?;
    let sources = [actor];
    let encoder = PerceptionCellEncoderV1::new(binding.clone(), &sources)?;
    let invoke = |scope: &CellScopeV1, source_frontier, encoder_digest|
        -> Result<CellEncodedInputV1, CellExecutionError> {
        encoder.encode(&CellEncodingRequestV1 {
            scope, source_frontier, encoder_digest, observation: &wire, checkpoint: None,
        })
    };
    let encoded = invoke(&scope, frontier, binding.encoder_digest)?;
    let observation = PerceptionObservationV1::decode(&wire)?;
    let values: Vec<i64> = observation.latents.iter().flat_map(|v| v.values_q24.iter().copied()).collect();
    if observation.encode()? != wire
        || encoded.feature_vector_q24 != values
        || encoded.encoder_digest != binding.encoder_digest
        || encoded.consumed_bytes != wire.len()
        || encoded.truncated_bytes != 0 {
        return Err("native Cell encoder output/byte accounting differs".into());
    }
    let mut changed_scope = scope.clone();
    changed_scope.principal_digest = different(scope.principal_digest);
    let scope_rejected = matches!(invoke(&changed_scope, frontier, binding.encoder_digest), Err(CellExecutionError::ScopeMismatch));
    let frontier_rejected = matches!(invoke(&scope, different(frontier), binding.encoder_digest), Err(CellExecutionError::StaleSource));
    let encoder_rejected = matches!(invoke(&scope, frontier, different(binding.encoder_digest)), Err(CellExecutionError::EncodingMismatch));
    let mut changed_binding = binding.clone();
    changed_binding.latent_model_digest = different(binding.latent_model_digest);
    let changed_encoder = PerceptionCellEncoderV1::new(changed_binding, &sources)?;
    let model_rejected = matches!(changed_encoder.encode(&CellEncodingRequestV1 {
        scope: &scope, source_frontier: frontier, encoder_digest: binding.encoder_digest,
        observation: &wire, checkpoint: None,
    }), Err(CellExecutionError::EncodingMismatch));
    let mut corrupted_raster = raster.clone();
    corrupted_raster[0] ^= 1;
    let raster_rejected = PerceptionActorSourceV1::new(expected.source_pin, &corrupted_raster).is_err();
    if !(scope_rejected && frontier_rejected && encoder_rejected && model_rejected && raster_rejected) {
        return Err("native rejection control failed".into());
    }
    write(Path::new(&args[3]), &serde_json::json!({
        "schema": "perc1.native-cell-encoder-readback.v1",
        "status": "PASS_NATIVE_CELL_ENCODER_ONLY",
        "scope": "unchanged PerceptionCellEncoderV1 with actual CellScope/request/trait/types",
        "scientific_status": "HOLD",
        "native_cell_owner_exercised": false, "inference_exercised": false,
        "daemon_admission_exercised": false, "authority_granted": false,
        "scope_digest": scope.digest().to_string(),
        "source_frontier": frontier.to_string(),
        "encoder_digest": encoded.encoder_digest.to_string(),
        "feature_scalars": encoded.feature_vector_q24.len(),
        "feature_vector_digest": canonical_feature_vector_digest_v1(&encoded.feature_vector_q24).to_string(),
        "feature_vector_q24": encoded.feature_vector_q24,
        "consumed_bytes": encoded.consumed_bytes, "truncated_bytes": encoded.truncated_bytes,
        "wire_sha256": Digest32::of_bytes(&wire).to_string(),
        "raster_sha256": Digest32::of_bytes(&raster).to_string(),
        "canonical_roundtrip_equal": true,
        "negative_controls": {
            "scope": scope_rejected, "frontier": frontier_rejected,
            "encoder": encoder_rejected, "model": model_rejected, "raster": raster_rejected,
        },
    }))
}
fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    match args.first().and_then(|v| v.to_str()) {
        Some("scope") if args.len() == 3 => {
            let input: ScopeInput = serde_json::from_slice(&read(Path::new(&args[1]), 4096)?)?;
            let scope = input.into_scope()?;
            write(Path::new(&args[2]), &serde_json::json!({
                "schema": "perc1.native-cell-scope.v1",
                "scope_digest": scope.digest().into_array(),
                "scope_digest_hex": scope.digest().to_string(),
                "authority_granted": false,
            }))
        },
        Some("consume") => consume(&args[1..]),
        _ => Err("usage: scope INPUT RESULT | consume WIRE RASTER EXPECTED RESULT".into()),
    }
}
"""


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _source_pins(root, ref):
    prefixes = ["codex-rs/" + name + "/src" for name in CRATES]
    output = subprocess.check_output(
        ["git", "ls-tree", "-r", "-z", ref, "--", *prefixes], cwd=root
    )
    pins = {}
    for entry in output.split(b"\0"):
        if not entry:
            continue
        metadata, path = entry.decode().split("\t")
        mode, kind, git_sha = metadata.split()
        if mode != "100644" or kind != "blob" or not path.endswith(".rs"):
            raise ValueError("unsupported native source entry: " + path)
        file = root / path
        if file.is_symlink() or not file.is_file():
            raise ValueError("materialize the exact native source first: " + path)
        raw = file.read_bytes()
        actual = hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest()
        if actual != git_sha:
            raise ValueError("native source differs from selected Git tree: " + path)
        pins[path] = {"git_blob_sha": git_sha, "sha256": _sha(raw)}
    for name in CRATES:
        if "codex-rs/" + name + "/src/lib.rs" not in pins:
            raise ValueError("source tree lacks required library: " + name)
    return pins


def build(root, target, ref, cargo, rustc, *, source=RUST, offline=True):
    root, target = root.resolve(), target.resolve()
    pins = _source_pins(root, ref)
    target.mkdir(parents=True, exist_ok=False)
    (target / "src").mkdir()
    manifests = {
        "Cargo.toml": """[workspace]
members = ["hepta-types", "hepta-infer-core", "hepta-neuron"]
resolver = "3"
[package]
name = "perc1-native-cell-probe"
version = "0.0.0"
edition = "2024"
[dependencies]
codex-hepta-types = { path = "hepta-types" }
codex-hepta-infer-core = { path = "hepta-infer-core" }
codex-hepta-neuron = { path = "hepta-neuron" }
serde = { version = "=1.0.229", features = ["derive"] }
serde_json = "=1.0.154"
[profile.dev]
debug = 0
"""
    }
    for name in CRATES:
        (target / name).mkdir()
        manifest = (
            '[package]\nname = "codex-'
            + name
            + '"\nversion = "0.0.0"\nedition = "2024"\n'
            '[lib]\nname = "codex_'
            + name.replace("-", "_")
            + '"\npath = '
            + json.dumps(str(root / "codex-rs" / name / "src/lib.rs"))
            + "\n[dependencies]\n"
        )
        if name == "hepta-types":
            manifest += 'sha2 = "=0.10.9"\n'
        else:
            manifest += 'codex-hepta-types = { path = "../hepta-types" }\n'
            manifest += 'serde = { version = "=1.0.229", features = ["derive"] }\nserde_json = "=1.0.154"\n'
        if name == "hepta-neuron":
            manifest += 'codex-hepta-infer-core = { path = "../hepta-infer-core" }\n'
        manifests[name + "/Cargo.toml"] = manifest
    for path, text in manifests.items():
        (target / path).write_text(text)
    (target / "src/main.rs").write_text(source)
    command = [
        cargo,
        "build",
        "--offline",
        "--jobs",
        "2",
        "--manifest-path",
        str(target / "Cargo.toml"),
    ]
    if not offline:
        command.remove("--offline")
    completed = subprocess.run(
        command,
        cwd=target,
        env=dict(os.environ, RUSTC=rustc),
        capture_output=True,
        text=True,
    )
    (target / "build.stdout.log").write_text(completed.stdout)
    (target / "build.stderr.log").write_text(completed.stderr)
    unchanged = all(
        _sha((root / path).read_bytes()) == pin["sha256"] for path, pin in pins.items()
    )
    binary = target / "target/debug/perc1-native-cell-probe"
    record = {
        "schema": "perc1.native-cell-probe-build.v1",
        "source_ref": ref,
        "command": command,
        "returncode": completed.returncode,
        "sources": pins,
        "sources_unchanged": unchanged,
        "probe_source_sha256": _sha(source.encode()),
        "manifests": {name: _sha(text.encode()) for name, text in manifests.items()},
        "rustc": subprocess.check_output([rustc, "--version"], text=True).strip(),
        "scope": "actual three repository libraries; standalone manifests; no workspace tests",
    }
    for name, path in (
        ("cargo_lock_sha256", target / "Cargo.lock"),
        ("binary_sha256", binary),
    ):
        if path.is_file():
            record[name] = _sha(path.read_bytes())
    (target / "build.json").write_text(json.dumps(record, indent=2) + "\n")
    if completed.returncode or not unchanged:
        raise RuntimeError("native build/source check failed; original logs retained")
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--source-ref", default=BASELINE)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--rustc", default="rustc")
    args = parser.parse_args()
    print(build(args.repo, args.build_dir, args.source_ref, args.cargo, args.rustc))


if __name__ == "__main__":
    main()
