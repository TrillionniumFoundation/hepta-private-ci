//! Host-owned composition for final-use-authorized automation effects.
//!
//! The TaskFlow owner persists intent/attempt/reconciliation state. Agentd owns
//! the selected provider contract and final-use verifier. Control callers can
//! transport a signed grant and exact provider bytes, but they cannot select a
//! provider endpoint, destination, final-use scope, subject, or TaskFlow fence.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_automation::AsyncAuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectDriverError;
use codex_hepta_automation::AuthorizedEffectFuture;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AuthorizedProviderEffectRequest;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::ProductEffectPreparationRequestV1;
use codex_hepta_automation::ProductEffectPreparationV1;
use codex_hepta_automation::ProviderEffectTaskFlowDriver;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowStepReceipt;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_model_provider::HttpProviderEffectAdapter;
use codex_model_provider::HttpProviderEffectConfig;
use codex_model_provider::HttpProviderEffectContractAttestation;
use http::HeaderMap;
use http::HeaderName;
use http::HeaderValue;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIdentity;

#[path = "automation_effect_host_config.rs"]
mod config;
use config::*;

const AUTOMATION_EFFECT_HOST_SCHEMA_VERSION: u32 = 2;
const LEGACY_AUTOMATION_EFFECT_HOST_SCHEMA_VERSION: u32 = 1;
const MAX_PROVIDER_RECOVERY_PROFILES: usize = 16;
const MAX_AUTOMATION_EFFECT_HOST_FILE_BYTES: u64 = 64 * 1024;
const MAX_AUTOMATION_EFFECT_REVOCATIONS_FILE_BYTES: u64 = 4 * 1024 * 1024;
const MAX_PROVIDER_HEADERS: usize = 64;
const AUTOMATION_EFFECT_PREPARATION_LEASE_MS: u64 = 60_000;

#[derive(Clone, Debug)]
pub(crate) enum AgentdAutomationEffectReconcileOutcome {
    Observed(Box<TaskFlowStepReceipt>),
    Indeterminate,
    ProvenAbsent,
}

#[derive(Clone)]
pub(crate) struct AgentdAutomationEffectHost {
    agent_id: codex_hepta_contracts::AgentId,
    provider_scope: String,
    provider_profile_digest: Sha256Digest,
    destination_id: String,
    final_use_scope_digest: Sha256Digest,
    authority: FinalUseAuthority,
    revocations_file: PathBuf,
    revocation_frontier: Arc<Mutex<(u64, u64, Sha256Digest)>>,
    adapter: HttpProviderEffectAdapter,
    recovery_profiles: BTreeMap<String, AutomationEffectRecoveryProfile>,
    spawn_generation: u64,
}

impl std::fmt::Debug for AgentdAutomationEffectHost {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("AgentdAutomationEffectHost")
            .field("agent_id", &self.agent_id)
            .field("provider_scope", &self.provider_scope)
            .field("provider_profile_digest", &self.provider_profile_digest)
            .field("destination_id", &self.destination_id)
            .field("final_use_scope_digest", &self.final_use_scope_digest)
            .field("adapter", &self.adapter)
            .finish_non_exhaustive()
    }
}

