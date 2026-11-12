//! Original completed execution evidence retained without another execution.
//! Only the actual runner can construct this value after authenticating its
//! existing store and holdout. Revalidation never claims, signs or renews.

use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_types::AuthorityPosture;

use super::*;

/// Exact original execution signature and record identity, with private fields
/// and no deserializer. This is evidence, never a grant or a CURRENT lease.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalProductEvaluationExecutionEvidenceV1 {
    key: ProductEvaluationExecutionKeyV1,
    record_digest: Digest32,
    evaluator: AuthenticatedPrincipalV1,
    objective_digest: Digest32,
    payload: Vec<u8>,
    record: Vec<u8>,
    attestation: SignedLearningEvidenceV1,
}

impl OriginalProductEvaluationExecutionEvidenceV1 {
    pub fn key(&self) -> &ProductEvaluationExecutionKeyV1 {
        &self.key
    }
    pub fn record_digest(&self) -> Digest32 {
        self.record_digest
    }
    pub fn attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.attestation
    }
    /// Exact original bytes, for a closed readonly host's evidence export.
    /// This creates no execution, signature or deserializable owner capability.
    pub fn signing_payload(&self) -> &[u8] {
        &self.payload
    }
    pub fn original_record(&self) -> &[u8] {
        &self.record
    }
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    /// Pure verification of the same original bytes under current host trust
    /// and time. A caller must separately reread the original physical owners.
    pub fn revalidate(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<VerifiedLearningEvidenceV1, ProductEvaluationError> {
        let verified = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &self.attestation,
                &self.payload,
                now,
            )
            .map_err(SignedEvaluationError::from)?;
        if verified.principal() != &self.evaluator
            || verified.objective_digest() != self.objective_digest
        {
            return Err(ProductEvaluationError::Binding(
                "original completed execution evidence",
            ));
        }
        Ok(verified)
    }
}

impl<S: FinalHoldoutCasStoreV1> ProductEvaluationRunnerV1<S> {
    /// Read the existing execution and retain its exact original signature.
    /// Missing and Pending remain errors. No provider, signer, callback with
    /// mutation authority, claim or complete operation is accepted.
    pub fn readback_temporal_comparison_evidence(
        &mut self,
        request: &ProductEvaluationExecutionRequestV1<'_>,
        executions: &mut impl ProductEvaluationExecutionStoreV1,
    ) -> Result<
        (
            ProductTemporalEvaluationReceiptV1,
            OriginalProductEvaluationExecutionEvidenceV1,
        ),
        ProductEvaluationExecutionErrorV1,
    > {
        let (key, _) = self.execution_context(request)?;
        let bytes = match executions.readback(&key)? {
            ProductEvaluationExecutionStateV1::Pending => {
                return Err(ProductEvaluationExecutionErrorV1::Pending);
            }
            ProductEvaluationExecutionStateV1::Completed(bytes) => bytes,
        };
        let receipt = self.authenticate_completed_execution(request, key.clone(), &bytes)?;
        let (attestation, body) = execution_codec::decode_envelope(&bytes)?;
        let original = OriginalProductEvaluationExecutionEvidenceV1 {
            payload: signing_payload(&key, body),
            record: bytes.clone(),
            key,
            record_digest: Digest32::of_bytes(&bytes),
            evaluator: request.evaluator.clone(),
            objective_digest: request.plan.frozen_plan.objective_digest,
            attestation,
        };
        // The earlier authentication can precede blocking holdout reads.
        // Recheck the original window after all original execution I/O.
        let now = (request.clock)().map_err(ProductEvaluationError::from)?;
        original.revalidate(request.verifier, now)?;
        Ok((receipt, original))
    }
}
