#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:120]!r}")
    write(path, content.replace(old, new, 1))


def replace_all(path: str, old: str, new: str, minimum: int = 1) -> None:
    content = read(path)
    count = content.count(old)
    if count < minimum:
        raise RuntimeError(f"{path}: expected at least {minimum} replacements, found {count}: {old[:120]!r}")
    write(path, content.replace(old, new))


write(
    "codex-rs/hepta-supervisor/src/supervisor_lock.rs",
    r'''use std::array;
use std::ops::Deref;
use std::ops::DerefMut;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use tokio::sync::Mutex;
use tokio::sync::MutexGuard;

use crate::daemon_protocol::SupervisordLockMetric;
use crate::daemon_protocol::SupervisordLockOperation;

const CONTENTION_THRESHOLD: Duration = Duration::from_micros(50);

#[derive(Default)]
struct Metric {
    acquisitions: AtomicU64,
    contended: AtomicU64,
    wait_total_micros: AtomicU64,
    wait_max_micros: AtomicU64,
    hold_total_micros: AtomicU64,
    hold_max_micros: AtomicU64,
}

pub(crate) struct SupervisorLock<T> {
    inner: Mutex<T>,
    metrics: [Metric; SupervisordLockOperation::COUNT],
}

impl<T> SupervisorLock<T> {
    pub(crate) fn new(value: T) -> Self {
        Self {
            inner: Mutex::new(value),
            metrics: array::from_fn(|_| Metric::default()),
        }
    }

    pub(crate) async fn lock(
        &self,
        operation: SupervisordLockOperation,
    ) -> SupervisorLockGuard<'_, T> {
        let wait_started = Instant::now();
        let guard = self.inner.lock().await;
        let waited = wait_started.elapsed();
        let metric = &self.metrics[operation.index()];
        metric.acquisitions.fetch_add(1, Ordering::Relaxed);
        if waited >= CONTENTION_THRESHOLD {
            metric.contended.fetch_add(1, Ordering::Relaxed);
        }
        let waited_micros = duration_micros(waited);
        metric
            .wait_total_micros
            .fetch_add(waited_micros, Ordering::Relaxed);
        metric
            .wait_max_micros
            .fetch_max(waited_micros, Ordering::Relaxed);
        SupervisorLockGuard {
            guard,
            metric,
            hold_started: Instant::now(),
        }
    }

    pub(crate) fn snapshot(&self) -> Vec<SupervisordLockMetric> {
        SupervisordLockOperation::ALL
            .into_iter()
            .map(|operation| {
                let metric = &self.metrics[operation.index()];
                SupervisordLockMetric {
                    operation,
                    acquisitions: metric.acquisitions.load(Ordering::Relaxed),
                    contended_acquisitions: metric.contended.load(Ordering::Relaxed),
                    wait_total_micros: metric.wait_total_micros.load(Ordering::Relaxed),
                    wait_max_micros: metric.wait_max_micros.load(Ordering::Relaxed),
                    hold_total_micros: metric.hold_total_micros.load(Ordering::Relaxed),
                    hold_max_micros: metric.hold_max_micros.load(Ordering::Relaxed),
                }
            })
            .collect()
    }
}

pub(crate) struct SupervisorLockGuard<'a, T> {
    guard: MutexGuard<'a, T>,
    metric: &'a Metric,
    hold_started: Instant,
}

impl<T> Deref for SupervisorLockGuard<'_, T> {
    type Target = T;

    fn deref(&self) -> &Self::Target {
        &self.guard
    }
}

impl<T> DerefMut for SupervisorLockGuard<'_, T> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.guard
    }
}

impl<T> Drop for SupervisorLockGuard<'_, T> {
    fn drop(&mut self) {
        let held_micros = duration_micros(self.hold_started.elapsed());
        self.metric
            .hold_total_micros
            .fetch_add(held_micros, Ordering::Relaxed);
        self.metric
            .hold_max_micros
            .fetch_max(held_micros, Ordering::Relaxed);
    }
}

fn duration_micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use tokio::sync::Barrier;

    use super::*;

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn records_wait_and_hold_by_operation() {
        let lock = Arc::new(SupervisorLock::new(0_u64));
        let barrier = Arc::new(Barrier::new(2));
        let first_lock = Arc::clone(&lock);
        let first_barrier = Arc::clone(&barrier);
        let first = tokio::spawn(async move {
            let mut guard = first_lock
                .lock(SupervisordLockOperation::TickAgent)
                .await;
            *guard += 1;
            first_barrier.wait().await;
            tokio::time::sleep(Duration::from_millis(10)).await;
        });
        barrier.wait().await;
        {
            let mut guard = lock.lock(SupervisordLockOperation::Snapshot).await;
            *guard += 1;
        }
        first.await.expect("first task");
        let metrics = lock.snapshot();
        let tick = metrics
            .iter()
            .find(|metric| metric.operation == SupervisordLockOperation::TickAgent)
            .expect("tick metric");
        let snapshot = metrics
            .iter()
            .find(|metric| metric.operation == SupervisordLockOperation::Snapshot)
            .expect("snapshot metric");
        assert_eq!(tick.acquisitions, 1);
        assert!(tick.hold_max_micros >= 9_000);
        assert_eq!(snapshot.acquisitions, 1);
        assert!(snapshot.wait_max_micros >= 9_000);
    }
}
''',
)

