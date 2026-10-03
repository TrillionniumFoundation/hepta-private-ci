//! Whole public dataset facts through the same Root-only control transport.
use super::*;
use crate::plasticity_runtime::parameter_dataset::ProtectedParameterDatasetV1;
use codex_hepta_agent_components::types::Digest32;

impl AgentdState {
    pub(crate) async fn prepare_parameter_dataset_payload(
        &self,
        round_hex: String,
        producer_source: String,
        producer_digest: String,
        plan_source: String,
        plan_digest: String,
    ) -> Result<crate::AgentdPayload, AgentdError> {
        let round = crate::AgentdSelfIterationRoundV1::decode(
            &crate::parameter_admission_query::decode_hex(&round_hex)?,
        )?;
        let expected_round = round.clone();
        let generation = self.current_generation()?;
        let source =
            |path: &str, digest: &str| -> Result<(std::path::PathBuf, Digest32), AgentdError> {
                let path = std::path::PathBuf::from(path);
                let pin: Digest32 = digest
                    .parse()
                    .map_err(|e| AgentdError::Invalid(format!("dataset pin: {e}")))?;
                if !path.is_absolute() || pin.is_zero() || pin.to_string() != digest {
                    return Err(AgentdError::Protocol("protected dataset source/pin".into()));
                }
                Ok((path, pin))
            };
        let request = ProtectedParameterDatasetV1 {
            round,
            producer: source(&producer_source, &producer_digest)?,
            plan: source(&plan_source, &plan_digest)?,
        };
        let iteration = self
            .self_iteration_handle
            .get()
            .ok_or_else(|| AgentdError::Invalid("original Round owner unavailable".into()))?;
        let handle = self
            .plasticity_runtime_handle()
            .ok_or_else(|| AgentdError::Invalid("original plasticity owner unavailable".into()))?;
        let facts = handle
            .prepare_parameter_dataset_v1(iteration, request)
            .await
            .map_err(|e| AgentdError::Invalid(e.to_string()))?;
        if self.current_generation()? != generation
            || iteration
                .inspect_current_round()
                .await?
                .is_none_or(|v| v.status.round != expected_round)
        {
            return Err(AgentdError::GenerationFenced(
                "dataset original Round/runtime changed".into(),
            ));
        }
        Ok(crate::AgentdPayload::PreparedParameterDatasetV1 {
            round_hex,
            producer_source,
            producer_digest,
            plan_source,
            plan_digest,
            dataset_json: serde_json::to_string(&facts.dataset)?,
            ledger_head_digest: facts.ledger_head_digest,
            ledger_record_count: facts.ledger_record_count,
            freeze_payload_hex: facts.freeze_payload_hex,
            proposal_registry_predecessor: facts.proposal_registry_predecessor,
            installed_artifact_head: facts.installed_artifact_head,
        })
    }
}
