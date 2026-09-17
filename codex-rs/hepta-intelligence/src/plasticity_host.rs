//! Product-side composition for governed plasticity proposal persistence.
//!
//! This adapter is deliberately proposal-only. It authenticates and constructs
//! a governed parameter proposal in `learning.plasticity`, then appends the
//! authority-free V2 record to the host-opened durable proposal registry. The
//! returned anchor must be retained by the host in an independent rollback
//! domain before the append is treated as externally acknowledged.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_plasticity::{
    DurableProposalAppendReceiptV1, DurableProposalRegistry, DurableProposalRegistryError,
    DurableRegistryAnchorV1, GovernedParameterProposalRequestV3, GovernedParameterProposalV3,
    GovernedProposalError, propose_governed_v3,
};
use codex_hepta_types::Digest32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableGovernedPlasticityReceiptV3 {
    pub governed: GovernedParameterProposalV3,
    pub durable: DurableProposalAppendReceiptV1,
    /// Persist this outside the registry file rollback domain before acknowledging the write.
    pub next_anchor: DurableRegistryAnchorV1,
}

#[derive(Debug)]
pub enum PlasticityHostErrorV3 {
    Governed(GovernedProposalError),
    Durable(DurableProposalRegistryError),
    MissingAnchorAfterAppend,
    AnchorReceiptMismatch,
}

impl fmt::Display for PlasticityHostErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityHostErrorV3 {}
impl From<GovernedProposalError> for PlasticityHostErrorV3 {
    fn from(value: GovernedProposalError) -> Self {
        Self::Governed(value)
    }
}
impl From<DurableProposalRegistryError> for PlasticityHostErrorV3 {
    fn from(value: DurableProposalRegistryError) -> Self {
        Self::Durable(value)
    }
}

/// Construct and durably append one governed plasticity proposal.
///
/// `expected_predecessor_frame_digest` must be the exact local durable head.
/// The registry itself must have been opened under the host's production anchor
/// policy. This function never activates, selects, promotes, releases, or
/// installs the proposal.
pub fn propose_and_persist_plasticity_v3(
    request: GovernedParameterProposalRequestV3<'_>,
    verifier: &LearningEvidenceVerifierV1,
    artifacts: &ArtifactRegistry,
    registry: &mut DurableProposalRegistry,
    expected_predecessor_frame_digest: Digest32,
    now: u64,
) -> Result<DurableGovernedPlasticityReceiptV3, PlasticityHostErrorV3> {
    let governed = propose_governed_v3(request, verifier, artifacts, now)?;
    let durable = registry.append_v2(
        expected_predecessor_frame_digest,
        governed.proposal.clone(),
    )?;
    let next_anchor = registry
        .current_anchor()?
        .ok_or(PlasticityHostErrorV3::MissingAnchorAfterAppend)?;
    if next_anchor.sequence != durable.sequence || next_anchor.frame_digest != durable.frame_digest {
        return Err(PlasticityHostErrorV3::AnchorReceiptMismatch);
    }
    Ok(DurableGovernedPlasticityReceiptV3 {
        governed,
        durable,
        next_anchor,
    })
}
