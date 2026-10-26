use super::*;
use crate::report::Inputs;
use crate::report::read;
use crate::report::string;
use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::TrainedCellBundleV5;
use codex_hepta_neuron::trained_cell_compatibility_digest_v5;
use codex_hepta_types::Generation;
use hepta_handoff_recovery_v7::positive::run;
use hepta_handoff_recovery_v7::positive::unhex;
use pretty_assertions::assert_eq;
use std::fs;
use std::path::PathBuf;

mod owner {
    use super::*;
    pub fn id(text: &str) -> Result<codex_hepta_types::StableId> {
        Ok(codex_hepta_types::StableId::new(text)?)
    }
    pub fn digest(text: &str) -> Digest32 {
        Digest32::of_bytes(text.as_bytes())
    }
    pub fn hex(bytes: &[u8]) -> String {
        bytes.iter().map(|b| format!("{b:02x}")).collect()
    }
}
#[path = "../../../trained-cell-v5/actual-review-driver/src/positive_fixtures.rs"]
mod fixtures;
use fixtures::*;
#[path = "audit_binding_tests.rs"]
mod audit_binding_tests;
#[path = "../../../trained-cell-v7/recovery-driver/src/handoff_fixtures.rs"]
mod handoff_fixtures;
#[path = "stream_fixtures.rs"]
mod stream_fixtures;
#[path = "stream_tests.rs"]
mod stream_tests;
#[path = "adapter_fixtures.rs"]
mod studies;
#[path = "adapter_v8_fixtures.rs"]
mod v8_fixtures;

fn inventory(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    let mut result = BTreeMap::new();
    for item in must(fs::read_dir(root)) {
        let path = must(item).path();
        if path.is_dir() {
            result.extend(inventory(&path));
        } else {
            result.insert(path.clone(), must(fs::read(&path)));
        }
    }
    result
}

#[test]
fn full_format_synthetic_report_reaches_exact_signed_owner_and_idempotent_reopen() {
    let study = must(studies::new(-0.002, 32, 6));
    let (profile, loaded) = must(study.load());
    let f = &study.fixture;
    let receipt = must(admission::positive(
        "prepare",
        &profile,
        &loaded,
        f.paths(),
        &f.output,
        None,
    ));
    assert_eq!(receipt["candidate_published"], json!(false));
    let signature = must(f.signature(&f.signing_key));
    let receipt = must(admission::positive(
        "execute",
        &profile,
        &loaded,
        f.paths(),
        &f.output,
        Some(&signature),
    ));
    assert_eq!(
        (
            receipt["candidate_published"].clone(),
            receipt["production_authority"].clone()
        ),
        (json!(true), json!(false))
    );
    assert_eq!(
        receipt["roundtrip"]["owner_bytes_unchanged_during_serving_and_rollback"],
        json!(true)
    );
    let before = inventory(&f.output.join("owner"));
    must(admission::positive(
        "execute",
        &profile,
        &loaded,
        f.paths(),
        &f.output,
        Some(&signature),
    ));
    assert_eq!(inventory(&f.output.join("owner")), before);
}

#[test]
fn exact_task_boundary_rejects_before_owner_or_signing_proposal() {
    let study = must(studies::new(-0.001, 32, 6));
    let (profile, loaded) = must(study.load());
    let receipt = must(admission::reject(&loaded));
    assert_eq!(
        (
            receipt["owner_writes"].clone(),
            receipt["signing_proposal_created"].clone()
        ),
        (json!(0), json!(false))
    );
    let f = &study.fixture;
    assert!(admission::positive("prepare", &profile, &loaded, f.paths(), &f.output, None).is_err());
    assert!(!f.output.exists());
}

