//! Independent host/observer cross-attestation of four original CellSplit effects.
//!
//! Four independently signed owner receipts and a separately signed target
//! host lifecycle report can each be valid but describe different splits.
//! This verification-only join requires the host and an independent observer
//! to sign exactly the same pairing, then reads all four real owners again.
//!
//! A joined proof does NOT convey NDU/Selector final-use, a global atomic
//! snapshot, production activation, physical split or performance acceptance.
//! The caller must still enforce those independent gates.

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD as BASE64;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::CellSplitExecutionPortV1;
use crate::CellSplitExecutionTranscriptV1;
use crate::CellSplitOwnerTrustV1;
use crate::CellSplitSignedTargetHostEvidenceV1;
use crate::CellSplitTargetHostEventKindV1;
use crate::CellSplitTargetHostEvidenceTrustPolicyV1;
use crate::CellSplitTargetHostSignatureV1;
use crate::durable::canonical_json;
use crate::durable::sha256;
use crate::verify_cell_split_execution_transcript_signatures_v1;
use crate::verify_cell_split_target_host_evidence;

pub const CELL_SPLIT_OBSERVER_JOIN_SCHEMA_V1: &str =
    "hepta.learning.cell-split.observer-effect-join.v1";

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitObserverJoinPayloadV1 {
    pub schema: String,
    pub split_id: String,
    pub target_host_id: String,
    pub scope_digest: String,
    pub parent_generation: u64,
    pub child_generation: u64,
    pub parent_artifact_digest: String,
    pub child_artifact_digest: String,
    pub ndu_snapshot_digest: String,
    pub route_fence_digest: String,
    pub plan_digest: String,
    pub transcript_digest: String,
    pub target_host_evidence_digest: String,
    /// Four original signed coordinator receipts in CAS, migration, CNS,
    /// Supervisor order. These are never self-asserted operation hashes.
    pub owner_receipt_digests: [String; 4],
    /// Exact host event records independently signed in its lifecycle chain.
    pub host_artifact_event_digest: String,
    pub host_route_cutover_event_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitSignedObserverJoinV1 {
    pub schema: String,
    pub payload: CellSplitObserverJoinPayloadV1,
    pub host_signature: CellSplitTargetHostSignatureV1,
    pub observer_signature: CellSplitTargetHostSignatureV1,
}

/// A read-only join verdict; never a production or final-use grant.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitObserverJoinReceiptV1 {
    pub schema: String,
    pub split_id: String,
    pub target_host_id: String,
    pub transcript_digest: String,
    pub target_host_evidence_digest: String,
    pub joined_payload_digest: String,
    pub four_current_owner_readbacks: bool,
    pub independently_signed_host_and_observer: bool,
    pub production_activation_authorized: bool,
}

#[derive(Debug, Error)]
pub enum CellSplitObserverJoinErrorV1 {
    #[error("CellSplit observer join rejected: {0}")]
    Invalid(&'static str),
    #[error("CellSplit observer join original owner unavailable: {0}")]
    Owner(String),
    #[error("CellSplit observer join encoding failed: {0}")]
    Encoding(#[from] serde_json::Error),
    #[error("CellSplit observer join canonical evidence failed: {0}")]
    Canonical(#[from] crate::AcceptanceError),
}

/// Pure builder for a *candidate* pair of existing signed envelopes. No
/// signature, remote read, authority or production receipt is issued here.
pub fn cell_split_observer_join_payload_v1(
    transcript: &CellSplitExecutionTranscriptV1,
    evidence: &CellSplitSignedTargetHostEvidenceV1,
) -> Result<CellSplitObserverJoinPayloadV1, CellSplitObserverJoinErrorV1> {
    let plan = &transcript.plan;
    let target = &evidence.payload;
    if transcript.receipts.len() != 4
        || plan.split_id != target.split_id
        || plan.parent_generation != target.parent_generation
        || plan.child_generation != target.child_generation
        || plan.parent_artifact_digest != target.parent_artifact_digest
        || plan.child_artifact_digest != target.child_artifact_digest
    {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "host and four-owner identities do not agree",
        ));
    }
    let artifact_event = target.events.iter().find(|event| {
        event.event_kind == CellSplitTargetHostEventKindV1::ArtifactLoaded
    }).ok_or(CellSplitObserverJoinErrorV1::Invalid("missing artifact event"))?;
    let route_event = target.events.iter().find(|event| {
        event.event_kind == CellSplitTargetHostEventKindV1::RouteCutover
    }).ok_or(CellSplitObserverJoinErrorV1::Invalid("missing cutover event"))?;
    Ok(CellSplitObserverJoinPayloadV1 {
        schema: CELL_SPLIT_OBSERVER_JOIN_SCHEMA_V1.into(),
        split_id: plan.split_id.clone(),
        target_host_id: target.target_host_id.clone(),
        scope_digest: plan.scope_digest.clone(),
        parent_generation: plan.parent_generation,
        child_generation: plan.child_generation,
        parent_artifact_digest: plan.parent_artifact_digest.clone(),
        child_artifact_digest: plan.child_artifact_digest.clone(),
        ndu_snapshot_digest: plan.ndu_snapshot_digest.clone(),
        route_fence_digest: plan.route_fence_digest.clone(),
        plan_digest: plan.digest().map_err(|_| {
            CellSplitObserverJoinErrorV1::Invalid("invalid frozen execution plan")
        })?,
        transcript_digest: transcript.transcript_digest.clone(),
        target_host_evidence_digest: target.evidence_digest.clone(),
        owner_receipt_digests: std::array::from_fn(|index| {
            transcript.receipts[index].receipt_digest.clone()
        }),
        host_artifact_event_digest: artifact_event.event_digest.clone(),
        host_route_cutover_event_digest: route_event.event_digest.clone(),
    })
}

/// Domain-separated bytes signed independently by the real host and observer.
/// This builder accepts no signing key or self-asserted authorization.
pub fn cell_split_observer_join_signing_payload_v1(
    payload: &CellSplitObserverJoinPayloadV1,
) -> Result<Vec<u8>, CellSplitObserverJoinErrorV1> {
    let mut bytes = b"hepta.learning.cell-split.observer-effect-join.v1\0".to_vec();
    bytes.extend_from_slice(&canonical_json(payload)?);
    Ok(bytes)
}

fn verify_join_signature(
    signature: &CellSplitTargetHostSignatureV1,
    trusted_key: &VerifyingKey,
    message: &[u8],
) -> Result<(), CellSplitObserverJoinErrorV1> {
    if trusted_key.is_weak()
        || BASE64.decode(&signature.verifying_key_base64)
            .map_err(|_| CellSplitObserverJoinErrorV1::Invalid("unreadable signer key"))?
            != trusted_key.to_bytes()
    {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "join signer is not independently trusted",
        ));
    }
    let raw = BASE64.decode(&signature.signature_base64)
        .map_err(|_| CellSplitObserverJoinErrorV1::Invalid("invalid join signature"))?;
    let signature = Signature::from_slice(&raw)
        .map_err(|_| CellSplitObserverJoinErrorV1::Invalid("malformed join signature"))?;
    trusted_key.verify_strict(message, &signature)
        .map_err(|_| CellSplitObserverJoinErrorV1::Invalid("untrusted join signature"))
}

