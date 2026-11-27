//! A host-frozen local policy over the original Root-enrolled Model proposal.
//! Policy data grants no authority. The original Selector key and independent
//! journal witness remain necessary; this owner cannot select or publish files.

use std::fs::File;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::LearningLocalDecisionV2;
use codex_hepta_learning_artifacts::LearningLocalDispositionV2;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use crate::AgentdRootQ24ModelFactoryV1;
use crate::CellQ24ModelProposalInputsV1;
use crate::CellQ24TrainingOwnerV1;
use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as Error;
use crate::learning_owner_journal::LearningOwnerJournalV1;

#[path = "cell_q24_local_decision_root.rs"]
mod original_root;
#[path = "cell_q24_local_decision_signing.rs"]
mod signing;

/// A finite policy frozen by the existing Selector host before Root enrollment.
/// Retention and deferral keep the independent evaluator's qualified result.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellQ24LocalPolicyV1 {
    AdoptQualified,
    RetainCurrent,
    DeferQualified,
}

impl CellQ24LocalPolicyV1 {
    fn code(self) -> u8 {
        match self {
            Self::AdoptQualified => 1,
            Self::RetainCurrent => 2,
            Self::DeferQualified => 3,
        }
    }

    #[must_use]
    pub fn digest(self) -> Digest32 {
        Digest32::of_parts(&[b"hepta.agentd.q24-local-policy.v1\0", &[self.code()]])
    }

    fn reason(self) -> Digest32 {
        Digest32::of_parts(&[b"hepta.agentd.q24-local-policy-reason.v1\0", &[self.code()]])
    }

    fn disposition(self) -> LearningLocalDispositionV2 {
        match self {
            Self::AdoptQualified => LearningLocalDispositionV2::AdoptCandidate,
            Self::RetainCurrent => LearningLocalDispositionV2::RetainParent,
            Self::DeferQualified => LearningLocalDispositionV2::DeferCandidate,
        }
    }
}

#[derive(Clone)]
pub struct OriginalCellQ24LocalDecisionConfigV1 {
    pub initial: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub policy: CellQ24LocalPolicyV1,
    pub signer: TrustedLearningSignerV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub maximum_signature_lifetime_seconds: u64,
}

pub struct OriginalCellQ24LocalDecisionOwnerV1<W: AnchorWitnessStore> {
    journal: LearningOwnerJournalV1<W>,
    config: OriginalCellQ24LocalDecisionConfigV1,
    key: SigningKey,
    binding: Digest32,
}

impl<W: AnchorWitnessStore> OriginalCellQ24LocalDecisionOwnerV1<W> {
    pub(crate) fn policy_digest(&self) -> Digest32 {
        self.config.policy.digest()
    }

