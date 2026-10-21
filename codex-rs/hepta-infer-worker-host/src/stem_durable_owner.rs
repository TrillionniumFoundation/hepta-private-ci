//! Strict existing DurableInferenceControl owner bridge for signed Stem use.
//! No second journal, model promotion, CAS claim or signing key is created.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::durable_control::Assignment;
use codex_hepta_infer_core::durable_control::ControlReceipt;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_infer_core::durable_control::TerminalObservation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::model_worker::BoundStemFeatureExecutionV1;
use crate::model_worker::InferenceWorker;
use crate::model_worker::ModelDriver;
use crate::model_worker::NeuronFeatureDriver;
use crate::model_worker::VerifiedStemFeatureDispatchV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StemDurableErrorV1 {
    MissingReservation,
    StaleRevision,
    IncompatibleReservation,
    BindingMismatch,
    ReconciliationOnly,
    DriverDenied,
    JournalOutcomeUnknown,
}

impl fmt::Display for StemDurableErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for StemDurableErrorV1 {}

#[derive(Debug)]
pub struct DurableStemReceiptV1 {
    pub control: ControlReceipt,
    pub execution: BoundStemFeatureExecutionV1,
    pub authority: AuthorityPosture,
}

impl<D: ModelDriver + NeuronFeatureDriver> InferenceWorker<D> {
    /// The single public, signed and durable Shared Stem execution boundary.
    /// Submit and reserve MUST already be persisted by the same controller.
    /// This method itself durably assigns before entering Final-use. An
    /// Assigned record is never re-dispatched, even after crash or lost ACK.
    pub fn dispatch_verified_stem_durable_v1(
        &mut self,
        control: &mut DurableInferenceControl,
        trusted_authority: &FinalUseAuthority,
        verified_use: VerifiedUseToken,
        now_ms: u64,
        expected_reserved_revision: u64,
        proposed: VerifiedStemFeatureDispatchV1<'_>,
    ) -> Result<DurableStemReceiptV1, StemDurableErrorV1> {
        let request_id = proposed.authorization.request_id.clone();
        let record = control
            .get(&request_id)
            .cloned()
            .ok_or(StemDurableErrorV1::MissingReservation)?;
        if record.state != RequestState::Reserved {
            return Err(StemDurableErrorV1::ReconciliationOnly);
        }
        if record.revision != expected_reserved_revision {
            return Err(StemDurableErrorV1::StaleRevision);
        }
        let reservation = record
            .reservation
            .as_ref()
            .ok_or(StemDurableErrorV1::MissingReservation)?;
        let authorization = &proposed.authorization;
        if record.request.request_id != request_id
            || record.request.principal_id != proposed.source.principal_id.to_string()
            || record.request.model_digest != authorization.model_digest
            || record.request.payload_digest != authorization.payload_digest
            || record.request.maximum_tokens != authorization.maximum_tokens
            || record.request.deadline_ms != authorization.deadline_ms
            || reservation.reservation_id != authorization.reservation_id
            || reservation.maximum_tokens != authorization.reservation_maximum_tokens
            || reservation.authority_epoch != proposed.access.authority_epoch
            || reservation.valid_until_ms <= now_ms
        {
            return Err(StemDurableErrorV1::IncompatibleReservation);
        }
        let binding = self
            .expected_stem_final_use_binding_v1(
                now_ms,
                proposed.source,
                proposed.access,
                proposed.selected_head.clone(),
                proposed.feature_vector_q24,
                authorization,
            )
            .map_err(|_| StemDurableErrorV1::BindingMismatch)?;
        let binding_bytes = serde_json::to_vec(&binding)
            .map_err(|_| StemDurableErrorV1::BindingMismatch)?;
        let binding_digest = Digest32::of_bytes(&binding_bytes);
        if record.request.semantic_digest != binding_digest.to_string() {
            return Err(StemDurableErrorV1::BindingMismatch);
        }
        let worker_generation = proposed.source.stem_generation.get();
        // The existing locked, append-only, fsynced journal is the ONLY
        // execution owner. No Final-use effect can occur before this write.
        let assignment_digest = Digest32::of_parts(&[
            b"hepta.inference.stem-durable-assignment.v1",
            binding_digest.as_array(),
            request_id.as_bytes(),
        ]);
        let assigned = control
            .assign(
                &request_id,
                expected_reserved_revision,
                Assignment {
                    worker_id: self.worker_id().to_string(),
                    worker_generation,
                    assignment_digest: assignment_digest.to_string(),
                },
            )
            .map_err(|_| StemDurableErrorV1::JournalOutcomeUnknown)?;
        let executed = self
            .run_verified_stem_feature_receipt_v1(
                trusted_authority,
                verified_use,
                now_ms,
                proposed,
            )
            .and_then(|receipt| {
                // Do not durably claim success if the signed binding or
                // no-authority Worker boundary ever diverges. A mismatch is
                // conservatively an unknown post-assignment outcome.
                if receipt.final_use_binding_digest != Some(binding_digest)
                    || receipt.authority.grants_any()
                    || receipt.worker_receipt.authority.grants_any()
                {
                    return Err(crate::model_worker::Error::FinalUseDenied);
                }
                Ok(receipt)
            });
        let (terminal_status, output_digest, observed_digest) = match &executed {
            Ok(result) => {
                let status = match result.worker_receipt.status {
                    NeuronFeatureTerminalStatusV1::Succeeded => Some(RequestState::Completed),
                    NeuronFeatureTerminalStatusV1::Failed => Some(RequestState::Failed),
                    NeuronFeatureTerminalStatusV1::Cancelled => Some(RequestState::Cancelled),
                    NeuronFeatureTerminalStatusV1::Indeterminate => None,
                };
                let output = (status == Some(RequestState::Completed))
                    .then(|| result.worker_receipt.output_digest.to_string());
                let digest = Digest32::of_parts(&[
                    b"hepta.inference.stem-worker-terminal.v1",
                    binding_digest.as_array(),
                    result.worker_receipt.receipt_digest.as_array(),
                ]);
                (status, output, digest)
            }
            Err(_) => (
                None,
                None,
                Digest32::of_parts(&[
                    b"hepta.inference.stem-worker-uncertain.v1",
                    binding_digest.as_array(),
                ]),
            ),
        };
        let observation = TerminalObservation {
            request_id: request_id.clone(),
            reservation_id: reservation.reservation_id.clone(),
            worker_id: self.worker_id().to_string(),
            worker_generation,
            model_digest: record.request.model_digest,
            payload_digest: record.request.payload_digest,
            terminal_observed: terminal_status.is_some(),
            terminal_status,
            output_digest,
            // Head-only Q24 path. Real Encoder/Stem token usage and resource
            // billing remain an independent production measurement gate.
            consumed_tokens: 0,
            usage_units: 0,
        };
        let control_receipt = control
            .settle(
                &request_id,
                assigned.revision,
                observed_digest.to_string(),
                observation,
            )
            .map_err(|_| StemDurableErrorV1::JournalOutcomeUnknown)?;
        let execution = executed.map_err(|_| StemDurableErrorV1::DriverDenied)?;
        Ok(DurableStemReceiptV1 {
            control: control_receipt,
            execution,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}
