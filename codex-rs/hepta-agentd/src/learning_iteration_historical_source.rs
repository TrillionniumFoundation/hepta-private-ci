//! A new recipient's bounded delivery of the same Root-observed historical A.
//! This retains no old writer or Automation outbox. A new explicit journal
//! witnesses dispatch; prior Pending permits only the original Root readback.

use std::fs::File;
use std::sync::Mutex;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_neuron::FileAnchorWitnessStore;

use super::*;
use crate::CellQ24PreparedLearningV1;
use crate::OriginalCellQ24LearningOpenV1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as JournalError;
use crate::learning_owner_journal::LearningOwnerJournalV1;
use crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1;
use crate::root_historical_task_read_client::RootHistoricalTaskReadClientV1;

#[path = "learning_iteration_terminal_acceptance.rs"]
mod terminal_acceptance;

pub(crate) struct RegisteredHistoricalLearningSourceV1 {
    receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
    prepared: Arc<CellQ24PreparedLearningV1>,
    identity: AgentdIdentity,
    end: Instant,
    terminal_acceptance: Mutex<
        Option<crate::root_completed_learning_history::OriginalCompletedLearningAcceptanceV1>,
    >,
}

impl RegisteredHistoricalLearningSourceV1 {
    pub(crate) fn require_original_stage_operation(
        &self,
        identity: &AgentdIdentity,
        read: &crate::cell_composed_q24::OriginalPreparedReadV1<'_>,
    ) -> Result<(), AgentdError> {
        if identity != &self.identity || Instant::now() >= self.end {
            return Err(refused("original historical stage owner or end differs"));
        }
        self.prepared
            .require_historical_source_in_operation(&self.receipt, read)
            .map_err(refused)?;
        if Instant::now() >= self.end {
            return Err(refused("original historical stage deadline"));
        }
        Ok(())
    }

    pub(crate) fn capture_original_historical_source(
        receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
        prepared: Arc<CellQ24PreparedLearningV1>,
        client: &Arc<RootHistoricalTaskReadClientV1>,
        session: &crate::AgentdRootAuthoritySession,
        identity: AgentdIdentity,
        end: Instant,
    ) -> Result<Arc<Self>, AgentdError> {
        receipt.require_original_client(client, session)?;
        if receipt.initial_snapshot().request.agent_id.as_str() != identity.agent_id.as_str() {
            return Err(refused("original recipient agent differs"));
        }
        let terminal_acceptance =
            RootHistoricalTaskReadClientV1::retain_original_completed_acceptance(
                client, session, &identity,
            )?;
        let source: Arc<RegisteredHistoricalLearningSourceV1> = Arc::new(Self {
            receipt,
            prepared,
            identity,
            end,
            terminal_acceptance: Mutex::new(Some(terminal_acceptance)),
        });
        source
            .require_current_historical_source(&source.identity)
            .inspect_err(|_| {
                let _ = std::io::Write::write_all(
                    &mut std::io::stderr(),
                    b"daemon_stage=historical.source.capture\n",
                );
            })?;
        source.receipt.require_original_client(client, session)?;
        Ok(source)
    }

    pub(crate) fn capture_original_historical_source_in_operation(
        receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
        prepared: Arc<CellQ24PreparedLearningV1>,
        client: &Arc<RootHistoricalTaskReadClientV1>,
        session: &crate::AgentdRootAuthoritySession,
        identity: AgentdIdentity,
        end: Instant,
        read: &crate::cell_composed_q24::OriginalPreparedReadV1<'_>,
    ) -> Result<Arc<Self>, AgentdError> {
        receipt.require_original_client(client, session)?;
        if receipt.initial_snapshot().request.agent_id.as_str() != identity.agent_id.as_str() {
            return Err(refused("original recipient agent differs"));
        }
        let terminal_acceptance =
            RootHistoricalTaskReadClientV1::retain_original_completed_acceptance(
                client, session, &identity,
            )?;
        let source: Arc<RegisteredHistoricalLearningSourceV1> = Arc::new(Self {
            receipt,
            prepared,
            identity,
            end,
            terminal_acceptance: Mutex::new(Some(terminal_acceptance)),
        });
        source
            .require_original_stage_operation(&source.identity, read)
            .inspect_err(|_| {
                let _ = std::io::Write::write_all(
                    &mut std::io::stderr(),
                    b"daemon_stage=historical.source.capture_operation\n",
                );
            })?;
        source.receipt.require_original_client(client, session)?;
        Ok(source)
    }

