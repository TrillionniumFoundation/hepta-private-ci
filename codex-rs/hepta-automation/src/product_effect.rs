//! Product preparation for the existing final-use-authorized TaskFlow effect path.
//!
//! Preparation freezes one logical operation into the existing TaskFlow
//! definition/run/step owners before a grant can be consumed. It neither mints
//! authority nor contacts a provider. Replays return the exact durable intent;
//! changed payload, destination, scope, predecessor, or compensation conflict.

use crate::AsyncAuthorizedEffectDriver;
use crate::AuthorizedEffectError;
use crate::TaskFlowStepReceipt;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;

use crate::AuthorizedEffectIntent;
use crate::AutomationStore;
use crate::TaskFlowCommand;
use crate::TaskFlowDefinition;
use crate::TaskFlowEdgeSpec;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowNodeKind;
use crate::TaskFlowNodeSpec;
use crate::TaskFlowRunState;
use crate::TaskFlowTransition;

const PRODUCT_EFFECT_WORKFLOW_ID: &str = "agentd.product-effect.v1";
const PRODUCT_EFFECT_STEP_ID: &str = "effect";
const PRODUCT_EFFECT_CAPABILITY: &str = "provider.deliver";
const MAX_PRODUCT_EFFECT_ATTEMPTS: u32 = 32;
const MAX_PROVIDER_SCOPE_BYTES: usize = 128;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductEffectPreparationRequestV1 {
    pub operation_id: String,
    pub subject_id: String,
    pub destination_id: String,
    pub payload_digest: Sha256Digest,
    pub final_use_scope_digest: Sha256Digest,
    pub policy_generation: u64,
    pub expected_predecessor_digest: Option<Sha256Digest>,
    pub compensation_for: Option<String>,
    pub provider_scope: String,
    pub provider_profile_digest: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductEffectPreparationV1 {
    pub intent: AuthorizedEffectIntent,
    pub intent_digest: Sha256Digest,
    pub provider_key: String,
    pub provider_scope: String,
    pub preparation_digest: Sha256Digest,
    pub provider_profile_digest: Sha256Digest,
    pub definition_digest: Sha256Digest,
    pub prepared_generation: u64,
    pub prepared_at_ms: u64,
    pub lease_deadline_ms: u64,
}

impl AutomationStore {
    pub async fn prepare_product_effect_v1(
        &self,
        request: &ProductEffectPreparationRequestV1,
        fence: &TaskFlowFence,
        now_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<ProductEffectPreparationV1, TaskFlowError> {
        validate_request(request)?;
        self.validate_taskflow_fence(fence)?;
        self.validate_product_effect_fence(fence, request.policy_generation)?;
        let mut horizon = now_ms
            .checked_add(lease_duration_ms)
            .ok_or_else(|| TaskFlowError::Invalid("product effect horizon overflow".to_string()))?;
        to_i64(horizon)?;
        if lease_duration_ms < 4 {
            return Err(TaskFlowError::Invalid(
                "product effect lease must cover durable preparation".to_string(),
            ));
        }
        let previous = self
            .product_effect_preparation_by_operation(&request.operation_id)
            .await?;
        let mut attempt = 1;
        let mut claim_before_reservation = false;
        let mut resume = None;
        if let Some(previous) = previous {
            ensure_request_matches_existing(request, &previous)?;
            let run = self.taskflow_run(&previous.intent.run_id).await?;
            let contact = self
                .effect_dispatch_attempt(
                    &previous.intent.run_id,
                    &previous.intent.step_id,
                    previous.intent.attempt,
                )
                .await?;
            let proven_absent = contact.as_ref().is_some_and(|contact| {
                matches!(
                    contact.observation.as_ref().map(|o| o.kind),
                    Some(
                        crate::effect_dispatch_ledger::EffectDispatchObservationKind::ProvenAbsent
                    )
                )
            });
            if let Some(run) = &run
                && let Some(expiry) = run.lease_expires_at_ms.filter(|expiry| *expiry > now_ms)
            {
                horizon = horizon.min(expiry);
            }
            if let Some(contact) = contact {
                // Unknown, in-flight and terminal effects retain their exact
                // historical result. Only a durable no-contact observation may retry.
                if !matches!(
                    contact.observation.as_ref().map(|o| o.kind),
                    Some(
                        crate::effect_dispatch_ledger::EffectDispatchObservationKind::ProvenAbsent
                    )
                ) {
                    return Ok(previous);
                }
            } else if let Some(run) = run.as_ref()
                && (matches!(
                    run.state,
                    TaskFlowRunState::Succeeded
                        | TaskFlowRunState::Failed
                        | TaskFlowRunState::Cancelled
                ) || (run
                    .lease_expires_at_ms
                    .is_some_and(|expires| expires > now_ms)
                    && self.product_effect_is_ready(&previous).await?))
            {
                return Ok(previous);
            }
            if !proven_absent
                && previous.prepared_generation == fence.generation
                && previous.lease_deadline_ms > now_ms
            {
                attempt = previous.intent.attempt;
                resume = Some(previous);
            } else {
                if request.provider_profile_digest != previous.provider_profile_digest
                    || request.provider_scope != previous.provider_scope
                {
                    return Err(TaskFlowError::Conflict(
                        "original provider profile is required for a new uncontacted attempt"
                            .to_string(),
                    ));
                }
                attempt = previous
                    .intent
                    .attempt
                    .checked_add(1)
                    .filter(|a| *a <= MAX_PRODUCT_EFFECT_ATTEMPTS)
                    .ok_or_else(|| {
                        TaskFlowError::Conflict(
                            "product effect attempt budget exhausted".to_string(),
                        )
                    })?;
                if run.is_some() {
                    // The native run claim and the provider-entry INSERT share
                    // SQLite's writer ordering. An old attempt cannot enter
                    // after this generation has taken over.
                    self.claim_taskflow_run(
                        &previous.intent.run_id,
                        fence,
                        now_ms,
                        lease_duration_ms,
                    )
                    .await?;
                    claim_before_reservation = true;
                }
            }
        }
        let run_id = product_effect_run_id(self.taskflow_owner_agent_id().as_str(), request);
        let provider_key = ProviderEffectKey::for_operation(
            &request.provider_scope,
            &run_id,
            PRODUCT_EFFECT_STEP_ID,
        )
        .map_err(|_| TaskFlowError::Invalid("product effect provider scope".to_string()))?;
        let intent = AuthorizedEffectIntent {
            run_id: run_id.clone(),
            step_id: PRODUCT_EFFECT_STEP_ID.to_string(),
            attempt,
            operation_id: request.operation_id.clone(),
            subject_id: request.subject_id.clone(),
            destination_id: request.destination_id.clone(),
            payload_digest: request.payload_digest.clone(),
            final_use_scope_digest: request.final_use_scope_digest.clone(),
            policy_generation: request.policy_generation,
            expected_predecessor_digest: request.expected_predecessor_digest.clone(),
            dependencies: Vec::new(),
            compensation_for: request.compensation_for.clone(),
        };
        let intent_digest = intent.digest()?;
        let definition = product_effect_definition()?;
        let mut proposed = ProductEffectPreparationV1 {
            intent,
            intent_digest,
            provider_key: provider_key.as_str().to_string(),
            provider_scope: request.provider_scope.clone(),
            preparation_digest: Sha256Digest::for_bytes(b"uncomputed-preparation"),
            provider_profile_digest: request.provider_profile_digest.clone(),
            definition_digest: definition.definition_digest().clone(),
            prepared_generation: fence.generation,
            prepared_at_ms: now_ms,
            lease_deadline_ms: horizon,
        };

        proposed.preparation_digest = preparation_digest(&proposed)?;
        let expected = match resume {
            Some(original) => original,
            None => {
                self.insert_product_effect_preparation(request, &proposed)
                    .await?
            }
        };
        if self.product_effect_is_ready(&expected).await? {
            return Ok(expected);
        }
        if expected.prepared_generation != fence.generation {
            return Err(TaskFlowError::StaleFence);
        }

        self.register_taskflow_definition(&definition, fence, now_ms)
            .await?;
        let run = self
            .create_taskflow_run(
                &run_id,
                &definition.workflow_id,
                definition.version,
                definition.definition_digest(),
                &run_id,
                now_ms,
            )
            .await?;
        let base_time = expected.prepared_at_ms;
        let claimed = if claim_before_reservation {
            run
        } else {
            self.claim_taskflow_run(&run_id, fence, now_ms, lease_duration_ms)
                .await?
        };
        if claimed.state == TaskFlowRunState::Queued {
            self.apply_taskflow_command(&TaskFlowCommand::new(
                &run_id,
                product_command_id("start", &expected.intent_digest),
                fence.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                add_time(base_time, 1)?,
            )?)
            .await?;
        }
        self.prepare_taskflow_step(
            &run_id,
            PRODUCT_EFFECT_STEP_ID,
            expected.intent.attempt,
            fence,
            &expected.intent_digest,
            &request.payload_digest,
            &product_command_id("prepare", &expected.intent_digest),
            add_time(base_time, 2)?,
        )
        .await?;
        self.claim_taskflow_step(
            &run_id,
            PRODUCT_EFFECT_STEP_ID,
            expected.intent.attempt,
            fence,
            &expected.intent_digest,
            &request.payload_digest,
            &product_command_id("claim", &expected.intent_digest),
            add_time(base_time, 3)?,
        )
        .await?;

        self.mark_product_effect_ready(&expected).await?;
        Ok(expected)
    }
}

impl AutomationStore {
    /// Dispatch one exact durable product preparation through the async
    /// final-use/provider boundary. The provider key comes only from the
    /// immutable preparation; callers cannot replace it after a restart or
    /// local retry.
    pub async fn execute_prepared_product_effect_async<D: AsyncAuthorizedEffectDriver>(
        &self,
        driver: &mut D,
        preparation: &ProductEffectPreparationV1,
        dispatch: crate::AuthorizedEffectDispatch<'_>,
    ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {
        let wire_payload = dispatch.wire_payload;
        if dispatch.intent != &preparation.intent {
            return Err(AuthorizedEffectError::BindingMismatch);
        }
        let durable = self
            .product_effect_preparation_by_attempt(
                &preparation.intent.run_id,
                &preparation.intent.step_id,
                preparation.intent.attempt,
            )
            .await?
            .ok_or(AuthorizedEffectError::BindingMismatch)?;
        if durable != *preparation
            || !self.product_effect_is_ready(&durable).await?
            || dispatch.signed_grant.grant.expires_at_unix_ms > durable.lease_deadline_ms
        {
            return Err(AuthorizedEffectError::BindingMismatch);
        }
        if Sha256Digest::for_bytes(wire_payload) != preparation.intent.payload_digest
            || preparation.intent.digest()? != preparation.intent_digest
        {
            return Err(AuthorizedEffectError::BindingMismatch);
        }
        let provider_key = ProviderEffectKey::parse(preparation.provider_key.clone())
            .map_err(|_| AuthorizedEffectError::BindingMismatch)?;
        let provider_intent =
            ProviderEffectIntent::new(provider_key, preparation.intent.payload_digest.clone());
        self.execute_authorized_taskflow_effect_async_with_provider_intent(
            driver,
            dispatch,
            provider_intent,
        )
        .await
    }
}

pub(super) fn product_effect_definition() -> Result<TaskFlowDefinition, TaskFlowError> {
    let mut effect = TaskFlowNodeSpec::effect(
        PRODUCT_EFFECT_STEP_ID,
        PRODUCT_EFFECT_CAPABILITY,
        "provider-effect-key-v1",
    );
    effect.max_attempts = MAX_PRODUCT_EFFECT_ATTEMPTS;
    TaskFlowDefinition::new(
        PRODUCT_EFFECT_WORKFLOW_ID,
        1,
        PRODUCT_EFFECT_STEP_ID,
        vec![
            effect,
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new(PRODUCT_EFFECT_STEP_ID, "success"),
            TaskFlowEdgeSpec::new(PRODUCT_EFFECT_STEP_ID, "failure"),
        ],
        vec![PRODUCT_EFFECT_CAPABILITY.to_string()],
        Sha256Digest::for_bytes(b"hepta.automation.product-effect.policy.v1"),
    )
}

fn product_effect_run_id(owner: &str, request: &ProductEffectPreparationRequestV1) -> String {
    let mut bytes = b"hepta.automation.product-effect.run.v1\0".to_vec();
    push_text(&mut bytes, owner);
    push_text(&mut bytes, &request.operation_id);
    format!(
        "product-effect:{}",
        Sha256Digest::for_bytes(&bytes).as_str()
    )
}

fn product_command_id(phase: &str, intent_digest: &Sha256Digest) -> String {
    format!("product-effect:{phase}:{}", intent_digest.as_str())
}

fn validate_request(request: &ProductEffectPreparationRequestV1) -> Result<(), TaskFlowError> {
    if request.provider_scope.is_empty()
        || request.provider_scope.len() > MAX_PROVIDER_SCOPE_BYTES
        || request.provider_scope.chars().any(char::is_control)
    {
        return Err(TaskFlowError::Invalid(
            "product effect provider scope is invalid".to_string(),
        ));
    }
    if request.policy_generation == 0 || is_zero_digest(&request.provider_profile_digest) {
        return Err(TaskFlowError::Invalid(
            "product effect profile/generation is invalid".to_string(),
        ));
    }
    Ok(())
}

pub(super) fn ensure_request_matches_existing(
    request: &ProductEffectPreparationRequestV1,
    existing: &ProductEffectPreparationV1,
) -> Result<(), TaskFlowError> {
    if existing.intent.operation_id != request.operation_id
        || existing.intent.subject_id != request.subject_id
        || existing.intent.destination_id != request.destination_id
        || existing.intent.payload_digest != request.payload_digest
        || existing.intent.final_use_scope_digest != request.final_use_scope_digest
        || existing.intent.expected_predecessor_digest != request.expected_predecessor_digest
        || existing.intent.compensation_for != request.compensation_for
    {
        return Err(TaskFlowError::Conflict(
            "product effect operation is bound to different semantics".to_string(),
        ));
    }
    Ok(())
}

pub(super) fn parse_digest(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<Sha256Digest, TaskFlowError> {
    Sha256Digest::parse(
        row.try_get::<String, _>(column)
            .map_err(|_| corrupt(column))?,
    )
    .map_err(|_| corrupt(column))
}

fn is_zero_digest(value: &Sha256Digest) -> bool {
    value.as_str().bytes().all(|byte| byte == b'0')
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn add_time(value: u64, delta: u64) -> Result<u64, TaskFlowError> {
    value
        .checked_add(delta)
        .ok_or_else(|| TaskFlowError::Invalid("product effect timestamp overflow".to_string()))
}

pub(super) fn to_i64(value: u64) -> Result<i64, TaskFlowError> {
    i64::try_from(value)
        .map_err(|_| TaskFlowError::Invalid("product effect integer overflow".to_string()))
}

pub(super) fn to_u64(value: i64) -> Result<u64, TaskFlowError> {
    u64::try_from(value).map_err(|_| corrupt("product effect negative integer"))
}

pub(super) fn corrupt(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Corrupt(message.into())
}

pub(super) fn is_constraint(error: &sqlx::Error) -> bool {
    matches!(error, sqlx::Error::Database(database) if database.is_unique_violation() || database.is_foreign_key_violation() || database.is_check_violation())
}

pub(super) fn preparation_digest(
    prepared: &ProductEffectPreparationV1,
) -> Result<Sha256Digest, TaskFlowError> {
    let bytes = serde_json::to_vec(&(
        "hepta.automation.product-preparation.v1",
        &prepared.intent,
        &prepared.intent_digest,
        &prepared.provider_key,
        &prepared.provider_scope,
        &prepared.provider_profile_digest,
        &prepared.definition_digest,
        prepared.prepared_generation,
        prepared.prepared_at_ms,
        prepared.lease_deadline_ms,
    ))
    .map_err(|_| corrupt("product preparation encoding"))?;
    Ok(Sha256Digest::for_bytes(&bytes))
}
