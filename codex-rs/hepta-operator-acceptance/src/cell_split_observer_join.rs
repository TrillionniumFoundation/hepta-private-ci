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

#[cfg(unix)]
use crate::CellSplitCnsRuntimeAttestationV1;
#[cfg(unix)]
use crate::CellSplitCnsRuntimeCommitV1;
#[cfg(unix)]
use crate::CellSplitSupervisorCommitV1;
use crate::CellSplitExecutionPortV1;
#[cfg(unix)]
use crate::CellSplitUnixEffectPortV1;
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

/// Independently provisioned original runtime keys. These MUST differ from
/// all outer four-owner keys, host signers, and Observer signers.
#[cfg(unix)]
pub struct CellSplitObserverOriginalRuntimeTrustV1<'a> {
    pub cns_original_runtime_key: &'a VerifyingKey,
    pub supervisor_original_journal_key: &'a VerifyingKey,
    /// An independently retained minimum terminal journal checkpoint digest.
    /// The signer key alone cannot prevent restoration of an older valid file.
    pub supervisor_minimum_checkpoint_digest: &'a str,
    /// Signed independently by a policy-pinned Observer after checking its
    /// own durable minimum checkpoint source. A caller-provided digest alone
    /// cannot certify anti-rollback. This signature is NOT a production grant.
    pub supervisor_minimum_observer_signature: &'a CellSplitTargetHostSignatureV1,
}

/// Additional read-only proof that the original CNS runtime and Supervisor
/// journal records are independently signed and agree with the host events.
/// Neither this record nor the ordinary Observer join is a final-use grant.
#[cfg(unix)]
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitObserverDeepReceiptV1 {
    pub join: CellSplitObserverJoinReceiptV1,
    pub original_cns_runtime_digest: String,
    pub original_supervisor_journal_digest: String,
    pub independently_signed_original_runtime_and_journal: bool,
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

    // A shared split ID and a correctly signed pair are insufficient: both
    // host lifecycle events must identify the exact independently signed
    // operations that the four-effect coordinator actually committed. Without
    // these equalities two unrelated, individually valid histories could be
    // jointly notarized and incorrectly treated as one execution.
    let original_artifact = &transcript.receipts[0];
    let original_cns = &transcript.receipts[2];
    if artifact_event.operation_id != original_artifact.intent.idempotency_key
        || artifact_event.receipt_digest != original_artifact.receipt_digest
        || route_event.operation_id != original_cns.intent.idempotency_key
        || route_event.receipt_digest != original_cns.receipt_digest
        || artifact_event.sequence >= route_event.sequence
    {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "host lifecycle is not bound to original Artifact CAS and CNS owner receipts",
        ));
    }
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

/// Domain-separated data for the independent Observer's *retained minimum*
/// checkpoint attestation. It binds the exact signed host execution, frozen
/// split plan, original Supervisor revision/authority epoch and checkpoint
/// digest. Creating these bytes does not authorize the caller to sign them:
/// the real Observer must first consult its separate monotonic witness store.
#[cfg(unix)]
pub fn cell_split_supervisor_minimum_signing_payload_v1(
    plan: &crate::CellSplitExecutionPlanV1,
    evidence: &CellSplitSignedTargetHostEvidenceV1,
    journal: &CellSplitSupervisorCommitV1,
    minimum_checkpoint_digest: &str,
) -> Result<Vec<u8>, CellSplitObserverJoinErrorV1> {
    let _ = decode_supervisor_digest_v1(minimum_checkpoint_digest)?;
    if evidence.payload.split_id != plan.split_id
        || evidence.payload.parent_generation != plan.parent_generation
        || evidence.payload.child_generation != plan.child_generation
        || journal.old_generation != plan.parent_generation
        || journal.new_generation != plan.child_generation
        || journal.idempotency_key.is_empty()
        || journal.domain_id.is_empty()
        || journal.authority_epoch == 0
        || journal.committed_revision == 0
        || evidence.payload.target_host_nonce.is_empty()
    {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "minimum checkpoint witness is not bound to the frozen host execution",
        ));
    }
    let plan_digest = plan.digest().map_err(|_| {
        CellSplitObserverJoinErrorV1::Invalid("invalid minimum checkpoint plan")
    })?;
    let mut payload = b"hepta.learning.cell-split.supervisor-minimum-observer.v1\0".to_vec();
    payload.extend_from_slice(&canonical_json(&(
        plan_digest,
        &evidence.payload.target_host_id,
        &evidence.payload.target_host_nonce,
        &evidence.payload.target_host_attestation_digest,
        &evidence.payload.evidence_digest,
        &journal.domain_id,
        &journal.idempotency_key,
        journal.authority_epoch,
        journal.committed_revision,
        sha256(&journal.original_checkpoint_bytes),
        minimum_checkpoint_digest,
    ))?);
    Ok(payload)
}

