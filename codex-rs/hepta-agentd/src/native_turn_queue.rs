//! Input delivery through the original QueueStore lock, lease and owner CAS.
//!
//! A queue lease covers admitting one user input. It is never serialized as
//! native turn execution authority and never renewed by the model loop.

use std::sync::Arc;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_protocol::ThreadId;
use codex_protocol::turn_input::TurnInput;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_thread_store::MAX_QUEUE_ITEMS;
use codex_thread_store::QueueStore;
use codex_thread_store::QueuedClientDispatchClaimOutcome;
use codex_thread_store::QueuedClientDispatchLease;
use codex_thread_store::QueuedClientDispatchLock;

use crate::native_turn_checkpoint::NativeQueueBindingV1;
use crate::native_turn_owner::NativeThreadTurnOwner;
use crate::native_turn_owner::NativeTurnAdmission;

/// An in-process borrow of the existing queue's dispatch ownership. Dropping
/// it does not claim that submission failed or requeue uncertain work.
pub struct NativeQueueDispatch {
    queue: Arc<dyn QueueStore>,
    lock: QueuedClientDispatchLock,
    lease: Option<QueuedClientDispatchLease>,
    thread_id: ThreadId,
    binding: NativeQueueBindingV1,
    payload: String,
}

impl NativeQueueDispatch {
    pub async fn claim(
        queue: Arc<dyn QueueStore>,
        thread_id: ThreadId,
        binding: NativeQueueBindingV1,
        owner_id: String,
        now_ms: i64,
        expires_at_ms: i64,
    ) -> Result<Self> {
        let rows = queue.list_page(thread_id, 0, MAX_QUEUE_ITEMS).await?;
        let row = rows.into_iter().find(|row| row.id == binding.queued_item_id).context("original queue input missing")?;
        let TurnInput::UserInput { content, client_id: Some(client_id) } = serde_json::from_str(&row.payload)? else {
            bail!("original queue row has no bound user input");
        };
        ensure!(row.thread_id == thread_id && client_id == binding.client_id && user_input_payload_sha256(&content)? == binding.payload_sha256, "original queue payload changed");
        let lock = queue.try_acquire_client_dispatch_lock(thread_id, binding.client_id.clone(), binding.payload_sha256.clone())?.context("original queue dispatch is owned by another process")?;
        let claim = queue.claim_client_binding_dispatch(&lock, binding.queued_item_id.clone(), owner_id, now_ms, expires_at_ms).await?;
        let QueuedClientDispatchClaimOutcome::Acquired(lease) = claim else {
            bail!("original queue dispatch requires reconciliation: {claim:?}");
        };
        Ok(Self { queue, lock, lease: Some(lease), thread_id, binding, payload: row.payload })
    }

    pub fn binding(&self) -> &NativeQueueBindingV1 {
        &self.binding
    }

    pub fn payload(&self) -> &str {
        &self.payload
    }

    /// Recheck the original queue owner immediately before recording its input.
    pub async fn authorize(&mut self, now_ms: i64, expires_at_ms: i64) -> Result<()> {
        let lease = self.lease.take().context("original queue dispatch lease unavailable")?;
        self.lease = Some(self.queue.authorize_client_binding_dispatch(&self.lock, lease, now_ms, expires_at_ms).await?);
        Ok(())
    }

    /// Only a durable native state plus its exact original history closes the
    /// original queue row. The existing queue transaction owns CAS and deletion.
    pub async fn complete<A: NativeTurnAdmission>(&mut self, owner: &NativeThreadTurnOwner<A>) -> Result<()> {
        ensure!(owner.anchor().checkpoint.thread_id == self.thread_id && owner.anchor().queue.as_ref() == Some(&self.binding), "native turn belongs to another queued input");
        owner.confirm_durable().await?;
        let lease = self.lease.as_ref().context("original queue dispatch lease unavailable")?;
        self.queue.complete_client_binding_dispatch(&self.lock, lease, owner.anchor().checkpoint.turn_id.clone()).await?;
        self.lease = None;
        Ok(())
    }

    /// Finish only an already durable native input after a crash or lost queue
    /// completion acknowledgement. Expiry alone never authorizes fresh work.
    pub async fn reconcile_completed<A: NativeTurnAdmission>(
        queue: Arc<dyn QueueStore>,
        owner: &NativeThreadTurnOwner<A>,
        owner_id: String,
        now_ms: i64,
        expires_at_ms: i64,
    ) -> Result<()> {
        owner.confirm_durable().await?;
        let anchor = owner.anchor();
        let binding = anchor.queue.as_ref().context("native turn has no original queued input")?;
        let lock = queue.try_acquire_client_dispatch_lock(anchor.checkpoint.thread_id, binding.client_id.clone(), binding.payload_sha256.clone())?.context("original queue dispatch is still owned")?;
        let claim = queue.claim_client_binding_dispatch(&lock, binding.queued_item_id.clone(), owner_id.clone(), now_ms, expires_at_ms).await?;
        let observed = match claim {
            QueuedClientDispatchClaimOutcome::Expired(expired) => queue.recover_expired_client_dispatch(
                &lock, expired, owner_id, Some(anchor.checkpoint.turn_id.clone()), now_ms, expires_at_ms,
            ).await?,
            QueuedClientDispatchClaimOutcome::Acquired(lease) => {
                // A durable input is already admitted. Settle that exact queue
                // identity; do not append input or run the agent a second time.
                queue.complete_client_binding_dispatch(&lock, &lease, anchor.checkpoint.turn_id.clone()).await?;
                return Ok(());
            }
            other => other,
        };
        match observed {
            QueuedClientDispatchClaimOutcome::Persisted { turn_id } if turn_id == anchor.checkpoint.turn_id => Ok(()),
            other => bail!("original queued input is not durably reconciled: {other:?}"),
        }
    }
}
