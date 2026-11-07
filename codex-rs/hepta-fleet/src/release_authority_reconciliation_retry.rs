//! A fresh authorization can retry only the one exact retained replacement.
//! Neither original signed material nor either proposal is replaced here.

use sha2::Digest;
use sha2::Sha256;

use super::PendingIntentReconciliation;
use super::ReleaseAuthority;
use super::load;
use crate::FleetRegistryError;
use crate::ReleaseIntentAnchorV1;
use crate::release_authority::invalid;
use crate::release_authority_set::record_bytes;
use crate::release_authority_store::IntentRecoveryWinner;

impl PendingIntentReconciliation {
    pub fn replacement_intent_anchor(&self) -> Option<&ReleaseIntentAnchorV1> {
        self.replacement.as_ref().map(|(_, record)| &record.anchor)
    }

    pub fn replacement_publication_sha256(&self) -> Result<Option<[u8; 32]>, FleetRegistryError> {
        self.replacement
            .as_ref()
            .map(|(update, _)| {
                let bytes = serde_json::to_vec(update).map_err(|error| {
                    invalid(format!("replacement update serialization failed: {error}"))
                })?;
                let mut hash = Sha256::new();
                hash.update(b"hepta.fleet.release-intent-reconciliation-update.v1\0");
                hash.update(bytes);
                Ok(hash.finalize().into())
            })
            .transpose()
    }

    pub fn retained_reconciliation_sha256(&self) -> Result<Option<[u8; 32]>, FleetRegistryError> {
        let Some(replacement) = self.replacement_publication_sha256()? else {
            return Ok(None);
        };
        let proposal = self
            .files
            .replacement_proposal
            .as_deref()
            .ok_or(FleetRegistryError::ReleaseAuthorityRecoveryRequired)?;
        let mut hash = Sha256::new();
        hash.update(b"hepta.fleet.release-intent-retained-reconciliation.v1\0");
        hash.update(self.pending_publication_sha256()?);
        hash.update(replacement);
        hash.update(load::hash(proposal));
        match self.files.replacement_attempt.as_deref() {
            Some(bytes) => {
                hash.update([1]);
                hash.update(load::hash(bytes));
            }
            None => {
                hash.update([0]);
                hash.update([0; 32]);
            }
        }
        Ok(Some(hash.finalize().into()))
    }
}

impl ReleaseAuthority {
    pub fn retry_retained_intent_publication(
        &self,
        mut admission: PendingIntentReconciliation,
        fresh_decision_sha256: [u8; 32],
        expected_anchor_sha256: [u8; 32],
        original_pending_sha256: [u8; 32],
        replacement_pending_sha256: [u8; 32],
        retained_state_sha256: [u8; 32],
    ) -> Result<(), FleetRegistryError> {
        admission.decision_window.ok_or_else(|| {
            invalid("retained publication retry requires its verified decision validity window")
        })?;
        self.recheck_intent_reconciliation(&admission)?;
        let (replacement, record) = admission
            .replacement
            .as_ref()
            .ok_or_else(|| invalid("there is no retained replacement to retry"))?;
        let expected = match admission.expected_intent_anchor() {
            Some(anchor) => anchor.sha256()?,
            None => ReleaseIntentAnchorV1::absent_sha256(&admission.original.anchor.agent_id),
        };
        if expected_anchor_sha256 != expected
            || admission.pending_publication_sha256()? != original_pending_sha256
            || admission.replacement_publication_sha256()? != Some(replacement_pending_sha256)
            || admission.retained_reconciliation_sha256()? != Some(retained_state_sha256)
            || fresh_decision_sha256 == [0; 32]
            || record.recovery_decision_sha256 == Some(fresh_decision_sha256)
            || record.publication_confirmation_sha256 == Some(fresh_decision_sha256)
            || admission
                .original
                .anchor
                .terminal_witness
                .as_ref()
                .is_some_and(|witness| {
                    witness.recovery_decision_sha256 == Some(fresh_decision_sha256)
                        || witness.publication_confirmation_sha256 == Some(fresh_decision_sha256)
                })
        {
            return Err(invalid(
                "retry does not bind the exact retained state and a distinct fresh decision",
            ));
        }
        let replacement = replacement.clone();
        let bytes = record_bytes(&replacement)?;
        // A proposal-only crash is completed with create_new. An existing
        // attempt must already have these exact canonical bytes; it is never
        // erased, replaced, or interpreted as evidence of non-execution.
        self.files
            .retain_exact_intent_reconciliation_attempt(&bytes)?;
        admission.files.replacement_attempt = Some(bytes);
        // Trusted time is read again after all reads/hashes and file fsyncs.
        // Expiry leaves both proposals fenced and issues no external CAS.
        self.recheck_intent_reconciliation(&admission)?;
        if self
            .frontier
            .compare_and_set(
                &self.config.owner_id,
                &replacement.expected,
                &Some(replacement.proposed),
            )
            .is_err()
            || self.recovery_frontier()? != replacement.proposed
        {
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        self.files
            .finish_intent_winner(IntentRecoveryWinner::ReplacementProposal)?;
        drop(admission.lock);
        Ok(())
    }
}
