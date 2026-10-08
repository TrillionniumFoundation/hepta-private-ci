//! Typed bridges from the durable control outbox to real downstream owners.
//!
//! [`DurableControlRoleOwnerV1`](super::DurableControlRoleOwnerV1) owns the
//! local intent/forwarded state.  It cannot also own TaskFlow, CNS, transport,
//! or effect execution.  This module provides the narrow hand-off contract:
//! a downstream owner receives the exact persisted intent and must return a
//! receipt bound to its identity, generation, and route fence.  If no owner is
//! registered, the result is explicitly unavailable and the local record stays
//! `Forwarded` for recovery; it is never promoted to terminal by a digest.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::ControlDispatchIntentV1;
use super::ControlDispatchReceiptV1;
use super::ControlOperationKindV1;
use super::ControlOwnerErrorV1;
use super::ControlRoleOwnerV1;
use super::DurableControlRoleOwnerV1;
use super::digest_bytes;

pub const CONTROL_BACKEND_SCHEMA_V1: &str = "hepta.cell-role.control-backend.v1";

/// Error reported by the downstream owner without changing the local outbox.
/// `Unavailable` means no owner could be contacted; a real owner may also
/// reject a stale fence or malformed request. None of these outcomes is a
/// terminal receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlBackendErrorV1 {
    Unavailable(&'static str),
    StaleFence,
    Rejected(&'static str),
}

/// Receipt returned by the concrete TaskFlow, CNS, transport, or effect
/// owner after it durably accepts an intent. The receipt is only admissible if
/// every binding field matches the persisted local intent.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlBackendSubmissionReceiptV1 {
    pub dispatch_id: StableId,
    pub cell_id: StableId,
    pub generation: Generation,
    pub operation: ControlOperationKindV1,
    pub intent_digest: Digest32,
    pub route_fence_digest: Digest32,
    pub backend_receipt_digest: Digest32,
    pub already_submitted: bool,
}

impl ControlBackendSubmissionReceiptV1 {
    pub fn validate(&self) -> Result<(), ControlOwnerErrorV1> {
        if self.dispatch_id.as_str().is_empty() || self.cell_id.as_str().is_empty() {
            return Err(ControlOwnerErrorV1::EmptyId("backend dispatch or cell"));
        }
        for (label, digest) in [
            ("backend intent", self.intent_digest),
            ("backend route fence", self.route_fence_digest),
            ("backend receipt", self.backend_receipt_digest),
        ] {
            if digest.is_zero() {
                return Err(ControlOwnerErrorV1::EmptyDigest(label));
            }
        }
        Ok(())
    }

    fn validate_against(
        &self,
        intent: &ControlDispatchIntentV1,
    ) -> Result<(), ControlOwnerErrorV1> {
        self.validate()?;
        let intent_digest = intent.content_digest()?;
        if self.dispatch_id != intent.dispatch_id
            || self.cell_id != intent.cell_id
            || self.generation != intent.generation
            || self.operation != intent.operation
            || self.intent_digest != intent_digest
            || self.route_fence_digest != intent.route_fence_digest
        {
            return Err(ControlOwnerErrorV1::BackendReceiptMismatch);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        digest_bytes(
            CONTROL_BACKEND_SCHEMA_V1.as_bytes(),
            &[
                self.dispatch_id.as_str().as_bytes(),
                self.cell_id.as_str().as_bytes(),
                &self.generation.get().to_be_bytes(),
                &[self.operation.tag()],
                self.intent_digest.as_array(),
                self.route_fence_digest.as_array(),
                self.backend_receipt_digest.as_array(),
                &[u8::from(self.already_submitted)],
            ],
        )
    }
}

/// Terminal observation returned by a concrete downstream owner. It binds
/// the terminal bytes to the exact submission receipt, so an unrelated digest
/// cannot close a forwarded local intent.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlBackendTerminalReceiptV1 {
    pub dispatch_id: StableId,
    pub cell_id: StableId,
    pub generation: Generation,
    pub operation: ControlOperationKindV1,
    pub intent_digest: Digest32,
    pub route_fence_digest: Digest32,
    pub submission_receipt_digest: Digest32,
    pub terminal_receipt_digest: Digest32,
}

impl ControlBackendTerminalReceiptV1 {
    pub fn validate(&self) -> Result<(), ControlOwnerErrorV1> {
        if self.dispatch_id.as_str().is_empty() || self.cell_id.as_str().is_empty() {
            return Err(ControlOwnerErrorV1::EmptyId(
                "backend terminal dispatch or cell",
            ));
        }
        for (label, digest) in [
            ("terminal intent", self.intent_digest),
            ("terminal route fence", self.route_fence_digest),
            ("submission receipt", self.submission_receipt_digest),
            ("terminal receipt", self.terminal_receipt_digest),
        ] {
            if digest.is_zero() {
                return Err(ControlOwnerErrorV1::EmptyDigest(label));
            }
        }
        Ok(())
    }

