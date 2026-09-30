//! Typed, journal-bound qualification replay. Storage does not return decisions.
//!
//! The archive contains the complete derived qualification bundle, metric roles,
//! signatures and V3 timing evidence. Native estimator diagnostics remain the
//! separately addressed evidence objects; recovery never reruns an estimator.
use std::path::Path;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DurableProductEvaluationAttemptJournalV1;
use crate::EvaluationClaimScopeV1;
use crate::IndependentEvaluationBundleV1;
use crate::LongitudinalTimeEvidenceV1;
use crate::MetricRoleContractV2;
use crate::ProductEvaluationAttemptPhaseV1;
use crate::ProductEvaluationAttemptTransitionV1;
use crate::ProductEvaluationError;
use crate::ProductQualificationPublicationRequestV1;
use crate::ProductTimingEvidenceV1;
use crate::RecordedProductEvaluationErrorV1;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationEvidenceV1;
use crate::attempt_recovery::validated_history;
use crate::decide_with_signed_evidence_v2;
use crate::decide_with_signed_longitudinal_evidence_v3;

#[path = "qualification_archive_codec.rs"]
pub(crate) mod codec;
#[path = "qualification_archive_models.rs"]
mod models;
#[path = "qualification_archive_store.rs"]
mod store;
use codec::Wire;
use codec::structure;

pub(crate) const TEMPORAL: u8 = 0;
pub(crate) const OUTCOME: u8 = 1;
const MAGIC: &[u8; 8] = b"HQARCV02";

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum ArchivedTiming {
    Qualification,
    SystemLongitudinal {
        timing: LongitudinalTimeEvidenceV1,
        minimum_window_micros: u64,
    },
}

impl ArchivedTiming {
    fn capture(value: ProductTimingEvidenceV1<'_>) -> Self {
        match value {
            ProductTimingEvidenceV1::Qualification => Self::Qualification,
            ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros,
            } => Self::SystemLongitudinal {
                timing: timing.clone(),
                minimum_window_micros,
            },
        }
    }

    pub(crate) fn as_evidence(&self) -> ProductTimingEvidenceV1<'_> {
        match self {
            Self::Qualification => ProductTimingEvidenceV1::Qualification,
            Self::SystemLongitudinal {
                timing,
                minimum_window_micros,
            } => ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros: *minimum_window_micros,
            },
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct Archive {
    family: u8,
    attempt_id: StableId,
    host_binding: Digest32,
    namespace: Digest32,
    execution_digest: Digest32,
    holdout_record_digest: Digest32,
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    evidence: SignedEvaluationEvidenceV1,
    pub(crate) timing: ArchivedTiming,
}
structure!(Archive {
    family,
    attempt_id,
    host_binding,
    namespace,
    execution_digest,
    holdout_record_digest,
    bundle,
    roles,
    evidence,
    timing,
});

impl Archive {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        family: u8,
        attempt_id: &StableId,
        host_binding: Digest32,
        namespace: Digest32,
        execution_digest: Digest32,
        holdout_record_digest: Digest32,
        bundle: IndependentEvaluationBundleV1,
        roles: Vec<MetricRoleContractV2>,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
    ) -> Self {
        Self {
            family,
            attempt_id: attempt_id.clone(),
            host_binding,
            namespace,
            execution_digest,
            holdout_record_digest,
            bundle,
            roles,
            evidence: evidence.clone(),
            timing: ArchivedTiming::capture(timing),
        }
    }

    fn encode(&self) -> Result<Vec<u8>, ProductEvaluationError> {
        let mut output = codec::Writer::default();
        output.put(MAGIC)?;
        self.write(&mut output)?;
        Ok(output.finish())
    }

    fn decode(bytes: &[u8]) -> Result<Self, ProductEvaluationError> {
        let mut input = codec::Reader::new(bytes)?;
        if input.take(MAGIC.len())? != MAGIC {
            return Err(codec::invalid());
        }
        let value = Self::read(&mut input)?;
        input.finish()?;
        if !matches!(value.family, TEMPORAL | OUTCOME) || value.encode()? != bytes {
            return Err(codec::invalid());
        }
        Ok(value)
    }

    pub(crate) fn verify(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<SignedEvaluationDecisionV1, ProductEvaluationError> {
        if self.host_binding.is_zero()
            || self.namespace.is_zero()
            || self.execution_digest.is_zero()
            || self.holdout_record_digest.is_zero()
        {
            return Err(ProductEvaluationError::Binding(
                "qualification archive identity",
            ));
        }
        let result = match &self.timing {
            ArchivedTiming::Qualification => {
                if self.bundle.claim_scope != EvaluationClaimScopeV1::Qualification {
                    return Err(ProductEvaluationError::Binding(
                        "qualification archive scope",
                    ));
                }
                decide_with_signed_evidence_v2(
                    self.bundle.clone(),
                    self.roles.clone(),
                    &self.evidence,
                    verifier,
                    now,
                )
            }
            ArchivedTiming::SystemLongitudinal {
                timing,
                minimum_window_micros,
            } => {
                if self.bundle.claim_scope != EvaluationClaimScopeV1::SystemLongitudinal {
                    return Err(ProductEvaluationError::Binding(
                        "qualification archive scope",
                    ));
                }
                decide_with_signed_longitudinal_evidence_v3(
                    self.bundle.clone(),
                    self.roles.clone(),
                    &self.evidence,
                    timing,
                    *minimum_window_micros,
                    verifier,
                    now,
                )
            }
        };
        result.map_err(ProductEvaluationError::Signed)
    }

    /// Encode from typed native inputs and anchor the exact artifact before a
    /// qualification decision can become durable. A failed append never grants
    /// permission to adopt unanchored disk bytes after restart.
    pub(crate) fn persist<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        journal: &mut J,
        root: &Path,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<SignedEvaluationDecisionV1, RecordedProductEvaluationErrorV1> {
        let reject = || RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
            attempt_id: self.attempt_id.clone(),
        };
        let history = validated_history(journal, &self.attempt_id).map_err(|_| reject())?;
        let latest = history.last().ok_or_else(reject)?;
        if latest.transition.phase != ProductEvaluationAttemptPhaseV1::ComparisonSealed
            || latest.transition.plan_digest != self.bundle.frozen_plan.plan_digest
            || latest.transition.holdout_record_digest != self.holdout_record_digest
            || latest.transition.terminal_digest != self.execution_digest
            || !history.iter().any(|event| {
                event.transition.phase == ProductEvaluationAttemptPhaseV1::IntentPersisted
                    && event.transition.holdout_record_digest == self.namespace
            })
        {
            return Err(reject());
        }
        let decision = self
            .verify(verifier, now)
            .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
        let bytes = self
            .encode()
            .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
        if Self::decode(&bytes).map_err(RecordedProductEvaluationErrorV1::Evaluation)? != *self {
            return Err(RecordedProductEvaluationErrorV1::Invariant(
                "qualification archive round trip",
            ));
        }
        store::persist(root, &self.attempt_id, &bytes)
            .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
        journal.append(ProductEvaluationAttemptTransitionV1 {
            attempt_id: self.attempt_id.clone(),
            plan_digest: self.bundle.frozen_plan.plan_digest,
            phase: ProductEvaluationAttemptPhaseV1::QualificationArtifactsPersisted,
            holdout_record_digest: self.holdout_record_digest,
            terminal_digest: Digest32::of_bytes(&bytes),
        })?;
        Ok(decision)
    }
}