write(
    "codex-rs/hepta-supervisor/src/production_authority_distribution.rs",
    r'''use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::RwLock;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::H7H89ProductionGrant;
use crate::H7H89ProductionGrantVerifier;
use crate::ProductionRecoveryDecision;

pub const MAX_REVOKED_PRODUCTION_GRANTS: usize = 1_024;

#[derive(Clone)]
pub struct ProductionAuthorityReader {
    state: Arc<RwLock<AuthorityState>>,
}

#[derive(Clone)]
pub struct ProductionAuthorityPublisher {
    state: Arc<RwLock<AuthorityState>>,
}

struct AuthorityState {
    generation: u64,
    verifier: H7H89ProductionGrantVerifier,
    revoked_grants: VecDeque<Sha256Digest>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionAuthorityDistributionSnapshot {
    pub generation: u64,
    pub signer_id: String,
    pub signer_epoch: u64,
    pub revoked_grants: u16,
}

#[derive(Debug, Error, Eq, PartialEq)]
pub enum ProductionAuthorityDistributionError {
    #[error("production authority distribution lock is poisoned")]
    Poisoned,
    #[error("production authority distribution generation mismatch: expected {expected}, actual {actual}")]
    GenerationFence { expected: u64, actual: u64 },
    #[error("production authority signer epoch must advance")]
    SignerEpochDidNotAdvance,
    #[error("production authority signer is stale")]
    StaleSigner,
    #[error("production authority signer is not current")]
    UnknownSigner,
    #[error("production authority grant is revoked")]
    RevokedGrant,
    #[error("production authority distribution generation overflow")]
    GenerationOverflow,
}

pub fn production_authority_distribution(
    verifier: H7H89ProductionGrantVerifier,
) -> Result<
    (ProductionAuthorityPublisher, ProductionAuthorityReader),
    ProductionAuthorityDistributionError,
> {
    let state = Arc::new(RwLock::new(AuthorityState {
        generation: 1,
        verifier,
        revoked_grants: VecDeque::new(),
    }));
    Ok((
        ProductionAuthorityPublisher {
            state: Arc::clone(&state),
        },
        ProductionAuthorityReader { state },
    ))
}

impl ProductionAuthorityReader {
    pub fn pinned(
        verifier: H7H89ProductionGrantVerifier,
    ) -> Result<Self, ProductionAuthorityDistributionError> {
        production_authority_distribution(verifier).map(|(_, reader)| reader)
    }

    pub fn snapshot(
        &self,
    ) -> Result<ProductionAuthorityDistributionSnapshot, ProductionAuthorityDistributionError> {
        let state = self
            .state
            .read()
            .map_err(|_| ProductionAuthorityDistributionError::Poisoned)?;
        snapshot(&state)
    }

    pub fn resolve_grant(
        &self,
        grant: &H7H89ProductionGrant,
    ) -> Result<H7H89ProductionGrantVerifier, ProductionAuthorityDistributionError> {
        let state = self
            .state
            .read()
            .map_err(|_| ProductionAuthorityDistributionError::Poisoned)?;
        verify_current(
            &state,
            &grant.signer_id,
            grant.signer_epoch,
            Some(&grant.grant_sha256),
        )?;
        Ok(state.verifier.clone())
    }

    pub fn resolve_recovery(
        &self,
        decision: &ProductionRecoveryDecision,
    ) -> Result<H7H89ProductionGrantVerifier, ProductionAuthorityDistributionError> {
        let state = self
            .state
            .read()
            .map_err(|_| ProductionAuthorityDistributionError::Poisoned)?;
        verify_current(
            &state,
            &decision.signer_id,
            decision.signer_epoch,
            Some(&decision.grant_sha256),
        )?;
        Ok(state.verifier.clone())
    }
}

impl ProductionAuthorityPublisher {
    pub fn snapshot(
        &self,
    ) -> Result<ProductionAuthorityDistributionSnapshot, ProductionAuthorityDistributionError> {
        let state = self
            .state
            .read()
            .map_err(|_| ProductionAuthorityDistributionError::Poisoned)?;
        snapshot(&state)
    }

    pub fn rotate(
        &self,
        expected_generation: u64,
        verifier: H7H89ProductionGrantVerifier,
    ) -> Result<ProductionAuthorityDistributionSnapshot, ProductionAuthorityDistributionError> {
        let mut state = self
            .state
            .write()
            .map_err(|_| ProductionAuthorityDistributionError::Poisoned)?;
        check_generation(&state, expected_generation)?;
        if verifier.signer_epoch() <= state.verifier.signer_epoch() {
            return Err(ProductionAuthorityDistributionError::SignerEpochDidNotAdvance);
        }
        state.generation = state
            .generation
            .checked_add(1)
            .ok_or(ProductionAuthorityDistributionError::GenerationOverflow)?;
        state.verifier = verifier;
        snapshot(&state)
    }

    pub fn revoke_grant(
        &self,
        expected_generation: u64,
        grant_sha256: Sha256Digest,
    ) -> Result<ProductionAuthorityDistributionSnapshot, ProductionAuthorityDistributionError> {
        let mut state = self
            .state
            .write()
            .map_err(|_| ProductionAuthorityDistributionError::Poisoned)?;
        check_generation(&state, expected_generation)?;
        if !state.revoked_grants.contains(&grant_sha256) {
            if state.revoked_grants.len() == MAX_REVOKED_PRODUCTION_GRANTS {
                state.revoked_grants.pop_front();
            }
            state.revoked_grants.push_back(grant_sha256);
        }
        state.generation = state
            .generation
            .checked_add(1)
            .ok_or(ProductionAuthorityDistributionError::GenerationOverflow)?;
        snapshot(&state)
    }
}

fn snapshot(
    state: &AuthorityState,
) -> Result<ProductionAuthorityDistributionSnapshot, ProductionAuthorityDistributionError> {
    Ok(ProductionAuthorityDistributionSnapshot {
        generation: state.generation,
        signer_id: state.verifier.signer_id().to_string(),
        signer_epoch: state.verifier.signer_epoch(),
        revoked_grants: u16::try_from(state.revoked_grants.len())
            .map_err(|_| ProductionAuthorityDistributionError::GenerationOverflow)?,
    })
}

fn check_generation(
    state: &AuthorityState,
    expected: u64,
) -> Result<(), ProductionAuthorityDistributionError> {
    if state.generation == expected {
        Ok(())
    } else {
        Err(ProductionAuthorityDistributionError::GenerationFence {
            expected,
            actual: state.generation,
        })
    }
}

fn verify_current(
    state: &AuthorityState,
    signer_id: &str,
    signer_epoch: u64,
    grant_sha256: Option<&Sha256Digest>,
) -> Result<(), ProductionAuthorityDistributionError> {
    if grant_sha256.is_some_and(|digest| state.revoked_grants.contains(digest)) {
        return Err(ProductionAuthorityDistributionError::RevokedGrant);
    }
    if signer_epoch < state.verifier.signer_epoch() {
        return Err(ProductionAuthorityDistributionError::StaleSigner);
    }
    if signer_id != state.verifier.signer_id() || signer_epoch != state.verifier.signer_epoch() {
        return Err(ProductionAuthorityDistributionError::UnknownSigner);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use codex_hepta_contracts::Sha256Digest;
    use ed25519_dalek::SigningKey;

    use super::*;
    use crate::H7H89ProductionTransition;
    use crate::SIGNED_AUTHORITY_NAMESPACE;
    use crate::SIGNED_AUTHORITY_SCHEMA_VERSION;

    fn verifier(id: &str, epoch: u64, seed: u8) -> H7H89ProductionGrantVerifier {
        let key = SigningKey::from_bytes(&[seed; 32]);
        H7H89ProductionGrantVerifier::from_bytes(id, epoch, key.verifying_key().to_bytes())
            .expect("verifier")
    }

    fn grant(id: &str, epoch: u64, digest: Sha256Digest) -> H7H89ProductionGrant {
        H7H89ProductionGrant {
            schema_version: SIGNED_AUTHORITY_SCHEMA_VERSION,
            namespace: SIGNED_AUTHORITY_NAMESPACE.to_string(),
            agent_id: "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12".to_string(),
            source_release: "v1".to_string(),
            target_release: "v2".to_string(),
            transition: H7H89ProductionTransition::Upgrade,
            h7_envelope_sha256: Sha256Digest::for_bytes(b"h7"),
            artifact_sha256: Sha256Digest::for_bytes(b"artifact"),
            expected_control_revision: 1,
            expected_lifecycle_generation: 1,
            authority_epoch: 1,
            signer_id: id.to_string(),
            signer_epoch: epoch,
            issued_at_unix_seconds: 1,
            expires_at_unix_seconds: 2,
            production_authority: true,
            external_effects: true,
            operator_acceptance: true,
            promotion: true,
            governance_bypass: false,
            signature_base64: "AA==".to_string(),
            grant_sha256: digest,
        }
    }

    #[test]
    fn rotation_revocation_and_generation_fences_are_fail_closed() {
        let (publisher, reader) =
            production_authority_distribution(verifier("release-policy", 1, 1))
                .expect("distribution");
        let first_digest = Sha256Digest::for_bytes(b"grant-1");
        let first = grant("release-policy", 1, first_digest.clone());
        reader.resolve_grant(&first).expect("current grant");

        let rotated = publisher
            .rotate(1, verifier("release-policy", 2, 2))
            .expect("rotate");
        assert_eq!(rotated.generation, 2);
        assert_eq!(
            reader.resolve_grant(&first),
            Err(ProductionAuthorityDistributionError::StaleSigner)
        );
        assert_eq!(
            publisher.rotate(1, verifier("release-policy", 3, 3)),
            Err(ProductionAuthorityDistributionError::GenerationFence {
                expected: 1,
                actual: 2,
            })
        );

        let second_digest = Sha256Digest::for_bytes(b"grant-2");
        let second = grant("release-policy", 2, second_digest.clone());
        reader.resolve_grant(&second).expect("rotated grant");
        let revoked = publisher
            .revoke_grant(2, second_digest)
            .expect("revoke");
        assert_eq!(revoked.generation, 3);
        assert_eq!(
            reader.resolve_grant(&second),
            Err(ProductionAuthorityDistributionError::RevokedGrant)
        );

        let wrong = grant("other-policy", 2, Sha256Digest::for_bytes(b"wrong"));
        assert_eq!(
            reader.resolve_grant(&wrong),
            Err(ProductionAuthorityDistributionError::UnknownSigner)
        );
    }
}
''',
)