fn verify_join_signature(
    signature: &CellSplitTargetHostSignatureV1,
    trusted_key: &VerifyingKey,
    message: &[u8],
) -> Result<(), CellSplitObserverJoinErrorV1> {
    if trusted_key.is_weak()
        || BASE64.decode(&signature.verifying_key_base64)
            .map_err(|_| CellSplitObserverJoinErrorV1::Invalid("unreadable signer key"))?
            != trusted_key.to_bytes().to_vec()
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
/// Public production-facing verifier. It cannot be given an allow-all
/// implementation of CellSplitExecutionPortV1. Socket owner keys must match
/// the frozen four original signature keys exactly, so caller-selected
/// readback signers cannot launder stale effect receipts.
#[cfg(unix)]
pub fn verify_cell_split_observer_join_v1(
    join: &CellSplitSignedObserverJoinV1,
    transcript: &CellSplitExecutionTranscriptV1,
    owner_trust: &CellSplitOwnerTrustV1,
    evidence: &CellSplitSignedTargetHostEvidenceV1,
    evidence_policy: &CellSplitTargetHostEvidenceTrustPolicyV1,
    live_owners: &mut CellSplitUnixEffectPortV1,
) -> Result<CellSplitObserverJoinReceiptV1, CellSplitObserverJoinErrorV1> {
    if !live_owners.uses_exact_owner_keys(owner_trust.owner_verifying_keys()) {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "live RPC trust pins differ from four original effect owners",
        ));
    }
    verify_cell_split_observer_join_with_port_v1(
        join, transcript, owner_trust, evidence, evidence_policy, live_owners,
    )
}

/// Crate-only generic verification permits deterministic failure injection in
/// tests but cannot mint a production-facing readback via a fake port.
pub(crate) fn verify_cell_split_observer_join_with_port_v1<P: CellSplitExecutionPortV1>(
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


/// Strict production-facing read-only verifier: besides the four original
/// outer signatures, check the independently pinned *inner* CNS and Supervisor
/// signatures. The trusted runtime signer is never learned from host evidence.
#[cfg(unix)]
#[allow(clippy::too_many_arguments)]
pub fn verify_cell_split_observer_join_deep_v1(
    join: &CellSplitSignedObserverJoinV1,
    transcript: &CellSplitExecutionTranscriptV1,
    owner_trust: &CellSplitOwnerTrustV1,
    evidence: &CellSplitSignedTargetHostEvidenceV1,
    evidence_policy: &CellSplitTargetHostEvidenceTrustPolicyV1,
    original_runtime_trust: &CellSplitObserverOriginalRuntimeTrustV1<'_>,
    live_owners: &mut CellSplitUnixEffectPortV1,
) -> Result<CellSplitObserverDeepReceiptV1, CellSplitObserverJoinErrorV1> {
    if !live_owners.uses_exact_owner_keys(owner_trust.owner_verifying_keys()) {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "live RPC trust pins differ from four original effect owners",
        ));
    }
    verify_cell_split_observer_join_deep_with_port_v1(
        join,
        transcript,
        owner_trust,
        evidence,
        evidence_policy,
        original_runtime_trust,
        live_owners,
    )
}

