//! Independently retained request context from the existing guarded journal.
//! This is an owner-context seam, not a computation verifier, consensus rule,
//! FinalUse grant or proof that a model was actually executed.

use codex_hepta_types::Digest32;

use super::CellGenerationJournalV2;
use crate::AnchorWitnessStore;
use crate::CellGenerationConfigV2;
use crate::CellGenerationErrorV2;
use crate::CellGenerationOwnerBindingV1;
use crate::CellGenerationProposalV2;
use crate::CellGenerationReceiptV2;
use crate::CellGenerationRequestV2;

/// An immutable cut of one durably admitted request and its guarded owner.
///
/// Only the journal can construct this type. It has no wire representation or
/// deserializer: a consumer obtains it from its own owner, never from the
/// producer's contract. The original request includes the actual input, task,
/// source frontier, deadline and predecessor state/scope/generation/writer epoch.
/// The configuration includes the complete existing manifest and initial state.
/// Request times retain the journal's host monotonic microsecond lane; they are
/// not a historical consensus time or a replacement for the authority's clock.
///
/// This is trusted only as far as the host's existing Current and witness ports.
/// It neither authenticates a producer nor verifies its proposed computation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellGenerationExpectedContextV1 {
    config: CellGenerationConfigV2,
    request: CellGenerationRequestV2,
    checkpoint: Digest32,
    owner: CellGenerationOwnerBindingV1,
}

impl CellGenerationExpectedContextV1 {
    pub fn configuration(&self) -> &CellGenerationConfigV2 {
        &self.config
    }

    pub fn request(&self) -> &CellGenerationRequestV2 {
        &self.request
    }

    pub const fn checkpoint(&self) -> Digest32 {
        self.checkpoint
    }

    pub fn owner_binding(&self) -> &CellGenerationOwnerBindingV1 {
        &self.owner
    }
}

impl<W: AnchorWitnessStore> CellGenerationJournalV2<W> {
    /// Read the pending request from this owner's durable admission, including
    /// after cold replay. Unguarded, unhealthy, retired or idle owners refuse.
    /// No producer-supplied request, context or success flag is accepted here.
    pub fn pending_expected_context(
        &self,
    ) -> Result<CellGenerationExpectedContextV1, CellGenerationErrorV2> {
        self.require_healthy()?;
        let owner = self
            .owner_binding()
            .ok_or(CellGenerationErrorV2::InvalidBinding)?;
        let request = self
            .state
            .pending
            .as_ref()
            .ok_or(CellGenerationErrorV2::Conflict)?;
        Ok(CellGenerationExpectedContextV1 {
            config: self.config.clone(),
            request: request.clone(),
            checkpoint: self.continuity_checkpoint()?,
            owner: owner.clone(),
        })
    }

    /// Recheck the exact pending owner cut. Every durable event, including
    /// cost, cancellation and dispatch observation, invalidates an older cut.
    /// Successful revalidation is not computation verification or authorization.
    pub fn require_expected_context(
        &self,
        expected: &CellGenerationExpectedContextV1,
    ) -> Result<(), CellGenerationErrorV2> {
        self.require_context_owner(expected)?;
        if self.state.pending.as_ref() != Some(&expected.request)
            || self.continuity_checkpoint()? != expected.checkpoint
        {
            return Err(CellGenerationErrorV2::Conflict);
        }
        Ok(())
    }

    /// Commit through the original journal only while this independently
    /// retained pending context still matches. This adds context checking, not
    /// a computation verifier; callers still need their real relation verifier
    /// and must retain the existing FinalUse dispatch boundary for protected use.
    /// This method adds no transaction spanning owners. Receipts retain their
    /// existing DENY_ALL posture.
    ///
    /// An exact already-committed request/proposal returns its original receipt
    /// without another append. Conflicting proposals still fail. Readback after
    /// a lost acknowledgement uses the same operation, never a new admission.
    pub fn commit_with_expected_context(
        &mut self,
        expected: &CellGenerationExpectedContextV1,
        proposal: CellGenerationProposalV2,
        now_micros: u64,
    ) -> Result<CellGenerationReceiptV2, CellGenerationErrorV2> {
        self.require_context_owner(expected)?;
        if proposal.request_digest != expected.request.digest()? {
            return Err(CellGenerationErrorV2::Conflict);
        }
        if self.state.lookup(&expected.request)?.is_none() {
            self.require_expected_context(expected)?;
        }
        self.commit(proposal, now_micros)
    }

    fn require_context_owner(
        &self,
        expected: &CellGenerationExpectedContextV1,
    ) -> Result<(), CellGenerationErrorV2> {
        self.require_healthy()?;
        if self.owner_binding() != Some(&expected.owner) || self.config != expected.config {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(())
    }
}
