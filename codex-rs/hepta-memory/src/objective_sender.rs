//! Original-owner Objective request retention. No effect outbox or second owner.

use super::ProductionDurableWriter;
use super::ProductionWriterError;
use crate::CognitiveRecoveryAnchor;
use crate::CognitiveStoreError;
use crate::cognitive_store::capture_recovery_anchor;
use crate::cognitive_store::unavailable;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Sqlite;
use sqlx::Transaction;
use std::sync::Arc;
use std::sync::Weak;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::time::Duration;

#[path = "objective_sender_model.rs"]
mod model;
#[path = "objective_sender_read.rs"]
mod read;
#[path = "objective_sender_store.rs"]
mod store;
pub use model::ObjectiveSenderIdentity;
pub use model::ObjectiveSenderInputError;
pub use model::ObjectiveSenderObservation;
pub use model::ObjectiveSenderObservationKind;
pub use model::ObjectiveSenderOrigin;
pub use model::ObjectiveSenderRequest;
pub use model::ObjectiveSenderWriterFence;
pub use read::ObjectiveSenderRetainedCursor;
pub use read::ObjectiveSenderRetainedPage;
pub use read::ObjectiveSenderRetainedPosition;
pub use read::ObjectiveSenderSnapshot;
pub(crate) use store::verify_sender_store;

const UNUSED: u8 = 0;
const STARTED: u8 = 1;
const OBSERVED: u8 = 2;
const CANCELLED: u8 = 3;
const RECOVERED: u8 = 4;
const MAX_CHECKPOINT_DEADLINE: Duration = Duration::from_secs(5);

pub use codex_hepta_authority_types::ObjectiveSenderCheckpoint;
pub use codex_hepta_authority_types::ObjectiveSenderCheckpointError;

