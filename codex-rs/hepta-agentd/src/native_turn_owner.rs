//! Native TurnOwner composition over the existing live thread and host admission.
//!
//! This adapter allocates no operation, queue, outbox, lease, or grant journal.
//! The host still supplies current authority, admission and FinalUse at dispatch.

use std::future::Future;
use std::sync::Arc;
use std::sync::Mutex;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_native_agent::ModelRequest;
use codex_hepta_native_agent::ToolAdmission;
use codex_hepta_native_agent::ToolCall;
use codex_hepta_native_agent::TurnBinding;
use codex_hepta_native_agent::TurnOwner;
use codex_hepta_native_agent::TurnState;
use codex_history::RolloutItem;
use codex_thread_store::LiveThread;
use codex_thread_store::NativeCheckpointBinding;
use codex_thread_store::NativeCheckpointCurrentness;
use codex_thread_store::NativeCheckpointExpected;
use codex_thread_store::NativeCheckpointLoad;
use codex_thread_store::NativeCheckpointOpenMode;
use codex_thread_store::NativeCheckpointSession;
use codex_thread_store::NativeCheckpointState;
use codex_thread_store::NativeCheckpointVersion;
use codex_thread_store::NativeHistoryVerification;
use codex_thread_store::NativeQueuedInputBinding;
use codex_thread_store::PersistContext;
use codex_thread_store::StoredNativeCheckpoint;
use tokio::sync::Semaphore;

use crate::native_turn_checkpoint::NativeTurnAnchorV1;
use crate::native_turn_checkpoint::{decode, encode, validate_transition};

/// Borrowed access to Agentd's original lifecycle and production-writer owners.
/// Admission must retain the exact original operation on retries and must not
/// allocate substitute authority. FinalUse remains the physical target's job.
pub trait NativeTurnAdmission: Send + Sync {
    fn verify_current(&self, binding: &TurnBinding) -> impl Future<Output = Result<()>> + Send;

    fn admit_model(
        &self,
        binding: &TurnBinding,
        sequence: usize,
        exact_body: &[u8],
    ) -> impl Future<Output = Result<ModelRequest>> + Send;

    fn admit_tool(
        &self,
        binding: &TurnBinding,
        call: &ToolCall,
    ) -> impl Future<Output = Result<ToolAdmission>> + Send;
}

/// One native turn using the same ThreadStore writer epoch as its history.
pub struct NativeThreadTurnOwner<A> {
    live_thread: LiveThread,
    session: NativeCheckpointSession,
    anchor: NativeTurnAnchorV1,
    admission: Arc<A>,
    // Serialize this owner's I/O without holding the cursor's data lock across
    // await. Cancellation releases the permit, not the exact pending CAS bytes.
    checkpoint_serial: Semaphore,
    cursor: Mutex<CheckpointCursor>,
}

#[derive(Default)]
struct CheckpointCursor {
    version: Option<NativeCheckpointVersion>,
    payload: Option<Vec<u8>>,
    // Set before awaiting storage. Cancellation may lose the acknowledgement,
    // but must never lose which exact CAS write is still being reconciled.
    pending: Option<Vec<u8>>,
}

impl CheckpointCursor {
    fn expected(&self) -> NativeCheckpointExpected {
        self.version.clone().map_or(NativeCheckpointExpected::Absent, NativeCheckpointExpected::Version)
    }

    fn observe(&mut self, observed: NativeCheckpointLoad, binding: &NativeCheckpointBinding) -> Result<()> {
        match observed {
            NativeCheckpointLoad::Missing => ensure!(self.version.is_none(), "native checkpoint disappeared"),
            NativeCheckpointLoad::Present(record) => {
                ensure!(&record.state.binding == binding, "native checkpoint original owner changed");
                if self.version.as_ref() == Some(&record.version) {
                    ensure!(self.payload.as_ref() == Some(&record.state.payload), "native checkpoint head payload changed");
                } else {
                    let next = self.version.as_ref().map_or(Some(1), |version| version.revision.checked_add(1));
                    ensure!(Some(record.version.revision) == next && self.pending.as_ref() == Some(&record.state.payload), "native checkpoint advanced outside this owner");
                    self.version = Some(record.version);
                    self.payload = Some(record.state.payload);
                    self.pending = None;
                }
            }
        }
        Ok(())
    }
}