    pub(crate) fn require_current_historical_source(
        &self,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        if identity != &self.identity || Instant::now() >= self.end {
            return Err(refused("historical recipient or original end differs"));
        }
        self.prepared
            .require_original_historical_source(&self.receipt)
            .map_err(refused)?;
        if Instant::now() >= self.end {
            return Err(refused("historical source deadline"));
        }
        Ok(())
    }

    pub(crate) fn require_prepared_historical_source(
        &self,
        prepared: &CellQ24PreparedLearningV1,
    ) -> Result<(), AgentdError> {
        if !std::ptr::eq(self.prepared.as_ref(), prepared) {
            return Err(refused("different actual prepared Dataset owner"));
        }
        self.require_current_historical_source(&self.identity)
    }

    pub(crate) fn request(&self) -> &LearningIterationRequestV1 {
        &self.prepared.initial().request
    }
}

pub(crate) struct OriginalHistoricalLearningDeliveryV1 {
    source: Arc<RegisteredHistoricalLearningSourceV1>,
    journal: LearningOwnerJournalV1<FileAnchorWitnessStore>,
    key: ProductEvaluationExecutionKeyV1,
    continuation: Option<crate::production_launcher::OriginalPostAContinuationV1>,
}

impl LearningIterationRuntimeBootstrapV1 {
    pub(crate) fn with_original_historical_source(
        self,
        source: Arc<RegisteredHistoricalLearningSourceV1>,
        identity: &AgentdIdentity,
        journal: File,
        witness: FileAnchorWitnessStore,
        mode: OriginalCellQ24LearningOpenV1,
    ) -> Result<Self, AgentdError> {
        self.require_identity(identity)?;
        let original: Arc<crate::OriginalCellQ24LearningStageOwnersV1> = Arc::clone(
            self.original_q24
                .as_ref()
                .ok_or_else(|| refused("actual assembled Q24 owners absent"))?,
        );
        let prepared: &CellQ24PreparedLearningV1 = original.prepared();
        prepared
            .with_original_prepared_operation(|read| {
                self.with_original_historical_source_in_operation(
                    source, identity, journal, witness, mode, read,
                )
            })
            .map_err(refused)?
    }

