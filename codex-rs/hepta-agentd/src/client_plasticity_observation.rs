//! Full raw original row response. Custody comes from the authenticated peer.
use super::*;
use codex_hepta_agent_components::plasticity::DurableCompletedProposalV1;
use codex_hepta_agent_components::plasticity::MAX_COMPLETED_PROPOSAL_BYTES_V1;
impl AgentdClient {
    pub async fn plasticity_completed_proposal(
        &self,
        proposal: codex_hepta_agent_components::types::StableId,
    ) -> Result<(u64, Option<DurableCompletedProposalV1>), AgentdError> {
        let proposal_id = proposal.to_string();
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::PlasticityCompletedProposal {
                    proposal_id: proposal_id.clone(),
                },
            })
            .await?;
        match response.payload {
            AgentdPayload::PlasticityCompletedProposal {
                proposal_id: actual,
                observation_hex,
            } if actual == proposal_id => {
                let row = observation_hex
                    .map(|hex| {
                        if hex.len() > 2 * MAX_COMPLETED_PROPOSAL_BYTES_V1 || hex.len() % 2 != 0 {
                            return Err(AgentdError::Protocol(
                                "plasticity whole response bound".into(),
                            ));
                        }
                        let mut bytes = Vec::with_capacity(hex.len() / 2);
                        for pair in hex.as_bytes().chunks_exact(2) {
                            let nibble = |byte| match byte {
                                b'0'..=b'9' => Ok(byte - b'0'),
                                b'a'..=b'f' => Ok(byte - b'a' + 10),
                                _ => Err(AgentdError::Protocol("plasticity response hex".into())),
                            };
                            bytes.push(nibble(pair[0])? * 16 + nibble(pair[1])?);
                        }
                        let row =
                            DurableCompletedProposalV1::from_bytes(&bytes).map_err(|error| {
                                AgentdError::Protocol(format!(
                                    "plasticity original row codec: {error}"
                                ))
                            })?;
                        if row.proposal.proposal_id != proposal {
                            return Err(AgentdError::Protocol(
                                "plasticity response identity".into(),
                            ));
                        }
                        Ok(row)
                    })
                    .transpose()?;
                Ok((response.current_generation, row))
            }
            payload => unexpected(payload),
        }
    }
}
