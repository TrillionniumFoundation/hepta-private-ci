//! Explicit bounded window facts from the same authenticated original peer.
use super::*;
use codex_hepta_agent_components::types::Digest32;
impl AgentdClient {
    /// Returns runtime generation and the whole original unsigned owner result.
    /// The independent Evaluator still authenticates its original Ledger witness.
    pub async fn prepare_parameter_dataset_window_v3(
        &self,
        round: crate::AgentdSelfIterationRoundV1,
        producer_path: std::path::PathBuf,
        producer_pin: Digest32,
        plan_path: std::path::PathBuf,
        plan_pin: Digest32,
    ) -> Result<(u64, crate::PreparedParameterDatasetWindowV3), AgentdError> {
        if producer_pin.is_zero()
            || plan_pin.is_zero()
            || !producer_path.is_absolute()
            || !plan_path.is_absolute()
        {
            return Err(AgentdError::Invalid("protected window sources/pins".into()));
        }
        let round_hex = encode_hex(&round.canonical_bytes()?);
        let producer_source = producer_path
            .to_str()
            .ok_or_else(|| AgentdError::Invalid("window producer path UTF-8".into()))?
            .to_owned();
        let plan_source = plan_path
            .to_str()
            .ok_or_else(|| AgentdError::Invalid("window plan path UTF-8".into()))?
            .to_owned();
        let producer_digest = producer_pin.to_string();
        let plan_digest = plan_pin.to_string();
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::PrepareParameterDatasetWindowV3 {
                    round_hex: round_hex.clone(),
                    producer_source: producer_source.clone(),
                    producer_digest: producer_digest.clone(),
                    plan_source: plan_source.clone(),
                    plan_digest: plan_digest.clone(),
                },
            })
            .await?;
        match response.payload {
            AgentdPayload::PreparedParameterDatasetWindowV3 {
                round_hex: actual_round,
                producer_source: actual_producer,
                producer_digest: actual_producer_pin,
                plan_source: actual_plan,
                plan_digest: actual_plan_pin,
                facts_json,
            } if actual_round == round_hex
                && actual_producer == producer_source
                && actual_producer_pin == producer_digest
                && actual_plan == plan_source
                && actual_plan_pin == plan_digest =>
            {
                let result = crate::PreparedParameterDatasetWindowV3::from_source_bytes(
                    facts_json.as_bytes(),
                )?;
                result.validate_at(&round, crate::authbus_ingress::now_ms()?)?;
                Ok((response.current_generation, result))
            }
            payload => unexpected(payload),
        }
    }
}
