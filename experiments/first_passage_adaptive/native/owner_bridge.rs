//! A research adapter using the original NeuronRuntime journal and witness.
//! FPT phase/task state is explicitly external; V1 sparse state is not relabelled.
#![forbid(unsafe_code)]
mod execution_state;
mod task_journal;
#[cfg(test)]
#[path = "owner_bridge_tests.rs"]
mod tests;

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::path::Component;
use std::path::Path;
use std::process::ExitCode;
use std::time::Instant;

use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use execution_state::Command;
use execution_state::EventWindow;
use execution_state::ExecutionState;
use execution_state::Terminal;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;

const Q: i64 = 1 << 24;
const LIMIT: usize = 256;
const PROFILE: &str = "hepta.fpt-adaptive.owner-research.v1";

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema: String,
    subject: String,
    sequence: u64,
    owner_monotonic_us: u64,
    checkpoint_digest: String,
    objective_digest: String,
    ndu_receipt_digest: String,
    fpt_checkpoint_digest: String,
    fpt_predecessor_digest: String,
    fpt_checkpoint_json: String,
    features_q24: [i64; 5],
    state: ExecutionState,
    window: EventWindow,
    deadline_us: u64,
    command: Command,
}

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

fn execute(store: &Path, data_root: &Path, request: Request) -> Result<Value, String> {
    if request.schema != PROFILE
        || request.sequence == 0
        || request.sequence > LIMIT as u64
        || request
            .features_q24
            .iter()
            .any(|value| !(-8 * Q..=8 * Q).contains(value))
    {
        return Err("unsupported profile, sequence or feature domain".into());
    }
    let mut next = request
        .state
        .advance(&request.window, request.deadline_us)?;
    next.admit(&request.command, request.deadline_us)?;
    let state_bytes = serde_json::to_vec(&next).map_err(|error| error.to_string())?;
    let state_digest = Digest32::of_bytes(&state_bytes);
    let fpt_model_digest = execution_state::validate_checkpoint(
        &request.fpt_checkpoint_json,
        digest(&request.fpt_checkpoint_digest)?,
        &next,
    )?;
    let request_value = serde_json::to_value(&request).map_err(|error| error.to_string())?;
    let request_bytes = serde_json::to_vec(&request_value).map_err(|error| error.to_string())?;
    let request_digest = Digest32::of_bytes(&request_bytes);
    let fpt_checkpoint_digest = digest(&request.fpt_checkpoint_digest)?;
    if let Some(mut replay) =
        task_journal::before(store, &request_value, &request_digest.to_string())?
    {
        let current = inspect(store, &request)?;
        if current["checkpoint_digest"] != replay["owner"]["checkpoint_after"] {
            return Err("historical replay requires a matching current native-owner anchor".into());
        }
        replay["replayed"] = json!(true);
        replay["source_reads_this_call"] = json!(0);
        replay["source_read_attempts_this_call"] = json!(0);
        return Ok(replay);
    }
    let subject = id(&request.subject)?;
    let objective = digest(&request.objective_digest)?;
    let mut scope_bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    scope_bytes.extend_from_slice(&(subject.as_str().len() as u32).to_be_bytes());
    scope_bytes.extend_from_slice(subject.as_str().as_bytes());
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(&scope_bytes),
        objective_digest: objective,
    };
    let (native, runtime_config) = config()?;
    std::fs::create_dir_all(store).map_err(|error| error.to_string())?;
    let open = |name: &str| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(store.join(name))
            .map_err(|error| error.to_string())
    };
    let witness =
        FileAnchorWitnessStore::open(open("witness.bin")?, scope, native.generation, LIMIT)
            .map_err(|error| error.to_string())?;
    let previous = witness.current().map_err(|error| error.to_string())?;
    let expected = digest(&request.checkpoint_digest)?;
    if previous.map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest) != expected {
        return Err("owner checkpoint predecessor mismatch".into());
    }
    let mut owner = if let Some(anchor) = previous {
        NeuronRuntime::recover(
            open("journal.bin")?,
            native,
            scope,
            LIMIT,
            runtime_config.clone(),
            anchor,
            witness,
        )
    } else {
        NeuronRuntime::bootstrap(
            open("journal.bin")?,
            native,
            scope,
            LIMIT,
            runtime_config.clone(),
            witness,
        )
    }
    .map_err(|error| error.to_string())?;
    let features = request.features_q24.to_vec();
    let input = NeuronTickInputV1 {
        tick_id: id(&format!("fpt.tick.{}", request.sequence))?,
        subject_id: subject,
        logical_sequence: request.sequence,
        monotonic_time_micros: request.owner_monotonic_us,
        checkpoint_digest: expected,
        input_feature_digest: canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features,
        objective_digest: objective,
        ndu_snapshot_digest: Digest32::of_parts(&[
            digest(&request.ndu_receipt_digest)?.as_array(),
            state_digest.as_array(),
            request_digest.as_array(),
            fpt_checkpoint_digest.as_array(),
        ]),
        body_generation: Some(1),
        modulator_digest: None,
    };
    let input_digest = input.semantic_digest().map_err(|error| error.to_string())?;
    let mut model = NumericalModel(runtime_config);
    let result = owner
        .tick(&mut model, input)
        .map_err(|error| error.to_string())?;
    let mut read = json!(null);
    let mut read_attempts = 0_u64;
    if matches!(request.command, Command::Read { .. })
        && next.terminal.is_none()
        && result.signal.abstain
    {
        next.read_units_spent = request.state.read_units_spent;
        next.terminal = Some(Terminal::Stopped);
    }
    if let Command::Read {
        relative_path,
        query,
    } = &request.command
        && next.terminal.is_none()
        && !result.signal.abstain
    {
        let outcome = (|| -> Result<Value, String> {
            if relative_path.is_empty()
                || Path::new(relative_path)
                    .components()
                    .any(|part| !matches!(part, Component::Normal(_)))
            {
                return Err("source path must be strictly relative".into());
            }
            let root = data_root
                .canonicalize()
                .map_err(|error| error.to_string())?;
            let path = root
                .join(relative_path)
                .canonicalize()
                .map_err(|error| error.to_string())?;
            if !path.starts_with(&root) {
                return Err("source escaped task scope".into());
            }
            let mut payload = Vec::new();
            read_attempts = 1;
            File::open(path)
                .map_err(|error| error.to_string())?
                .take(65_537)
                .read_to_end(&mut payload)
                .map_err(|error| error.to_string())?;
            if payload.len() > 65_536 {
                return Err("source exceeds bounded task read".into());
            }
            let text = std::str::from_utf8(&payload).map_err(|error| error.to_string())?;
            let answer = text.lines().find_map(|line| {
                line.split_once('=')
                    .filter(|(key, _)| *key == query)
                    .map(|(_, value)| value.to_owned())
            });
            Ok(
                json!({"source_digest":Digest32::of_bytes(&payload).to_string(), "bytes":payload.len(), "answer":answer}),
            )
        })();
        match outcome {
            Ok(value) => read = value,
            Err(error) => {
                if read_attempts == 0 {
                    next.read_units_spent = request.state.read_units_spent;
                }
                next.terminal = Some(Terminal::ReadFailed);
                read = json!({"error":error});
            }
        }
    }
    let response = json!({"schema":PROFILE,"status":"research-executed","state":next,
        "admitted_state_digest":state_digest.to_string(),"request_digest":request_digest.to_string(),
        "input_digest":input_digest.to_string(),"fpt_checkpoint_digest":request.fpt_checkpoint_digest,"read":read,
        "fpt_model_digest":fpt_model_digest,"source_read_attempts_this_call":read_attempts,
        "owner":{"algorithm":"codex_hepta_neuron::NeuronRuntime::tick",
            "recovered":previous.is_some(),"checkpoint_before":result.tick.checkpoint_before.to_string(),
            "checkpoint_after":result.tick.checkpoint_after.to_string(),
            "model_runtime_digest":result.signal.model_runtime_digest.to_string(),
            "temporal_state_digest":result.signal.temporal_state_digest.to_string(),
            "abstain":result.signal.abstain,"signals_q24":result.signal.signals_q24,
            "execution_micros":result.tick.resource_receipt.execution_micros,
            "journal_bytes_written":result.tick.resource_receipt.journal_bytes_written},
        "ndu_receipt_digest":request.ndu_receipt_digest,"source_commit":env!("HEPTA_FPT_OWNER_SOURCE_COMMIT"),
        "calibration_certified":false,"calibration_fields":"worst-case upper bounds; no empirical calibration claim",
        "fpt_state_owned_by":"research-task sidecar; not native V1 sparse checkpoint",
        "binding_scope":"native journal binds admission/request/FPT digests; task sidecar records post-I/O outcome",
        "event_source":"trusted research FirstPassageCell observations; Rust checks event/phase contract, not an independent stochastic-law proof",
        "replayed":false,"source_reads_this_call":u64::from(read.get("source_digest").is_some()),
        "clock_semantics":{"owner":"host monotonic microseconds","events":"task physical microseconds","sequence":"decision ordinal"},
        "production_activation":false,"authority":"DENY_ALL"});
    task_journal::after(store, request.sequence, &response)?;
    Ok(response)
}

