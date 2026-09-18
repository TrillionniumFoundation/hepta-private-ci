//! Governed plasticity proposal records.
//!
//! Parameter V2 remains the stable proposal envelope. Parameter V3 adds a
//! deterministic generator-complete search profile, and topology V2 adds typed
//! structural proposal construction. Historical V1 records remain read-only.
//! Every surface is proposal-only: this crate has no API for runtime mutation,
//! authority mutation, self-promotion, selection, activation or release.

#![forbid(unsafe_code)]

mod durable_registry;
mod generator_v3;
mod legacy;
mod mutation_grammar_v1;
mod parameter_v2;
mod registry;
mod topology_v2;
mod types;

pub use durable_registry::DurableProposalAppendReceiptV1;
pub use durable_registry::DurableProposalRegistry;
pub use durable_registry::DurableProposalRegistryError;
pub use durable_registry::DurableRegistryAnchorV1;
pub use generator_v3::GeneratedParameterCandidateSetV3;
pub use generator_v3::ParameterGeneratorErrorV3;
pub use generator_v3::ParameterGeneratorProfileV3;
pub use generator_v3::ParameterPlasticitySignalV3;
pub use generator_v3::generate_parameter_candidates_v3;
pub use generator_v3::parameter_generator_signing_payload_v3;
pub use generator_v3::verify_generated_parameter_candidates_v3;
pub use mutation_grammar_v1::MutationGrammarErrorV1;
pub use mutation_grammar_v1::MutationGrammarManifestV1;
pub use mutation_grammar_v1::MutationSurfaceV1;
pub use mutation_grammar_v1::ParameterMutationRuleV1;
pub use mutation_grammar_v1::authorize_parameter_mutation_v1;
pub use mutation_grammar_v1::build_mutation_grammar_manifest_v1;
pub use mutation_grammar_v1::verify_mutation_grammar_manifest_v1;
pub use parameter_v2::propose_v2;
pub use parameter_v2::verify_parameter_proposal_v2;
pub use registry::ProposalRegistry;
pub use registry::ProposalRegistrySlotV2;
pub use topology_v2::TopologyCandidateKindV2;
pub use topology_v2::TopologyCandidateV2;
pub use topology_v2::TopologyChangeV2;
pub use topology_v2::TopologyOperationV2;
pub use topology_v2::TopologyProposalErrorV2;
pub use topology_v2::TopologyProposalRequestV2;
pub use topology_v2::TopologyProposalV2;
pub use topology_v2::propose_topology_v2;
pub use topology_v2::verify_topology_proposal_v2;
pub use types::AppendDisposition;
pub use types::CandidateNormMetricsV2;
pub use types::Error;
pub use types::LayerNormDenominatorV2;
pub use types::LayerRelativeNormV2;
pub use types::ParameterCandidateKindV2;
pub use types::ParameterCandidateRequestV2;
pub use types::ParameterCandidateV2;
pub use types::ParameterDelta;
pub use types::ParameterDeltaV2;
pub use types::ParameterNormProfileV2;
pub use types::ParameterProposalRequestV2;
pub use types::ParameterProposalV2;
pub use types::PlasticityProposal;
pub use types::ProposalDigestVerification;
pub use types::ProposalReadResult;
pub use types::ProposalRecord;
pub use types::ProposalRequest;
pub use types::ProposalStatus;
pub use types::ProposalVersion;
pub use types::ProposalWindowV2;
pub use types::ProposalWriteRequest;
pub use types::TopologyDelta;
pub use types::TopologyOperation;

use types::LEGACY_V1;
use types::PARAMETER_V2;

#[cfg(test)]
use codex_hepta_types::Digest32;
#[cfg(test)]
use codex_hepta_types::FixedQ32;
#[cfg(test)]
use codex_hepta_types::Generation;
#[cfg(test)]
use codex_hepta_types::StableId;

/// The legacy V1 writer is deliberately disabled. Historical records remain
/// available through read_versioned_proposal.
pub fn propose(_request: ProposalRequest) -> Result<PlasticityProposal, Error> {
    Err(Error::LegacyWriteDisabled)
}

pub fn dispatch_proposal_version(version: u16) -> Result<ProposalVersion, Error> {
    match version {
        LEGACY_V1 => Ok(ProposalVersion::LegacyV1),
        PARAMETER_V2 => Ok(ProposalVersion::ParameterV2),
        value => Err(Error::UnsupportedVersion(value)),
    }
}

pub fn propose_versioned(request: ProposalWriteRequest) -> Result<ProposalRecord, Error> {
    match request {
        ProposalWriteRequest::LegacyV1(_) => Err(Error::LegacyWriteDisabled),
        ProposalWriteRequest::ParameterV2(request) => propose_v2(*request)
            .map(Box::new)
            .map(ProposalRecord::ParameterV2),
    }
}

/// Dispatch and validate a typed record without changing its version.
///
/// A successful V1 read reports that historical digest verification is
/// unavailable; it does not authenticate the record's provenance.
pub fn read_versioned_proposal(
    version: u16,
    record: ProposalRecord,
) -> Result<ProposalReadResult, Error> {
    let declared = dispatch_proposal_version(version)?;
    if declared != record.version() {
        return Err(Error::VersionPayloadMismatch);
    }
    let digest_verification = match &record {
        ProposalRecord::LegacyV1(proposal) => {
            legacy::validate_legacy_v1_read(proposal)?;
            ProposalDigestVerification::UnavailableLegacyMissingMaximumAbsoluteDelta
        }
        ProposalRecord::ParameterV2(proposal) => {
            verify_parameter_proposal_v2(proposal)?;
            ProposalDigestVerification::VerifiedV2
        }
    };
    Ok(ProposalReadResult {
        record,
        digest_verification,
    })
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
