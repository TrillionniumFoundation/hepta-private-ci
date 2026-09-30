use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::RwLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerVerifierV1;
use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceError;
use crate::LearningArtifactPublishRequestV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::read_dataset_withdrawal_snapshot;

use super::ArtifactOwnerActionV1;
use super::ArtifactOwnerBackupReceiptV1;
use super::ArtifactOwnerBootstrapV1;
use super::ArtifactOwnerKeyringV1;
use super::ArtifactOwnerRuntimePhaseV1;
use super::ArtifactOwnerRuntimeStatusV1;
use super::FsOwnerDurableStoreV1;
use super::InstallWithdrawalSnapshotCommandV1;
use super::OwnerDurableStoreV1;
use super::OwnerRequestDispositionV1;
use super::OwnerRequestJournalV1;
use super::PublishArtifactCommandV1;
use super::SignedArtifactOwnerRequestV1;
use super::backup_owner_root_v1;
use super::bootstrap::load_keyring;
use super::capability_validation::ArtifactOwnerCapabilityError;
use super::reconciliation::ArtifactOwnerReconciliationError;
use super::recovery::ArtifactOwnerStatusError;
use super::registry_commands::ArtifactOwnerCommandDecodeError;
use super::transaction::OwnerJournalError;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerCommandResultV1 {
    pub response: Vec<u8>,
    pub should_shutdown: bool,
    pub replayed: bool,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ArtifactOwnerMetricsV1 {
    pub requests_received: u64,
    pub requests_authenticated: u64,
    pub authentication_failures: u64,
    pub exact_replays: u64,
    pub replay_conflicts: u64,
    pub publications_succeeded: u64,
    pub publications_failed: u64,
    pub recovery_publications_succeeded: u64,
    pub withdrawal_frontiers_installed: u64,
    pub authz_reloads: u64,
    pub backups_succeeded: u64,
    pub command_failures: u64,
}

impl ArtifactOwnerMetricsV1 {
    #[must_use]
    pub fn response_json(self) -> String {
        format!(
            concat!(
                "{{\"schema\":\"hepta.learning-artifactd.metrics.v1\",",
                "\"requestsReceived\":{},\"requestsAuthenticated\":{},",
                "\"authenticationFailures\":{},\"exactReplays\":{},",
                "\"replayConflicts\":{},\"publicationsSucceeded\":{},",
                "\"publicationsFailed\":{},\"recoveryPublicationsSucceeded\":{},",
                "\"withdrawalFrontiersInstalled\":{},\"authzReloads\":{},",
                "\"backupsSucceeded\":{},\"commandFailures\":{}}}"
            ),
            self.requests_received,
            self.requests_authenticated,
            self.authentication_failures,
            self.exact_replays,
            self.replay_conflicts,
            self.publications_succeeded,
            self.publications_failed,
            self.recovery_publications_succeeded,
            self.withdrawal_frontiers_installed,
            self.authz_reloads,
            self.backups_succeeded,
            self.command_failures,
        )
    }
}

#[derive(Debug, Default)]
struct ArtifactOwnerMetricCountersV1 {
    requests_received: AtomicU64,
    requests_authenticated: AtomicU64,
    authentication_failures: AtomicU64,
    exact_replays: AtomicU64,
    replay_conflicts: AtomicU64,
    publications_succeeded: AtomicU64,
    publications_failed: AtomicU64,
    recovery_publications_succeeded: AtomicU64,
    withdrawal_frontiers_installed: AtomicU64,
    authz_reloads: AtomicU64,
    backups_succeeded: AtomicU64,
    command_failures: AtomicU64,
}

impl ArtifactOwnerMetricCountersV1 {
    fn snapshot(&self) -> ArtifactOwnerMetricsV1 {
        ArtifactOwnerMetricsV1 {
            requests_received: self.requests_received.load(Ordering::Relaxed),
            requests_authenticated: self.requests_authenticated.load(Ordering::Relaxed),
            authentication_failures: self.authentication_failures.load(Ordering::Relaxed),
            exact_replays: self.exact_replays.load(Ordering::Relaxed),
            replay_conflicts: self.replay_conflicts.load(Ordering::Relaxed),
            publications_succeeded: self.publications_succeeded.load(Ordering::Relaxed),
            publications_failed: self.publications_failed.load(Ordering::Relaxed),
            recovery_publications_succeeded: self
                .recovery_publications_succeeded
                .load(Ordering::Relaxed),
            withdrawal_frontiers_installed: self
                .withdrawal_frontiers_installed
                .load(Ordering::Relaxed),
            authz_reloads: self.authz_reloads.load(Ordering::Relaxed),
            backups_succeeded: self.backups_succeeded.load(Ordering::Relaxed),
            command_failures: self.command_failures.load(Ordering::Relaxed),
        }
    }
}

pub struct LearningArtifactReferenceHostV1 {
    service: Mutex<LearningArtifactOwnerService>,
    keyrings: RwLock<Vec<ArtifactOwnerKeyringV1>>,
    authz_path: PathBuf,
    backup_root: PathBuf,
    store: Arc<dyn OwnerDurableStoreV1>,
    journal: OwnerRequestJournalV1,
    phase: Mutex<ArtifactOwnerRuntimePhaseV1>,
    started_at: u64,
    trust_digest: Digest32,
    metrics: ArtifactOwnerMetricCountersV1,
    shutdown_requested: AtomicBool,
}

impl fmt::Debug for LearningArtifactReferenceHostV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LearningArtifactReferenceHostV1")
            .field("root", &self.store.root())
            .field("authz_path", &self.authz_path)
            .field("backup_root", &self.backup_root)
            .field("started_at", &self.started_at)
            .field("trust_digest", &self.trust_digest)
            .finish_non_exhaustive()
    }
}

