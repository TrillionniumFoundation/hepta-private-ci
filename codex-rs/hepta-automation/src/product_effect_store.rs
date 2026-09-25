//! Immutable product preparation and completion receipts in the existing owner database.
use super::product_effect::*;
use crate::AuthorizedEffectIntent;
use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use codex_hepta_contracts::ProviderEffectKey;
use sqlx::Row;

impl AutomationStore {
    pub(super) async fn insert_product_effect_preparation(
        &self,
        request: &ProductEffectPreparationRequestV1,
        expected: &ProductEffectPreparationV1,
    ) -> Result<ProductEffectPreparationV1, TaskFlowError> {
        let intent_json = serde_json::to_string(&expected.intent).map_err(|error| {
            TaskFlowError::Corrupt(format!("product effect intent serialization: {error}"))
        })?;
        let inserted = sqlx::query(
            "INSERT INTO automation_product_effect_preparations (
                 owner_agent_id, operation_id, run_id, step_id, attempt,
                 intent_json, intent_digest, payload_digest, provider_key, provider_scope, preparation_digest,
                 provider_profile_digest, definition_digest, prepared_generation,
                 prepared_at_ms, lease_deadline_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&request.operation_id)
        .bind(&expected.intent.run_id)
        .bind(&expected.intent.step_id)
        .bind(i64::from(expected.intent.attempt))
        .bind(intent_json)
        .bind(expected.intent_digest.as_str())
        .bind(expected.intent.payload_digest.as_str())
        .bind(&expected.provider_key)
        .bind(&expected.provider_scope)
        .bind(expected.preparation_digest.as_str())
        .bind(expected.provider_profile_digest.as_str())
        .bind(expected.definition_digest.as_str())
        .bind(to_i64(expected.prepared_generation)?)
        .bind(to_i64(expected.prepared_at_ms)?)
        .bind(to_i64(expected.lease_deadline_ms)?)
        .execute(self.taskflow_pool())
        .await;
        match inserted {
            Ok(_) => Ok(expected.clone()),
            Err(error) if is_constraint(&error) => {
                let existing = self
                    .product_effect_preparation_by_attempt(
                        &expected.intent.run_id,
                        &expected.intent.step_id,
                        expected.intent.attempt,
                    )
                    .await?
                    .ok_or_else(|| {
                        TaskFlowError::Conflict(
                            "product effect preparation identity raced".to_string(),
                        )
                    })?;
                ensure_request_matches_existing(request, &existing)?;
                Ok(existing)
            }
            Err(_) => Err(TaskFlowError::Unavailable),
        }
    }

