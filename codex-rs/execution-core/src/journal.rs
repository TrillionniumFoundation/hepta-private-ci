//! Deterministic single-operation sequence validator without effect privileges.

use crate::ApprovalRequest;
use crate::EffectReceipt;
use crate::ExecutionClass;
use crate::ExecutionError;
use crate::ExecutionRecord;
use crate::ExecutionReservation;
use crate::ExecutionStarted;
use crate::FinalUse;

/// A separate host must verify policy, principal, lease, generation, signed
/// FinalUse and exact payload immediately before any effect crosses the boundary.
/// Verifying a serialized Verified tag alone is explicitly insufficient.
pub trait ExecutionVerifier {
    fn verify_start(
        &self,
        reservation: &ExecutionReservation,
        started: &ExecutionStarted,
        class: ExecutionClass,
    ) -> Result<(), ExecutionError>;
}

/// A distinct observation owner must verify actual host outcomes. Neither a
/// model-generated completion nor a JSON receipt proves an effect occurred.
pub trait EffectReceiptVerifier {
    fn verify_effect(&self, receipt: &EffectReceipt) -> Result<(), ExecutionError>;
}

/// Bounded, volatile journal for one operation. Production must commit each
/// accepted event to an append-only durable ledger before emitting/using it.
#[derive(Debug, Default)]
pub struct ExecutionJournal {
    events: Vec<ExecutionRecord>,
}

impl ExecutionJournal {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn events(&self) -> &[ExecutionRecord] {
        &self.events
    }

    pub fn append(&mut self, event: ExecutionRecord) -> Result<String, ExecutionError> {
        self.append_checked(event, None, None)
    }

    pub fn append_started(
        &mut self,
        event: ExecutionStarted,
        verifier: &impl ExecutionVerifier,
    ) -> Result<String, ExecutionError> {
        self.append_checked(ExecutionRecord::ExecutionStarted(event), Some(verifier), None)
    }

    pub fn append_effect_receipt(
        &mut self,
        event: EffectReceipt,
        verifier: &impl EffectReceiptVerifier,
    ) -> Result<String, ExecutionError> {
        self.append_checked(ExecutionRecord::EffectReceipt(event), None, Some(verifier))
    }

