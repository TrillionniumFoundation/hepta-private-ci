//! Bounded research RR feature broker. Official runtime/journal/witness remain unchanged.
//! The 8 exported features are not the 81 task actions; all publication authority is denied.
use codex_hepta_infer_core::{
    NeuronFeatureObservationV1, NeuronFeatureReceiptV1, NeuronFeatureRequestV1,
    NeuronFeatureTerminalStatusV1, NeuronModelRuntimeTupleV1, build_neuron_feature_receipt_v1,
    neuron_feature_request_digest_v1,
};
use codex_hepta_neuron::{
    AnchorWitnessStore, FileAnchorWitnessStore, InferenceControlModelPort, JournalAnchor,
    JournalScope, NeuronCalibrationProfileV1, NeuronInferenceControlPort, NeuronModelError,
    NeuronResourceEnvelopeV1, NeuronRuntime, NeuronRuntimeConfigV1, NeuronTickInputV1,
    SparseCheckpoint, SparseConfig, SparseTick, WitnessStoreError,
    canonical_feature_vector_digest_v1, sparse_tick,
};
use codex_hepta_types::{Digest32, Generation, StableId};
use serde_json::{Value, json};
use std::error::Error;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

type Outcome<T> = Result<T, Box<dyn Error>>;
const Q: i64 = 1 << 24;
const WIDTH: usize = 8;
const INPUTS: usize = 22;
const CAP: usize = 256;
const MAX_JSON: u64 = 1 << 20;
const SUBJECT: &str = "research.rr-feature.owner.0";

