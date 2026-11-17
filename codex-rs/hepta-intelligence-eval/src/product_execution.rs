//! Original-owner execution persistence. A claimed but incomplete operation is
//! never redispatched. Stored bytes are authenticated before private decoding;
//! neither a file, a checksum nor this readback supplies independent qualification.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use super::FinalHoldoutCasStoreV1;
use super::FinalHoldoutJournalReceiptV1;
use super::ProductEvaluationError;
use super::ProductEvaluationRunnerV1;
use super::ProductFrozenEvaluationPlanV1;
use super::ProductProviderErrorV1;
use super::ProductTemporalEvaluationReceiptV1;
use super::TemporalEvaluationPlan;
use super::execution_codec;
use crate::FinalHoldoutProviderV1;
use crate::SignedEvaluationError;

use crate::ProductEvaluationExecutionClaimV1;
use crate::ProductEvaluationExecutionKeyV1;
use crate::ProductEvaluationExecutionStateV1;
use crate::ProductEvaluationExecutionStoreErrorV1;
use crate::ProductEvaluationExecutionStoreV1;

/// Host-pinned original evaluator, current trust and clock; never read these from
/// the execution blob. Restoring a signed execution is not a new validity window.
pub struct ProductEvaluationExecutionRequestV1<'a> {
    pub plan: &'a ProductFrozenEvaluationPlanV1,
    pub candidate_plan: &'a TemporalEvaluationPlan,
    pub baseline_plan: &'a TemporalEvaluationPlan,
    pub evaluator: &'a AuthenticatedPrincipalV1,
    pub verifier: &'a LearningEvidenceVerifierV1,
    pub clock: &'a dyn Fn() -> Result<u64, ProductProviderErrorV1>,
}

/// Constructed only after the original runner produces the sealed execution.
/// The owner must reconcile this exact result against its own operation before
/// signing; this request is not a generic caller-supplied bytes signing service.
pub struct ProductEvaluationExecutionAttestationRequestV1<'a> {
    key: &'a ProductEvaluationExecutionKeyV1,
    execution: &'a ProductTemporalEvaluationReceiptV1,
    signing_payload: Vec<u8>,
}

impl ProductEvaluationExecutionAttestationRequestV1<'_> {
    #[must_use]
    pub fn key(&self) -> &ProductEvaluationExecutionKeyV1 {
        self.key
    }

    #[must_use]
    pub fn execution(&self) -> &ProductTemporalEvaluationReceiptV1 {
        self.execution
    }

    #[must_use]
    pub fn signing_payload(&self) -> &[u8] {
        &self.signing_payload
    }
}

/// Original evaluator signing capability. Implementations re-read their own
/// completed execution and sign the supplied canonical request only on an exact
/// match. This crate constructs neither a signer nor its trust or signing key.
pub trait ProductEvaluationExecutionAttestorV1 {
    fn attest_execution(
        &mut self,
        request: &ProductEvaluationExecutionAttestationRequestV1<'_>,
    ) -> Result<SignedLearningEvidenceV1, ProductProviderErrorV1>;
}

/// Derive the exact original execution identity before a host supplies its
/// evaluator capability. This is a binding calculation, not a claim, signing
/// request or authorization to consume the holdout.
pub fn product_evaluation_execution_key_v1(
    plan: &ProductFrozenEvaluationPlanV1,
    namespace: Digest32,
    evaluator: &AuthenticatedPrincipalV1,
) -> Result<ProductEvaluationExecutionKeyV1, ProductEvaluationError> {
    plan.validate_integrity()?;
    if namespace.is_zero() {
        return Err(ProductEvaluationError::Binding(
            "original execution namespace",
        ));
    }
    evaluator
        .validate(evaluator.authenticated_at)
        .map_err(|_| ProductEvaluationError::Binding("original execution evaluator"))?;
    let mut binding = b"hepta.intelligence-eval.execution-key.v1".to_vec();
    binding.extend_from_slice(namespace.as_array());
    binding.extend_from_slice(plan.receipt_seal.as_array());
    super::push_principal(&mut binding, evaluator);
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: plan.frozen_plan.plan_id.clone(),
        binding_digest: Digest32::of_bytes(&binding),
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductEvaluationExecutionErrorV1 {
    Pending,
    MissingExecution,
    Evaluation(ProductEvaluationError),
    Store(ProductEvaluationExecutionStoreErrorV1),
}

impl fmt::Display for ProductEvaluationExecutionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductEvaluationExecutionErrorV1 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Pending | Self::MissingExecution => None,
            Self::Evaluation(error) => Some(error),
            Self::Store(error) => Some(error),
        }
    }
}

