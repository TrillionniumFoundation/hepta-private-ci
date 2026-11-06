//! One original Objective sender and its actual, kernel-authenticated Agentd transport.
//! This Linux composition never creates a writer, issuer, checkpoint or retry grant.

use super::*;
use codex_hepta_memory::ObjectiveSenderCheckpoint;
use codex_hepta_memory::ObjectiveSenderError;
use codex_hepta_memory::ObjectiveSenderObservation;
use codex_hepta_memory::ObjectiveSenderObservationKind;
use codex_hepta_memory::ObjectiveSenderRequest;
use codex_hepta_memory::ObjectiveSenderSnapshot;
use codex_hepta_memory::ObjectiveSenderTicket;
use codex_hepta_memory::ProductionObjectiveSender;
use tokio_util::sync::CancellationToken;

#[path = "objective_client_observation.rs"]
mod observation;
#[path = "objective_client_transport.rs"]
mod transport;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AgentdObjectivePeer {
    pub uid: u32,
    pub pid: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectiveClientMode {
    Initial,
    Recovered,
}

/// A close-only fence. A retired window cannot be reopened by a callback.
#[derive(Clone)]
pub struct AgentdObjectiveWindow {
    closed: CancellationToken,
}

impl AgentdObjectiveWindow {
    pub fn close(&self) {
        self.closed.cancel();
    }

    pub fn is_live(&self) -> bool {
        !self.closed.is_cancelled()
    }

