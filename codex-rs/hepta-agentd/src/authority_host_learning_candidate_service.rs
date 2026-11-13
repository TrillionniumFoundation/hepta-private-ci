//! Explicit original inputs, complete role admission and supervised Root work.
//! This service does not load trust from its handoff or manufacture any owner.

use std::net::Shutdown;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use super::RootResidentLearningHandleV3;
use super::RootResidentLearningRegistrationV3;
use super::RootResidentLearningRuntimeV3;
use super::authority::ResidentRootAuthorityV3;
use super::authority::ResidentStoreActionV3;
use crate::AgentdError;
use crate::AgentdRootAuthorityPeer;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellQ24CandidateStageOwnersV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::RootCandidateStageHandoffV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use tokio_util::sync::CancellationToken;

/// Supplied by the original provider, separately from untrusted wire metadata.
/// These typed values retain their original scope, baseline and evidence trust.
pub struct RootResidentCandidateInputsV1 {
    pub material: OriginalCellQ24MaterialReceiptConfigV1,
    pub protocol: OriginalCellEvaluationPanelRegistrationV1,
    pub baseline: Arc<LoadedCellQ24ModelV1>,
    pub verifier: LearningEvidenceVerifierV1,
}

/// One already connected A/successor endpoint for the original resident server.
/// Its pidfd and process identity are not the role hosts' consumer identities.
pub struct RootResidentLearningConsumerV3 {
    pub stream: UnixStream,
    pub peer: AgentdRootAuthorityPeer,
    pub uid: u32,
    pub original_consumer_pidfd: OwnedFd,
    pub timeout: Duration,
    pub lifetime: Duration,
}

/// No Clone, stage getter, writer, signer or fresh replay entry escapes.
pub struct RootResidentCandidateServiceV1 {
    runtime: RootResidentLearningRuntimeV3,
    handle: RootResidentLearningHandleV3,
    consumer: RootResidentLearningConsumerV3,
    end: Instant,
}

impl RootResidentLearningRegistrationV3 {
    /// Consume an existing registration and original connected roles. Recovered
    /// custody selects only recovered channels; packet bytes cannot promote it.
    /// The original provider calls this inside the resident's Tokio runtime.
    pub fn into_candidate_service(
        self,
        inputs: RootResidentCandidateInputsV1,
        handoff: RootCandidateStageHandoffV1,
        consumer: RootResidentLearningConsumerV3,
    ) -> Result<RootResidentCandidateServiceV1, AgentdError> {
        let admitted = Instant::now();
        if consumer.uid == 0
            || consumer.timeout.is_zero()
            || consumer.timeout > Duration::from_secs(30)
            || consumer.lifetime.is_zero()
            || consumer.lifetime > Duration::from_secs(300)
        {
            return Err(AgentdError::Invalid(
                "original resident consumer timing or identity differs".into(),
            ));
        }
        let consumer_end = admitted
            .checked_add(consumer.lifetime)
            .ok_or_else(|| AgentdError::Invalid("resident consumer deadline overflow".into()))?;
        ResidentRootAuthorityV3::perform(
            &self.owner.authority,
            ResidentStoreActionV3::Check,
            &CancellationToken::new(),
        )?;
        let (streams, handoff_end) =
            handoff.into_original_streams(&self.owner.authority.profile)?;
        let end = handoff_end.min(consumer_end);
        let RootResidentCandidateInputsV1 {
            material,
            protocol,
            baseline,
            verifier,
        } = inputs;
        let stages = if ResidentRootAuthorityV3::readonly(&self.owner.authority) {
            OriginalCellQ24CandidateStageOwnersV1::recover_original_streams(
                material, streams, protocol, baseline,
            )
        } else {
            OriginalCellQ24CandidateStageOwnersV1::from_original_streams(
                material, streams, protocol, baseline,
            )
        }
        .map_err(|error| {
            AgentdError::Protocol(format!("original resident role admission: {error}"))
        })?;
        let stages =
            OriginalCellQ24CandidateStageOwnersV1::restrict_original_handoff_deadline(stages, end)
                .map_err(|error| {
                    AgentdError::Protocol(format!("original handoff deadline: {error}"))
                })?;
        ResidentRootAuthorityV3::perform(
            &self.owner.authority,
            ResidentStoreActionV3::Check,
            &CancellationToken::new(),
        )?;
        let (handle, runtime) = RootResidentLearningRegistrationV3::into_candidate_runtime(
            self, stages, verifier, /*capacity*/ 1,
        )?;
        Ok(RootResidentCandidateServiceV1 {
            runtime,
            handle,
            consumer,
            end,
        })
    }
}

struct CloseOriginalStream(UnixStream);

impl Drop for CloseOriginalStream {
    fn drop(&mut self) {
        let _ = self.0.shutdown(Shutdown::Both);
    }
}

impl RootResidentCandidateServiceV1 {
    /// Run the real original service and coordinator. A EOF does not cancel
    /// admitted Root work. Root cancellation/finite expiry closes the original
    /// server and joins owned work; dropping this future also closes/cancels.
    /// A remote effect already dispatched can outlive a cancelled await;
    /// only the original explicit readback path can reconcile that uncertainty.
    /// Return values describe service lifetime, never a learning disposition.
    pub async fn run(self, root_cancellation: CancellationToken) -> Result<(), AgentdError> {
        let Self {
            runtime,
            handle,
            consumer,
            end,
        } = self;
        let lifetime = end
            .checked_duration_since(Instant::now())
            .filter(|duration| !duration.is_zero())
            .ok_or_else(|| {
                AgentdError::GenerationFenced("original resident service expired".into())
            })?;
        let cancellation = root_cancellation.child_token();
        let _cancel_on_drop = cancellation.clone().drop_guard();
        let shutdown = CloseOriginalStream(consumer.stream.try_clone()?);
        let server = tokio::task::spawn_blocking(move || {
            RootResidentLearningHandleV3::serve_original_stream(
                &handle,
                consumer.stream,
                consumer.peer,
                consumer.uid,
                consumer.original_consumer_pidfd,
                consumer.timeout,
                lifetime,
            )
        });
        let run = RootResidentLearningRuntimeV3::run(runtime, cancellation.clone());
        let work = async move {
            let (runtime_result, server_result) = tokio::join!(run, server);
            runtime_result?;
            server_result
                .map_err(|error| AgentdError::Protocol(format!("resident server join: {error}")))?
                .map_err(|error| {
                    AgentdError::Protocol(format!("original resident server: {error}"))
                })
        };
        tokio::pin!(work);
        tokio::select! {
            result = &mut work => result,
            _ = root_cancellation.cancelled() => {
                cancellation.cancel();
                let _ = shutdown.0.shutdown(Shutdown::Both);
                work.await
            }
            _ = tokio::time::sleep_until(end.into()) => {
                cancellation.cancel();
                let _ = shutdown.0.shutdown(Shutdown::Both);
                let _terminal = work.await;
                Err(AgentdError::GenerationFenced("original resident service deadline elapsed; only explicit recovery may follow".into()))
            }
        }
    }
}