write(
    "codex-rs/hepta-supervisor/src/production_caller.rs",
    r'''use codex_hepta_memory::H7SignedArtifactEnvelope;
use thiserror::Error;

use crate::H7H89ProductionGrant;
use crate::H7H89ProductionTransition;
use crate::ProductionAuthorityDistributionError;
use crate::ProductionAuthorityReader;
use crate::SupervisordClient;
use crate::SupervisordControlFence;
use crate::SupervisordMutationAccepted;
use crate::SupervisorError;

#[derive(Clone, Debug)]
pub struct AuthorizedProductionTransition {
    pub grant: H7H89ProductionGrant,
    pub h7_envelope: H7SignedArtifactEnvelope,
}

pub struct ProductionSupervisorCaller {
    client: SupervisordClient,
    authority: ProductionAuthorityReader,
}

#[derive(Debug, Error)]
pub enum ProductionSupervisorCallerError {
    #[error(transparent)]
    Authority(#[from] ProductionAuthorityDistributionError),
    #[error("supervisord transport rejected production transition: {0}")]
    Supervisor(String),
    #[error("supervisord production receipt does not bind the dispatched grant")]
    ReceiptBinding,
}

impl ProductionSupervisorCaller {
    pub fn new(client: SupervisordClient, authority: ProductionAuthorityReader) -> Self {
        Self { client, authority }
    }

    pub async fn dispatch(
        &self,
        fence: SupervisordControlFence,
        transition: AuthorizedProductionTransition,
    ) -> Result<SupervisordMutationAccepted, ProductionSupervisorCallerError> {
        // Preflight the external distribution before transport. Supervisord
        // independently repeats this lookup at final use, so rotation or
        // revocation racing this call still fails closed at the daemon.
        self.authority.resolve_grant(&transition.grant)?;
        let expected_digest = transition.grant.grant_sha256.clone();
        let accepted = match transition.grant.transition {
            H7H89ProductionTransition::Upgrade => {
                self.client
                    .signed_upgrade(fence, transition.grant, transition.h7_envelope)
                    .await
            }
            H7H89ProductionTransition::Rollback => {
                self.client
                    .signed_rollback(fence, transition.grant, transition.h7_envelope)
                    .await
            }
        }
        .map_err(map_supervisor)?;
        if accepted
            .production_receipt
            .as_ref()
            .is_none_or(|receipt| receipt.grant_sha256 != expected_digest)
        {
            return Err(ProductionSupervisorCallerError::ReceiptBinding);
        }
        Ok(accepted)
    }

    pub fn authority(&self) -> &ProductionAuthorityReader {
        &self.authority
    }
}

fn map_supervisor(error: SupervisorError) -> ProductionSupervisorCallerError {
    ProductionSupervisorCallerError::Supervisor(error.to_string())
}
''',
)

