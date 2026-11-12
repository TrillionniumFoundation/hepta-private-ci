//! One Root-owned coordinator future, admitted only by a fresh schema-3 CAS.
//! A's socket or worker exit does not cancel it. Root cancellation, revocation,
//! deadline or unknown completion ends execution permanently; recovery is read-only.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use super::authentication;
use super::gate::ResidentContinuationV3;
use super::gate::ResidentRegisteredStateV3;
use super::model::ResidentOriginalModelProofV3;
use super::profile::RootResidentLearningProfileV3;
use super::stages::ResidentOriginalStageOwnersV3;
use crate::AgentdError;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::RootResidentLearningEffectGateV3;

pub(super) enum ResidentRequestModeV3 {
    Admit,
    Readback,
}

struct ResidentRequestV3 {
    mode: ResidentRequestModeV3,
    reply: oneshot::Sender<Result<ResidentRuntimeObservationV3, Error>>,
}

pub(super) struct ResidentRuntimeObservationV3 {
    pub(super) snapshot: Option<LearningIterationSnapshotV1>,
    pub(super) attestations: Vec<SignedLearningEvidenceV1>,
    pub(super) model: Option<ResidentOriginalModelProofV3>,
    pub(super) dispatch_pending: bool,
}

/// A keyless Root server handle. The wire selects only admit/readback for the
/// already fixed operation; it cannot upload a snapshot or another task.
#[derive(Clone)]
pub struct RootResidentLearningHandleV3 {
    sender: mpsc::Sender<ResidentRequestV3>,
    pub(super) profile: RootResidentLearningProfileV3,
    pub(super) authorization_binding: codex_hepta_types::Digest32,
    pub(super) readonly: bool,
    pub(super) runtime: tokio::runtime::Handle,
}

enum ResidentStagesV3 {
    Uninstalled(Option<ResidentOriginalStageOwnersV3>),
    Installed(Arc<ResidentOriginalStageOwnersV3>),
}

impl ResidentStagesV3 {
    fn get(&self) -> Result<&ResidentOriginalStageOwnersV3, Error> {
        match self {
            Self::Uninstalled(Some(stages)) => Ok(stages),
            Self::Installed(stages) => Ok(stages),
            Self::Uninstalled(None) => Err(Error::Unavailable),
        }
    }
}

pub struct RootResidentLearningRuntimeV3 {
    owner: Arc<ResidentRegisteredStateV3>,
    verifier: LearningEvidenceVerifierV1,
    stages: ResidentStagesV3,
    receiver: mpsc::Receiver<ResidentRequestV3>,
    admission_requested: bool,
}

pub(super) fn compose(
    owner: Arc<ResidentRegisteredStateV3>,
    stages: ResidentOriginalStageOwnersV3,
    verifier: LearningEvidenceVerifierV1,
    capacity: usize,
) -> Result<(RootResidentLearningHandleV3, RootResidentLearningRuntimeV3), AgentdError> {
    let profile = &owner.authority.profile;
    profile
        .require_verifier(&verifier)
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    if !(1..=8).contains(&capacity)
        || verifier.trust_digest() != profile.initial.owners.evidence_trust_digest
    {
        return Err(AgentdError::Invalid(
            "resident queue or original role trust differs".into(),
        ));
    }
    ResidentOriginalStageOwnersV3::require_initial(
        &stages,
        &profile.initial,
        &profile.scope,
        &verifier,
    )
    .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    let authorization_binding = owner
        .authority
        .authorization_binding()
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    let readonly = owner.authority.readonly();
    let (sender, receiver) = mpsc::channel(capacity);
    let handle = RootResidentLearningHandleV3 {
        sender,
        profile: profile.clone(),
        authorization_binding,
        readonly,
        runtime: tokio::runtime::Handle::try_current()
            .map_err(|error| AgentdError::Invalid(error.to_string()))?,
    };
    Ok((
        handle,
        RootResidentLearningRuntimeV3 {
            owner,
            verifier,
            stages: ResidentStagesV3::Uninstalled(Some(stages)),
            receiver,
            admission_requested: readonly,
        },
    ))
}

