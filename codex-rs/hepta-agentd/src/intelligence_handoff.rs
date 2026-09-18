use std::fmt;
use std::str::FromStr;

use codex_hepta_intelligence::IntelligenceContractErrorV1;
use codex_hepta_intelligence::IntelligenceHostEnvelopeV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::ContextAttachment;
use crate::RunPhase;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceDispatchProposalV1 {
    pub run_id: String,
    pub run_revision: u64,
    pub envelope_digest: Digest32,
    pub context_digest: Digest32,
    pub proposal_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IntelligenceHandoffErrorV1 {
    Contract(IntelligenceContractErrorV1),
    Run(AgentRunError),
    Binding(&'static str),
}

impl fmt::Display for IntelligenceHandoffErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for IntelligenceHandoffErrorV1 {}

/// Validate one intelligence facade envelope against the already-admitted Agentd
/// run and return a proposal-only dispatch receipt.
///
/// This is the named Agentd consumer for `IntelligenceHostEnvelopeV1`. It never
/// invokes Codex, a model, a tool, or an external effect, and it deliberately
/// does not advance the coordinator to `Dispatched`. The existing dispatch owner
/// remains responsible for calling `mark_dispatched` only after dispatch entry.
pub fn prepare_intelligence_dispatch_v1(
    coordinator: &mut AgentRunCoordinator,
    expected_revision: u64,
    attachment: &ContextAttachment,
    envelope: &IntelligenceHostEnvelopeV1,
) -> Result<IntelligenceDispatchProposalV1, IntelligenceHandoffErrorV1> {
    envelope
        .validate()
        .map_err(IntelligenceHandoffErrorV1::Contract)?;

    let current = coordinator
        .run(&attachment.run_id)
        .ok_or(IntelligenceHandoffErrorV1::Run(AgentRunError::RunNotFound))?;
    if current.revision != expected_revision {
        return Err(IntelligenceHandoffErrorV1::Run(
            AgentRunError::StaleRevision,
        ));
    }
    if current.phase != RunPhase::ContextAttached {
        return Err(IntelligenceHandoffErrorV1::Run(
            AgentRunError::ContextRequired,
        ));
    }

    // Re-admit the exact attachment through the existing coordinator. In the
    // ContextAttached state this is idempotent, but it still checks the stored
    // request/objective/body/artifact tuple before returning.
    let verified = coordinator
        .attach_context(expected_revision, attachment.clone())
        .map_err(IntelligenceHandoffErrorV1::Run)?;
    if verified.revision != expected_revision
        || verified.phase != RunPhase::ContextAttached
        || !verified.idempotent
    {
        return Err(IntelligenceHandoffErrorV1::Binding(
            "context verification",
        ));
    }

    if envelope.run_id.as_str() != attachment.run_id
        || envelope.request_digest.to_string() != attachment.request_digest
        || envelope.objective_digest.to_string() != attachment.objective_digest
        || envelope.context_digest.to_string() != attachment.context_digest
    {
        return Err(IntelligenceHandoffErrorV1::Binding(
            "run/request/objective/context",
        ));
    }

    let context_digest = Digest32::from_str(&attachment.context_digest)
        .map_err(|_| IntelligenceHandoffErrorV1::Binding("context digest"))?;
    let proposal_digest = proposal_digest(
        &attachment.run_id,
        expected_revision,
        envelope.envelope_digest,
        context_digest,
    );
    Ok(IntelligenceDispatchProposalV1 {
        run_id: attachment.run_id.clone(),
        run_revision: expected_revision,
        envelope_digest: envelope.envelope_digest,
        context_digest,
        proposal_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn proposal_digest(
    run_id: &str,
    revision: u64,
    envelope_digest: Digest32,
    context_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.intelligence-dispatch-proposal.v1\0".to_vec();
    bytes.extend_from_slice(&u32::try_from(run_id.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(run_id.as_bytes());
    bytes.extend_from_slice(&revision.to_be_bytes());
    bytes.extend_from_slice(envelope_digest.as_array());
    bytes.extend_from_slice(context_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "intelligence_handoff_tests.rs"]
mod tests;