/// Testable pure checker around injected read-only ports. Only the pinned
/// Unix-socket wrapper above is production-facing.
#[cfg(unix)]
#[allow(clippy::too_many_arguments)]
pub(crate) fn verify_cell_split_observer_join_deep_with_port_v1<P: CellSplitExecutionPortV1>(
    join: &CellSplitSignedObserverJoinV1,
    transcript: &CellSplitExecutionTranscriptV1,
    owner_trust: &CellSplitOwnerTrustV1,
    evidence: &CellSplitSignedTargetHostEvidenceV1,
    evidence_policy: &CellSplitTargetHostEvidenceTrustPolicyV1,
    original_runtime_trust: &CellSplitObserverOriginalRuntimeTrustV1<'_>,
    live_owners: &mut P,
) -> Result<CellSplitObserverDeepReceiptV1, CellSplitObserverJoinErrorV1> {
    let originals = verify_original_runtime_receipts_v1(
        transcript,
        owner_trust,
        evidence,
        evidence_policy,
        original_runtime_trust,
    )?;
    let join_receipt = verify_cell_split_observer_join_with_port_v1(
        join,
        transcript,
        owner_trust,
        evidence,
        evidence_policy,
        live_owners,
    )?;
    Ok(CellSplitObserverDeepReceiptV1 {
        join: join_receipt,
        original_cns_runtime_digest: originals.0,
        original_supervisor_journal_digest: originals.1,
        independently_signed_original_runtime_and_journal: true,
        production_activation_authorized: false,
    })
}

#[cfg(unix)]
fn verify_original_runtime_receipts_v1(
    transcript: &CellSplitExecutionTranscriptV1,
    owner_trust: &CellSplitOwnerTrustV1,
    evidence: &CellSplitSignedTargetHostEvidenceV1,
    evidence_policy: &CellSplitTargetHostEvidenceTrustPolicyV1,
    runtime_trust: &CellSplitObserverOriginalRuntimeTrustV1<'_>,
) -> Result<(String, String), CellSplitObserverJoinErrorV1> {
    verify_cell_split_execution_transcript_signatures_v1(transcript, owner_trust)
        .map_err(|_| CellSplitObserverJoinErrorV1::Invalid(
            "original owner transcript signature or lineage failed",
        ))?;
    verify_cell_split_target_host_evidence(evidence, evidence_policy)
        .map_err(|_| CellSplitObserverJoinErrorV1::Invalid(
            "signed original host lifecycle failed verification",
        ))?;
    let cns_key = runtime_trust.cns_original_runtime_key;
    let supervisor_key = runtime_trust.supervisor_original_journal_key;
    if cns_key.is_weak()
        || supervisor_key.is_weak()
        || cns_key == supervisor_key
        || owner_trust.contains_owner_key(cns_key)
        || owner_trust.contains_owner_key(supervisor_key)
        || evidence_policy.host_keys.values().any(|key| key == cns_key || key == supervisor_key)
        || evidence_policy.observer_keys.values().any(|key| key == cns_key || key == supervisor_key)
    {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "original runtime keys are not independent from owners and Observer",
        ));
    }

    let cns = &transcript.receipts[2];
    let original_cns: CellSplitCnsRuntimeCommitV1 =
        serde_json::from_slice(&cns.owner_receipt_bytes)?;
    let plan = &transcript.plan;
    let host_route = evidence.payload.events.iter()
        .find(|event| event.event_kind == CellSplitTargetHostEventKindV1::RouteCutover)
        .ok_or(CellSplitObserverJoinErrorV1::Invalid("missing host cutover event"))?;
    if original_cns.idempotency_key != cns.intent.idempotency_key
        || original_cns.committed_sequence != cns.owner_sequence
        || original_cns.predecessor_route_digest != host_route.predecessor_digest
        || original_cns.successor_route_digest != host_route.route_digest
        || original_cns.original_runtime_receipt_bytes.is_empty()
        || original_cns.original_runtime_receipt_bytes.len() > 32 * 1024
    {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "original CNS runtime cutover differs from host and owner receipt",
        ));
    }
    CellSplitCnsRuntimeAttestationV1::verify_original_bytes(plan, &original_cns)
        .map_err(CellSplitObserverJoinErrorV1::Invalid)?;
    verify_pinned_signature(
        cns_key,
        &original_cns.original_runtime_receipt_bytes,
        &original_cns.original_runtime_signature_bytes,
        "independent original CNS runtime signature is invalid",
    )?;

    let supervisor = &transcript.receipts[3];
    let journal: CellSplitSupervisorCommitV1 =
        serde_json::from_slice(&supervisor.owner_receipt_bytes)?;
    // Independently valid CNS and Supervisor signatures cannot be combined
    // across two different authority epochs. A successful finalization is
    // part of the SAME original routing handoff, not merely the same model
    // generations or split identifier.
    verify_original_handoff_epoch_v1(&original_cns, &journal)?;
    if journal.idempotency_key != supervisor.intent.idempotency_key
        || journal.committed_revision != supervisor.owner_sequence
        || journal.old_generation != plan.parent_generation
        || journal.new_generation != plan.child_generation
        || journal.original_checkpoint_bytes.is_empty()
        || journal.original_checkpoint_bytes.len() > 32 * 1024
    {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "original Supervisor receipt differs from frozen split",
        ));
    }
    // The Supervisor original signer domain-separates the durable handoff
    // checkpoint from ordinary RPC or join signatures.
    let mut payload = b"hepta.supervisor.cell-split.original-journal.v1\0".to_vec();
    payload.extend_from_slice(&(journal.idempotency_key.len() as u64).to_be_bytes());
    payload.extend_from_slice(journal.idempotency_key.as_bytes());
    payload.extend_from_slice(&(journal.original_checkpoint_bytes.len() as u64).to_be_bytes());
    payload.extend_from_slice(&journal.original_checkpoint_bytes);
    verify_pinned_signature(
        supervisor_key,
        &payload,
        &journal.original_checkpoint_signature_bytes,
        "independent original Supervisor journal signature is invalid",
    )?;

    verify_original_supervisor_checkpoint_v1(
        &journal.original_checkpoint_bytes,
        &journal,
        plan,
    )?;
    let original: OriginalSupervisorCheckpointV1 =
        serde_json::from_slice(&journal.original_checkpoint_bytes)?;
    if original.receipt_digest != runtime_trust.supervisor_minimum_checkpoint_digest {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "original Supervisor journal is below independently retained checkpoint",
        ));
    }
    // A matching string is not independent evidence: it could have been
    // copied directly from the untrusted original checkpoint. Require the
    // externally pinned Observer's signature over the *full* run-specific
    // checkpoint minimum. The deployment remains responsible for ensuring
    // that this Observer reads a genuinely monotonic store before signing.
    let witness = runtime_trust.supervisor_minimum_observer_signature;
    let observer_key = evidence_policy
        .observer_keys
        .get(&witness.signer_id)
        .ok_or(CellSplitObserverJoinErrorV1::Invalid(
            "Supervisor minimum witness signer is not an independent Observer",
        ))?;
    if witness.signer_id == evidence.host_signature.signer_id
        || !evidence.observer_signatures.iter().any(|signature| {
            signature.signer_id == witness.signer_id
        })
        || owner_trust.contains_owner_key(observer_key)
        || observer_key == cns_key
        || observer_key == supervisor_key
        || evidence_policy.host_keys.values().any(|key| key == observer_key)
    {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "Supervisor minimum witness does not come from an independent Observer",
        ));
    }
    let message = cell_split_supervisor_minimum_signing_payload_v1(
        plan,
        evidence,
        &journal,
        runtime_trust.supervisor_minimum_checkpoint_digest,
    )?;
    verify_join_signature(witness, observer_key, &message)?;
    Ok((
        sha256(&original_cns.original_runtime_receipt_bytes),
        sha256(&journal.original_checkpoint_bytes),
    ))
}

