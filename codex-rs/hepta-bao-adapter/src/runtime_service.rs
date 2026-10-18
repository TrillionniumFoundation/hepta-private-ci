//! The single protected production owner composes the actual provider saga.
use crate::BaoApprovedReadV1;
use crate::BaoAuthBusAdmission;
use crate::BaoAuthBusEvidenceProvider;
use crate::BaoClient;
use crate::BaoConsumptionStateV1;
use crate::BaoFinalUseHost;
use crate::BaoSecretReceipt;
use crate::ConsumerEvidenceClient;
use crate::ConsumerPortClient;
use crate::ConsumerPortError;
use crate::HeptaSecretsProductRuntimeV1;
use crate::SecretsAuthorityClient;
use crate::SqliteBaoOwnerV1;
use crate::compose_hepta_secrets_runtime;
use crate::local_endpoint::BoundSocket;
use crate::local_service::LocalServiceOwner;
use crate::runtime_authbus::open_authbus;
use crate::runtime_clock::RuntimeEvidence;
use crate::runtime_clock::RuntimeProtectedClock;
use crate::runtime_config::SecretsRuntimeServiceConfig;
use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::ReservationState;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::future::Future;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

#[derive(Deserialize, Serialize)]
#[serde(tag = "command", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum RuntimeRequest {
    Consume {
        operation_id: String,
        budget_ms: u64,
    },
    Status {
        operation_id: String,
    },
    Recover {
        operation_id: String,
    },
}
#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum SecretsRuntimeResponse {
    Completed {
        original_operation_id: String,
        receipt: BaoSecretReceipt,
        reservation_id: String,
        observed_cost: u64,
    },
    Unknown {
        original_operation_id: String,
    },
    Rejected,
}

struct SecretsRuntimeOwner {
    config: SecretsRuntimeServiceConfig,
    client: BaoClient,
    host: Arc<BaoFinalUseHost>,
    authority: SecretsAuthorityClient,
    consumer: Arc<ConsumerPortClient>,
    clock: Arc<RuntimeProtectedClock>,
    owner: Arc<SqliteBaoOwnerV1>,
    authbus: AuthBusAuthorityHost,
    runtime: HeptaSecretsProductRuntimeV1,
    admission: tokio::sync::Semaphore,
    fenced: AtomicBool,
}

/// Root policy supplies every authority and destination. The kernel peer only
/// chooses its enrolled Agent identity; requests contain no secret, policy,
/// provider endpoint, success field or replacement operation identity.
pub async fn serve_secrets_runtime(
    config: SecretsRuntimeServiceConfig,
    shutdown: impl Future<Output = ()>,
) -> Result<(), ConsumerPortError> {
    let (client, consumer, authority) = config.components()?;
    let endpoint = BoundSocket::bind(&config.service.socket_path, config.service.ipc_group_gid)?;
    let consumer = Arc::new(consumer);
    let clock = Arc::new(RuntimeProtectedClock::new(Duration::from_millis(
        config.maximum_clock_age_ms,
    )));
    let mut evidence = RuntimeEvidence {
        client: ConsumerEvidenceClient::new(config.evidence.clone())?,
        clock: Arc::clone(&clock),
    };
    evidence.trusted_time().map_err(unavailable)?;
    let update = authority.refresh_revocations()?;
    std::fs::create_dir_all(&config.final_use_state).map_err(unavailable)?;
    std::fs::set_permissions(
        &config.final_use_state,
        std::fs::Permissions::from_mode(0o700),
    )
    .map_err(unavailable)?;
    let final_use = FinalUseAuthority::open_state_dir_with_recovered_trust(
        &config.final_use_state,
        config.roles.issuer_id.clone(),
        config.roles.issuer_verifying_key,
        update.update.head.clone(),
        Arc::clone(&clock) as Arc<dyn AuthorityClock>,
        Arc::new(authority.clone()),
    )
    .map_err(|error| startup_error("final-use-owner", error))?;
    let host = Arc::new(
        BaoFinalUseHost::new(
            final_use,
            FinalUseApprovalVerifier::new(
                config.roles.approver_id.clone(),
                config.roles.approver_verifying_key,
            )
            .map_err(unavailable)?,
            FinalUseRevocationFeedVerifier::new(
                config.revocation_distributor_id.clone(),
                config.revocation_verifying_key,
            )
            .map_err(unavailable)?,
            Arc::clone(&clock) as Arc<dyn AuthorityClock>,
            [consumer.registration().map_err(unavailable)?],
        )
        .map_err(unavailable)?,
    );
    host.apply_revocation_update(&update)
        .map_err(|error| startup_error("revocation-feed", error))?;
    let authbus = open_authbus(&config, &mut evidence)
        .await
        .map_err(|error| startup_error("authbus-owner", error))?;
    let owner =
        match SqliteBaoOwnerV1::open(&config.owner_database, /*external_checkpoint*/ None).await {
            Ok(owner) => Arc::new(owner),
            Err(error) => {
                authbus.close().await;
                return Err(unavailable(error));
            }
        };
    let runtime = match compose_hepta_secrets_runtime(
        Arc::clone(&host),
        Arc::clone(&owner),
        Default::default(),
    ) {
        Ok(runtime) => runtime,
        Err(error) => {
            owner.close().await;
            authbus.close().await;
            return Err(unavailable(error));
        }
    };
    let service = config.service.clone();
    let owner = Arc::new(SecretsRuntimeOwner {
        config,
        client,
        host,
        authority,
        consumer,
        clock,
        owner,
        authbus,
        runtime,
        admission: tokio::sync::Semaphore::new(1),
        fenced: AtomicBool::new(false),
    });
    crate::local_service::serve(service, owner, endpoint, shutdown).await
}

