use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use serde::Serialize;
use tokio_util::sync::CancellationToken;

use super::AttestedModelHandle;
use super::DriverInterruptReason;
use super::DriverLoadObservation;
use super::DriverReconciliation;
use super::DriverRunObservation;
use super::DriverUnloadObservation;
use super::LocalFuture;
use super::LocalModelDriver;
use super::LocalRunAdmission;
use super::LocalRunResult;
use super::LocalWorkerError;
use super::ResourceManager;
use super::TrustedAuthorityProvider;
use super::TrustedClock;
use super::TrustedDeadline;
use super::TrustedReleaseObservation;
use super::TrustedResourceObservation;
use super::TrustedResourceObserver;
use super::VerifiedInput;
use super::VerifiedModelManifest;
use super::VerifiedResourceGrant;
use super::digest;
use super::durable;
use super::live_authority::LiveAuthorityMonitor;
#[cfg(test)]
use super::live_authority::PinnedAuthorityProvider;

#[derive(Clone)]
struct SupervisedDriver<D, C> {
    driver: Arc<D>,
    monitor: LiveAuthorityMonitor<C>,
}

impl<D, C> LocalModelDriver for SupervisedDriver<D, C>
where
    D: LocalModelDriver,
    C: TrustedClock + Clone,
{
    fn load<'a>(
        &'a self,
        manifest: &'a VerifiedModelManifest,
        grant: &'a VerifiedResourceGrant,
    ) -> LocalFuture<'a, DriverLoadObservation> {
        self.driver.load(manifest, grant)
    }

    fn cleanup_failed_load<'a>(
        &'a self,
        load: &'a DriverLoadObservation,
    ) -> LocalFuture<'a, DriverUnloadObservation> {
        self.driver.cleanup_failed_load(load)
    }

    fn run<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
        input: &'a VerifiedInput,
        cancellation: &'a CancellationToken,
        deadline: TrustedDeadline,
    ) -> LocalFuture<'a, DriverRunObservation> {
        Box::pin(async move {
            if self.monitor.require_current().await.is_err() {
                cancellation.cancel();
                return std::future::pending().await;
            }
            let run = self.driver.run(handle, input, cancellation, deadline);
            tokio::pin!(run);
            let authority_watch = self.monitor.cancel_when_invalid(cancellation);
            tokio::pin!(authority_watch);
            tokio::select! {
                result = &mut run => result,
                _ = &mut authority_watch => std::future::pending().await,
            }
        })
    }

    fn interrupt<'a>(
        &'a self,
        operation_id: &'a str,
        handle: &'a AttestedModelHandle,
        reason: DriverInterruptReason,
    ) -> LocalFuture<'a, DriverReconciliation> {
        Box::pin(async move {
            let interrupted = self.driver.interrupt(operation_id, handle, reason).await?;
            if !matches!(interrupted, DriverReconciliation::Terminal(_)) {
                return Ok(interrupted);
            }
            let inspected = self.driver.inspect(operation_id, handle).await?;
            match (&interrupted, &inspected) {
                (
                    DriverReconciliation::Terminal(interrupt_terminal),
                    DriverReconciliation::Terminal(inspect_terminal),
                ) if interrupt_terminal == inspect_terminal => Ok(inspected),
                (_, DriverReconciliation::Pending { .. }) => Ok(inspected),
                (_, DriverReconciliation::MissingHistory) => {
                    Ok(DriverReconciliation::Ambiguous {
                        reason: format!(
                            "{}; interrupt claimed terminality but independent inspect had no history",
                            reason.as_str()
                        ),
                    })
                }
                (_, DriverReconciliation::Ambiguous { reason: detail }) => {
                    Ok(DriverReconciliation::Ambiguous {
                        reason: format!(
                            "{}; interrupt terminality was not independently confirmed: {detail}",
                            reason.as_str()
                        ),
                    })
                }
                _ => Ok(DriverReconciliation::Ambiguous {
                    reason: format!(
                        "{}; interrupt and independent inspect returned conflicting terminal evidence",
                        reason.as_str()
                    ),
                }),
            }
        })
    }

    fn inspect<'a>(
        &'a self,
        operation_id: &'a str,
        handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, DriverReconciliation> {
        self.driver.inspect(operation_id, handle)
    }

    fn unload<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, DriverUnloadObservation> {
        self.driver.unload(handle)
    }
}