impl LearningArtifactReferenceHostV1 {
    pub fn open(bootstrap: ArtifactOwnerBootstrapV1) -> Result<Self, ArtifactOwnerCommandError> {
        let root = bootstrap.runtime.service.root.clone();
        let started_at = bootstrap.runtime.service.now;
        let withdrawal_head = bootstrap.runtime.service.withdrawal_registry.head_digest();
        let trust_digest = ArtifactOwnerVerifierV1::new(bootstrap.runtime.service.trust.clone())
            .map_err(|error| ArtifactOwnerCommandError::Owner(error.to_string()))?
            .trust_digest();
        let store: Arc<dyn OwnerDurableStoreV1> =
            Arc::new(FsOwnerDurableStoreV1::open(&root)?);
        let initial = ArtifactOwnerRuntimeStatusV1 {
            phase: ArtifactOwnerRuntimePhaseV1::Starting,
            process_id: std::process::id(),
            started_at,
            observed_at: started_at,
            keyring_generation: bootstrap.keyring.generation(),
            keyring_digest: bootstrap.keyring.digest(),
            trust_digest,
            registry_head_digest: Digest32::ZERO,
            withdrawal_head_digest: withdrawal_head,
            recovery_operation_id: None,
            detail: "opening fenced owner and replaying durable state".to_owned(),
        };
        initial.persist(store.as_ref())?;

        let service = match LearningArtifactOwnerService::open(bootstrap.runtime.service) {
            Ok(service) => service,
            Err(error) => {
                let failed = ArtifactOwnerRuntimeStatusV1 {
                    phase: ArtifactOwnerRuntimePhaseV1::Failed,
                    detail: "owner open or recovery failed".to_owned(),
                    ..initial
                };
                let _ = failed.persist(store.as_ref());
                return Err(ArtifactOwnerCommandError::Service(error));
            }
        };
        let phase = if service.recovery_required().is_some() {
            ArtifactOwnerRuntimePhaseV1::Recovering
        } else {
            ArtifactOwnerRuntimePhaseV1::Ready
        };
        let value = Self {
            service: Mutex::new(service),
            keyrings: RwLock::new(vec![bootstrap.keyring]),
            authz_path: bootstrap.runtime.authz_path,
            backup_root: bootstrap.runtime.backup_root,
            journal: OwnerRequestJournalV1::new(Arc::clone(&store)),
            store,
            phase: Mutex::new(phase),
            started_at,
            trust_digest,
            metrics: ArtifactOwnerMetricCountersV1::default(),
            shutdown_requested: AtomicBool::new(false),
        };
        value.persist_status(started_at, "startup recovery complete or explicitly fenced")?;
        Ok(value)
    }

