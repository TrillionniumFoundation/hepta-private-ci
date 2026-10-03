//! Carry the original operation ceiling to the sole transport writer.

use std::io;
use std::path::Path;
use std::time::Duration;

use codex_app_server_client::RemoteRequestSendGuard;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::CognitiveContextSnapshot;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::VerifiedUseToken;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use super::NativeWorkerConfig;
use super::Result;
use super::unix_time_ms;
use super::validate_post_authority_fence;

#[derive(Clone, Copy)]
pub(super) struct NativeExecutionDeadline {
    pub unix_ms: u64,
    pub monotonic: Instant,
}

impl NativeExecutionDeadline {
    pub fn capture(timeout: Duration, signed_ceiling: Option<u64>) -> Result<Self> {
        // Take the monotonic anchor first so clock sampling cannot extend it.
        let monotonic = Instant::now();
        let now = unix_time_ms()?;
        let budget_ms = u64::try_from(timeout.as_millis())?;
        let unix_ms = now
            .checked_add(budget_ms)
            .ok_or("execution deadline overflow")?;
        let unix_ms = signed_ceiling.map_or(unix_ms, |ceiling| ceiling.min(unix_ms));
        if unix_ms <= now {
            return Err("execution plan or operation deadline already elapsed".into());
        }
        let monotonic = monotonic
            .checked_add(Duration::from_millis(unix_ms - now))
            .ok_or("monotonic execution deadline overflow")?;
        Ok(Self { unix_ms, monotonic })
    }
}

#[allow(
    clippy::too_many_arguments,
    reason = "The guard binds one immutable request, authority, cancellation, and owner snapshot"
)]
pub(super) fn native_send_guard(
    config: &NativeWorkerConfig,
    ingress: &Path,
    snapshot: Option<CognitiveContextSnapshot>,
    deadline: NativeExecutionDeadline,
    cancellation: CancellationToken,
    verified_use: VerifiedUseToken,
    binding: FinalUseBinding,
) -> Result<RemoteRequestSendGuard> {
    let owner = AgentdClient::new(
        config.agentd_socket.clone(),
        config.agent_id.clone(),
        config.generation,
    )?;
    let ingress = ingress.to_path_buf();
    Ok(RemoteRequestSendGuard::new(
        deadline.monotonic,
        cancellation.clone().cancelled_owned(),
        async move {
            // These observations happen after both queue and sink readiness.
            // They are not an atomic cross-process generation lease.
            let health = owner.health().await.map_err(io::Error::other)?;
            let current_ingress = owner.session_ingress().await.map_err(io::Error::other)?;
            if let Some(snapshot) = snapshot {
                let checked = owner
                    .revalidate_cognitive_context(&snapshot)
                    .await
                    .map_err(io::Error::other)?;
                if checked.snapshot_digest != snapshot.snapshot_digest
                    || checked.read_digest != snapshot.read_digest
                    || usize::from(checked.verified_item_count) != snapshot.items.len()
                {
                    return Err(io::Error::other("cognitive physical-send receipt mismatch"));
                }
            }
            Ok(move || {
                let now = unix_time_ms().map_err(|error| io::Error::other(error.to_string()))?;
                validate_post_authority_fence(
                    &health,
                    &ingress,
                    &current_ingress.socket_path,
                    cancellation.is_cancelled(),
                    now,
                    deadline.unix_ms,
                )
                .map_err(|error| io::Error::other(error.to_string()))?;
                let entered = verified_use.enter(&binding).map_err(io::Error::other)?;
                if !entered.matches(&binding) {
                    return Err(io::Error::other("physical-send authority binding mismatch"));
                }
                Ok(entered)
            })
        },
    ))
}

#[cfg(test)]
#[path = "native_send_guard_tests.rs"]
mod tests;