impl AgentdAutomationEffectHost {
    pub(crate) fn open(identity: &AgentdIdentity, path: &Path) -> Result<Self, AgentdError> {
        let config = read_host_file(path)?;
        match config.schema_version {
            LEGACY_AUTOMATION_EFFECT_HOST_SCHEMA_VERSION if config.recovery_profiles.is_empty() => {
            }
            LEGACY_AUTOMATION_EFFECT_HOST_SCHEMA_VERSION => {
                return Err(AgentdError::Invalid(
                    "automation effect host schema v1 cannot carry recovery profiles".to_string(),
                ));
            }
            AUTOMATION_EFFECT_HOST_SCHEMA_VERSION
                if config.recovery_profiles.len() <= MAX_PROVIDER_RECOVERY_PROFILES => {}
            AUTOMATION_EFFECT_HOST_SCHEMA_VERSION => {
                return Err(AgentdError::Invalid(
                    "automation effect recovery profile bound exceeded".to_string(),
                ));
            }
            _ => {
                return Err(AgentdError::Invalid(
                    "unsupported automation effect host schema".to_string(),
                ));
            }
        }

        let active_profile = open_provider_profile(config.active_profile())?;
        let mut recovery_profiles = BTreeMap::new();
        for recovery in &config.recovery_profiles {
            let opened = open_provider_profile(recovery.view())?;
            if opened.profile_digest == active_profile.profile_digest {
                return Err(AgentdError::Invalid(
                    "active provider profile cannot be repeated as a recovery profile".to_string(),
                ));
            }
            let digest = opened.profile_digest.as_str().to_string();
            let previous = recovery_profiles.insert(
                digest,
                AutomationEffectRecoveryProfile {
                    destination_id: opened.destination_id,
                    final_use_scope_digest: opened.final_use_scope_digest,
                    adapter: opened.adapter,
                },
            );
            if previous.is_some() {
                return Err(AgentdError::Invalid(
                    "automation effect recovery profile digest is duplicated".to_string(),
                ));
            }
        }

        let final_use_verifying_key = decode_hex_array::<32>(
            &config.final_use_verifying_key_hex,
            "final_use_verifying_key_hex",
        )?;
        if !config.final_use_revocations_file.is_absolute() {
            return Err(AgentdError::Invalid(
                "final_use_revocations_file must be absolute".to_string(),
            ));
        }
        let initial_revocations = read_revocations_file(&config.final_use_revocations_file)?;
        let frontier = (
            initial_revocations.authority_epoch,
            initial_revocations.revision,
            revocations_digest(&initial_revocations)?,
        );

        let authority_root = identity
            .layout
            .automation_root()
            .join("final-use-authority");
        fs::create_dir_all(&authority_root)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&authority_root, fs::Permissions::from_mode(0o700))?;
        }
        let authority = FinalUseAuthority::open_state_dir(
            &authority_root,
            config.final_use_signer_id,
            final_use_verifying_key,
            initial_revocations,
        )
        .map_err(|error| {
            AgentdError::Protocol(format!(
                "open automation final-use authority state: {error}"
            ))
        })?;

        Ok(Self {
            agent_id: identity.agent_id.clone(),
            provider_scope: active_profile.provider_scope,
            provider_profile_digest: active_profile.profile_digest,
            destination_id: active_profile.destination_id,
            final_use_scope_digest: active_profile.final_use_scope_digest,
            authority,
            revocations_file: config.final_use_revocations_file,
            revocation_frontier: Arc::new(Mutex::new(frontier)),
            adapter: active_profile.adapter,
            recovery_profiles,
            spawn_generation: identity.spawn_generation,
        })
    }

    pub(crate) async fn prepare(
        &self,
        store: &AutomationStore,
        operation_id: String,
        wire_payload: &[u8],
        expected_predecessor_digest: Option<Sha256Digest>,
        compensation_for: Option<String>,
        now_ms: u64,
    ) -> Result<ProductEffectPreparationV1, AgentdError> {
        self.validate_wire_payload(wire_payload)?;
        self.refresh_revocations()?;
        let mut run_generation = self.spawn_generation;
        if let Some(previous) = store
            .product_effect_preparation_by_operation(&operation_id)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("read preparation generation: {error}"))
            })?
        {
            if let Some(run) =
                store
                    .taskflow_run(&previous.intent.run_id)
                    .await
                    .map_err(|error| {
                        AgentdError::Protocol(format!("read preparation owner: {error}"))
                    })?
            {
                let generation = run.generation.unwrap_or(previous.prepared_generation);
                run_generation = if run.owner_epoch == Some(self.spawn_generation)
                    && run
                        .lease_expires_at_ms
                        .is_some_and(|expiry| expiry > now_ms)
                {
                    generation
                } else {
                    generation.checked_add(1).ok_or_else(|| {
                        AgentdError::Invalid("TaskFlow generation exhausted".to_string())
                    })?
                };
            } else if previous.lease_deadline_ms <= now_ms
                || previous.prepared_generation < self.spawn_generation
            {
                run_generation = previous.prepared_generation.checked_add(1).ok_or_else(|| {
                    AgentdError::Invalid("TaskFlow generation exhausted".to_string())
                })?;
            }
        }
        let fence = TaskFlowFence::new(
            self.agent_id.clone(),
            "agentd.automation-effect",
            self.spawn_generation,
            run_generation,
            product_effect_fencing_token(
                &self.agent_id,
                self.spawn_generation,
                &self.provider_profile_digest,
            ),
        )
        .map_err(|error| AgentdError::Protocol(format!("product effect fence: {error}")))?;
        let request = ProductEffectPreparationRequestV1 {
            operation_id,
            subject_id: self.agent_id.as_str().to_string(),
            destination_id: self.destination_id.clone(),
            payload_digest: Sha256Digest::for_bytes(wire_payload),
            final_use_scope_digest: self.final_use_scope_digest.clone(),
            policy_generation: self.spawn_generation,
            expected_predecessor_digest,
            compensation_for,
            provider_scope: self.provider_scope.clone(),
            provider_profile_digest: self.provider_profile_digest.clone(),
        };
        store
            .prepare_product_effect_v1(
                &request,
                &fence,
                now_ms,
                AUTOMATION_EFFECT_PREPARATION_LEASE_MS,
            )
            .await
            .map_err(|error| AgentdError::Protocol(format!("prepare product effect: {error}")))
    }

    pub(crate) async fn execute(
        &self,
        store: &AutomationStore,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
        signed_grant: &SignedFinalUseGrant,
        command_id: &str,
        now_ms: u64,
    ) -> Result<TaskFlowStepReceipt, AgentdError> {
        self.validate_intent(intent, wire_payload)?;
        self.refresh_revocations()?;
        if let Some(receipt) = store
            .read_authorized_taskflow_effect_receipt(intent, command_id)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("read terminal effect receipt: {error}"))
            })?
        {
            return Ok(receipt);
        }
        let preparation = store
            .product_effect_preparation_by_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("read product effect preparation: {error}"))
            })?
            .ok_or_else(|| {
                AgentdError::Invalid(
                    "effect dispatch requires a durable product preparation".to_string(),
                )
            })?;
        if preparation.intent != *intent
            || preparation.provider_profile_digest != self.provider_profile_digest
        {
            return Err(AgentdError::GenerationFenced(
                "effect preparation does not match the active provider profile".to_string(),
            ));
        }
        let run = store
            .taskflow_run(&intent.run_id)
            .await
            .map_err(|error| AgentdError::Protocol(format!("read effect TaskFlow run: {error}")))?
            .ok_or_else(|| {
                AgentdError::Invalid("effect TaskFlow run does not exist".to_string())
            })?;
        let fence = self.current_fence(&run, now_ms)?;
        if signed_grant.grant.expires_at_unix_ms > preparation.lease_deadline_ms
            || run
                .lease_expires_at_ms
                .is_none_or(|expiry| signed_grant.grant.expires_at_unix_ms > expiry)
        {
            return Err(AgentdError::Invalid(
                "final-use grant outlives the prepared owner lease".to_string(),
            ));
        }
        let binding = intent
            .final_use_binding()
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        let mut driver = CurrentRevocationEffectDriver {
            host: self.clone(),
            inner: ProviderEffectTaskFlowDriver::new(
                self.destination_id.clone(),
                self.adapter.clone(),
            )
            .map_err(|error| AgentdError::Protocol(format!("provider driver: {error}")))?,
        };
        store
            .execute_prepared_product_effect_async(
                &mut driver,
                &preparation,
                codex_hepta_automation::AuthorizedEffectDispatch {
                    authority: &self.authority,
                    intent,
                    wire_payload,
                    fence: &fence,
                    signed_grant,
                    expected_binding: &binding,
                    command_id,
                    now_ms,
                },
            )
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("automation authorized effect dispatch: {error}"))
            })
    }

    pub(crate) async fn reconcile(
        &self,
        store: &AutomationStore,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        now_ms: u64,
    ) -> Result<AgentdAutomationEffectReconcileOutcome, AgentdError> {
        let pending = store
            .authorized_taskflow_effect_attempt(run_id, step_id, attempt)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("read pending authorized effect: {error}"))
            })?
            .ok_or_else(|| {
                AgentdError::Invalid("authorized effect is not pending reconciliation".to_string())
            })?;
        let run = store
            .taskflow_run(run_id)
            .await
            .map_err(|error| AgentdError::Protocol(format!("read effect TaskFlow run: {error}")))?
            .ok_or_else(|| {
                AgentdError::Invalid("effect TaskFlow run does not exist".to_string())
            })?;
        if run.owner_agent_id != self.agent_id {
            return Err(AgentdError::GenerationFenced(
                "TaskFlow run is owned by a different Agent".to_string(),
            ));
        }
        if let Some(receipt) = store
            .read_prepared_product_effect_receipt(run_id, step_id, attempt)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("read settled product effect: {error}"))
            })?
        {
            return Ok(AgentdAutomationEffectReconcileOutcome::Observed(Box::new(
                receipt,
            )));
        }
        let fence = self.historical_fence(&run)?;
        if let Some(local) = store
            .settle_authorized_taskflow_effect_observation(run_id, step_id, attempt, &fence)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!(
                    "settle durable authorized effect observation: {error}"
                ))
            })?
        {
            match local {
                AuthorizedEffectRecoveryResult::Observed(receipt)
                    if receipt.final_outcome.is_some()
                        || receipt.observation != Some(TaskFlowStepObservation::Indeterminate) =>
                {
                    return Ok(AgentdAutomationEffectReconcileOutcome::Observed(receipt));
                }
                AuthorizedEffectRecoveryResult::ProvenAbsent => {
                    return Ok(AgentdAutomationEffectReconcileOutcome::ProvenAbsent);
                }
                AuthorizedEffectRecoveryResult::Observed(_) => {}
            }
        }
        // Only local, immutable evidence may be settled without an original
        // provider binding. Legacy unknown attempts need an explicit migration
        // proof; never guess their old provider from the current configuration.
        let preparation = store
            .product_effect_preparation_by_attempt(run_id, step_id, attempt)
            .await
            .map_err(|error| AgentdError::Protocol(format!("read recovery profile: {error}")))?
            .ok_or_else(|| {
                AgentdError::Protocol(
                    "legacy effect lacks a frozen provider profile; explicit migration required"
                        .to_string(),
                )
            })?;
        if preparation.intent.payload_digest != pending.payload_digest
            || preparation.intent.destination_id != pending.destination_id
            || preparation.intent_digest != pending.intent_digest
            || pending.provider_key.as_ref().map(ProviderEffectKey::as_str)
                != Some(preparation.provider_key.as_str())
        {
            return Err(AgentdError::GenerationFenced(
                "pending effect differs from its frozen preparation".to_string(),
            ));
        }
        let adapter = self.recovery_adapter(&preparation)?;
        let key = ProviderEffectKey::parse(preparation.provider_key.clone())
            .map_err(|error| AgentdError::Invalid(format!("stored provider key: {error:?}")))?;
        let provider_intent = ProviderEffectIntent::new(key, pending.payload_digest.clone());
        match adapter.lookup_for_intent(&provider_intent).await {
            ProviderEffectLookup::Ack(ack) => {
                let Some(receipt) = terminal_receipt_from_ack(&ack) else {
                    return Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate);
                };
                match store
                    .recover_authorized_taskflow_effect(
                        run_id,
                        step_id,
                        attempt,
                        &fence,
                        AuthorizedEffectRecovery::Observed(receipt),
                        now_ms,
                    )
                    .await
                    .map_err(|error| {
                        AgentdError::Protocol(format!(
                            "reconcile authorized effect terminal observation: {error}"
                        ))
                    })? {
                    AuthorizedEffectRecoveryResult::Observed(receipt) => {
                        Ok(AgentdAutomationEffectReconcileOutcome::Observed(receipt))
                    }
                    AuthorizedEffectRecoveryResult::ProvenAbsent => Err(AgentdError::Protocol(
                        "status lookup cannot manufacture provider absence".to_string(),
                    )),
                }
            }
            ProviderEffectLookup::Conflict { .. } => Err(AgentdError::Protocol(
                "provider reports a same-key payload conflict".to_string(),
            )),
            ProviderEffectLookup::NotFound | ProviderEffectLookup::Unknown => {
                Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate)
            }
        }
    }

    fn recovery_adapter(
        &self,
        prepared: &ProductEffectPreparationV1,
    ) -> Result<&HttpProviderEffectAdapter, AgentdError> {
        if prepared.intent.subject_id != self.agent_id.as_str() {
            return Err(AgentdError::GenerationFenced(
                "effect recovery subject differs from owner".to_string(),
            ));
        }
        if prepared.provider_profile_digest == self.provider_profile_digest {
            if prepared.intent.destination_id == self.destination_id
                && prepared.intent.final_use_scope_digest == self.final_use_scope_digest
            {
                return Ok(&self.adapter);
            }
        } else if let Some(profile) = self
            .recovery_profiles
            .get(prepared.provider_profile_digest.as_str())
            && prepared.intent.destination_id == profile.destination_id
            && prepared.intent.final_use_scope_digest == profile.final_use_scope_digest
        {
            return Ok(&profile.adapter);
        }
        Err(AgentdError::GenerationFenced(
            "original provider profile is unavailable for reconciliation".to_string(),
        ))
    }

    fn refresh_revocations(&self) -> Result<(), AgentdError> {
        let head = read_revocations_file(&self.revocations_file)?;
        let mut frontier = self.revocation_frontier.lock().map_err(|_| {
            AgentdError::Protocol(
                "automation effect revocation frontier lock is poisoned".to_string(),
            )
        })?;
        let observed = (
            head.authority_epoch,
            head.revision,
            revocations_digest(&head)?,
        );
        if observed.0 == frontier.0 && observed.1 == frontier.1 {
            return if observed.2 == frontier.2 {
                Ok(())
            } else {
                Err(AgentdError::GenerationFenced(
                    "revocation content changed without advancing its frontier".to_string(),
                ))
            };
        }
        if observed.0 < frontier.0 || (observed.0 == frontier.0 && observed.1 < frontier.1) {
            return Err(AgentdError::GenerationFenced(
                "automation effect revocation frontier rolled back".to_string(),
            ));
        }
        self.authority.update_revocations(head).map_err(|error| {
            AgentdError::GenerationFenced(format!(
                "automation effect revocation refresh rejected: {error}"
            ))
        })?;
        *frontier = observed;
        Ok(())
    }

    fn validate_intent(
        &self,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
    ) -> Result<(), AgentdError> {
        self.validate_wire_payload(wire_payload)?;
        if intent.subject_id != self.agent_id.as_str()
            || intent.destination_id != self.destination_id
            || intent.final_use_scope_digest != self.final_use_scope_digest
        {
            return Err(AgentdError::GenerationFenced(
                "automation effect intent is outside the host-owned subject/destination/scope"
                    .to_string(),
            ));
        }
        if Sha256Digest::for_bytes(wire_payload) != intent.payload_digest {
            return Err(AgentdError::Invalid(
                "automation effect wire payload digest mismatch".to_string(),
            ));
        }
        Ok(())
    }

    fn validate_wire_payload(&self, wire_payload: &[u8]) -> Result<(), AgentdError> {
        if wire_payload.is_empty() || wire_payload.len() > crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES {
            return Err(AgentdError::Invalid(
                "automation effect wire payload is empty or too large".to_string(),
            ));
        }
        Ok(())
    }

    fn historical_fence(
        &self,
        run: &codex_hepta_automation::TaskFlowRun,
    ) -> Result<TaskFlowFence, AgentdError> {
        if run.owner_agent_id != self.agent_id {
            return Err(AgentdError::GenerationFenced(
                "TaskFlow run is owned by a different Agent".to_string(),
            ));
        }
        TaskFlowFence::new(
            run.owner_agent_id.clone(),
            run.owner_id
                .clone()
                .ok_or_else(|| AgentdError::Protocol("TaskFlow owner id is missing".to_string()))?,
            run.owner_epoch.ok_or_else(|| {
                AgentdError::Protocol("TaskFlow owner epoch is missing".to_string())
            })?,
            run.generation.ok_or_else(|| {
                AgentdError::Protocol("TaskFlow owner generation is missing".to_string())
            })?,
            run.fencing_token.clone().ok_or_else(|| {
                AgentdError::Protocol("TaskFlow fencing token is missing".to_string())
            })?,
        )
        .map_err(|error| AgentdError::Protocol(format!("rebuild TaskFlow fence: {error}")))
    }

    fn current_fence(
        &self,
        run: &codex_hepta_automation::TaskFlowRun,
        now_ms: u64,
    ) -> Result<TaskFlowFence, AgentdError> {
        let fence = self.historical_fence(run)?;
        if fence.owner_epoch != self.spawn_generation {
            return Err(AgentdError::GenerationFenced(
                "effect execution requires the current host generation".to_string(),
            ));
        }
        if run
            .lease_expires_at_ms
            .is_none_or(|expires_at| expires_at <= now_ms)
        {
            return Err(AgentdError::Protocol(
                "TaskFlow owner lease is not current".to_string(),
            ));
        }
        Ok(fence)
    }
}

