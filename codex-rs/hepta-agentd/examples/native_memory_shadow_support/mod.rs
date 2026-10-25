//! Explicit controlled qualification context and registered shadow profile.
//! No production Objective/NDU authority or calibration is manufactured here.

mod evidence;
pub use evidence::journal_evidence;
pub use evidence::read_evidence;

use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_agentd::NativeMemoryContextAuthorityV1;
use codex_hepta_agentd::NativeMemoryError;
use codex_hepta_agentd::NativeMemoryModelConfigV1;
use codex_hepta_agentd::NativeMemoryShadowFilesV1;
use codex_hepta_agentd::NativeMemoryShadowProfileV1;
use codex_hepta_agentd::NativeMemoryShadowStartV1;
use codex_hepta_agentd::NativeMemoryTickContextV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronShadowConfigV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::native_memory_support::retain;

pub const PROVIDER: &str = "controlled-qualification-context-v1";
const SUBJECT: &str = "subject:controlled-native-shadow-qualification";
const CELL: &str = "cell:controlled-native-shadow-qualification";
const HEAD: &[u8] = b"hepta.memory-cell.hidden-tanh-and-next-token-top-probabilities.v1";
const ENCODER: &[u8] = b"hepta.memory-cell.query-utf8-q16-padded512.v1";
const MAX_RECORDS: usize = 8;

#[derive(Clone)]
pub struct ControlledQualificationContext {
    root: PathBuf,
    clock: Arc<Instant>,
    checks: Arc<AtomicU64>,
    pub subject: StableId,
    pub objective: Digest32,
    pub ndu: Digest32,
}

impl ControlledQualificationContext {
    pub fn create(root: &Path) -> anyhow::Result<Self> {
        for (name, purpose) in [
            ("objective", "Observe one fixed pretrained decoder through the real shadow transaction"),
            ("ndu", "Controlled qualification state; no production NDU selection or authority"),
        ] {
            retain(&root.join(format!("{name}-context.json")), &serde_json::json!({
                "schema": "hepta.memory-cell.controlled-qualification-context.v1",
                "provider": PROVIDER, "kind": name, "purpose": purpose,
                "subject": SUBJECT, "production_authority": false,
                "source_hash_substituted_for_context": false,
            }))?;
        }
        let value = Self {
            root: root.to_path_buf(), clock: Arc::new(Instant::now()),
            checks: Arc::new(AtomicU64::new(0)), subject: StableId::new(SUBJECT)?,
            objective: Digest32::of_bytes(&std::fs::read(root.join("objective-context.json"))?),
            ndu: Digest32::of_bytes(&std::fs::read(root.join("ndu-context.json"))?),
        };
        retain(&root.join("context-provider.json"), &serde_json::json!({
            "provider": PROVIDER, "subject_id": value.subject.as_str(),
            "objective_digest": value.objective.to_string(), "ndu_snapshot_digest": value.ndu.to_string(),
            "body_generation": null, "modulator_digest": null,
            "clock": "one shared process Instant; cloned across both owner recoveries",
            "clock_epoch_scope": "same process only", "cross_process_clock_recovery": false,
            "production_authority": false, "calibration": null,
        }))?;
        Ok(value)
    }

    pub fn calls(&self) -> u64 { self.checks.load(Ordering::SeqCst) }
}

impl NativeMemoryContextAuthorityV1 for ControlledQualificationContext {
    fn current(&mut self) -> Result<NativeMemoryTickContextV1, NativeMemoryError> {
        self.checks.fetch_add(1, Ordering::SeqCst);
        for (name, expected) in [("objective", self.objective), ("ndu", self.ndu)] {
            let actual = Digest32::of_reader(
                File::open(self.root.join(format!("{name}-context.json"))).map_err(rejected)?,
                /*maximum_bytes*/ 4096,
            ).map_err(rejected)?;
            if actual != expected { return Err(rejected("controlled context bytes changed")); }
        }
        let elapsed = u64::try_from(self.clock.elapsed().as_micros()).map_err(rejected)?;
        Ok(NativeMemoryTickContextV1 {
            subject_id: self.subject.clone(), objective_digest: self.objective,
            ndu_snapshot_digest: self.ndu,
            monotonic_time_micros: elapsed.checked_add(1).ok_or_else(|| rejected("clock overflow"))?,
            body_generation: None, modulator_digest: None,
        })
    }
}

fn rejected(error: impl std::fmt::Display) -> NativeMemoryError {
    NativeMemoryError::Rejected(error.to_string())
}

pub fn profile(model: &NativeMemoryModelConfigV1) -> anyhow::Result<NativeMemoryShadowProfileV1> {
    anyhow::ensure!(model.output_width == 5, "separately registered width-five observation profile required");
    Ok(NativeMemoryShadowProfileV1 {
        cell_id: StableId::new(CELL)?,
        sparse: SparseConfig {
            model_digest: Digest32::of_bytes(HEAD),
            normalization_digest: Digest32::of_bytes(b"controlled-qualification:identity-q24-v1"),
            generation: Generation::new(model.generation)?, width: model.output_width, top_k: 1,
            temporal_decay_q24: 1 << 23, inhibition_gain_q24: 1 << 24, inhibition: vec![],
            activity_decay_q24: 0, target_activity_q24: 1 << 21, threshold_rate_q24: 1 << 21,
            threshold_min_q24: -(1 << 24), threshold_max_q24: 1 << 24, eligibility_decay_q24: 1 << 23,
        },
        limits: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 120_000_000, p99_latency_micros: 120_000_000,
            transient_allocation_bytes: 4_u64 << 30, checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
        max_records: MAX_RECORDS,
    })
}

pub fn descriptor(model: &NativeMemoryModelConfigV1) -> anyhow::Result<NeuronShadowConfigV1> {
    let registered = profile(model)?;
    Ok(NeuronShadowConfigV1 {
        config_id: StableId::new(model.config_id.clone())?, generation: Generation::new(model.generation)?,
        model_id: StableId::new(model.model_id.clone())?,
        model_manifest_digest: model.pins.manifest_sha256.parse()?,
        encoder_digest: Digest32::of_bytes(ENCODER), head_digest: Digest32::of_bytes(HEAD),
        weights_digest: model.pins.weights_digest.parse()?, tokenizer_digest: model.pins.tokenizer_digest.parse()?,
        preprocessor_digest: model.pins.preprocessor_digest.parse()?, quantization_digest: model.pins.quantization_digest.parse()?,
        runtime_digest: model.pins.runtime_digest.parse()?, device_digest: model.pins.device_digest.parse()?,
        normalization_digest: registered.sparse.normalization_digest,
        native_config_digest: registered.sparse.digest()?,
        input_feature_dimension: 512, state_width: model.output_width, modulator_dimension: 1,
        resource_envelope: registered.limits,
    })
}

pub fn files(root: &Path, start: NativeMemoryShadowStartV1) -> anyhow::Result<NativeMemoryShadowFilesV1> {
    let open = |name| -> std::io::Result<File> {
        let mut options = OpenOptions::new();
        options.read(true).write(true);
        if matches!(start, NativeMemoryShadowStartV1::Bootstrap) { options.create_new(true); }
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        options.open(root.join(name))
    };
    Ok(NativeMemoryShadowFilesV1 { journal: open("shadow-journal")?, witness: open("shadow-witness")?, start })
}
