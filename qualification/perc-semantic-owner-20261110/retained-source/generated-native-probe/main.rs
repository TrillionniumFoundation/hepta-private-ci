use codex_hepta_neuron::{
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
