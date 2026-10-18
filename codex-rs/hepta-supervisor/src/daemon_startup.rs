//! The original kernel owner spans admitted startup work and queued results.

use std::sync::Arc;

use super::owner::SingleInstanceLock;
use crate::SupervisorError;

// Field order matters when an abandoned join drops a recovered Supervisor or
// opened resource host: its owned state retires before the last flock guard.
pub(crate) struct OwnedStartup<T> {
    pub(crate) outcome: Result<T, SupervisorError>,
    pub(crate) instance: Arc<SingleInstanceLock>,
}

pub(crate) async fn run_owned<T: Send + 'static>(
    instance: Arc<SingleInstanceLock>,
    work: impl FnOnce() -> Result<T, SupervisorError> + Send + 'static,
) -> Result<OwnedStartup<T>, SupervisorError> {
    tokio::task::spawn_blocking(move || OwnedStartup {
        outcome: work(),
        instance,
    })
    .await
    .map_err(|error| SupervisorError::Invalid(format!("startup owner worker failed: {error}")))
}

#[cfg(all(target_os = "linux", feature = "local-host"))]
pub(crate) async fn recover_with_local_host<T: Send + 'static>(
    host: Arc<crate::LocalFleetHost>,
    instance: Arc<SingleInstanceLock>,
    cancellation: tokio_util::sync::CancellationToken,
    work: impl FnOnce() -> Result<T, SupervisorError> + Send + 'static,
) -> Result<
    (
        OwnedStartup<T>,
        tokio::task::JoinHandle<Result<(), SupervisorError>>,
    ),
    SupervisorError,
> {
    // The same original host covers cold catalog and durable process recovery.
    // This task and each admitted upkeep job share the original kernel guard.
    let maintenance_owner = Arc::clone(&instance);
    let maintenance = tokio::spawn(async move {
        host.run_maintenance(cancellation, maintenance_owner)
            .await
            .map_err(|error| SupervisorError::Invalid(error.to_string()))
    });
    let recovered = run_owned(instance, work).await?;
    Ok((recovered, maintenance))
}

#[cfg(test)]
#[path = "daemon_startup_tests.rs"]
mod tests;