/// Rebuild and verify only the exact artifact already committed in the anchored
/// history. No decoder callback, cached decision or caller-supplied digest is an
/// authentication result. Pending and Published never enter this writer path.
#[allow(clippy::too_many_arguments)]
pub(crate) fn recover<J: DurableProductEvaluationAttemptJournalV1>(
    journal: &mut J,
    attempt_id: &StableId,
    root: &Path,
    host_binding: Digest32,
    namespace: Digest32,
    family: u8,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<SignedEvaluationDecisionV1, RecordedProductEvaluationErrorV1> {
    use ProductEvaluationAttemptPhaseV1 as Phase;
    let reject = || RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
        attempt_id: attempt_id.clone(),
    };
    let history = validated_history(journal, attempt_id).map_err(|error| match error {
        crate::ProductAttemptRecoveryErrorV1::Journal(error) => {
            RecordedProductEvaluationErrorV1::Journal(error)
        }
        _ => reject(),
    })?;
    let latest = history.last().ok_or_else(reject)?;
    if !matches!(
        latest.transition.phase,
        Phase::QualificationArtifactsPersisted | Phase::QualificationDecided
    ) {
        return Err(reject());
    }
    let prepared = history
        .iter()
        .find(|event| event.transition.phase == Phase::QualificationArtifactsPersisted)
        .ok_or_else(reject)?;
    let sealed = history
        .iter()
        .find(|event| event.transition.phase == Phase::ComparisonSealed)
        .ok_or_else(reject)?;
    let bytes =
        store::load(root, attempt_id).map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
    if Digest32::of_bytes(&bytes) != prepared.transition.terminal_digest {
        return Err(reject());
    }
    let archive = Archive::decode(&bytes).map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
    if &archive.attempt_id != attempt_id
        || archive.host_binding != host_binding
        || archive.namespace != namespace
        || archive.family != family
        || archive.bundle.frozen_plan.plan_digest != sealed.transition.plan_digest
        || archive.execution_digest != sealed.transition.terminal_digest
        || archive.holdout_record_digest != sealed.transition.holdout_record_digest
        || !history.iter().any(|event| {
            event.transition.phase == Phase::IntentPersisted
                && event.transition.holdout_record_digest == namespace
        })
    {
        return Err(reject());
    }
    let decision = archive
        .verify(verifier, now)
        .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
    let request =
        ProductQualificationPublicationRequestV1::new(archive.execution_digest, &decision)
            .map_err(|error| {
                RecordedProductEvaluationErrorV1::Evaluation(ProductEvaluationError::Sink(error))
            })?;
    if latest.transition.phase == Phase::QualificationDecided {
        if latest.transition.terminal_digest != request.request_digest {
            return Err(reject());
        }
    } else {
        journal.append(ProductEvaluationAttemptTransitionV1 {
            attempt_id: attempt_id.clone(),
            plan_digest: sealed.transition.plan_digest,
            phase: Phase::QualificationDecided,
            holdout_record_digest: sealed.transition.holdout_record_digest,
            terminal_digest: request.request_digest,
        })?;
    }
    Ok(decision)
}