    pub(crate) fn with_original_historical_source_in_operation(
        mut self,
        source: Arc<RegisteredHistoricalLearningSourceV1>,
        identity: &AgentdIdentity,
        journal: File,
        witness: FileAnchorWitnessStore,
        mode: OriginalCellQ24LearningOpenV1,
        read: &crate::cell_composed_q24::OriginalPreparedReadV1<'_>,
    ) -> Result<Self, AgentdError> {
        self.require_identity(identity)?;
        let original: &Arc<crate::OriginalCellQ24LearningStageOwnersV1> = self
            .original_q24
            .as_ref()
            .ok_or_else(|| refused("actual assembled Q24 owners absent"))?;
        let prepared: &CellQ24PreparedLearningV1 = original.prepared();
        crate::cell_composed_q24::OriginalPreparedReadV1::require_prepared(read, prepared)
            .map_err(refused)?;
        let (key, journal) = (|| -> Result<_, AgentdError> {
            source.require_original_stage_operation(identity, read)?;
            let registry = self
                .circuit_delivery_registry
                .as_ref()
                .ok_or_else(|| refused("original source registry absent"))?;
            if self.retained_source.is_some()
                || self.historical_source.is_some()
                || self.historical_delivery.is_some()
                || !self.enforce_circuit_admission
                || !matches!(
                    self.circuit_delivery_source,
                    CircuitLearningSourceV1::OriginalQ24
                )
                || self.scope.as_ref() != Some(prepared.scope())
                || self.owners != prepared.initial().owners
                || registry.requests.as_slice() != std::slice::from_ref(source.request())
            {
                return Err(refused(
                    "historical delivery differs from original Root assembly",
                ));
            }
            source.require_original_stage_operation(identity, read)?;
            let key = ProductEvaluationExecutionKeyV1 {
                plan_id: source.request().operation_id.clone(),
                binding_digest: Digest32::of_parts(&[
                    b"hepta.agentd.original-historical-learning-delivery.v1\0",
                    crate::neuron_generation_process_identity_digest_v1(identity)?.as_array(),
                    prepared.initial().head_digest.as_array(),
                    prepared.scope().binding().as_array(),
                ]),
            };
            let journal = match mode {
                OriginalCellQ24LearningOpenV1::Create => {
                    LearningOwnerJournalV1::create(journal, witness, key.binding_digest)
                }
                OriginalCellQ24LearningOpenV1::Recover => {
                    LearningOwnerJournalV1::recover(journal, witness, key.binding_digest)
                }
            }
            .map_err(refused)?;
            source.require_original_stage_operation(identity, read)?;
            Ok((key, journal))
        })()?;
        crate::cell_composed_q24::OriginalPreparedReadV1::require_prepared(read, prepared)
            .map_err(refused)?;
        self.historical_source = Some(Arc::clone(&source));
        self.historical_delivery = Some(OriginalHistoricalLearningDeliveryV1 {
            source,
            journal,
            key,
            continuation: None,
        });
        Ok(self)
    }

    pub(crate) fn with_original_post_a_continuation(
        mut self,
        continuation: crate::production_launcher::OriginalPostAContinuationV1,
        identity: &AgentdIdentity,
    ) -> Result<Self, AgentdError> {
        self.require_identity(identity)?;
        let owners = self
            .original_q24
            .as_ref()
            .ok_or_else(|| refused("original Q24 aggregate absent"))?;
        let delivery = self
            .historical_delivery
            .as_mut()
            .ok_or_else(|| refused("original historical delivery absent"))?;
        if delivery.continuation.is_some() {
            return Err(refused("original post-A continuation already installed"));
        }
        crate::production_launcher::OriginalPostAContinuationV1::require_original_delivery(
            &continuation,
            &delivery.source,
            owners,
            identity,
        )?;
        delivery.continuation = Some(continuation);
        Ok(self)
    }
}

impl OriginalHistoricalLearningDeliveryV1 {
    pub(super) fn require_original_source(
        &self,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        self.source.require_current_historical_source(identity)
    }