#[derive(Clone)]
struct AuthorityAwareObserver<O, C> {
    observer: Arc<O>,
    monitor: LiveAuthorityMonitor<C>,
    admitted_handles: Arc<Mutex<BTreeSet<String>>>,
}

impl<O, C> TrustedResourceObserver for AuthorityAwareObserver<O, C>
where
    O: TrustedResourceObserver,
    C: TrustedClock + Clone,
{
    fn observe_model<'a>(
        &'a self,
        handle_id: &'a str,
        device_uuid: &'a str,
        worker_generation: u64,
    ) -> LocalFuture<'a, TrustedResourceObservation> {
        Box::pin(async move {
            self.monitor.require_current().await?;
            let observed = self
                .observer
                .observe_model(handle_id, device_uuid, worker_generation)
                .await?;
            let mut handles = self
                .admitted_handles
                .lock()
                .map_err(|_| LocalWorkerError::ResourceStatePoisoned)?;
            if handles.contains(handle_id) && observed.transient_memory_bytes != 0 {
                return Err(LocalWorkerError::Observer(
                    "terminal resource observation retained transient execution memory"
                        .to_string(),
                ));
            }
            handles.insert(handle_id.to_string());
            Ok(observed)
        })
    }

    fn observe_unattested_release<'a>(
        &'a self,
        handle_id: &'a str,
        device_uuid: &'a str,
        worker_generation: u64,
    ) -> LocalFuture<'a, TrustedReleaseObservation> {
        self.observer
            .observe_unattested_release(handle_id, device_uuid, worker_generation)
    }

    fn observe_release<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, TrustedReleaseObservation> {
        self.observer.observe_release(handle)
    }
}

/// Hardened public local-model composition. Repository tests may use the
/// compatibility constructor, but non-test product composition must inject a
/// live, monotonic authority provider through `new_with_authority`.
pub struct DurableLocalModelWorker<D, O, C>
where
    D: LocalModelDriver,
    O: TrustedResourceObserver,
    C: TrustedClock + Clone,
{
    inner: durable::DurableLocalModelWorker<SupervisedDriver<D, C>, AuthorityAwareObserver<O, C>, C>,
    monitor: LiveAuthorityMonitor<C>,
}