/// An independently signed original must still be the canonical durable
/// WriterHandoffCheckpointV1 record, not a plausible JSON object signed by
/// an otherwise trusted key. This mirrors the original on-disk V1 schema and
/// content digest without linking to the Supervisor crate (which depends on
/// operator-acceptance).
#[cfg(unix)]
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct OriginalSupervisorCheckpointV1 {
    schema_version: u16,
    operation_id: String,
    domain_id: String,
    source_writer: String,
    target_writer: String,
    old_generation: u64,
    new_generation: u64,
    authority_epoch: u64,
    migration_plan_digest: String,
    schema_digest: String,
    rollback_predecessor_digest: String,
    revision: u64,
    phase: String,
    outbox_watermark: Option<u64>,
    unknown_effect_count: u32,
    evidence_digest: String,
    previous_receipt_digest: String,
    receipt_digest: String,
}

#[cfg(unix)]
impl OriginalSupervisorCheckpointV1 {
    /// Domain and exact byte sequence from writer_handoff::checkpoint_digest.
    /// The owner stores ten ordered checkpoints, retiring at revision ten.
    pub(crate) fn content_digest_v1(&self) -> Result<String, CellSplitObserverJoinErrorV1> {
        let malformed = || CellSplitObserverJoinErrorV1::Invalid(
            "original Supervisor checkpoint has invalid digest encoding",
        );
        let mut bytes = b"hepta.writer-handoff.checkpoint.v1".to_vec();
        for identity in [
            &self.operation_id,
            &self.domain_id,
            &self.source_writer,
            &self.target_writer,
        ] {
            let size = u32::try_from(identity.len()).map_err(|_| malformed())?;
            bytes.extend_from_slice(&size.to_be_bytes());
            bytes.extend_from_slice(identity.as_bytes());
        }
        for number in [
            self.old_generation,
            self.new_generation,
            self.authority_epoch,
        ] {
            bytes.extend_from_slice(&number.to_be_bytes());
        }
        for digest in [
            &self.migration_plan_digest,
            &self.schema_digest,
            &self.rollback_predecessor_digest,
        ] {
            bytes.extend_from_slice(&decode_supervisor_digest_v1(digest)?);
        }
        bytes.extend_from_slice(&self.revision.to_be_bytes());
        bytes.push(9); // WriterHandoffPhaseV1::Retired
        match self.outbox_watermark {
            Some(watermark) => {
                bytes.push(1);
                bytes.extend_from_slice(&watermark.to_be_bytes());
            }
            None => bytes.push(0),
        }
        bytes.extend_from_slice(&self.unknown_effect_count.to_be_bytes());
        bytes.extend_from_slice(&decode_supervisor_digest_v1(&self.evidence_digest)?);
        bytes.extend_from_slice(&decode_supervisor_digest_v1(&self.previous_receipt_digest)?);
        Ok(sha256(&bytes))
    }
}

