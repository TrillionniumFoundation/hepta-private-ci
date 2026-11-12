//! Local qualification of real PERC bytes, diagnostic native head arithmetic,
//! durable Cell ownership and original inference readback. No daemon enrollment.
//! Linux same-boot clock; separate local witness is not an independent trust domain.

#![recursion_limit = "256"]

use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_infer_core::neuron_feature_request_digest_v1;
use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeMap;
use std::error::Error;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const Q: i64 = 1 << 24;
const LIMIT: i64 = 8 * Q;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ScopeInput {
    agent_id: String,
    cell_id: String,
    run_id: String,
    principal_digest: [u8; 32],
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

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Head {
    schema: String,
    provenance: String,
    weights_q24: Vec<Vec<i64>>,
    bias_q24: Vec<i64>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    schema: String,
    boot_sha256: [u8; 32],
    monotonic_micros: u64,
    deadline_micros: u64,
    files: BTreeMap<String, [u8; 32]>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Observed {
    request_sha256: [u8; 32],
    drive_q24: Vec<i64>,
    prediction_q24: Vec<i64>,
    latency_micros: u64,
    memory_bytes: u64,
    transient_bytes: u64,
    receipt_sha256: [u8; 32],
}

enum Mode {
    Start,
    LoseAck,
    ReadOnly,
}

fn read(path: &Path, limit: usize) -> Result<Vec<u8>> {
    if !fs::symlink_metadata(path)?.file_type().is_file() {
        return Err("regular nonsymlink input required".into());
    }
    let mut bytes = Vec::new();
    File::open(path)?
        .take((limit + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.is_empty() || bytes.len() > limit {
        return Err("input byte bound exceeded".into());
    }
    Ok(bytes)
}

fn write(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    File::open(path.parent().ok_or("missing parent")?)?.sync_all()?;
    Ok(())
}

fn clock() -> Result<u64> {
    let uptime = fs::read_to_string("/proc/uptime")?;
    let (seconds, fraction) = uptime
        .split_whitespace()
        .next()
        .ok_or("uptime")?
        .split_once('.')
        .ok_or("uptime decimal")?;
    if fraction.len() != 2 {
        return Err("unsupported uptime precision".into());
    }
    seconds
        .parse::<u64>()?
        .checked_mul(1_000_000)
        .and_then(|v| {
            fraction
                .parse::<u64>()
                .ok()?
                .checked_mul(10_000)?
                .checked_add(v)
        })
        .ok_or_else(|| "uptime overflow".into())
}

fn id(value: &str) -> Result<StableId> {
    Ok(StableId::new(value)?)
}
fn pin(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn definition(
    expected: &Expected,
    model: Digest32,
    boot: Digest32,
    width: usize,
) -> Result<CellDefinitionV1> {
    let generation = Generation::new(1)?;
    let native = SparseConfig {
        model_digest: model,
        normalization_digest: pin("perc-diagnostic-normalizer-v1"),
        generation,
        width,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    };
    let runtime = NeuronRuntimeConfigV1 {
        config_id: id("perc-native-owner-qualification")?,
        generation,
        model_id: id("diagnostic-q24-linear-head")?,
        model_manifest_digest: model,
        encoder_digest: Digest32::from_array(expected.encoder_digest),
        head_digest: model,
        weights_digest: model,
        tokenizer_digest: pin("no-tokenizer-q24"),
        preprocessor_digest: native.normalization_digest,
        quantization_digest: pin("Q24-i128-dot-toward-zero-clamp8-v1"),
        runtime_digest: pin("perc-native-diagnostic-linear-v1"),
        device_digest: boot,
        normalization_digest: native.normalization_digest,
        native_config_digest: native.digest()?,
        input_feature_dimension: expected.feature_dimension,
        state_width: width,
        modulator_dimension: 1,
        // Qualification fixture only. These calibration fields are not empirical measurements.
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: pin("diagnostic-not-scientific-calibration"),
            ood_artifact_digest: pin("diagnostic-not-scientific-ood"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 32,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 500_000,
            maximum_ood_ppm: 500_000,
            minimum_active_ppm: 100_000,
            maximum_active_ppm: 500_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 1000,
            maximum_ece_ppm: 50_000,
            measured_false_acceptance_ppm: 1000,
            maximum_false_acceptance_ppm: 20_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 100_000,
            p99_latency_micros: 1_000_000,
            transient_allocation_bytes: 1_048_576,
            checkpoint_bytes: 65_536,
            write_amplification_ppm: 4_000_000,
        },
    };
    Ok(CellDefinitionV1 {
        cell_id: id(&expected.scope.cell_id)?,
        bundle_digest: model,
        state_schema_digest: pin("perc-native-owner-qualification-v1"),
        runtime,
        native,
        candidates: vec![
            CellCandidateV1 {
                candidate_id: id("observe")?,
                activation_index: 0,
                kind: CellCandidateKindV1::SlowPath,
            },
            CellCandidateV1 {
                candidate_id: id("abstain")?,
                activation_index: width - 1,
                kind: CellCandidateKindV1::Abstain,
            },
        ],
        max_input_bytes: 65_536,
        max_queue_age_micros: 1_000_000,
        max_resident_bytes: 1_048_576,
    })
}

struct Control {
    root: PathBuf,
    head: Head,
    runtime: NeuronModelRuntimeTupleV1,
    encoder_digest: Digest32,
    head_digest: Digest32,
    executions: usize,
    reads: usize,
    lose_ack: bool,
}

impl Control {
    fn receipt(
        &self,
        request: &NeuronFeatureRequestV1,
        value: &Observed,
    ) -> Result<NeuronFeatureReceiptV1> {
        if neuron_feature_request_digest_v1(request)?.into_array() != value.request_sha256 {
            return Err("original inference request mismatch".into());
        }
        Ok(build_neuron_feature_receipt_v1(
            request,
            self.runtime.clone(),
            NeuronFeatureObservationV1 {
                encoder_digest: self.encoder_digest,
                head_digest: self.head_digest,
                drive_q24: value.drive_q24.clone(),
                prediction_q24: value.prediction_q24.clone(),
                observed_memory_bytes: value.memory_bytes,
                transient_allocation_bytes: value.transient_bytes,
                queue_age_micros: 0,
                latency_micros: value.latency_micros,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        )?)
    }

    fn execute(&mut self, request: &NeuronFeatureRequestV1) -> Result<NeuronFeatureReceiptV1> {
        if request.encoder_digest != self.encoder_digest
            || request.head_digest != self.head_digest
            || request.weights_digest != self.runtime.weights_digest
            || request.expected_output_width * 2 != self.head.weights_q24.len()
            || request.feature_vector_q24.len() != self.head.weights_q24[0].len()
        {
            return Err("head input binding mismatch".into());
        }
        let request_sha256 = neuron_feature_request_digest_v1(request)?.into_array();
        write(&self.root.join("head-claim.bin"), &request_sha256)?;
        self.executions += 1;
        let started = Instant::now();
        let values: Vec<i64> = self
            .head
            .weights_q24
            .iter()
            .zip(&self.head.bias_q24)
            .map(|(row, bias)| {
                let dot: i128 = row
                    .iter()
                    .zip(&request.feature_vector_q24)
                    .map(|(w, x)| i128::from(*w) * i128::from(*x))
                    .sum();
                (dot / i128::from(Q) + i128::from(*bias))
                    .clamp(-i128::from(LIMIT), i128::from(LIMIT)) as i64
            })
            .collect();
        let drive_q24 = values[..request.expected_output_width].to_vec();
        let prediction_q24 = values[request.expected_output_width..].to_vec();
        let transient_bytes =
            (values.capacity() + drive_q24.capacity() + prediction_q24.capacity()) as u64 * 8;
        let latency_micros = u64::try_from(started.elapsed().as_micros())?;
        let mut value = Observed {
            request_sha256,
            drive_q24,
            prediction_q24,
            latency_micros,
            memory_bytes: (self
                .head
                .weights_q24
                .iter()
                .map(Vec::capacity)
                .sum::<usize>()
                + self.head.bias_q24.capacity()) as u64
                * 8,
            transient_bytes,
            receipt_sha256: [0; 32],
        };
        let receipt = self.receipt(request, &value)?;
        value.receipt_sha256 = receipt.receipt_digest.into_array();
        write(
            &self.root.join("head-receipt.json"),
            &serde_json::to_vec(&value)?,
        )?;
        Ok(receipt)
    }
}

impl NeuronInferenceControlPort for Control {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> std::result::Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let receipt = self
            .execute(request)
            .map_err(|_| NeuronModelError::Indeterminate)?;
        if self.lose_ack {
            Err(NeuronModelError::Indeterminate)
        } else {
            Ok(receipt)
        }
    }
}

impl CellInferenceReadbackPortV1 for Control {
    fn read_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> std::result::Result<Option<NeuronFeatureReceiptV1>, NeuronModelError> {
        self.reads += 1;
        let result = (|| -> Result<_> {
            let value: Observed =
                serde_json::from_slice(&read(&self.root.join("head-receipt.json"), 65_536)?)?;
            let receipt = self.receipt(request, &value)?;
            if receipt.receipt_digest.into_array() != value.receipt_sha256
                || read(&self.root.join("head-claim.bin"), 32)? != value.request_sha256
            {
                return Err("retained inference receipt mismatch".into());
            }
            Ok(receipt)
        })();
        result
            .map(Some)
            .map_err(|_| NeuronModelError::Indeterminate)
    }
}

fn initialize(root: &Path, paths: &[std::ffi::OsString]) -> Result<()> {
    fs::create_dir(root)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root, fs::Permissions::from_mode(0o700))?;
    }
    let mut files = BTreeMap::new();
    for ((name, limit), source) in [
        ("wire.json", 65_536),
        ("raster.rgb", 64 * 1024 * 1024),
        ("expected.json", 65_536),
        ("head.json", 1_048_576),
    ]
    .into_iter()
    .zip(paths)
    {
        let raw = read(Path::new(source), limit)?;
        files.insert(name.to_string(), Digest32::of_bytes(&raw).into_array());
        write(&root.join(name), &raw)?;
    }
    let monotonic_micros = clock()?;
    let manifest = Manifest {
        schema: "perc1.native-owner-qualification.v1".into(),
        boot_sha256: Digest32::of_bytes(&read(Path::new("/proc/sys/kernel/random/boot_id"), 128)?)
            .into_array(),
        monotonic_micros,
        deadline_micros: monotonic_micros
            .checked_add(60_000_000)
            .ok_or("deadline overflow")?,
        files,
    };
    write(&root.join("manifest.json"), &serde_json::to_vec(&manifest)?)?;
    write(&root.join("cell.journal"), &[])?;
    write(&root.join("witness.journal"), &[])
}

fn run(root: &Path, output: &Path, mode: Mode) -> Result<()> {
    let manifest: Manifest = serde_json::from_slice(&read(&root.join("manifest.json"), 8192)?)?;
    if manifest.schema != "perc1.native-owner-qualification.v1"
        || manifest.boot_sha256
            != Digest32::of_bytes(&read(Path::new("/proc/sys/kernel/random/boot_id"), 128)?)
                .into_array()
        || manifest.monotonic_micros == 0
        || manifest.deadline_micros <= manifest.monotonic_micros
    {
        return Err("same-boot manifest binding mismatch".into());
    }
    let limits = [
        ("wire.json", 65_536),
        ("raster.rgb", 64 * 1024 * 1024),
        ("expected.json", 65_536),
        ("head.json", 1_048_576),
    ];
    if manifest.files.len() != limits.len() {
        return Err("manifest inventory mismatch".into());
    }
    let mut retained = BTreeMap::new();
    for (name, limit) in limits {
        let bytes = read(&root.join(name), limit)?;
        if manifest.files.get(name) != Some(&Digest32::of_bytes(&bytes).into_array()) {
            return Err("retained source changed".into());
        }
        retained.insert(name, bytes);
    }
    let expected: Expected = serde_json::from_slice(&retained["expected.json"])?;
    let head: Head = serde_json::from_slice(&retained["head.json"])?;
    let width = head.weights_q24.len() / 2;
    if head.schema != "perc1.diagnostic-q24-linear-head.v1"
        || head.provenance != "hand_authored_diagnostic_no_training_claim"
        || !(2..=32).contains(&width)
        || head.weights_q24.len() != width * 2
        || !(1..=512).contains(&expected.feature_dimension)
        || head.bias_q24.len() != width * 2
        || head
            .weights_q24
            .iter()
            .any(|r| r.len() != expected.feature_dimension)
        || head
            .weights_q24
            .iter()
            .flatten()
            .chain(&head.bias_q24)
            .any(|v| !(-LIMIT..=LIMIT).contains(v))
    {
        return Err("invalid diagnostic head".into());
    }
    let scope = CellScopeV1 {
        agent_id: id(&expected.scope.agent_id)?,
        cell_id: id(&expected.scope.cell_id)?,
        run_id: id(&expected.scope.run_id)?,
        principal_digest: Digest32::from_array(expected.scope.principal_digest),
    };
    let definition = definition(
        &expected,
        Digest32::of_bytes(&retained["head.json"]),
        Digest32::from_array(manifest.boot_sha256),
        width,
    )?;
    let r = &definition.runtime;
    let mut control = Control {
        root: root.into(),
        head,
        runtime: NeuronModelRuntimeTupleV1 {
            model_id: r.model_id.clone(),
            model_manifest_digest: r.model_manifest_digest,
            weights_digest: r.weights_digest,
            tokenizer_digest: r.tokenizer_digest,
            preprocessor_digest: r.preprocessor_digest,
            quantization_digest: r.quantization_digest,
            runtime_digest: r.runtime_digest,
            device_digest: r.device_digest,
        },
        encoder_digest: r.encoder_digest,
        head_digest: r.head_digest,
        executions: 0,
        reads: 0,
        lose_ack: matches!(mode, Mode::LoseAck),
    };
    let frontier = Digest32::from_array(expected.source_frontier);
    let input = CellStepInputV1 {
        operation_id: id("perc-native-step-1")?,
        scope: scope.clone(),
        source_frontier: frontier,
        objective_digest: pin("local-perception-mechanism-qualification"),
        ndu_snapshot_digest: pin("no-learned-ctrl-claim"),
        monotonic_micros: manifest.monotonic_micros,
        deadline_micros: manifest.deadline_micros,
        observation: retained["wire.json"].clone(),
        candidates: definition
            .candidates
            .iter()
            .map(|c| CellCandidateMaskV1 {
                candidate_id: c.candidate_id.clone(),
                allowed: true,
            })
            .collect(),
    };
    let witness = FileAnchorWitnessStore::open(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(root.join("witness.journal"))?,
        JournalScope {
            scope_digest: scope.digest(),
            objective_digest: input.objective_digest,
        },
        definition.runtime.generation,
        /*max_records*/ 64,
    )?;
    let mut owner = CellOwnerJournalV1::open(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(root.join("cell.journal"))?,
        witness,
        vec![CellJournalPartitionV1 {
            scope: scope.clone(),
            definition: definition.clone(),
            source_frontier: frontier,
            writer_epoch: 1,
        }],
        /*max_records*/ 64,
    )?;
    let request_digest = canonical_cell_step_request_digest_v1(&definition, &input)?;
    let committed = match owner.lookup(&scope, &input.operation_id, request_digest) {
        Ok(value) => value,
        Err(CellExecutionError::InferencePending) => None,
        Err(error) => return Err(error.into()),
    };
    if matches!(mode, Mode::ReadOnly)
        && committed.is_none()
        && owner.pending_inference(&scope)?.is_none()
    {
        return Err("read-only request has no original admission; no work dispatched".into());
    }
    let (receipt, status, encodings) = if let Some(value) = committed {
        (Some(value), "REPLAYED", 0)
    } else {
        let sources = [PerceptionActorSourceV1::new(
            expected.source_pin,
            &retained["raster.rgb"],
        )?];
        let encoder = PerceptionCellEncoderV1::new(
            PerceptionEncoderBindingV1 {
                encoder_digest: r.encoder_digest,
                latent_model_digest: Digest32::from_array(expected.latent_model_digest),
                residual_predictor_digest: None,
                representation: expected.representation,
                feature_dimension: expected.feature_dimension,
            },
            &sources,
        )?;
        let inferred = if owner.pending_inference(&scope)?.is_some() {
            recover_cell_inference(&definition, &owner, &encoder, input, &mut control, clock()?)
        } else {
            let prepared = prepare_cell_step(&definition, &owner, &encoder, input, clock()?)?;
            infer_cell_with_clock(prepared, &mut owner, &mut control, || {
                clock().unwrap_or(u64::MAX)
            })
        };
        match inferred {
            Ok(value) => (
                Some(commit_cell_step(
                    &mut owner,
                    decide_cell(value, clock()?)?,
                    clock()?,
                )?),
                "COMMITTED",
                1,
            ),
            Err(CellExecutionError::Backend(NeuronModelError::Indeterminate)) => {
                (None, "PENDING_ORIGINAL_READBACK", 1)
            }
            Err(error) => return Err(error.into()),
        }
    };
    let snapshot = owner.snapshot(&scope)?;
    let value = serde_json::json!({
        "schema": "perc1.native-owner-observation.v1", "status": status,
        "scientific_status": "HOLD", "authority_granted": false, "daemon_admission_exercised": false,
        "native_cell_owner_exercised": true, "diagnostic_head_inference_executions": control.executions,
        "inference_readbacks": control.reads, "encoder_calls": encodings,
        "head_provenance": "hand_authored_diagnostic_no_training_claim", "trained_semantic_model_executed": false,
        "calibration": "hand-authored fixture; no empirical calibration or OOD qualification",
        "scope_digest": scope.digest().to_string(), "definition_digest": definition.semantic_digest()?.to_string(),
        "source_frontier": frontier.to_string(), "head_sha256": control.head_digest.to_string(),
        "wire_sha256": Digest32::of_bytes(&retained["wire.json"]).to_string(),
        "owner_revision": snapshot.revision, "pending": owner.pending_inference(&scope)?.is_some(),
        "decision": receipt.as_ref().map(|v| serde_json::json!({
            "operation_id": v.operation_id.to_string(), "operation_digest": v.operation_digest.to_string(),
            "request_digest": v.semantic_request_digest.to_string(), "scope_digest": v.scope.digest().to_string(),
            "bundle_digest": v.bundle_digest.to_string(), "source_frontier": v.source_frontier.to_string(),
            "checkpoint_before": v.checkpoint_before.to_string(), "checkpoint_after": v.checkpoint_after.to_string(),
            "model_output_digest": v.model_output_digest.to_string(), "selected_candidate": v.selected_candidate.to_string(),
            "policy": v.policy.iter().map(|p| serde_json::json!({"candidate_id":p.candidate_id.to_string(),"allowed":p.allowed,"probability_ppm":p.probability_ppm})).collect::<Vec<_>>(),
            "confidence_ppm": v.confidence_ppm, "ood_ppm": v.ood_ppm, "authority_granted": v.authority.grants_any(),
            "consumed_input_bytes": v.cost.consumed_input_bytes, "truncated_input_bytes": v.cost.truncated_input_bytes,
            "deadline_exceeded": v.deadline_exceeded, "model_latency_micros": v.cost.model_latency_micros,
            "queue_age_micros": v.cost.queue_age_micros, "resident_bytes": v.cost.resident_bytes,
            "transient_allocation_bytes": v.cost.transient_allocation_bytes, "checkpoint_bytes": v.cost.checkpoint_bytes,
        })),
        "clock": "Linux /proc/uptime centisecond resolution, same boot only",
        "cost_scope": "head Instant wall and owned vector capacities; no CPU, RSS, energy or billing claim",
    });
    write(output, &serde_json::to_vec_pretty(&value)?)
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    match args.first().and_then(|v| v.to_str()) {
        Some(mode @ ("start" | "lose-ack")) if args.len() == 7 => {
            initialize(Path::new(&args[1]), &args[2..6])?;
            run(
                Path::new(&args[1]),
                Path::new(&args[6]),
                if mode == "lose-ack" {
                    Mode::LoseAck
                } else {
                    Mode::Start
                },
            )
        }
        Some("read") if args.len() == 3 => {
            run(Path::new(&args[1]), Path::new(&args[2]), Mode::ReadOnly)
        }
        _ => Err(
            "usage: start|lose-ack ROOT WIRE RASTER EXPECTED HEAD OUTPUT | read ROOT OUTPUT".into(),
        ),
    }
}
