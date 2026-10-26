//! The one report-to-owner adapter shared by explicitly installed future studies.
//! Historical frozen parsers and their receipts remain unchanged.
use crate::Result;
use crate::ensure;
pub use crate::profile::HEADS;
use crate::profile::Profile;
pub use crate::profile::SEEDS;
pub use crate::profile::TASKS;
use codex_hepta_types::Digest32;
pub use hepta_handoff_recovery_v7::report::Inputs;
pub use hepta_handoff_recovery_v7::report::array;
pub use hepta_handoff_recovery_v7::report::hash;
pub use hepta_handoff_recovery_v7::report::key;
pub use hepta_handoff_recovery_v7::report::number;
pub use hepta_handoff_recovery_v7::report::read;
pub use hepta_handoff_recovery_v7::report::string;
use serde_json::Value;
use serde_json::json;
use std::path::Path;

pub struct Paths<'a> {
    pub protocol: &'a Path,
    pub evaluation: &'a Path,
    pub gate: &'a Path,
    pub predecessor: &'a Path,
    pub candidate: &'a Path,
    pub conversion: &'a Path,
    pub contracts: &'a Path,
}
pub struct Loaded {
    pub(crate) inputs: Inputs,
    pub(crate) protocol: Value,
    pub(crate) gate: Value,
    pub(crate) profile_digest: Digest32,
}
impl Loaded {
    pub fn disposition(&self) -> Value {
        json!({"all_registered_gates_met":self.inputs.all_numeric_gates_pass,
            "measurements":self.inputs.aggregate,"protocol_sha256":self.inputs.policy.protocol_digest.to_string(),
            "report_sha256":self.inputs.report_digest.to_string(),"gate_input_sha256":self.inputs.gate_digest.to_string(),
            "native_profile_sha256":self.profile_digest.to_string(),"production_authority":false})
    }
}

pub fn load(profile: &Profile, paths: &Paths<'_>) -> Result<Loaded> {
    let protocol_bytes = read(paths.protocol)?;
    let report_bytes = read(paths.evaluation)?;
    let gate_bytes = read(paths.gate)?;
    let protocol: Value = serde_json::from_slice(&protocol_bytes)?;
    let report: Value = serde_json::from_slice(&report_bytes)?;
    let gate: Value = serde_json::from_slice(&gate_bytes)?;
    profile.verify_protocol(&protocol_bytes, &protocol)?;
    profile.verify_bindings(&gate)?;
    let protocol_digest = Digest32::of_bytes(&protocol_bytes);
    let report_digest = Digest32::of_bytes(&report_bytes);
    ensure(
        hash(&report, "protocol_sha256")? == protocol_digest
            && hash(&gate, "protocol_sha256")? == protocol_digest
            && hash(&gate, "report_sha256")? == report_digest
            && report["schema"] == profile.value()["evaluation_schema"]
            && report["candidate"] == profile.value()["candidate_policy"]
            && report["study_scope"] == profile.value()["study_scope"]
            && gate["candidate_format"] == profile.value()["candidate_format"],
        "report, candidate format or study identity differs",
    )?;
    let definition = json!({"mpc":protocol["mpc"],"models":protocol["models"],"evaluation":protocol["evaluation"]});
    let canonical = string(&gate, "candidate_definition_json")?;
    ensure(
        serde_json::from_str::<Value>(canonical)? == definition
            && Digest32::of_bytes(canonical.as_bytes())
                == hash(&gate, "candidate_definition_sha256")?,
        "candidate algorithm definition changed",
    )?;
    let datasets = string(&gate, "source_dataset_definition_json")?;
    ensure(
        Digest32::of_bytes(datasets.as_bytes()) == hash(&gate, "source_dataset_sha256")?,
        "dataset definition differs from the installed source identity",
    )?;
    let predecessor = read(paths.predecessor)?;
    let candidate = read(paths.candidate)?;
    ensure(
        Digest32::of_bytes(&predecessor) == hash(&gate, "predecessor_sha256")?
            && Digest32::of_bytes(&candidate) == hash(&gate, "candidate_sha256")?,
        "full-state payload digest differs",
    )?;
    crate::payload::verify(
        profile,
        &gate,
        paths.conversion,
        paths.contracts,
        &predecessor,
        &candidate,
    )?;
    let census = crate::census::verify(&report, &gate, &protocol)?;
    let scores = crate::measurements::evaluate(&protocol, &report, &gate, census)?;
    Ok(Loaded {
        inputs: Inputs {
            policy: scores.policy,
            measurements: scores.measurements,
            aggregate: scores.aggregate,
            report_digest,
            gate_digest: Digest32::of_bytes(&gate_bytes),
            candidate,
            predecessor,
            code_digest: hash(&gate, "training_code_sha256")?,
            runtime_digest: hash(&gate, "runtime_sha256")?,
            dataset_digest: hash(&gate, "source_dataset_sha256")?,
            all_numeric_gates_pass: scores.passed,
        },
        protocol,
        gate,
        profile_digest: profile.digest(),
    })
}