    pub fn handle(
        &self,
        request: SignedArtifactOwnerRequestV1,
        now: u64,
    ) -> Result<ArtifactOwnerCommandResultV1, ArtifactOwnerCommandError> {
        self.metrics.requests_received.fetch_add(1, Ordering::Relaxed);
        let verified = match self.verify_request(&request, now) {
            Ok(verified) => verified,
            Err(error) => {
                self.metrics
                    .authentication_failures
                    .fetch_add(1, Ordering::Relaxed);
                return Err(ArtifactOwnerCommandError::Capability(error));
            }
        };
        self.metrics
            .requests_authenticated
            .fetch_add(1, Ordering::Relaxed);
        let disposition = match self.journal.prepare(
            &verified.request.request_id,
            verified.request_digest,
            &verified.request.client_id,
            verified.request.action.as_str(),
        ) {
            Ok(value) => value,
            Err(OwnerJournalError::ReplayConflict) => {
                self.metrics
                    .replay_conflicts
                    .fetch_add(1, Ordering::Relaxed);
                return Err(ArtifactOwnerCommandError::Journal(
                    OwnerJournalError::ReplayConflict,
                ));
            }
            Err(error) => return Err(error.into()),
        };
        if let OwnerRequestDispositionV1::ReturnStored(response) = disposition {
            self.metrics.exact_replays.fetch_add(1, Ordering::Relaxed);
            return Ok(ArtifactOwnerCommandResultV1 {
                should_shutdown: response_requests_shutdown(&response),
                response,
                replayed: true,
            });
        }

        let execution = self.execute(&verified.request, now);
        let (response, outcome, should_shutdown) = match execution {
            Ok(value) => (value.response, "success", value.should_shutdown),
            Err(error) => {
                self.metrics.command_failures.fetch_add(1, Ordering::Relaxed);
                (
                    error_response(error.code(), &error.to_string()).into_bytes(),
                    "error",
                    false,
                )
            }
        };
        let response = self.journal.complete(
            &verified.request.request_id,
            verified.request_digest,
            &response,
        )?;
        self.journal.record_audit(
            &verified.request.request_id,
            verified.request_digest,
            &verified.request.client_id,
            verified.request.action.as_str(),
            outcome,
            now,
            &response,
        )?;
        Ok(ArtifactOwnerCommandResultV1 {
            response,
            should_shutdown,
            replayed: false,
        })
    }

    #[must_use]
    pub fn shutdown_requested(&self) -> bool {
        self.shutdown_requested.load(Ordering::Acquire)
    }

    pub fn mark_stopped(&self, now: u64) -> Result<(), ArtifactOwnerCommandError> {
        *self
            .phase
            .lock()
            .map_err(|_| ArtifactOwnerCommandError::Poisoned)? =
            ArtifactOwnerRuntimePhaseV1::Stopped;
        self.persist_status(now, "listener stopped and writer fence is being released")
    }

    #[must_use]
    pub fn metrics(&self) -> ArtifactOwnerMetricsV1 {
        self.metrics.snapshot()
    }

    pub fn status(
        &self,
        now: u64,
        detail: impl Into<String>,
    ) -> Result<ArtifactOwnerRuntimeStatusV1, ArtifactOwnerCommandError> {
        let phase = *self
            .phase
            .lock()
            .map_err(|_| ArtifactOwnerCommandError::Poisoned)?;
        let keyrings = self
            .keyrings
            .read()
            .map_err(|_| ArtifactOwnerCommandError::Poisoned)?;
        let keyring = keyrings
            .last()
            .ok_or(ArtifactOwnerCommandError::InvalidState)?;
        let service = self
            .service
            .lock()
            .map_err(|_| ArtifactOwnerCommandError::Poisoned)?;
        Ok(ArtifactOwnerRuntimeStatusV1 {
            phase,
            process_id: std::process::id(),
            started_at: self.started_at,
            observed_at: now,
            keyring_generation: keyring.generation(),
            keyring_digest: keyring.digest(),
            trust_digest: self.trust_digest,
            registry_head_digest: service.registry().snapshot().head_digest,
            withdrawal_head_digest: service.withdrawal_registry().head_digest(),
            recovery_operation_id: service.recovery_required().cloned(),
            detail: detail.into(),
        })
    }

    fn verify_request(
        &self,
        request: &SignedArtifactOwnerRequestV1,
        now: u64,
    ) -> Result<super::capability_validation::VerifiedArtifactOwnerRequestV1, ArtifactOwnerCapabilityError>
    {
        let keyrings = self
            .keyrings
            .read()
            .map_err(|_| ArtifactOwnerCapabilityError::InvalidKeyring)?;
        let keyring = keyrings
            .iter()
            .find(|keyring| keyring.generation() == request.keyring_generation)
            .ok_or(ArtifactOwnerCapabilityError::InvalidKeyring)?;
        keyring.verify(request, now)
    }

