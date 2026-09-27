//! Fail-closed production admission for kernel.evidence.
//!
//! Production requires authenticated-admission snapshot V2 and monotonic owner
//! trust V2. Legacy snapshot/trust formats remain readable in development but
//! never become production authority by relabelling.

use std::collections::BTreeSet;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EvidenceAcceptedFrontierV1;
use codex_hepta_evidence::EvidenceFrontierBackend;
use codex_hepta_evidence::EvidenceRecoveryFrontierV2;
use codex_hepta_evidence::EvidenceTrustGenerationAcceptanceV1;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_evidence::LockedFileEvidenceFrontierBackend;
use codex_hepta_evidence::VerifiedEvidenceTrustSnapshot;
use codex_hepta_evidence::evidence_recovery_frontier_v2_sha256;
use codex_hepta_evidence::evidence_recovery_ledger_root_v2;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::evidence_frontier_signers::EvidenceFrontierSignerTrustV2;
use crate::evidence_trust::read_owner_file;

const PRODUCTION_CONFIG_SCHEMA_VERSION: u32 = 1;
const BACKUP_PUBLICATION_SCHEMA_VERSION: u32 = 2;
const BUILD_PROVENANCE_SCHEMA_VERSION: u32 = 1;
const BACKUP_RESTORE_WITNESS_SCHEMA_VERSION: u32 = 1;
const MAX_EXTERNAL_CONTROL_FILE_BYTES: u64 = 2 * 1024 * 1024;
const MAX_EXECUTABLE_BYTES: u64 = 4 * 1024 * 1024 * 1024;
const MAX_BACKUP_OBJECT_BYTES: u64 = 4_u64 * 1024 * 1024 * 1024 * 1024;
const MAX_FRONTIER_AGE_MS: u64 = 30 * 24 * 60 * 60 * 1000;
const MAX_FUTURE_CLOCK_SKEW_MS: u64 = 5 * 60 * 1000;
const REQUIRED_QUALIFICATION_CHECKS: [&str; 5] = [
    "agentd-product-test",
    "docs",
    "evidence-tests",
    "implementation-maps",
    "lane-a-truth",
];
const NON_RELEASE_QUALIFICATION_FLAGS: [&str; 5] = [
    "independentAcceptance",
    "externalFrontierActive",
    "backupRestoreDrilled",
    "canaryAccepted",
    "releaseApproved",
];

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceProductionConfigV1 {
    schema_version: u32,
    mode: String,
    agent_id: String,
    store_id: String,
    external_backend_root: PathBuf,
    backend_identity_sha256: Sha256Digest,
    exact_source_receipt_file: PathBuf,
    merge_candidate_receipt_file: PathBuf,
    backup_publication_receipt_file: PathBuf,
    minimum_frontier_generation: u64,
    frontier_max_age_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct QualifiedSourceIdentity {
    source_commit: String,
    source_tree: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct QualificationWorkflowIdentity {
    repository: String,
    run_id: u64,
    run_attempt: u64,
}

include!("evidence_backup_manifest.rs");

pub(crate) fn is_production_evidence_profile(
    identity: &AgentdIdentity,
    descriptor_or_frontier: &Path,
) -> bool {
    descriptor_or_frontier.parent() == Some(identity.home_root.as_path())
}

/// Returns only the issuer digest actually admitted by the signed frontier.
/// The host retains this pin for every operation in the process generation.
pub(crate) async fn verify_production_evidence_frontier(
    identity: &AgentdIdentity,
    store: &HeptaEvidenceStore,
    issuer_trust_file: &Path,
    production_config_file: &Path,
    signer_trust_file: &Path,
) -> Result<Sha256Digest, AgentdError> {
    let config_bytes = read_owner_file(production_config_file, identity)?;
    let config: EvidenceProductionConfigV1 = serde_json::from_slice(&config_bytes)?;
    config.validate(identity)?;
    let root = config.external_backend_root.canonicalize()?;
    if root != config.external_backend_root {
        return Err(recovery_required(
            "external frontier backend root must be canonical",
        ));
    }
    let external_files = [
        signer_trust_file,
        config.exact_source_receipt_file.as_path(),
        config.merge_candidate_receipt_file.as_path(),
        config.backup_publication_receipt_file.as_path(),
    ];
    let mut unique_files = BTreeSet::new();
    for path in external_files {
        if !unique_files.insert(path.to_path_buf()) {
            return Err(recovery_required(
                "production evidence control files must be role-distinct",
            ));
        }
    }
    let signer_trust_bytes = read_external_private_file(
        signer_trust_file,
        &root,
        identity,
        MAX_EXTERNAL_CONTROL_FILE_BYTES,
    )?;
    let exact_source_bytes = read_external_private_file(
        &config.exact_source_receipt_file,
        &root,
        identity,
        MAX_EXTERNAL_CONTROL_FILE_BYTES,
    )?;
    let merge_candidate_bytes = read_external_private_file(
        &config.merge_candidate_receipt_file,
        &root,
        identity,
        MAX_EXTERNAL_CONTROL_FILE_BYTES,
    )?;
    let backup_publication_bytes = read_external_private_file(
        &config.backup_publication_receipt_file,
        &root,
        identity,
        MAX_EXTERNAL_CONTROL_FILE_BYTES,
    )?;
    let issuer_trust_bytes = read_owner_file(issuer_trust_file, identity)?;
    let issuer_trust_sha256 = Sha256Digest::for_bytes(&issuer_trust_bytes);
    let signer_trust = EvidenceFrontierSignerTrustV2::parse(&signer_trust_bytes)?;
    let signer_trust_sha256 = Sha256Digest::for_bytes(&signer_trust_bytes);
    let qualified_source =
        validate_qualification_receipts(&exact_source_bytes, &merge_candidate_bytes)?;
    let qualification_receipt_sha256 = qualification_receipt_set_sha256(
        &Sha256Digest::for_bytes(&exact_source_bytes),
        &Sha256Digest::for_bytes(&merge_candidate_bytes),
    );
    let backup_publication_sha256 = Sha256Digest::for_bytes(&backup_publication_bytes);
    let backup: EvidenceBackupPublicationReceiptV1 =
        serde_json::from_slice(&backup_publication_bytes)?;
    let build_artifact_sha256 = current_executable_sha256()?;
    let mut backend = LockedFileEvidenceFrontierBackend::open_external(
        &root,
        config.backend_identity_sha256.clone(),
        &identity.home_root,
    )
    .map_err(backend_error)?;
    backend.verify_backend_identity().map_err(backend_error)?;
    let frontier = backend
        .get_latest(&config.store_id)
        .map_err(backend_error)?
        .ok_or_else(|| recovery_required("external frontier backend has no published frontier"))?;
    frontier
        .validate_structure()
        .map_err(|error| recovery_required(&error.to_string()))?;
    require_authenticated_snapshot(&frontier)?;
    let now = current_time_millis()?;
    if frontier.created_at_unix_ms > now.saturating_add(MAX_FUTURE_CLOCK_SKEW_MS)
        || now.saturating_sub(frontier.created_at_unix_ms) > config.frontier_max_age_ms
    {
        return Err(recovery_required(
            "latest external frontier is outside the configured freshness window",
        ));
    }
    if frontier.frontier_generation < config.minimum_frontier_generation
        || frontier.store_id != config.store_id
        || frontier.source_commit != qualified_source.source_commit
        || frontier.source_tree != qualified_source.source_tree
        || frontier.issuer_trust_registry_sha256 != issuer_trust_sha256
        || frontier.frontier_signer_registry_sha256 != signer_trust_sha256
        || frontier.backend_identity_sha256 != config.backend_identity_sha256
        || frontier.build_artifact_sha256 != build_artifact_sha256
        || frontier.qualification_receipt_sha256 != qualification_receipt_sha256
        || frontier.backup_publication_sha256 != backup_publication_sha256
    {
        return Err(recovery_required(
            "latest external frontier does not match the production identity pins",
        ));
    }
    signer_trust.verify(&frontier)?;
    validate_backup_publication(
        &backup,
        &frontier,
        &build_artifact_sha256,
        now,
        config.frontier_max_age_ms,
    )?;
    verify_backup_object(
        &backup,
        &root,
        identity,
        &[
            signer_trust_file,
            config.exact_source_receipt_file.as_path(),
            config.merge_candidate_receipt_file.as_path(),
            config.backup_publication_receipt_file.as_path(),
        ],
    )?;
    if evidence_recovery_ledger_root_v2(&frontier.snapshot) != frontier.ledger_root_sha256 {
        return Err(recovery_required(
            "signed snapshot does not match its ledger root",
        ));
    }
    let verified_trust = VerifiedEvidenceTrustSnapshot::load_owner_registry(
        store,
        issuer_trust_file,
        identity.agent_id.as_str(),
        Some(&issuer_trust_sha256),
    )
    .map_err(evidence_error)?;
    if !verified_trust.is_monotonic() || verified_trust.registry_generation() == 0 {
        return Err(recovery_required(
            "production issuer trust must use monotonic registry schema V2",
        ));
    }
    store
        .verify_production_qualification_provenance_bounded(
            verified_trust.registry_generation(),
            verified_trust.registry_sha256(),
        )
        .await
        .map_err(evidence_error)?;
    let frontier_sha256 = evidence_recovery_frontier_v2_sha256(&frontier)
        .map_err(|error| recovery_required(&error.to_string()))?;
    let accepted_frontier = EvidenceAcceptedFrontierV1 {
        store_id: frontier.store_id.clone(),
        frontier_generation: frontier.frontier_generation,
        frontier_sha256: frontier_sha256.clone(),
        backend_identity_sha256: frontier.backend_identity_sha256.clone(),
        accepted_at_unix_ms: now,
    };
    let accepted_trust = EvidenceTrustGenerationAcceptanceV1 {
        store_id: frontier.store_id.clone(),
        agent_id: verified_trust.agent_id().to_string(),
        registry_generation: verified_trust.registry_generation(),
        registry_sha256: verified_trust.registry_sha256().clone(),
        predecessor_sha256: verified_trust.predecessor_sha256().cloned(),
        accepted_frontier_generation: frontier.frontier_generation,
        accepted_frontier_sha256: frontier_sha256,
        backend_identity_sha256: frontier.backend_identity_sha256.clone(),
        accepted_at_unix_ms: now,
    };
    // Snapshot comparison, trust rotation and frontier acceptance commit under
    // the SAME BEGIN IMMEDIATE transaction. A failed trust rotation cannot
    // leave a newer frontier accepted, and vice versa.
    store
        .accept_production_generation_at_snapshot(
            &accepted_frontier,
            &frontier.snapshot,
            &accepted_trust,
        )
        .await
        .map_err(evidence_error)?;
    Ok(issuer_trust_sha256)
}

fn require_authenticated_snapshot(
    frontier: &EvidenceRecoveryFrontierV2,
) -> Result<(), AgentdError> {
    if frontier.snapshot.schema_version != 2 {
        return Err(recovery_required(
            "production requires authenticated-admission snapshot V2; legacy envelope-only snapshots cannot be upgraded by relabelling",
        ));
    }
    Ok(())
}

// Same-module extraction preserves the existing private validation surface and
// test visibility. No parser, signature, path, artifact or authority check is
// replaced by the stronger snapshot/trust checks above.
include!("evidence_production_checks.rs");
include!("evidence_publication_driver.rs");

#[cfg(test)]
#[path = "evidence_production_tests.rs"]
mod tests;
