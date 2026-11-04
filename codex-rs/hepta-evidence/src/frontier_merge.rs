use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::EvidenceError;
use crate::EvidenceRecoveryFrontierV2;
use crate::evidence_recovery_frontier_v2_sha256;

pub const FRONTIER_REPAIR_AUTHORIZATION_SCHEMA_VERSION: u32 = 1;
pub const FRONTIER_REPAIR_AUTHORITY_SCHEMA_VERSION: u32 = 1;
pub const FRONTIER_REPAIR_AUTHORIZATION_MAX_VALIDITY_MS: u64 = 24 * 60 * 60 * 1000;

/// Closed-world result of comparing one authenticated recovery frontier with
/// the locally accepted frontier. The decision is deliberately not an
/// `Ordering`: equal generation with different canonical identity is a
/// conflict, never an arbitrary lexical winner.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FrontierMergeDecision {
    ExactDuplicate,
    IncomingStale,
    IncomingWins,
    ConflictSameOrderDifferentIdentity,
    InvalidIncoming,
    InvalidCurrent,
    RepairRequired,
}

/// Classify a proposed recovery frontier before storage or external effects.
///
/// This routine validates structure and canonical identity, requires strict
/// next-generation progression for an automatic win, and rejects every
/// same-generation identity split. Changes to the store/backend/source/build,
/// qualification set, migration set, or issuer trust require an exact signed
/// repair authorization rather than implicit overwrite.
pub fn classify_frontier_merge(
    current: &EvidenceRecoveryFrontierV2,
    incoming: &EvidenceRecoveryFrontierV2,
) -> FrontierMergeDecision {
    if current.validate_structure().is_err() {
        return FrontierMergeDecision::InvalidCurrent;
    }
    if incoming.validate_structure().is_err() {
        return FrontierMergeDecision::InvalidIncoming;
    }
    let current_digest = match evidence_recovery_frontier_v2_sha256(current) {
        Ok(digest) => digest,
        Err(_) => return FrontierMergeDecision::InvalidCurrent,
    };
    let incoming_digest = match evidence_recovery_frontier_v2_sha256(incoming) {
        Ok(digest) => digest,
        Err(_) => return FrontierMergeDecision::InvalidIncoming,
    };
    if current_digest == incoming_digest {
        return FrontierMergeDecision::ExactDuplicate;
    }
    if incoming.frontier_generation == current.frontier_generation {
        return FrontierMergeDecision::ConflictSameOrderDifferentIdentity;
    }
    if incoming.store_id != current.store_id
        || incoming.backend_identity_sha256 != current.backend_identity_sha256
    {
        return FrontierMergeDecision::RepairRequired;
    }
    if incoming.frontier_generation < current.frontier_generation {
        return FrontierMergeDecision::IncomingStale;
    }
    if !is_automatic_successor(current, incoming) {
        return FrontierMergeDecision::RepairRequired;
    }
    FrontierMergeDecision::IncomingWins
}

fn is_automatic_successor(
    current: &EvidenceRecoveryFrontierV2,
    incoming: &EvidenceRecoveryFrontierV2,
) -> bool {
    if current.frontier_generation.checked_add(1) != Some(incoming.frontier_generation)
        || incoming.snapshot.database_lineage != current.snapshot.database_lineage
        || incoming.snapshot.schema_version < current.snapshot.schema_version
        || incoming.snapshot.migration_set_sha256 != current.snapshot.migration_set_sha256
        || incoming.snapshot.qualification_max_seq < current.snapshot.qualification_max_seq
        || incoming.created_at_unix_ms < current.created_at_unix_ms
        || incoming.signer_policy_generation < current.signer_policy_generation
        || incoming.issuer_trust_registry_sha256 != current.issuer_trust_registry_sha256
        || incoming.source_commit != current.source_commit
        || incoming.source_tree != current.source_tree
        || incoming.build_artifact_sha256 != current.build_artifact_sha256
        || incoming.qualification_receipt_sha256 != current.qualification_receipt_sha256
    {
        return false;
    }
    if incoming.snapshot.qualification_max_seq == current.snapshot.qualification_max_seq
        && incoming.snapshot.qualification_frontier_sha256
            != current.snapshot.qualification_frontier_sha256
    {
        return false;
    }
    if incoming.frontier_signer_registry_sha256 != current.frontier_signer_registry_sha256
        && incoming.signer_policy_generation <= current.signer_policy_generation
    {
        return false;
    }
    true
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FrontierRepairReasonV1 {
    BackendMigration,
    StoreRecovery,
    TrustRootRotation,
    SchemaMigration,
    OperatorDisasterRecovery,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FrontierRepairAlgorithmV1 {
    Ed25519,
}

/// Independently retained repair-authority key metadata. A caller cannot make
/// a raw public key authoritative merely by placing it beside a repair request;
/// the key id, epoch and trust-root generation must match this admitted record.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FrontierRepairAuthorityV1 {
    pub schema_version: u32,
    pub authority_key_id: String,
    pub authority_key_epoch: u64,
    pub trust_root_generation: u64,
    pub algorithm: FrontierRepairAlgorithmV1,
    pub public_key_hex: String,
    pub not_before_unix_ms: u64,
    pub not_after_unix_ms: u64,
    pub revoked: bool,
}

/// Exact, one-transition repair authorization. It cannot authorize a class of
/// future overwrites: both canonical frontier digests, both generations, the
/// operator, reason, expiry and nonce are signed.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FrontierRepairAuthorizationV1 {
    pub schema_version: u32,
    pub store_id: String,
    pub current_frontier_sha256: Sha256Digest,
    pub target_frontier_sha256: Sha256Digest,
    pub current_generation: u64,
    pub target_generation: u64,
    pub reason_code: FrontierRepairReasonV1,
    pub operator_principal_id: String,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub nonce_hex: String,
    pub authority_key_id: String,
    pub authority_key_epoch: u64,
    pub authority_algorithm: FrontierRepairAlgorithmV1,
    pub trust_root_generation: u64,
    pub authority_signature_hex: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct UnsignedFrontierRepairAuthorizationV1<'a> {
    schema_version: u32,
    store_id: &'a str,
    current_frontier_sha256: &'a Sha256Digest,
    target_frontier_sha256: &'a Sha256Digest,
    current_generation: u64,
    target_generation: u64,
    reason_code: FrontierRepairReasonV1,
    operator_principal_id: &'a str,
    issued_at_unix_ms: u64,
    expires_at_unix_ms: u64,
    nonce_hex: &'a str,
    authority_key_id: &'a str,
    authority_key_epoch: u64,
    authority_algorithm: FrontierRepairAlgorithmV1,
    trust_root_generation: u64,
}