    fn append_checked(
        &mut self,
        event: ExecutionRecord,
        verifier: Option<&dyn ExecutionVerifier>,
        receipt_verifier: Option<&dyn EffectReceiptVerifier>,
    ) -> Result<String, ExecutionError> {
        event.validate()?;
        let previous = self.events.last();
        let expected_predecessor = previous.map(ExecutionRecord::digest).transpose()?;
        if event.binding().predecessor != expected_predecessor {
            return Err(ExecutionError::Sequence("predecessor digest mismatch"));
        }
        if let Some(first) = self.events.first() {
            let previous_binding = previous.ok_or(ExecutionError::Sequence("empty last record"))?;
            if !first.binding().same_operation(event.binding()) {
                return Err(ExecutionError::Binding("operation identity changed"));
            }
            if let FinalUse::Verified { .. } = &previous_binding.binding().final_use
                && previous_binding.binding().final_use != event.binding().final_use
            {
                return Err(ExecutionError::Binding("FinalUse witness changed or downgraded"));
            }
        }
        match (previous, &event) {
            (None, ExecutionRecord::ExecutionIntent(_))
            | (Some(ExecutionRecord::ExecutionIntent(_)), ExecutionRecord::ExecutionReservation(_))
            | (Some(ExecutionRecord::ExecutionReservation(_)), ExecutionRecord::ApprovalRequest(_))
            | (Some(ExecutionRecord::ExecutionReservation(_)), ExecutionRecord::ExecutionStarted(_))
            | (Some(ExecutionRecord::ApprovalRequest(_)), ExecutionRecord::ExecutionStarted(_))
            | (Some(ExecutionRecord::ExecutionStarted(_)), ExecutionRecord::ExecutionOutputChunk(_))
            | (Some(ExecutionRecord::ExecutionOutputChunk(_)), ExecutionRecord::ExecutionOutputChunk(_))
            | (Some(ExecutionRecord::ExecutionStarted(_)), ExecutionRecord::ExecutionCompleted(_))
            | (Some(ExecutionRecord::ExecutionOutputChunk(_)), ExecutionRecord::ExecutionCompleted(_))
            | (Some(ExecutionRecord::ExecutionReservation(_)), ExecutionRecord::ExecutionCancelled(_))
            | (Some(ExecutionRecord::ApprovalRequest(_)), ExecutionRecord::ExecutionCancelled(_))
            | (Some(ExecutionRecord::ExecutionStarted(_)), ExecutionRecord::ExecutionCancelled(_))
            | (Some(ExecutionRecord::ExecutionOutputChunk(_)), ExecutionRecord::ExecutionCancelled(_))
            | (Some(ExecutionRecord::ExecutionCompleted(_)), ExecutionRecord::ExecutionReconciled(_))
            | (Some(ExecutionRecord::ExecutionCancelled(_)), ExecutionRecord::ExecutionReconciled(_))
            | (Some(ExecutionRecord::ExecutionCompleted(_)), ExecutionRecord::EffectReceipt(_))
            | (Some(ExecutionRecord::ExecutionReconciled(_)), ExecutionRecord::EffectReceipt(_)) => {}
            _ => return Err(ExecutionError::Sequence("illegal or repeated transition")),
        }

        let intent = self
            .events
            .first()
            .and_then(|first| match first {
                ExecutionRecord::ExecutionIntent(value) => Some(value),
                _ => None,
            });

        if let ExecutionRecord::ApprovalRequest(_) = &event
            && !intent.is_some_and(|value| value.class.needs_approval())
        {
            return Err(ExecutionError::Sequence("approval not required for this class"));
        }

        if let ExecutionRecord::ExecutionOutputChunk(chunk) = &event {
            let expected_sequence = self
                .events
                .iter()
                .rev()
                .find_map(|value| match value {
                    ExecutionRecord::ExecutionOutputChunk(last) => Some(last.sequence),
                    _ => None,
                })
                .unwrap_or(0)
                .checked_add(1)
                .ok_or(ExecutionError::Sequence("output chunk counter overflow"))?;
            if chunk.sequence != expected_sequence {
                return Err(ExecutionError::Sequence("out of order output"));
            }
        }

        if let ExecutionRecord::ExecutionStarted(started) = &event {
            let verifier = verifier.ok_or(ExecutionError::VerifierRequired)?;
            let intent = intent.ok_or(ExecutionError::Sequence("intent missing"))?;
            let reservation = self
                .events
                .iter()
                .find_map(|record| match record {
                    ExecutionRecord::ExecutionReservation(value) => Some(value),
                    _ => None,
                })
                .ok_or(ExecutionError::Sequence("reservation missing"))?;
            if started.binding.currentness != crate::Currentness::Current
                || started.started_at_unix_ms > reservation.expires_at_unix_ms
                || started.reservation_digest
                    != ExecutionRecord::ExecutionReservation(reservation.clone()).digest()?
            {
                return Err(ExecutionError::AuthorizationDenied);
            }
            if intent.class.needs_final_use()
                && !matches!(started.binding.final_use, FinalUse::Verified { .. })
            {
                return Err(ExecutionError::AuthorizationDenied);
            }
            let was_requested = self
                .events
                .iter()
                .any(|record| matches!(record, ExecutionRecord::ApprovalRequest(_)));
            if intent.class.needs_approval()
                && (!was_requested || started.approval_receipt_digest.is_none())
            {
                return Err(ExecutionError::AuthorizationDenied);
            }
            if !intent.class.needs_approval() && started.approval_receipt_digest.is_some() {
                return Err(ExecutionError::Binding("unexpected approval receipt"));
            }
            verifier.verify_start(reservation, started, intent.class)?;
        }

        if let ExecutionRecord::EffectReceipt(receipt) = &event {
            receipt_verifier
                .ok_or(ExecutionError::VerifierRequired)?
                .verify_effect(receipt)?;
        }

        let digest = event.digest()?;
        self.events.push(event);
        Ok(digest)
    }
}