fn inspect(store: &Path, request: &Request) -> Result<Value, String> {
    if !store.exists() {
        return Ok(
            json!({"schema":PROFILE,"sequence":0,"checkpoint_digest":Digest32::ZERO.to_string()}),
        );
    }
    let subject = id(&request.subject)?;
    let mut bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    bytes.extend_from_slice(&(subject.as_str().len() as u32).to_be_bytes());
    bytes.extend_from_slice(subject.as_str().as_bytes());
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(&bytes),
        objective_digest: digest(&request.objective_digest)?,
    };
    let (native, runtime) = config()?;
    let open = |name: &str| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(store.join(name))
            .map_err(|error| error.to_string())
    };
    let witness =
        FileAnchorWitnessStore::open(open("witness.bin")?, scope, native.generation, LIMIT)
            .map_err(|error| error.to_string())?;
    let anchor = witness
        .current()
        .map_err(|error| error.to_string())?
        .ok_or("unacknowledged owner state requires reconciliation")?;
    let owner = NeuronRuntime::recover(
        open("journal.bin")?,
        native,
        scope,
        LIMIT,
        runtime,
        anchor,
        witness,
    )
    .map_err(|error| error.to_string())?;
    let current = owner
        .current_anchor()
        .map_err(|error| error.to_string())?
        .ok_or("missing recovered anchor")?;
    Ok(
        json!({"schema":PROFILE,"sequence":current.sequence,"checkpoint_digest":current.checkpoint_digest.to_string(),"source_reads":0}),
    )
}

fn main() -> ExitCode {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let run = || -> Result<Value, String> {
        if !((args.len() == 4 || args.len() == 5)
            && args[0] == "--store"
            && args[2] == "--data-root"
            && (args.len() == 4 || args[4] == "--inspect"))
        {
            return Err("expected --store PATH --data-root PATH [--inspect]".into());
        }
        let mut input = Vec::new();
        std::io::stdin()
            .take(65_537)
            .read_to_end(&mut input)
            .map_err(|error| error.to_string())?;
        if input.len() > 65_536 {
            return Err("input exceeds 64 KiB".into());
        }
        let request: Request = serde_json::from_slice(&input).map_err(|error| error.to_string())?;
        if args.len() == 5 {
            inspect(Path::new(&args[1]), &request)
        } else {
            execute(Path::new(&args[1]), Path::new(&args[3]), request)
        }
    };
    match run() {
        Ok(value) => {
            println!("{value}");
            ExitCode::SUCCESS
        }
        Err(error) => {
            println!(
                "{}",
                json!({"schema":PROFILE,"status":"error","error":error,"authority":"DENY_ALL"})
            );
            ExitCode::FAILURE
        }
    }
}