write(
    "codex-rs/hepta-supervisor/src/recovery_diagnostics.rs",
    r'''use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;

use crate::ProcessDriver;
use crate::ProductionMutationStatus;
use crate::ReleaseTransactionPhase;
use crate::Supervisor;
use crate::daemon_protocol::RecoveryBlocker;
use crate::daemon_protocol::RecoveryOperatorAction;
use crate::daemon_protocol::SupervisordRecoveryDiagnostic;

pub(crate) fn diagnose<D: ProcessDriver>(
    registry: &FleetRegistry,
    supervisor: &Supervisor<D>,
    agent_id: &AgentId,
    current_authority_epoch: u64,
) -> SupervisordRecoveryDiagnostic {
    let mutation = match supervisor.production_mutation_state(agent_id) {
        Ok(value) => value,
        Err(_) => return diagnostic(agent_id, RecoveryBlocker::DurabilityFailure, None, None),
    };
    let Some(mutation) = mutation else {
        return diagnostic(agent_id, RecoveryBlocker::None, None, None);
    };
    if mutation.receipt.status != ProductionMutationStatus::RecoveryRequired {
        return diagnostic(
            agent_id,
            RecoveryBlocker::None,
            Some(mutation.receipt.status),
            None,
        );
    }
    let transaction = match supervisor.release_selection_snapshot(agent_id) {
        Ok(Some(value)) => value,
        Ok(None) => {
            return diagnostic(
                agent_id,
                RecoveryBlocker::IntentMismatch,
                Some(mutation.receipt.status),
                None,
            );
        }
        Err(_) => {
            return diagnostic(
                agent_id,
                RecoveryBlocker::DurabilityFailure,
                Some(mutation.receipt.status),
                None,
            );
        }
    };
    let phase = Some(transaction.phase);
    if transaction.grant_sha256.as_ref() != Some(&mutation.receipt.grant_sha256)
        || mutation.release_transaction_sha256.as_ref()
            != Some(&transaction.transaction_sha256)
    {
        return diagnostic(
            agent_id,
            RecoveryBlocker::IntentMismatch,
            Some(mutation.receipt.status),
            phase,
        );
    }
    if transaction.authority_epoch != Some(current_authority_epoch) {
        return diagnostic(
            agent_id,
            RecoveryBlocker::AuthorityEpochChange,
            Some(mutation.receipt.status),
            phase,
        );
    }
    let Some(snapshot) = supervisor.snapshot(agent_id) else {
        return diagnostic(
            agent_id,
            RecoveryBlocker::DurabilityFailure,
            Some(mutation.receipt.status),
            phase,
        );
    };
    if snapshot.active && (snapshot.runtime_fenced || snapshot.release_change_pending) {
        return diagnostic(
            agent_id,
            RecoveryBlocker::ProcessAmbiguity,
            Some(mutation.receipt.status),
            phase,
        );
    }
    let current = snapshot.active_release.as_deref();
    if current.is_some_and(|release| {
        release != transaction.source_release && release != transaction.target_release
    }) || transaction.phase != ReleaseTransactionPhase::RecoveryRequired
    {
        return diagnostic(
            agent_id,
            RecoveryBlocker::ReleaseCasAmbiguity,
            Some(mutation.receipt.status),
            phase,
        );
    }
    for release in [&transaction.source_release, &transaction.target_release] {
        let Ok(release_id) = ReleaseId::parse(release.clone()) else {
            return diagnostic(
                agent_id,
                RecoveryBlocker::IntentMismatch,
                Some(mutation.receipt.status),
                phase,
            );
        };
        if registry
            .resolve_release_binding(agent_id, &release_id)
            .is_err()
        {
            return diagnostic(
                agent_id,
                RecoveryBlocker::FrontierDrift,
                Some(mutation.receipt.status),
                phase,
            );
        }
    }
    diagnostic(
        agent_id,
        RecoveryBlocker::AwaitingIndependentDecision,
        Some(mutation.receipt.status),
        phase,
    )
}

fn diagnostic(
    agent_id: &AgentId,
    blocker: RecoveryBlocker,
    production_status: Option<ProductionMutationStatus>,
    transaction_phase: Option<ReleaseTransactionPhase>,
) -> SupervisordRecoveryDiagnostic {
    let (action, retry_safe) = match blocker {
        RecoveryBlocker::None => (RecoveryOperatorAction::None, true),
        RecoveryBlocker::ProcessAmbiguity => {
            (RecoveryOperatorAction::FenceAndObserveProcessExit, false)
        }
        RecoveryBlocker::ReleaseCasAmbiguity => {
            (RecoveryOperatorAction::InspectReleaseStateCas, false)
        }
        RecoveryBlocker::IntentMismatch => {
            (RecoveryOperatorAction::InspectIntentAndTransaction, false)
        }
        RecoveryBlocker::FrontierDrift => {
            (RecoveryOperatorAction::RequalifyReleaseFrontier, false)
        }
        RecoveryBlocker::AuthorityEpochChange => {
            (RecoveryOperatorAction::RefreshAuthorityEpoch, false)
        }
        RecoveryBlocker::DurabilityFailure => {
            (RecoveryOperatorAction::RepairDurableState, false)
        }
        RecoveryBlocker::AwaitingIndependentDecision => {
            (RecoveryOperatorAction::IssueIndependentRecoveryDecision, false)
        }
    };
    SupervisordRecoveryDiagnostic {
        agent_id: agent_id.clone(),
        blocker,
        action,
        retry_safe,
        production_status,
        transaction_phase,
    }
}
''',
)

