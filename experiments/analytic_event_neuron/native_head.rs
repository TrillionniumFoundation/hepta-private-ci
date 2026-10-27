//! An actual NeuronModelPort over a Gaussian terminal-event head.
//! The Linux libm ABI is part of this experiment's platform qualification.
use std::error::Error;
use std::fs::{self, File, OpenOptions};
use std::path::Path;
use std::time::Instant;

use codex_hepta_neuron::{
    AnchorWitnessStore, FileAnchorWitnessStore, JournalScope, LocalModelRuntimeReceiptV1,
    NeuronCalibrationProfileV1, NeuronModelError, NeuronModelOutputV1, NeuronModelPort,
    NeuronModelRequestV1, NeuronResourceEnvelopeV1, NeuronRuntime, NeuronRuntimeConfigV1,
    NeuronTickInputV1, canonical_feature_vector_digest_v1, canonical_model_output_digest_v1,
};
use codex_hepta_types::{Digest32, StableId};
use serde_json::{Value, json};

use super::{Q, config};

#[link(name = "m")]
unsafe extern "C" {
    fn erfc(value: f64) -> f64;
}

fn tail(value: f64) -> f64 {
    // erfc has no pointers or mutable memory; libm is pinned by platform receipt.
    0.5 * unsafe { erfc(value / std::f64::consts::SQRT_2) }
}

fn probabilities(parameters: &[f64]) -> [f64; 3] {
    let (mean, variance, lower, upper) =
        (parameters[0], parameters[1], parameters[2], parameters[3]);
    if variance == 0. {
        return if mean <= lower {
            [1., 0., 0.]
        } else if mean <= upper {
            [0., 1., 0.]
        } else {
            [0., 0., 1.]
        };
    }
    let std = variance.sqrt();
    let lo = (lower - mean) / std;
    let hi = (upper - mean) / std;
    let put = tail(-lo);
    let call = tail(hi);
    let neutral = if lo >= 0. {
        tail(lo) - tail(hi)
    } else if hi <= 0. {
        tail(-hi) - tail(-lo)
    } else {
        1. - put - call
    };
    [put, neutral.max(0.), call]
}

fn quantize(p: [f64; 3]) -> [i64; 3] {
    let raw = p.map(|x| x * Q as f64);
    let mut q = raw.map(|x| x.floor() as i64);
    let remainder = Q - q.iter().sum::<i64>();
    let mut order = [0, 1, 2];
    order.sort_by(|&a, &b| {
        (raw[b] - q[b] as f64)
            .total_cmp(&(raw[a] - q[a] as f64))
            .then(a.cmp(&b))
    });
    for index in order.into_iter().take(remainder.max(0) as usize) {
        q[index] += 1;
    }
    q
}

fn resident_bytes() -> Result<u64, NeuronModelError> {
    let status =
        fs::read_to_string("/proc/self/status").map_err(|_| NeuronModelError::Unavailable)?;
    status
        .lines()
        .find_map(|line| {
            line.strip_prefix("VmRSS:")
                .and_then(|s| s.split_whitespace().next())
                .and_then(|s| s.parse::<u64>().ok())
                .map(|kb| kb * 1024)
        })
        .ok_or(NeuronModelError::Unavailable)
}

struct AnalyticHead {
    config: NeuronRuntimeConfigV1,
    latest: Option<Value>,
}

impl NeuronModelPort for AnalyticHead {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        let started = Instant::now();
        let c = &self.config;
        if request.config_id != c.config_id
            || request.generation != c.generation
            || request.model_id != c.model_id
            || request.encoder_digest != c.encoder_digest
            || request.head_digest != c.head_digest
            || request.weights_digest != c.weights_digest
            || request.expected_output_width != c.state_width
            || request.feature_vector_q24.len() != 4
        {
            return Err(NeuronModelError::Rejected);
        }
        let parameters: Vec<f64> = request
            .feature_vector_q24
            .iter()
            .map(|&x| x as f64 / Q as f64)
            .collect();
        if parameters[1] < 0. || parameters[2] >= parameters[3] {
            return Err(NeuronModelError::Rejected);
        }
        let p = probabilities(&parameters);
        let q = quantize(p);
        if q.iter().sum::<i64>() != Q || q.iter().any(|&x| x < 0 || x > Q) {
            return Err(NeuronModelError::Indeterminate);
        }
        let mut drive_q24 = vec![0; c.state_width];
        drive_q24[..3].copy_from_slice(&q);
        let prediction_q24 = vec![0; c.state_width];
        let rss = resident_bytes()?;
        let receipt = LocalModelRuntimeReceiptV1 {
            model_id: c.model_id.clone(),
            model_manifest_digest: c.model_manifest_digest,
            weights_digest: c.weights_digest,
            tokenizer_digest: c.tokenizer_digest,
            preprocessor_digest: c.preprocessor_digest,
            quantization_id: StableId::new("aen.q24.mass.v1")
                .map_err(|_| NeuronModelError::Rejected)?,
            quantization_digest: c.quantization_digest,
            backend_id: StableId::new("linux.libm.erfc.v1")
                .map_err(|_| NeuronModelError::Rejected)?,
            runtime_digest: c.runtime_digest,
            device_identity_digest: c.device_digest,
            latency_micros: started.elapsed().as_micros() as u64,
            resident_bytes: rss,
        };
        let output_digest = canonical_model_output_digest_v1(&drive_q24, &prediction_q24, &receipt)
            .map_err(|_| NeuronModelError::Indeterminate)?;
        self.latest = Some(
            json!({"parameters_q24_decoded": parameters, "probabilities": p,
            "probabilities_q24": q, "model_output_digest": output_digest.to_string(),
            "model_input_digest": request.input_digest.to_string(),
            "allocated_output_vector_bytes": (drive_q24.capacity() + prediction_q24.capacity()) * 8,
            "allocation_measurement_scope": "output vectors only; RSS is entire process"}),
        );
        Ok(NeuronModelOutputV1 {
            encoder_digest: c.encoder_digest,
            head_digest: c.head_digest,
            output_digest,
            drive_q24,
            prediction_q24,
            queue_age_micros: 0,
            // Exact output capacity, not an invented whole-process peak measurement.
            transient_allocation_bytes: (2 * c.state_width * 8) as u64,
            runtime_receipt: receipt,
        })
    }
}