    #[cfg(feature = "desktop-objective-ui")]
    pub(crate) async fn cancelled(&self) {
        self.closed.cancelled().await;
    }
}

#[derive(Debug, thiserror::Error)]
pub enum AgentdObjectiveClientError {
    #[error(transparent)]
    Owner(#[from] ObjectiveSenderError),
    #[error(transparent)]
    Agentd(#[from] AgentdError),
    #[error("the original Objective transport identity differs")]
    Binding,
    #[error("the Objective window has been retired")]
    Retired,
    #[error("this original Objective has no unused local send opportunity")]
    AlreadyAttempted,
    #[error("the Objective observation does not match the original request")]
    Observation,
}

/// A fresh result and the last independently acknowledged immutable publication.
/// An unknown fresh lookup never erases an earlier publication or implies absence.
pub struct AgentdObjectiveHistory {
    pub latest: crate::ObjectiveAdmissionOutcome,
    pub retained_publication: Option<crate::ObjectiveAdmissionPublication>,
    current_generation: u64,
}

impl AgentdObjectiveHistory {
    /// The authenticated daemon's lifecycle witness for this fresh lookup.
    /// It is distinct from the process spawn generation and grants no authority.
    pub fn current_generation(&self) -> u64 {
        self.current_generation
    }
}

pub struct AgentdObjectiveClient<C: ObjectiveSenderCheckpoint> {
    client: AgentdClient,
    sender: ProductionObjectiveSender<C>,
    original: ObjectiveSenderRequest,
    peer: AgentdObjectivePeer,
    ticket: Option<ObjectiveSenderTicket>,
    attempted: bool,
    cancellation_attempted: bool,
    window: AgentdObjectiveWindow,
}

impl AgentdClient {
    /// Trusted host composition only. The peer is the independently configured
    /// current daemon identity, checked against kernel credentials on every I/O.
    /// A recovered binding may observe an earlier daemon generation; it can
    /// neither send that request again nor cancel a new generation's run.
    pub fn bind_original_objective<C: ObjectiveSenderCheckpoint>(
        self,
        sender: ProductionObjectiveSender<C>,
        original: ObjectiveSenderRequest,
        peer: AgentdObjectivePeer,
        mode: ObjectiveClientMode,
    ) -> Result<AgentdObjectiveClient<C>, AgentdObjectiveClientError> {
        let origin = original.origin();
        if original
            .exact_original()
            .iter()
            .any(|byte| matches!(byte, b'\n' | b'\r'))
            || self.expected_agent_id != origin.agent_id
            || self.socket_path.to_str() != Some(origin.endpoint_identity.as_str())
            || peer.pid == 0
            || i32::try_from(peer.pid).is_err()
            || (mode == ObjectiveClientMode::Initial
                && (self.spawn_generation != origin.spawn_generation
                    || peer.uid != origin.expected_peer_uid
                    || peer.pid != origin.expected_peer_pid))
        {
            return Err(AgentdObjectiveClientError::Binding);
        }
        self.next_request_id
            .fetch_max(origin.request_id.saturating_add(1), Ordering::Relaxed);
        Ok(AgentdObjectiveClient {
            client: self,
            sender,
            original,
            peer,
            ticket: None,
            attempted: mode == ObjectiveClientMode::Recovered,
            cancellation_attempted: false,
            window: AgentdObjectiveWindow {
                closed: CancellationToken::new(),
            },
        })
    }
}

impl<C: ObjectiveSenderCheckpoint> AgentdObjectiveClient<C> {
    pub fn window(&self) -> AgentdObjectiveWindow {
        self.window.clone()
    }

    pub fn original(&self) -> &ObjectiveSenderRequest {
        &self.original
    }

    fn require_live(&self) -> Result<(), AgentdObjectiveClientError> {
        if self.window.is_live() {
            Ok(())
        } else {
            Err(AgentdObjectiveClientError::Retired)
        }
    }

    async fn retain_initial(&mut self) -> Result<(), AgentdObjectiveClientError> {
        self.require_live()?;
        if self.attempted {
            return Err(AgentdObjectiveClientError::AlreadyAttempted);
        }
        // Claim before any await. Cancellation or a lost checkpoint ACK cannot
        // re-enter this path with a new request, signature or send opportunity.
        self.attempted = true;
        self.ticket = Some(
            self.sender
                .retain_before_send(self.original.clone())
                .await?,
        );
        self.require_live()
    }

    /// Exact original bytes reach the existing ObjectiveStart endpoint once.
    /// Publication is an admission observation, never model/effect completion.
    pub async fn submit_once(
        &mut self,
    ) -> Result<ObjectiveStartOutcome, AgentdObjectiveClientError> {
        self.retain_initial().await?;
        let ticket = self
            .ticket
            .as_ref()
            .ok_or(AgentdObjectiveClientError::Observation)?;
        self.sender.mark_send_started(ticket).await?;
        self.require_live()?;
        let original = std::str::from_utf8(self.original.exact_original())
            .map_err(|_| AgentdObjectiveClientError::Binding)?;
        let origin = self.original.origin();
        let frame = format!(
            "{{\"schema_version\":{},\"request_id\":{},\"spawn_generation\":{},\"method\":{{\"type\":\"objective_start\",\"request\":{original}}}}}\n",
            AGENTD_CONTROL_SCHEMA_VERSION, origin.request_id, origin.spawn_generation
        );
        let (response, raw) = self
            .send_frame(origin.request_id, frame.into_bytes())
            .await?;
        let outcome = match response.payload {
            AgentdPayload::ObjectiveRun(receipt)
                if receipt.run_id == self.original.identity().run_id =>
            {
                ObjectiveStartOutcome::Admitted { receipt }
            }
            AgentdPayload::ObjectiveConflict {
                run_id,
                conflict_digest,
            } if run_id == self.original.identity().run_id => ObjectiveStartOutcome::Conflict {
                run_id,
                conflict_digest,
            },
            payload @ AgentdPayload::Error { .. } => {
                self.sender
                    .retain_observation(
                        ticket,
                        &ObjectiveSenderObservation::from_original(
                            ObjectiveSenderObservationKind::Submission,
                            raw,
                        )
                        .map_err(ObjectiveSenderError::from)?,
                    )
                    .await?;
                return unexpected(payload).map_err(Into::into);
            }
            payload => return unexpected(payload).map_err(Into::into),
        };
        self.sender
            .retain_observation(
                ticket,
                &ObjectiveSenderObservation::from_original(
                    ObjectiveSenderObservationKind::Submission,
                    raw,
                )
                .map_err(ObjectiveSenderError::from)?,
            )
            .await?;
        self.require_live()?;
        Ok(outcome)
    }

    /// Explicit cancellation before transport retains the original permanent
    /// fence too. It cannot turn an unknown/started/recovered send into "unsent".
    pub async fn cancel_local(&mut self) -> Result<(), AgentdObjectiveClientError> {
        self.require_live()?;
        if !self.attempted {
            self.retain_initial().await?;
        }
        let ticket = self
            .ticket
            .as_ref()
            .ok_or(AgentdObjectiveClientError::AlreadyAttempted)?;
        self.sender.retain_local_cancellation(ticket).await?;
        self.require_live()
    }

    async fn recover_handle(&mut self) -> Result<(), AgentdObjectiveClientError> {
        self.require_live()?;
        if self.ticket.is_none() {
            // A missing row remains missing: recovery never retains a new row.
            self.attempted = true;
            self.ticket = Some(self.sender.recover_pending(self.original.clone()).await?);
        }
        Ok(())
    }

    /// A committed local cancellation becomes visible only after an independent
    /// current-cut acknowledgement, including after its original ACK was lost.
    pub async fn acknowledged_local_cancellation(
        &mut self,
    ) -> Result<bool, AgentdObjectiveClientError> {
        self.recover_handle().await?;
        let ticket = self
            .ticket
            .as_ref()
            .ok_or(AgentdObjectiveClientError::Observation)?;
        let cancelled = self
            .sender
            .snapshot_acknowledged(ticket)
            .await?
            .locally_cancelled;
        self.require_live()?;
        Ok(cancelled)
    }

    pub async fn refresh(&mut self) -> Result<AgentdObjectiveHistory, AgentdObjectiveClientError> {
        self.recover_handle().await?;
        let ticket = self
            .ticket
            .as_ref()
            .ok_or(AgentdObjectiveClientError::Observation)?;
        let snapshot = self.sender.snapshot_acknowledged(ticket).await?;
        let retained = publication(&snapshot, &self.original)
            .map_err(|_| AgentdObjectiveClientError::Observation)?;
        let query = crate::ObjectiveAdmissionQuery {
            request: serde_json::from_slice(self.original.exact_original())
                .map_err(AgentdError::from)?,
            anchor: retained
                .as_ref()
                .map(|value| crate::ObjectiveJournalAnchor {
                    sequence: value.publication_sequence,
                    chain_digest: value.chain_digest.clone(),
                }),
        };
        let (response, raw) = self
            .send_method(crate::AgentdMethod::ObjectiveAdmission { query })
            .await?;
        let current_generation = response.current_generation;
        let latest = match &response.payload {
            AgentdPayload::ObjectiveAdmission { outcome } => outcome.clone(),
            payload => return unexpected(payload.clone()).map_err(Into::into),
        };
        if let crate::ObjectiveAdmissionOutcome::Published { publication: value } = &latest {
            validate_publication(value, &self.original)
                .map_err(|_| AgentdObjectiveClientError::Observation)?;
        }
        let next = match &latest {
            crate::ObjectiveAdmissionOutcome::Published { publication } => {
                Some((**publication).clone())
            }
            crate::ObjectiveAdmissionOutcome::Unknown { .. } => retained,
        };
        self.retain_current_response(ticket, &response, raw, next.as_ref())
            .await?;
        self.require_live()?;
        Ok(AgentdObjectiveHistory {
            latest,
            retained_publication: next,
            current_generation,
        })
    }

    /// Query the original runtime only after a fresh, matching publication.
    /// The receipt's phase and terminal flag remain the original owner's values.
    pub async fn current_run(&mut self) -> Result<AgentRunReceipt, AgentdObjectiveClientError> {
        if self.client.spawn_generation != self.original.origin().spawn_generation {
            return Err(AgentdObjectiveClientError::Binding);
        }
        let history = self.refresh().await?;
        self.run_after_history(&history).await
    }

    // This method stays private: an untrusted renderer cannot supply a made-up
    // admission as authority to inspect or cancel another runtime.
    async fn run_after_history(
        &self,
        history: &AgentdObjectiveHistory,
    ) -> Result<AgentRunReceipt, AgentdObjectiveClientError> {
        if self.client.spawn_generation != self.original.origin().spawn_generation
            || !matches!(
                history.latest,
                crate::ObjectiveAdmissionOutcome::Published { ref publication }
                    if matches!(publication.outcome, crate::ObjectivePublicationOutcome::Compiled { .. })
            )
        {
            return Err(AgentdObjectiveClientError::Observation);
        }
        let (response, raw) = self
            .send_method(crate::AgentdMethod::RunStatus {
                run_id: self.original.identity().run_id.clone(),
            })
            .await?;
        match &response.payload {
            AgentdPayload::RunStatus { run: Some(receipt) }
                if receipt.run_id == self.original.identity().run_id
                    && receipt.generation == history.current_generation
                    && response.current_generation == history.current_generation =>
            {
                let ticket = self
                    .ticket
                    .as_ref()
                    .ok_or(AgentdObjectiveClientError::Observation)?;
                self.retain_current_response(
                    ticket,
                    &response,
                    raw,
                    history.retained_publication.as_ref(),
                )
                .await?;
                self.require_live()?;
                Ok(receipt.clone())
            }
            payload => unexpected(payload.clone()).map_err(Into::into),
        }
    }

    /// Read admission and, when available in the same generation, the runtime.
    /// No polling task or retry is created. Distinct complete replies, including
    /// terminal run receipts, are retained and acknowledged before returning.
    /// Identical states with new correlation IDs re-acknowledge existing bytes.
    pub async fn observe_current(
        &mut self,
    ) -> Result<(AgentdObjectiveHistory, Option<AgentRunReceipt>), AgentdObjectiveClientError> {
        let history = self.refresh().await?;
        let run = self.run_after_history(&history).await.ok();
        Ok((history, run))
    }

    /// Cancel the freshly observed original run revision once. A stale revision
    /// or lost reply is returned to the caller; this method never retries.
    pub async fn cancel_current(
        &mut self,
        reason: String,
    ) -> Result<AgentRunCancellation, AgentdObjectiveClientError> {
        if self.cancellation_attempted {
            return Err(AgentdObjectiveClientError::AlreadyAttempted);
        }
        self.cancellation_attempted = true;
        let current = self.current_run().await?;
        let generation = current.generation;
        let (response, raw) = self
            .send_method(crate::AgentdMethod::RunCancel {
                run_id: current.run_id,
                expected_revision: current.revision,
                reason,
            })
            .await?;
        let cancellation = match response.payload {
            AgentdPayload::RunCancellation(value)
                if value.receipt.run_id == self.original.identity().run_id
                    && value.receipt.generation == generation
                    && response.current_generation == generation =>
            {
                value
            }
            payload => return unexpected(payload).map_err(Into::into),
        };
        let ticket = self
            .ticket
            .as_ref()
            .ok_or(AgentdObjectiveClientError::Observation)?;
        self.sender
            .retain_observation(
                ticket,
                &ObjectiveSenderObservation::from_original(
                    ObjectiveSenderObservationKind::History,
                    raw,
                )
                .map_err(ObjectiveSenderError::from)?,
            )
            .await?;
        self.require_live()?;
        Ok(cancellation)
    }
}

impl<C: ObjectiveSenderCheckpoint> Drop for AgentdObjectiveClient<C> {
    fn drop(&mut self) {
        self.window.close();
    }
}

fn validate_publication(
    value: &crate::ObjectiveAdmissionPublication,
    original: &ObjectiveSenderRequest,
) -> Result<(), ObjectiveSenderError> {
    let id = original.identity();
    if value.run_id != id.run_id
        || value.original_spawn_generation != id.body_spawn_generation
        || value.issuer_id != id.issuer_id
        || value.key_epoch != id.key_epoch
        || value.message_id != id.message_id
        || value.message_sequence != id.sequence
        || value.expires_at_ms != id.expires_at_ms
        || value.signed_body_digest != id.signed_body_sha256.as_str()
        || value.publication_sequence == 0
    {
        return Err(ObjectiveSenderError::ObservationConflict);
    }
    for digest in [
        &value.profile_digest,
        &value.publication_digest,
        &value.chain_digest,
    ] {
        codex_hepta_contracts::Sha256Digest::parse(digest)
            .map_err(|_| ObjectiveSenderError::ObservationConflict)?;
    }
    Ok(())
}

fn publication(
    snapshot: &ObjectiveSenderSnapshot,
    original: &ObjectiveSenderRequest,
) -> Result<Option<crate::ObjectiveAdmissionPublication>, ObjectiveSenderError> {
    let mut retained: Option<crate::ObjectiveAdmissionPublication> = None;
    for observed in &snapshot.observations {
        let response: AgentdResponse = serde_json::from_slice(observed.exact_original())
            .map_err(|_| ObjectiveSenderError::ObservationConflict)?;
        if response.agent_id != original.origin().agent_id
            || response.schema_version != AGENTD_CONTROL_SCHEMA_VERSION
            || response.request_id == 0
        {
            return Err(ObjectiveSenderError::ObservationConflict);
        }
        if let AgentdPayload::ObjectiveAdmission {
            outcome: crate::ObjectiveAdmissionOutcome::Published { publication },
        } = response.payload
        {
            validate_publication(&publication, original)?;
            if retained
                .as_ref()
                .is_some_and(|before| before != publication.as_ref())
            {
                return Err(ObjectiveSenderError::ObservationConflict);
            }
            retained = Some(*publication);
        }
    }
    Ok(retained)
}