impl<A: NativeTurnAdmission> NativeThreadTurnOwner<A> {
    /// Read the exact original correlation before Agentd restores its original
    /// coordinator as Indeterminate. This never admits, renews, dispatches or
    /// writes a checkpoint, and does not infer dispatch from pending bytes.
    pub(crate) async fn read_original(
        live_thread: LiveThread,
        original: NativeCheckpointBinding,
        currentness: Arc<dyn NativeCheckpointCurrentness>,
    ) -> Result<(NativeTurnAnchorV1, TurnState)> {
        let (_, anchor, state) = Self::read_original_record(live_thread, original, currentness).await?;
        Ok((anchor, state))
    }

    /// Return the exact verified head as well as decoded state. This is still
    /// read-only; a continuation needs independent original-owner evidence.
    pub(crate) async fn read_original_record(
        live_thread: LiveThread,
        original: NativeCheckpointBinding,
        currentness: Arc<dyn NativeCheckpointCurrentness>,
    ) -> Result<(StoredNativeCheckpoint, NativeTurnAnchorV1, TurnState)> {
        let session = live_thread.open_native_checkpoint(
            original.clone(), NativeCheckpointOpenMode::Recover, currentness,
        ).await?;
        let NativeCheckpointLoad::Present(record) = live_thread.load_native_checkpoint(&session).await? else {
            anyhow::bail!("original native checkpoint missing; no fresh admission allowed");
        };
        ensure!(record.state.binding == original, "stored original binding changed");
        let (anchor, state) = decode(&record.state.payload, &original)?;
        validate_history(&live_thread, &session, &anchor).await?;
        Ok((record, anchor, state))
    }

    /// Read the complete original hash-linked checkpoint chain. The store
    /// validates its bounds and links; native execution additionally folds
    /// every payload transition against the original operation evidence.
    pub(crate) async fn read_original_chain(
        live_thread: LiveThread,
        original: NativeCheckpointBinding,
        currentness: Arc<dyn NativeCheckpointCurrentness>,
    ) -> Result<(Vec<StoredNativeCheckpoint>, NativeTurnAnchorV1)> {
        let session = live_thread.open_native_checkpoint(
            original.clone(), NativeCheckpointOpenMode::Recover, currentness,
        ).await?;
        let records = live_thread.load_native_checkpoint_chain(&session).await?;
        let last = records.last().context("original native checkpoint chain is missing")?;
        let (anchor, _) = decode(&last.state.payload, &original)?;
        validate_history(&live_thread, &session, &anchor).await?;
        Ok((records, anchor))
    }

    /// Start only after the original history owner has durably recorded its
    /// input and complete recovery binding. The first native state precedes
    /// queue completion and every model/tool admission.
    pub async fn create(
        live_thread: LiveThread,
        anchor: NativeTurnAnchorV1,
        currentness: Arc<dyn NativeCheckpointCurrentness>,
        admission: Arc<A>,
        initial: &TurnState,
    ) -> Result<Self> {
        encode(&anchor, initial)?;
        ensure!(initial.model_calls == 0 && initial.tool_calls == 0
            && initial.pending_model.is_none() && initial.provider_response_id.is_none()
            && initial.pending_tool.is_none() && initial.queued_tools.is_empty()
            && initial.completed_call_ids.is_empty() && initial.final_answer.is_none()
            && !initial.cancelled && initial.last_error.is_none() && initial.model_usage.is_empty(),
            "new native turn already contains admitted work");
        admission.verify_current(&initial.binding).await?;
        live_thread.persist(PersistContext::TurnStart).await?;
        live_thread.flush().await?;
        let session = live_thread.open_native_checkpoint(
            anchor.checkpoint.clone(), NativeCheckpointOpenMode::Create, currentness,
        ).await?;
        validate_history(&live_thread, &session, &anchor).await?;
        ensure!(matches!(live_thread.load_native_checkpoint(&session).await?, NativeCheckpointLoad::Missing), "native turn already exists; recover its original state");
        let owner = Self { live_thread, session, anchor, admission,
            checkpoint_serial: Semaphore::new(1), cursor: Mutex::new(CheckpointCursor::default()) };
        owner.checkpoint(initial).await?;
        Ok(owner)
    }

