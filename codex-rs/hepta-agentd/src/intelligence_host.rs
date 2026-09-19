//! Product-side consumer for the intelligence composition envelope.
//!
//! This module does not run a second model/tool loop. It validates the bounded
//! authority-free envelope produced by intelligence.control and returns an
//! agentd-owned handoff receipt that can be inserted into the V3 predecessor
//! chain before Codex/App Server execution is attempted by its existing owner.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence::HostEnvelopePortV3;
use codex_hepta_intelligence::IntelligenceContractErrorV1;
use codex_hepta_intelligence::IntelligenceHostEnvelopeV1;
use codex_hepta_intelligence::LaneFStageV3;
use codex_hepta_intelligence::PortDecisionV3;
use codex_hepta_intelligence::PortFailureClassV3;
use codex_hepta_intelligence::PortFailureV3;
use codex_hepta_intelligence::PortInputV3;
use codex_hepta_intelligence::PortReceiptV3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceAcceptanceV1 {
    pub run_id: StableId,
    pub envelope_digest: Digest32,
    pub acceptance_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentdIntelligenceErrorV1 {
    InvalidEnvelope(IntelligenceContractErrorV1),
    WrongConsumer,
    StageMismatch,
    SnapshotMismatch,
    PredecessorMismatch,
    Arithmetic,
}

impl fmt::Display for AgentdIntelligenceErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AgentdIntelligenceErrorV1 {}

#[derive(Clone, Copy, Debug, Default)]
pub struct AgentdIntelligenceHostV1;

impl AgentdIntelligenceHostV1 {
    pub fn accept(
        &self,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<AgentdIntelligenceAcceptanceV1, AgentdIntelligenceErrorV1> {
        envelope
            .validate()
            .map_err(AgentdIntelligenceErrorV1::InvalidEnvelope)?;
        if envelope.consumer_id.as_str() != "runtime.agentd" {
            return Err(AgentdIntelligenceErrorV1::WrongConsumer);
        }
        let mut bytes = b"hepta.agentd.intelligence-acceptance.v1\0".to_vec();
        push_id(&mut bytes, &envelope.run_id)?;
        bytes.extend_from_slice(envelope.envelope_digest.as_array());
        bytes.extend_from_slice(envelope.snapshot_digest.as_array());
        let acceptance_digest = Digest32::of_bytes(&bytes);
        Ok(AgentdIntelligenceAcceptanceV1 {
            run_id: envelope.run_id.clone(),
            envelope_digest: envelope.envelope_digest,
            acceptance_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    pub fn port_receipt(
        &self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        let rejection = || PortFailureV3 {
            class: PortFailureClassV3::Rejected,
            evidence_digest: handoff_failure_digest(input, envelope),
        };
        if input.stage != LaneFStageV3::HostHandoffAccepted {
            return Err(rejection());
        }
        if input.run_id != envelope.run_id {
            return Err(rejection());
        }
        if input.snapshot_digest != envelope.snapshot_digest {
            return Err(rejection());
        }
        if input.predecessor_digest != envelope.envelope_digest {
            return Err(rejection());
        }
        let acceptance = self.accept(envelope).map_err(|_| rejection())?;
        let producer = StableId::new("runtime.agentd").map_err(|_| rejection())?;
        Ok(PortReceiptV3 {
            stage: input.stage,
            producer,
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest: acceptance.acceptance_digest,
            decision: PortDecisionV3::Continue,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

impl HostEnvelopePortV3 for AgentdIntelligenceHostV1 {
    fn accept_host_envelope_v3(
        &mut self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.port_receipt(input, envelope)
    }
}

fn handoff_failure_digest(input: &PortInputV3, envelope: &IntelligenceHostEnvelopeV1) -> Digest32 {
    let mut bytes = b"hepta.agentd.intelligence-handoff-failure.v1\0".to_vec();
    bytes.extend_from_slice(input.snapshot_digest.as_array());
    bytes.extend_from_slice(input.predecessor_digest.as_array());
    bytes.extend_from_slice(envelope.envelope_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), AgentdIntelligenceErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| AgentdIntelligenceErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("fixture id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn envelope() -> IntelligenceHostEnvelopeV1 {
        IntelligenceHostEnvelopeV1::new(
            id("run"),
            digest("snapshot"),
            digest("objective"),
            digest("candidate-set"),
            digest("utility"),
            digest("evaluation"),
            Some(digest("neural")),
            Some(digest("prompt")),
            digest("intuition"),
            digest("context"),
            digest("pre-handoff"),
            10_000,
        )
        .expect("envelope")
    }

    #[test]
    fn agentd_accepts_only_the_exact_intelligence_envelope() {
        let host = AgentdIntelligenceHostV1;
        let envelope = envelope();
        let input = PortInputV3 {
            run_id: envelope.run_id.clone(),
            snapshot_digest: envelope.snapshot_digest,
            predecessor_digest: envelope.envelope_digest,
            budget_micros: 1_000,
            stage: LaneFStageV3::HostHandoffAccepted,
        };
        let receipt = host.port_receipt(&input, &envelope).expect("acceptance");
        assert_eq!(receipt.producer.as_str(), "runtime.agentd");
        assert_eq!(receipt.predecessor_digest, envelope.envelope_digest);
        assert!(!receipt.authority.grants_any());

        let mut tampered = envelope.clone();
        tampered.context_digest = digest("tampered");
        assert!(host.port_receipt(&input, &tampered).is_err());
    }
}