/// Requires full offline signature validation, host + observer signed binding,
/// and then independent fresh current-owner verification of every effect.
/// This API never prepares, executes or reconciles a CellSplit operation.
///
/// Even a successful result is NOT a global atomic snapshot or permission to
/// promote: the actual final-use gate must revalidate all current authorities.
pub fn verify_cell_split_observer_join_v1<P: CellSplitExecutionPortV1>(
    join: &CellSplitSignedObserverJoinV1,
    transcript: &CellSplitExecutionTranscriptV1,
    owner_trust: &CellSplitOwnerTrustV1,
    evidence: &CellSplitSignedTargetHostEvidenceV1,
    evidence_policy: &CellSplitTargetHostEvidenceTrustPolicyV1,
    live_owners: &mut P,
) -> Result<CellSplitObserverJoinReceiptV1, CellSplitObserverJoinErrorV1> {
    verify_cell_split_execution_transcript_signatures_v1(transcript, owner_trust)
        .map_err(|_| CellSplitObserverJoinErrorV1::Invalid(
            "four original owner signatures or predecessor chain failed",
        ))?;
    let host_receipt = verify_cell_split_target_host_evidence(evidence, evidence_policy)
        .map_err(|_| CellSplitObserverJoinErrorV1::Invalid(
            "target-host signatures, observer or lifecycle replay failed",
        ))?;
    if !host_receipt.production_gate_passed
        || join.schema != CELL_SPLIT_OBSERVER_JOIN_SCHEMA_V1
        || join.payload != cell_split_observer_join_payload_v1(transcript, evidence)?
    {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "unsigned or mismatched four-owner host evidence binding",
        ));
    }
    let host_id = &evidence.host_signature.signer_id;
    let observer_id = &join.observer_signature.signer_id;
    let host_key = evidence_policy.host_keys.get(host_id)
        .ok_or(CellSplitObserverJoinErrorV1::Invalid("host trust root missing"))?;
    let observer_key = evidence_policy.observer_keys.get(observer_id)
        .ok_or(CellSplitObserverJoinErrorV1::Invalid("observer trust root missing"))?;
    if join.host_signature.signer_id != *host_id
        || !evidence.observer_signatures.iter().any(|record| {
            record.signer_id == *observer_id
        })
        || join.observer_signature.signer_id == *host_id
        || host_key == observer_key
        || owner_trust.contains_owner_key(host_key)
        || owner_trust.contains_owner_key(observer_key)
    {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "host, observer and effect-owner signers must be independent",
        ));
    }
    let message = cell_split_observer_join_signing_payload_v1(&join.payload)?;
    verify_join_signature(&join.host_signature, host_key, &message)?;
    verify_join_signature(&join.observer_signature, observer_key, &message)?;
    // Never accept a signed join to a former owner state. A real production
    // caller supplies the pinned Unix RPC owner port, not a mock.
    for receipt in &transcript.receipts {
        live_owners.verify_committed(&receipt.intent, receipt)
            .map_err(|e| CellSplitObserverJoinErrorV1::Owner(e.to_string()))?;
    }
    Ok(CellSplitObserverJoinReceiptV1 {
        schema: CELL_SPLIT_OBSERVER_JOIN_SCHEMA_V1.into(),
        split_id: join.payload.split_id.clone(),
        target_host_id: join.payload.target_host_id.clone(),
        transcript_digest: join.payload.transcript_digest.clone(),
        target_host_evidence_digest: join.payload.target_host_evidence_digest.clone(),
        joined_payload_digest: sha256(&canonical_json(&join.payload)?),
        four_current_owner_readbacks: true,
        independently_signed_host_and_observer: true,
        production_activation_authorized: false,
    })
}