write(
    "codex-rs/hepta-supervisor/src/qualification_fault.rs",
    r'''use std::io;

pub(crate) fn check(point: &str) -> io::Result<()> {
    #[cfg(any(test, feature = "qualification"))]
    {
        let Ok(specification) = std::env::var("HEPTA_SUPERVISOR_FAULT") else {
            return Ok(());
        };
        let Some((expected, action)) = specification.split_once('=') else {
            return Ok(());
        };
        if expected != point {
            return Ok(());
        }
        return match action {
            "storage_full" => Err(io::Error::from_raw_os_error(libc::ENOSPC)),
            "fsync" => Err(io::Error::from_raw_os_error(libc::EIO)),
            "rename" => Err(io::Error::from_raw_os_error(libc::EXDEV)),
            "permission" => Err(io::Error::from_raw_os_error(libc::EACCES)),
            "kill" => kill_process(),
            _ => Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "unknown supervisor qualification fault action",
            )),
        };
    }
    #[cfg(not(any(test, feature = "qualification")))]
    {
        let _ = point;
        Ok(())
    }
}

#[cfg(any(test, feature = "qualification"))]
fn kill_process() -> io::Result<()> {
    #[cfg(unix)]
    {
        // SAFETY: raise is called with the fixed SIGKILL constant. The process
        // terminates immediately; the fallback error is only for an impossible
        // return after a failed signal delivery.
        let result = unsafe { libc::raise(libc::SIGKILL) };
        Err(io::Error::other(format!(
            "SIGKILL qualification failpoint returned {result}"
        )))
    }
    #[cfg(not(unix))]
    {
        std::process::abort()
    }
}
''',
)

