//! Public trust data for the newly registered historical-learning recipient.
//! Only an actual Root response may place its activation in a private capsule;
//! this data conversion cannot create that capability or reuse Initial's one.

use std::io;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::root_initial_learning_trust_data::LearningTrustPayloadV1;
use crate::root_initial_learning_trust_data::LearningTrustRoleSelectionV1;

pub(crate) const TRUST_PURPOSE: &str = "runtime.learning.historical-trust-read.v1";

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct HistoricalLearningTrustPayloadV1 {
    pub(crate) signed: LearningTrustPayloadV1,
    pub(crate) freeze_evaluator: LearningTrustRoleSelectionV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct HistoricalLearningTrustPinV1 {
    pub(crate) initial: String,
    pub(crate) target: String,
    pub(crate) mapping: String,
    pub(crate) payload: String,
    pub(crate) root: String,
    pub(crate) distribution: String,
    pub(crate) trust: String,
    pub(crate) learning_scope: String,
    pub(crate) objective: String,
    pub(crate) freeze_evaluator: String,
}

impl HistoricalLearningTrustPinV1 {
    pub(crate) fn require_initial(&self, initial: &LearningIterationSnapshotV1) -> io::Result<()> {
        for value in [
            &self.initial,
            &self.target,
            &self.mapping,
            &self.payload,
            &self.root,
            &self.distribution,
            &self.trust,
            &self.learning_scope,
            &self.objective,
            &self.freeze_evaluator,
        ] {
            let digest: Digest32 = value.parse().map_err(io::Error::other)?;
            if digest.is_zero() || digest.to_string() != *value {
                return Err(io::Error::other("noncanonical current recipient trust pin"));
            }
        }
        if !initial.receipts.is_empty()
            || self.initial != initial.head_digest.to_string()
            || self.trust != initial.owners.evidence_trust_digest.to_string()
            || self.objective != initial.request.envelope.objective_digest.to_string()
        {
            return Err(io::Error::other(
                "current recipient trust differs from original profile",
            ));
        }
        Ok(())
    }
}

impl HistoricalLearningTrustPayloadV1 {
    pub(crate) fn freeze_evaluator_digest(&self) -> io::Result<Digest32> {
        Ok(Digest32::of_parts(&[
            b"hepta.root.historical-freeze-evaluator.v1\0",
            &serde_json::to_vec(&self.freeze_evaluator).map_err(io::Error::other)?,
        ]))
    }

    /// Explicit genesis only. No absent previous generation can authorize a
    /// rotation; the Root-held mapping and pin must remain byte-for-byte fixed.
    pub(crate) fn activate_for_recipient(
        &self,
        initial: &LearningIterationSnapshotV1,
        now_seconds: u64,
    ) -> io::Result<(ActivatedLearningTrustV1, TrustedLearningSignerV1)> {
        let (activated, _, _) = self.signed.activate_pinned_genesis(now_seconds)?;
        if !initial.receipts.is_empty()
            || activated.verifier().trust_digest() != initial.owners.evidence_trust_digest
            || activated.verifier().objective_digest() != initial.request.envelope.objective_digest
        {
            return Err(io::Error::other(
                "activated trust differs from current Root recipient",
            ));
        }
        let mut matching = self.signed.distribution.signers.iter().filter(|signer| {
            signer.principal_id == self.freeze_evaluator.principal_id
                && signer.controller_id == self.freeze_evaluator.controller_id
        });
        let signer = matching
            .next()
            .ok_or_else(|| io::Error::other("fixed freeze Evaluator absent"))?;
        if matching.next().is_some() {
            return Err(io::Error::other("fixed freeze Evaluator ambiguous"));
        }
        let signer = signer.original_signer()?;
        activated
            .verifier()
            .require_signer_binding(LearningEvidenceRoleV1::Evaluator, &signer, now_seconds)
            .map_err(io::Error::other)?;
        Ok((activated, signer))
    }

    pub(crate) fn require_activation_pin(
        &self,
        initial: &LearningIterationSnapshotV1,
        activated: &ActivatedLearningTrustV1,
        pin: &HistoricalLearningTrustPinV1,
    ) -> io::Result<()> {
        pin.require_initial(initial)?;
        if activated.root_digest().to_string() != pin.root
            || activated.distribution_digest().to_string() != pin.distribution
            || activated.verifier().trust_digest().to_string() != pin.trust
            || activated.verifier().scope_digest().to_string() != pin.learning_scope
            || activated.verifier().objective_digest().to_string() != pin.objective
            || self.freeze_evaluator_digest()?.to_string() != pin.freeze_evaluator
        {
            return Err(io::Error::other(
                "actual activated recipient trust pin differs",
            ));
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct HistoricalLearningTrustResponseV1 {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) request_id: u64,
    pub(crate) profile: String,
    pub(crate) pin: HistoricalLearningTrustPinV1,
    pub(crate) payload: HistoricalLearningTrustPayloadV1,
}