    pub async fn product_effect_preparation_by_operation(
        &self,
        operation_id: &str,
    ) -> Result<Option<ProductEffectPreparationV1>, TaskFlowError> {
        let row = sqlx::query(
            "SELECT * FROM automation_product_effect_preparations
             WHERE owner_agent_id = ? AND operation_id = ? ORDER BY attempt DESC LIMIT 1",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(operation_id)
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        row.map(preparation_from_row).transpose()
    }

    pub async fn product_effect_preparation_by_attempt(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
    ) -> Result<Option<ProductEffectPreparationV1>, TaskFlowError> {
        let row = sqlx::query(
            "SELECT * FROM automation_product_effect_preparations
             WHERE owner_agent_id = ? AND run_id = ? AND step_id = ? AND attempt = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(step_id)
        .bind(i64::from(attempt))
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        row.map(preparation_from_row).transpose()
    }

    pub(super) fn validate_product_effect_fence(
        &self,
        fence: &TaskFlowFence,
        policy_generation: u64,
    ) -> Result<(), TaskFlowError> {
        if fence.owner_agent_id != *self.taskflow_owner_agent_id()
            || fence.owner_epoch != policy_generation
        {
            return Err(TaskFlowError::StaleFence);
        }
        Ok(())
    }
}

fn preparation_from_row(
    row: sqlx::sqlite::SqliteRow,
) -> Result<ProductEffectPreparationV1, TaskFlowError> {
    let intent_json: String = row
        .try_get("intent_json")
        .map_err(|_| corrupt("product effect intent json"))?;
    let intent: AuthorizedEffectIntent =
        serde_json::from_str(&intent_json).map_err(|_| corrupt("product effect intent json"))?;
    let intent_digest = parse_digest(&row, "intent_digest")?;
    if intent.digest()? != intent_digest {
        return Err(corrupt("product effect intent digest"));
    }
    let payload_digest = parse_digest(&row, "payload_digest")?;
    if intent.payload_digest != payload_digest {
        return Err(corrupt("product effect payload digest"));
    }
    let run_id: String = row
        .try_get("run_id")
        .map_err(|_| corrupt("product effect run id"))?;
    let step_id: String = row
        .try_get("step_id")
        .map_err(|_| corrupt("product effect step id"))?;
    let attempt = u32::try_from(
        row.try_get::<i64, _>("attempt")
            .map_err(|_| corrupt("product effect attempt"))?,
    )
    .map_err(|_| corrupt("product effect attempt"))?;
    if intent.run_id != run_id || intent.step_id != step_id || intent.attempt != attempt {
        return Err(corrupt("product effect attempt identity"));
    }
    let prepared = ProductEffectPreparationV1 {
        intent,
        intent_digest,
        provider_key: row
            .try_get("provider_key")
            .map_err(|_| corrupt("product effect provider key"))?,
        provider_scope: row
            .try_get("provider_scope")
            .map_err(|_| corrupt("provider scope"))?,
        preparation_digest: parse_digest(&row, "preparation_digest")?,
        provider_profile_digest: parse_digest(&row, "provider_profile_digest")?,
        definition_digest: parse_digest(&row, "definition_digest")?,
        lease_deadline_ms: to_u64(
            row.try_get("lease_deadline_ms")
                .map_err(|_| corrupt("preparation deadline"))?,
        )?,
        prepared_generation: to_u64(
            row.try_get("prepared_generation")
                .map_err(|_| corrupt("product effect generation"))?,
        )?,
        prepared_at_ms: to_u64(
            row.try_get("prepared_at_ms")
                .map_err(|_| corrupt("product effect timestamp"))?,
        )?,
    };
    let operation_id: String = row
        .try_get("operation_id")
        .map_err(|_| corrupt("operation id"))?;
    let expected_key = ProviderEffectKey::for_operation(
        &prepared.provider_scope,
        &prepared.intent.run_id,
        &prepared.intent.step_id,
    )
    .map_err(|_| corrupt("provider key"))?;
    if prepared.intent.operation_id != operation_id
        || prepared.lease_deadline_ms <= prepared.prepared_at_ms
        || prepared.preparation_digest != preparation_digest(&prepared)?
        || prepared.provider_key != expected_key.as_str()
        || prepared.definition_digest != *product_effect_definition()?.definition_digest()
    {
        return Err(corrupt("complete product preparation binding"));
    }
    Ok(prepared)
}

impl AutomationStore {
    pub(super) async fn product_effect_is_ready(
        &self,
        prepared: &ProductEffectPreparationV1,
    ) -> Result<bool, TaskFlowError> {
        let recorded: Option<String> = sqlx::query_scalar("SELECT preparation_digest FROM automation_product_effect_ready WHERE owner_agent_id = ? AND operation_id = ? AND attempt = ?")
            .bind(self.owner_agent_id().as_str()).bind(&prepared.intent.operation_id)
            .bind(i64::from(prepared.intent.attempt)).fetch_optional(self.taskflow_pool()).await.map_err(|_| TaskFlowError::Unavailable)?;
        match recorded {
            None => Ok(false),
            Some(digest) if digest == prepared.preparation_digest.as_str() => Ok(true),
            Some(_) => Err(corrupt("product readiness binding")),
        }
    }
    pub(super) async fn mark_product_effect_ready(
        &self,
        prepared: &ProductEffectPreparationV1,
    ) -> Result<(), TaskFlowError> {
        sqlx::query("INSERT INTO automation_product_effect_ready VALUES (?, ?, ?, ?) ON CONFLICT(owner_agent_id, operation_id, attempt) DO NOTHING")
            .bind(self.owner_agent_id().as_str()).bind(&prepared.intent.operation_id).bind(i64::from(prepared.intent.attempt)).bind(prepared.preparation_digest.as_str())
            .execute(self.taskflow_pool()).await.map_err(|_| TaskFlowError::Unavailable)?;
        if !self.product_effect_is_ready(prepared).await? {
            return Err(corrupt("missing product readiness"));
        }
        Ok(())
    }
}