impl RootResidentLearningHandleV3 {
    pub(super) async fn request(
        &self,
        mode: ResidentRequestModeV3,
    ) -> Result<ResidentRuntimeObservationV3, Error> {
        let permit = self.sender.try_reserve().map_err(|error| match error {
            mpsc::error::TrySendError::Full(_) => Error::QueueFull,
            mpsc::error::TrySendError::Closed(_) => Error::Unavailable,
        })?;
        let (reply, receive) = oneshot::channel();
        permit.send(ResidentRequestV3 { mode, reply });
        receive.await.map_err(|_| Error::CommitUncertain)?
    }
}

impl RootResidentLearningRuntimeV3 {
    /// The original Root host supervises this consumed runtime. Its cancellation
    /// token is independent of A's pidfd/session. All original role channels are
    /// still finite, and a remote effect may outlive a cancelled await: only
    /// same-operation readback is then permitted, never automatic replay.
    pub async fn run(mut self, root_cancellation: CancellationToken) -> Result<(), AgentdError> {
        type Active = Pin<Box<dyn Future<Output = Result<(), Error>> + Send>>;
        let mut active: Option<Active> = None;
        let mut channel_open = true;
        loop {
            tokio::select! {
                biased;
                _ = root_cancellation.cancelled() => return Ok(()),
                result = async {
                    match &mut active {
                        Some(future) => future.await,
                        None => std::future::pending().await,
                    }
                } => {
                    // Success and refusal both end the sole fresh future. The
                    // protected head remains available for authenticated reads.
                    let _completion = result;
                    active = None;
                }
                command = self.receiver.recv(), if channel_open => {
                    let Some(command) = command else {
                        // Losing A or a server handle is not Root cancellation.
                        channel_open = false;
                        if active.is_none() {
                            root_cancellation.cancelled().await;
                            return Ok(());
                        }
                        continue;
                    };
                    if command.reply.is_closed() {
                        // The validated operation reached this Root queue, but
                        // its caller no longer observes an admission response.
                        self.admission_requested = true;
                        continue;
                    }
                    let result = if matches!(command.mode, ResidentRequestModeV3::Admit)
                        && !self.admission_requested
                    {
                        self.admission_requested = true;
                        self.admit(&root_cancellation).await.map(|(observation, future)| {
                            active = future;
                            observation
                        })
                    } else {
                        self.readback(&root_cancellation).await
                    };
                    if result.is_err() {
                        // This request already passed the fixed wire context.
                        // Another connection cannot promote a refused original
                        // observation back into a fresh admission attempt.
                        self.admission_requested = true;
                    }
                    // An admission response is only the initial cut. A's
                    // original outbox cannot ACK/retire this incomplete cut.
                    let _ = command.reply.send(result);
                }
            }
        }
    }

    async fn admit(
        &mut self,
        cancellation: &CancellationToken,
    ) -> Result<
        (
            ResidentRuntimeObservationV3,
            Option<Pin<Box<dyn Future<Output = Result<(), Error>> + Send>>>,
        ),
        Error,
    > {
        let initial = self.owner.authority.profile.initial.clone();
        // Empty recovery is not source evidence. Only fresh actual CAS admits
        // the original Experience handler, which checks its own live source.
        let Some(continuation) =
            ResidentRegisteredStateV3::admit(&self.owner, cancellation).await?
        else {
            return Ok((self.readback(cancellation).await?, None));
        };
        let ResidentStagesV3::Uninstalled(slot) = &mut self.stages else {
            return Err(Error::CommitUncertain);
        };
        let mut stages = slot.take().ok_or(Error::CommitUncertain)?;
        ResidentOriginalStageOwnersV3::install_fresh_resident_gate(
            &mut stages,
            Arc::clone(&continuation.gate),
        )?;
        let stages = Arc::new(stages);
        self.stages = ResidentStagesV3::Installed(Arc::clone(&stages));
        let owner = Arc::clone(&self.owner);
        let verifier = self.verifier.clone();
        let observed = ResidentRuntimeObservationV3 {
            snapshot: Some(initial),
            attestations: Vec::new(),
            model: None,
            dispatch_pending: false,
        };
        let future = Box::pin(continue_original(owner, stages, verifier, continuation));
        Ok((observed, Some(future)))
    }