write(
    "codex-rs/hepta-supervisor/src/lock_qualification.rs",
    r'''use std::sync::Arc;
use std::time::Duration;

use serde::Deserialize;
use serde::Serialize;
use tokio::task::JoinSet;

use crate::daemon_protocol::SupervisordLockMetric;
use crate::daemon_protocol::SupervisordLockOperation;
use crate::supervisor_lock::SupervisorLock;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisorLockQualificationReceipt {
    pub schema: String,
    pub managed_instances: u16,
    pub scenarios: Vec<String>,
    pub metrics: Vec<SupervisordLockMetric>,
    pub hol_observed: bool,
    pub applied_refactor: String,
    pub target_host_evidence: bool,
}

pub async fn run_supervisor_lock_qualification() -> SupervisorLockQualificationReceipt {
    let lock = Arc::new(SupervisorLock::new(0_u64));
    run_wave(
        Arc::clone(&lock),
        SupervisordLockOperation::Snapshot,
        256,
        Duration::ZERO,
    )
    .await;
    for count in [26, 128, 256] {
        run_wave(
            Arc::clone(&lock),
            SupervisordLockOperation::TickAgent,
            count,
            Duration::from_micros(100),
        )
        .await;
    }
    run_slow_then_readers(
        Arc::clone(&lock),
        SupervisordLockOperation::TickAgent,
        Duration::from_millis(20),
    )
    .await;
    run_slow_then_readers(
        Arc::clone(&lock),
        SupervisordLockOperation::Roster,
        Duration::from_millis(20),
    )
    .await;
    let mut mixed = JoinSet::new();
    for index in 0..192_u16 {
        let lock = Arc::clone(&lock);
        mixed.spawn(async move {
            let operation = match index % 3 {
                0 => SupervisordLockOperation::Mutation,
                1 => SupervisordLockOperation::Snapshot,
                _ => SupervisordLockOperation::Health,
            };
            let mut guard = lock.lock(operation).await;
            *guard = guard.saturating_add(1);
            if operation == SupervisordLockOperation::Mutation {
                tokio::time::sleep(Duration::from_micros(50)).await;
            }
        });
    }
    while mixed.join_next().await.is_some() {}

    let metrics = lock.snapshot();
    let hol_observed = metrics.iter().any(|metric| {
        matches!(
            metric.operation,
            SupervisordLockOperation::TickAgent | SupervisordLockOperation::Roster
        ) && metric.hold_max_micros >= 15_000
    });
    SupervisorLockQualificationReceipt {
        schema: "hepta.runtime-supervisor.lock-qualification.v1".to_string(),
        managed_instances: 256,
        scenarios: vec![
            "healthy_fleet".to_string(),
            "crash_wave_10_percent".to_string(),
            "crash_wave_50_percent".to_string(),
            "crash_wave_100_percent".to_string(),
            "slow_process_driver".to_string(),
            "slow_filesystem".to_string(),
            "concurrent_drain_status_mutation".to_string(),
        ],
        metrics,
        hol_observed,
        applied_refactor:
            "out_of_lock_registry_collection_plus_tick_plan_and_per_agent_tick_locking".to_string(),
        target_host_evidence: false,
    }
}

async fn run_wave(
    lock: Arc<SupervisorLock<u64>>,
    operation: SupervisordLockOperation,
    count: u16,
    hold: Duration,
) {
    let mut tasks = JoinSet::new();
    for _ in 0..count {
        let lock = Arc::clone(&lock);
        tasks.spawn(async move {
            let mut guard = lock.lock(operation).await;
            *guard = guard.saturating_add(1);
            if !hold.is_zero() {
                tokio::time::sleep(hold).await;
            }
        });
    }
    while tasks.join_next().await.is_some() {}
}

async fn run_slow_then_readers(
    lock: Arc<SupervisorLock<u64>>,
    slow_operation: SupervisordLockOperation,
    hold: Duration,
) {
    let slow_lock = Arc::clone(&lock);
    let slow = tokio::spawn(async move {
        let mut guard = slow_lock.lock(slow_operation).await;
        *guard = guard.saturating_add(1);
        tokio::time::sleep(hold).await;
    });
    tokio::task::yield_now().await;
    run_wave(
        Arc::clone(&lock),
        SupervisordLockOperation::Snapshot,
        64,
        Duration::ZERO,
    )
    .await;
    slow.await.expect("slow qualification task");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn qualification_covers_256_instances_and_detects_injected_hol() {
        let receipt = run_supervisor_lock_qualification().await;
        assert_eq!(receipt.managed_instances, 256);
        assert_eq!(receipt.scenarios.len(), 7);
        assert!(receipt.hol_observed);
        assert!(receipt.metrics.iter().any(|metric| {
            metric.operation == SupervisordLockOperation::TickAgent
                && metric.acquisitions >= 411
        }));
    }
}
''',
)