#[test]
fn fixed_scientific_family_supports_three_or_seven_registered_policies_without_profile_forks() {
    for count in [3, 7] {
        let study = must(studies::new(-0.002, 32, count));
        let (_, loaded) = must(study.load());
        assert_eq!(
            loaded.disposition()["all_registered_gates_met"],
            json!(true)
        );
    }
    let study = must(studies::new(-0.002, 32, 6));
    let mut protocol: Value = must(serde_json::from_slice(&must(read(&study.protocol))));
    protocol["evaluation"]["policies"][5] = json!("warmup_old");
    let bytes = must(serde_json::to_vec(&protocol));
    let mut profile_value: Value = must(serde_json::from_slice(&must(read(&study.profile))));
    profile_value["protocol_sha256"] = json!(Digest32::of_bytes(&bytes).to_string());
    let pin = must(studies::write(&study.profile, &profile_value));
    let profile = must(profile::Profile::load(&study.profile, pin));
    assert!(profile.verify_protocol(&bytes, &protocol).is_err());
}

#[test]
fn self_rehashed_missing_execution_does_not_become_a_complete_census() {
    let study = must(studies::new(-0.002, 32, 6));
    let mut report: Value = must(serde_json::from_slice(&must(read(&study.evaluation))));
    report["cost_records"].as_array_mut().unwrap().pop();
    let digest = must(studies::write(&study.evaluation, &report));
    let mut gate: Value = must(serde_json::from_slice(&must(read(&study.gate))));
    gate["report_sha256"] = json!(digest.to_string());
    must(studies::write(&study.gate, &gate));
    assert!(study.load().is_err());
    assert!(!study.fixture.output.exists());
}

#[test]
fn source_change_or_uninstalled_profile_cannot_reach_owner() {
    let study = must(studies::new(-0.002, 32, 6));
    assert!(profile::Profile::load(&study.profile, owner::digest("another host pin")).is_err());
    let mut gate: Value = must(serde_json::from_slice(&must(read(&study.gate))));
    gate["training_code_sha256"] =
        json!(owner::digest("changed controller implementation").to_string());
    must(studies::write(&study.gate, &gate));
    assert!(study.load().is_err());
    assert!(!study.fixture.output.exists());
}

#[test]
fn complete_metric_report_cannot_admit_a_midplan_native_payload() {
    let study = must(studies::new(-0.002, 17, 6));
    let (profile, loaded) = must(study.load());
    let f = &study.fixture;
    let error =
        admission::positive("prepare", &profile, &loaded, f.paths(), &f.output, None).unwrap_err();
    assert!(error.to_string().contains("completed exact32"));
    assert!(!f.output.exists());
}

#[test]
fn self_rehashed_controller_stride_change_cannot_replace_the_external_contract() {
    use codex_hepta_neuron::CellTrainingCheckpointV7;
    use codex_hepta_neuron::TrainingHandoffBundleV7;
    let study = must(studies::new(-0.002, 32, 6));
    let bytes = must(read(&study.candidate));
    let bundle = must(TrainingHandoffBundleV7::decode(
        &bytes,
        Digest32::of_bytes(&bytes),
    ));
    let mut checkpoints = Vec::new();
    for checkpoint in bundle.checkpoints() {
        let mut wrapper: Value = must(serde_json::from_slice(
            checkpoint.controller_metadata_json(),
        ));
        let mut source: Value = must(serde_json::from_str(must(string(
            &wrapper,
            "source_controller_json",
        ))));
        source["contract"]["configuration"]["commit_stride"] = json!(1);
        wrapper["controller_config_sha256"] = json!(
            Digest32::of_bytes(&must(serde_json::to_vec(
                &source["contract"]["configuration"]
            )))
            .to_string()
        );
        let source = must(serde_json::to_string(&source));
        wrapper["source_controller_sha256"] =
            json!(Digest32::of_bytes(source.as_bytes()).to_string());
        wrapper["source_controller_json"] = json!(source);
        checkpoints.push(must(CellTrainingCheckpointV7::new(
            checkpoint.cell_id().clone(),
            checkpoint.state_metadata_json().to_vec(),
            checkpoint.state_vector().to_vec(),
            must(serde_json::to_vec(&wrapper)),
            checkpoint.planned_actions().to_vec(),
        )));
    }
    let changed = must(TrainingHandoffBundleV7::new(
        bundle.serving().clone(),
        bundle.protocol_digest(),
        bundle.predecessor_digest(),
        checkpoints,
    ));
    must(fs::write(&study.candidate, changed.encode()));
    let mut conversion: Value = must(serde_json::from_slice(&must(read(
        &study.fixture.conversion,
    ))));
    conversion["versions"][1]["handoff_payload_sha256"] =
        json!(changed.content_digest().to_string());
    let conversion_digest = must(studies::write(&study.fixture.conversion, &conversion));
    let mut gate: Value = must(serde_json::from_slice(&must(read(&study.gate))));
    gate["candidate_sha256"] = json!(changed.content_digest().to_string());
    gate["conversion_manifest_sha256"] = json!(conversion_digest.to_string());
    must(studies::write(&study.gate, &gate));
    let error = study.load().err().unwrap();
    assert!(error.to_string().contains("complete contract"));
    assert!(!study.fixture.output.exists());
}