#[cfg(unix)]
fn decode_supervisor_digest_v1(
    value: &str,
) -> Result<[u8; 32], CellSplitObserverJoinErrorV1> {
    if value.len() != 64
        || !value.bytes().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
    {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "original Supervisor checkpoint has invalid digest encoding",
        ));
    }
    let mut bytes = [0_u8; 32];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|_| CellSplitObserverJoinErrorV1::Invalid(
                "original Supervisor checkpoint has invalid digest encoding",
            ))?;
    }
    if bytes == [0_u8; 32] {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "original Supervisor checkpoint contains an empty digest",
        ));
    }
    Ok(bytes)
}

#[cfg(unix)]
fn verify_original_supervisor_checkpoint_v1(
    bytes: &[u8],
    journal: &CellSplitSupervisorCommitV1,
    plan: &crate::CellSplitExecutionPlanV1,
) -> Result<(), CellSplitObserverJoinErrorV1> {
    let checkpoint: OriginalSupervisorCheckpointV1 = serde_json::from_slice(bytes)?;
    // The Supervisor's canonical_receipt_bytes_v1 uses serde_json::to_vec
    // over a fixed ordered struct. Do not use durable::canonical_json here:
    // it sorts JSON map keys and is a different representation.
    if serde_json::to_vec(&checkpoint)?.as_slice() != bytes
        || checkpoint.schema_version != 1
        || checkpoint.phase != "retired"
        || checkpoint.revision != 10
        || checkpoint.outbox_watermark.is_none()
        || checkpoint.unknown_effect_count != 0
        || checkpoint.operation_id != plan.split_id
        || checkpoint.domain_id != journal.domain_id
        || codex_hepta_types::StableId::new(checkpoint.operation_id.clone()).is_err()
        || codex_hepta_types::StableId::new(checkpoint.domain_id.clone()).is_err()
        || codex_hepta_types::StableId::new(checkpoint.source_writer.clone()).is_err()
        || codex_hepta_types::StableId::new(checkpoint.target_writer.clone()).is_err()
        || checkpoint.old_generation != plan.parent_generation
        || checkpoint.new_generation != plan.child_generation
        || checkpoint.authority_epoch != journal.authority_epoch
        || checkpoint.revision != journal.committed_revision
        || checkpoint.receipt_digest != checkpoint.content_digest_v1()?
    {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "signed original Supervisor checkpoint is not a canonical terminal journal record",
        ));
    }
    Ok(())
}

