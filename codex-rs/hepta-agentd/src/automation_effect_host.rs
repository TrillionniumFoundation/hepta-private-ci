//! Host-owned composition for final-use-authorized automation effects.
//!
//! TaskFlow owns durable intent/attempt/observation. Agentd owns the provider
//! contract, exact historical provider-key profile, feed freshness and bounded
//! task lifetime on its existing runtime. A cancelled response is not a cancelled
//! provider effect, proof of absence, or permission to discard its owner.

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
use codex_hepta_automation::AuthorizedEffectPending;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AuthorizedProviderEffectRequest;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowStepReceipt;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseTrustKey;
use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_contracts::VerifiedFinalUseRevocationHead;
use codex_model_provider::HttpProviderEffectAdapter;
use codex_model_provider::HttpProviderEffectConfig;
use codex_model_provider::HttpProviderEffectContractAttestation;
use http::HeaderMap;
use http::HeaderName;
use http::HeaderValue;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdProductionAuthorityBootstrap;
use crate::authority_trust_host::AgentdFinalUseTrustStore;

#[path = "authority_effect_tasks.rs"]
mod effect_tasks;
#[path = "authority_feed_clock.rs"]
mod feed_clock;

use effect_tasks::EffectTasks;
use feed_clock::FinalUseFeedClock;

const AUTOMATION_EFFECT_HOST_SCHEMA_VERSION: u32 = 2;
const MAX_AUTOMATION_EFFECT_HOST_FILE_BYTES: u64 = 64 * 1024;
const MAX_AUTOMATION_EFFECT_REVOCATION_FEED_FILE_BYTES: u64 = 4 * 1024 * 1024;
const MAX_FINAL_USE_TRUST_KEYS: usize = 8;
const MAX_PROVIDER_HEADERS: usize = 64;
const MAX_INFLIGHT_EFFECTS: usize = 1_024;

fn default_inflight_effects() -> usize {
    64
}

fn default_claim_reserve() -> usize {
    256
}

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
    destination_id: String,
    final_use_scope_digest: Sha256Digest,
    authority: FinalUseAuthority,
    refresh_clock: Arc<dyn AuthorityClock>,
    admission_clock: Arc<FinalUseFeedClock>,
    revocation_feed_verifier: FinalUseRevocationFeedVerifier,
    revocation_feed_file: PathBuf,
    revocation_refresh: Arc<Mutex<()>>,
    adapter: HttpProviderEffectAdapter,
    effect_tasks: Arc<EffectTasks>,
    claim_reserve: usize,
    max_inflight_effects: usize,
}