    fn execute(
        &self,
        request: &SignedArtifactOwnerRequestV1,
        now: u64,
    ) -> Result<ExecutionResultV1, ArtifactOwnerCommandError> {
        match request.action {
            ArtifactOwnerActionV1::Health => {
                require_empty_payload(&request.payload)?;
                let status = self.status(now, "authenticated liveness probe")?;
                Ok(ExecutionResultV1::json(
                    format!(
                        "{{\"schema\":\"hepta.learning-artifactd.health.v1\",\"live\":{},\"phase\":\"{}\"}}",
                        status.phase.is_live(),
                        status.phase.as_str()
                    ),
                    false,
                ))
            }
            ArtifactOwnerActionV1::Ready => {
                require_empty_payload(&request.payload)?;
                let status = self.status(now, "authenticated readiness probe")?;
                Ok(ExecutionResultV1::json(
                    format!(
                        "{{\"schema\":\"hepta.learning-artifactd.ready.v1\",\"ready\":{},\"phase\":\"{}\"}}",
                        status.phase.is_ready(),
                        status.phase.as_str()
                    ),
                    false,
                ))
            }
            ArtifactOwnerActionV1::Status => {
                require_empty_payload(&request.payload)?;
                Ok(ExecutionResultV1::json(
                    self.status(now, "authenticated status request")?
                        .response_json(),
                    false,
                ))
            }
            ArtifactOwnerActionV1::Metrics => {
                require_empty_payload(&request.payload)?;
                Ok(ExecutionResultV1::json(
                    self.metrics().response_json(),
                    false,
                ))
            }
            ArtifactOwnerActionV1::Publish => self.execute_publish(request, now, false),
            ArtifactOwnerActionV1::RecoverPublish => self.execute_publish(request, now, true),
            ArtifactOwnerActionV1::InstallWithdrawalFrontier => {
                self.execute_install_withdrawal(&request.payload, now)
            }
            ArtifactOwnerActionV1::ReloadAuthz => self.execute_reload_authz(&request.payload, now),
            ArtifactOwnerActionV1::Backup => {
                require_empty_payload(&request.payload)?;
                let receipt = backup_owner_root_v1(
                    self.store.root(),
                    &self.backup_root,
                    request.request_id.clone(),
                )?;
                self.metrics
                    .backups_succeeded
                    .fetch_add(1, Ordering::Relaxed);
                Ok(ExecutionResultV1::json(backup_response(&receipt), false))
            }
            ArtifactOwnerActionV1::Shutdown => {
                require_empty_payload(&request.payload)?;
                *self
                    .phase
                    .lock()
                    .map_err(|_| ArtifactOwnerCommandError::Poisoned)? =
                    ArtifactOwnerRuntimePhaseV1::Draining;
                self.shutdown_requested.store(true, Ordering::Release);
                self.persist_status(now, "authenticated graceful shutdown requested")?;
                Ok(ExecutionResultV1::json(
                    "{\"schema\":\"hepta.learning-artifactd.shutdown.v1\",\"accepted\":true}"
                        .to_owned(),
                    true,
                ))
            }
        }
    }

