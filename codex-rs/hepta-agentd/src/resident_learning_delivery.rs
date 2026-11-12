//! Late ordinary-A enrollment into the explicit Root-resident operation.
//! This actor owns no role signer or execution token. It joins the actual
//! completed A outbox to the fixed Root peer, then observes that same operation.

use std::sync::Arc;
use std::time::Duration;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::CircuitLearningDeliveryV1;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use super::request_digest;
use super::retire_acknowledged_delivery;
use crate::AgentdError;
use crate::AgentdRootResidentLearningClientV3;
use crate::AgentdState;
use crate::LearningIterationRuntimeErrorV1 as Error;

struct EnrollmentV3 {
    root: AgentdRootResidentLearningClientV3,
    reply: oneshot::Sender<Result<(), Error>>,
}

/// The original launcher can hand off one actual Root connection after A has
/// completed. An enrollment ACK confirms only the local source join. It is
/// never a learning completion ACK and cannot retire A's durable outbox.
pub struct AgentdRootResidentEnrollmentV3 {
    sender: mpsc::Sender<EnrollmentV3>,
}

/// Optional, consumed by ordinary Agentd startup. No future A receipt or role
/// attestation is prefilled, and no default runtime constructs this value.
pub(crate) struct AgentdRootResidentDeliveryV3 {
    receiver: mpsc::Receiver<EnrollmentV3>,
}

pub(crate) fn root_resident_learning_delivery_v3()
-> (AgentdRootResidentEnrollmentV3, AgentdRootResidentDeliveryV3) {
    let (sender, receiver) = mpsc::channel(1);
    (
        AgentdRootResidentEnrollmentV3 { sender },
        AgentdRootResidentDeliveryV3 { receiver },
    )
}

impl AgentdRootResidentEnrollmentV3 {
    pub async fn enroll_original_root(
        &self,
        root: AgentdRootResidentLearningClientV3,
    ) -> Result<(), Error> {
        let permit = self.sender.try_reserve().map_err(|error| match error {
            mpsc::error::TrySendError::Full(_) => Error::QueueFull,
            mpsc::error::TrySendError::Closed(_) => Error::Unavailable,
        })?;
        let (reply, receive) = oneshot::channel();
        permit.send(EnrollmentV3 { root, reply });
        receive.await.map_err(|_| Error::CommitUncertain)?
    }
}

enum DeliveryAdmissionV3 {
    FirstClaim,
    Readback,
}

struct EnrolledOriginalV3 {
    root: AgentdRootResidentLearningClientV3,
    initial: LearningIterationSnapshotV1,
    admission: DeliveryAdmissionV3,
}

impl AgentdRootResidentDeliveryV3 {
    pub(crate) async fn run_original_resident_delivery(
        mut self,
        store: AutomationStore,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let enrollment = tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            enrollment = self.receiver.recv() => enrollment,
        };
        self.receiver.close();
        let Some(enrollment) = enrollment else {
            cancellation.cancelled().await;
            return Ok(());
        };
        if enrollment.reply.is_closed() {
            cancellation.cancelled().await;
            return Ok(());
        }
        let prepared = tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            result = prepare_enrollment(&store, &state, enrollment.root) => result,
        };
        let mut original = match prepared {
            Ok(original) => original,
            Err(error) => {
                let _ = enrollment.reply.send(Err(error));
                cancellation.cancelled().await;
                return Ok(());
            }
        };
        if enrollment.reply.send(Ok(())).is_err() {
            // The local registration ACK was not observed. Do not begin a
            // new claim; explicit later recovery needs a new read-only peer.
            cancellation.cancelled().await;
            return Ok(());
        }
        let mut tick = tokio::time::interval(Duration::from_secs(3));
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                _ = tick.tick() => {}
            }
            // This is only the current AutomationStore owner's local write
            // boundary. It is not a permanent lease for Root's continuation.
            if !state.plasticity_admission_ready()? {
                continue;
            }
            let result = tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                result = original.deliver(&store, &state) => result,
            };
            match result {
                Ok(()) => {
                    cancellation.cancelled().await;
                    return Ok(());
                }
                Err(Error::CommitUncertain | Error::Unavailable | Error::QueueFull) => {}
                Err(error) => {
                    return Err(AgentdError::Protocol(format!(
                        "Root resident learning delivery refused: {error}"
                    )));
                }
            }
        }
    }
}

