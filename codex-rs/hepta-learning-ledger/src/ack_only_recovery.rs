//! **QUALIFICATION FEATURE ONLY**: independently root-authorized, exact
//! ACK-only recovery for *one* ALREADY DURABLE authenticated V2 event.
//!
//! Not enabled in default builds. Product host MUST pin the root out-of-band,
//! obtain actual independently durable source-time Escrow from another
//! administrator, provide trustworthy monotonic current time and the LATEST
//! authoritative root-signed revocation cut. A valid test root created by
//! the caller does not prove product enrollment, independence, or hardware
//! durability. This module never generates signer credentials or creates an
//! original Ledger event; it may only synchronize an existing Witness.
//!
//! No historical caller-supplied "now" may reauthorize an old Generator or
//! Observer signature. RecoveryAuthority signs a NEW narrowly scoped grant
//! under a fresh root-signed cut, and escrow evidence must already have been
//! signed and independently preserved before the original append.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::{Signature, VerifyingKey};

use crate::DurableLedger;
use crate::DurableLedgerError;
use crate::LedgerAnchor;
use crate::LedgerEvent;
use crate::LedgerWitnessFrontier;
use crate::LedgerWitnessStore;

const DELEGATION_DOMAIN: &[u8] = b"hepta.learning-ledger.ackonly-delegation.test.v1";
const CUT_DOMAIN: &[u8] = b"hepta.learning-ledger.ackonly-current-cut.test.v1";
const ESCROW_DOMAIN: &[u8] = b"hepta.learning-ledger.ackonly-preappend-escrow.test.v1";
const GRANT_DOMAIN: &[u8] = b"hepta.learning-ledger.ackonly-recovery-grant.test.v1";
const MAX_CUT_AGE_MS: u64 = 30_000;
const MAX_GRANT_WINDOW_MS: u64 = 90_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AckOnlyRootPinV1 {
    pub root_id: StableId,
    pub ledger_binding: Digest32,
    pub objective_digest: Digest32,
    pub verifying_key: [u8; 32],
    pub valid_from: u64,
    pub expires_at: u64,
    pub revoked_at: Option<u64>,
}