    fn execute_publish(
        &self,
        request: &SignedArtifactOwnerRequestV1,
        now: u64,
        recovery: bool,
    ) -> Result<ExecutionResultV1, ArtifactOwnerCommandError> {
        let command = PublishArtifactCommandV1::decode(&request.payload)?;
        if command.now != request.issued_at {
            return Err(ArtifactOwnerCommandError::RequestTimeMismatch);
        }
        let phase = *self
            .phase
            .lock()
            .map_err(|_| ArtifactOwnerCommandError::Poisoned)?;
        if recovery && phase != ArtifactOwnerRuntimePhaseV1::Recovering {
            return Err(ArtifactOwnerCommandError::RecoveryNotRequired);
        }
        if !recovery && phase != ArtifactOwnerRuntimePhaseV1::Ready {
            return Err(ArtifactOwnerCommandError::NotReady);
        }
        let mut service = self
            .service
            .lock()
            .map_err(|_| ArtifactOwnerCommandError::Poisoned)?;
        if recovery
            && service.recovery_required() != Some(&command.operation_id)
        {
            return Err(ArtifactOwnerCommandError::RecoveryOperationMismatch);
        }
        let admission = admit_manifest_at_withdrawal_head_v3(
            service.withdrawal_registry(),
            command.expected_withdrawal_head,
            command.manifest.manifest,
            now,
        )?;
        let result = service.publish_durable(LearningArtifactPublishRequestV1 {
            operation_id: command.operation_id,
            admission,
            payload: command.payload,
            signed_current_head: command.signed_current_head,
            expected_registry_predecessor_head: command.expected_registry_predecessor_head,
            now,
        });
        match result {
            Ok(receipt) => {
                let now_ready = service.recovery_required().is_none();
                drop(service);
                if now_ready {
                    *self
                        .phase
                        .lock()
                        .map_err(|_| ArtifactOwnerCommandError::Poisoned)? =
                        ArtifactOwnerRuntimePhaseV1::Ready;
                }
                self.metrics
                    .publications_succeeded
                    .fetch_add(1, Ordering::Relaxed);
                if recovery {
                    self.metrics
                        .recovery_publications_succeeded
                        .fetch_add(1, Ordering::Relaxed);
                }
                self.persist_status(now, "publication acknowledged and current head advanced")?;
                let publication = receipt.publication();
                Ok(ExecutionResultV1::json(
                    format!(
                        concat!(
                            "{{\"schema\":\"hepta.learning-artifactd.publication.v1\",",
                            "\"operationId\":\"{}\",\"admissionDigest\":\"{}\",",
                            "\"registryHeadDigest\":\"{}\",\"witnessDigest\":\"{}\",",
                            "\"stateDigest\":\"{}\",\"acknowledgedAt\":{},",
                            "\"durableCommitDigest\":\"{}\",",
                            "\"publicationCapabilityDigest\":\"{}\",",
                            "\"writerLeaseGeneration\":{},\"registryGeneration\":{},",
                            "\"withdrawalHeadDigest\":\"{}\",\"routeHeadDigest\":\"{}\"}}"
                        ),
                        publication.operation_id,
                        publication.admission_digest,
                        publication.registry_head_digest,
                        publication.witness_digest,
                        publication.state_digest,
                        publication.acknowledged_at,
                        receipt.receipt_digest(),
                        receipt.capability_digest(),
                        receipt.writer_lease_generation(),
                        receipt.registry_generation().get(),
                        receipt.withdrawal_head_digest(),
                        receipt.route_head_digest(),
                    ),
                    false,
                ))
            }
            Err(error) => {
                let requires_recovery = service.recovery_required().is_some();
                drop(service);
                self.metrics
                    .publications_failed
                    .fetch_add(1, Ordering::Relaxed);
                if requires_recovery {
                    *self
                        .phase
                        .lock()
                        .map_err(|_| ArtifactOwnerCommandError::Poisoned)? =
                        ArtifactOwnerRuntimePhaseV1::Recovering;
                    self.persist_status(now, "publication failed after a durable phase; exact recovery required")?;
                }
                Err(ArtifactOwnerCommandError::Service(error))
            }
        }
    }

