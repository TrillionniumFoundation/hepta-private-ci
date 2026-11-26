//! Root-protected approval of actual successor programs before any new execution.
//! Keys, identity, epoch, scope and original ledger configuration stay pinned.
use super::files::Access;
use super::files::ReviewResult;
use super::files::read_root;
use super::generator_wire::program_digest;
use super::independent_trust::IndependentTrustConfig;
use super::transfer::FixedCalibrationPublicationV1;
use crate::LearningEvidenceRoleV1;
use crate::activate_learning_trust;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use std::path::Path;
use std::path::PathBuf;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ProgramApproval {
    pub schema: String,
    pub original_trust_config_digest: String,
    pub previous_publication_path: PathBuf,
    pub previous_publication_digest: String,
    pub observer_program_digest: String,
    pub reviewer_program_path: PathBuf,
    pub reviewer_program_digest: String,
    pub reviewer_uid: u32,
    pub reviewer_gid: u32,
    pub reviewer_verifying_key_digest: String,
    pub authority_epoch: u64,
    pub scope_digest: String,
    pub objective_digest: String,
    pub generation: u64,
    pub effective_at_ms: u64,
    pub expires_at_ms: u64,
}
pub(super) struct ApprovedCycle {
    pub value: ProgramApproval,
    pub digest: Digest32,
    pub previous_sequence: u64,
    pub previous_head: Digest32,
    pub previous_root_key: [u8; 32],
    pub previous_trust: crate::ActivatedLearningTrustV1,
}
impl ApprovedCycle {
    pub(super) fn open(
        path: &Path,
        config: &IndependentTrustConfig,
        original: Digest32,
        actual_observer: Digest32,
        now: u64,
    ) -> ReviewResult<Self> {
        let bytes = read_root(path, 16 * 1024, Access::Private)?;
        let value: ProgramApproval = serde_json::from_slice(&bytes)?;
        let reviewer = config
            .independent_reviewer
            .as_ref()
            .ok_or("cycle needs original independent reviewer")?;
        let old_bytes = read_root(
            &value.previous_publication_path,
            4 * 1024 * 1024,
            Access::Immutable,
        )?;
        let metadata: serde_json::Value = serde_json::from_slice(&old_bytes)?;
        let old: FixedCalibrationPublicationV1 = if metadata.get("schema").is_some() {
            let previous: super::cycle_transfer::FixedCalibrationPublicationV2 =
                serde_json::from_slice(&old_bytes)?;
            previous.signing_payload()?;
            previous.into_original_fields()
        } else {
            serde_json::from_slice(&old_bytes)?
        };
        let (root, distribution) = old.trust.native()?;
        let original_generation = distribution.distribution.generation;
        let old_review = distribution
            .distribution
            .trust
            .signers
            .iter()
            .find(|s| s.principal.principal_id.as_str() == "fixed-no-custody-reviewer")
            .cloned();
        let previous_trust = activate_learning_trust(&root, distribution, None, now)?;
        if value.schema != "hepta.fixed-calibration-cycle-program-approval.v2"
            || value.original_trust_config_digest.parse::<Digest32>()? != original
            || Digest32::of_bytes(&old_bytes)
                != value.previous_publication_digest.parse::<Digest32>()?
            || value.observer_program_digest.parse::<Digest32>()? != actual_observer
            || value.authority_epoch != config.authority_epoch
            || value.scope_digest != config.scope_digest
            || value.objective_digest != config.objective_digest
            || value.reviewer_uid != reviewer.uid
            || value.reviewer_gid != reviewer.gid
            || value.generation
                != original_generation
                    .checked_add(1)
                    .ok_or("cycle generation overflow")?
            || value.effective_at_ms < config.valid_from
            || value.effective_at_ms > now
            || value.expires_at_ms <= now
            || value.expires_at_ms > config.expires_at
            || old.trust.scope_digest != config.scope_digest
            || old.trust.objective_digest != config.objective_digest
            || old.trust.authority_epoch != config.authority_epoch
            || old_review
                .as_ref()
                .is_none_or(|s| s.roles != [LearningEvidenceRoleV1::Evaluator])
        {
            return Err("current cycle approval changed original admitted identity/epoch/policy or successor pins".into());
        }
        let key = read_root(&reviewer.public_key_path, 32, Access::Immutable)?;
        if value.reviewer_verifying_key_digest.parse::<Digest32>()? != Digest32::of_bytes(&key)
            || old_review
                .as_ref()
                .ok_or("original reviewer")?
                .verifying_key
                .as_slice()
                != key
            || program_digest(&value.reviewer_program_path)?
                != value.reviewer_program_digest.parse::<Digest32>()?
            || program_digest(&reviewer.program_path)?
                != reviewer.program_digest.parse::<Digest32>()?
        {
            return Err("actual current/original immutable reviewer or public key changed".into());
        }
        Ok(Self {
            digest: Digest32::of_bytes(&bytes),
            previous_sequence: old.cut.acknowledged_sequence,
            previous_head: old.cut.acknowledged_head.parse()?,
            previous_root_key: root.verifying_key,
            previous_trust,
            value,
        })
    }
}
