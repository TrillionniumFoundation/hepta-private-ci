//! Root's original verification fact, committed with the first completed B
//! record. This data is not a current qualification or an execution capability.
//! An ordinary readback must never create or renew this fact.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;

use super::*;
use crate::HostAuthorityService;
use crate::learning_owner_evidence;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(in super::super) struct OriginalBCompletedAcceptanceV1 {
    schema: u8,
    frozen_scope: [u8; 32],
    root_verified_at_seconds: u64,
    native_verified_at_seconds: u64,
    training_attestation: [u8; 32],
    evaluation_attestation: [u8; 32],
    enrollment_cut: [u8; 32],
}

impl OriginalBEnrollment {
    /// Only the actual Root operation calls this after native execution and
    /// its complete Root-context postchecks. The enclosing record's Ready CAS
    /// still has to succeed before any later reader may rely on these bytes.
    pub(in super::super) fn retain_original_completed_acceptance(
        &mut self,
        service: &HostAuthorityService,
        scope: &FrozenLearningScopeV2,
        completed: &super::super::execution::OriginalBCompleted,
        verifier: &LearningEvidenceVerifierV1,
    ) -> io::Result<()> {
        if self.completed_acceptance.is_some()
            || self.realized_training_head != Some(completed.training.head_digest.into_array())
            || verifier.trust_digest().into_array() != self.trust
        {
            return Err(io::Error::other("original B acceptance cannot be replaced"));
        }
        scope
            .validate_snapshot(&completed.training)
            .map_err(io::Error::other)?;
        let training = completed
            .training
            .receipts
            .last()
            .ok_or_else(|| io::Error::other("original B Training receipt absent"))?;
        let training_payload =
            learning_iteration_receipt_signing_bytes_v1(training).map_err(io::Error::other)?;
        let evaluation_payload = learning_iteration_receipt_signing_bytes_v1(&completed.receipt)
            .map_err(io::Error::other)?;
        let training_bytes =
            learning_owner_evidence::encode(&training_payload, &completed.training_attestation)
                .map_err(io::Error::other)?;
        if self.original_training_attestation.as_ref() != Some(&training_bytes)
            || self.completed_receipt != Some(Digest32::of_bytes(&evaluation_payload).into_array())
        {
            return Err(io::Error::other("original B accepted receipt differs"));
        }
        // This is a new sample from the actual Root clock, not either signer's
        // issued_at. Both exact signatures are verified at that same sample.
        let verified_at = HostAuthorityService::original_learning_unix_seconds(service)?;
        let generator = verifier
            .verify(
                LearningEvidenceRoleV1::Generator,
                &completed.training_attestation,
                &training_payload,
                verified_at,
            )
            .map_err(io::Error::other)?;
        let evaluator = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &completed.attestation,
                &evaluation_payload,
                verified_at,
            )
            .map_err(io::Error::other)?;
        if generator.principal().principal_id != completed.training.owners.trainer
            || evaluator.principal().principal_id != completed.training.owners.evaluator
        {
            return Err(io::Error::other("original B accepted actors differ"));
        }
        verify_signed_actor_separation(&generator, &evaluator, verified_at)
            .map_err(io::Error::other)?;
        let acceptance = OriginalBCompletedAcceptanceV1 {
            schema: 1,
            frozen_scope: scope.binding().into_array(),
            root_verified_at_seconds: verified_at,
            native_verified_at_seconds: completed.verified_at,
            training_attestation: Digest32::of_bytes(&training_bytes).into_array(),
            evaluation_attestation: Digest32::of_bytes(
                &learning_owner_evidence::encode(&evaluation_payload, &completed.attestation)
                    .map_err(io::Error::other)?,
            )
            .into_array(),
            enrollment_cut: self.completed_enrollment_cut()?.into_array(),
        };
        acceptance.require_original(self)?;
        self.completed_acceptance = Some(acceptance);
        Ok(())
    }

    pub(in super::super) fn require_completed_acceptance(&self) -> io::Result<()> {
        match (&self.completed_receipt, &self.completed_acceptance) {
            (None, None) => Ok(()),
            (Some(_), Some(acceptance)) => acceptance.require_original(self),
            _ => Err(io::Error::other(
                "original B completion verification fact missing",
            )),
        }
    }

    fn completed_enrollment_cut(&self) -> io::Result<Digest32> {
        if self.completed_receipt.is_none()
            || self.realized_training_head.is_none()
            || self.realized_plan.is_none()
            || self.realized_plan_statement.is_none()
            || self.original_training_attestation.is_none()
            || self.original_training_work.is_none()
            || self.heads.is_none()
            || self.cell_images.as_ref().is_none_or(Vec::is_empty)
            || self.output_images.is_empty()
            || self.admitted_source.is_none()
            || self.released_source != self.admitted_source
        {
            return Err(io::Error::other(
                "complete original B physical cut required",
            ));
        }
        let mut original = self.clone();
        original.completed_acceptance = None;
        let bytes = serde_json::to_vec(&original).map_err(io::Error::other)?;
        Ok(Digest32::of_parts(&[
            b"hepta.root.independent-b.accepted-completion-cut.v1\0",
            &bytes,
        ]))
    }
}

impl OriginalBCompletedAcceptanceV1 {
    fn require_original(&self, original: &OriginalBEnrollment) -> io::Result<()> {
        let training = original
            .original_training_attestation
            .as_ref()
            .ok_or_else(|| io::Error::other("original B Training signature missing"))?;
        if self.schema != 1
            || self.frozen_scope == [0; 32]
            || self.root_verified_at_seconds < original.registered_at_seconds
            || self.root_verified_at_seconds >= original.expires_at_seconds
            || self.native_verified_at_seconds < original.registered_at_seconds
            || self.native_verified_at_seconds > self.root_verified_at_seconds
            || self.training_attestation != Digest32::of_bytes(training).into_array()
            || self.evaluation_attestation == [0; 32]
            || self.enrollment_cut != original.completed_enrollment_cut()?.into_array()
        {
            return Err(io::Error::other(
                "original B completed verification fact differs",
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "authority_host_q24_evaluation_acceptance_tests.rs"]
mod tests;
