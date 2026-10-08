//! Authority-free action proposal role adapter.
//!
//! `ActionProposalV1` is the last typed product of a cell circuit before a
//! deterministic effect owner.  It identifies an action and binds its
//! arguments, preconditions, timing, propensity, and supporting evidence.  It
//! deliberately contains no credential, runtime handle, provider dispatch
//! instruction, or authority.  A downstream effect owner may accept or reject
//! the proposal, but this adapter can never execute it.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::CalibratedIntuitionReceiptV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellRoleContractErrorV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepReceiptV1;
use codex_hepta_types::CellStepStatusV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use super::CellAdapterContextV1;
use super::CellRoleAdapterErrorV1;
use super::CellRoleStepV1;

/// Versioned schema for proposal payloads.  The version is separate from the
/// `CellStepReceiptV1` schema so changing action fields cannot silently change
/// the receipt interpretation.
pub const ACTION_PROPOSAL_SCHEMA_V1: &str = "hepta.cell-role.action-proposal.v1";

/// A proposal can only be observed or handed to an external owner.  This
/// constant is intentionally public so callers can assert the boundary in
/// integration tests without looking at implementation details.
pub const ACTION_PROPOSAL_EXECUTION_ALLOWED_V1: bool = false;

/// The only execution posture representable by an action proposal.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ActionProposalExecutionModeV1 {
    ProposalOnly,
}

impl ActionProposalExecutionModeV1 {
    pub const fn execution_allowed(self) -> bool {
        false
    }

    pub const fn authority(self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// A typed action proposal.  This is a value object, rather than an effect
/// command: it carries no provider, credential, runtime handle, or dispatch
/// callback.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActionProposalV1 {
    pub action_id: StableId,
    pub arguments_digest: Digest32,
    pub precondition_digest: Digest32,
    pub effect_class: StableId,
    /// Latest time at which an effect owner may consider this proposal.
    pub deadline_unix_ms: u64,
    /// Time after which the proposal is invalid, even if it was not dispatched.
    pub expiry_unix_ms: u64,
    /// Probability assigned by the complete, calibrated candidate policy.
    pub propensity: ProbabilityQ32,
    /// Evidence directly supporting this proposal, usually a calibrated
    /// decision receipt or an equivalent independent observation receipt.
    pub evidence_digest: Digest32,
}

/// Owner-local qualification receipt for a proposal.  It records that the
/// typed payload was checked at a particular observation time; it never
/// authorizes dispatch or reserves an effect capability.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActionProposalQualificationReceiptV1 {
    pub proposal_digest: Digest32,
    pub observed_at_unix_ms: u64,
    pub execution_allowed: bool,
    pub authority: AuthorityPosture,
    pub qualification_digest: Digest32,
}

impl ActionProposalQualificationReceiptV1 {
    pub fn validate(&self) -> Result<(), ActionProposalErrorV1> {
        if self.proposal_digest.is_zero() || self.qualification_digest.is_zero() {
            return Err(ActionProposalErrorV1::EmptyDigest("qualification"));
        }
        if self.observed_at_unix_ms == 0 {
            return Err(ActionProposalErrorV1::InvalidObservationTime);
        }
        if self.execution_allowed || self.authority.grants_any() {
            return Err(ActionProposalErrorV1::ReplayMismatch);
        }
        Ok(())
    }
}

impl ActionProposalV1 {
    pub const EXECUTION_MODE: ActionProposalExecutionModeV1 =
        ActionProposalExecutionModeV1::ProposalOnly;

    pub fn validate(&self) -> Result<(), ActionProposalErrorV1> {
        if self.action_id.as_str().is_empty() {
            return Err(ActionProposalErrorV1::EmptyId("action"));
        }
        if self.effect_class.as_str().is_empty() {
            return Err(ActionProposalErrorV1::EmptyId("effect class"));
        }
        for (label, digest) in [
            ("arguments", self.arguments_digest),
            ("precondition", self.precondition_digest),
            ("evidence", self.evidence_digest),
        ] {
            if digest.is_zero() {
                return Err(ActionProposalErrorV1::EmptyDigest(label));
            }
        }
        if self.deadline_unix_ms == 0 {
            return Err(ActionProposalErrorV1::InvalidTimeWindow(
                "deadline must be nonzero",
            ));
        }
        if self.expiry_unix_ms == 0 {
            return Err(ActionProposalErrorV1::InvalidTimeWindow(
                "expiry must be nonzero",
            ));
        }
        if self.expiry_unix_ms < self.deadline_unix_ms {
            return Err(ActionProposalErrorV1::InvalidTimeWindow(
                "expiry must be at or after deadline",
            ));
        }
        if self.propensity == ProbabilityQ32::ZERO {
            return Err(ActionProposalErrorV1::ZeroPropensity);
        }
        Ok(())
    }