impl SecretsRuntimeOwner {
    async fn status(&self, operation: &str) -> Result<SecretsRuntimeResponse, ConsumerPortError> {
        let unknown = || SecretsRuntimeResponse::Unknown {
            original_operation_id: operation.to_owned(),
        };
        let row = match self.owner.consumption_result(operation).await {
            Ok(row) => row,
            Err(crate::SqliteBaoOwnerErrorV1::OperationNotFound) => return Ok(unknown()),
            Err(error) => return Err(unavailable(error)),
        };
        if row.operation.state != BaoConsumptionStateV1::Succeeded {
            return Ok(unknown());
        }
        let reservation = self
            .authbus
            .reservation_by_operation(&StableId::new(operation).map_err(unavailable)?)
            .await
            .map_err(unavailable)?;
        let Some(reservation) = reservation else {
            return Ok(unknown());
        };
        let Some(receipt) = row.operation.receipt else {
            return Ok(unknown());
        };
        if reservation.state != ReservationState::Settled
            || reservation.observed_cost != Some(self.config.evidence.cost)
            || reservation.terminal_evidence
                != Some(Digest32::from_array(
                    receipt.evidence_digest().map_err(unavailable)?,
                ))
            || !self
                .consumer
                .observe(operation, row.operation.semantic_sha256)?
        {
            return Ok(unknown());
        }
        Ok(SecretsRuntimeResponse::Completed {
            original_operation_id: operation.to_owned(),
            receipt,
            reservation_id: reservation.reservation_id.as_str().to_owned(),
            observed_cost: self.config.evidence.cost,
        })
    }
    async fn consume(
        &self,
        peer: u32,
        operation: &str,
        budget_ms: u64,
        transport_deadline: Instant,
    ) -> Result<SecretsRuntimeResponse, ConsumerPortError> {
        if self.fenced.load(Ordering::Acquire) || self.owner.is_fenced() {
            return self.status(operation).await;
        }
        let deadline = transport_deadline.min(
            Instant::now()
                + Duration::from_millis(budget_ms.min(self.config.service.request_timeout_ms)),
        );
        let _serial = self.admission.acquire().await.map_err(unavailable)?;
        if self.fenced.load(Ordering::Acquire) || Instant::now() >= deadline {
            return self.status(operation).await;
        }
        let _clock_budget = self.clock.begin_original_deadline(deadline)?;
        // A fresh protected sample is prepared before any final-use entry.
        let mut evidence = RuntimeEvidence {
            client: ConsumerEvidenceClient::new(self.config.evidence.clone())?
                .for_original_deadline(deadline),
            clock: Arc::clone(&self.clock),
        };
        let time = evidence.trusted_time().map_err(unavailable)?;
        let current = self.clock.now_unix_ms().map_err(unavailable)?;
        if current < self.config.policy_not_before_ms || current >= self.config.policy_expires_at_ms
        {
            return self.status(operation).await;
        }
        let policy = self
            .authbus
            .policy_snapshot(&StableId::new(&self.config.policy_id).map_err(unavailable)?)
            .await
            .map_err(unavailable)?;
        if policy.revoked || policy.expires_at_ms != self.config.policy_expires_at_ms {
            return self.status(operation).await;
        }
        let authority = self.authority.for_original_deadline(deadline);
        let (pair, update) = match authority.authorize_original_once(operation) {
            Ok(pair) => pair,
            Err(_) => return self.status(operation).await,
        };
        self.host
            .apply_revocation_update(&update)
            .map_err(unavailable)?;
        let source_time = self
            .authbus
            .observe_trusted_time_attestation(&time)
            .await
            .map_err(unavailable)?;
        let quota = self
            .authbus
            .quota_snapshot(&self.config.quota_key(peer)?)
            .await
            .map_err(unavailable)?;
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .ok_or(ConsumerPortError::Unavailable)?;
        let expires = self
            .clock
            .now_unix_ms()
            .map_err(unavailable)?
            .checked_add(u64::try_from(remaining.as_millis()).map_err(unavailable)?)
            .ok_or(ConsumerPortError::Unavailable)?
            .min(pair.grant.grant.expires_at_unix_ms)
            .min(self.config.policy_expires_at_ms);
        if source_time.wall_time_ms() < self.config.policy_not_before_ms
            || source_time.wall_time_ms() >= expires
        {
            return Err(ConsumerPortError::Rejected);
        }
        let admission = BaoAuthBusAdmission {
            policy_revision: policy.revision,
            quota_key: quota.quota_key,
            expected_quota_revision: quota.revision,
            operation_id: StableId::new(operation).map_err(unavailable)?,
            amount: self.config.evidence.cost,
            expires_at_ms: expires,
        };
        authority.begin_original(&pair)?;
        let _budget = self
            .consumer
            .begin_original_operation(operation, deadline)?;
        let read = BaoApprovedReadV1 {
            admission: &admission,
            grant: &pair.grant,
            approval: &pair.approval,
            request: &self.config.request,
        };
        match self
            .runtime
            .runtime()
            .consume_kv_v2_with_authbus(&self.client, &self.authbus, read, &mut evidence)
            .await
        {
            Ok(_) => self.status(operation).await,
            Err(error) => {
                eprintln!("secrets runtime original provider saga remains Unknown: {error:?}");
                self.status(operation).await
            }
        }
    }
    async fn recover(&self, operation: &str) -> Result<SecretsRuntimeResponse, ConsumerPortError> {
        let _serial = self.admission.acquire().await.map_err(unavailable)?;
        if self.owner.consumption_result(operation).await.is_err() {
            return self.status(operation).await;
        }
        let mut evidence = RuntimeEvidence {
            client: ConsumerEvidenceClient::new(self.config.evidence.clone())?,
            clock: Arc::clone(&self.clock),
        };
        // Refresh the same independently verified clock used by recovery claims.
        // This cannot clear a permanent fence or admit a provider/credential effect.
        evidence.trusted_time().map_err(unavailable)?;
        // This existing owner recovery only observes the original consumer and
        // settles its exact held reservation. It has no provider redispatch port.
        let _result = self
            .runtime
            .runtime()
            .reconcile_consumption(&self.authbus, operation, &mut evidence)
            .await;
        self.status(operation).await
    }
}
impl LocalServiceOwner for SecretsRuntimeOwner {
    async fn handle(
        &self,
        peer: u32,
        body: &[u8],
        original_deadline: Instant,
    ) -> Result<Vec<u8>, ConsumerPortError> {
        let request: RuntimeRequest = serde_json::from_slice(body).map_err(unavailable)?;
        let response = match request {
            RuntimeRequest::Consume {
                operation_id,
                budget_ms,
            } => {
                let original = self.config.operation_id(peer, &operation_id)?;
                if budget_ms == 0 {
                    SecretsRuntimeResponse::Rejected
                } else {
                    self.consume(peer, &original, budget_ms, original_deadline)
                        .await
                        .unwrap_or(SecretsRuntimeResponse::Unknown {
                            original_operation_id: original,
                        })
                }
            }
            RuntimeRequest::Status { operation_id } => {
                self.status(&self.config.operation_id(peer, &operation_id)?)
                    .await?
            }
            RuntimeRequest::Recover { operation_id } => {
                self.recover(&self.config.operation_id(peer, &operation_id)?)
                    .await?
            }
        };
        serde_json::to_vec(&response).map_err(unavailable)
    }
    fn fence_unknown(&self) {
        self.fenced.store(true, Ordering::Release);
    }
    async fn close(&self) {
        self.fence_unknown();
        self.owner.close().await;
        self.authbus.close().await;
    }
}
fn unavailable(_error: impl std::fmt::Display) -> ConsumerPortError {
    ConsumerPortError::Unavailable
}

fn startup_error(phase: &str, error: impl std::fmt::Display) -> ConsumerPortError {
    eprintln!("secrets runtime startup {phase} failed: {error}");
    ConsumerPortError::Unavailable
}