async fn prepare_enrollment(
    store: &AutomationStore,
    state: &AgentdState,
    root: AgentdRootResidentLearningClientV3,
) -> Result<EnrolledOriginalV3, Error> {
    let initial = root.profile.initial().clone();
    let request = &initial.request;
    LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
    if request.agent_id.as_str() != store.owner_agent_id().as_str()
        || request.agent_id.as_str() != state.identity().agent_id.as_str()
    {
        return Err(Error::WrongScope);
    }
    // Confirm the original registered Root profile over its actual peer. An
    // empty *checkpoint* is not successful recovery; the Root owner preserves
    // that distinction. Any refusal here happens before an A outbox claim.
    let observed = AgentdRootResidentLearningClientV3::readback(&root).await?;
    let admission = if root.original_readback_only() {
        let row = delivery_row(store, request.source_run_id.as_str()).await?;
        let digest = request_digest(store, request, &initial.owners, &row.intent)?;
        if row.request_digest.as_ref() != Some(&digest) {
            return Err(Error::CommitUncertain);
        }
        // A later legal AutomationStore owner can reconcile exact old A.
        // It does not enroll A in C's source registry or submit old work.
        DeliveryAdmissionV3::Readback
    } else {
        root.require_fresh_admission_channel()?;
        if observed.snapshot().is_some() || observed.dispatch_pending() {
            return Err(Error::CommitUncertain);
        }
        state
            .require_resident_learning_source_candidate(request)
            .await
            .map_err(|_| Error::WrongScope)?;
        state
            .attach_circuit_learning_sources(vec![request.source_run_id.clone()])
            .map_err(|_| Error::WrongScope)?;
        let host = state
            .objective_runtime
            .get()
            .ok_or(Error::OwnerUnavailable("original Objective source owner"))?;
        host.reconcile_learning_outbox(store, Some(&request.source_run_id))
            .await
            .map_err(|_| Error::CommitUncertain)?;
        state
            .require_circuit_learning_source(request)
            .await
            .map_err(|_| Error::WrongScope)?;
        if !state
            .automation_admission_ready()
            .map_err(|_| Error::Unavailable)?
        {
            return Err(Error::Unavailable);
        }
        root.require_fresh_admission_channel()?;
        DeliveryAdmissionV3::FirstClaim
    };
    Ok(EnrolledOriginalV3 {
        root,
        initial,
        admission,
    })
}

async fn delivery_row(
    store: &AutomationStore,
    source_run_id: &str,
) -> Result<CircuitLearningDeliveryV1, Error> {
    store
        .circuit_learning_delivery(source_run_id)
        .await
        .map_err(|_| Error::CommitUncertain)?
        .ok_or(Error::OwnerUnavailable("original completed A outbox"))
}

impl EnrolledOriginalV3 {
    async fn deliver(&mut self, store: &AutomationStore, state: &AgentdState) -> Result<(), Error> {
        let request = &self.initial.request;
        let owners = &self.initial.owners;
        let row = delivery_row(store, request.source_run_id.as_str()).await?;
        let digest = request_digest(store, request, owners, &row.intent)?;
        if row.acknowledged_head.is_some() {
            // Existing exact ACK cleanup returns no snapshot or new learning
            // result. The original transactional owner rechecks all bindings.
            return retire_acknowledged_delivery(store, request, owners, &row).await;
        }
        let first = matches!(self.admission, DeliveryAdmissionV3::FirstClaim);
        let new_claim = if first && row.request_digest.is_none() {
            self.root.require_fresh_admission_channel()?;
            if !state
                .automation_admission_ready()
                .map_err(|_| Error::Unavailable)?
            {
                return Err(Error::Unavailable);
            }
            state
                .require_circuit_learning_source(request)
                .await
                .map_err(|_| Error::WrongScope)?;
            self.root.require_fresh_admission_channel()?;
            // Mark the local once state before the original durable effect.
            // Lost claim ACK never re-enters this branch, even in this actor.
            self.admission = DeliveryAdmissionV3::Readback;
            store
                .claim_circuit_learning(&row.intent, &digest)
                .await
                .map_err(|_| Error::CommitUncertain)?
        } else {
            self.admission = DeliveryAdmissionV3::Readback;
            if row.request_digest.as_ref() != Some(&digest) {
                return Err(Error::CommitUncertain);
            }
            false
        };
        let observed = if new_claim {
            state
                .require_circuit_learning_source(request)
                .await
                .map_err(|_| Error::WrongScope)?;
            if !state
                .automation_admission_ready()
                .map_err(|_| Error::Unavailable)?
            {
                return Err(Error::CommitUncertain);
            }
            AgentdRootResidentLearningClientV3::admit_after_original_claim(&self.root).await?
        } else {
            AgentdRootResidentLearningClientV3::readback(&self.root).await?
        };
        if observed.dispatch_pending() {
            return Err(Error::CommitUncertain);
        }
        let snapshot = observed.snapshot().ok_or(Error::CommitUncertain)?;
        if snapshot.request != *request || snapshot.owners != *owners {
            return Err(Error::WrongScope);
        }
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        if coordinator.next_stage().is_some() {
            // Root admission and every partial cut leave A's claim unresolved.
            return Err(Error::CommitUncertain);
        }
        // The client just checked all original role signatures after actual
        // Root CURRENT readback. A's local generation can still have changed
        // during that remote I/O; it must remain the legal outbox writer.
        if !state
            .plasticity_admission_ready()
            .map_err(|_| Error::Unavailable)?
        {
            return Err(Error::CommitUncertain);
        }
        self.root.revalidate_original_observation(&observed)?;
        let head =
            Sha256Digest::parse(snapshot.head_digest.to_string()).map_err(|_| Error::WrongScope)?;
        store
            .acknowledge_circuit_learning(&row.intent, &digest, &head)
            .await
            .map_err(|_| Error::CommitUncertain)?;
        store
            .retire_acknowledged_circuit_learning(&row.intent, &digest, &head)
            .await
            .map_err(|_| Error::CommitUncertain)?;
        Ok(())
    }
}