    fn execute_install_withdrawal(
        &self,
        payload: &[u8],
        now: u64,
    ) -> Result<ExecutionResultV1, ArtifactOwnerCommandError> {
        let command = InstallWithdrawalSnapshotCommandV1::decode(payload)?;
        let metadata = fs::symlink_metadata(&command.snapshot_path)?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(ArtifactOwnerCommandError::SnapshotPath);
        }
        let registry = read_dataset_withdrawal_snapshot(
            File::open(command.snapshot_path)?,
            command.receipt,
        )?;
        let head = registry.head_digest();
        self.service
            .lock()
            .map_err(|_| ArtifactOwnerCommandError::Poisoned)?
            .install_withdrawal_frontier(registry)?;
        self.metrics
            .withdrawal_frontiers_installed
            .fetch_add(1, Ordering::Relaxed);
        self.persist_status(now, "authenticated withdrawal frontier installed")?;
        Ok(ExecutionResultV1::json(
            format!(
                "{{\"schema\":\"hepta.learning-artifactd.withdrawal-frontier.v1\",\"headDigest\":\"{head}\"}}"
            ),
            false,
        ))
    }

    fn execute_reload_authz(
        &self,
        payload: &[u8],
        now: u64,
    ) -> Result<ExecutionResultV1, ArtifactOwnerCommandError> {
        require_empty_payload(payload)?;
        let next = load_keyring(&self.authz_path)?;
        let mut keyrings = self
            .keyrings
            .write()
            .map_err(|_| ArtifactOwnerCommandError::Poisoned)?;
        let current = keyrings
            .last()
            .ok_or(ArtifactOwnerCommandError::InvalidState)?;
        if next.generation() <= current.generation() {
            return Err(ArtifactOwnerCommandError::KeyringRollback);
        }
        keyrings.push(next);
        if keyrings.len() > 2 {
            keyrings.remove(0);
        }
        let generation = keyrings
            .last()
            .ok_or(ArtifactOwnerCommandError::InvalidState)?
            .generation();
        drop(keyrings);
        #[cfg(all(test, unix))]
        test_process_crash_barrier("authz-after-install-before-ack");
        self.metrics.authz_reloads.fetch_add(1, Ordering::Relaxed);
        self.persist_status(now, "new authenticated transport keyring generation loaded")?;
        Ok(ExecutionResultV1::json(
            format!(
                "{{\"schema\":\"hepta.learning-artifactd.authz-reload.v1\",\"generation\":{generation}}}"
            ),
            false,
        ))
    }

    fn persist_status(
        &self,
        now: u64,
        detail: &str,
    ) -> Result<(), ArtifactOwnerCommandError> {
        self.status(now, detail)?.persist(self.store.as_ref())?;
        Ok(())
    }
}

#[cfg(all(test, unix))]
fn test_process_crash_barrier(stage: &str) {
    use std::io::Write as _;
    use std::time::Duration;

    if std::env::var("HEPTA_ARTIFACT_HOST_CRASH_CUT").ok().as_deref() != Some(stage) {
        return;
    }
    let marker = std::env::var_os("HEPTA_ARTIFACT_HOST_CRASH_MARKER")
        .map(PathBuf::from)
        .expect("test host crash marker");
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&marker)
        .expect("create test host crash marker");
    file.write_all(stage.as_bytes())
        .and_then(|()| file.sync_all())
        .expect("sync test host crash marker");
    if let Some(parent) = marker.parent() {
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .expect("sync test host crash marker directory");
    }
    loop {
        std::thread::sleep(Duration::from_secs(1));
    }
}

struct ExecutionResultV1 {
    response: Vec<u8>,
    should_shutdown: bool,
}

impl ExecutionResultV1 {
    fn json(value: String, should_shutdown: bool) -> Self {
        let mut response = value.into_bytes();
        response.push(b'\n');
        Self {
            response,
            should_shutdown,
        }
    }
}

fn require_empty_payload(payload: &[u8]) -> Result<(), ArtifactOwnerCommandError> {
    if payload.is_empty() {
        Ok(())
    } else {
        Err(ArtifactOwnerCommandError::UnexpectedPayload)
    }
}

fn backup_response(receipt: &ArtifactOwnerBackupReceiptV1) -> String {
    format!(
        concat!(
            "{{\"schema\":\"hepta.learning-artifactd.backup.v1\",",
            "\"backupId\":\"{}\",\"manifestDigest\":\"{}\",",
            "\"fileCount\":{},\"totalBytes\":{}}}"
        ),
        receipt.backup_id,
        receipt.manifest_digest,
        receipt.file_count,
        receipt.total_bytes,
    )
}

fn response_requests_shutdown(response: &[u8]) -> bool {
    response.windows(b"\"accepted\":true".len()).any(|window| {
        window == b"\"accepted\":true"
    }) && response.windows(b"shutdown.v1".len()).any(|window| {
        window == b"shutdown.v1"
    })
}

fn error_response(code: &str, detail: &str) -> String {
    format!(
        "{{\"schema\":\"hepta.learning-artifactd.error.v1\",\"code\":\"{}\",\"detail\":\"{}\"}}\n",
        escape_json(code),
        escape_json(detail)
    )
}

fn escape_json(value: &str) -> String {
    let mut output = String::with_capacity(value.len());
    for character in value.chars() {
        match character {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            character if character.is_control() => output.push('?'),
            character => output.push(character),
        }
    }
    output
}

