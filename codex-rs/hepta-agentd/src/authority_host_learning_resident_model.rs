//! Proposal has no LearningEvidence role. This private projection originates
//! only in an actual original Model command readback. A receiver accepts it
//! only inside the fixed, authenticated Root resident reply. It is never an
//! owner, grant, writable journal, deserialized seal or fresh execution token.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;
use codex_hepta_learning_artifacts::LearningProposalDispositionV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::profile::RootResidentLearningProfileV3;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::OriginalCellQ24ModelCommandReceiptV1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

const HEADER: &[u8; 8] = b"HERMOD01";
pub(super) const ENCODED_BYTES: usize = 152;

#[derive(Clone, Eq, PartialEq)]
pub(super) struct ResidentOriginalModelProofV3 {
    context: Digest32,
    record: [u8; 80],
    binding: Digest32,
}

impl ResidentOriginalModelProofV3 {
    pub(super) fn from_original_readback(
        profile: &RootResidentLearningProfileV3,
        verifier: &LearningEvidenceVerifierV1,
        snapshot: &LearningIterationSnapshotV1,
        signatures: &[SignedLearningEvidenceV1],
        original: &OriginalCellQ24ModelCommandReceiptV1,
        now: u64,
    ) -> Result<Self, Error> {
        if original.snapshot() != snapshot || original.authority() != AuthorityPosture::DENY_ALL {
            return Err(Error::WrongScope);
        }
        let (record, context) =
            OriginalCellQ24ModelCommandReceiptV1::original_record_for_root(original, signatures)
                .map_err(|_| Error::WrongScope)?;
        require_record(profile, snapshot, record, now)?;
        let binding = binding(profile, verifier, snapshot, signatures, context, record)?;
        Ok(Self {
            context,
            record: *record,
            binding,
        })
    }

    pub(super) fn encode(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(ENCODED_BYTES);
        bytes.extend_from_slice(HEADER);
        bytes.extend_from_slice(self.context.as_array());
        bytes.extend_from_slice(&self.record);
        bytes.extend_from_slice(self.binding.as_array());
        bytes
    }

    /// The fixed Root reply decoder authenticates the channel before using
    /// this projection. Readonly recovery may validate and discard it as a
    /// comparison pin. Neither use constructs an original Model receipt.
    pub(super) fn decode_root_reply(
        bytes: &[u8],
        profile: &RootResidentLearningProfileV3,
        verifier: &LearningEvidenceVerifierV1,
        snapshot: &LearningIterationSnapshotV1,
        signatures: &[SignedLearningEvidenceV1],
        now: u64,
    ) -> Result<Self, Error> {
        if bytes.len() != ENCODED_BYTES || &bytes[..8] != HEADER {
            return Err(Error::WrongScope);
        }
        let proof = Self {
            context: Digest32::from_array(bytes[8..40].try_into().map_err(|_| Error::WrongScope)?),
            record: bytes[40..120].try_into().map_err(|_| Error::WrongScope)?,
            binding: Digest32::from_array(
                bytes[120..152].try_into().map_err(|_| Error::WrongScope)?,
            ),
        };
        proof.require_original(profile, verifier, snapshot, signatures, now)?;
        Ok(proof)
    }

    pub(super) fn require_original(
        &self,
        profile: &RootResidentLearningProfileV3,
        verifier: &LearningEvidenceVerifierV1,
        snapshot: &LearningIterationSnapshotV1,
        signatures: &[SignedLearningEvidenceV1],
        now: u64,
    ) -> Result<(), Error> {
        require_record(profile, snapshot, &self.record, now)?;
        if binding(
            profile,
            verifier,
            snapshot,
            signatures,
            self.context,
            &self.record,
        )? != self.binding
        {
            return Err(Error::WrongScope);
        }
        Ok(())
    }
}