    pub(super) async fn run(
        mut self,
        handle: LearningIterationHandleV1,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let Some(continuation) = self.continuation.take() else {
            return self.run_delivery(handle, state, cancellation).await;
        };
        let joined = cancellation.child_token();
        // The continuation's original physical source preflight must finish
        // before delivery can submit Restore to the same Historical client.
        // This consumes the concrete continuation once; no Root read crosses
        // the await, and no journal claim exists yet on this fresh path.
        let continuation = match crate::production_launcher::OriginalPostAContinuationV1::prepare_original_delivery(
            continuation,
            Arc::clone(&state),
            joined.clone(),
        )
        .await
        {
            Ok(Some(continuation)) => continuation,
            Ok(None) => return Ok(()),
            Err(error) => {
                let _ = std::io::Write::write_fmt(
                    &mut std::io::stderr(),
                    format_args!(
                        "daemon_stage=historical.continuation.original_result error={error:?}\n"
                    ),
                );
                joined.cancel();
                return Err(error);
            }
        };
        let delivery_cancelled = joined.clone();
        let continuation_cancelled = joined.clone();
        let delivery = self.run_delivery(handle, Arc::clone(&state), joined.clone());
        let continuation = continuation.run_original_prepared_continuation();
        // Both owned futures remain joined after an error or shutdown. An
        // original publisher or issuer already in progress is never detached.
        let first_failure = AtomicU8::new(0);
        let (delivery, continuation) = tokio::join!(
            async {
                let result = delivery.await;
                if result.is_err() {
                    let _ =
                        first_failure.compare_exchange(0, 1, Ordering::AcqRel, Ordering::Acquire);
                    if let Err(error) = &result {
                        let _ = std::io::Write::write_fmt(
                            &mut std::io::stderr(),
                            format_args!(
                                "daemon_stage=historical.delivery.joined_result error={error:?}\n"
                            ),
                        );
                    }
                    delivery_cancelled.cancel();
                }
                result
            },
            async {
                let result = continuation.await;
                if result.is_err() {
                    let _ =
                        first_failure.compare_exchange(0, 2, Ordering::AcqRel, Ordering::Acquire);
                    if let Err(error) = &result {
                        let _ = std::io::Write::write_fmt(
                            &mut std::io::stderr(),
                            format_args!(
                                "daemon_stage=historical.continuation.original_result error={error:?}\n"
                            ),
                        );
                    }
                    continuation_cancelled.cancel();
                }
                result
            },
        );
        // A failed continuation cancels delivery, which must retain its Pending
        // journal. That secondary uncertainty must not replace the actual cause.
        // Both futures have still joined before either original error escapes.
        if first_failure.load(Ordering::Acquire) == 2 {
            continuation?;
            return delivery;
        }
        delivery?;
        continuation
    }