fn runtime_config(
    native: &codex_hepta_neuron::SparseConfig,
) -> Result<NeuronRuntimeConfigV1, Box<dyn Error>> {
    let d = |value: &str| Digest32::of_bytes(value.as_bytes());
    Ok(NeuronRuntimeConfigV1 {
        config_id: StableId::new("analytic.research.owner.v1")?,
        generation: native.generation,
        model_id: StableId::new("gaussian.terminal.event.v1")?,
        model_manifest_digest: d(
            "mean,variance,lower,upper -> put,neutral,call; physical conditional law; no discount",
        ),
        encoder_digest: d("signedQ24.parameters.order.mean.variance.lower.upper.v1"),
        head_digest: native.model_digest,
        weights_digest: d("fixed analytic libm constants; no learned weights in this adapter"),
        tokenizer_digest: d("numeric input; tokenizer not applicable"),
        preprocessor_digest: d("strict finite bounded parameters; ties-even Q24 input"),
        quantization_digest: d("Q24 simplex largest remainder canonical index ties v1"),
        runtime_digest: d(concat!(
            env!("AEN_NATIVE_SOURCE_SHA256"),
            env!("AEN_COMPILER_SHA256")
        )),
        device_digest: d(&format!(
            "{}:{}:{}",
            std::env::consts::OS,
            std::env::consts::ARCH,
            fs::read_to_string("/proc/sys/kernel/osrelease")?.trim()
        )),
        normalization_digest: native.normalization_digest,
        native_config_digest: native.digest()?,
        input_feature_dimension: 4,
        state_width: native.width,
        modulator_dimension: 1,
        // The profile is deliberately outside the bounded 1..1024 owner lifetime.
        // Legacy required measured_* slots carry conservative unknown bounds.
        // No empirical calibration claim is made and every output must abstain.
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: d(
                "UNQUALIFIED.expired-profile.v1; unknown ECE upper bound 1000000",
            ),
            ood_artifact_digest: d("UNQUALIFIED.no-OOD-validation.v1"),
            generation: native.generation,
            valid_from_sequence: 1025,
            expires_after_sequence: 1025,
            zero_confidence_error_q24: 1,
            maximum_in_domain_error_q24: 1,
            minimum_confidence_ppm: 1_000_000,
            maximum_ood_ppm: 0,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 0,
            measured_ece_ppm: 1_000_000,
            maximum_ece_ppm: 1_000_000,
            measured_false_acceptance_ppm: 1_000_000,
            maximum_false_acceptance_ppm: 1_000_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 1_000_000,
            p99_latency_micros: 10_000_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    })
}

