//! Actual terminal projection followed by the earliest real eligibility gate.
//! These are explicitly different research contexts. This test never invents
//! an acknowledged neuron checkpoint to reach the dynamic resolver/proposal.
#![cfg(unix)] // NduProjectionStoreV1 has a declared Unix durability profile.

use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agentd::plasticity_modulator_digest_v1;
use codex_hepta_bellman_operator::LoadedTabularOperatorV1;
use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_infer_core::GenerationRequestV1;
use codex_hepta_infer_worker_host::generation_driver::GenerationProcessEvidenceV1;
use codex_hepta_ndu::NduProjectionKindV1;
use codex_hepta_ndu::NduProjectionStoreV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde_json::Value;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FilePin {
    path: PathBuf,
    sha256: String,
    bytes: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Terminal {
    objective_sha256: String,
    subject_sha256: String,
    artifact_sha256: String,
    dataset_sha256: String,
    training_profile_sha256: String,
    generation: u64,
    sensor_id: String,
    action_id: String,
    observed_value_q32: i64,
    snapshot_sha256: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Neuron {
    objective_sha256: String,
    source_pair_sha256: String,
    snapshot_sha256: String,
    scope_sha256: String,
    generation: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Fixture {
    schema: String,
    inputs: BTreeMap<String, FilePin>,
    terminal: Terminal,
    neuron: Neuron,
    scope: String,
    authority: String,
}

impl Fixture {
    fn read(&self, name: &str) -> Result<Vec<u8>> {
        let pin = self.inputs.get(name).context("registered source file")?;
        let metadata = std::fs::symlink_metadata(&pin.path)?;
        ensure!(pin.path.is_absolute() && metadata.is_file() && !metadata.file_type().is_symlink());
        ensure!(metadata.len() == pin.bytes && pin.bytes <= 8 * 1024 * 1024);
        let bytes = std::fs::read(&pin.path)?;
        ensure!(
            Digest32::of_bytes(&bytes).to_string() == pin.sha256,
            "source byte pin changed"
        );
        Ok(bytes)
    }
}

#[test]
#[ignore = "requires independently pinned completed terminal and rejected-neuron owner evidence"]
fn real_terminal_projection_cannot_supply_missing_neuron_acknowledgement() -> Result<()> {
    let path = PathBuf::from(
        std::env::var_os("HEPTA_PLASTICITY_REJECTION_FIXTURE").context("prepared fixture")?,
    );
    let expected: Digest32 = std::env::var("HEPTA_PLASTICITY_REJECTION_FIXTURE_SHA256")?.parse()?;
    let metadata = std::fs::symlink_metadata(&path)?;
    ensure!(path.is_absolute() && metadata.is_file() && !metadata.file_type().is_symlink());
    ensure!(metadata.len() <= 128 * 1024);
    let bytes = std::fs::read(&path)?;
    ensure!(bytes.len() <= 128 * 1024 && Digest32::of_bytes(&bytes) == expected);
    let fixture: Fixture = serde_json::from_slice(&bytes)?;
    ensure!(
        fixture.schema == "hepta.ndu-v6.plasticity-prerequisite-fixture.v1"
            && fixture.authority == "deny_all"
    );
    ensure!(fixture.scope.contains("distinct research contexts"));
    for name in fixture.inputs.keys() {
        fixture.read(name)?;
    }
    let terminal_report: Value = serde_json::from_slice(&fixture.read("terminal_evidence")?)?;
    let rejected: Value = serde_json::from_slice(&fixture.read("neuron_evidence")?)?;
    ensure!(terminal_report["state"] == "completed" && terminal_report["authority"] == "deny_all");
    ensure!(terminal_report["artifact_digest"] == fixture.terminal.artifact_sha256);
    ensure!(terminal_report["objective_sha256"] == fixture.terminal.objective_sha256);
    ensure!(terminal_report["state_sha256"] == fixture.terminal.subject_sha256);
    ensure!(rejected["status"] == "rejected" && rejected["native_error"] == "InvalidCalibration");
    ensure!(
        rejected["model_executed"] == true
            && rejected["actual_inference_owner_terminal"] == "Completed"
    );
    ensure!(
        rejected["neuron_checkpoint_committed"] == false && rejected["daemon_activated"] == false
    );
    ensure!(
        rejected["authority"] == "deny_all"
            && rejected["specification_sha256"] == fixture.neuron.objective_sha256
    );
    let native_fixture: Value = serde_json::from_slice(&fixture.read("neuron_fixture")?)?;
    let request: GenerationRequestV1 = serde_json::from_value(native_fixture["request"].clone())?;
    let process: GenerationProcessEvidenceV1 =
        serde_json::from_slice(&fixture.read("neuron_process")?)?;
    let execution = process
        .execution
        .as_ref()
        .context("actual owner execution")?;
    execution.verify(&request)?;
    ensure!(
        !process.timed_out
            && process.exit_code == Some(0)
            && process.authority == "deny_all"
            && process.request_sha256 == execution.request_sha256
            && process.model == request.model
    );
    ensure!(
        fixture.neuron.source_pair_sha256 == request.input_source_sha256
            && fixture.neuron.snapshot_sha256 == request.model.snapshot_sha256
    );
    ensure!(fixture.read("neuron_journal")?.is_empty());
    // This is the actual pre-existing witness, not a fresh substitute.
    ensure!(!fixture.read("neuron_witness")?.is_empty());

    let terminal = &fixture.terminal;
    let objective: Digest32 = terminal.objective_sha256.parse()?;
    let subject: Digest32 = terminal.subject_sha256.parse()?;
    let pin = TabularPayloadPinV1 {
        payload_digest: fixture.inputs["terminal_payload"].sha256.parse()?,
        artifact_digest: terminal.artifact_sha256.parse()?,
        objective_digest: objective,
        dataset_digest: terminal.dataset_sha256.parse()?,
        sensor_core_digest: subject,
        training_profile_digest: terminal.training_profile_sha256.parse()?,
        generation: Generation::new(terminal.generation)?,
    };
    let loaded =
        LoadedTabularOperatorV1::from_pinned_payload(&fixture.read("terminal_payload")?, &pin)?;
    ensure!(terminal.action_id == "fixed_dev_tuned");
    let prediction = loaded.predict(
        &StableId::new(&terminal.sensor_id)?,
        &StableId::new(&terminal.action_id)?,
    )?;
    ensure!(
        prediction.value.raw() == terminal.observed_value_q32 && !prediction.authority.grants_any()
    );
    ensure!(
        prediction.value >= FixedQ32::from_raw(-FixedQ32::ONE.raw())
            && prediction.value <= FixedQ32::ONE
    );
    let values = vec![prediction.value];
    let modulator = plasticity_modulator_digest_v1(objective, subject, &values)?;

    let output = tempfile::Builder::new()
        .prefix("plasticity-prerequisite-")
        .tempdir_in(path.parent().context("fixture parent")?)?
        .keep();
    let projection_root = output.join("ndu-owner");
    std::fs::create_dir(&projection_root)?;
    let mut projection = NduProjectionStoreV1::open(&projection_root)?;
    let mut binding = b"hepta.local-terminal-utility-projection.v1\0".to_vec();
    binding.extend_from_slice(expected.as_array());
    binding.extend_from_slice(pin.artifact_digest.as_array());
    let recorded = projection.append_projection(
        NduProjectionKindV1::Utility,
        Digest32::of_bytes(&binding),
        objective,
        subject,
        modulator,
    )?;
    binding.extend_from_slice(b"selected");
    let selected = projection.select_projection(
        Digest32::of_bytes(&binding),
        objective,
        subject,
        modulator,
    )?;
    ensure!(projection.selected_projection_digest(objective, subject)? == Some(modulator));
    let entries = projection.entries()?.to_vec();
    ensure!(entries.len() == 2);
    let backup = projection.backup_bytes()?;
    std::fs::write(output.join("ndu-projection.backup"), &backup)?;
    drop(projection);
    let restored = NduProjectionStoreV1::open(&projection_root)?;
    ensure!(
        restored.entries()? == entries.as_slice()
            && restored.selected_projection_digest(objective, subject)? == Some(modulator)
    );

    let neuron_objective: Digest32 = fixture.neuron.objective_sha256.parse()?;
    let neuron_source: Digest32 = fixture.neuron.source_pair_sha256.parse()?;
    ensure!(objective != neuron_objective && !neuron_source.is_zero());
    ensure!(terminal.snapshot_sha256 != fixture.neuron.snapshot_sha256);
    // Keep the real terminal subject unchanged. The rejected Neuron had no
    // NDU owner; its source-pair identity is not an admitted NDU subject.
    ensure!(
        restored
            .selected_projection_digest(neuron_objective, subject)?
            .is_none()
    );
    let scope = JournalScope {
        scope_digest: fixture.neuron.scope_sha256.parse()?,
        objective_digest: neuron_objective,
    };
    let handle = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&fixture.inputs["neuron_witness"].path)?;
    let witness = FileAnchorWitnessStore::open(
        handle,
        scope,
        Generation::new(fixture.neuron.generation)?,
        /*max_records*/ 8,
    )?;
    let acknowledged = witness.current()?;
    ensure!(acknowledged.is_none());
    // PlasticityDynamicOwnerEvidenceResolverV1::new requires JournalAnchor,
    // plus the admitted SparseJournal. Never convert None to a forged anchor,
    // initialize an unanchored journal, or directly commit eligibility here.
    let prerequisite = acknowledged.ok_or("MissingAcknowledgedNeuronCheckpoint");
    assert_eq!(prerequisite, Err("MissingAcknowledgedNeuronCheckpoint"));
    drop(witness);
    for name in fixture.inputs.keys() {
        fixture.read(name)?;
    }
    let binary = std::fs::read(std::env::current_exe()?)?;
    std::fs::write(output.join("owner-test-executable.bin"), &binary)?;
    let terminal_evidence = serde_json::json!({
        "artifact_sha256": terminal.artifact_sha256, "payload_sha256": pin.payload_digest.to_string(),
        "objective_sha256": terminal.objective_sha256, "subject_sha256": terminal.subject_sha256,
        "snapshot_sha256": terminal.snapshot_sha256, "action_id": terminal.action_id,
        "value_q32_from_loaded_cell": prediction.value.raw(),
    });
    let projection_evidence = serde_json::json!({
        "modulator_semantics": "identity projection of one observed terminal utility; not a neural gradient or general NDU recursion",
        "modulator_sha256": modulator.to_string(), "actual_store_records": 2,
        "projection_entry_sha256": recorded.entry_digest.to_string(), "selected_entry_sha256": selected.entry_digest.to_string(),
        "backup_sha256": Digest32::of_bytes(&backup).to_string(), "recovered_identically": true,
    });
    let neuron_evidence = serde_json::json!({
        "objective_sha256": fixture.neuron.objective_sha256, "source_pair_sha256": fixture.neuron.source_pair_sha256,
        "source_semantics": "source-ID pair identity only; full public request is bound separately; no admitted NDU subject",
        "generation_request_sha256": execution.request_sha256,
        "snapshot_sha256": fixture.neuron.snapshot_sha256, "original_error": "InvalidCalibration",
        "original_journal_bytes": 0, "actual_witness_anchor": null,
    });
    let prerequisite_evidence = serde_json::json!({
        "rejection_layer": "existing AnchorWitnessStore::current returned None; no JournalAnchor for dynamic resolver constructor",
        "rejection": "MissingAcknowledgedNeuronCheckpoint", "same_context_proposal_attempt": false,
        "contexts_relabelled": false, "dynamic_resolver_constructed": false, "parameter_generator_called": false,
        "proposal_admission_called": false, "proposal_writer_created": false, "updates_produced": 0,
        "eligibility_written": false,
    });
    let input_pins = fixture
        .inputs
        .iter()
        .map(|(name, pin)| {
            (
                name,
                serde_json::json!({"path":pin.path,"sha256":pin.sha256,"bytes":pin.bytes}),
            )
        })
        .collect::<BTreeMap<_, _>>();
    let report = serde_json::json!({
        "schema": "hepta.ndu-v6.plasticity-prerequisite-evidence.v1", "state": "completed",
        "fixture_sha256": expected.to_string(), "scope": fixture.scope, "authority": "deny_all",
        "terminal": terminal_evidence, "ndu_projection": projection_evidence,
        "neuron": neuron_evidence, "prerequisite": prerequisite_evidence,
        "original_source_files_unchanged": true, "production_authenticated": false,
        "test_binary_sha256": Digest32::of_bytes(&binary).to_string(),
        "input_file_pins": input_pins,
    });
    let evidence = output.join("evidence.json");
    std::fs::write(&evidence, serde_json::to_vec_pretty(&report)?)?;
    println!(
        "PLASTICITY_PREREQUISITE_EVIDENCE path={} sha256={}",
        evidence.display(),
        Digest32::of_bytes(&std::fs::read(&evidence)?)
    );
    Ok(())
}