fn text<'a>(value: &'a Value, field: &str) -> Outcome<&'a str> {
    value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("missing text {field}").into())
}
fn number(value: &Value, field: &str) -> Outcome<u64> {
    value
        .get(field)
        .and_then(Value::as_u64)
        .ok_or_else(|| format!("missing unsigned {field}").into())
}
fn boolean(value: &Value, field: &str) -> Outcome<bool> {
    value
        .get(field)
        .and_then(Value::as_bool)
        .ok_or_else(|| format!("missing boolean {field}").into())
}
fn digest(value: &Value, field: &str) -> Outcome<Digest32> {
    let result: Digest32 = text(value, field)?.parse()?;
    if result.is_zero() {
        return Err(format!("zero manifest digest {field}").into());
    }
    Ok(result)
}
fn vector(value: &Value, field: &str, width: usize) -> Outcome<Vec<i64>> {
    let entries = value
        .get(field)
        .and_then(Value::as_array)
        .ok_or("missing Q24 vector")?;
    if entries.len() != width {
        return Err("incorrect Q24 width".into());
    }
    entries
        .iter()
        .map(|item| {
            let signed = item.as_i64().ok_or("Q24 value is not an integer")?;
            if !(-8 * Q..=8 * Q).contains(&signed) {
                return Err("Q24 value exceeds native bound".into());
            }
            Ok(signed)
        })
        .collect()
}
fn read_document(path: &Path) -> Outcome<(Value, Digest32)> {
    let mut bytes = Vec::new();
    File::open(path)?
        .take(MAX_JSON + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_JSON {
        return Err("JSON document exceeds bound".into());
    }
    Ok((serde_json::from_slice(&bytes)?, Digest32::of_bytes(&bytes)))
}
fn id(value: impl Into<String>) -> StableId {
    StableId::new(value.into()).expect("bounded fixed identity")
}
fn generation() -> Generation {
    Generation::new(1).expect("positive fixed generation")
}
fn hash(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn emit(value: &Value) -> io::Result<()> {
    let mut out = io::stdout().lock();
    serde_json::to_writer(&mut out, value)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    out.write_all(b"\n")?;
    out.flush()
}
fn wait_go() -> io::Result<()> {
    let mut line = String::new();
    if io::stdin().read_line(&mut line)? == 0 || line.trim() != "go" {
        return Err(io::Error::new(
            io::ErrorKind::UnexpectedEof,
            "supervisor must send literal go",
        ));
    }
    Ok(())
}
fn scope() -> JournalScope {
    let raw = SUBJECT.as_bytes();
    let mut bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
    JournalScope {
        scope_digest: Digest32::of_bytes(&bytes),
        objective_digest: hash(
            "research RR feature bridge; no effect authority; no production Cell qualification",
        ),
    }
}
fn native(manifest: &Value) -> Outcome<SparseConfig> {
    Ok(SparseConfig {
        model_digest: digest(manifest, "head_digest")?,
        normalization_digest: digest(manifest, "normalization_digest")?,
        generation: generation(),
        width: WIDTH,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: 0,
        inhibition: vec![],
        activity_decay_q24: Q / 2,
        target_activity_q24: Q / 4,
        threshold_rate_q24: Q / 16,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    })
}
fn runtime_tuple(manifest: &Value) -> Outcome<NeuronModelRuntimeTupleV1> {
    Ok(NeuronModelRuntimeTupleV1 {
        model_id: StableId::new(text(manifest, "model_id")?)?,
        model_manifest_digest: digest(manifest, "model_manifest_digest")?,
        weights_digest: digest(manifest, "weights_digest")?,
        tokenizer_digest: digest(manifest, "tokenizer_digest")?,
        preprocessor_digest: digest(manifest, "preprocessor_digest")?,
        quantization_digest: digest(manifest, "quantization_digest")?,
        runtime_digest: digest(manifest, "runtime_digest")?,
        device_digest: digest(manifest, "device_digest")?,
    })
}
fn config(manifest: &Value) -> Outcome<NeuronRuntimeConfigV1> {
    let n = native(manifest)?;
    let t = runtime_tuple(manifest)?;
    Ok(NeuronRuntimeConfigV1 {
        config_id: id("research.rr-feature.config.v1"),
        generation: generation(),
        model_id: t.model_id,
        model_manifest_digest: t.model_manifest_digest,
        encoder_digest: digest(manifest, "encoder_digest")?,
        head_digest: n.model_digest,
        weights_digest: t.weights_digest,
        tokenizer_digest: t.tokenizer_digest,
        preprocessor_digest: t.preprocessor_digest,
        quantization_digest: t.quantization_digest,
        runtime_digest: t.runtime_digest,
        device_digest: t.device_digest,
        normalization_digest: n.normalization_digest,
        native_config_digest: n.digest()?,
        input_feature_dimension: INPUTS,
        state_width: WIDTH,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: hash(
                "uncertified research RR bridge calibration fixture; no quality evidence",
            ),
            ood_artifact_digest: hash("uncertified research RR bridge OOD fixture"),
            generation: generation(),
            valid_from_sequence: 1,
            expires_after_sequence: CAP as u64,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 1_000_000,
            maximum_ood_ppm: 0,
            // top_k=1 and width=8 can never reach 100% active: always abstain.
            minimum_active_ppm: 1_000_000,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 0,
            maximum_ece_ppm: 0,
            measured_false_acceptance_ppm: 0,
            maximum_false_acceptance_ppm: 0,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 1_000_000,
            p99_latency_micros: 10_000_000,
            transient_allocation_bytes: 1 << 30,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    })
}
fn admission(path: &Path) -> Outcome<(NeuronTickInputV1, Digest32)> {
    let (value, admission_sha) = read_document(path)?;
    let sequence = number(&value, "sequence")?;
    if sequence > CAP as u64 {
        return Err("admission exceeds bounded history".into());
    }
    number(&value, "dt_micros")?;
    boolean(&value, "event_mask")?;
    let features = vector(&value, "features_q24", INPUTS)?;
    let input = NeuronTickInputV1 {
        tick_id: id(format!("research.rr-feature.tick.{sequence}")),
        subject_id: id(SUBJECT),
        logical_sequence: sequence,
        monotonic_time_micros: number(&value, "time_micros")?,
        checkpoint_digest: text(&value, "previous_native_checkpoint")?.parse()?,
        input_feature_digest: canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features,
        objective_digest: scope().objective_digest,
        ndu_snapshot_digest: admission_sha,
        body_generation: Some(1),
        modulator_digest: None,
    };
    input.semantic_digest()?;
    Ok((input, admission_sha))
}
fn feature_request(manifest: &Value, input: &NeuronTickInputV1) -> Outcome<NeuronFeatureRequestV1> {
    let c = config(manifest)?;
    Ok(NeuronFeatureRequestV1 {
        request_id: input.tick_id.clone(),
        generation: c.generation,
        model_id: c.model_id,
        encoder_digest: c.encoder_digest,
        head_digest: c.head_digest,
        weights_digest: c.weights_digest,
        input_digest: input.semantic_digest()?,
        feature_vector_q24: input.feature_vector_q24.clone(),
        expected_output_width: WIDTH,
    })
}
fn descriptor(request: &NeuronFeatureRequestV1, admission_sha: Digest32) -> Outcome<Value> {
    Ok(
        json!({"request": {"request_id":request.request_id.as_str(), "generation":request.generation.get(),
        "model_id":request.model_id.as_str(), "encoder_digest":request.encoder_digest.to_string(),
        "head_digest":request.head_digest.to_string(), "weights_digest":request.weights_digest.to_string(),
        "input_digest":request.input_digest.to_string(), "feature_vector_q24":request.feature_vector_q24,
        "expected_output_width":request.expected_output_width},
        "request_digest":neuron_feature_request_digest_v1(request)?.to_string(),
        "admission_sha256":admission_sha.to_string()}),
    )
}
fn body_digest(manifest: &Value) -> Outcome<Digest32> {
    // Exact private runtime_types::body_digest encoding, with body_generation=1.
    let mut bytes = b"hepta.neuron.body-binding.v1".to_vec();
    bytes.extend_from_slice(digest(manifest, "head_digest")?.as_array());
    bytes.extend_from_slice(&generation().get().to_be_bytes());
    bytes.extend_from_slice(&1_u64.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}
fn predict(manifest: &Value, history_path: &Path) -> Outcome<Value> {
    let (history, _) = read_document(history_path)?;
    let entries = history.as_array().ok_or("history must be an array")?;
    if entries.len() > CAP {
        return Err("history exceeds bounded capacity".into());
    }
    let mut previous: Option<SparseCheckpoint> = None;
    let mut anchors = Vec::new();
    let mut inputs = Vec::new();
    for entry in entries {
        let (input, _) = admission(Path::new(text(entry, "admission_path")?))?;
        if input.checkpoint_digest
            != previous
                .as_ref()
                .map_or(Digest32::ZERO, SparseCheckpoint::digest)
        {
            return Err("admission predecessor differs from pure replay prefix".into());
        }
        let input_digest = input.semantic_digest()?;
        let tick = SparseTick {
            scope_digest: scope().scope_digest,
            objective_digest: input.objective_digest,
            ndu_digest: input.ndu_snapshot_digest,
            body_digest: body_digest(manifest)?,
            input_digest,
            sequence: input.logical_sequence,
            monotonic_micros: input.monotonic_time_micros,
            drive_q24: vector(entry, "drive_q24", WIDTH)?,
            prediction_q24: vector(entry, "prediction_q24", WIDTH)?,
        };
        let (next, _) = sparse_tick(&native(manifest)?, &tick, previous.as_ref())?;
        anchors.push(next.digest().to_string());
        inputs.push(input_digest.to_string());
        previous = Some(next);
    }
    Ok(json!({"anchors":anchors, "input_digests":inputs}))
}

struct Backend {
    python: PathBuf,
    script: PathBuf,
    root: PathBuf,
    manifest_path: PathBuf,
    admission_path: PathBuf,
    manifest_sha: Digest32,
    admission_sha: Digest32,
    tuple: NeuronModelRuntimeTupleV1,
    expected: NeuronFeatureRequestV1,
    backend_executed: bool,
}
impl Backend {
    fn prepare(&mut self, request: &NeuronFeatureRequestV1) -> Outcome<NeuronFeatureReceiptV1> {
        if request != &self.expected
            || read_document(&self.manifest_path)?.1 != self.manifest_sha
            || read_document(&self.admission_path)?.1 != self.admission_sha
        {
            return Err("request or immutable input file changed".into());
        }
        let mut child = Command::new(&self.python)
            .arg(&self.script)
            .arg("prepare")
            .arg("--root")
            .arg(&self.root)
            .arg("--manifest")
            .arg(&self.manifest_path)
            .arg("--admission")
            .arg(&self.admission_path)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()?;
        let mut pipe = child.stdin.take().ok_or("backend stdin missing")?;
        serde_json::to_writer(&mut pipe, &descriptor(request, self.admission_sha)?)?;
        pipe.write_all(b"\n")?;
        drop(pipe);
        let mut bytes = Vec::new();
        child
            .stdout
            .take()
            .ok_or("backend stdout missing")?
            .take(MAX_JSON + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() as u64 > MAX_JSON {
            let _ = child.kill();
            let _ = child.wait();
            return Err("backend response exceeds bound".into());
        }
        if !child.wait()?.success() {
            return Err("Python backend prepare failed".into());
        }
        let response: Value = serde_json::from_slice(&bytes)?;
        if digest(&response, "request_digest")? != neuron_feature_request_digest_v1(request)? {
            return Err("backend request digest mismatch".into());
        }
        digest(&response, "prepared_sha256")?;
        self.backend_executed = boolean(&response, "backend_executed")?;
        let resident = number(&response, "resident_bytes")?;
        let transient = number(&response, "transient_upper_bound_bytes")?;
        if resident == 0 || transient < resident {
            return Err("invalid process memory observations".into());
        }
        let receipt = build_neuron_feature_receipt_v1(
            request,
            self.tuple.clone(),
            NeuronFeatureObservationV1 {
                encoder_digest: request.encoder_digest,
                head_digest: request.head_digest,
                drive_q24: vector(&response, "drive_q24", WIDTH)?,
                prediction_q24: vector(&response, "prediction_q24", WIDTH)?,
                observed_memory_bytes: resident,
                transient_allocation_bytes: transient,
                queue_age_micros: 0,
                latency_micros: number(&response, "latency_micros")?,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        )?;
        emit(&json!({"stage":"prepared", "backend":response,
            "runtime_tuple_digest":receipt.runtime_tuple_digest.to_string(), "feature_receipt_digest":receipt.receipt_digest.to_string(),
            "memory_scope":"Python process RSS and whole-process VmHWM upper bound; not isolated transient allocation"}))?;
        wait_go()?;
        Ok(receipt)
    }
}
impl NeuronInferenceControlPort for Backend {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        self.prepare(request).map_err(|error| {
            eprintln!("backend rejected: {error}");
            NeuronModelError::Rejected
        })
    }
}
struct PausingWitness {
    inner: FileAnchorWitnessStore,
    phase: String,
    sequence: u64,
}
impl PausingWitness {
    fn barrier(&self, phase: &str, next: JournalAnchor) -> Result<(), WitnessStoreError> {
        if self.phase == phase && self.sequence == next.sequence {
            emit(&json!({"stage":phase, "sequence":next.sequence,
                "checkpoint":next.checkpoint_digest.to_string(),
                "next_anchor":{"sequence":next.sequence,"checkpoint":next.checkpoint_digest.to_string()}}))?;
            wait_go()?;
        }
        Ok(())
    }
}
impl AnchorWitnessStore for PausingWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.barrier("before_witness", next)?;
        self.inner.compare_and_swap(expected, next)?;
        self.barrier("after_witness", next)
    }
}
fn open_owner(
    root: &Path,
    manifest: &Value,
    phase: &str,
    sequence: u64,
    allow_bootstrap: bool,
) -> Outcome<NeuronRuntime<PausingWitness>> {
    let journal = root.join("journal.bin");
    let witness = root.join("witness.bin");
    let fresh = !journal.exists() && !witness.exists();
    if fresh && !allow_bootstrap {
        return Err("recovery requires an existing published witness".into());
    }
    if journal.exists() != witness.exists() {
        return Err("partial native store; no bootstrap fallback".into());
    }
    if fresh {
        fs::create_dir_all(root)?;
    }
    let open = |path: &Path| -> io::Result<File> {
        let mut options = OpenOptions::new();
        options.read(true).write(true);
        if fresh {
            options.create_new(true);
        }
        options.open(path)
    };
    if !fresh && fs::metadata(&witness)?.len() <= 112 {
        return Err("no durable witness anchor; no bootstrap-gap repair".into());
    }
    let inner = FileAnchorWitnessStore::open(open(&witness)?, scope(), generation(), CAP)?;
    let anchor = inner.current()?;
    let pausing = PausingWitness {
        inner,
        phase: phase.into(),
        sequence,
    };
    if fresh {
        Ok(NeuronRuntime::bootstrap(
            open(&journal)?,
            native(manifest)?,
            scope(),
            CAP,
            config(manifest)?,
            pausing,
        )?)
    } else {
        Ok(NeuronRuntime::recover(
            open(&journal)?,
            native(manifest)?,
            scope(),
            CAP,
            config(manifest)?,
            anchor.ok_or("missing witness; no fallback")?,
            pausing,
        )?)
    }
}
fn tick(args: &[String]) -> Outcome<()> {
    let (manifest, manifest_sha) = read_document(Path::new(&args[3]))?;
    let (input, admission_sha) = admission(Path::new(&args[4]))?;
    let phase = args[8].as_str();
    if !["none", "before_witness", "after_witness"].contains(&phase) {
        return Err("invalid fault phase".into());
    }
    let request = feature_request(&manifest, &input)?;
    let request_digest = neuron_feature_request_digest_v1(&request)?;
    let input_digest = input.semantic_digest()?;
    let sequence = input.logical_sequence;
    let mut owner = open_owner(Path::new(&args[2]), &manifest, phase, sequence, true)?;
    let mut backend = Backend {
        python: args[5].clone().into(),
        script: args[6].clone().into(),
        root: args[7].clone().into(),
        manifest_path: args[3].clone().into(),
        admission_path: args[4].clone().into(),
        manifest_sha,
        admission_sha,
        tuple: runtime_tuple(&manifest)?,
        expected: request,
        backend_executed: false,
    };
    let output = owner.tick(&mut InferenceControlModelPort::new(&mut backend), input)?;
    let anchor = owner
        .current_anchor()?
        .ok_or("successful tick omitted anchor")?;
    if anchor.checkpoint_digest != output.tick.checkpoint_after
        || output.signal.authority.grants_any()
        || !output.tick.abstain
    {
        return Err("invalid committed identity or unexpected non-abstention/authority".into());
    }
    emit(
        &json!({"stage":"committed", "sequence":sequence, "checkpoint":anchor.checkpoint_digest.to_string(),
        "input_digest":input_digest.to_string(), "request_digest":request_digest.to_string(),
        "abstain":output.tick.abstain, "authority":false, "backend_executed":backend.backend_executed,
        "native_execution_micros_including_barriers":output.tick.resource_receipt.execution_micros,
        "journal_bytes_written":output.tick.resource_receipt.journal_bytes_written}),
    )?;
    wait_go()?;
    Ok(())
}
fn run() -> Outcome<()> {
    let args = std::env::args().collect::<Vec<_>>();
    match args.get(1).map(String::as_str) {
        Some("describe") if args.len() == 4 => {
            let (manifest, _) = read_document(Path::new(&args[2]))?;
            let (input, sha) = admission(Path::new(&args[3]))?;
            emit(&descriptor(&feature_request(&manifest, &input)?, sha)?)?;
        }
        Some("predict") if args.len() == 4 => {
            let (manifest, _) = read_document(Path::new(&args[2]))?;
            emit(&predict(&manifest, Path::new(&args[3]))?)?;
        }
        Some("tick") if args.len() == 9 => tick(&args)?,
        Some("recover") if args.len() == 4 => {
            let (manifest, _) = read_document(Path::new(&args[3]))?;
            let owner = open_owner(Path::new(&args[2]), &manifest, "none", 0, false)?;
            let anchor = owner.current_anchor()?.ok_or("recovery omitted anchor")?;
            emit(&json!({"stage":"recovered", "sequence":anchor.sequence,
                "checkpoint":anchor.checkpoint_digest.to_string(), "model_calls":0, "authority":false}))?;
        }
        _ => return Err("usage: describe MANIFEST ADMISSION | predict MANIFEST HISTORY_JSON | tick STORES MANIFEST ADMISSION PYTHON BACKEND HOST_ROOT FAULT_PHASE | recover STORES MANIFEST".into()),
    }
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("RR research bridge: {error}");
        std::process::exit(1);
    }
}