/// Independently typed role namespace. This does not alter the old
/// LearningEvidenceRoleV1 serialized signing tags or original LLM policy.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AckOnlyRootDelegationV1 {
    pub root_id: StableId,
    pub authority_epoch: u64,
    pub authority_id: StableId,
    pub authority_controller_id: StableId,
    pub recovery_verifying_key: [u8; 32],
    pub escrow_id: StableId,
    pub escrow_controller_id: StableId,
    pub escrow_verifying_key: [u8; 32],
    pub effective_at: u64,
    pub expires_at: u64,
    pub root_signature: [u8; 64],
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AckOnlyCurrentRevocationCutV1 {
    pub root_id: StableId,
    pub delegation_digest: Digest32,
    pub authority_epoch: u64,
    pub cut_id: Digest32,
    pub issued_at: u64,
    pub expires_at: u64,
    /// Host source of truth is root controlled, never the affected signer.
    pub recovery_authority_current: bool,
    pub escrow_authority_current: bool,
    pub original_event_not_revoked: bool,
    pub root_signature: [u8; 64],
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AckOnlySourceEscrowV1 {
    pub escrow_id: StableId,
    pub authority_epoch: u64,
    pub ledger_binding: Digest32,
    pub objective_digest: Digest32,
    pub original_record_id: StableId,
    pub original_authentication_digest: Digest32,
    pub previous_witness: LedgerAnchor,
    pub target_anchor: LedgerAnchor,
    pub target_event_digest: Digest32,
    /// Source actor's original SignedEvidenceV1 timestamp as *verified by
    /// host*. The native stored authentication digest must match exactly.
    pub original_actor_evidence_issued_at: u64,
    /// Claimed receipt time: a cryptographic assertion by the escrow owner,
    /// NOT independently verified wall-time or physical fsync durability.
    pub escrow_held_at: u64,
    /// Claimed earliest start of original native append. A trusted external
    /// owner must independently verify that escrow was durable before this.
    pub original_append_started_at: u64,
    pub unique_intent_digest: Digest32,
    pub escrow_signature: [u8; 64],
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AckOnlyRecoveryGrantV1 {
    pub grant_id: StableId,
    pub grant_nonce: Digest32,
    pub delegation_digest: Digest32,
    pub current_cut_digest: Digest32,
    pub authority_epoch: u64,
    pub ledger_binding: Digest32,
    pub objective_digest: Digest32,
    pub source_escrow_receipt_digest: Digest32,
    pub original_record_id: StableId,
    pub original_authentication_digest: Digest32,
    pub previous_witness: LedgerAnchor,
    pub target_anchor: LedgerAnchor,
    pub target_event_digest: Digest32,
    pub issued_at: u64,
    pub expires_at: u64,
    pub recovery_signature: [u8; 64],
}

/// Exactly one immutable bundle of admission proofs for one witness ACK.
/// Product host still owns pinned Root and trusted time out-of-band.
#[derive(Clone, Copy, Debug)]
pub struct AckOnlyRecoveryProofV1<'a> {
    pub root: &'a AckOnlyRootPinV1,
    pub delegation: &'a AckOnlyRootDelegationV1,
    pub cut: &'a AckOnlyCurrentRevocationCutV1,
    pub escrow: &'a AckOnlySourceEscrowV1,
    pub independent_source_escrow_readback: &'a [u8],
    pub grant: &'a AckOnlyRecoveryGrantV1,
    pub current_host_time_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AckOnlyTestReceiptV1 {
    pub grant_id: StableId,
    pub source_event_digest: Digest32,
    pub source_escrow_receipt_digest: Digest32,
    pub previous_witness: LedgerAnchor,
    pub acknowledged_witness: LedgerAnchor,
    /// This only proves local WitnessStore::advance synced successfully.
    /// It cannot attest remote independent escrow disk or power-fail survival.
    pub witness_synced: bool,
    pub ledger_record_count_unchanged: bool,
    pub qualification_only_no_product_authority: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AckOnlyRecoveryError {
    InvalidRootPin,
    InvalidDelegation,
    InvalidCurrentRevocationCut,
    InvalidEscrow,
    MissingIndependentEscrowReadback,
    InvalidRecoveryGrant,
    MismatchedWitnessOrLedger,
    AlreadyAcknowledged,
    NotExactlyOneUnwitnessedRecord,
    UnsupportedOriginalEventKind,
    ActorControllerNotIndependent,
    Durable(DurableLedgerError),
}

impl fmt::Display for AckOnlyRecoveryError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for AckOnlyRecoveryError {}
impl From<DurableLedgerError> for AckOnlyRecoveryError {
    fn from(value: DurableLedgerError) -> Self {
        Self::Durable(value)
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let b = id.as_str().as_bytes();
    bytes.extend_from_slice(&(b.len() as u64).to_be_bytes());
    bytes.extend_from_slice(b);
}
fn push_anchor(bytes: &mut Vec<u8>, anchor: LedgerAnchor) {
    bytes.extend_from_slice(&anchor.sequence.to_be_bytes());
    bytes.extend_from_slice(anchor.chain_digest.as_array());
}
fn strong_key(raw: &[u8; 32]) -> Result<VerifyingKey, AckOnlyRecoveryError> {
    let key = VerifyingKey::from_bytes(raw).map_err(|_| AckOnlyRecoveryError::InvalidDelegation)?;
    if key.is_weak() {
        return Err(AckOnlyRecoveryError::InvalidDelegation);
    }
    Ok(key)
}
fn verify(
    key: &[u8; 32],
    payload: &[u8],
    sig: &[u8; 64],
    error: AckOnlyRecoveryError,
) -> Result<(), AckOnlyRecoveryError> {
    strong_key(key)?
        .verify_strict(payload, &Signature::from_bytes(sig))
        .map_err(|_| error)
}

impl AckOnlyRootDelegationV1 {
    #[must_use]
    pub fn signing_bytes(&self, root: &AckOnlyRootPinV1) -> Vec<u8> {
        let mut b = DELEGATION_DOMAIN.to_vec();
        push_id(&mut b, &self.root_id);
        b.extend_from_slice(root.ledger_binding.as_array());
        b.extend_from_slice(root.objective_digest.as_array());
        b.extend_from_slice(&self.authority_epoch.to_be_bytes());
        push_id(&mut b, &self.authority_id);
        push_id(&mut b, &self.authority_controller_id);
        b.extend_from_slice(&self.recovery_verifying_key);
        push_id(&mut b, &self.escrow_id);
        push_id(&mut b, &self.escrow_controller_id);
        b.extend_from_slice(&self.escrow_verifying_key);
        b.extend_from_slice(&self.effective_at.to_be_bytes());
        b.extend_from_slice(&self.expires_at.to_be_bytes());
        b
    }
    #[must_use]
    pub fn digest(&self, root: &AckOnlyRootPinV1) -> Digest32 {
        let mut bytes = self.signing_bytes(root);
        bytes.extend_from_slice(&self.root_signature);
        Digest32::of_bytes(&bytes)
    }
}
impl AckOnlyCurrentRevocationCutV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut b = CUT_DOMAIN.to_vec();
        push_id(&mut b, &self.root_id);
        b.extend_from_slice(self.delegation_digest.as_array());
        b.extend_from_slice(&self.authority_epoch.to_be_bytes());
        b.extend_from_slice(self.cut_id.as_array());
        b.extend_from_slice(&self.issued_at.to_be_bytes());
        b.extend_from_slice(&self.expires_at.to_be_bytes());
        for active in [
            self.recovery_authority_current,
            self.escrow_authority_current,
            self.original_event_not_revoked,
        ] {
            b.push(u8::from(active));
        }
        b
    }
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut b = self.signing_bytes();
        b.extend_from_slice(&self.root_signature);
        Digest32::of_bytes(&b)
    }
}
impl AckOnlySourceEscrowV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut b = ESCROW_DOMAIN.to_vec();
        push_id(&mut b, &self.escrow_id);
        b.extend_from_slice(&self.authority_epoch.to_be_bytes());
        b.extend_from_slice(self.ledger_binding.as_array());
        b.extend_from_slice(self.objective_digest.as_array());
        push_id(&mut b, &self.original_record_id);
        b.extend_from_slice(self.original_authentication_digest.as_array());
        push_anchor(&mut b, self.previous_witness);
        push_anchor(&mut b, self.target_anchor);
        b.extend_from_slice(self.target_event_digest.as_array());
        for n in [
            self.original_actor_evidence_issued_at,
            self.escrow_held_at,
            self.original_append_started_at,
        ] {
            b.extend_from_slice(&n.to_be_bytes());
        }
        b.extend_from_slice(self.unique_intent_digest.as_array());
        b
    }
    #[must_use]
    pub fn receipt_bytes(&self) -> Vec<u8> {
        let mut b = self.signing_bytes();
        b.extend_from_slice(&self.escrow_signature);
        b
    }
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.receipt_bytes())
    }
}
impl AckOnlyRecoveryGrantV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut b = GRANT_DOMAIN.to_vec();
        push_id(&mut b, &self.grant_id);
        for d in [
            self.grant_nonce,
            self.delegation_digest,
            self.current_cut_digest,
        ] {
            b.extend_from_slice(d.as_array());
        }
        b.extend_from_slice(&self.authority_epoch.to_be_bytes());
        for d in [
            self.ledger_binding,
            self.objective_digest,
            self.source_escrow_receipt_digest,
        ] {
            b.extend_from_slice(d.as_array());
        }
        push_id(&mut b, &self.original_record_id);
        b.extend_from_slice(self.original_authentication_digest.as_array());
        push_anchor(&mut b, self.previous_witness);
        push_anchor(&mut b, self.target_anchor);
        b.extend_from_slice(self.target_event_digest.as_array());
        b.extend_from_slice(&self.issued_at.to_be_bytes());
        b.extend_from_slice(&self.expires_at.to_be_bytes());
        b
    }
}

