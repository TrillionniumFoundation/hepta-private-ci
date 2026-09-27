use std::collections::BTreeSet;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::EVIDENCE_DATABASE_LINEAGE;
use crate::EvidenceError;
use crate::EvidenceRecoverySnapshotV1;

pub const EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION: u32 = 2;
pub const EVIDENCE_RECOVERY_FRONTIER_V2_MAX_SIGNATURES: usize = 8;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceRecoveryFrontierSignatureV2 {
    pub signer_principal_id: String,
    pub signer_key_epoch: u64,
    pub signature_hex: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceRecoveryFrontierV2 {
    pub schema_version: u32,
    pub store_id: String,
    pub frontier_generation: u64,
    pub snapshot: EvidenceRecoverySnapshotV1,
    pub ledger_root_sha256: Sha256Digest,
    pub issuer_trust_registry_sha256: Sha256Digest,
    pub frontier_signer_registry_sha256: Sha256Digest,
    pub backend_identity_sha256: Sha256Digest,
    pub build_artifact_sha256: Sha256Digest,
    pub qualification_receipt_sha256: Sha256Digest,
    pub backup_publication_sha256: Sha256Digest,
    pub source_commit: String,
    pub source_tree: String,
    pub created_at_unix_ms: u64,
    pub signer_policy_generation: u64,
    pub signatures: Vec<EvidenceRecoveryFrontierSignatureV2>,
}

impl EvidenceRecoveryFrontierV2 {
    pub fn validate_structure(&self) -> Result<(), EvidenceError> {
        if self.schema_version != EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION {
            return Err(invalid("unsupported evidence recovery frontier v2 schema"));
        }
        StableId::new(self.store_id.clone())
            .map_err(|error| invalid(format!("invalid recovery store id: {error}")))?;
        if self.frontier_generation == 0 {
            return Err(invalid("frontier generation must be positive"));
        }
        if self.snapshot.schema_version != 1
            || self.snapshot.database_lineage != EVIDENCE_DATABASE_LINEAGE
        {
            return Err(invalid("frontier snapshot lineage is not supported"));
        }
        for (label, digest) in [
            ("snapshot migration set", &self.snapshot.migration_set_sha256),
            (
                "snapshot qualification frontier",
                &self.snapshot.qualification_frontier_sha256,
            ),
            (
                "snapshot replay frontier",
                &self.snapshot.authbus_replay_frontier_sha256,
            ),
            ("ledger root", &self.ledger_root_sha256),
            ("issuer trust registry", &self.issuer_trust_registry_sha256),
            (
                "frontier signer registry",
                &self.frontier_signer_registry_sha256,
            ),
            ("backend identity", &self.backend_identity_sha256),
            ("build artifact", &self.build_artifact_sha256),
            (
                "qualification receipt set",
                &self.qualification_receipt_sha256,
            ),
            ("backup publication", &self.backup_publication_sha256),
        ] {
            if !valid_sha256(digest) {
                return Err(invalid(format!(
                    "frontier {label} digest is not canonical lowercase SHA-256"
                )));
            }
        }
        if self.ledger_root_sha256 != evidence_recovery_ledger_root_v2(&self.snapshot) {
            return Err(invalid("frontier ledger root does not match the snapshot"));
        }
        if !valid_git_id(&self.source_commit) || !valid_git_id(&self.source_tree) {
            return Err(invalid("frontier source identity is not canonical git hex"));
        }
        if self.created_at_unix_ms == 0 || self.signer_policy_generation == 0 {
            return Err(invalid(
                "frontier creation time and signer policy generation must be positive",
            ));
        }
        if self.signatures.is_empty()
            || self.signatures.len() > EVIDENCE_RECOVERY_FRONTIER_V2_MAX_SIGNATURES
        {
            return Err(invalid("frontier signature count is outside the bounded policy"));
        }

        let mut seen = BTreeSet::new();
        let mut previous: Option<(&str, u64)> = None;
        for signature in &self.signatures {
            StableId::new(signature.signer_principal_id.clone()).map_err(|error| {
                invalid(format!("invalid recovery signer principal id: {error}"))
            })?;
            if signature.signer_key_epoch == 0
                || signature.signature_hex.len() != 128
                || !signature
                    .signature_hex
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            {
                return Err(invalid("frontier contains an invalid signer binding"));
            }
            let current = (
                signature.signer_principal_id.as_str(),
                signature.signer_key_epoch,
            );
            if previous.is_some_and(|previous| previous >= current)
                || !seen.insert((
                    signature.signer_principal_id.clone(),
                    signature.signer_key_epoch,
                ))
            {
                return Err(invalid(
                    "frontier signatures must be unique and canonically ordered",
                ));
            }
            previous = Some(current);
        }
        Ok(())
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct UnsignedEvidenceRecoveryFrontierV2<'a> {
    schema_version: u32,
    store_id: &'a str,
    frontier_generation: u64,
    snapshot: &'a EvidenceRecoverySnapshotV1,
    ledger_root_sha256: &'a Sha256Digest,
    issuer_trust_registry_sha256: &'a Sha256Digest,
    frontier_signer_registry_sha256: &'a Sha256Digest,
    backend_identity_sha256: &'a Sha256Digest,
    build_artifact_sha256: &'a Sha256Digest,
    qualification_receipt_sha256: &'a Sha256Digest,
    backup_publication_sha256: &'a Sha256Digest,
    source_commit: &'a str,
    source_tree: &'a str,
    created_at_unix_ms: u64,
    signer_policy_generation: u64,
}

pub fn evidence_recovery_frontier_v2_signing_bytes(
    frontier: &EvidenceRecoveryFrontierV2,
) -> Result<Vec<u8>, EvidenceError> {
    frontier.validate_structure()?;
    let unsigned = UnsignedEvidenceRecoveryFrontierV2 {
        schema_version: frontier.schema_version,
        store_id: &frontier.store_id,
        frontier_generation: frontier.frontier_generation,
        snapshot: &frontier.snapshot,
        ledger_root_sha256: &frontier.ledger_root_sha256,
        issuer_trust_registry_sha256: &frontier.issuer_trust_registry_sha256,
        frontier_signer_registry_sha256: &frontier.frontier_signer_registry_sha256,
        backend_identity_sha256: &frontier.backend_identity_sha256,
        build_artifact_sha256: &frontier.build_artifact_sha256,
        qualification_receipt_sha256: &frontier.qualification_receipt_sha256,
        backup_publication_sha256: &frontier.backup_publication_sha256,
        source_commit: &frontier.source_commit,
        source_tree: &frontier.source_tree,
        created_at_unix_ms: frontier.created_at_unix_ms,
        signer_policy_generation: frontier.signer_policy_generation,
    };
    let payload = serde_json::to_vec(&unsigned)
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
    let mut bytes = b"hepta.evidence.recovery-frontier.v2\0".to_vec();
    push_part(&mut bytes, &payload);
    Ok(bytes)
}

pub fn evidence_recovery_frontier_v2_sha256(
    frontier: &EvidenceRecoveryFrontierV2,
) -> Result<Sha256Digest, EvidenceError> {
    frontier.validate_structure()?;
    let bytes = serde_json::to_vec(frontier)
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

pub fn evidence_recovery_ledger_root_v2(
    snapshot: &EvidenceRecoverySnapshotV1,
) -> Sha256Digest {
    let mut bytes = b"hepta.evidence.recovery-ledger-root.v2\0".to_vec();
    bytes.extend_from_slice(&snapshot.schema_version.to_be_bytes());
    push_part(&mut bytes, snapshot.database_lineage.as_bytes());
    push_part(
        &mut bytes,
        snapshot.migration_set_sha256.as_str().as_bytes(),
    );
    bytes.extend_from_slice(&snapshot.qualification_max_seq.to_be_bytes());
    push_part(
        &mut bytes,
        snapshot
            .qualification_frontier_sha256
            .as_str()
            .as_bytes(),
    );
    push_part(
        &mut bytes,
        snapshot
            .authbus_replay_frontier_sha256
            .as_str()
            .as_bytes(),
    );
    Sha256Digest::for_bytes(&bytes)
}

fn valid_sha256(value: &Sha256Digest) -> bool {
    value.as_str().len() == 64
        && value
            .as_str()
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn valid_git_id(value: &str) -> bool {
    matches!(value.len(), 40 | 64)
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn push_part(target: &mut Vec<u8>, part: &[u8]) {
    target.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    target.extend_from_slice(part);
}

fn invalid(message: impl Into<String>) -> EvidenceError {
    EvidenceError::InvalidRecord(message.into())
}

#[cfg(test)]
#[path = "frontier_v2_tests.rs"]
mod tests;