    /// Stable digest of the complete proposal payload.  The digest is an
    /// observation binding; it is not an authorization token.
    pub fn content_digest(&self) -> Result<Digest32, ActionProposalErrorV1> {
        self.validate()?;
        let mut bytes = Vec::with_capacity(256);
        bytes.extend_from_slice(ACTION_PROPOSAL_SCHEMA_V1.as_bytes());
        append_bytes(&mut bytes, self.action_id.as_str().as_bytes());
        bytes.extend_from_slice(self.arguments_digest.as_array());
        bytes.extend_from_slice(self.precondition_digest.as_array());
        append_bytes(&mut bytes, self.effect_class.as_str().as_bytes());
        bytes.extend_from_slice(&self.deadline_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.expiry_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.propensity.raw().to_be_bytes());
        bytes.extend_from_slice(self.evidence_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }

    pub const fn execution_mode(&self) -> ActionProposalExecutionModeV1 {
        Self::EXECUTION_MODE
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// The result is intentionally the same immutable payload.  The surrounding
/// [`CellRoleStepV1`] carries the state/output receipt; no separate executor
/// result is exposed by this crate.
pub type ActionProposalResultV1 = ActionProposalV1;

/// Errors local to proposal construction and validation.  A separate error
/// keeps the shared role adapter contract stable while still rejecting timing,
/// propensity, and disposition mistakes at this boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ActionProposalErrorV1 {
    Adapter(CellRoleAdapterErrorV1),
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    InvalidTimeWindow(&'static str),
    ZeroPropensity,
    NoSelectedAction,
    InvalidObservationTime,
    DeadlinePassed,
    Expired,
    ReplayMismatch,
}

impl fmt::Display for ActionProposalErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ActionProposalErrorV1 {}

impl From<CellRoleAdapterErrorV1> for ActionProposalErrorV1 {
    fn from(error: CellRoleAdapterErrorV1) -> Self {
        Self::Adapter(error)
    }
}

impl From<CellRoleContractErrorV1> for ActionProposalErrorV1 {
    fn from(error: CellRoleContractErrorV1) -> Self {
        Self::Adapter(CellRoleAdapterErrorV1::Contract(error))
    }
}

/// Adapter from a validated proposal to the common authority-free step
/// receipt.  It does not dispatch, reserve credentials, mutate a route, or
/// write a ledger.
pub struct ActionProposalAdapterV1;

impl ActionProposalAdapterV1 {
    pub const OWNER_MODULE: &'static str = "hepta-cell-roles::action-proposal";

    pub fn adapt(
        context: &CellAdapterContextV1,
        proposal: &ActionProposalV1,
    ) -> Result<CellRoleStepV1<ActionProposalResultV1>, ActionProposalErrorV1> {
        context.validate(CellRoleV1::ActionProposal)?;
        proposal.validate()?;
        let proposal_digest = proposal.content_digest()?;
        let state_successor_digest = digest_parts(
            b"hepta.cell-role.action-proposal-state.v1",
            &[
                context.state_predecessor_digest.as_array(),
                proposal_digest.as_array(),
            ],
        );
        let receipt = CellStepReceiptV1 {
            cell_id: context.cell_id.clone(),
            generation: context.generation,
            scope_digest: context.scope_digest,
            role: CellRoleV1::ActionProposal,
            capability_digest: context.capability_digest,
            input_frontier_digest: context.input_frontier_digest,
            state_predecessor_digest: context.state_predecessor_digest,
            state_successor_digest,
            output_digest: proposal_digest,
            uncertainty_ppm: 0,
            ood_ppm: 0,
            resource_receipt_digest: context.resource_receipt_digest,
            evidence_digest: context.evidence_digest,
            status: CellStepStatusV1::Accepted,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.validate()?;
        Ok(CellRoleStepV1 {
            result: proposal.clone(),
            receipt,
        })
    }

    /// Validate a proposal at the point where a downstream owner would
    /// consider dispatch. This remains proposal-only: credentials, effects,
    /// and provider calls belong to the downstream owner.
    pub fn qualify(
        proposal: &ActionProposalV1,
        observed_at_unix_ms: u64,
    ) -> Result<ActionProposalQualificationReceiptV1, ActionProposalErrorV1> {
        proposal.validate()?;
        if observed_at_unix_ms == 0 {
            return Err(ActionProposalErrorV1::InvalidObservationTime);
        }
        if observed_at_unix_ms > proposal.expiry_unix_ms {
            return Err(ActionProposalErrorV1::Expired);
        }
        if observed_at_unix_ms > proposal.deadline_unix_ms {
            return Err(ActionProposalErrorV1::DeadlinePassed);
        }
        let proposal_digest = proposal.content_digest()?;
        let qualification_digest = digest_parts(
            b"hepta.cell-role.action-proposal-qualification.v1",
            &[
                proposal_digest.as_array(),
                &observed_at_unix_ms.to_be_bytes(),
                &[u8::from(ACTION_PROPOSAL_EXECUTION_ALLOWED_V1)],
            ],
        );
        Ok(ActionProposalQualificationReceiptV1 {
            proposal_digest,
            observed_at_unix_ms,
            execution_allowed: ACTION_PROPOSAL_EXECUTION_ALLOWED_V1,
            authority: AuthorityPosture::DENY_ALL,
            qualification_digest,
        })
    }

    /// Recompute the typed proposal digest and compare it with a persisted
    /// qualification receipt. The observation timestamp is part of the
    /// qualification binding so a receipt cannot silently be replayed as a
    /// fresh expiry check.
    pub fn replay(
        proposal: &ActionProposalV1,
        receipt: &ActionProposalQualificationReceiptV1,
    ) -> Result<(), ActionProposalErrorV1> {
        receipt.validate()?;
        let replayed = Self::qualify(proposal, receipt.observed_at_unix_ms)?;
        if replayed != *receipt {
            return Err(ActionProposalErrorV1::ReplayMismatch);
        }
        Ok(())
    }

    /// Constructs a proposal only from a selected calibrated candidate.  An
    /// abstention or slow path is never silently converted into an action.
    pub fn from_calibrated_receipt(
        receipt: &CalibratedIntuitionReceiptV1,
        arguments_digest: Digest32,
        precondition_digest: Digest32,
        effect_class: StableId,
        deadline_unix_ms: u64,
        expiry_unix_ms: u64,
    ) -> Result<ActionProposalV1, ActionProposalErrorV1> {
        let action_id = match &receipt.disposition {
            CalibratedDispositionV1::Selected(action_id) => action_id.clone(),
            CalibratedDispositionV1::Abstained(_) | CalibratedDispositionV1::SlowPath(_) => {
                return Err(ActionProposalErrorV1::NoSelectedAction);
            }
        };
        let propensity = receipt
            .propensities
            .iter()
            .find(|candidate| candidate.candidate_id == action_id)
            .map(|candidate| candidate.probability)
            .ok_or(ActionProposalErrorV1::NoSelectedAction)?;
        let proposal = ActionProposalV1 {
            action_id,
            arguments_digest,
            precondition_digest,
            effect_class,
            deadline_unix_ms,
            expiry_unix_ms,
            propensity,
            evidence_digest: receipt.receipt_digest,
        };
        proposal.validate()?;
        Ok(proposal)
    }

    /// Convenience composition of [`Self::from_calibrated_receipt`] and
    /// [`Self::adapt`].  The calibrated receipt is still only evidence for a
    /// proposal; this method never dispatches the selected action.
    pub fn adapt_calibrated_receipt(
        context: &CellAdapterContextV1,
        receipt: &CalibratedIntuitionReceiptV1,
        arguments_digest: Digest32,
        precondition_digest: Digest32,
        effect_class: StableId,
        deadline_unix_ms: u64,
        expiry_unix_ms: u64,
    ) -> Result<CellRoleStepV1<ActionProposalResultV1>, ActionProposalErrorV1> {
        let proposal = Self::from_calibrated_receipt(
            receipt,
            arguments_digest,
            precondition_digest,
            effect_class,
            deadline_unix_ms,
            expiry_unix_ms,
        )?;
        Self::adapt(context, &proposal)
    }
}

fn append_bytes(target: &mut Vec<u8>, bytes: &[u8]) {
    target.extend_from_slice(&(bytes.len() as u64).to_be_bytes());
    target.extend_from_slice(bytes);
}

fn digest_parts(domain: &[u8], fields: &[&[u8]]) -> Digest32 {
    let mut bytes = Vec::with_capacity(domain.len() + fields.len() * 40);
    append_bytes(&mut bytes, domain);
    for field in fields {
        append_bytes(&mut bytes, field);
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: u8) -> Digest32 {
        Digest32::of_bytes(&[value])
    }

    fn context() -> CellAdapterContextV1 {
        CellAdapterContextV1 {
            cell_id: id("cell.action.1"),
            generation: Generation::new(1).expect("generation"),
            scope_digest: digest(1),
            role: CellRoleV1::ActionProposal,
            capability_digest: digest(2),
            input_frontier_digest: digest(3),
            state_predecessor_digest: digest(4),
            resource_receipt_digest: digest(5),
            evidence_digest: digest(6),
        }
    }

    fn proposal() -> ActionProposalV1 {
        ActionProposalV1 {
            action_id: id("action.read"),
            arguments_digest: digest(7),
            precondition_digest: digest(8),
            effect_class: id("effect.read-only"),
            deadline_unix_ms: 100,
            expiry_unix_ms: 200,
            propensity: ProbabilityQ32::ONE,
            evidence_digest: digest(9),
        }
    }

    #[test]
    fn proposal_maps_to_authority_free_step_receipt() {
        let proposal = proposal();
        let step = ActionProposalAdapterV1::adapt(&context(), &proposal).expect("step");
        assert_eq!(step.result, proposal);
        assert_eq!(step.receipt.role, CellRoleV1::ActionProposal);
        assert_eq!(step.receipt.authority, AuthorityPosture::DENY_ALL);
        assert!(
            !step
                .receipt
                .content_digest()
                .expect("receipt digest")
                .is_zero()
        );
        assert!(!step.result.execution_mode().execution_allowed());
        assert!(!ACTION_PROPOSAL_EXECUTION_ALLOWED_V1);
    }

    #[test]
    fn proposal_rejects_invalid_window_and_zero_propensity() {
        let mut invalid = proposal();
        invalid.expiry_unix_ms = invalid.deadline_unix_ms - 1;
        assert!(matches!(
            invalid.validate(),
            Err(ActionProposalErrorV1::InvalidTimeWindow(_))
        ));
        invalid.expiry_unix_ms = invalid.deadline_unix_ms;
        invalid.propensity = ProbabilityQ32::ZERO;
        assert_eq!(
            invalid.validate(),
            Err(ActionProposalErrorV1::ZeroPropensity)
        );
    }

    #[test]
    fn proposal_digest_is_deterministic_and_binds_all_fields() {
        let proposal = proposal();
        let first = proposal.content_digest().expect("digest");
        assert_eq!(first, proposal.content_digest().expect("digest"));
        let mut changed = proposal.clone();
        changed.arguments_digest = digest(10);
        assert_ne!(first, changed.content_digest().expect("digest"));
    }

    #[test]
    fn proposal_qualification_is_replayable_and_denies_execution() {
        let proposal = proposal();
        let qualification = ActionProposalAdapterV1::qualify(&proposal, 100).expect("qualify");
        assert_eq!(
            qualification.proposal_digest,
            proposal.content_digest().expect("digest")
        );
        assert!(!qualification.execution_allowed);
        assert_eq!(qualification.authority, AuthorityPosture::DENY_ALL);
        ActionProposalAdapterV1::replay(&proposal, &qualification).expect("replay");
        assert_eq!(
            ActionProposalAdapterV1::qualify(&proposal, 150),
            Err(ActionProposalErrorV1::DeadlinePassed)
        );
        assert_eq!(
            ActionProposalAdapterV1::qualify(&proposal, 201),
            Err(ActionProposalErrorV1::Expired)
        );
    }
}