fn validate_actors(
    root: &AckOnlyRootPinV1,
    delegation: &AckOnlyRootDelegationV1,
    cut: &AckOnlyCurrentRevocationCutV1,
    escrow: &AckOnlySourceEscrowV1,
    grant: &AckOnlyRecoveryGrantV1,
    now: u64,
) -> Result<(), AckOnlyRecoveryError> {
    if root.ledger_binding.is_zero()
        || root.objective_digest.is_zero()
        || root.valid_from == 0
        || root.valid_from > now
        || now > root.expires_at
        || root.revoked_at.is_some_and(|at| now >= at)
    {
        return Err(AckOnlyRecoveryError::InvalidRootPin);
    }
    strong_key(&root.verifying_key).map_err(|_| AckOnlyRecoveryError::InvalidRootPin)?;
    if delegation.root_id != root.root_id
        || delegation.authority_epoch == 0
        || delegation.effective_at < root.valid_from
        || delegation.expires_at > root.expires_at
        || delegation.effective_at > now
        || now > delegation.expires_at
        || delegation.authority_controller_id == delegation.escrow_controller_id
        || delegation.recovery_verifying_key == delegation.escrow_verifying_key
        || delegation.authority_id == delegation.escrow_id
    {
        return Err(AckOnlyRecoveryError::InvalidDelegation);
    }
    strong_key(&delegation.recovery_verifying_key)?;
    strong_key(&delegation.escrow_verifying_key)?;
    verify(
        &root.verifying_key,
        &delegation.signing_bytes(root),
        &delegation.root_signature,
        AckOnlyRecoveryError::InvalidDelegation,
    )?;
    let delegation_digest = delegation.digest(root);
    if cut.root_id != root.root_id
        || cut.delegation_digest != delegation_digest
        || cut.authority_epoch != delegation.authority_epoch
        || cut.cut_id.is_zero()
        || cut.issued_at < root.valid_from
        || cut.issued_at < delegation.effective_at
        || cut.issued_at > cut.expires_at
        || cut.issued_at > now
        || now > cut.expires_at
        || now.saturating_sub(cut.issued_at) > MAX_CUT_AGE_MS
        || cut.expires_at > delegation.expires_at
        || !cut.recovery_authority_current
        || !cut.escrow_authority_current
        || !cut.original_event_not_revoked
    {
        return Err(AckOnlyRecoveryError::InvalidCurrentRevocationCut);
    }
    verify(
        &root.verifying_key,
        &cut.signing_bytes(),
        &cut.root_signature,
        AckOnlyRecoveryError::InvalidCurrentRevocationCut,
    )?;
    if escrow.escrow_id != delegation.escrow_id
        || escrow.authority_epoch != delegation.authority_epoch
        || escrow.ledger_binding != root.ledger_binding
        || escrow.objective_digest != root.objective_digest
        || escrow.original_authentication_digest.is_zero()
        || escrow.unique_intent_digest.is_zero()
        || escrow.target_event_digest.is_zero()
        || escrow.original_actor_evidence_issued_at == 0
        || escrow.original_actor_evidence_issued_at > escrow.escrow_held_at
        || escrow.escrow_held_at > escrow.original_append_started_at
        || escrow.escrow_held_at < delegation.effective_at
        || escrow.original_append_started_at > delegation.expires_at
    {
        return Err(AckOnlyRecoveryError::InvalidEscrow);
    }
    verify(
        &delegation.escrow_verifying_key,
        &escrow.signing_bytes(),
        &escrow.escrow_signature,
        AckOnlyRecoveryError::InvalidEscrow,
    )?;
    if grant.grant_nonce.is_zero()
        || grant.delegation_digest != delegation_digest
        || grant.current_cut_digest != cut.digest()
        || grant.authority_epoch != delegation.authority_epoch
        || grant.ledger_binding != root.ledger_binding
        || grant.objective_digest != root.objective_digest
        || grant.source_escrow_receipt_digest != escrow.digest()
        || grant.original_record_id != escrow.original_record_id
        || grant.original_authentication_digest != escrow.original_authentication_digest
        || grant.previous_witness != escrow.previous_witness
        || grant.target_anchor != escrow.target_anchor
        || grant.target_event_digest != escrow.target_event_digest
        || grant.issued_at < cut.issued_at
        || grant.issued_at < escrow.original_append_started_at
        || grant.issued_at > now
        || grant.expires_at < now
        || grant.expires_at > cut.expires_at
        || grant.expires_at.saturating_sub(grant.issued_at) > MAX_GRANT_WINDOW_MS
    {
        return Err(AckOnlyRecoveryError::InvalidRecoveryGrant);
    }
    verify(
        &delegation.recovery_verifying_key,
        &grant.signing_bytes(),
        &grant.recovery_signature,
        AckOnlyRecoveryError::InvalidRecoveryGrant,
    )
}

