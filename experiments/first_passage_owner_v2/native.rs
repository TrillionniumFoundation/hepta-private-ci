//! Original V1 numerical profile composed with its real NeuronRuntime owner.
//! The config/model block below is copied byte-for-byte from the frozen bridge.
use crate::contract::Request;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::Instant;
const Q: i64 = 1 << 24;
const LIMIT: usize = 256;
const PROFILE: &str = "hepta.fpt-adaptive.owner-research.v1";
fn id(value: &str) -> Result<StableId, String> {
    StableId::new(value).map_err(|error| error.to_string())
}

fn digest(value: &str) -> Result<Digest32, String> {
    value.parse::<Digest32>().map_err(|error| error.to_string())
}

fn marker(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn config() -> Result<(SparseConfig, NeuronRuntimeConfigV1), String> {
    let generation = Generation::new(1).map_err(|error| error.to_string())?;
    let native = SparseConfig {
        model_digest: marker("identity.numeric.fpt.features.v1"),
        normalization_digest: marker("margin.risk.activity.resource.time.q24.v1"),
        generation,
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: 0,
        inhibition: vec![],
        activity_decay_q24: Q / 2,
        target_activity_q24: Q / 5,
        threshold_rate_q24: 0,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    };
    let runtime = NeuronRuntimeConfigV1 {
        config_id: id(PROFILE)?,
        generation,
        model_id: id("numerical.fpt.identity.v1")?,
        model_manifest_digest: marker(PROFILE),
        encoder_digest: marker("five.named.q24.features"),
        head_digest: native.model_digest,
        weights_digest: marker("5x5.identity.matrix"),
        tokenizer_digest: marker("numeric.vector.no-tokenizer"),
        preprocessor_digest: marker("checked.q24.vector.v1"),
        quantization_digest: marker("signed.q24"),
        runtime_digest: marker(env!("HEPTA_FPT_NATIVE_SOURCE_DIGEST")),
        device_digest: marker(std::env::consts::ARCH),
        normalization_digest: native.normalization_digest,
        native_config_digest: native.digest().map_err(|error| error.to_string())?,
        input_feature_dimension: 5,
        state_width: 5,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: marker("research.unestablished.worst-case-bounds.v1"),
            ood_artifact_digest: marker("research.unestablished.worst-case-bounds.v1"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: LIMIT as u64,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 16 * Q,
            minimum_confidence_ppm: 0,
            maximum_ood_ppm: 1_000_000,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 20,
            measured_ece_ppm: 1_000_000,
            maximum_ece_ppm: 1_000_000,
            measured_false_acceptance_ppm: 1_000_000,
            maximum_false_acceptance_ppm: 1_000_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 10_000_000,
            p99_latency_micros: 30_000_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    };
    Ok((native, runtime))
}

struct NumericalModel(NeuronRuntimeConfigV1);

impl NeuronModelPort for NumericalModel {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        let start = Instant::now();
        let drive_q24 = request.feature_vector_q24.clone();
        let prediction_q24 = drive_q24.clone();
        let runtime_receipt = LocalModelRuntimeReceiptV1 {
            model_id: self.0.model_id.clone(),
            model_manifest_digest: self.0.model_manifest_digest,
            weights_digest: self.0.weights_digest,
            tokenizer_digest: self.0.tokenizer_digest,
            preprocessor_digest: self.0.preprocessor_digest,
            quantization_id: id("signed.q24").map_err(|_| NeuronModelError::Unavailable)?,
            quantization_digest: self.0.quantization_digest,
            backend_id: id("native.numeric.identity").map_err(|_| NeuronModelError::Unavailable)?,
            runtime_digest: self.0.runtime_digest,
            device_identity_digest: self.0.device_digest,
            latency_micros: start.elapsed().as_micros() as u64,
            resident_bytes: ((drive_q24.capacity() + prediction_q24.capacity()) * size_of::<i64>())
                as u64,
        };
        let output_digest =
            canonical_model_output_digest_v1(&drive_q24, &prediction_q24, &runtime_receipt)
                .map_err(|_| NeuronModelError::Unavailable)?;
        Ok(NeuronModelOutputV1 {
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            output_digest,
            drive_q24,
            prediction_q24,
            queue_age_micros: 0,
            transient_allocation_bytes: 80,
            runtime_receipt,
        })
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Receipt {
    pub sequence: u64,
    pub before: String,
    pub after: String,
    pub abstain: bool,
}

pub struct Owner {
    runtime: NeuronRuntime<FileAnchorWitnessStore>,
    model: NumericalModel,
}

impl Owner {
    pub fn open(
        root: &Path,
        request: &Request,
        expected: &str,
        sequence: u64,
    ) -> Result<Self, String> {
        let subject = id(&request.config.run_id)?;
        let mut bytes = b"hepta.neuron.subject-scope.v1".to_vec();
        bytes.extend_from_slice(&(subject.as_str().len() as u32).to_be_bytes());
        bytes.extend_from_slice(subject.as_str().as_bytes());
        let scope = JournalScope {
            scope_digest: Digest32::of_bytes(&bytes),
            objective_digest: digest(&request.config.objective_digest)?,
        };
        let open = |name: &str| -> Result<File, String> {
            let path = root.join(name);
            crate::store::regular_exists(&path)?;
            OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .mode(0o600)
                .custom_flags(crate::store::OPEN_FLAGS)
                .open(path)
                .map_err(|e| e.to_string())
        };
        let (sparse, config) = config()?;
        let witness = FileAnchorWitnessStore::open(
            open("native-witness.bin")?,
            scope,
            sparse.generation,
            LIMIT,
        )
        .map_err(|e| e.to_string())?;
        let anchor = witness.current().map_err(|e| e.to_string())?;
        let actual = anchor.map_or(Digest32::ZERO, |a| a.checkpoint_digest);
        if actual != digest(expected)? || anchor.map_or(0, |a| a.sequence) != sequence {
            return Err("native owner/settlement frontier mismatch".into());
        }
        let runtime = if let Some(a) = anchor {
            NeuronRuntime::recover(
                open("native-journal.bin")?,
                sparse,
                scope,
                LIMIT,
                config.clone(),
                a,
                witness,
            )
        } else {
            NeuronRuntime::bootstrap(
                open("native-journal.bin")?,
                sparse,
                scope,
                LIMIT,
                config.clone(),
                witness,
            )
        }
        .map_err(|e| e.to_string())?;
        if runtime
            .current_anchor()
            .map_err(|e| e.to_string())?
            .map_or(Digest32::ZERO, |a| a.checkpoint_digest)
            != actual
        {
            return Err("native committed suffix requires reconciliation".into());
        }
        Ok(Self {
            runtime,
            model: NumericalModel(config),
        })
    }

    pub fn tick(&mut self, request: &Request, expected: &str) -> Result<Receipt, String> {
        let features = request.features_q24.to_vec();
        let input = NeuronTickInputV1 {
            tick_id: id(&format!("fpt.v2.{}", request.sequence))?,
            subject_id: id(&request.config.run_id)?,
            logical_sequence: request.sequence,
            monotonic_time_micros: request.owner_monotonic_us,
            checkpoint_digest: digest(expected)?,
            input_feature_digest: canonical_feature_vector_digest_v1(&features),
            feature_vector_q24: features,
            objective_digest: digest(&request.config.objective_digest)?,
            ndu_snapshot_digest: digest(&crate::contract::hash(request)?)?,
            body_generation: Some(1),
            modulator_digest: None,
        };
        let output = self
            .runtime
            .tick(&mut self.model, input)
            .map_err(|e| e.to_string())?;
        Ok(Receipt {
            sequence: request.sequence,
            before: output.tick.checkpoint_before.to_string(),
            after: output.tick.checkpoint_after.to_string(),
            abstain: output.signal.abstain,
        })
    }
}