pub fn frontier_repair_authorization_signing_bytes(
    authorization: &FrontierRepairAuthorizationV1,
) -> Result<Vec<u8>, EvidenceError> {
    validate_authorization_shape(authorization, false)?;
    let unsigned = UnsignedFrontierRepairAuthorizationV1 {
        schema_version: authorization.schema_version,
        store_id: &authorization.store_id,
        current_frontier_sha256: &authorization.current_frontier_sha256,
        target_frontier_sha256: &authorization.target_frontier_sha256,
        current_generation: authorization.current_generation,
        target_generation: authorization.target_generation,
        reason_code: authorization.reason_code,
        operator_principal_id: &authorization.operator_principal_id,
        issued_at_unix_ms: authorization.issued_at_unix_ms,
        expires_at_unix_ms: authorization.expires_at_unix_ms,
        nonce_hex: &authorization.nonce_hex,
        authority_key_id: &authorization.authority_key_id,
        authority_key_epoch: authorization.authority_key_epoch,
        authority_algorithm: authorization.authority_algorithm,
        trust_root_generation: authorization.trust_root_generation,
    };
    let payload = serde_json::to_vec(&unsigned)
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
    let mut bytes = b"hepta.evidence.frontier-repair-authorization.v1\0".to_vec();
    bytes.extend_from_slice(
        &u64::try_from(payload.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(&payload);
    Ok(bytes)
}

/// Verify an authorization against the exact current and target frontiers and
/// an independently admitted authority key. Invalid frontiers and stale or
/// ambiguous transitions remain non-repairable.
pub fn verify_frontier_repair_authorization(
    authorization: &FrontierRepairAuthorizationV1,
    authority: &FrontierRepairAuthorityV1,
    current: &EvidenceRecoveryFrontierV2,
    target: &EvidenceRecoveryFrontierV2,
    now_unix_ms: u64,
) -> Result<(), EvidenceError> {
    validate_authorization_shape(authorization, true)?;
    validate_authority(authority, now_unix_ms)?;
    current.validate_structure()?;
    target.validate_structure()?;

    let current_digest = evidence_recovery_frontier_v2_sha256(current)?;
    let target_digest = evidence_recovery_frontier_v2_sha256(target)?;
    if authorization.store_id != current.store_id
        || authorization.store_id != target.store_id
        || authorization.current_frontier_sha256 != current_digest
        || authorization.target_frontier_sha256 != target_digest
        || authorization.current_generation != current.frontier_generation
        || authorization.target_generation != target.frontier_generation
        || authorization.authority_key_id != authority.authority_key_id
        || authorization.authority_key_epoch != authority.authority_key_epoch
        || authorization.authority_algorithm != authority.algorithm
        || authorization.trust_root_generation != authority.trust_root_generation
    {
        return Err(invalid(
            "frontier repair authorization does not bind the exact transition and authority",
        ));
    }
    if now_unix_ms < authorization.issued_at_unix_ms
        || now_unix_ms > authorization.expires_at_unix_ms
    {
        return Err(invalid("frontier repair authorization is not currently valid"));
    }
    match classify_frontier_merge(current, target) {
        FrontierMergeDecision::IncomingWins | FrontierMergeDecision::RepairRequired => {}
        FrontierMergeDecision::ExactDuplicate
        | FrontierMergeDecision::IncomingStale
        | FrontierMergeDecision::ConflictSameOrderDifferentIdentity
        | FrontierMergeDecision::InvalidIncoming
        | FrontierMergeDecision::InvalidCurrent => {
            return Err(invalid(
                "frontier repair authorization cannot admit this transition class",
            ));
        }
    }

    let public_key = decode_hex_array::<32>(&authority.public_key_hex, "repair public key")?;
    let signature = decode_hex_array::<64>(
        &authorization.authority_signature_hex,
        "repair authorization signature",
    )?;
    let verifying_key = VerifyingKey::from_bytes(&public_key)
        .map_err(|_| invalid("repair authority public key is invalid"))?;
    verifying_key
        .verify_strict(
            &frontier_repair_authorization_signing_bytes(authorization)?,
            &Signature::from_bytes(&signature),
        )
        .map_err(|_| invalid("frontier repair authorization signature is invalid"))?;
    Ok(())
}

fn validate_authorization_shape(
    authorization: &FrontierRepairAuthorizationV1,
    require_signature: bool,
) -> Result<(), EvidenceError> {
    if authorization.schema_version != FRONTIER_REPAIR_AUTHORIZATION_SCHEMA_VERSION
        || authorization.current_generation == 0
        || authorization.target_generation <= authorization.current_generation
        || authorization.issued_at_unix_ms == 0
        || authorization.expires_at_unix_ms <= authorization.issued_at_unix_ms
        || authorization
            .expires_at_unix_ms
            .saturating_sub(authorization.issued_at_unix_ms)
            > FRONTIER_REPAIR_AUTHORIZATION_MAX_VALIDITY_MS
        || authorization.authority_key_epoch == 0
        || authorization.trust_root_generation == 0
    {
        return Err(invalid("frontier repair authorization metadata is invalid"));
    }
    StableId::new(authorization.store_id.clone())
        .map_err(|error| invalid(format!("invalid repair store id: {error}")))?;
    StableId::new(authorization.operator_principal_id.clone())
        .map_err(|error| invalid(format!("invalid repair operator id: {error}")))?;
    StableId::new(authorization.authority_key_id.clone())
        .map_err(|error| invalid(format!("invalid repair authority key id: {error}")))?;
    decode_hex_array::<32>(&authorization.nonce_hex, "repair nonce")?;
    if require_signature {
        decode_hex_array::<64>(
            &authorization.authority_signature_hex,
            "repair authorization signature",
        )?;
    } else if !authorization.authority_signature_hex.is_empty()
        && authorization.authority_signature_hex.len() != 128
    {
        return Err(invalid("repair authorization signature has invalid length"));
    }
    Ok(())
}

fn validate_authority(
    authority: &FrontierRepairAuthorityV1,
    now_unix_ms: u64,
) -> Result<(), EvidenceError> {
    if authority.schema_version != FRONTIER_REPAIR_AUTHORITY_SCHEMA_VERSION
        || authority.authority_key_epoch == 0
        || authority.trust_root_generation == 0
        || authority.not_before_unix_ms == 0
        || authority.not_after_unix_ms <= authority.not_before_unix_ms
        || authority.revoked
        || now_unix_ms < authority.not_before_unix_ms
        || now_unix_ms > authority.not_after_unix_ms
    {
        return Err(invalid("frontier repair authority is unavailable or revoked"));
    }
    StableId::new(authority.authority_key_id.clone())
        .map_err(|error| invalid(format!("invalid repair authority key id: {error}")))?;
    decode_hex_array::<32>(&authority.public_key_hex, "repair public key")?;
    Ok(())
}

fn decode_hex_array<const N: usize>(value: &str, label: &str) -> Result<[u8; N], EvidenceError> {
    if value.len() != N.saturating_mul(2) {
        return Err(invalid(format!("{label} has invalid length")));
    }
    let bytes = value.as_bytes();
    let mut decoded = [0_u8; N];
    for index in 0..N {
        let high = decode_nibble(bytes[index * 2])
            .ok_or_else(|| invalid(format!("{label} is not lowercase hexadecimal")))?;
        let low = decode_nibble(bytes[index * 2 + 1])
            .ok_or_else(|| invalid(format!("{label} is not lowercase hexadecimal")))?;
        decoded[index] = (high << 4) | low;
    }
    Ok(decoded)
}

fn decode_nibble(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        _ => None,
    }
}

fn invalid(message: impl Into<String>) -> EvidenceError {
    EvidenceError::InvalidRecord(message.into())
}

#[cfg(test)]
#[path = "frontier_merge_tests.rs"]
mod tests;
