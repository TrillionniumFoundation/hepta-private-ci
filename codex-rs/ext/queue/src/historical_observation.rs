//! Exact durable observations without queue reservation, wake, or dispatch.

use super::*;
use codex_thread_store::QueuedClientBindingObservation;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum QueueHistoricalTerminal {
    Completed,
    Failed,
    Interrupted,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum QueueHistoricalOutcome {
    Pending {
        queued_submission_id: Option<String>,
    },
    Persisted {
        turn_id: String,
        terminal: Option<QueueHistoricalTerminal>,
    },
    Missing,
    Unknown,
    Cancelled,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QueueHistoricalObservation {
    pub client_user_message_id: String,
    pub payload_sha256: String,
    pub outcome: QueueHistoricalOutcome,
}

/// A deliberately read-only facade retaining only the durable queue owner.
/// It never retains a dispatcher, thread manager, or outgoing event channel.
#[derive(Clone)]
pub struct QueueHistoricalObserver {
    queue: Arc<dyn QueueStore>,
}

impl QueueHistoricalObserver {
    pub fn new(queue: Arc<dyn QueueStore>) -> Self {
        Self { queue }
    }

    /// Observe the exact durable client/payload binding and explicit terminal
    /// lifecycle record. Absence and EOF never prove a terminal outcome.
    pub async fn observe(
        &self,
        thread_id: ThreadId,
        rollout_path: Option<&Path>,
        client_id: &str,
        expected_payload_sha256: &str,
    ) -> Result<QueueHistoricalObservation, QueueServiceError> {
        if client_id.is_empty() || expected_payload_sha256.is_empty() {
            return Err(QueueServiceError::InvalidInput);
        }
        let binding = self
            .queue
            .observe_client_binding(thread_id, client_id, expected_payload_sha256)
            .await?;
        // Rollout persistence can precede queue settlement, including a
        // cancellation tombstone. The exact persisted join takes precedence.
        let persisted = match scan_history(
            rollout_path,
            client_id,
            expected_payload_sha256,
            PersistedClientJoinMode::ExactHistorical(thread_id),
        )
        .await
        {
            Ok(persisted) => persisted,
            Err(QueueServiceError::HistoricalObservationIncomplete) => {
                return Ok(QueueHistoricalObservation {
                    client_user_message_id: client_id.to_string(),
                    payload_sha256: expected_payload_sha256.to_string(),
                    outcome: QueueHistoricalOutcome::Unknown,
                });
            }
            Err(error) => return Err(error),
        };
        let outcome = if let Some((turn_id, terminal)) = persisted {
            if let Some(QueuedClientBindingObservation::Persisted {
                turn_id: bound_turn_id,
            }) = &binding
                && bound_turn_id != &turn_id
            {
                return Err(QueueServiceError::AmbiguousClientIdBinding {
                    client_id: client_id.to_string(),
                });
            }
            QueueHistoricalOutcome::Persisted { turn_id, terminal }
        } else {
            match binding {
                Some(
                    QueuedClientBindingObservation::Queued(record)
                    | QueuedClientBindingObservation::Dispatching(record),
                ) => QueueHistoricalOutcome::Pending {
                    queued_submission_id: Some(record.id),
                },
                Some(QueuedClientBindingObservation::Reserved) => QueueHistoricalOutcome::Pending {
                    queued_submission_id: None,
                },
                Some(QueuedClientBindingObservation::Persisted { turn_id }) => {
                    QueueHistoricalOutcome::Persisted {
                        turn_id,
                        terminal: None,
                    }
                }
                Some(QueuedClientBindingObservation::Cancelled) => {
                    QueueHistoricalOutcome::Cancelled
                }
                None => QueueHistoricalOutcome::Missing,
            }
        };
        Ok(QueueHistoricalObservation {
            client_user_message_id: client_id.to_string(),
            payload_sha256: expected_payload_sha256.to_string(),
            outcome,
        })
    }
}

pub(super) async fn scan_history(
    rollout_path: Option<&Path>,
    client_id: &str,
    expected_sha256: &str,
    mode: PersistedClientJoinMode,
) -> Result<Option<(String, Option<QueueHistoricalTerminal>)>, QueueServiceError> {
    // A historical authority scan is complete and bounded; it never returns
    // a terminal record from a prefix. Other queue readers keep their behavior.
    const MAX_LINE_BYTES: usize = 1024 * 1024;
    const MAX_SCAN_BYTES: usize = 32 * 1024 * 1024;
    const MAX_SCAN_LINES: usize = 65_536;
    let Some(path) = rollout_path else {
        return Ok(None);
    };
    enum Reader {
        Existing(codex_rollout::RolloutLineReader),
        Bounded(codex_rollout::BoundedRolloutLineReader),
    }
    let historical = matches!(mode, PersistedClientJoinMode::ExactHistorical(_));
    let deadline = tokio::time::Instant::now() + Duration::from_secs(4);
    let opened = if historical {
        tokio::time::timeout_at(
            deadline,
            codex_rollout::open_bounded_rollout_line_reader(path, MAX_LINE_BYTES),
        )
        .await
        .map_err(|_| QueueServiceError::HistoricalObservationIncomplete)?
        .map(Reader::Bounded)
    } else {
        open_rollout_line_reader(path).await.map(Reader::Existing)
    };
    let mut reader = match opened {
        Ok(reader) => reader,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) if historical && error.kind() == std::io::ErrorKind::InvalidData => {
            return Err(QueueServiceError::HistoricalObservationIncomplete);
        }
        Err(error) => return Err(queue_rollout_error(path, "open", error)),
    };
    let mut current_turn_id = None;
    let mut pending_recovery_unready = None;
    let mut recovery_restart_turn_id = None;
    let mut found = None;
    let mut terminal = None;
    let mut legacy_turn_ids = HashSet::new();
    let mut legacy_without_digest = false;
    let mut scan_bytes = 0usize;
    let mut scan_lines = 0usize;
    let mut first_record = true;
    loop {
        let read = async {
            match &mut reader {
                Reader::Existing(reader) => reader.next_line().await,
                Reader::Bounded(reader) => reader.next_line().await,
            }
        };
        let line = if historical {
            tokio::time::timeout_at(deadline, read)
                .await
                .map_err(|_| QueueServiceError::HistoricalObservationIncomplete)?
        } else {
            read.await
        };
        let Some(line) = line.map_err(|error| {
            if historical && error.kind() == std::io::ErrorKind::InvalidData {
                QueueServiceError::HistoricalObservationIncomplete
            } else {
                queue_rollout_error(path, "read", error)
            }
        })?
        else {
            break;
        };
        scan_lines = scan_lines.saturating_add(1);
        scan_bytes = scan_bytes.saturating_add(line.len().saturating_add(1));
        if historical && (scan_bytes > MAX_SCAN_BYTES || scan_lines > MAX_SCAN_LINES) {
            return Err(QueueServiceError::HistoricalObservationIncomplete);
        }
        if line.trim().is_empty() {
            continue;
        }
        let record = serde_json::from_str::<RolloutLine>(&line).map_err(|error| {
            if historical {
                return QueueServiceError::HistoricalObservationIncomplete;
            }
            QueueServiceError::Storage(ThreadStoreError::Internal {
                message: format!(
                    "failed to decode rollout `{}` during queue reconciliation: {error}",
                    path.display()
                ),
            })
        })?;
        if first_record
            && let PersistedClientJoinMode::ExactHistorical(thread_id) = mode
            && !matches!(&record.item, RolloutItem::SessionMeta(metadata) if metadata.meta.id == thread_id)
        {
            return Err(malformed_rollout_turn_boundary(
                "historical rollout does not begin with its owning thread identity".to_string(),
            ));
        }
        first_record = false;
        let update = match &record.item {
            RolloutItem::EventMsg(EventMsg::TurnComplete(event)) => Some((
                event.turn_id.clone(),
                Some(if event.error.is_some() {
                    QueueHistoricalTerminal::Failed
                } else {
                    QueueHistoricalTerminal::Completed
                }),
            )),
            RolloutItem::EventMsg(EventMsg::TurnAborted(event)) => event
                .turn_id
                .clone()
                .map(|id| (id, Some(QueueHistoricalTerminal::Interrupted))),
            RolloutItem::EventMsg(EventMsg::TurnStarted(event)) => {
                Some((event.turn_id.clone(), None))
            }
            RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(event))
                if event.state == TurnRecoveryCandidateState::Unready =>
            {
                Some((event.turn_id.clone(), None))
            }
            _ => None,
        };
        // Validate all boundaries and the exact normalized UserMessage item
        // before accepting lifecycle evidence. This is the dispatch scanner,
        // including its strict consumed recovery hand-off checks.
        scan_persisted_client_line(
            record.item,
            client_id,
            expected_sha256,
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
            &mut found,
            &mut legacy_turn_ids,
            &mut legacy_without_digest,
        )?;
        if let Some((id, state)) = update
            && found.as_deref() == Some(id.as_str())
        {
            terminal = state;
        }
    }
    if let Some(turn_id) = recovery_restart_turn_id {
        return Err(malformed_rollout_turn_boundary(format!(
            "recovery hand-off for turn `{turn_id}` was not followed by a turn start"
        )));
    }
    if legacy_turn_ids
        .iter()
        .any(|id| found.as_deref() != Some(id.as_str()))
    {
        if mode == PersistedClientJoinMode::LegacyCompatibility
            && found.is_none()
            && legacy_turn_ids.len() == 1
            && !legacy_without_digest
        {
            return Ok(legacy_turn_ids.into_iter().next().map(|id| (id, None)));
        }
        return Err(QueueServiceError::LegacyClientIdBinding {
            client_id: client_id.to_string(),
        });
    }
    Ok(found.map(|id| (id, terminal)))
}

#[cfg(test)]
#[path = "historical_observation_tests.rs"]
mod tests;
