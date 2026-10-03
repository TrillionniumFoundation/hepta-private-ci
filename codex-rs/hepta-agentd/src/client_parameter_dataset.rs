//! Pure complete dataset receipt; the original peer supplies no signing grant.
use super::*;
use codex_hepta_agent_components::learning_ledger::ReviewDatasetWireV1;
use codex_hepta_agent_components::learning_ledger::verify_dataset_snapshot_receipt_v3;
use codex_hepta_agent_components::types::Digest32;

impl AgentdClient {
    /// Returns runtime generation, same-held Ledger facts and actual proposal
    /// predecessor. No record is appended and no principal expiry is extended.
    pub async fn prepare_parameter_dataset_v1(
        &self,
        round: crate::AgentdSelfIterationRoundV1,
        producer_path: std::path::PathBuf,
        producer_pin: Digest32,
        plan_path: std::path::PathBuf,
        plan_pin: Digest32,
    ) -> Result<(u64, crate::PreparedParameterDatasetV1), AgentdError> {
        if producer_pin.is_zero()
            || plan_pin.is_zero()
            || !producer_path.is_absolute()
            || !plan_path.is_absolute()
        {
            return Err(AgentdError::Invalid(
                "protected dataset sources/pins".into(),
            ));
        }
        let round_hex = encode_hex(&round.canonical_bytes()?);
        let producer_source = producer_path
            .to_str()
            .ok_or_else(|| AgentdError::Invalid("producer path UTF-8".into()))?
            .to_owned();
        let plan_source = plan_path
            .to_str()
            .ok_or_else(|| AgentdError::Invalid("plan path UTF-8".into()))?
            .to_owned();
        let producer_digest = producer_pin.to_string();
        let plan_digest = plan_pin.to_string();
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::PrepareParameterDatasetV1 {
                    round_hex: round_hex.clone(),
                    producer_source: producer_source.clone(),
                    producer_digest: producer_digest.clone(),
                    plan_source: plan_source.clone(),
                    plan_digest: plan_digest.clone(),
                },
            })
            .await?;
        match response.payload {
            AgentdPayload::PreparedParameterDatasetV1 {
                round_hex: actual_round,
                producer_source: actual_producer,
                producer_digest: actual_producer_pin,
                plan_source: actual_plan,
                plan_digest: actual_plan_pin,
                dataset_json,
                ledger_head_digest,
                ledger_record_count,
                freeze_payload_hex,
                proposal_registry_predecessor,
                installed_artifact_head,
            } if actual_round == round_hex
                && actual_producer == producer_source
                && actual_producer_pin == producer_digest
                && actual_plan == plan_source
                && actual_plan_pin == plan_digest =>
            {
                let dataset: ReviewDatasetWireV1 = serde_json::from_str(&dataset_json)?;
                let native = dataset
                    .native()
                    .map_err(|e| AgentdError::Protocol(e.to_string()))?;
                let now = crate::authbus_ingress::now_ms()?;
                verify_dataset_snapshot_receipt_v3(&native, now)
                    .map_err(|e| AgentdError::Protocol(e.to_string()))?;
                let head: Digest32 = ledger_head_digest
                    .parse()
                    .map_err(|e| AgentdError::Protocol(format!("dataset head: {e}")))?;
                let predecessor: Digest32 = proposal_registry_predecessor
                    .parse()
                    .map_err(|e| AgentdError::Protocol(format!("proposal predecessor: {e}")))?;
                let installed_head: Digest32 = installed_artifact_head
                    .parse()
                    .map_err(|e| AgentdError::Protocol(format!("installed artifact head: {e}")))?;
                if head.is_zero()
                    || head.to_string() != ledger_head_digest
                    || head != native.snapshot.ledger_head_digest
                    || ledger_record_count < native.snapshot.eligible_frontier
                    || predecessor.to_string() != proposal_registry_predecessor
                    || installed_head.is_zero()
                    || installed_head.to_string() != installed_artifact_head
                    || crate::parameter_admission_query::decode_hex(&freeze_payload_hex)?.is_empty()
                    || now < round.admitted_at_ms()
                    || now >= round.deadline_ms()
                {
                    return Err(AgentdError::Protocol(
                        "dataset complete facts binding".into(),
                    ));
                }
                Ok((
                    response.current_generation,
                    crate::PreparedParameterDatasetV1 {
                        dataset,
                        ledger_head_digest,
                        ledger_record_count,
                        freeze_payload_hex,
                        proposal_registry_predecessor,
                        installed_artifact_head,
                    },
                ))
            }
            payload => unexpected(payload),
        }
    }
}