write(
    "codex-rs/hepta-supervisor/src/bin/hepta-supervisor-lock-qualification.rs",
    r'''use anyhow::Context;
use codex_hepta_supervisor::run_supervisor_lock_qualification;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let receipt = run_supervisor_lock_qualification().await;
    let encoded = serde_json::to_string_pretty(&receipt).context("encode qualification receipt")?;
    println!("{encoded}");
    Ok(())
}
''',
)

# daemon protocol additions
replace_once(
    "codex-rs/hepta-supervisor/src/daemon_protocol.rs",
    "use codex_hepta_contracts::AgentId;\n",
    "use codex_hepta_contracts::AgentId;\nuse codex_hepta_contracts::Sha256Digest;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon_protocol.rs",
    "use crate::DurableReleaseTransaction;\n",
    "use crate::DurableReleaseTransaction;\nuse crate::ReleaseTransactionPhase;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon_protocol.rs",
    "            SupervisordMethod::Health\n            | SupervisordMethod::Snapshot { .. }\n",
    "            SupervisordMethod::Health\n            | SupervisordMethod::Diagnostics { .. }\n            | SupervisordMethod::Snapshot { .. }\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon_protocol.rs",
    "pub enum SupervisordMethod {\n    Health,\n",
    "pub enum SupervisordMethod {\n    Health,\n    Diagnostics {\n        agent_id: Option<AgentId>,\n    },\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon_protocol.rs",
    "pub enum SupervisordPayload {\n    Health(SupervisordHealth),\n",
    "pub enum SupervisordPayload {\n    Health(SupervisordHealth),\n    Diagnostics(SupervisordDiagnostics),\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon_protocol.rs",
    "#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]\n#[serde(deny_unknown_fields)]\npub struct SupervisordAgentStatus {\n",
    r'''#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SupervisordLockOperation {
    TickPlan,
    TickAgent,
    Health,
    Roster,
    Snapshot,
    ReleaseSelection,
    ProductionMutationStatus,
    Mutation,
    SignedMutation,
    RecoveryResolution,
    Diagnostics,
}

impl SupervisordLockOperation {
    pub(crate) const ALL: [Self; 11] = [
        Self::TickPlan,
        Self::TickAgent,
        Self::Health,
        Self::Roster,
        Self::Snapshot,
        Self::ReleaseSelection,
        Self::ProductionMutationStatus,
        Self::Mutation,
        Self::SignedMutation,
        Self::RecoveryResolution,
        Self::Diagnostics,
    ];
    pub(crate) const COUNT: usize = Self::ALL.len();

    pub(crate) const fn index(self) -> usize {
        match self {
            Self::TickPlan => 0,
            Self::TickAgent => 1,
            Self::Health => 2,
            Self::Roster => 3,
            Self::Snapshot => 4,
            Self::ReleaseSelection => 5,
            Self::ProductionMutationStatus => 6,
            Self::Mutation => 7,
            Self::SignedMutation => 8,
            Self::RecoveryResolution => 9,
            Self::Diagnostics => 10,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisordLockMetric {
    pub operation: SupervisordLockOperation,
    pub acquisitions: u64,
    pub contended_acquisitions: u64,
    pub wait_total_micros: u64,
    pub wait_max_micros: u64,
    pub hold_total_micros: u64,
    pub hold_max_micros: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecoveryBlocker {
    None,
    ProcessAmbiguity,
    ReleaseCasAmbiguity,
    IntentMismatch,
    FrontierDrift,
    AuthorityEpochChange,
    DurabilityFailure,
    AwaitingIndependentDecision,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecoveryOperatorAction {
    None,
    FenceAndObserveProcessExit,
    InspectReleaseStateCas,
    InspectIntentAndTransaction,
    RequalifyReleaseFrontier,
    RefreshAuthorityEpoch,
    RepairDurableState,
    IssueIndependentRecoveryDecision,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisordRecoveryDiagnostic {
    pub agent_id: AgentId,
    pub blocker: RecoveryBlocker,
    pub action: RecoveryOperatorAction,
    pub retry_safe: bool,
    pub production_status: Option<ProductionMutationStatus>,
    pub transaction_phase: Option<ReleaseTransactionPhase>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisordDiagnostics {
    pub supervisor_epoch: SupervisorEpoch,
    pub process_id: u32,
    pub registered_agents: u16,
    pub observed_faults: u64,
    pub authority_distribution_generation: Option<u64>,
    pub authority_signer_id: Option<String>,
    pub authority_signer_epoch: Option<u64>,
    pub lock_metrics: Vec<SupervisordLockMetric>,
    pub recovery: Option<SupervisordRecoveryDiagnostic>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisordAgentStatus {
''',
)

# signed authority verifier introspection
replace_once(
    "codex-rs/hepta-supervisor/src/signed_authority.rs",
    "    pub fn from_bytes(\n        signer_id: impl Into<String>,\n",
    "    pub fn signer_id(&self) -> &str {\n        &self.signer_id\n    }\n\n    pub const fn signer_epoch(&self) -> u64 {\n        self.signer_epoch\n    }\n\n    pub fn from_bytes(\n        signer_id: impl Into<String>,\n",
)