#[derive(Debug)]
pub enum ArtifactOwnerCommandError {
    Config(super::ArtifactOwnerConfigError),
    Capability(ArtifactOwnerCapabilityError),
    Journal(OwnerJournalError),
    Decode(ArtifactOwnerCommandDecodeError),
    Service(LearningArtifactOwnerServiceError),
    Admission(crate::ArtifactAdmissionError),
    Storage(crate::ArtifactStorageError),
    Reconciliation(ArtifactOwnerReconciliationError),
    Status(ArtifactOwnerStatusError),
    Io(std::io::Error),
    Owner(String),
    Poisoned,
    InvalidState,
    NotReady,
    RecoveryNotRequired,
    RecoveryOperationMismatch,
    RequestTimeMismatch,
    UnexpectedPayload,
    SnapshotPath,
    KeyringRollback,
}

impl ArtifactOwnerCommandError {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::Config(_) => "config",
            Self::Capability(_) => "unauthorized",
            Self::Journal(OwnerJournalError::ReplayConflict) => "replay_conflict",
            Self::Journal(_) => "request_journal",
            Self::Decode(_) => "invalid_command",
            Self::Service(_) => "owner_service",
            Self::Admission(_) => "admission",
            Self::Storage(_) => "storage",
            Self::Reconciliation(_) => "reconciliation",
            Self::Status(_) => "status",
            Self::Io(_) => "io",
            Self::Owner(_) => "owner",
            Self::Poisoned => "poisoned",
            Self::InvalidState => "invalid_state",
            Self::NotReady => "not_ready",
            Self::RecoveryNotRequired => "recovery_not_required",
            Self::RecoveryOperationMismatch => "recovery_operation_mismatch",
            Self::RequestTimeMismatch => "request_time_mismatch",
            Self::UnexpectedPayload => "unexpected_payload",
            Self::SnapshotPath => "snapshot_path",
            Self::KeyringRollback => "keyring_rollback",
        }
    }
}

impl fmt::Display for ArtifactOwnerCommandError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactOwnerCommandError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Config(error) => Some(error),
            Self::Capability(error) => Some(error),
            Self::Journal(error) => Some(error),
            Self::Decode(error) => Some(error),
            Self::Service(error) => Some(error),
            Self::Admission(error) => Some(error),
            Self::Storage(error) => Some(error),
            Self::Reconciliation(error) => Some(error),
            Self::Status(error) => Some(error),
            Self::Io(error) => Some(error),
            Self::Owner(_)
            | Self::Poisoned
            | Self::InvalidState
            | Self::NotReady
            | Self::RecoveryNotRequired
            | Self::RecoveryOperationMismatch
            | Self::RequestTimeMismatch
            | Self::UnexpectedPayload
            | Self::SnapshotPath
            | Self::KeyringRollback => None,
        }
    }
}

impl From<super::ArtifactOwnerConfigError> for ArtifactOwnerCommandError {
    fn from(value: super::ArtifactOwnerConfigError) -> Self {
        Self::Config(value)
    }
}

impl From<ArtifactOwnerCapabilityError> for ArtifactOwnerCommandError {
    fn from(value: ArtifactOwnerCapabilityError) -> Self {
        Self::Capability(value)
    }
}

impl From<OwnerJournalError> for ArtifactOwnerCommandError {
    fn from(value: OwnerJournalError) -> Self {
        Self::Journal(value)
    }
}

impl From<ArtifactOwnerCommandDecodeError> for ArtifactOwnerCommandError {
    fn from(value: ArtifactOwnerCommandDecodeError) -> Self {
        Self::Decode(value)
    }
}

impl From<LearningArtifactOwnerServiceError> for ArtifactOwnerCommandError {
    fn from(value: LearningArtifactOwnerServiceError) -> Self {
        Self::Service(value)
    }
}

impl From<crate::ArtifactAdmissionError> for ArtifactOwnerCommandError {
    fn from(value: crate::ArtifactAdmissionError) -> Self {
        Self::Admission(value)
    }
}

impl From<crate::ArtifactStorageError> for ArtifactOwnerCommandError {
    fn from(value: crate::ArtifactStorageError) -> Self {
        Self::Storage(value)
    }
}

impl From<ArtifactOwnerReconciliationError> for ArtifactOwnerCommandError {
    fn from(value: ArtifactOwnerReconciliationError) -> Self {
        Self::Reconciliation(value)
    }
}

impl From<ArtifactOwnerStatusError> for ArtifactOwnerCommandError {
    fn from(value: ArtifactOwnerStatusError) -> Self {
        Self::Status(value)
    }
}

impl From<std::io::Error> for ArtifactOwnerCommandError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}