    /// Reopen exact pending requests. Missing or incomplete legacy history is
    /// held for recovery; it is never converted into a fresh native turn.
    pub async fn recover(
        live_thread: LiveThread,
        original: NativeCheckpointBinding,
        currentness: Arc<dyn NativeCheckpointCurrentness>,
        admission: Arc<A>,
    ) -> Result<(Self, TurnState)> {
        let session = live_thread.open_native_checkpoint(
            original.clone(), NativeCheckpointOpenMode::Recover, currentness,
        ).await?;
        let NativeCheckpointLoad::Present(record) = live_thread.load_native_checkpoint(&session).await? else {
            anyhow::bail!("original native checkpoint missing; no fresh admission allowed");
        };
        let (anchor, state) = decode(&record.state.payload, &original)?;
        ensure!(record.state.binding == original, "stored original binding changed");
        validate_history(&live_thread, &session, &anchor).await?;
        if anchor.run.is_some() {
            crate::native_history::sync_native_history(&live_thread, &session, &record).await?;
        }
        // Loading old state is observation. The live authority is checked by
        // verify_current and the store's held permit before any subsequent write.
        let cursor = CheckpointCursor { version: Some(record.version), payload: Some(record.state.payload), pending: None };
        Ok((Self { live_thread, session, anchor, admission,
            checkpoint_serial: Semaphore::new(1), cursor: Mutex::new(cursor) }, state))
    }

    pub fn anchor(&self) -> &NativeTurnAnchorV1 {
        &self.anchor
    }

    /// A fresh continuation must recover the exact head whose complete state
    /// was proven, never a newer checkpoint with the same public identifiers.
    pub(crate) fn require_checkpoint(&self, expected: &StoredNativeCheckpoint) -> Result<()> {
        ensure!(expected.state.binding == self.anchor.checkpoint,
            "checkpoint continuation changed the original binding");
        self.with_cursor(|cursor| {
            ensure!(cursor.version.as_ref() == Some(&expected.version)
                && cursor.payload.as_ref() == Some(&expected.state.payload)
                && cursor.pending.is_none(),
                "checkpoint continuation head changed after original-owner verification");
            Ok(())
        })
    }

    // Every mutation is synchronous. The surrounding checkpoint_serial permit
    // spans load/CAS/history synchronization; it is never a storage authority.
    fn with_cursor<T>(
        &self,
        update: impl FnOnce(&mut CheckpointCursor) -> Result<T>,
    ) -> Result<T> {
        let mut cursor = self.cursor.lock()
            .map_err(|_| anyhow::anyhow!("native checkpoint cursor lock poisoned"))?;
        update(&mut cursor)
    }

    pub(crate) async fn confirm_durable(&self) -> Result<()> {
        self.verify_current(&self.anchor.turn_binding()?).await?;
        validate_history(&self.live_thread, &self.session, &self.anchor).await?;
        let _serial = self.checkpoint_serial.acquire().await
            .context("native checkpoint serialization closed")?;
        let observed = self.live_thread.load_native_checkpoint(&self.session).await?;
        self.with_cursor(|cursor| {
            cursor.observe(observed, &self.anchor.checkpoint)?;
            ensure!(cursor.version.is_some() && cursor.pending.is_none(), "native checkpoint acknowledgement still pending");
            Ok(())
        })
    }

    // Caller retains checkpoint_serial. The original store's owned commit may
    // outlive a cancelled waiter; pending remains in this same owner until an
    // exact load/commit acknowledgement reconciles its single successor.
    async fn commit_pending(&self) -> Result<()> {
        let (expected, payload) = self.with_cursor(|cursor| {
            Ok((cursor.expected(), cursor.pending.clone()
                .context("native pending checkpoint missing")?))
        })?;
        let result = self.live_thread.commit_native_checkpoint(
            &self.session,
            expected,
            NativeCheckpointState { binding: self.anchor.checkpoint.clone(), payload },
        ).await;
        match result {
            Ok(record) => self.with_cursor(|cursor| {
                cursor.observe(NativeCheckpointLoad::Present(record), &self.anchor.checkpoint)
            })?,
            Err(error) => {
                // The original cancelled commit and our exact retry may race.
                // Accept only its single exact successor, never an arbitrary head.
                let observed = self.live_thread.load_native_checkpoint(&self.session).await?;
                let still_pending = self.with_cursor(|cursor| {
                    cursor.observe(observed, &self.anchor.checkpoint)?;
                    Ok(cursor.pending.is_some())
                })?;
                if still_pending {
                    return Err(error.into());
                }
            }
        }
        self.with_cursor(|cursor| {
            ensure!(cursor.pending.is_none(), "native checkpoint was not acknowledged");
            Ok(())
        })
    }
}

