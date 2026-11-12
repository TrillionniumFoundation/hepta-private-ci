//! One original Selector operation over actual Model/E and version peers.
//! The Model's opaque transfer owns its full E body until real Finish. No
//! request can supply a qualification seal, a Model owner or signing material.

use codex_hepta_neuron::AnchorWitnessStore;

use super::*;
use crate::OriginalCellQ24ModelCommandClientV1;
use crate::OriginalCellQ24ModelReadV1;
use crate::OriginalCellQ24ModelReadCompletionV1;
use crate::OriginalCellEvaluationModelMaterialV1;
use crate::OriginalCircuitModelPublicationContextV1;
use crate::OriginalCircuitCandidateLearningReadClientV1;
use crate::OriginalCircuitCandidateLearningReadContextV1;

pub(crate) struct OriginalCircuitModelSelectionRemoteSourcesV1<'a> {
    pub(crate) context: &'a OriginalCircuitCandidateLearningReadContextV1,
    pub(crate) model: &'a OriginalCellQ24ModelCommandClientV1,
    pub(crate) live: &'a OriginalCircuitCandidateLearningReadClientV1,
}

fn unavailable(_: impl std::fmt::Display) -> Error {
    OwnerError::Binding("original positive Model/retention/version source").into()
}

impl<W: AnchorWitnessStore> OriginalCircuitModelSelectionReceiptOwnerV1<W> {
    pub(crate) async fn attest_original_remote_selection(
        &mut self,
        source: OriginalCircuitModelSelectionRemoteSourcesV1<'_>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        if self.readback_only {
            return Err(OwnerError::Binding("recovered original Model Selector is readback only").into());
        }
        self.remote_result(source, /*execute*/ true).await
    }

    pub(crate) async fn readback_remote(
        &mut self,
        source: OriginalCircuitModelSelectionRemoteSourcesV1<'_>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        self.remote_result(source, /*execute*/ false).await
    }

    async fn remote_result(
        &mut self,
        source: OriginalCircuitModelSelectionRemoteSourcesV1<'_>,
        execute: bool,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        if self.fenced {
            return Err(OwnerError::CommitUncertain.into());
        }
        let existing = match self.journal.read(&self.saved) {
            Ok(bytes) => Some(bytes),
            Err(OwnerError::Store(ProductEvaluationExecutionStoreErrorV1::Missing)) if execute => None,
            Err(error) => return Err(error.into()),
        };
        // Cancellation, a failed source or an unknown claim never restores a
        // reusable operation. Only successful full closure clears this flag.
        self.fenced = true;
        let result = self.remote_operation(source, existing, execute).await;
        if result.is_ok() {
            self.fenced = false;
        }
        result
    }

    async fn remote_operation(
        &mut self,
        source: OriginalCircuitModelSelectionRemoteSourcesV1<'_>,
        existing: Option<Vec<u8>>,
        execute: bool,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let started = binding::now()?;
        let context: &OriginalCircuitModelPublicationContextV1 = source.context.model_publication_context();
        source.context.authenticate(started).map_err(unavailable)?;
        OriginalCircuitCandidateLearningReadClientV1::require_original_context(source.live, source.context).map_err(unavailable)?;
        if source.context.prefix() != source.context.decision()
            || context.decision() != &self.config.decision
            || context.scope() != &self.config.scope
            || context.verifier().trust_digest() != self.config.verifier.trust_digest()
            || context.verifier().scope_digest() != self.config.verifier.scope_digest()
            || context.verifier().objective_digest() != self.config.verifier.objective_digest()
            || context.signatures()[2] != self.config.training_evidence
            || context.signatures()[3] != self.config.evaluation_evidence
        {
            return Err(OwnerError::Binding("same original positive Model Selector context").into());
        }
        let operation: OriginalCellQ24ModelReadV1<'_> =
            OriginalCellQ24ModelCommandClientV1::begin_original_model_read(source.model).await.map_err(unavailable)?;
        if operation.model() != context.model() {
            return Err(OwnerError::Binding("same actual original Model").into());
        }
        operation.require_current(started).map_err(unavailable)?;
        context.authenticate_material(operation.material(), started, execute).map_err(unavailable)?;
        OriginalCellEvaluationModelMaterialV1::require_original_selector_material(
            operation.material(), &self.config, binding::now()?,
        )
            .map_err(unavailable)?;
        let before = OriginalCircuitCandidateLearningReadClientV1::read_current(source.live).await.map_err(unavailable)?;
        let original = (
            context.signatures()[2].clone(),
            context.signatures()[3].clone(),
        );
        let config = &self.config;
        let key = &self.key;
        let identity = self.saved.binding_digest;
        let bytes = match existing {
            Some(bytes) => bytes,
            None => self.journal.commit_once(&self.saved, || {
                let issued_at = binding::now()?;
                binding::new_work_time(config, started, issued_at)?;
                operation.require_current(started)
                    .map_err(|_| OwnerError::Binding("same original Model operation before signing"))?;
                let expiry = context.authenticate_material(operation.material(), issued_at, /*new_work*/ true)
                    .map_err(|_| OwnerError::Binding("current complete original Model panel"))?
                    .min(config.decision.request.envelope.expiry_unix_seconds)
                    .min(binding::signature_expiry(config, issued_at)?);
                OriginalCellEvaluationModelMaterialV1::require_original_selector_material(
                    operation.material(), config, issued_at,
                )
                    .map_err(|_| OwnerError::Binding("same original Selector primary material"))?;
                binding::authenticate_roles(config, &original, issued_at)
                    .map_err(|_| OwnerError::Binding("current independent original Selector roles"))?;
                let receipt = binding::receipt(config, before.observation(), issued_at)
                    .map_err(|_| OwnerError::Binding("actual original positive publication"))?;
                let payload = learning_iteration_receipt_signing_bytes_v1(&receipt)
                    .map_err(|_| OwnerError::Binding("original positive Selector payload"))?;
                let signed = binding::sign_original_until(config, key, &payload, identity, issued_at, expiry)?;
                learning_owner_evidence::encode(&payload, &signed)
            })?,
        };
        let (payload, signed) = learning_owner_evidence::decode(&bytes)?;
        let receipt = binding::receipt(config, before.observation(), signed.issued_at)?;
        if payload != learning_iteration_receipt_signing_bytes_v1(&receipt)? {
            return Err(OwnerError::Binding("exact original positive Selector receipt").into());
        }
        let after = OriginalCircuitCandidateLearningReadClientV1::read_current(source.live).await.map_err(unavailable)?;
        if after != before {
            return Err(OwnerError::CommitUncertain.into());
        }
        let completed: OriginalCellQ24ModelReadCompletionV1 = operation.finish().await.map_err(unavailable)?;
        if completed.model() != context.model() || self.journal.read(&self.saved)? != bytes {
            return Err(OwnerError::CommitUncertain.into());
        }
        // The final physical journal read is above. Everything below is pure
        // verification at the final clock, including all original nested windows.
        let current = binding::now()?;
        if current < started {
            return Err(OwnerError::Binding("original Model Selector clock regressed").into());
        }
        let expiry = context.authenticate_material(completed.material(), current, execute)
            .map_err(unavailable)?
            .min(config.decision.request.envelope.expiry_unix_seconds)
            .min(binding::signature_expiry(config, signed.issued_at)?);
        OriginalCellEvaluationModelMaterialV1::require_original_selector_material(
            completed.material(), config, current,
        ).map_err(unavailable)?;
        let (training, evaluation) = binding::authenticate_roles(config, &original, current)?;
        let selector = config.verifier.verify(
            LearningEvidenceRoleV1::Selector, &signed, &payload, current,
        )?;
        if signed.expires_at != expiry
            || signed.evidence_id != binding::evidence_id(identity)?
            || selector.principal() != &config.signer.principal
            || selector.controller_id() != &config.signer.controller_id
        {
            return Err(OwnerError::Binding("original full-panel Selector signature window").into());
        }
        verify_signed_actor_separation(&training, &selector, current)?;
        verify_signed_actor_separation(&evaluation, &selector, current)?;
        Ok((receipt, signed))
    }
}