impl From<ProductEvaluationError> for ProductEvaluationExecutionErrorV1 {
    fn from(error: ProductEvaluationError) -> Self {
        Self::Evaluation(error)
    }
}
impl From<ProductEvaluationExecutionStoreErrorV1> for ProductEvaluationExecutionErrorV1 {
    fn from(error: ProductEvaluationExecutionStoreErrorV1) -> Self {
        Self::Store(error)
    }
}

impl<S: FinalHoldoutCasStoreV1> ProductEvaluationRunnerV1<S> {
    /// Execute only a new durable claim, or authenticate the original completion.
    /// Pending includes a crash before consumption and uncertain provider/signing
    /// results. It requires original-owner reconciliation, never automatic retry.
    /// Completion acknowledgement loss is recovered by readback without another
    /// provider release, estimator run or signing request. Qualification remains
    /// on the existing signed, role-separated `qualify_and_persist` path.
    pub fn evaluate_or_readback_temporal_comparison<
        P: FinalHoldoutProviderV1,
        E: ProductEvaluationExecutionStoreV1,
        A: ProductEvaluationExecutionAttestorV1,
    >(
        &mut self,
        request: &ProductEvaluationExecutionRequestV1<'_>,
        provider: &mut P,
        executions: &mut E,
        attestor: &mut A,
    ) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationExecutionErrorV1> {
        let (key, previous) = self.execution_context(request)?;
        let bytes = match executions.claim(&key)? {
            ProductEvaluationExecutionClaimV1::Existing(
                ProductEvaluationExecutionStateV1::Pending,
            ) => {
                return Err(ProductEvaluationExecutionErrorV1::Pending);
            }
            ProductEvaluationExecutionClaimV1::Existing(
                ProductEvaluationExecutionStateV1::Completed(bytes),
            ) => bytes,
            ProductEvaluationExecutionClaimV1::Claimed => {
                if previous.is_some() {
                    return Err(ProductEvaluationExecutionErrorV1::MissingExecution);
                }
                let executed = self.evaluate_temporal_comparison(
                    request.plan,
                    request.candidate_plan,
                    request.baseline_plan,
                    provider,
                )?;
                let body = execution_codec::encode_execution(&executed)?;
                let signing_payload = signing_payload(&key, &body);
                let signed = attestor
                    .attest_execution(&ProductEvaluationExecutionAttestationRequestV1 {
                        key: &key,
                        execution: &executed,
                        signing_payload: signing_payload.clone(),
                    })
                    .map_err(ProductEvaluationError::from)?;
                authenticate(request, &signed, &signing_payload)?;
                let encoded = execution_codec::encode_envelope(&signed, &body)?;
                executions.complete(&key, &encoded)?;
                match executions.readback(&key)? {
                    ProductEvaluationExecutionStateV1::Pending => {
                        return Err(ProductEvaluationExecutionErrorV1::Pending);
                    }
                    ProductEvaluationExecutionStateV1::Completed(bytes) if bytes == encoded => {
                        bytes
                    }
                    ProductEvaluationExecutionStateV1::Completed(_) => {
                        return Err(ProductEvaluationExecutionStoreErrorV1::Corrupt.into());
                    }
                }
            }
        };
        self.authenticate_completed_execution(request, key, &bytes)
    }

    /// Authenticate only an existing completion through the original owners.
    /// Missing or pending work stays unresolved. This recovery entry receives
    /// neither a holdout provider nor a signer, and cannot claim or complete an
    /// execution. Current fences, original signatures and plans remain required.
    pub fn readback_temporal_comparison(
        &mut self,
        request: &ProductEvaluationExecutionRequestV1<'_>,
        executions: &mut impl ProductEvaluationExecutionStoreV1,
    ) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationExecutionErrorV1> {
        let (key, _) = self.execution_context(request)?;
        let bytes = match executions.readback(&key)? {
            ProductEvaluationExecutionStateV1::Pending => {
                return Err(ProductEvaluationExecutionErrorV1::Pending);
            }
            ProductEvaluationExecutionStateV1::Completed(bytes) => bytes,
        };
        self.authenticate_completed_execution(request, key, &bytes)
    }