    async fn run_delivery(
        mut self,
        handle: LearningIterationHandleV1,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        loop {
            tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                _ = tokio::time::sleep(Duration::from_millis(50)) => {}
            }
            if require_ready(&state).is_ok() && state.automation_admission_ready()? {
                break;
            }
            if Instant::now() >= self.source.end {
                return Err(refused("historical delivery deadline"));
            }
        }
        let source: Arc<RegisteredHistoricalLearningSourceV1> = Arc::clone(&self.source);
        // The real witnessed claim and its source postcheck are synchronous.
        // Only the owned reservation and same-journal claim survive; the read
        // does not enter the later submit await or its separate completion.
        let (reservation, existing, claim) = source
            .prepared
            .with_original_prepared_operation(|read| -> Result<_, AgentdError> {
                source.require_original_stage_operation(state.identity(), read)?;
                let reservation = handle.reserve().map_err(refused)?;
                let existing = self.journal.read(&self.key);
                let claim = if matches!(
                    &existing,
                    Err(JournalError::Store(
                        ProductEvaluationExecutionStoreErrorV1::Missing
                    ))
                ) {
                    Some(
                        self.journal
                            .prepare_original_historical_delivery(&self.key)
                            .map_err(refused)?,
                    )
                } else {
                    None
                };
                source.require_original_stage_operation(state.identity(), read)?;
                Ok((reservation, existing, claim))
            })
            .map_err(refused)??;
        let snapshot = match existing {
            Ok(saved) => {
                drop(claim);
                let snapshot = self.readback(reservation, &cancellation).await?;
                if saved.as_slice() != snapshot.head_digest.as_array() {
                    return Err(refused("original delivery head differs"));
                }
                require_complete(&self.source, &snapshot)?;
                self.source
                    .require_current_historical_source(state.identity())?;
                snapshot
            }
            Err(JournalError::Pending) => {
                drop(claim);
                let snapshot = self.readback(reservation, &cancellation).await?;
                require_complete(&self.source, &snapshot)?;
                self.source
                    .require_current_historical_source(state.identity())?;
                snapshot
            }
            Err(JournalError::Store(ProductEvaluationExecutionStoreErrorV1::Missing)) => {
                let claim = match claim {
                    Some(crate::learning_owner_journal::OriginalHistoricalDeliveryPreparationV1::Claimed(claim)) => claim,
                    Some(crate::learning_owner_journal::OriginalHistoricalDeliveryPreparationV1::Completed(_)) | None => {
                        return Err(refused("new delivery did not execute its original claim"));
                    }
                };
                let result = tokio::select! {
                    _ = cancellation.cancelled() => Err(LearningIterationRuntimeErrorV1::CommitUncertain),
                    result = tokio::time::timeout_at(source.end.into(), reservation.submit(source.request().clone())) =>
                        result.unwrap_or(Err(LearningIterationRuntimeErrorV1::CommitUncertain)),
                }.map_err(|error| {
                    let _ = std::io::Write::write_fmt(
                        &mut std::io::stderr(),
                        format_args!("daemon_stage=historical.delivery.original_result error={error:?}\n"),
                    );
                    refused(JournalError::Pending)
                })?;
                // Dispatch returned before this fresh source borrow begins.
                // Its two physical Root observations surround the actual
                // journal completion and all original completion postchecks.
                source
                    .prepared
                    .with_original_prepared_operation(|read| {
                        require_complete(&source, &result).map_err(|_| {
                            JournalError::Binding("original Root delivery is incomplete")
                        })?;
                        source
                            .require_original_stage_operation(state.identity(), read)
                            .map_err(|_| {
                                JournalError::Binding("post-dispatch historical source")
                            })?;
                        claim
                            .complete_original_historical_delivery(result.head_digest.as_array())?;
                        require_complete(&source, &result).map_err(|_| {
                            JournalError::Binding("original Root delivery is incomplete")
                        })?;
                        source
                            .require_original_stage_operation(state.identity(), read)
                            .map_err(|_| {
                                JournalError::Binding("post-complete historical source")
                            })?;
                        Ok::<_, JournalError>(result)
                    })
                    .map_err(refused)?
                    .map_err(refused)?
            }
            Err(error) => return Err(refused(error)),
        };
        require_complete(&self.source, &snapshot)?;
        self.source
            .accept_original_terminal(&snapshot, &state)
            .await?;
        cancellation.cancelled().await;
        Ok(())
    }

    async fn readback(
        &self,
        reservation: LearningIterationReservationV1<'_>,
        cancellation: &CancellationToken,
    ) -> Result<LearningIterationSnapshotV1, AgentdError> {
        self.source
            .require_current_historical_source(&self.source.identity)?;
        let result = tokio::select! {
            _ = cancellation.cancelled() => return Err(refused("original historical readback cancelled")),
            result = tokio::time::timeout_at(self.source.end.into(), reservation.readback(self.source.request().clone())) => result,
        }.map_err(refused)?.map_err(refused)?;
        require_complete(&self.source, &result)?;
        self.source
            .require_current_historical_source(&self.source.identity)?;
        Ok(result)
    }
}

fn require_complete(
    source: &RegisteredHistoricalLearningSourceV1,
    snapshot: &LearningIterationSnapshotV1,
) -> Result<(), AgentdError> {
    if snapshot.request != *source.request() || snapshot.owners != source.prepared.initial().owners
    {
        return Err(refused("historical Root snapshot differs"));
    }
    source
        .prepared
        .scope()
        .validate_snapshot(snapshot)
        .map_err(refused)?;
    let completed =
        LearningIterationCoordinatorV1::from_snapshot(snapshot.clone()).map_err(refused)?;
    if completed.next_stage().is_some() {
        return Err(refused("original historical iteration is incomplete"));
    }
    Ok(())
}

fn refused(message: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(format!("original historical learning source: {message}"))
}