// This is a pre-contact freshness check, not a second authority issuer.
// A changed host feed defers the effect; refresh occurs after the current
// final-use guard is released. No old feed is accepted while waiting on SQLite.
struct CurrentRevocationEffectDriver {
    host: AgentdAutomationEffectHost,
    inner: ProviderEffectTaskFlowDriver<HttpProviderEffectAdapter>,
}
impl AsyncAuthorizedEffectDriver for CurrentRevocationEffectDriver {
    fn dispatch<'a>(
        &'a mut self,
        request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        Box::pin(async move {
            let head = read_revocations_file(&self.host.revocations_file)
                .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
            let digest = revocations_digest(&head)
                .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
            {
                let frontier = self
                    .host
                    .revocation_frontier
                    .lock()
                    .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
                if (head.authority_epoch, head.revision) != (frontier.0, frontier.1)
                    || digest != frontier.2
                {
                    return Err(AuthorizedEffectDriverError::BeforeProviderContact);
                }
            }
            self.inner.dispatch(request).await
        })
    }
}
fn revocations_digest(head: &FinalUseRevocations) -> Result<Sha256Digest, AgentdError> {
    Ok(Sha256Digest::for_bytes(&serde_json::to_vec(head)?))
}

fn product_effect_fencing_token(
    agent_id: &codex_hepta_contracts::AgentId,
    generation: u64,
    provider_profile_digest: &Sha256Digest,
) -> String {
    let mut bytes = b"hepta.agentd.automation-effect-fence.v1\0".to_vec();
    push_profile_text(&mut bytes, agent_id.as_str());
    bytes.extend_from_slice(&generation.to_be_bytes());
    push_profile_text(&mut bytes, provider_profile_digest.as_str());
    Sha256Digest::for_bytes(&bytes).as_str().to_string()
}

fn terminal_receipt_from_ack(ack: &ProviderEffectAck) -> Option<AuthorizedEffectProviderReceipt> {
    let outcome = match ack.status {
        ProviderEffectAckStatus::Completed => AuthorizedEffectOutcome::Succeeded,
        ProviderEffectAckStatus::Rejected => AuthorizedEffectOutcome::Failed,
        ProviderEffectAckStatus::Accepted => return None,
    };
    Some(AuthorizedEffectProviderReceipt {
        outcome,
        receipt_digest: serialized_observation_digest(
            b"hepta.agentd.provider-effect.lookup.v1\0",
            ack,
        ),
    })
}

fn serialized_observation_digest(domain: &[u8], value: &impl serde::Serialize) -> Sha256Digest {
    let mut bytes = domain.to_vec();
    if let Ok(encoded) = serde_json::to_vec(value) {
        bytes.extend_from_slice(&encoded);
    } else {
        bytes.extend_from_slice(b"serialization-unavailable");
    }
    Sha256Digest::for_bytes(&bytes)
}

#[cfg(all(test, unix))]
#[path = "automation_effect_host_tests.rs"]
mod tests;