    pub(crate) fn require_context(
        &self,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> Result<(), Error> {
        if &self.config.initial != initial || &self.config.scope != scope {
            return Err(Error::Binding("original local policy scope"));
        }
        self.config.verifier.require_signer_binding(
            LearningEvidenceRoleV1::Selector,
            &self.config.signer,
            now()?,
        )?;
        Ok(())
    }

    pub fn create(
        file: File,
        witness: W,
        config: OriginalCellQ24LocalDecisionConfigV1,
        key: SigningKey,
        factory: &AgentdRootQ24ModelFactoryV1,
    ) -> Result<Self, Error> {
        let binding = validate(&config, &key, factory)?;
        Ok(Self {
            journal: LearningOwnerJournalV1::create(file, witness, binding)?,
            config,
            key,
            binding,
        })
    }

    pub fn recover(
        file: File,
        witness: W,
        config: OriginalCellQ24LocalDecisionConfigV1,
        key: SigningKey,
        factory: &AgentdRootQ24ModelFactoryV1,
    ) -> Result<Self, Error> {
        let binding = validate(&config, &key, factory)?;
        Ok(Self {
            journal: LearningOwnerJournalV1::recover(file, witness, binding)?,
            config,
            key,
            binding,
        })
    }

    /// The source is the live original factory and trainer, never a caller's
    /// purported Proposal receipt. Revalidation does not rerun fitting or B.
    pub async fn attest_original_decision<T: AnchorWitnessStore, S: FinalHoldoutCasStoreV1>(
        &mut self,
        factory: &mut AgentdRootQ24ModelFactoryV1,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        dataset: &LearningIterationSnapshotV1,
        inputs: &CellQ24ModelProposalInputsV1<'_, S>,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let proposal = self
            .original_proposal(factory, trainer, dataset, inputs, snapshot)
            .await?;
        let saved = self.saved(&proposal);
        let bytes = self.sign_original_proposal(&proposal, &saved)?;
        if self
            .original_proposal(factory, trainer, dataset, inputs, snapshot)
            .await?
            != proposal
        {
            return Err(Error::CommitUncertain);
        }
        self.authenticate(snapshot, &proposal, &saved, &bytes)
    }

    /// A missing or Pending decision stays unresolved. History cannot cause
    /// recovery to sign a replacement or substitute the currently chosen policy.
    pub async fn readback<T: AnchorWitnessStore, S: FinalHoldoutCasStoreV1>(
        &mut self,
        factory: &mut AgentdRootQ24ModelFactoryV1,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        dataset: &LearningIterationSnapshotV1,
        inputs: &CellQ24ModelProposalInputsV1<'_, S>,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let proposal = self
            .original_proposal(factory, trainer, dataset, inputs, snapshot)
            .await?;
        let saved = self.saved(&proposal);
        let bytes = self.journal.read(&saved)?;
        if self
            .original_proposal(factory, trainer, dataset, inputs, snapshot)
            .await?
            != proposal
        {
            return Err(Error::CommitUncertain);
        }
        self.authenticate(snapshot, &proposal, &saved, &bytes)
    }

    async fn original_proposal<T: AnchorWitnessStore, S: FinalHoldoutCasStoreV1>(
        &self,
        factory: &mut AgentdRootQ24ModelFactoryV1,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        dataset: &LearningIterationSnapshotV1,
        inputs: &CellQ24ModelProposalInputsV1<'_, S>,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<LearningIterationSnapshotV1, Error> {
        let prefix = self.proposal_prefix(factory, snapshot)?;
        let original = factory
            .readback(trainer, dataset, inputs)
            .await
            .map_err(|error| {
                if crate::cell_q24_learning_owner_error::is_commit_uncertain(&error) {
                    Error::CommitUncertain
                } else {
                    Error::Binding("original Model proposal unavailable")
                }
            })?;
        self.require_original_proposal(prefix, &original)
    }

    fn proposal_prefix(
        &self,
        factory: &AgentdRootQ24ModelFactoryV1,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<LearningIterationCoordinatorV1, Error> {
        factory
            .require_learning_scope(&self.config.initial, &self.config.scope)
            .map_err(|_| Error::Binding("local policy original Root operation"))?;
        factory
            .require_local_policy(self.config.policy.digest())
            .map_err(|_| Error::Binding("local policy original Root reservation"))?;
        self.config
            .scope
            .validate_snapshot(snapshot)
            .map_err(|_| Error::Binding("local decision scope"))?;
        LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())
            .map_err(|_| Error::Binding("local decision history"))?;
        if snapshot.request != self.config.initial.request
            || snapshot.owners != self.config.initial.owners
        {
            return Err(Error::Binding("local decision operation"));
        }
        let mut prefix = LearningIterationCoordinatorV1::from_snapshot(self.config.initial.clone())
            .map_err(|_| Error::Binding("local decision initial cut"))?;
        for retained in &snapshot.receipts {
            prefix
                .record(retained.clone(), retained.observed_unix_seconds)
                .map_err(|_| Error::Binding("local decision prefix"))?;
            if retained.observation.stage() == LearningIterationStageV1::Proposal {
                break;
            }
        }
        Ok(prefix)
    }

    fn require_original_proposal(
        &self,
        prefix: LearningIterationCoordinatorV1,
        original: &crate::CellQ24ModelProposalReceiptV1,
    ) -> Result<LearningIterationSnapshotV1, Error> {
        if prefix.snapshot().receipts.last() != Some(original.learning_receipt())
            || prefix.next_stage() != Some(LearningIterationStageV1::Selection)
            || prefix.next_task_bundle() == Some(&self.config.initial.request.selected_bundle)
        {
            return Err(Error::Binding(
                "local policy requires the original qualified proposal",
            ));
        }
        Ok(prefix.snapshot().clone())
    }

    fn saved(&self, proposal: &LearningIterationSnapshotV1) -> ProductEvaluationExecutionKeyV1 {
        ProductEvaluationExecutionKeyV1 {
            plan_id: self.config.initial.request.operation_id.clone(),
            binding_digest: Digest32::of_parts(&[
                b"hepta.agentd.q24-local-decision.v1\0",
                self.binding.as_array(),
                proposal.head_digest.as_array(),
            ]),
        }
    }

    fn authenticate(
        &mut self,
        snapshot: &LearningIterationSnapshotV1,
        proposal: &LearningIterationSnapshotV1,
        saved: &ProductEvaluationExecutionKeyV1,
        bytes: &[u8],
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let (original, signed) = learning_owner_evidence::decode(bytes)?;
        let receipt = decision(self.config.policy, proposal, signed.issued_at)?;
        if payload(&receipt)? != original
            || signed.evidence_id != evidence_id(saved.binding_digest)?
            || snapshot
                .receipts
                .get(proposal.receipts.len())
                .is_some_and(|retained| retained != &receipt)
            || self.journal.read(saved)? != bytes
        {
            return Err(Error::Binding("exact original local decision"));
        }
        let verified = self.config.verifier.verify(
            LearningEvidenceRoleV1::Selector,
            &signed,
            &original,
            now()?,
        )?;
        if verified.principal() != &self.config.signer.principal
            || verified.controller_id() != &self.config.signer.controller_id
        {
            return Err(Error::Binding("original local Selector"));
        }
        Ok((receipt, signed))
    }
}

fn decision(
    policy: CellQ24LocalPolicyV1,
    proposal: &LearningIterationSnapshotV1,
    at: u64,
) -> Result<LearningIterationReceiptV1, Error> {
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(proposal.clone())
        .map_err(|_| Error::Binding("local proposal cut"))?;
    let candidate = coordinator
        .candidate()
        .ok_or(Error::Binding("local proposal candidate"))?
        .digest()
        .map_err(|_| Error::Binding("local proposal bundle"))?;
    let selected = match policy {
        CellQ24LocalPolicyV1::AdoptQualified => candidate,
        CellQ24LocalPolicyV1::RetainCurrent | CellQ24LocalPolicyV1::DeferQualified => proposal
            .request
            .selected_bundle
            .digest()
            .map_err(|_| Error::Binding("local original baseline"))?,
    };
    let receipt = LearningIterationReceiptV1 {
        operation_id: proposal.request.operation_id.clone(),
        actor_id: proposal.owners.selector.clone(),
        predecessor: proposal.head_digest,
        evidence_digest: Digest32::of_parts(&[
            b"hepta.agentd.q24-local-decision-evidence.v1\0",
            proposal.head_digest.as_array(),
            policy.digest().as_array(),
            policy.reason().as_array(),
        ]),
        observed_unix_seconds: at,
        observation: LearningIterationObservationV1::LocalDecisionV2(LearningLocalDecisionV2 {
            proposal_head: proposal.head_digest,
            candidate_bundle: candidate,
            selected_bundle: selected,
            policy_digest: policy.digest(),
            reason_digest: policy.reason(),
            disposition: policy.disposition(),
        }),
    };
    coordinator
        .record(receipt.clone(), at)
        .map_err(|_| Error::Binding("local decision extension"))?;
    Ok(receipt)
}

fn validate(
    config: &OriginalCellQ24LocalDecisionConfigV1,
    key: &SigningKey,
    factory: &AgentdRootQ24ModelFactoryV1,
) -> Result<Digest32, Error> {
    factory
        .require_learning_scope(&config.initial, &config.scope)
        .map_err(|_| Error::Binding("local decision Root scope"))?;
    factory
        .require_local_policy(config.policy.digest())
        .map_err(|_| Error::Binding("local decision Root policy"))?;
    if key.verifying_key().to_bytes() != config.signer.verifying_key
        || config.initial.owners.selector != config.signer.principal.principal_id
        || config.initial.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.initial.request.envelope.objective_digest != config.verifier.objective_digest()
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
    {
        return Err(Error::Binding("original local Selector capability"));
    }
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Selector,
        &config.signer,
        now()?,
    )?;
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.q24-local-decision-owner.v1\0",
        config.initial.head_digest.as_array(),
        config.scope.binding().as_array(),
        config.policy.digest().as_array(),
        config.verifier.trust_digest().as_array(),
        &config.maximum_signature_lifetime_seconds.to_be_bytes(),
    ]))
}

fn payload(receipt: &LearningIterationReceiptV1) -> Result<Vec<u8>, Error> {
    learning_iteration_receipt_signing_bytes_v1(receipt)
        .map_err(|_| Error::Binding("local decision encoding"))
}

fn evidence_id(binding: Digest32) -> Result<StableId, Error> {
    StableId::new(format!("original-local-decision:{binding}"))
        .map_err(|_| Error::Binding("local evidence id"))
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("local decision clock"))
}

#[cfg(test)]
#[path = "cell_q24_local_decision_owner_tests.rs"]
mod tests;