fn require_record(
    profile: &RootResidentLearningProfileV3,
    snapshot: &LearningIterationSnapshotV1,
    record: &[u8; 80],
    now: u64,
) -> Result<(), Error> {
    profile.scope.validate_snapshot(snapshot)?;
    let complete = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
    let stages = [
        Stage::Experience,
        Stage::Dataset,
        Stage::Training,
        Stage::Evaluation,
        Stage::Proposal,
    ];
    if snapshot.request != profile.initial.request
        || snapshot.owners != profile.initial.owners
        || snapshot.receipts.len() != stages.len()
        || !snapshot
            .receipts
            .iter()
            .zip(stages)
            .all(|(receipt, stage)| receipt.observation.stage() == stage)
        || snapshot.training_no_update_v2().is_some()
        || complete.next_stage() != Some(Stage::Selection)
        || &record[..8] != b"HQ24PROP"
    {
        return Err(Error::WrongScope);
    }
    let mut prefix = LearningIterationCoordinatorV1::from_snapshot(profile.initial.clone())?;
    for receipt in &snapshot.receipts[..4] {
        prefix.record(receipt.clone(), receipt.observed_unix_seconds)?;
    }
    let material = Digest32::from_array(record[40..72].try_into().map_err(|_| Error::WrongScope)?);
    let at = u64::from_le_bytes(record[72..80].try_into().map_err(|_| Error::WrongScope)?);
    let composition = Digest32::of_parts(&[b"hepta.cell.q24.model-proposal-receipt.v1\0", record]);
    let candidate = prefix
        .candidate()
        .ok_or(Error::WrongScope)?
        .digest()
        .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
    let receipt = &snapshot.receipts[4];
    if prefix.next_stage() != Some(Stage::Proposal)
        || record[8..40] != *prefix.snapshot().head_digest.as_array()
        || material.is_zero()
        || at < snapshot.receipts[3].observed_unix_seconds
        || at >= snapshot.request.envelope.expiry_unix_seconds
        || at > now
        || receipt.observed_unix_seconds != at
        || receipt.operation_id != snapshot.request.operation_id
        || receipt.actor_id != snapshot.owners.proposal
        || receipt.predecessor != prefix.snapshot().head_digest
        || receipt.evidence_digest != composition
        || receipt.observation
            != (LearningIterationObservationV1::Proposal {
                candidate_bundle: candidate,
                proposal_id: snapshot.request.operation_id.clone(),
                composition_digest: composition,
                disposition: LearningProposalDispositionV1::UpdateCandidates,
            })
    {
        return Err(Error::WrongScope);
    }
    Ok(())
}

fn binding(
    profile: &RootResidentLearningProfileV3,
    verifier: &LearningEvidenceVerifierV1,
    snapshot: &LearningIterationSnapshotV1,
    signatures: &[SignedLearningEvidenceV1],
    context: Digest32,
    record: &[u8; 80],
) -> Result<Digest32, Error> {
    profile
        .require_verifier(verifier)
        .map_err(|_| Error::WrongScope)?;
    if context.is_zero() || signatures.len() != 4 {
        return Err(Error::WrongScope);
    }
    let mut bytes = b"hepta.agentd.root-resident-original-model-proof.v3\0".to_vec();
    for digest in [
        profile.binding,
        profile.scope.binding(),
        verifier.trust_digest(),
        verifier.scope_digest(),
        verifier.objective_digest(),
        context,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    let encoded = encode_original_owner_snapshot_v1(snapshot).map_err(Error::Checkpoint)?;
    bytes.extend_from_slice(&(encoded.len() as u64).to_be_bytes());
    bytes.extend_from_slice(&encoded);
    bytes.extend_from_slice(record);
    for signed in signatures {
        let original = signed.signing_bytes();
        bytes.extend_from_slice(&(original.len() as u64).to_be_bytes());
        bytes.extend_from_slice(&original);
        bytes.extend_from_slice(&signed.signature);
    }
    Ok(Digest32::of_bytes(&bytes))
}
