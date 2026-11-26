//! Offline numeric observations for an independent evaluation owner. This
//! process cannot issue model selection, resource grants or action credentials.
use std::error::Error;
use std::io::BufRead;
use std::io::Read;
use std::io::Write;
use std::path::Path;

use codex_hepta_infer_worker_host::local_cpu_model::CpuNeuronModelDriver;
use codex_hepta_infer_worker_host::model_worker::ModelDriver;
use codex_hepta_infer_worker_host::model_worker::NeuronFeatureDriver;
use codex_hepta_infer_worker_host::model_worker::NeuronFeatureRequest;
use codex_hepta_infer_worker_host::model_worker::WorkerRequest;
use codex_hepta_types::Digest32;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    request_id: String,
    feature_vector_q24: Vec<i64>,
    expected_output_width: usize,
}

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() != 2 {
        return Err(
            "usage: hepta-cpu-neuron-score ABSOLUTE_MANIFEST SHA256 < features.jsonl".into(),
        );
    }
    let pin: Digest32 = args[1].parse()?;
    let mut driver = CpuNeuronModelDriver::open(Path::new(&args[0]), pin)?;
    let manifest = driver.manifest().clone();
    let encoder = driver.encoder_digest().to_owned();
    let head = driver.head_digest().to_owned();
    let handle = driver.load(&manifest)?;
    let mut source = std::io::stdin().lock();
    let mut output = std::io::stdout().lock();
    loop {
        let mut line = String::new();
        let length = source.by_ref().take(16 * 1024 + 1).read_line(&mut line)?;
        if length == 0 {
            break;
        }
        if length > 16 * 1024 || !line.ends_with('\n') {
            return Err("bounded complete feature line required".into());
        }
        let input_digest = Digest32::of_bytes(line.as_bytes());
        let input: Input = serde_json::from_str(&line)?;
        if input.request_id.is_empty()
            || input.request_id.len() > 128
            || input.feature_vector_q24.len() > 512
        {
            return Err("feature identity or vector budget".into());
        }
        let feature_bytes: Vec<u8> = input
            .feature_vector_q24
            .iter()
            .flat_map(|value| value.to_be_bytes())
            .collect();
        let feature_digest = Digest32::of_bytes(&feature_bytes);
        let executed_at_ms = u64::try_from(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)?
                .as_millis(),
        )?;
        let observation = driver.run_neuron_features(
            &handle,
            &NeuronFeatureRequest {
                authorization: WorkerRequest {
                    request_id: input.request_id.clone(),
                    reservation_id: String::new(),
                    model_digest: manifest.model_digest.clone(),
                    payload_digest: input_digest.to_string(),
                    maximum_tokens: manifest.maximum_tokens,
                    deadline_ms: 0,
                    lease_payload_digest: String::new(),
                    reservation_model_digest: String::new(),
                    reservation_maximum_tokens: 0,
                    cancelled: false,
                },
                encoder_digest: encoder.clone(),
                head_digest: head.clone(),
                weights_digest: manifest.weights_digest.clone(),
                input_digest: input_digest.to_string(),
                feature_vector_q24: input.feature_vector_q24,
                expected_output_width: input.expected_output_width,
            },
        )?;
        serde_json::to_writer(
            &mut output,
            &serde_json::json!({
                "schema":"hepta.cpu-neuron.offline-observation.v1", "request_id":input.request_id,
            "input_line_digest":input_digest.to_string(), "model_manifest_digest":manifest.model_digest,
            "input_digest":feature_digest.to_string(), "executed_at_ms":executed_at_ms,
            "terminal_observed":observation.terminal_observed, "succeeded":observation.succeeded,
            "runtime_digest":manifest.runtime_digest,
                "weights_digest":manifest.weights_digest, "encoder_digest":observation.encoder_digest,
                "head_digest":observation.head_digest, "drive_q24":observation.drive_q24,
                "prediction_q24":observation.prediction_q24,
                "latency_micros":observation.latency_micros,
                "resident_bytes":observation.observed_memory_bytes,
                "transient_allocation_bytes":observation.transient_allocation_bytes,
                "qualified":false, "authority_grants_any":false
            }),
        )?;
        output.write_all(b"\n")?;
    }
    driver.unload(handle)?;
    Ok(())
}