    async fn readback(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<ResidentRuntimeObservationV3, Error> {
        let (original, _) = self.owner.read(cancellation).await?;
        let evidence = match &original.snapshot {
            Some(snapshot) => {
                authentication::original_attestations(
                    &self.owner,
                    self.stages.get()?,
                    &self.verifier,
                    snapshot,
                    cancellation,
                )
                .await?
            }
            None => authentication::ResidentOriginalEvidenceV3 {
                signatures: Vec::new(),
                model: None,
            },
        };
        let (current, fresh) = self.owner.read(cancellation).await?;
        if current.snapshot != original.snapshot
            || current.dispatch_pending != original.dispatch_pending
        {
            return Err(Error::CommitUncertain);
        }
        if let Some(snapshot) = &current.snapshot {
            ResidentOriginalStageOwnersV3::require_initial(
                self.stages.get()?,
                &self.owner.authority.profile.initial,
                &self.owner.authority.profile.scope,
                &self.verifier,
            )?;
            authentication::verify_original_evidence(
                &self.owner.authority.profile,
                &self.verifier,
                snapshot,
                &evidence.signatures,
                evidence.model.as_ref(),
                fresh / 1_000,
            )?;
        }
        Ok(ResidentRuntimeObservationV3 {
            snapshot: current.snapshot,
            attestations: evidence.signatures,
            model: evidence.model,
            dispatch_pending: current.dispatch_pending,
        })
    }
}

async fn continue_original(
    owner: Arc<ResidentRegisteredStateV3>,
    stages: Arc<ResidentOriginalStageOwnersV3>,
    verifier: LearningEvidenceVerifierV1,
    continuation: ResidentContinuationV3,
) -> Result<(), Error> {
    let profile = &owner.authority.profile;
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(profile.initial.clone())?;
    let gate = &continuation.gate;
    while let Some(stage) = coordinator.next_stage() {
        ResidentOriginalStageOwnersV3::require_stage(
            stages.as_ref(),
            coordinator.snapshot(),
            stage,
        )?;
        let predecessor = coordinator.snapshot().clone();
        gate.begin(&predecessor, stage).await?;
        // The durable local intent has been committed. Original role hosts,
        // not this released Root lock, linearize any subsequent remote effects.
        let call = ResidentOriginalStageOwnersV3::execute_original_stage(
            stages.as_ref(), &predecessor, stage,
        );
        let mut call = Box::pin(call);
        let mut watchdog = tokio::time::interval(Duration::from_millis(250));
        watchdog.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        let training_end = tokio::time::Instant::now()
            .checked_add(Duration::from_millis(
                predecessor.request.budget.maximum_training_milliseconds,
            ))
            .ok_or(Error::DeadlineExceeded)?;
        let completed = loop {
            tokio::select! {
                biased;
                _ = gate.cancellation().cancelled() => return Err(Error::CommitUncertain),
                _ = tokio::time::sleep_until(training_end),
                    if stage == LearningIterationStageV1::Training =>
                        return Err(Error::CommitUncertain),
                result = &mut call => break result?,
                _ = watchdog.tick() => RootResidentLearningEffectGateV3::require_current(gate, &predecessor, &profile.scope).await?,
            }
        };
        RootResidentLearningEffectGateV3::require_current(gate, &predecessor, &profile.scope)
            .await?;
        profile.scope.validate_observation(&completed.receipt.observation)?;
        let (_, now) = owner.read(gate.cancellation()).await?;
        coordinator.record(completed.receipt, now / 1_000)?;
        let evidence = match completed.candidate {
            Some(original) => authentication::candidate_continuation_attestations(
                &owner, &stages, &verifier, coordinator.snapshot(), original, gate.cancellation(),
            ).await?,
            None => authentication::original_attestations(
                &owner, &stages, &verifier, coordinator.snapshot(), gate.cancellation(),
            ).await?,
        };
        RootResidentLearningEffectGateV3::require_current(gate, &predecessor, &profile.scope)
            .await?;
        let (_, fresh) = owner.read(gate.cancellation()).await?;
        ResidentOriginalStageOwnersV3::require_initial(
            &stages,
            &profile.initial,
            &profile.scope,
            &verifier,
        )?;
        authentication::verify_original_evidence(
            profile,
            &verifier,
            coordinator.snapshot(),
            &evidence.signatures,
            evidence.model.as_ref(),
            fresh / 1_000,
        )?;
        gate.checkpoint(&predecessor, coordinator.snapshot().clone())
            .await?;
    }
    // Dropping the continuation permanently disables its installed effect gate.
    // The complete result is returned only through the independent readback path.
    Ok(())
}