/// **Feature gated qualification entry**. Exact durable Ledger record -> exact
/// Witness append, never a new Ledger event. External source escrow readback
/// MUST have been independently obtained from its originating host. Matching
/// caller-supplied bytes is not proof of physical remote fsync by itself.
///
/// The product host must supply out-of-band ROOT identity, authoritative
/// signed revocation cut and secure current time. Until those capabilities
/// are deployed this API is *not* a production release surface.
pub fn reconcile_one_existing_ack_qualification(
    ledger: &DurableLedger,
    witness: &mut LedgerWitnessStore,
    proof: &AckOnlyRecoveryProofV1<'_>,
) -> Result<AckOnlyTestReceiptV1, AckOnlyRecoveryError> {
    let root = proof.root;
    let delegation = proof.delegation;
    let cut = proof.cut;
    let escrow = proof.escrow;
    let independently_readback_escrow_bytes = proof.independent_source_escrow_readback;
    let grant = proof.grant;
    let now = proof.current_host_time_ms;
    // Verify trusted signer domain before considering any disk write.
    validate_actors(root, delegation, cut, escrow, grant, now)?;
    if independently_readback_escrow_bytes.len() > 4096
        || independently_readback_escrow_bytes != escrow.receipt_bytes()
    {
        return Err(AckOnlyRecoveryError::MissingIndependentEscrowReadback);
    }
    if ledger.binding_digest() != root.ledger_binding || witness.binding() != root.ledger_binding {
        return Err(AckOnlyRecoveryError::MismatchedWitnessOrLedger);
    }
    let before = witness.frontier()?;
    // The original DurableLedger provides a validated borrowed projection,
    // but deliberately exposes no mutable or raw frontier object. Recover
    // its exact anchor from the last original ledger record only.
    let records = ledger.records()?;
    let ledger_frontier = match records.last() {
        Some(last) => LedgerWitnessFrontier {
            anchor: LedgerAnchor {
                sequence: last.sequence.get(),
                chain_digest: last.chain_digest,
            },
            segment: None,
            sealed: false,
        },
        None => LedgerWitnessFrontier::empty(),
    };
    if before == ledger_frontier {
        return Err(AckOnlyRecoveryError::AlreadyAcknowledged);
    }
    let expected_seq = before
        .anchor
        .sequence
        .checked_add(1)
        .ok_or(AckOnlyRecoveryError::NotExactlyOneUnwitnessedRecord)?;
    if expected_seq != ledger_frontier.anchor.sequence
        || grant.previous_witness != before.anchor
        || grant.target_anchor != ledger_frontier.anchor
        || before.segment.is_some()
        || ledger_frontier.segment.is_some()
    {
        return Err(AckOnlyRecoveryError::NotExactlyOneUnwitnessedRecord);
    }
    let idx = usize::try_from(before.anchor.sequence)
        .map_err(|_| AckOnlyRecoveryError::NotExactlyOneUnwitnessedRecord)?;
    let record = records
        .get(idx)
        .ok_or(AckOnlyRecoveryError::NotExactlyOneUnwitnessedRecord)?;
    if usize::try_from(ledger_frontier.anchor.sequence).ok() != Some(records.len())
        || record.sequence.get() != expected_seq
        || record.predecessor_chain_digest != before.anchor.chain_digest
        || record.chain_digest != ledger_frontier.anchor.chain_digest
        || grant.target_event_digest != record.event_digest
        || grant.original_record_id != *record.event.record_id()
    {
        return Err(AckOnlyRecoveryError::MismatchedWitnessOrLedger);
    }
    let (source_auth, source_controller) = match &record.event {
        LedgerEvent::AuthenticatedDecisionV2(value) => {
            if value.objective_digest != root.objective_digest {
                return Err(AckOnlyRecoveryError::MismatchedWitnessOrLedger);
            }
            (value.authentication_digest, &value.generator_controller_id)
        }
        LedgerEvent::AuthenticatedOutcomeV2(value) => {
            // Outcome record stores an observer but not its objective. Bind
            // the same immutable authenticated predecessor Decision/episode
            // and require pairwise controller separation from BOTH signers.
            let source_decision = records[..idx]
                .iter()
                .rev()
                .find_map(|item| match &item.event {
                    LedgerEvent::AuthenticatedDecisionV2(d) if d.episode_id == value.episode_id => {
                        Some(d)
                    }
                    _ => None,
                })
                .ok_or(AckOnlyRecoveryError::MismatchedWitnessOrLedger)?;
            if source_decision.objective_digest != root.objective_digest {
                return Err(AckOnlyRecoveryError::MismatchedWitnessOrLedger);
            }
            if [
                &delegation.authority_controller_id,
                &delegation.escrow_controller_id,
            ]
            .contains(&&source_decision.generator_controller_id)
            {
                return Err(AckOnlyRecoveryError::ActorControllerNotIndependent);
            }
            (value.authentication_digest, &value.observer_controller_id)
        }
        _ => return Err(AckOnlyRecoveryError::UnsupportedOriginalEventKind),
    };
    if source_auth != grant.original_authentication_digest || source_auth.is_zero() {
        return Err(AckOnlyRecoveryError::MismatchedWitnessOrLedger);
    }
    if source_controller == &delegation.authority_controller_id
        || source_controller == &delegation.escrow_controller_id
    {
        return Err(AckOnlyRecoveryError::ActorControllerNotIndependent);
    }
    let next = witness.advance(before, ledger_frontier)?;
    if next.anchor != grant.target_anchor {
        return Err(AckOnlyRecoveryError::MismatchedWitnessOrLedger);
    }
    debug_assert_eq!(ledger.records()?.len(), records.len());
    Ok(AckOnlyTestReceiptV1 {
        grant_id: grant.grant_id.clone(),
        source_event_digest: record.event_digest,
        source_escrow_receipt_digest: escrow.digest(),
        previous_witness: before.anchor,
        acknowledged_witness: next.anchor,
        witness_synced: true,
        ledger_record_count_unchanged: true,
        qualification_only_no_product_authority: true,
    })
}

#[cfg(test)]
#[path = "ack_only_recovery_tests.rs"]
mod tests;
