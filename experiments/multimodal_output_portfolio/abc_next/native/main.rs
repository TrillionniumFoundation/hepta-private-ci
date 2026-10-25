//! Actual native runtime replay on independently qualified, frozen head inputs.
mod head;
mod measure;
mod runtime_profile;

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::Instant;

use codex_hepta_ndu::NduProjectionKindV1;
use codex_hepta_ndu::NduProjectionStoreV1;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use codex_native_owner_bridge::plasticity_modulator_digest_v1;
use serde::Deserialize;
use serde_json::json;

#[global_allocator]
static ALLOCATOR: measure::ObservedAllocator = measure::ObservedAllocator;
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

#[derive(Deserialize)]
struct Row {
    pair: usize,
    features: Vec<i64>,
    confidence_ppm: u32,
    ood_ppm: u32,
    declared_ood: bool,
    joint_correct: u8,
    terminal_value_q32: i64,
    observed_record_digest: String,
    source_pair_digest: String,
}
#[derive(Deserialize)]
struct Packet {
    pins: runtime_profile::Pins,
    rows: Vec<Row>,
    weights_path: String,
    calibration_path: String,
    verification_path: String,
}

fn file(path: &Path) -> Result<File> {
    Ok(OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)?)
}
fn checked_read(path: &str, expected: &str) -> Result<Vec<u8>> {
    let bytes = std::fs::read(path)?;
    if Digest32::of_bytes(&bytes).to_string() != expected {
        return Err("File pin changed".into());
    }
    Ok(bytes)
}
fn percentile(values: &mut [u64], p: usize) -> u64 {
    values.sort_unstable();
    values[(values.len() * p).div_ceil(100) - 1]
}