    fn execution_context(
        &mut self,
        request: &ProductEvaluationExecutionRequestV1<'_>,
    ) -> Result<
        (
            ProductEvaluationExecutionKeyV1,
            Option<FinalHoldoutJournalReceiptV1>,
        ),
        ProductEvaluationExecutionErrorV1,
    > {
        request.plan.validate_integrity()?;
        for (actual, expected) in [
            (
                request.candidate_plan,
                request.plan.candidate_temporal_plan_digest,
            ),
            (
                request.baseline_plan,
                request.plan.baseline_temporal_plan_digest,
            ),
        ] {
            if actual.plan_digest != expected
                || actual.plan_digest
                    != actual
                        .canonical_digest()
                        .map_err(ProductEvaluationError::from)?
                || actual.objective_digest != request.plan.frozen_plan.objective_digest
            {
                return Err(ProductEvaluationError::Binding("temporal execution plan").into());
            }
        }
        let (namespace, previous) = self
            .holdout
            .read_consumption(&request.plan.frozen_plan)
            .map_err(ProductEvaluationError::from)?;
        let key = product_evaluation_execution_key_v1(request.plan, namespace, request.evaluator)?;
        Ok((key, previous))
    }

    fn authenticate_completed_execution(
        &mut self,
        request: &ProductEvaluationExecutionRequestV1<'_>,
        key: ProductEvaluationExecutionKeyV1,
        bytes: &[u8],
    ) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationExecutionErrorV1> {
        let (signed, body) = execution_codec::decode_envelope(bytes)?;
        // Authenticate exact raw bytes before constructing any sealed estimator.
        authenticate(request, &signed, &signing_payload(&key, body))?;
        let (_, consumed) = self
            .holdout
            .read_consumption(&request.plan.frozen_plan)
            .map_err(ProductEvaluationError::from)?;
        let consumed = consumed.ok_or(ProductEvaluationExecutionErrorV1::MissingExecution)?;
        let mut restored = execution_codec::decode_execution(body, request.plan, &consumed)?;
        if restored.candidate.plan_digest != request.candidate_plan.plan_digest
            || restored.candidate.evaluation_id != request.candidate_plan.evaluation_id
            || restored.baseline.plan_digest != request.baseline_plan.plan_digest
            || restored.baseline.evaluation_id != request.baseline_plan.evaluation_id
        {
            return Err(ProductEvaluationError::Binding("restored temporal plans").into());
        }
        let (_, current) = self
            .holdout
            .read_consumption(&request.plan.frozen_plan)
            .map_err(ProductEvaluationError::from)?;
        if current.as_ref() != Some(&consumed) {
            return Err(ProductEvaluationError::Binding("current holdout consumption").into());
        }
        restored.execution_evaluator = Some(request.evaluator.clone());
        Ok(restored)
    }
}

fn signing_payload(key: &ProductEvaluationExecutionKeyV1, body: &[u8]) -> Vec<u8> {
    let mut bytes = b"hepta.intelligence-eval.signed-execution.v1".to_vec();
    super::push_id(&mut bytes, &key.plan_id);
    bytes.extend_from_slice(key.binding_digest.as_array());
    bytes.extend_from_slice(Digest32::of_bytes(body).as_array());
    bytes
}

fn authenticate(
    request: &ProductEvaluationExecutionRequestV1<'_>,
    signed: &SignedLearningEvidenceV1,
    payload: &[u8],
) -> Result<(), ProductEvaluationError> {
    let now = (request.clock)()?;
    let verified = request
        .verifier
        .verify(LearningEvidenceRoleV1::Evaluator, signed, payload, now)
        .map_err(SignedEvaluationError::from)?;
    if verified.principal() != request.evaluator
        || verified.objective_digest() != request.plan.frozen_plan.objective_digest
    {
        return Err(ProductEvaluationError::Binding(
            "original execution evaluator",
        ));
    }
    Ok(())
}