#[test]
fn honest_incomplete_candidate_is_an_unavailable_gate_and_no_owner_write() {
    let study = must(studies::new(-0.002, 32, 6));
    let mut report: Value = must(serde_json::from_slice(&must(read(&study.evaluation))));
    let matches = |row: &Value| {
        row["task"] == "agnews"
            && row["head"] == "linear"
            && row["seed"] == 7
            && row["policy"] == "synthetic-policy-0"
    };
    for field in ["cost_records", "records", "completion_gates"] {
        for row in report[field]
            .as_array_mut()
            .unwrap()
            .iter_mut()
            .filter(|row| matches(row))
        {
            row["completed_steps"] = json!(24);
            if field == "records" {
                row["execution_status"] = json!("stopped");
            } else {
                row["status"] = json!("stopped");
            }
            if field == "completion_gates" {
                row["criterion_met"] = json!(false);
            }
        }
    }
    report["required_completion_met"] = json!(false);
    report["candidate_completed_fits"] = json!(11);
    report["all_registered_gates_met"] = json!(false);
    let digest = must(studies::write(&study.evaluation, &report));
    let mut gate: Value = must(serde_json::from_slice(&must(read(&study.gate))));
    gate["required_completion_met"] = json!(false);
    gate["all_registered_gates_met"] = json!(false);
    gate["report_sha256"] = json!(digest.to_string());
    for name in ["task", "retention", "total_cost"] {
        gate["comparisons"][name]["evidence_sha256"] = json!(digest.to_string());
        gate["comparisons"][name]["measurement"] = json!({"status":"unavailable"});
    }
    must(studies::write(&study.gate, &gate));
    let (profile, loaded) = must(study.load());
    assert_eq!(must(admission::reject(&loaded))["owner_writes"], json!(0));
    let f = &study.fixture;
    assert!(admission::positive("prepare", &profile, &loaded, f.paths(), &f.output, None).is_err());
    assert!(!f.output.exists());
}

#[test]
fn changed_audit_profile_and_unknown_controller_schema_stay_closed() {
    let study = must(studies::new(-0.002, 32, 6));
    let (profile, loaded) = must(study.load());
    let f = &study.fixture;
    let mut audit: Value = must(serde_json::from_slice(&must(read(&f.replay))));
    audit["native_profile_sha256"] = json!(owner::digest("another profile").to_string());
    must(studies::write(&f.replay, &audit));
    assert!(admission::positive("prepare", &profile, &loaded, f.paths(), &f.output, None).is_err());
    assert!(!f.output.exists());
    let mut value: Value = must(serde_json::from_slice(&must(read(&study.profile))));
    value["controller_schema"] = json!("hepta.cell-field-controller.v8");
    let pin = must(studies::write(&study.profile, &value));
    assert!(profile::Profile::load(&study.profile, pin).is_err());
}
