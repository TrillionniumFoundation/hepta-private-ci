//! Shared absolute startup deadlines without discarding original SDK errors.
use std::future::Future;

use codex_hepta_paths::HeptaAgentLayout;
use tokio::time::Instant;
use tokio::time::error::Elapsed;

use super::MATRIX_STARTUP_REQUEST_TIMEOUT;
use super::MatrixSdkClient;
use super::MatrixSdkError;
use super::MatrixSidecarConfig;

/// Keep the original error available for the caller's existing stage mapping.
pub(super) enum RequestFailure<E> {
    Expired,
    Timeout(Elapsed),
    Request(E),
}

pub(super) async fn build_until(
    layout: &HeptaAgentLayout,
    config: MatrixSidecarConfig,
    store_passphrase: Option<&str>,
    startup_deadline: Instant,
    timeout_stage: &'static str,
) -> Result<MatrixSdkClient, MatrixSdkError> {
    if Instant::now() >= startup_deadline {
        return Err(MatrixSdkError::initialization_rejected(timeout_stage));
    }
    let sidecar = tokio::time::timeout_at(
        startup_deadline,
        MatrixSdkClient::build(layout, config, store_passphrase),
    )
    .await
    .map_err(|error| MatrixSdkError::initialization(timeout_stage, error))??;
    // Synchronous KDF work can return Ready after the timer expires.
    if Instant::now() >= startup_deadline {
        return Err(MatrixSdkError::initialization_rejected(timeout_stage));
    }
    Ok(sidecar)
}

pub(super) async fn request_until<T, E>(
    startup_deadline: Instant,
    request: impl Future<Output = Result<T, E>>,
) -> Result<T, RequestFailure<E>> {
    let now = Instant::now();
    if now >= startup_deadline {
        return Err(RequestFailure::Expired);
    }
    let request_deadline = startup_deadline.min(now + MATRIX_STARTUP_REQUEST_TIMEOUT);
    let response = tokio::time::timeout_at(request_deadline, request)
        .await
        .map_err(RequestFailure::Timeout)?
        .map_err(RequestFailure::Request)?;
    if Instant::now() >= request_deadline {
        return Err(RequestFailure::Expired);
    }
    Ok(response)
}

pub(super) fn finish(
    sidecar: &MatrixSdkClient,
    startup_deadline: Instant,
) -> Result<(), MatrixSdkError> {
    // Reject expired activation without claiming a completed session write was
    // rolled back. Existing identity and event-cache errors keep their causes.
    if Instant::now() >= startup_deadline {
        return Err(MatrixSdkError::initialization_rejected(
            "startup.finalize.deadline",
        ));
    }
    sidecar.verify_authenticated_identity()?;
    sidecar.enable_event_cache()?;
    if Instant::now() >= startup_deadline {
        return Err(MatrixSdkError::initialization_rejected(
            "startup.finalize.deadline",
        ));
    }
    Ok(())
}