fn main() -> Result<()> {
    let process_started = Instant::now();
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        return Err("Usage: native-head packet.json expected-sha256 new-output-directory".into());
    }
    let packet_bytes = checked_read(&args[1], &args[2])?;
    let packet: Packet = serde_json::from_slice(&packet_bytes)?;
    let output = Path::new(&args[3]);
    std::fs::create_dir(output)?;
    let weights_bytes = checked_read(&packet.weights_path, &packet.pins.weights)?;
    let calibration_bytes = checked_read(&packet.calibration_path, &packet.pins.calibration)?;
    let verification_bytes = checked_read(&packet.verification_path, &packet.pins.verification)?;
    let verification: serde_json::Value = serde_json::from_slice(&verification_bytes)?;
    if verification["native_measured_ece_ppm"].as_u64() != Some(packet.pins.measured_ece_ppm as u64)
        || verification["native_measured_false_acceptance_ppm"].as_u64()
            != Some(packet.pins.measured_false_acceptance_ppm as u64)
    {
        return Err(
            "Reported calibration does not match the independent verification artifact".into(),
        );
    }
    let binary = Digest32::of_bytes(&std::fs::read(std::env::current_exe()?)?);
    let (native, config) = runtime_profile::configuration(&packet.pins, binary)?;
    let model_heap_before = measure::live_bytes();
    let mut model = head::LearnedHead {
        weights: serde_json::from_slice(&weights_bytes)?,
        calibration: serde_json::from_slice(&calibration_bytes)?,
        config: config.clone(),
        measured_resident_heap_bytes: 0,
    };
    model.measured_resident_heap_bytes = measure::live_bytes() - model_heap_before;
    let objective: Digest32 = packet.pins.protocol.parse()?;
    let mut samples = Vec::new();
    let mut outer = Vec::new();
    let mut allocation = Vec::new();
    let mut admitted = 0;
    let mut id_admitted = 0;
    let mut ood_admitted = 0;
    let mut parity = 0;
    let mut recovered = 0;
    let mut records = File::create_new(output.join("ticks.jsonl"))?;
    for row in &packet.rows {
        let root = output.join(format!("case-{:04}", row.pair));
        std::fs::create_dir(&root)?;
        let subject = StableId::new(format!(
            "abc3.case.{}.{}",
            row.pair,
            &row.source_pair_digest[..16]
        ))?;
        let scope = JournalScope {
            scope_digest: runtime_profile::subject_scope(&subject),
            objective_digest: objective,
        };
        let values = vec![FixedQ32::from_raw(row.terminal_value_q32)];
        let modulator = plasticity_modulator_digest_v1(objective, scope.scope_digest, &values)?;
        let ndu_root = root.join("ndu");
        std::fs::create_dir(&ndu_root)?;
        let mut projection = NduProjectionStoreV1::open(&ndu_root)?;
        let observation: Digest32 = row.observed_record_digest.parse()?;
        projection.append_projection(
            NduProjectionKindV1::Utility,
            observation,
            objective,
            scope.scope_digest,
            modulator,
        )?;
        let selected_identity = Digest32::of_bytes(format!("{observation}:selected").as_bytes());
        projection.select_projection(
            selected_identity,
            objective,
            scope.scope_digest,
            modulator,
        )?;
        let backup = projection.backup_bytes()?;
        drop(projection);
        std::fs::write(root.join("ndu.backup"), &backup)?;
        let projection = NduProjectionStoreV1::open(&ndu_root)?;
        if projection.selected_projection_digest(objective, scope.scope_digest)? != Some(modulator)
        {
            return Err("NDU projection recovery mismatch".into());
        }
        let journal_path = root.join("neuron.journal");
        let witness_path = root.join("neuron.witness");
        let witness =
            FileAnchorWitnessStore::open(file(&witness_path)?, scope, native.generation, 2)?;
        let mut runtime = NeuronRuntime::bootstrap(
            file(&journal_path)?,
            native.clone(),
            scope,
            2,
            config.clone(),
            witness,
        )?;
        let input = NeuronTickInputV1 {
            tick_id: StableId::new(format!("abc3.tick.{}", row.pair))?,
            subject_id: subject,
            logical_sequence: 1,
            monotonic_time_micros: 1,
            checkpoint_digest: Digest32::ZERO,
            input_feature_digest: canonical_feature_vector_digest_v1(&row.features),
            feature_vector_q24: row.features.clone(),
            objective_digest: objective,
            ndu_snapshot_digest: modulator,
            body_generation: Some(1),
            modulator_digest: Some(modulator),
        };
        let journal_before = std::fs::metadata(&journal_path)?.len();
        let witness_before = std::fs::metadata(&witness_path)?.len();
        let baseline = measure::start_window();
        let began = Instant::now();
        let result = runtime.tick(&mut model, input)?;
        let outer_micros = began.elapsed().as_micros() as u64;
        let outer_allocation = measure::peak_delta(baseline) as u64;
        let journal_delta = std::fs::metadata(&journal_path)?.len() - journal_before;
        let witness_delta = std::fs::metadata(&witness_path)?.len() - witness_before;
        let anchor = runtime
            .current_anchor()?
            .ok_or("Missing acknowledged checkpoint")?;
        let eligibility = runtime
            .current_eligibility_sample()?
            .ok_or("Missing eligibility")?;
        let checkpoint = runtime.canonical_checkpoint(&result.tick, u64::MAX)?;
        std::fs::write(
            root.join("checkpoint.bin"),
            encode_neuron_checkpoint_v1(&checkpoint)?,
        )?;
        if result.tick.confidence_ppm == row.confidence_ppm && result.tick.ood_ppm == row.ood_ppm {
            parity += 1;
        } else {
            return Err("Rust head differs from frozen qualification prediction".into());
        }
        if !result.tick.abstain {
            admitted += 1;
            if row.declared_ood {
                ood_admitted += 1;
            } else {
                id_admitted += 1;
            }
        }
        samples.push(NeuronResourceSampleV1 {
            host_profile_digest: config.device_digest,
            exact_candidate_digest: config.model_manifest_digest,
            observed_at_micros: row.pair as u64 + 1,
            receipt: result.tick.resource_receipt.clone(),
        });
        outer.push(outer_micros);
        allocation.push(outer_allocation);
        drop(runtime);
        let witness =
            FileAnchorWitnessStore::open(file(&witness_path)?, scope, native.generation, 2)?;
        if witness.current()? != Some(anchor) {
            return Err("Durable witness differs from returned anchor".into());
        }
        let restored = NeuronRuntime::recover(
            file(&journal_path)?,
            native.clone(),
            scope,
            2,
            config.clone(),
            anchor,
            witness,
        )?;
        if restored.current_anchor()? != Some(anchor)
            || restored.current_eligibility_sample()?.as_ref() != Some(&eligibility)
        {
            return Err("Runtime recovery changed checkpoint/eligibility".into());
        }
        recovered += 1;
        drop(restored);
        let record = json!({"pair":row.pair,"subject_scope":scope.scope_digest.to_string(),"objective":objective.to_string(),
            "confidence_ppm":result.tick.confidence_ppm,"ood_ppm":result.tick.ood_ppm,"abstain":result.tick.abstain,
            "joint_correct":row.joint_correct,"declared_ood":row.declared_ood,"anchor":anchor.checkpoint_digest.to_string(),
            "sequence":anchor.sequence,"eligibility_digest":result.tick.eligibility_digest.to_string(),
            "eligibility_q24":eligibility.eligibility_q24(),"native_execution_micros":result.tick.resource_receipt.execution_micros,
            "outer_tick_with_witness_micros":outer_micros,"model_latency_micros":result.model_runtime.latency_micros,
            "outer_peak_live_allocation_delta":outer_allocation,"model_peak_live_allocation_delta":result.tick.resource_receipt.transient_allocation_bytes,
            "checkpoint_bytes":result.tick.resource_receipt.checkpoint_bytes,"journal_bytes_written":journal_delta,
            "witness_bytes_written":witness_delta,"ndu_modulator":modulator.to_string(),"ndu_terminal_q32":row.terminal_value_q32,
            "source_pair_digest":row.source_pair_digest,"observed_record_digest":row.observed_record_digest,
            "authority":"deny_all","recovered":true});
        writeln!(records, "{record}")?;
        if row.pair == 0 {
            std::fs::write(
                root.join("context.json"),
                serde_json::to_vec_pretty(&record)?,
            )?;
        }
    }
    records.sync_all()?;
    let summary = summarize_resource_samples(&samples, &config.resource_envelope)?;
    let outer95 = percentile(&mut outer, 95);
    let outer99 = percentile(&mut outer, 99);
    let maximum_allocation = *allocation.iter().max().ok_or("No samples")?;
    let report = json!({"schema":"hepta.abc3.resident-native-execution.v1","packet_sha256":args[2],"binary_sha256":binary.to_string(),
        "real_native_runtime_invocations":samples.len(),"new_independent_statistical_samples":0,
        "admitted_nonabstaining_ticks":admitted,"id_nonabstaining":id_admitted,"ood_nonabstaining":ood_admitted,
        "prediction_parity":parity,"acknowledged_recovery_count":recovered,"measured_ece_ppm":packet.pins.measured_ece_ppm,
        "measured_false_acceptance_ppm":packet.pins.measured_false_acceptance_ppm,
        "native_p95_micros":summary.p95_execution_micros,"native_p99_micros":summary.p99_execution_micros,
        "outer_p95_including_witness_micros":outer95,"outer_p99_including_witness_micros":outer99,
        "maximum_model_transient_allocation":summary.maximum_transient_allocation_bytes,
        "maximum_outer_tick_peak_live_delta":maximum_allocation,"maximum_checkpoint_bytes":summary.maximum_checkpoint_bytes,
        "native_maximum_write_amplification_ppm":summary.maximum_write_amplification_ppm,
        "native_resource_samples_pass":summary.pilot_ceiling_passed_for_supplied_samples,
        "outer_resource_samples_pass":outer95<=3000 && outer99<=8000 && maximum_allocation<=524288,
        "sample_set_digest":summary.sample_set_digest.to_string(),"process_wall_micros":process_started.elapsed().as_micros(),
        "source_manifest":packet.pins.source_manifest,"dataset":packet.pins.dataset,
        "measured_model_resident_heap_bytes":model.measured_resident_heap_bytes,
        "process_status_at_end":std::fs::read_to_string("/proc/self/status")?,
        "scope":"resident correctness head with real native NDU projection store, NeuronRuntime, file witness and recovery; upstream generator separately charged",
        "future_dynamics_forecast":false,"agentd_fleet_process":false,"production_authority":false,"authority":"deny_all"});
    std::fs::write(
        output.join("result.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    println!("{report}");
    Ok(())
}