impl<D, O, C> DurableLocalModelWorker<D, O, C>
where
    D: LocalModelDriver + 'static,
    O: TrustedResourceObserver + 'static,
    C: TrustedClock + Clone + 'static,
{
    pub fn new_with_authority<A>(
        driver: D,
        observer: O,
        clock: C,
        authority: A,
        grant: &VerifiedResourceGrant,
    ) -> Result<Self, LocalWorkerError>
    where
        A: TrustedAuthorityProvider + 'static,
    {
        Self::new_with_shared_authority(driver, observer, clock, Arc::new(authority), grant)
    }

    pub fn new_with_shared_authority(
        driver: D,
        observer: O,
        clock: C,
        authority: Arc<dyn TrustedAuthorityProvider>,
        grant: &VerifiedResourceGrant,
    ) -> Result<Self, LocalWorkerError> {
        let monitor = LiveAuthorityMonitor::new(authority, clock.clone(), grant)?;
        let driver = SupervisedDriver {
            driver: Arc::new(driver),
            monitor: monitor.clone(),
        };
        let observer = AuthorityAwareObserver {
            observer: Arc::new(observer),
            monitor: monitor.clone(),
            admitted_handles: Arc::new(Mutex::new(BTreeSet::new())),
        };
        let inner = durable::DurableLocalModelWorker::new(driver, observer, clock, grant)?;
        Ok(Self { inner, monitor })
    }

    #[cfg(test)]
    pub fn new(
        driver: D,
        observer: O,
        clock: C,
        grant: &VerifiedResourceGrant,
    ) -> Result<Self, LocalWorkerError> {
        let authority = PinnedAuthorityProvider::new(grant, &clock)?;
        Self::new_with_authority(driver, observer, clock, authority, grant)
    }

    #[cfg(not(test))]
    pub fn new(
        _driver: D,
        _observer: O,
        _clock: C,
        _grant: &VerifiedResourceGrant,
    ) -> Result<Self, LocalWorkerError> {
        Err(LocalWorkerError::InvalidGrant(
            "live authority provider required; use new_with_authority",
        ))
    }

    pub fn resources(&self) -> &ResourceManager {
        self.inner.resources()
    }

    pub async fn load_model(
        &self,
        grant: &VerifiedResourceGrant,
        manifest: &VerifiedModelManifest,
    ) -> Result<AttestedModelHandle, LocalWorkerError> {
        self.monitor.require_current().await?;
        self.inner.load_model(grant, manifest).await
    }

    pub async fn unload_model(
        &self,
        grant: &VerifiedResourceGrant,
        manifest: &VerifiedModelManifest,
        handle: &AttestedModelHandle,
    ) -> Result<(), LocalWorkerError> {
        self.inner.unload_model(grant, manifest, handle).await
    }

    pub async fn run(
        &self,
        control: &mut DurableInferenceControl,
        grant: &VerifiedResourceGrant,
        manifest: &VerifiedModelManifest,
        handle: &AttestedModelHandle,
        admission: LocalRunAdmission,
        input: &VerifiedInput,
        cancellation: &CancellationToken,
    ) -> Result<LocalRunResult, LocalWorkerError> {
        let snapshot = self.monitor.require_current().await?;
        let deadline = self.monitor.bind_deadline(admission.requested_deadline_ms)?;
        let request = NativeRequest {
            request_id: admission.request_id.clone(),
            principal_id: grant.worker_subject().to_string(),
            worker_generation: grant.worker_generation(),
            model: manifest.model_id().to_string(),
            payload_digest: local_payload_digest(
                grant,
                manifest,
                handle,
                &admission,
                input,
                deadline.as_millis(),
            )?,
        };
        let record = control
            .reserve_native(request, admission.maximum_in_flight)
            .map_err(control_error)?;
        if record.authority_observation.as_ref() != Some(&snapshot.to_native()) {
            control
                .observe_native_authority(&admission.request_id, snapshot.to_native())
                .map_err(control_error)?;
        }
        let request_id = admission.request_id.clone();
        let result = self
            .inner
            .run(
                control,
                grant,
                manifest,
                handle,
                admission,
                input,
                cancellation,
            )
            .await;
        if let Some(snapshot) = self.monitor.last_snapshot() {
            control
                .observe_native_authority(&request_id, snapshot.to_native())
                .map_err(control_error)?;
        }
        result
    }

    pub fn last_authority_failure(&self) -> Option<String> {
        self.monitor.last_failure()
    }
}

#[derive(Serialize)]
struct LocalPayloadBinding<'a> {
    schema: &'static str,
    request_id: &'a str,
    worker_subject: &'a str,
    worker_generation: u64,
    grant_witness_digest: &'a str,
    manifest_semantic_digest: &'a str,
    handle_id: &'a str,
    handle_attestation_digest: &'a str,
    input_digest: &'a str,
    maximum_tokens: u32,
    maximum_usage_units: u64,
    expected_transient_memory_bytes: u64,
    deadline_ms: u64,
}

fn local_payload_digest(
    grant: &VerifiedResourceGrant,
    manifest: &VerifiedModelManifest,
    handle: &AttestedModelHandle,
    admission: &LocalRunAdmission,
    input: &VerifiedInput,
    deadline_ms: u64,
) -> Result<String, LocalWorkerError> {
    let binding = LocalPayloadBinding {
        schema: "hepta.local-model-operation.v1",
        request_id: &admission.request_id,
        worker_subject: grant.worker_subject(),
        worker_generation: grant.worker_generation(),
        grant_witness_digest: grant.witness_digest(),
        manifest_semantic_digest: manifest.semantic_digest(),
        handle_id: handle.handle_id(),
        handle_attestation_digest: handle.resource_attestation_digest(),
        input_digest: input.digest(),
        maximum_tokens: admission.maximum_tokens,
        maximum_usage_units: admission.maximum_usage_units,
        expected_transient_memory_bytes: admission.expected_transient_memory_bytes,
        deadline_ms,
    };
    let encoded = serde_json::to_vec(&binding)
        .map_err(|_| LocalWorkerError::InvalidInput("local payload encoding"))?;
    Ok(digest(&encoded))
}

fn control_error(error: codex_hepta_infer_core::durable_control::Error) -> LocalWorkerError {
    LocalWorkerError::Control(error.to_string())
}