#[derive(Debug, thiserror::Error)]
pub enum ObjectiveSenderError {
    #[error(transparent)]
    Input(#[from] ObjectiveSenderInputError),
    #[error(transparent)]
    Writer(#[from] ProductionWriterError),
    #[error(transparent)]
    Store(#[from] CognitiveStoreError),
    #[error("the original Objective or Run already has a retained send fence")]
    AlreadyRetained,
    #[error("the original Objective request was not retained by this owner")]
    Missing,
    #[error("the complete retained Objective identity differs")]
    IdentityMismatch,
    #[error("Objective sender retention capacity is exhausted")]
    Capacity,
    #[error("Objective observation conflicts with the retained lifecycle")]
    ObservationConflict,
    #[error("the local unused Objective permission is unavailable")]
    LocalCancellationUnavailable,
    #[error("the one local Objective send permission is unavailable")]
    SendPermissionUnavailable,
    #[error("Objective mutation may be durable but its independent acknowledgement is unknown")]
    AcknowledgementUnknown,
}

/// Opaque, non-cloneable local ticket. Recovery produces the same read/record
/// handle with no unused permission; it can never mint another sending ticket.
pub struct ObjectiveSenderTicket {
    request: ObjectiveSenderRequest,
    local: AtomicU8,
    writer: Weak<ProductionDurableWriter>,
}

impl ObjectiveSenderTicket {
    pub fn request(&self) -> &ObjectiveSenderRequest {
        &self.request
    }
}

/// A restricted capability over the same original ProductionDurableWriter.
/// It opens no database and provides no issuer, transport, default checkpoint,
/// or production trust. An embedding must supply its independent checkpoint.
/// The retained synchronous authority verifier and clock must also be bounded
/// and nonblocking; cooperative timeouts cannot preempt these callbacks.
pub struct ProductionObjectiveSender<C: ObjectiveSenderCheckpoint> {
    writer: Arc<ProductionDurableWriter>,
    checkpoint: Arc<C>,
    deadline: Duration,
    spawn_generation: u64,
}

impl ProductionDurableWriter {
    pub fn objective_sender<C: ObjectiveSenderCheckpoint>(
        self: &Arc<Self>,
        checkpoint: Arc<C>,
        deadline: Duration,
    ) -> Result<ProductionObjectiveSender<C>, ObjectiveSenderError> {
        self.objective_sender_for_spawn_generation(checkpoint, deadline, self.generation())
    }

    /// Bind the sender to the trusted embedding's process generation. A local
    /// lease advances only on lease succession; a supervisor may advance its
    /// process generation on additional lifecycle transitions. The embedding
    /// must authenticate this process binding independently of the writer's
    /// retained authority. This creates no sending permission or durable row.
    pub fn objective_sender_for_spawn_generation<C: ObjectiveSenderCheckpoint>(
        self: &Arc<Self>,
        checkpoint: Arc<C>,
        deadline: Duration,
        spawn_generation: u64,
    ) -> Result<ProductionObjectiveSender<C>, ObjectiveSenderError> {
        if spawn_generation == 0 || deadline.is_zero() || deadline > MAX_CHECKPOINT_DEADLINE {
            return Err(ObjectiveSenderInputError::Bound.into());
        }
        self.sender_live_check()?;
        self.live_verifier
            .as_ref()
            .ok_or(ProductionWriterError::LiveVerifierRequired)?
            .verify_sender_process_binding(
                &self.authority,
                self.owner_agent_id(),
                self.lease_id(),
                self.generation(),
                spawn_generation,
            )
            .map_err(ProductionWriterError::AuthorityRejected)?;
        Ok(ProductionObjectiveSender {
            writer: Arc::clone(self),
            checkpoint,
            deadline,
            spawn_generation,
        })
    }

    fn sender_live_check(&self) -> Result<(), ProductionWriterError> {
        Sha256Digest::parse(self.authority.grant_digest.as_str()).map_err(|_| {
            ProductionWriterError::Invalid(
                "malformed Objective sender authority grant digest".to_string(),
            )
        })?;
        super::validate_authority_for_agent(&self.authority, self.store.owner_agent_id())?;
        self.live_verifier
            .as_ref()
            .ok_or(ProductionWriterError::LiveVerifierRequired)?
            .verify(&self.authority, self.store.owner_agent_id())
            .map_err(ProductionWriterError::AuthorityRejected)
    }
}

impl<C: ObjectiveSenderCheckpoint> ProductionObjectiveSender<C> {
    fn verify_process_binding(&self) -> Result<(), ProductionWriterError> {
        self.writer.sender_live_check()?;
        self.writer
            .live_verifier
            .as_ref()
            .ok_or(ProductionWriterError::LiveVerifierRequired)?
            .verify_sender_process_binding(
                &self.writer.authority,
                self.writer.owner_agent_id(),
                self.writer.lease_id(),
                self.writer.generation(),
                self.spawn_generation,
            )
            .map_err(ProductionWriterError::AuthorityRejected)
    }

    /// One original transaction retains exact bytes and permanently occupies
    /// their one sending opportunity. Any later error leaves that fence intact.
    /// The origin must match this capability's fixed process generation, which
    /// can differ from the independently fenced local writer lease generation.
    pub async fn retain_before_send(
        &self,
        request: ObjectiveSenderRequest,
    ) -> Result<ObjectiveSenderTicket, ObjectiveSenderError> {
        if request.origin.agent_id != *self.writer.owner_agent_id()
            || request.origin.spawn_generation != self.spawn_generation
        {
            return Err(ObjectiveSenderError::IdentityMismatch);
        }
        self.verify_process_binding()?;
        self.writer.verify_current_authority().await?;
        let mut transaction = self
            .writer
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let fence = self.current_fence(&mut transaction).await?;
        store::retain(&mut transaction, &request, &fence).await?;
        self.writer.sender_live_check()?;
        transaction
            .commit()
            .await
            .map_err(|_| ObjectiveSenderError::AcknowledgementUnknown)?;
        self.acknowledge_committed()
            .await
            .map_err(|_| ObjectiveSenderError::AcknowledgementUnknown)?;
        Ok(ObjectiveSenderTicket {
            request,
            local: AtomicU8::new(UNUSED),
            writer: Arc::downgrade(&self.writer),
        })
    }

    /// Consume this process's single local sending permission before any
    /// transport I/O. The durable fence was already committed and acknowledged
    /// by retain_before_send. A refusal, cancellation or lost reply never
    /// rearms this ticket. A recovered ticket cannot enter this transition.
    pub async fn mark_send_started(
        &self,
        ticket: &ObjectiveSenderTicket,
    ) -> Result<(), ObjectiveSenderError> {
        self.require_ticket_owner(ticket)?;
        if ticket.request.origin.agent_id != *self.writer.owner_agent_id()
            || ticket.request.origin.spawn_generation != self.spawn_generation
        {
            return Err(ObjectiveSenderError::IdentityMismatch);
        }
        ticket
            .local
            .compare_exchange(UNUSED, STARTED, Ordering::SeqCst, Ordering::SeqCst)
            .map_err(|_| ObjectiveSenderError::SendPermissionUnavailable)?;
        self.writer.verify_current_authority().await?;
        self.verify_process_binding()?;
        Ok(())
    }

    /// Append or re-acknowledge the exact same immutable observation. This
    /// method performs no network submission, history query or RunCancel.
    pub async fn retain_observation(
        &self,
        ticket: &ObjectiveSenderTicket,
        observation: &ObjectiveSenderObservation,
    ) -> Result<(), ObjectiveSenderError> {
        self.require_ticket_owner(ticket)?;
        match ticket
            .local
            .compare_exchange(STARTED, OBSERVED, Ordering::SeqCst, Ordering::SeqCst)
        {
            Ok(_) | Err(OBSERVED) | Err(RECOVERED) => {}
            Err(_) => return Err(ObjectiveSenderError::ObservationConflict),
        }
        self.append(
            ticket,
            store::EventKind::from(observation.kind),
            &observation.exact_json,
        )
        .await
    }

    /// Check the current retained observations and append under the same original
    /// BEGIN IMMEDIATE transaction. This is for trusted composition code which
    /// must preserve a semantic invariant across concurrently recovered handles;
    /// it supplies no authority or sending permission. The check must be bounded,
    /// synchronous and nonblocking: no I/O, waiting, or re-entry into this store.
    /// A check rejection rolls back before append or checkpoint acknowledgement.
    /// Success still uses the original live checks, immutable append and independent ACK.
    /// Exact retries are checked again and re-acknowledged without another event.
    pub async fn retain_observation_checked<F>(
        &self,
        ticket: &ObjectiveSenderTicket,
        observation: &ObjectiveSenderObservation,
        check: F,
    ) -> Result<(), ObjectiveSenderError>
    where
        F: FnOnce(&ObjectiveSenderSnapshot) -> Result<(), ObjectiveSenderError> + Send,
    {
        self.require_ticket_owner(ticket)?;
        match ticket
            .local
            .compare_exchange(STARTED, OBSERVED, Ordering::SeqCst, Ordering::SeqCst)
        {
            Ok(_) | Err(OBSERVED) | Err(RECOVERED) => {}
            Err(_) => return Err(ObjectiveSenderError::ObservationConflict),
        }
        self.append_with_check(
            ticket,
            store::EventKind::from(observation.kind),
            &observation.exact_json,
            Some(check),
        )
        .await
    }

    /// Read retained observations and obtain an independent current-cut ACK
    /// before returning them as acknowledged recovery data. Unlike `snapshot`,
    /// this does not infer confirmation from the presence of local SQLite rows.
    /// The snapshot and complete recovery cut share one original BEGIN IMMEDIATE
    /// transaction, held through the injected checkpoint and its live checks.
    /// A final live check follows the read-only transaction's release.
    /// No event, sending permission or local cancellation permission is created.
    /// A failed or cancelled ACK returns no snapshot; the same original records
    /// remain available for a later explicit read/ACK without resubmission.
    /// Re-acknowledgement never reopens a fenced owner generation.
    pub async fn snapshot_acknowledged(
        &self,
        ticket: &ObjectiveSenderTicket,
    ) -> Result<ObjectiveSenderSnapshot, ObjectiveSenderError> {
        self.require_ticket_owner(ticket)?;
        self.writer.sender_live_check()?;
        self.writer.verify_authority().await?;
        let mut transaction = self
            .writer
            .store
            .begin_checkpoint_barrier()
            .await
            .map_err(unavailable)?;
        store::require_request(&mut transaction, &ticket.request).await?;
        let snapshot = store::snapshot(&mut transaction, &ticket.request).await?;
        self.acknowledge_transaction(&mut transaction).await?;
        transaction.rollback().await.map_err(unavailable)?;
        self.writer.sender_live_check()?;
        Ok(snapshot)
    }

    /// Independently acknowledge the complete original owner cut without an
    /// Objective request or ticket. This closes a startup lease transition using
    /// the same original transaction, live authority checks and checkpoint gate
    /// as sender retention. No request, event, send or cancellation permission
    /// is created. An uncertain or cancelled started checkpoint exchange fences
    /// the whole owner; a later readback can settle evidence but cannot reopen
    /// that generation. Cancellation before that exchange leaves any existing
    /// Dirty state unacknowledged; it never supplies a clean receipt.
    pub async fn acknowledge_owner_cut(&self) -> Result<(), ObjectiveSenderError> {
        self.verify_process_binding()?;
        self.writer.verify_authority().await?;
        self.acknowledge_committed().await
    }

    /// Consume only this live unused local permission. A failed durable ACK
    /// cannot rearm it; the same local cancellation can only be re-acknowledged.
    pub async fn retain_local_cancellation(
        &self,
        ticket: &ObjectiveSenderTicket,
    ) -> Result<(), ObjectiveSenderError> {
        self.require_ticket_owner(ticket)?;
        match ticket
            .local
            .compare_exchange(UNUSED, CANCELLED, Ordering::SeqCst, Ordering::SeqCst)
        {
            Ok(_) | Err(CANCELLED) => {}
            Err(_) => return Err(ObjectiveSenderError::LocalCancellationUnavailable),
        }
        self.append(ticket, store::EventKind::LocalCancelled, "null")
            .await
    }

    fn require_ticket_owner(
        &self,
        ticket: &ObjectiveSenderTicket,
    ) -> Result<(), ObjectiveSenderError> {
        if !Weak::ptr_eq(&ticket.writer, &Arc::downgrade(&self.writer)) {
            return Err(ObjectiveSenderError::IdentityMismatch);
        }
        Ok(())
    }

    async fn append(
        &self,
        ticket: &ObjectiveSenderTicket,
        kind: store::EventKind,
        observation: &str,
    ) -> Result<(), ObjectiveSenderError> {
        self.append_with_check(
            ticket,
            kind,
            observation,
            /*check*/
            None::<fn(&ObjectiveSenderSnapshot) -> Result<(), ObjectiveSenderError>>,
        )
        .await
    }

    async fn append_with_check<F>(
        &self,
        ticket: &ObjectiveSenderTicket,
        kind: store::EventKind,
        observation: &str,
        check: Option<F>,
    ) -> Result<(), ObjectiveSenderError>
    where
        F: FnOnce(&ObjectiveSenderSnapshot) -> Result<(), ObjectiveSenderError> + Send,
    {
        self.writer.verify_current_authority().await?;
        if ticket.request.origin.agent_id != *self.writer.owner_agent_id() {
            return Err(ObjectiveSenderError::IdentityMismatch);
        }
        let mut transaction = self
            .writer
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let fence = self.current_fence(&mut transaction).await?;
        store::require_request(&mut transaction, &ticket.request).await?;
        if let Some(check) = check {
            let snapshot = store::snapshot(&mut transaction, &ticket.request).await?;
            check(&snapshot)?;
        }
        store::append(&mut transaction, &ticket.request, &fence, kind, observation).await?;
        self.writer.sender_live_check()?;
        transaction
            .commit()
            .await
            .map_err(|_| ObjectiveSenderError::AcknowledgementUnknown)?;
        self.acknowledge_committed()
            .await
            .map_err(|_| ObjectiveSenderError::AcknowledgementUnknown)
    }

    async fn current_fence(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
    ) -> Result<model::OwnerFence, ObjectiveSenderError> {
        let lease = self
            .writer
            .lease
            .require_current_transaction(transaction)
            .await
            .map_err(ProductionWriterError::from)?;
        self.verify_process_binding()?;
        Ok(model::OwnerFence {
            owner_agent_id: self.writer.owner_agent_id().clone(),
            lease_id: self.writer.lease_id().to_string(),
            lease_sha256: lease.lease_sha256,
            generation: self.writer.generation(),
            authority_epoch: self.writer.authority.authority_epoch,
            owner_epoch: self.writer.authority.owner_epoch,
            authority_grant_digest: self.writer.authority.grant_digest.clone(),
            fencing_token_digest: self.writer.authority.fencing_token_digest()?,
            expires_at_unix_seconds: self.writer.authority.lease_expires_at_unix_seconds,
        })
    }

    async fn acknowledge_committed(&self) -> Result<(), ObjectiveSenderError> {
        // This is the original database-wide SQLite write serialization, not a
        // capability-local Mutex. Intervening commits are included in capture.
        let mut transaction = self
            .writer
            .store
            .begin_checkpoint_barrier()
            .await
            .map_err(unavailable)?;
        self.acknowledge_transaction(&mut transaction).await?;
        transaction.rollback().await.map_err(unavailable)?;
        self.verify_process_binding()?;
        Ok(())
    }

    async fn acknowledge_transaction(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
    ) -> Result<(), ObjectiveSenderError> {
        let writer = self.current_fence(transaction).await?;
        let current = capture_recovery_anchor(transaction, self.writer.owner_agent_id()).await?;
        self.writer.sender_live_check()?;
        let attempt = self.writer.store.commit_gate.checkpoint_attempt();
        let acknowledged = tokio::time::timeout(
            self.deadline,
            self.checkpoint.acknowledge_current(&current, &writer),
        )
        .await
        .map_err(|_| ObjectiveSenderError::AcknowledgementUnknown)?
        .map_err(|_| ObjectiveSenderError::AcknowledgementUnknown)?;
        if acknowledged != current {
            return Err(ObjectiveSenderError::AcknowledgementUnknown);
        }
        self.verify_process_binding()?;
        attempt.acknowledge();
        Ok(())
    }
}

#[cfg(test)]
#[path = "objective_sender_test_support.rs"]
mod test_support;

#[cfg(test)]
#[path = "objective_sender_tests.rs"]
mod tests;

#[cfg(all(test, unix))]
#[path = "objective_sender_crash_tests.rs"]
mod crash_tests;

#[cfg(test)]
#[path = "objective_sender_gate_tests.rs"]
mod gate_tests;

#[cfg(test)]
#[path = "cognitive_checkpoint_tests.rs"]
mod protected_checkpoint_tests;

#[cfg(test)]
#[path = "objective_sender_generation_tests.rs"]
mod generation_tests;