pub fn run(
    case: &str,
    directory: &str,
    parameters: [f64; 4],
    expected_checkpoint: Option<String>,
) -> Result<Value, Box<dyn Error>> {
    if case.is_empty()
        || parameters.iter().any(|x| !x.is_finite() || x.abs() > 8.)
        || parameters[1] < 0.
        || parameters[2] >= parameters[3]
        || (parameters[1] > 0. && parameters[1] < 1. / Q as f64)
    {
        return Err("Invalid typed parameter domain; positive variance must be >= 2^-24".into());
    }
    let feature_vector_q24: Vec<i64> = parameters
        .iter()
        .map(|x| (x * Q as f64).round_ties_even() as i64)
        .collect();
    if feature_vector_q24[2] >= feature_vector_q24[3] {
        return Err("Thresholds collapse in Q24".into());
    }
    let mut native = config()?;
    native.model_digest = Digest32::of_bytes(
        concat!(
            "gaussian.libm.erfc.head.v1:",
            env!("AEN_NATIVE_SOURCE_SHA256")
        )
        .as_bytes(),
    );
    native.normalization_digest = Digest32::of_bytes(b"terminal.probability.simplex.q24.v1");
    let cfg = runtime_config(&native)?;
    let subject = StableId::new(format!("aen.{}", Digest32::of_bytes(case.as_bytes())))?;
    let mut bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    bytes.extend_from_slice(&(subject.as_str().len() as u32).to_be_bytes());
    bytes.extend_from_slice(subject.as_str().as_bytes());
    let objective = Digest32::of_bytes(b"analytic.terminal.prediction.experimental.owner.v1");
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(&bytes),
        objective_digest: objective,
    };
    let path = Path::new(directory);
    fs::create_dir_all(path)?;
    let open = |name| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path.join(name))
    };
    let witness = FileAnchorWitnessStore::open(
        open("anchor.witness")?,
        scope,
        native.generation,
        /*max_records*/ 1024,
    )?;
    let before = witness.current()?;
    let mut runtime = match before {
        Some(anchor) => NeuronRuntime::recover(
            open("state.journal")?,
            native,
            scope,
            /*max_records*/ 1024,
            cfg.clone(),
            anchor,
            witness,
        )?,
        None => NeuronRuntime::bootstrap(
            open("state.journal")?,
            native,
            scope,
            /*max_records*/ 1024,
            cfg.clone(),
            witness,
        )?,
    };
    let current = runtime.current_anchor()?;
    let sequence = current.map_or(1, |a| a.sequence + 1);
    let checkpoint = current.map_or(Digest32::ZERO, |a| a.checkpoint_digest);
    let input = NeuronTickInputV1 {
        tick_id: StableId::new(format!("aen.tick.{sequence}"))?,
        subject_id: subject,
        logical_sequence: sequence,
        monotonic_time_micros: sequence * 1000,
        checkpoint_digest: match expected_checkpoint {
            Some(value) => value.parse()?,
            None => checkpoint,
        },
        input_feature_digest: canonical_feature_vector_digest_v1(&feature_vector_q24),
        feature_vector_q24,
        objective_digest: objective,
        ndu_snapshot_digest: Digest32::of_bytes(case.as_bytes()),
        body_generation: Some(1),
        modulator_digest: None,
    };
    let mut model = AnalyticHead {
        config: cfg,
        latest: None,
    };
    let started = Instant::now();
    let output = runtime.tick(&mut model, input)?;
    let wall_ns = started.elapsed().as_nanos();
    if !output.tick.abstain
        || output.tick.confidence_ppm != 0
        || output.signal.authority.grants_any()
    {
        return Err("Unqualified typed owner must abstain and deny authority".into());
    }
    // New directory entries become durable in addition to the original file fsync.
    File::open(path)?.sync_all()?;
    Ok(
        json!({"case":case,"sequence":sequence,"recovered":before.is_some(),
        "typed_model_port":true,"original_neuron_runtime":true,"original_sparse_journal":true,
        "independent_anchor_witness":true,"native_owner_integration":false,
        "owner_scope":"experimental local owner; not Agentd dispatch owner", "authority":"DENY_ALL",
        "input_parameters_fp64":parameters,"head":model.latest,
        "checkpoint_before":output.tick.checkpoint_before.to_string(),
        "checkpoint_after":output.tick.checkpoint_after.to_string(),
        "model_runtime_digest":output.signal.model_runtime_digest.to_string(),
        "temporal_state_digest":output.signal.temporal_state_digest.to_string(),
        "signals_q24":output.signal.signals_q24,"active_indices":output.tick.active_indices,
        "prediction_error_q24":output.tick.prediction_error_q24,
        "legacy_runtime_confidence_ppm":output.tick.confidence_ppm,
        "calibration_status":"UNQUALIFIED; expired profile; legacy measured slots are unknown worst-case bounds",
        "calibrated_success_probability":false,"abstain":output.tick.abstain,"ood_ppm":output.tick.ood_ppm,
        "typed_tick_wall_ns":wall_ns,"head_execution_micros":output.model_runtime.latency_micros,
        "process_resident_bytes":output.model_runtime.resident_bytes,
        "journal_bytes":fs::metadata(path.join("state.journal"))?.len(),
        "witness_bytes":fs::metadata(path.join("anchor.witness"))?.len(),
        "journal_bytes_written":output.tick.resource_receipt.journal_bytes_written,
        "checkpoint_bytes":output.tick.resource_receipt.checkpoint_bytes,
        "semantic_rng":"none: deterministic probability head; Python pulse owner has versioned RNG"}),
    )
}
