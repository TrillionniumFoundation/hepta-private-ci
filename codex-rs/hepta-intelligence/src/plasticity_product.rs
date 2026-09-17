//! Product composition for governed plasticity proposal writes.
//!
//! This is the named product caller for `learning.plasticity`. It authenticates
//! a prepared proposal against current artifact/evidence state and writes only
//! through the externally anchored production registry. It cannot install
//! weights, mutate topology, select, promote, activate or release a candidate.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_plasticity::DurableProposalAnchorStoreV1;
use codex_hepta_plasticity::GovernedParameterProposalAttestationsV3;
use codex_hepta_plasticity::GovernedParameterProposalErrorV3;
use codex_hepta_plasticity::GovernedParameterProposalV3;
use codex_hepta_plasticity::PlasticityEvidenceResolverV3;
use codex_hepta_plasticity::PreparedGovernedParameterProposalV3;
use codex_hepta_plasticity::ProductionProposalAppendReceiptV1;
use codex_hepta_plasticity::ProductionProposalRegistryErrorV1;
use codex_hepta_plasticity::ProductionProposalRegistryV1;
use codex_hepta_plasticity::admit_governed_parameter_proposal_v3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityProductRequestV1 {
    pub prepared: PreparedGovernedParameterProposalV3,
    pub attestations: GovernedParameterProposalAttestationsV3,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityProductReceiptV1 {
    pub proposal_id: StableId,
    pub governance_digest: Digest32,
    pub governed: GovernedParameterProposalV3,
    pub durable: ProductionProposalAppendReceiptV1,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlasticityProductStageV1 {
    GovernedAdmission,
    DurableProposalWrite,
    ExternalAnchorAcknowledgement,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityProductEventV1 {
    pub stage: PlasticityProductStageV1,
    pub proposal_digest: Digest32,
    pub governance_digest: Digest32,
    pub sequence: Option<u64>,
}

/// The selected host owns the telemetry backend. Events deliberately contain
/// digests and sequence only; raw evidence/parameter values never enter logs.
pub trait PlasticityProductEventSinkV1 {
    fn record(&mut self, event: PlasticityProductEventV1);
}

#[derive(Debug)]
pub enum PlasticityProductErrorV1 {
    Governed(GovernedParameterProposalErrorV3),
    Registry(ProductionProposalRegistryErrorV1),
}

impl fmt::Display for PlasticityProductErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityProductErrorV1 {}
impl From<GovernedParameterProposalErrorV3> for PlasticityProductErrorV1 {
    fn from(value: GovernedParameterProposalErrorV3) -> Self {
        Self::Governed(value)
    }
}
impl From<ProductionProposalRegistryErrorV1> for PlasticityProductErrorV1 {
    fn from(value: ProductionProposalRegistryErrorV1) -> Self {
        Self::Registry(value)
    }
}

/// Authenticate and durably retain one proposal.
///
/// The prepared context is recomputed inside admission, so an artifact
/// quarantine/revocation or evidence disappearance between prepare and commit
/// fails closed. The production registry synchronizes the proposal frame before
/// atomically advancing the independent anti-rollback anchor.
pub fn run_governed_plasticity_v1<R, S, E>(
    request: PlasticityProductRequestV1,
    artifacts: &ArtifactRegistry,
    resolver: &mut R,
    verifier: &LearningEvidenceVerifierV1,
    registry: &mut ProductionProposalRegistryV1<S>,
    events: &mut E,
    now: u64,
) -> Result<PlasticityProductReceiptV1, PlasticityProductErrorV1>
where
    R: PlasticityEvidenceResolverV3,
    S: DurableProposalAnchorStoreV1,
    E: PlasticityProductEventSinkV1,
{
    let governed = admit_governed_parameter_proposal_v3(
        request.prepared,
        &request.attestations,
        artifacts,
        resolver,
        verifier,
        now,
    )?;
    events.record(PlasticityProductEventV1 {
        stage: PlasticityProductStageV1::GovernedAdmission,
        proposal_digest: governed.proposal.proposal_digest,
        governance_digest: governed.governance_digest,
        sequence: None,
    });

    let durable = registry.append_v2(governed.proposal.clone())?;
    events.record(PlasticityProductEventV1 {
        stage: PlasticityProductStageV1::DurableProposalWrite,
        proposal_digest: governed.proposal.proposal_digest,
        governance_digest: governed.governance_digest,
        sequence: Some(durable.durable.sequence),
    });
    events.record(PlasticityProductEventV1 {
        stage: PlasticityProductStageV1::ExternalAnchorAcknowledgement,
        proposal_digest: governed.proposal.proposal_digest,
        governance_digest: governed.governance_digest,
        sequence: Some(durable.acknowledged_anchor.sequence),
    });

    Ok(PlasticityProductReceiptV1 {
        proposal_id: governed.proposal.proposal_id.clone(),
        governance_digest: governed.governance_digest,
        governed,
        durable,
        authority: AuthorityPosture::DENY_ALL,
    })
}
