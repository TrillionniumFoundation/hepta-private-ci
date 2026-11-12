//! One-shot data exchange with an independently operated original actor.
//! A missing response may wait inside the SAME operation. No authority call,
//! nonce, signing request or failed result is resubmitted by this adapter.

use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_types::Digest32;
use serde::{Deserialize, Serialize};

use crate::{AgentdError, CellQ24PreparedLearningV1};
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;

use super::files::{MutableFileData, OriginalDeploymentFiles, OriginalFileMode, OriginalPinnedRead};
use super::{deployment_error, deployment_refused};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalActorExchangeData {
    pub request: MutableFileData,
    pub response: PathBuf,
}

/// Captures the actual request's ORIGINAL absolute business expiry. This is
/// independent of the two original phase bounds; no Duration starts a new end.
pub(super) struct OriginalActorWait {
    context: Arc<OriginalSameActorRootContext>,
    business_expiry_unix_seconds: u64,
    last_unix_seconds: u64,
}

impl OriginalActorWait {
    pub(super) fn for_original_prepared(
        context: Arc<OriginalSameActorRootContext>,
        prepared: &CellQ24PreparedLearningV1,
    ) -> Result<Self, AgentdError> {
        OriginalSameActorRootContext::require_current(&context)?;
        prepared.revalidate_source().map_err(deployment_error)?;
        let business_expiry_unix_seconds =
            prepared.initial().request.envelope.expiry_unix_seconds;
        let last_unix_seconds = context.clock().now_unix_ms()
            .map_err(deployment_error)? / 1_000;
        if business_expiry_unix_seconds <= last_unix_seconds {
            return Err(deployment_refused("original signing business deadline has elapsed"));
        }
        let mut wait = Self { context, business_expiry_unix_seconds, last_unix_seconds };
        wait.require_original_live()?;
        Ok(wait)
    }

    /// Ordinary Outcome/Selection handoff also uses the already approved
    /// absolute task expiry, never a deadline based on this later wait.
    pub(super) fn for_original_task(
        context: Arc<OriginalSameActorRootContext>,
        original_expiry_unix_seconds: u64,
    ) -> Result<Self, AgentdError> {
        OriginalSameActorRootContext::require_current(&context)?;
        let last_unix_seconds = context.clock().now_unix_ms()
            .map_err(deployment_error)? / 1_000;
        let mut wait = Self {
            context, business_expiry_unix_seconds: original_expiry_unix_seconds,
            last_unix_seconds,
        };
        wait.require_original_live()?;
        Ok(wait)
    }

    pub(super) fn require_original_live(&mut self) -> Result<u64, AgentdError> {
        OriginalSameActorRootContext::require_current(&self.context)?;
        let now = self.context.clock().now_unix_ms().map_err(deployment_error)? / 1_000;
        if now < self.last_unix_seconds || now >= self.business_expiry_unix_seconds {
            return Err(deployment_refused("original actor deadline expired or clock regressed"));
        }
        self.last_unix_seconds = now;
        OriginalSameActorRootContext::require_current(&self.context)?;
        Ok(now)
    }

    pub(super) fn wait_original_file(
        &mut self,
        files: &mut OriginalDeploymentFiles,
        path: &std::path::Path,
        maximum: usize,
    ) -> Result<OriginalPinnedRead, AgentdError> {
        loop {
            self.require_original_live()?;
            match std::fs::symlink_metadata(path) {
                Ok(_) => {
                    // The first visible response is read exactly once. An
                    // empty, partial, changed, unauthorized or invalid file is
                    // an error, never a reason to wait for a replacement.
                    let read = files.read_original_stage(path, maximum)?;
                    self.require_original_live()?;
                    return Ok(read);
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => return Err(error.into()),
            }
            // This concrete coordinator has a retained std::thread owner.
            // Waiting does not hold a Root request, owner mutex or Tokio worker.
            // A late wake still checks the same absolute bounds before reading.
            std::thread::park_timeout(Duration::from_millis(5));
        }
    }
}

/// Deliberately not Clone. Taking this object consumes its one request path
/// even if write, sync, waiting or parsing fails. The durable owner which made
/// the original request retains Pending/uncertain state on that failure.
pub(super) struct OriginalActorExchange {
    data: OriginalActorExchangeData,
}

impl OriginalActorExchange {
    pub(super) fn new(data: OriginalActorExchangeData) -> Result<Self, AgentdError> {
        if !matches!(data.request.mode, OriginalFileMode::CreateNew)
            || data.request.path == data.response
        {
            return Err(deployment_refused("original actor exchange requires a fresh request path"));
        }
        Ok(Self { data })
    }

    pub(super) fn exchange_original<T: Serialize>(
        self,
        request: &T,
        files: &mut OriginalDeploymentFiles,
        wait: &mut OriginalActorWait,
    ) -> Result<(Digest32, OriginalPinnedRead), AgentdError> {
        wait.require_original_live()?;
        let bytes = serde_json::to_vec(request).map_err(deployment_error)?;
        if bytes.is_empty() || bytes.len() > 1024 * 1024 {
            return Err(deployment_refused("original signing request exceeds its data bound"));
        }
        // A response already at this unique original path is not a reply to
        // the request we have yet to publish. Never adopt a precomputed reply.
        match std::fs::symlink_metadata(&self.data.response) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Ok(_) => return Err(deployment_refused("original response path already exists")),
            Err(error) => return Err(error.into()),
        }
        let (mut file, directory) =
            files.open_original_owner_with_directory(&self.data.request)?;
        wait.require_original_live()?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        directory.sync_all()?;
        wait.require_original_live()?;
        // The external original actor must publish a complete response once,
        // e.g. by an atomic rename after syncing its own private temporary file.
        let response = wait.wait_original_file(files, &self.data.response, 1024 * 1024)?;
        wait.require_original_live()?;
        Ok((Digest32::of_bytes(&bytes), response))
    }
}