impl std::fmt::Debug for AgentdAutomationEffectHost {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("AgentdAutomationEffectHost")
            .field("agent_id", &self.agent_id)
            .field("provider_scope", &self.provider_scope)
            .field("destination_id", &self.destination_id)
            .field("final_use_scope_digest", &self.final_use_scope_digest)
            .field("adapter", &self.adapter)
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct FinalUseTrustKeyFileV1 {
    key_id: String,
    verifying_key_hex: String,
    not_before_authority_epoch: u64,
    not_after_authority_epoch: u64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct AutomationEffectHostFileV2 {
    schema_version: u32,
    provider_scope: String,
    destination_id: String,
    final_use_scope_sha256: String,
    dispatch_url: String,
    lookup_url_template: String,
    #[serde(default)]
    headers: BTreeMap<String, String>,
    timeout_ms: u64,
    contract_id: String,
    contract_sha256: String,
    contract_authority_epoch: u64,
    contract_signature_hex: String,
    contract_verifying_key_hex: String,
    final_use_signer_id: String,
    final_use_issuer_keys: Vec<FinalUseTrustKeyFileV1>,
    final_use_revocation_distributor_id: String,
    final_use_revocation_keys: Vec<FinalUseTrustKeyFileV1>,
    final_use_revocation_feed_file: PathBuf,
    final_use_trust_root: PathBuf,
    #[serde(default = "default_inflight_effects")]
    max_inflight_effects: usize,
    #[serde(default = "default_claim_reserve")]
    claim_reserve: usize,
}

#[derive(Clone, Copy)]
enum AutomationAuthorityMode<'a> {
    Compatibility,
    Production(&'a AgentdProductionAuthorityBootstrap),
}

impl AgentdAutomationEffectHost {
    pub(crate) fn open(identity: &AgentdIdentity, path: &Path) -> Result<Self, AgentdError> {
        Self::open_with_authority(identity, path, AutomationAuthorityMode::Compatibility)
    }

    pub(crate) fn open_production(
        identity: &AgentdIdentity,
        path: &Path,
        authority: &AgentdProductionAuthorityBootstrap,
    ) -> Result<Self, AgentdError> {
        Self::open_with_authority(
            identity,
            path,
            AutomationAuthorityMode::Production(authority),
        )
    }

    fn open_with_authority(
        identity: &AgentdIdentity,
        path: &Path,
        authority_mode: AutomationAuthorityMode<'_>,
    ) -> Result<Self, AgentdError> {
        let config = read_host_file(path)?;
        if config.schema_version != AUTOMATION_EFFECT_HOST_SCHEMA_VERSION {
            return Err(AgentdError::Invalid(
                "unsupported automation effect host schema".to_string(),
            ));
        }
        validate_host_identifier("provider_scope", &config.provider_scope)?;
        validate_host_identifier("destination_id", &config.destination_id)?;
        if config.timeout_ms == 0 || config.timeout_ms > 30_000 {
            return Err(AgentdError::Invalid(
                "automation effect timeout_ms must be 1..=30000".to_string(),
            ));
        }
        if config.headers.len() > MAX_PROVIDER_HEADERS {
            return Err(AgentdError::Invalid(
                "automation effect provider header bound exceeded".to_string(),
            ));
        }
        if config.max_inflight_effects == 0 || config.max_inflight_effects > MAX_INFLIGHT_EFFECTS {
            return Err(AgentdError::Invalid(
                "max_inflight_effects must be 1..=1024".to_string(),
            ));
        }
        let final_use_scope_digest = Sha256Digest::parse(config.final_use_scope_sha256.clone())
            .map_err(AgentdError::Invalid)?;
        let declared_contract_digest =
            Sha256Digest::parse(config.contract_sha256.clone()).map_err(AgentdError::Invalid)?;
        let contract_signature =
            decode_hex_array::<64>(&config.contract_signature_hex, "contract_signature_hex")?;
        let contract_verifying_key = decode_hex_array::<32>(
            &config.contract_verifying_key_hex,
            "contract_verifying_key_hex",
        )?;
        let final_use_issuer_keys = issuer_trust_keys(&config.final_use_issuer_keys)?;
        let final_use_revocation_keys = control_trust_keys(&config.final_use_revocation_keys)?;
        let mut headers = HeaderMap::new();
        for (name, value) in config.headers {
            let name = HeaderName::from_bytes(name.as_bytes()).map_err(|error| {
                AgentdError::Invalid(format!("invalid provider header name: {error}"))
            })?;
            let value = HeaderValue::from_bytes(value.as_bytes()).map_err(|error| {
                AgentdError::Invalid(format!("invalid provider header value: {error}"))
            })?;
            headers.append(name, value);
        }
        let attestation = HttpProviderEffectContractAttestation::verify_signed(
            config.contract_id.clone(),
            declared_contract_digest,
            config.contract_authority_epoch,
            &contract_signature,
            &contract_verifying_key,
        )
        .map_err(AgentdError::Invalid)?;
        let adapter = HttpProviderEffectAdapter::new(HttpProviderEffectConfig {
            dispatch_url: config.dispatch_url,
            lookup_url_template: config.lookup_url_template,
            headers,
            timeout: Duration::from_millis(config.timeout_ms),
            contract_id: config.contract_id,
            attestation: Some(attestation),
        })
        .map_err(AgentdError::Invalid)?;
        if !config.final_use_revocation_feed_file.is_absolute()
            || !config.final_use_trust_root.is_absolute()
        {
            return Err(AgentdError::Invalid(
                "final_use_revocation_feed_file and final_use_trust_root must be absolute"
                    .to_string(),
            ));
        }
        let revocation_feed_verifier = FinalUseRevocationFeedVerifier::new_with_keys(
            config.final_use_revocation_distributor_id,
            final_use_revocation_keys,
        )
        .map_err(|error| {
            AgentdError::Invalid(format!("invalid final-use revocation trust: {error}"))
        })?;
        let signed_update = read_revocation_feed_file(&config.final_use_revocation_feed_file)?;
        let authority_root = identity
            .layout
            .automation_root()
            .join("final-use-authority");
        let local_authority_uninitialized =
            if matches!(authority_mode, AutomationAuthorityMode::Compatibility) {
                authority_state_uninitialized(&authority_root)?
            } else {
                false
            };
        fs::create_dir_all(&authority_root)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&authority_root, fs::Permissions::from_mode(0o700))?;
        }
        let (refresh_clock, admission_clock, authority) = match authority_mode {
            AutomationAuthorityMode::Compatibility => {
                let authority_trust = Arc::new(AgentdFinalUseTrustStore::open(
                    &config.final_use_trust_root,
                    &identity.home_root,
                    &config.final_use_signer_id,
                )?);
                let now = authority_trust.now_unix_ms().map_err(|error| {
                    AgentdError::Protocol(format!("sample protected final-use clock: {error}"))
                })?;
                let verified_initial_head = VerifiedFinalUseRevocationHead::verify(
                    &revocation_feed_verifier,
                    &signed_update,
                    now,
                )
                .map_err(|error| {
                    AgentdError::GenerationFenced(format!(
                        "initial signed final-use revocation feed rejected: {error}"
                    ))
                })?;
                let initial_revocations = verified_initial_head.head().clone();
                let initial_frontier = FinalUseFrontier::for_initial_head(&initial_revocations)
                    .map_err(|error| {
                        AgentdError::Invalid(format!("invalid initial final-use frontier: {error}"))
                    })?;
                authority_trust
                    .ensure_initial_frontier(initial_frontier, local_authority_uninitialized)?;
                let refresh_clock: Arc<dyn AuthorityClock> = authority_trust.clone();
                let admission_clock = Arc::new(FinalUseFeedClock::new(Arc::clone(&refresh_clock)));
                admission_clock
                    .publish(&verified_initial_head)
                    .map_err(|error| {
                        AgentdError::GenerationFenced(format!(
                            "initial feed interval rejected: {error}"
                        ))
                    })?;
                let clock: Arc<dyn AuthorityClock> = admission_clock.clone();
                let frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>> =
                    authority_trust;
                let authority = FinalUseAuthority::recover_state_dir_with_issuer_keys(
                    &authority_root,
                    config.final_use_signer_id.clone(),
                    final_use_issuer_keys,
                    initial_revocations,
                    clock,
                    frontier_store,
                )
                .map_err(|error| {
                    AgentdError::Protocol(format!(
                        "open automation final-use authority state: {error}"
                    ))
                })?;
                (refresh_clock, admission_clock, authority)
            }
            AutomationAuthorityMode::Production(bootstrap) => {
                let context = bootstrap.bind(&final_use_issuer_keys).map_err(|error| {
                    AgentdError::GenerationFenced(format!(
                        "production final-use trust rejected: {error}"
                    ))
                })?;
                let refresh_clock = context.clock();
                let now = refresh_clock.now_unix_ms().map_err(|error| {
                    AgentdError::GenerationFenced(format!(
                        "sample production final-use clock: {error}"
                    ))
                })?;
                let verified_initial_head = VerifiedFinalUseRevocationHead::verify(
                    &revocation_feed_verifier,
                    &signed_update,
                    now,
                )
                .map_err(|error| {
                    AgentdError::GenerationFenced(format!(
                        "initial signed final-use revocation feed rejected: {error}"
                    ))
                })?;
                let admission_clock = context.feed_clock();
                admission_clock
                    .publish(&verified_initial_head)
                    .map_err(|error| {
                        AgentdError::GenerationFenced(format!(
                            "initial production feed interval rejected: {error}"
                        ))
                    })?;
                let authority = context
                    .recover_state_dir_with_feed_clock(
                        &authority_root,
                        config.final_use_signer_id.clone(),
                        final_use_issuer_keys,
                        &verified_initial_head,
                        Arc::clone(&admission_clock),
                    )
                    .map_err(|error| {
                        AgentdError::GenerationFenced(format!(
                            "recover production automation authority: {error}"
                        ))
                    })?;
                (refresh_clock, admission_clock, authority)
            }
        };
        let capacity = authority
            .capacity()
            .map_err(|error| AgentdError::Protocol(format!("read authority capacity: {error}")))?;
        if config
            .claim_reserve
            .saturating_add(config.max_inflight_effects)
            >= capacity.max_claims
            || config.claim_reserve >= capacity.max_revocations
        {
            return Err(AgentdError::Invalid(
                "authority reserve leaves no admissible capacity".to_string(),
            ));
        }
        let host = Self {
            agent_id: identity.agent_id.clone(),
            provider_scope: config.provider_scope,
            destination_id: config.destination_id,
            final_use_scope_digest,
            authority,
            refresh_clock,
            admission_clock,
            revocation_feed_verifier,
            revocation_feed_file: config.final_use_revocation_feed_file,
            revocation_refresh: Arc::new(Mutex::new(())),
            adapter,
            effect_tasks: Arc::new(EffectTasks::new(config.max_inflight_effects)),
            claim_reserve: config.claim_reserve,
            max_inflight_effects: config.max_inflight_effects,
        };
        // No authority escapes before the recovered head and verified feed agree.
        host.refresh_revocations()?;
        Ok(host)
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
        // Terminal observation is read-only and neither consumes reserve nor
        // needs a fresh effect grant/feed. All identity checks remain in store.
        if let Some(receipt) = store
            .read_authorized_taskflow_effect_receipt(intent, command_id)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("read terminal effect receipt: {error}"))
            })?
        {
            return Ok(receipt);
        }
        let response = self
            .effect_tasks
            .submit(|| {
                let host = self.clone();
                let store = store.clone();
                let intent = intent.clone();
                let wire_payload = wire_payload.to_vec();
                let signed_grant = signed_grant.clone();
                let command_id = command_id.to_owned();
                async move {
                    host.execute_owned(
                        &store,
                        &intent,
                        &wire_payload,
                        &signed_grant,
                        &command_id,
                        now_ms,
                    )
                    .await
                }
            })
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        response.await.map_err(|_| AgentdError::Protocol(
            "effect task ended without a response; preserve its durable identity and reconcile before retry".to_string(),
        ))?
    }

    async fn execute_owned(
        &self,
        store: &AutomationStore,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
        signed_grant: &SignedFinalUseGrant,
        command_id: &str,
        now_ms: u64,
    ) -> Result<TaskFlowStepReceipt, AgentdError> {
        self.refresh_revocations()?;
        let capacity = self
            .authority
            .capacity()
            .map_err(|error| AgentdError::Protocol(format!("read authority capacity: {error}")))?;
        // Account for every possible concurrent one-nonce task. Reconciliation
        // and signed revocation/epoch transitions never pass through this gate.
        if capacity.remaining_claims()
            <= self.claim_reserve.saturating_add(self.max_inflight_effects)
            || capacity.remaining_revocations() <= self.claim_reserve
        {
            return Err(AgentdError::GenerationFenced(format!(
                "authority reserve reached: claims={} revocations={}; request signed epoch rollover",
                capacity.remaining_claims(),
                capacity.remaining_revocations(),
            )));
        }
        let run = store
            .taskflow_run(&intent.run_id)
            .await
            .map_err(|error| AgentdError::Protocol(format!("read effect TaskFlow run: {error}")))?
            .ok_or_else(|| {
                AgentdError::Invalid("effect TaskFlow run does not exist".to_string())
            })?;
        let fence = self.current_fence(&run, now_ms)?;
        let binding = intent
            .final_use_binding()
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        let mut driver = HttpAuthorizedEffectDriver {
            adapter: self.adapter.clone(),
            provider_scope: self.provider_scope.clone(),
            destination_id: self.destination_id.clone(),
            admission_clock: Arc::clone(&self.admission_clock),
            grant_not_before: signed_grant.grant.not_before_unix_ms,
            grant_expires: signed_grant.grant.expires_at_unix_ms,
        };
        store
            .execute_authorized_taskflow_effect_async(
                &self.authority,
                &mut driver,
                intent,
                wire_payload,
                &fence,
                signed_grant,
                &binding,
                command_id,
                now_ms,
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
        if pending.destination_id != self.destination_id {
            return Err(AgentdError::GenerationFenced(
                "pending effect destination differs from the configured provider".to_string(),
            ));
        }
        let run = store
            .taskflow_run(run_id)
            .await
            .map_err(|error| AgentdError::Protocol(format!("read effect TaskFlow run: {error}")))?
            .ok_or_else(|| {
                AgentdError::Invalid("effect TaskFlow run does not exist".to_string())
            })?;
        let fence = self.current_fence(&run, now_ms)?;
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
                    if receipt.observation != Some(TaskFlowStepObservation::Indeterminate) =>
                {
                    return Ok(AgentdAutomationEffectReconcileOutcome::Observed(Box::new(
                        receipt,
                    )));
                }
                AuthorizedEffectRecoveryResult::ProvenAbsent => {
                    return Ok(AgentdAutomationEffectReconcileOutcome::ProvenAbsent);
                }
                AuthorizedEffectRecoveryResult::Observed(_) => {}
            }
        }
        let provider_intent = self.provider_intent(&pending)?;
        match self.adapter.lookup_for_intent(&provider_intent).await {
            ProviderEffectLookup::Ack(ack) => {
                if ack.validate_for(&provider_intent).is_err() {
                    return Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate);
                }
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
                    AuthorizedEffectRecoveryResult::Observed(receipt) => Ok(
                        AgentdAutomationEffectReconcileOutcome::Observed(Box::new(receipt)),
                    ),
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

    fn refresh_revocations(&self) -> Result<(), AgentdError> {
        let _refresh = self.revocation_refresh.lock().map_err(|_| {
            AgentdError::Protocol(
                "automation effect revocation refresh lock is poisoned".to_string(),
            )
        })?;
        let signed = read_revocation_feed_file(&self.revocation_feed_file)?;
        let now = self.refresh_clock.now_unix_ms().map_err(|error| {
            AgentdError::Protocol(format!("sample protected final-use clock: {error}"))
        })?;
        let verified =
            VerifiedFinalUseRevocationHead::verify(&self.revocation_feed_verifier, &signed, now)
                .map_err(|error| {
                    AgentdError::GenerationFenced(format!(
                        "automation effect signed revocation feed rejected: {error}"
                    ))
                })?;
        let current = self.authority.revocation_head().map_err(|error| {
            AgentdError::Protocol(format!("read automation revocation head: {error}"))
        })?;
        if current != signed.update.head {
            // Invalidate before mutation, publish only after success. An older
            // request waiting in the DB cannot borrow a newer feed's lifetime
            // while still observing an older authority head.
            self.admission_clock.invalidate().map_err(|error| {
                AgentdError::GenerationFenced(format!("invalidate feed interval: {error}"))
            })?;
            self.revocation_feed_verifier
                .apply(&self.authority, &signed, now)
                .map_err(|error| {
                    AgentdError::GenerationFenced(format!(
                        "automation effect revocation refresh rejected: {error}"
                    ))
                })?;
        }
        self.admission_clock.publish(&verified).map_err(|error| {
            AgentdError::GenerationFenced(format!("publish committed feed interval: {error}"))
        })
    }

    fn validate_intent(
        &self,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
    ) -> Result<(), AgentdError> {
        if wire_payload.is_empty() || wire_payload.len() > crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES {
            return Err(AgentdError::Invalid(
                "automation effect wire payload is empty or too large".to_string(),
            ));
        }
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

    fn current_fence(
        &self,
        run: &codex_hepta_automation::TaskFlowRun,
        now_ms: u64,
    ) -> Result<TaskFlowFence, AgentdError> {
        if run.owner_agent_id != self.agent_id {
            return Err(AgentdError::GenerationFenced(
                "TaskFlow run is owned by a different Agent".to_string(),
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

    fn provider_intent(
        &self,
        pending: &AuthorizedEffectPending,
    ) -> Result<ProviderEffectIntent, AgentdError> {
        historical_provider_intent(
            &self.provider_scope,
            &pending.run_id,
            &pending.step_id,
            &pending.payload_digest,
        )
        .map_err(|_| {
            AgentdError::Invalid("invalid historical provider effect identity".to_string())
        })
    }
}

/// Preserve the pre-migration external provider-key profile for dispatch AND
/// lookup. The async TaskFlow logical key is not substituted for this namespace.
fn historical_provider_intent(
    provider_scope: &str,
    run_id: &str,
    step_id: &str,
    payload: &Sha256Digest,
) -> Result<ProviderEffectIntent, AuthorizedEffectDriverError> {
    let key = ProviderEffectKey::for_operation(provider_scope, run_id, step_id)
        .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
    Ok(ProviderEffectIntent::new(key, payload.clone()))
}

struct HttpAuthorizedEffectDriver {
    adapter: HttpProviderEffectAdapter,
    provider_scope: String,
    destination_id: String,
    admission_clock: Arc<FinalUseFeedClock>,
    grant_not_before: u64,
    grant_expires: u64,
}

impl AsyncAuthorizedEffectDriver for HttpAuthorizedEffectDriver {
    fn dispatch<'a>(
        &'a mut self,
        request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        Box::pin(async move {
            if request.intent.destination_id != self.destination_id
                || request.provider_intent.payload_sha256 != request.intent.payload_digest
                || Sha256Digest::for_bytes(request.wire_payload) != request.intent.payload_digest
            {
                return Err(AuthorizedEffectDriverError::BeforeProviderContact);
            }
            let provider_intent = historical_provider_intent(
                &self.provider_scope,
                &request.intent.run_id,
                &request.intent.step_id,
                &request.intent.payload_digest,
            )?;
            // The witness has already been durably recorded. Recheck time at
            // actual provider entry, not before an intervening database await.
            let (now, uncertainty) = self
                .admission_clock
                .now_with_uncertainty()
                .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
            if now
                .checked_sub(uncertainty)
                .is_none_or(|earliest| earliest < self.grant_not_before)
                || now
                    .checked_add(uncertainty)
                    .is_none_or(|latest| latest >= self.grant_expires)
            {
                return Err(AuthorizedEffectDriverError::BeforeProviderContact);
            }
            let dispatch = self
                .adapter
                .dispatch_with_payload(&provider_intent, request.wire_payload)
                .await;
            match &dispatch {
                ProviderEffectDispatch::NotDispatched { .. } => {
                    Err(AuthorizedEffectDriverError::BeforeProviderContact)
                }
                ProviderEffectDispatch::Ack(ack) if ack.validate_for(&provider_intent).is_err() => {
                    Ok(AuthorizedEffectProviderReceipt {
                        outcome: AuthorizedEffectOutcome::Indeterminate,
                        receipt_digest: serialized_observation_digest(
                            b"hepta.agentd.provider-effect.invalid-ack.v1\0",
                            ack,
                        ),
                    })
                }
                _ => Ok(receipt_from_dispatch(&dispatch)),
            }
        })
    }
}

fn receipt_from_dispatch(dispatch: &ProviderEffectDispatch) -> AuthorizedEffectProviderReceipt {
    let outcome = match dispatch {
        ProviderEffectDispatch::Ack(ack) => match ack.status {
            ProviderEffectAckStatus::Completed => AuthorizedEffectOutcome::Succeeded,
            ProviderEffectAckStatus::Rejected => AuthorizedEffectOutcome::Failed,
            ProviderEffectAckStatus::Accepted => AuthorizedEffectOutcome::Indeterminate,
        },
        ProviderEffectDispatch::Rejected { .. } => AuthorizedEffectOutcome::Failed,
        ProviderEffectDispatch::Unknown | ProviderEffectDispatch::NotDispatched { .. } => {
            AuthorizedEffectOutcome::Indeterminate
        }
    };
    AuthorizedEffectProviderReceipt {
        outcome,
        receipt_digest: serialized_observation_digest(
            b"hepta.agentd.provider-effect.dispatch.v1\0",
            dispatch,
        ),
    }
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

fn read_host_file(path: &Path) -> Result<AutomationEffectHostFileV2, AgentdError> {
    let bytes = read_protected_file(
        path,
        MAX_AUTOMATION_EFFECT_HOST_FILE_BYTES,
        "automation effect host file",
    )?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn read_revocation_feed_file(path: &Path) -> Result<SignedFinalUseRevocationUpdate, AgentdError> {
    let bytes = read_protected_file(
        path,
        MAX_AUTOMATION_EFFECT_REVOCATION_FEED_FILE_BYTES,
        "automation effect signed revocation feed file",
    )?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn issuer_trust_keys(
    configured: &[FinalUseTrustKeyFileV1],
) -> Result<Vec<FinalUseIssuerTrustKey>, AgentdError> {
    validate_trust_key_count(configured)?;
    configured
        .iter()
        .map(|key| {
            validate_host_identifier("final-use issuer key id", &key.key_id)?;
            Ok(FinalUseIssuerTrustKey {
                key_id: key.key_id.clone(),
                verifying_key: decode_hex_array::<32>(
                    &key.verifying_key_hex,
                    "final-use issuer verifying key",
                )?,
                not_before_authority_epoch: key.not_before_authority_epoch,
                not_after_authority_epoch: key.not_after_authority_epoch,
            })
        })
        .collect()
}

fn control_trust_keys(
    configured: &[FinalUseTrustKeyFileV1],
) -> Result<Vec<FinalUseTrustKey>, AgentdError> {
    validate_trust_key_count(configured)?;
    configured
        .iter()
        .map(|key| {
            validate_host_identifier("final-use revocation key id", &key.key_id)?;
            Ok(FinalUseTrustKey {
                key_id: key.key_id.clone(),
                verifying_key: decode_hex_array::<32>(
                    &key.verifying_key_hex,
                    "final-use revocation verifying key",
                )?,
                not_before_authority_epoch: key.not_before_authority_epoch,
                not_after_authority_epoch: key.not_after_authority_epoch,
            })
        })
        .collect()
}

fn validate_trust_key_count(configured: &[FinalUseTrustKeyFileV1]) -> Result<(), AgentdError> {
    if configured.is_empty() || configured.len() > MAX_FINAL_USE_TRUST_KEYS {
        return Err(AgentdError::Invalid(
            "final-use trust-key ring must contain 1..=8 keys".to_string(),
        ));
    }
    Ok(())
}

fn authority_state_uninitialized(root: &Path) -> Result<bool, AgentdError> {
    if !root.exists() {
        return Ok(true);
    }
    let metadata = fs::symlink_metadata(root)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(AgentdError::Invalid(
            "automation final-use authority root is not a safe directory".to_string(),
        ));
    }
    Ok(!root.join("authority.lock").exists()
        && !root.join("authority.json").exists()
        && !root.join("authority.claims").exists())
}

fn read_protected_file(path: &Path, max_bytes: u64, label: &str) -> Result<Vec<u8>, AgentdError> {
    if !path.is_absolute() {
        return Err(AgentdError::Invalid(format!("{label} must be absolute")));
    }
    let canonical = path.canonicalize()?;
    if canonical != path {
        return Err(AgentdError::Invalid(format!(
            "{label} must be canonical and symlink-free"
        )));
    }
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(AgentdError::Invalid(format!(
            "{label} must be a regular non-symlink file"
        )));
    }
    if metadata.len() == 0 || metadata.len() > max_bytes {
        return Err(AgentdError::Invalid(format!(
            "{label} is empty or too large"
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(AgentdError::Invalid(format!(
                "{label} must not be group/world accessible"
            )));
        }
    }
    Ok(fs::read(path)?)
}

fn validate_host_identifier(label: &str, value: &str) -> Result<(), AgentdError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
    {
        return Err(AgentdError::Invalid(format!(
            "{label} must be a bounded identifier"
        )));
    }
    Ok(())
}

fn decode_hex_array<const N: usize>(value: &str, label: &str) -> Result<[u8; N], AgentdError> {
    if value.len() != N * 2 {
        return Err(AgentdError::Invalid(format!(
            "{label} must contain exactly {} hex characters",
            N * 2
        )));
    }
    let mut output = [0_u8; N];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = hex_nibble(pair[0])
            .ok_or_else(|| AgentdError::Invalid(format!("{label} contains non-hex data")))?;
        let low = hex_nibble(pair[1])
            .ok_or_else(|| AgentdError::Invalid(format!("{label} contains non-hex data")))?;
        output[index] = (high << 4) | low;
    }
    Ok(output)
}

fn hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}

#[cfg(all(test, unix))]
#[path = "automation_effect_host_tests.rs"]
mod tests;