impl<A: NativeTurnAdmission> TurnOwner for NativeThreadTurnOwner<A> {
    async fn verify_current(&self, binding: &TurnBinding) -> Result<()> {
        ensure!(binding == &self.anchor.turn_binding()?, "native owner original binding changed");
        self.admission.verify_current(binding).await
    }

    async fn checkpoint(&self, state: &TurnState) -> Result<()> {
        self.verify_current(&state.binding).await?;
        let payload = encode(&self.anchor, state)?;
        let _serial = self.checkpoint_serial.acquire().await
            .context("native checkpoint serialization closed")?;
        let observed = self.live_thread.load_native_checkpoint(&self.session).await?;
        let has_pending = self.with_cursor(|cursor| {
            cursor.observe(observed, &self.anchor.checkpoint)?;
            Ok(cursor.pending.is_some())
        })?;
        if has_pending {
            self.commit_pending().await?;
        }
        let changed = self.with_cursor(|cursor| {
            if cursor.payload.as_ref() == Some(&payload) {
                return Ok(false);
            }
            if let Some(previous) = &cursor.payload {
                let (_, previous) = decode(previous, &self.anchor.checkpoint)?;
                validate_transition(&previous, state)?;
            }
            cursor.pending = Some(payload);
            Ok(true)
        })?;
        if changed {
            self.commit_pending().await?;
        }
        if self.anchor.run.is_some() {
            let NativeCheckpointLoad::Present(record) = self.live_thread.load_native_checkpoint(&self.session).await? else {
                anyhow::bail!("acknowledged native checkpoint disappeared before history synchronization");
            };
            self.with_cursor(|cursor| {
                cursor.observe(NativeCheckpointLoad::Present(record.clone()), &self.anchor.checkpoint)
            })?;
            crate::native_history::sync_native_history(&self.live_thread, &self.session, &record).await?;
        }
        Ok(())
    }

    async fn admit_model(&self, binding: &TurnBinding, sequence: usize, exact_body: &[u8]) -> Result<ModelRequest> {
        self.verify_current(binding).await?;
        let request = self.admission.admit_model(binding, sequence, exact_body).await?;
        ensure!(!request.operation_id.is_empty() && request.body == exact_body, "host changed exact model admission");
        Ok(request)
    }

    async fn admit_tool(&self, binding: &TurnBinding, call: &ToolCall) -> Result<ToolAdmission> {
        self.verify_current(binding).await?;
        let admitted = self.admission.admit_tool(binding, call).await?;
        admitted.intent.validate()?;
        ensure!(admitted.intent.cell.generation == binding.generation
            && admitted.intent.cell.input_digest == codex_hepta_types::Digest32::of_bytes(&call.arguments)
            && admitted.intent.arguments_digest == codex_hepta_types::Digest32::of_bytes(&admitted.arguments), "host changed exact tool admission");
        Ok(admitted)
    }
}

async fn validate_history(live: &LiveThread, session: &NativeCheckpointSession, anchor: &NativeTurnAnchorV1) -> Result<()> {
    anchor.validate()?;
    live.verify_native_history(session, NativeHistoryVerification {
        recovery_item: RolloutItem::TurnRecoveryRequestBinding(anchor.recovery.clone()),
        queued_input: anchor.queue.as_ref().map(|queue| NativeQueuedInputBinding {
            client_id: queue.client_id.clone(), payload_sha256: queue.payload_sha256.clone(),
        }),
    }).await?;
    Ok(())
}

#[cfg(test)]
#[path = "native_turn_owner_tests.rs"]
mod tests;
