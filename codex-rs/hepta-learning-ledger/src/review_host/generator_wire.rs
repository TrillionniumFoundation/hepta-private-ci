//! The generator signs typed decisions. This wire has no outcome/signing API.
use super::files::ReviewResult;
use crate::LearningEvidenceRoleV1;
use crate::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::path::PathBuf;

pub use crate::public_principal_wire_v1::PrincipalWire;
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct GeneratorContract {
    pub schema: String,
    pub uid: u32,
    pub principal: PrincipalWire,
    pub objective_digest: String,
    pub trust_digest: String,
    pub audit_digest: String,
    pub generator_program_digest: String,
    pub scorer_path: PathBuf,
    pub scorer_digest: String,
    pub candidate_manifest_path: PathBuf,
    pub candidate_weights_path: PathBuf,
    pub baseline_manifest_path: PathBuf,
    pub baseline_weights_path: PathBuf,
    pub mapping_path: PathBuf,
    pub inputs_path: PathBuf,
    pub private_key_path: PathBuf,
    pub inaccessible_paths: Vec<PathBuf>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SignedDecisionRow {
    pub index: usize,
    pub policy: String,
    pub observation_line: String,
    pub payload_digest: String,
    pub signature_hex: String,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct GeneratorBatch {
    pub schema: String,
    pub contract_digest: String,
    pub program_digest: String,
    pub uid: u32,
    pub no_new_privileges: bool,
    pub supplementary_groups_empty: bool,
    pub capabilities_zero: bool,
    pub cgroup: String,
    pub private_custody_denied: usize,
    pub issued_at_ms: u64,
    pub rows: Vec<SignedDecisionRow>,
}
pub(super) fn generator_evidence(
    contract: &GeneratorContract,
    row: &SignedDecisionRow,
    issued: u64,
) -> ReviewResult<SignedLearningEvidenceV1> {
    let p = contract.principal.principal()?;
    Ok(SignedLearningEvidenceV1 {
        evidence_id: StableId::new(format!(
            "calibration.generator.{}.{}.{}",
            contract.audit_digest, row.policy, row.index
        ))?,
        principal_id: p.principal_id,
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: contract.trust_digest.parse()?,
        scope_digest: p.scope_digest,
        objective_digest: contract.objective_digest.parse()?,
        authority_epoch: p.authority_epoch,
        issued_at: issued,
        expires_at: issued
            .checked_add(3_600_000)
            .ok_or("expiry overflow")?
            .min(p.expires_at),
        payload_digest: row.payload_digest.parse()?,
        signature: decode_hex::<64>(&row.signature_hex)?,
    })
}
pub(super) use crate::public_evidence_wire_v1::decode_hex;
pub(super) use crate::public_evidence_wire_v1::encode_hex;
pub(super) fn now_ms() -> ReviewResult<u64> {
    Ok(u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_millis(),
    )?)
}
pub(super) fn program_digest(path: &std::path::Path) -> ReviewResult<Digest32> {
    Ok(Digest32::of_bytes(&super::files::read_root(
        path,
        128 * 1024 * 1024,
        super::files::Access::Immutable,
    )?))
}

pub(super) fn bounded_generator_controller(
    program: Digest32,
    uid: u32,
    launcher: Digest32,
    manager: Digest32,
) -> ReviewResult<StableId> {
    Ok(StableId::new(format!(
        "bounded-generator.{}",
        Digest32::of_bytes(
            &[
                program.as_array().as_slice(),
                uid.to_be_bytes().as_slice(),
                launcher.as_array(),
                manager.as_array(),
                b"clear-groups;all-caps-zero;no-new-privileges;cgroup-memory-256MiB-pids16-cpu100;protected-eval-custody",
            ]
            .concat()
        )
    ))?)
}