    fn validate_against(
        &self,
        intent: &ControlDispatchIntentV1,
        submission: &ControlBackendSubmissionReceiptV1,
    ) -> Result<(), ControlOwnerErrorV1> {
        self.validate()?;
        let intent_digest = intent.content_digest()?;
        if self.dispatch_id != intent.dispatch_id
            || self.cell_id != intent.cell_id
            || self.generation != intent.generation
            || self.operation != intent.operation
            || self.intent_digest != intent_digest
            || self.route_fence_digest != intent.route_fence_digest
            || self.submission_receipt_digest != submission.content_digest()
        {
            return Err(ControlOwnerErrorV1::BackendReceiptMismatch);
        }
        submission.validate_against(intent)
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        digest_bytes(
            b"hepta.cell-role.control-backend-terminal.v1",
            &[
                self.dispatch_id.as_str().as_bytes(),
                self.cell_id.as_str().as_bytes(),
                &self.generation.get().to_be_bytes(),
                &[self.operation.tag()],
                self.intent_digest.as_array(),
                self.route_fence_digest.as_array(),
                self.submission_receipt_digest.as_array(),
                self.terminal_receipt_digest.as_array(),
            ],
        )
    }
}

/// A downstream implementation is responsible for contacting its own
/// durable owner. It must be idempotent by `dispatch_id` and the exact intent
/// digest, and it must not claim terminality from local forwarding alone.
pub trait ControlDispatchBackendV1 {
    fn submit(
        &mut self,
        intent: &ControlDispatchIntentV1,
    ) -> Result<ControlBackendSubmissionReceiptV1, ControlBackendErrorV1>;
}

/// Result of the local-forward plus backend hand-off. `Unavailable` is an
/// honest, retryable state and deliberately carries the still-forwarded local
/// receipt rather than pretending the operation reached a terminal state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlBackendDispatchOutcomeV1 {
    Submitted(ControlBackendSubmissionReceiptV1),
    Unavailable(ControlBackendErrorV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlBackendDispatchResultV1 {
    pub local_receipt: ControlDispatchReceiptV1,
    pub outcome: ControlBackendDispatchOutcomeV1,
}

impl DurableControlRoleOwnerV1 {
    /// Forward one durable outbox item to the registered downstream owner.
    /// The local forward is persisted before the backend call. On a crash
    /// between those steps, reopening and retrying this method is safe because
    /// backend implementations must de-duplicate the immutable dispatch id.
    pub fn submit_to_backend<B: ControlDispatchBackendV1>(
        &mut self,
        dispatch_id: &StableId,
        backend: &mut B,
    ) -> Result<ControlBackendDispatchResultV1, ControlOwnerErrorV1> {
        let intent = self
            .dispatch_intent(dispatch_id)
            .cloned()
            .ok_or(ControlOwnerErrorV1::MissingDispatch)?;
        let local_receipt = self.forward(dispatch_id)?;
        match backend.submit(&intent) {
            Ok(submission) => {
                submission.validate_against(&intent)?;
                Ok(ControlBackendDispatchResultV1 {
                    local_receipt,
                    outcome: ControlBackendDispatchOutcomeV1::Submitted(submission),
                })
            }
            Err(error) => Ok(ControlBackendDispatchResultV1 {
                local_receipt,
                outcome: ControlBackendDispatchOutcomeV1::Unavailable(error),
            }),
        }
    }

    /// Record a backend terminal observation only after verifying all receipt
    /// bindings. The resulting local terminal digest includes the backend
    /// submission and terminal receipt, so it cannot be replayed for another
    /// intent or route fence.
    pub fn record_backend_terminal(
        &mut self,
        dispatch_id: &StableId,
        submission: &ControlBackendSubmissionReceiptV1,
        terminal: &ControlBackendTerminalReceiptV1,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        let intent = self
            .dispatch_intent(dispatch_id)
            .cloned()
            .ok_or(ControlOwnerErrorV1::MissingDispatch)?;
        if terminal.dispatch_id != *dispatch_id {
            return Err(ControlOwnerErrorV1::BackendReceiptMismatch);
        }
        submission.validate_against(&intent)?;
        terminal.validate_against(&intent, submission)?;
        self.record_terminal(dispatch_id, terminal.content_digest())
    }
}

#[cfg(test)]
#[path = "control_backend_tests.rs"]
mod tests;