#[cfg(unix)]
fn verify_original_handoff_epoch_v1(
    cns: &CellSplitCnsRuntimeCommitV1,
    supervisor: &CellSplitSupervisorCommitV1,
) -> Result<(), CellSplitObserverJoinErrorV1> {
    if cns.authority_epoch == 0 || cns.authority_epoch != supervisor.authority_epoch {
        return Err(CellSplitObserverJoinErrorV1::Invalid(
            "original CNS and Supervisor authority epochs differ",
        ));
    }
    Ok(())
}

#[cfg(unix)]
fn verify_pinned_signature(
    key: &VerifyingKey,
    message: &[u8],
    signature: &[u8],
    reason: &'static str,
) -> Result<(), CellSplitObserverJoinErrorV1> {
    let parsed = Signature::from_slice(signature)
        .map_err(|_| CellSplitObserverJoinErrorV1::Invalid(reason))?;
    key.verify_strict(message, &parsed)
        .map_err(|_| CellSplitObserverJoinErrorV1::Invalid(reason))
}

#[cfg(all(test, unix))]
mod authority_epoch_tests {
    use super::*;

    #[test]
    fn independently_signed_cns_and_supervisor_must_share_authority_epoch() {
        let cns = CellSplitCnsRuntimeCommitV1 {
            idempotency_key: "11".repeat(32),
            cns_id: "cns.main".into(),
            predecessor_route_digest: "22".repeat(32),
            successor_route_digest: "33".repeat(32),
            predecessor_generation: 7,
            successor_generation: 8,
            authority_epoch: 9,
            committed_sequence: 2,
            original_runtime_receipt_bytes: vec![1],
            original_runtime_signature_bytes: vec![0; 64],
        };
        let mut journal = CellSplitSupervisorCommitV1 {
            idempotency_key: "44".repeat(32),
            domain_id: "scope.main".into(),
            handoff_plan_digest: "55".repeat(32),
            old_generation: 7,
            new_generation: 8,
            authority_epoch: 9,
            committed_revision: 3,
            original_checkpoint_bytes: vec![1],
            original_checkpoint_signature_bytes: vec![0; 64],
        };
        assert!(verify_original_handoff_epoch_v1(&cns, &journal).is_ok());

        journal.authority_epoch = 10;
        assert!(matches!(
            verify_original_handoff_epoch_v1(&cns, &journal),
            Err(CellSplitObserverJoinErrorV1::Invalid(
                "original CNS and Supervisor authority epochs differ"
            ))
        ));
        journal.authority_epoch = 9;
        let mut missing_epoch = cns;
        missing_epoch.authority_epoch = 0;
        assert!(verify_original_handoff_epoch_v1(&missing_epoch, &journal).is_err());
    }
}


#[cfg(all(test, unix))]
mod original_checkpoint_integrity_tests {
    use super::*;

    fn fixture() -> (crate::CellSplitExecutionPlanV1, CellSplitSupervisorCommitV1) {
        let plan = crate::CellSplitExecutionPlanV1 {
            split_id: "split.observer".into(),
            scope_digest: "11".repeat(32),
            parent_generation: 7,
            child_generation: 8,
            parent_artifact_digest: "22".repeat(32),
            child_artifact_digest: "33".repeat(32),
            ndu_snapshot_digest: "44".repeat(32),
            route_fence_digest: "55".repeat(32),
            owner_ids: [
                "artifact".into(), "migration".into(),
                "cns".into(), "supervisor".into(),
            ],
        };
        let json = serde_json::json!({
            "schemaVersion": 1,
            "operationId": "split.observer",
            "domainId": "domain.observer",
            "sourceWriter": "cell.parent",
            "targetWriter": "cell.child",
            "oldGeneration": 7,
            "newGeneration": 8,
            "authorityEpoch": 9,
            "migrationPlanDigest": "61".repeat(32),
            "schemaDigest": "62".repeat(32),
            "rollbackPredecessorDigest": "63".repeat(32),
            "revision": 10,
            "phase": "retired",
            "outboxWatermark": 42,
            "unknownEffectCount": 0,
            "evidenceDigest": "64".repeat(32),
            "previousReceiptDigest": "65".repeat(32),
            "receiptDigest": "00".repeat(32),
        });
        let mut checkpoint: OriginalSupervisorCheckpointV1 =
            serde_json::from_value(json).expect("typed canonical handoff");
        checkpoint.receipt_digest = checkpoint.content_digest_v1().expect("checkpoint hash");
        let bytes = serde_json::to_vec(&checkpoint).expect("native order");
        let journal = CellSplitSupervisorCommitV1 {
            idempotency_key: "aa".repeat(32),
            domain_id: "domain.observer".into(),
            handoff_plan_digest: "66".repeat(32),
            old_generation: 7,
            new_generation: 8,
            authority_epoch: 9,
            committed_revision: 10,
            original_checkpoint_bytes: bytes,
            original_checkpoint_signature_bytes: vec![0; 64],
        };
        (plan, journal)
    }