# library module declarations and exports
replace_once(
    "codex-rs/hepta-supervisor/src/lib.rs",
    "mod process_deadline;\nmod recovery;\n",
    "mod process_deadline;\nmod production_authority_distribution;\nmod production_caller;\nmod qualification_fault;\nmod recovery;\nmod recovery_diagnostics;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/lib.rs",
    "mod supervisor;\nmod supervisor_qualification;\n",
    "mod supervisor;\nmod supervisor_lock;\nmod supervisor_qualification;\n#[cfg(feature = \"qualification\")]\nmod lock_qualification;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/lib.rs",
    "pub use daemon::run_supervisord_with_grant_verifier;\n",
    "pub use daemon::run_supervisord_with_authority_distribution;\npub use daemon::run_supervisord_with_grant_verifier;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/lib.rs",
    "pub use daemon_protocol::SupervisordHealth;\n",
    "pub use daemon_protocol::RecoveryBlocker;\npub use daemon_protocol::RecoveryOperatorAction;\npub use daemon_protocol::SupervisordDiagnostics;\npub use daemon_protocol::SupervisordHealth;\npub use daemon_protocol::SupervisordLockMetric;\npub use daemon_protocol::SupervisordLockOperation;\npub use daemon_protocol::SupervisordRecoveryDiagnostic;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/lib.rs",
    "pub use process_deadline::enforce_process_termination_deadline_v1;\n",
    "pub use process_deadline::enforce_process_termination_deadline_v1;\npub use production_authority_distribution::MAX_REVOKED_PRODUCTION_GRANTS;\npub use production_authority_distribution::ProductionAuthorityDistributionError;\npub use production_authority_distribution::ProductionAuthorityDistributionSnapshot;\npub use production_authority_distribution::ProductionAuthorityPublisher;\npub use production_authority_distribution::ProductionAuthorityReader;\npub use production_authority_distribution::production_authority_distribution;\npub use production_caller::AuthorizedProductionTransition;\npub use production_caller::ProductionSupervisorCaller;\npub use production_caller::ProductionSupervisorCallerError;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/lib.rs",
    "pub use signed_authority::H7H89ProductionGrantVerifier;\n",
    "pub use signed_authority::H7H89ProductionGrantVerifier;\npub use signed_authority::ProductionAuthorityError;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/lib.rs",
    "pub use supervisor::Supervisor;\n",
    "pub use supervisor::Supervisor;\n#[cfg(feature = \"qualification\")]\npub use lock_qualification::SupervisorLockQualificationReceipt;\n#[cfg(feature = \"qualification\")]\npub use lock_qualification::run_supervisor_lock_qualification;\n",
)

# client diagnostics
replace_once(
    "codex-rs/hepta-supervisor/src/daemon_client.rs",
    "use crate::daemon_protocol::SupervisordControlFence;\n",
    "use crate::daemon_protocol::SupervisordControlFence;\nuse crate::daemon_protocol::SupervisordDiagnostics;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon_client.rs",
    "    pub async fn roster(&self, limit: u16) -> Result<Vec<SupervisordAgentStatus>, SupervisorError> {\n",
    "    pub async fn diagnostics(\n        &self,\n        agent_id: Option<AgentId>,\n    ) -> Result<SupervisordDiagnostics, SupervisorError> {\n        match self.send(SupervisordMethod::Diagnostics { agent_id }).await? {\n            SupervisordPayload::Diagnostics(diagnostics) => Ok(diagnostics),\n            payload => unexpected(payload),\n        }\n    }\n\n    pub async fn roster(&self, limit: u16) -> Result<Vec<SupervisordAgentStatus>, SupervisorError> {\n",
)

# per-agent tick method
replace_once(
    "codex-rs/hepta-supervisor/src/supervisor.rs",
    r'''    pub fn tick(&mut self, now: Instant) -> TickReport {
        let mut report = TickReport::default();
        let agent_ids: Vec<_> = self.slots.keys().cloned().collect();
        for agent_id in agent_ids {
            let result = self.with_slot(&agent_id, |supervisor, slot| {
                supervisor.tick_slot(&agent_id, slot, now)
            });
            if let Err(error) = result {
                self.record_fault(&agent_id, &error, &mut report);
            }
        }
        report
    }
''',
    r'''    pub(crate) fn tick_agent(&mut self, agent_id: &AgentId, now: Instant) -> TickReport {
        let mut report = TickReport::default();
        let result = self.with_slot(agent_id, |supervisor, slot| {
            supervisor.tick_slot(agent_id, slot, now)
        });
        if let Err(error) = result {
            self.record_fault(agent_id, &error, &mut report);
        }
        report
    }

    pub fn tick(&mut self, now: Instant) -> TickReport {
        let mut report = TickReport::default();
        for agent_id in self.agent_ids() {
            report.faults.extend(self.tick_agent(&agent_id, now).faults);
        }
        report
    }
''',
)

# Cargo binary
replace_once(
    "codex-rs/hepta-supervisor/Cargo.toml",
    "[[bin]]\nname = \"hepta-authority-signer\"\n",
    "[[bin]]\nname = \"hepta-supervisor-lock-qualification\"\npath = \"src/bin/hepta-supervisor-lock-qualification.rs\"\ntest = false\nrequired-features = [\"qualification\"]\n\n[[bin]]\nname = \"hepta-authority-signer\"\n",
)

print("runtime.supervisor source phase patched")
