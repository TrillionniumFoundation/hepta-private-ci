//! Durable original Dataset material, without a signer or a new source owner.
//! The host supplies the same authorized file, independent witness and complete
//! profile on reopen. A journal record is not historical-ledger authentication:
//! recovery replays only the actual witnessed LedgerWriter's original history.
//! Ordinary Root/StageOwner assembly and real custody remain separate inputs.

use std::fs::File;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::LearningLedger;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::freeze_dataset_from_ledger;

use super::*;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;
use crate::learning_owner_journal::LearningOwnerJournalV1;

#[path = "cell_q24_dataset_recovery_codec.rs"]
mod codec;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24DatasetRecoveryErrorV1 {
    #[error("original Q24 Dataset recovery binding: {0}")]
    Binding(&'static str),
    #[error("original Q24 Dataset recovery material: {0}")]
    Dataset(#[from] OriginalCellQ24DatasetErrorV1),
    #[error("original Q24 Dataset recovery ledger: {0}")]
    Ledger(#[from] ProductionLedgerError),
    #[error("original Q24 Dataset recovery owner: {0}")]
    Owner(#[from] LearningOriginalOwnerErrorV1),
}
type RecoveryError = OriginalCellQ24DatasetRecoveryErrorV1;

/// Persistence of a sealed Dataset, not authority to freeze, train or adopt one.
/// The full record must fit the existing 65,536-byte owner-store limit. This is
/// a recovery-material bound, not a change to Dataset or training capacities.
/// The host retains directory durability and an independent rollback domain for
/// the witness; restoring both journal and witness does not prove freshness.
pub struct OriginalCellQ24DatasetRecoveryOwnerV1<W: AnchorWitnessStore> {
    journal: LearningOwnerJournalV1<W>,
    profile: CellQ24DatasetProfileV1,
}

impl<W: AnchorWitnessStore> OriginalCellQ24DatasetRecoveryOwnerV1<W> {
    pub fn create(
        file: File,
        witness: W,
        profile: CellQ24DatasetProfileV1,
    ) -> Result<Self, RecoveryError> {
        let binding = owner_binding(&profile)?;
        Ok(Self {
            journal: LearningOwnerJournalV1::create(file, witness, binding)?,
            profile,
        })
    }

    /// Reopen exactly the original owner. Missing or incomplete state is never
    /// treated as a fresh owner or as NoUpdate. Existing journal recovery may
    /// reconcile a completed fsynced suffix with its original witness.
    pub fn recover(
        file: File,
        witness: W,
        profile: CellQ24DatasetProfileV1,
    ) -> Result<Self, RecoveryError> {
        let binding = owner_binding(&profile)?;
        Ok(Self {
            journal: LearningOwnerJournalV1::recover(file, witness, binding)?,
            profile,
        })
    }

    pub fn retain<T: AnchorWitnessStore>(
        &mut self,
        plan: &DatasetFreezePlanV2,
        material: &OriginalCellQ24DatasetV1,
        ledger: &LedgerWriter,
        source: &CircuitTaskSourceReadbackV1<T>,
        identity: &AgentdIdentity,
    ) -> Result<(), RecoveryError> {
        let key = self.key(plan)?;
        if material.profile != self.profile
            || material.dataset.snapshot.snapshot_id != plan.snapshot_id
            || material.dataset.snapshot.objective_digest != plan.objective_digest
            || material.dataset.inclusion_policy_digest != plan.inclusion_policy_digest
        {
            return Err(RecoveryError::Binding("complete original profile and plan"));
        }
        OriginalCellQ24DatasetV1::revalidate(material, ledger, source, identity)?;
        // Encode and reject capacity overflow before commit_once can claim.
        let bytes = codec::encode(&codec::SavedMaterial::from_original(plan, material)?)?;
        let saved = self.journal.commit_once(&key, || Ok(bytes.clone()))?;
        if saved != bytes {
            return Err(RecoveryError::Binding(
                "conflicting retained Dataset material",
            ));
        }
        OriginalCellQ24DatasetV1::revalidate(material, ledger, source, identity)?;
        if self.journal.read(&key)? != bytes {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        Ok(())
    }

    /// Restore from actual owners and the host's original complete plan. No
    /// decoded receipt, record array, batch or digest is accepted as authority.
    pub fn restore<T: AnchorWitnessStore>(
        &mut self,
        plan: &DatasetFreezePlanV2,
        ledger: &LedgerWriter,
        source: &CircuitTaskSourceReadbackV1<T>,
        identity: &AgentdIdentity,
    ) -> Result<OriginalCellQ24DatasetV1, RecoveryError> {
        let key = self.key(plan)?;
        let before = current_ledger(ledger, identity, &self.profile)?;
        let bytes = self.journal.read(&key)?;
        let saved = codec::decode(&bytes)?;
        if saved.profile != self.profile || saved.plan != *plan {
            return Err(RecoveryError::Binding("complete original profile and plan"));
        }
        let prefix = original_prefix(ledger, saved.original_head)?;
        let payload = dataset_freeze_signing_payload_v2(&prefix, plan)?;
        if payload != saved.freeze_payload {
            return Err(RecoveryError::Binding("original freeze payload bytes"));
        }
        let at = now()?;
        let verified = ledger
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &saved.evidence,
                &payload,
                at,
            )
            .map_err(|_| RecoveryError::Binding("current original freeze signature"))?;
        let dataset =
            freeze_dataset_from_ledger(&prefix, plan.clone(), verified.principal().clone(), at)?;
        // This canonical encoding includes every receipt field and the original
        // producer. It is compared byte for byte, never by a receipt digest.
        if codec::receipt_bytes(&dataset)? != saved.receipt {
            return Err(RecoveryError::Binding("complete original Dataset receipt"));
        }
        // Historical validity does not resurrect a corrected/revoked record or
        // withdrawn source. Read the current original owners independently.
        let (batch, publications) = collect(ledger, source, identity, &self.profile, &dataset)?;
        if batch.encoded() != saved.batch {
            return Err(RecoveryError::Binding("complete original batch bytes"));
        }
        let material = OriginalCellQ24DatasetV1 {
            profile: saved.profile,
            dataset,
            evidence: saved.evidence,
            freeze_payload: payload,
            batch,
            publications,
        };
        OriginalCellQ24DatasetV1::revalidate(&material, ledger, source, identity)?;
        if current_ledger(ledger, identity, &self.profile)? != before {
            return Err(RecoveryError::Binding("original ledger frontier changed"));
        }
        if self.journal.read(&key)? != bytes {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        Ok(material)
    }

    fn key(
        &self,
        plan: &DatasetFreezePlanV2,
    ) -> Result<ProductEvaluationExecutionKeyV1, RecoveryError> {
        if plan.objective_digest != self.profile.objective_digest
            || plan.inclusion_policy_digest != self.profile.digest()?
        {
            return Err(RecoveryError::Binding("original signed extraction plan"));
        }
        Ok(ProductEvaluationExecutionKeyV1 {
            plan_id: plan.snapshot_id.clone(),
            binding_digest: owner_binding(&self.profile)?,
        })
    }
}

fn owner_binding(profile: &CellQ24DatasetProfileV1) -> Result<Digest32, RecoveryError> {
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.original-q24-dataset-recovery.v1\0",
        profile.digest()?.as_array(),
    ]))
}

pub(super) fn original_material_bytes(
    material: &OriginalCellQ24DatasetV1,
) -> Result<Vec<u8>, RecoveryError> {
    let plan = DatasetFreezePlanV2 {
        snapshot_id: material.dataset.snapshot.snapshot_id.clone(),
        objective_digest: material.dataset.snapshot.objective_digest,
        inclusion_policy_digest: material.dataset.inclusion_policy_digest,
    };
    codec::encode(&codec::SavedMaterial::from_original(&plan, material)?)
}

pub(super) fn original_prefix(
    ledger: &LedgerWriter,
    head: Digest32,
) -> Result<LedgerSnapshot, RecoveryError> {
    // Only original owner records are replayed. The caller cannot submit a
    // snapshot or reconstruct a convenient history from receipt digests.
    let actual = ledger.snapshot()?;
    let mut replay = LearningLedger::new();
    for record in actual.records() {
        let appended = replay
            .append(record.event.clone())
            .map_err(ProductionLedgerError::from)?;
        if appended.disposition != AppendDisposition::Appended
            || replay.records().last() != Some(record)
        {
            return Err(RecoveryError::Binding("complete original ledger record"));
        }
        if record.chain_digest == head {
            return Ok(replay.snapshot());
        }
    }
    Err(RecoveryError::Binding(
        "original signed head absent from actual ledger",
    ))
}

#[cfg(all(test, unix))]
#[path = "cell_q24_dataset_recovery_tests.rs"]
mod tests;