    #[test]
    fn original_supervisor_checkpoint_requires_actual_journal_schema_and_digest() {
        let (plan, journal) = fixture();
        assert!(verify_original_supervisor_checkpoint_v1(
            &journal.original_checkpoint_bytes, &journal, &plan,
        ).is_ok());

        let original: OriginalSupervisorCheckpointV1 =
            serde_json::from_slice(&journal.original_checkpoint_bytes)
                .expect("original typed checkpoint");
        // Stable vector computed independently from the Supervisor's domain,
        // big-endian identity lengths, phase tag, and Q24-free digest fields.
        assert_eq!(
            original.receipt_digest,
            "3d33ace2a9bc2afeea989ffbf81b7cd785f703c9a5dff9411832a8f9a5edac51",
        );
        for (name, key, value) in [
            ("false terminal revision", "revision", serde_json::json!(11)),
            ("missing drain watermark", "outboxWatermark", serde_json::Value::Null),
            ("forged prior digest", "previousReceiptDigest",
                serde_json::json!("ff".repeat(32))),
            ("invalid schema", "schemaVersion", serde_json::json!(2)),
            ("different handoff domain", "domainId",
                serde_json::json!("other-domain")),
            ("illegal owner identity", "sourceWriter",
                serde_json::json!("invalid writer")),
            ("different final-use epoch", "authorityEpoch", serde_json::json!(10)),
            ("stale generation", "newGeneration", serde_json::json!(9)),
            ("nonterminal phase", "phase", serde_json::json!("route_published")),
            ("unknown effect remains", "unknownEffectCount", serde_json::json!(1)),
        ] {
            let mut altered = serde_json::to_value(&original).expect("json value");
            altered[key] = value;
            let mut changed: OriginalSupervisorCheckpointV1 =
                serde_json::from_value(altered).expect("well-formed field type");
            // Except for the explicit hash-tamper case, repair the receipt
            // digest so the test exercises semantic validation independently
            // of the self-hash check.
            if name != "forged prior digest" {
                changed.receipt_digest = changed.content_digest_v1()
                    .expect("rehash well-formed tampering");
            }
            let bytes = serde_json::to_vec(&changed).expect("typed encoding");
            assert!(
                verify_original_supervisor_checkpoint_v1(&bytes, &journal, &plan).is_err(),
                "{name}: a signed but altered checkpoint cannot qualify",
            );
        }

        let sorted_json = canonical_json(&original).expect("sorted JSON object");
        assert_ne!(sorted_json, journal.original_checkpoint_bytes);
        assert!(verify_original_supervisor_checkpoint_v1(
            &sorted_json, &journal, &plan,
        ).is_err(), "native WriterHandoff serialisation cannot be replaced");

        let mut dropped = serde_json::to_value(&original).expect("value");
        dropped.as_object_mut().expect("checkpoint object").remove("sourceWriter");
        let bytes = serde_json::to_vec(&dropped).expect("incomplete JSON");
        assert!(verify_original_supervisor_checkpoint_v1(
            &bytes, &journal, &plan,
        ).is_err(), "all durable writer-handoff fields are mandatory");

        let mut extra = serde_json::to_value(&original).expect("value");
        extra["pretendAuthorized"] = serde_json::json!(true);
        let bytes = serde_json::to_vec(&extra).expect("extra JSON");
        assert!(verify_original_supervisor_checkpoint_v1(
            &bytes, &journal, &plan,
        ).is_err(), "unrecognized checkpoint claims must be rejected");
    }
}
