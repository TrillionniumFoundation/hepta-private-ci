//! Explicit in-process custody and unsigned completion for one Joint request.
//!
//! The host supplies its original checkpoint, Memory and Ledger objects. This
//! channel neither constructs a complete learning-iteration profile nor starts
//! a worker. Start/Cancel still use the existing TaskFlow and FinalUse path.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::JointTextInputRefV1;
use codex_hepta_automation::JointTextJobIdentityV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_memory::CognitiveStore;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::JointTextTrainingErrorV1;
use crate::JointTextTrainingOutputBytesV1;
use crate::LearningIterationCheckpointOwnerV1;
use crate::PreparedJointTextTrainingRequestV1;
use crate::UnsignedJointTextTrainingCandidateV1;
use crate::automation_effect_host::AgentdAutomationEffectHost;
use crate::revalidate_joint_text_training_output_v1;

const MAX_OWNER_QUEUE: usize = 64;

/// Unsigned candidate and the actual fixed-custody runner terminal evidence.
///
/// Runner measurements cover claim through terminal. They exclude host
/// admission/staging, this readback, prior attempts and unobserved physical
/// energy. The candidate's worker measurements overlap this interval and must
/// not be added to it as independent work. No complete historical cost is
/// asserted, and the candidate retains H-B's original DENY_ALL authority.
#[derive(Clone, Debug, PartialEq)]
pub struct JointTextTrainingCompletionV1 {
    pub candidate: UnsignedJointTextTrainingCandidateV1,
    pub terminal_digest: Sha256Digest,
    pub runner_wall_nanoseconds: u64,
    pub runner_child_cpu_nanoseconds: Option<u64>,
    pub scope: &'static str,
    pub full_history_cost: Option<serde_json::Value>,
}

/// Retains the concrete registered owner, not a callable replacement or a
/// cached assertion of freshness. Every check performs a new durable restore.
pub(crate) struct JointTextCheckpointBindingV1 {
    owner: Arc<LearningIterationCheckpointOwnerV1>,
    snapshot: LearningIterationSnapshotV1,
}

impl JointTextCheckpointBindingV1 {
    pub(crate) fn bind(
        owner: Arc<LearningIterationCheckpointOwnerV1>,
        snapshot: LearningIterationSnapshotV1,
    ) -> Result<Self, AgentdError> {
        let binding = Self { owner, snapshot };
        binding.require_current()?;
        Ok(binding)
    }

    pub(crate) fn iteration_snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.snapshot
    }

    /// Equality is a current data observation, not a receipt signature, grant,
    /// transaction with Memory, or permission to launch a Training job.
    pub(crate) fn require_current(&self) -> Result<(), AgentdError> {
        let restored = self.owner.restore(&self.snapshot.request);
        let current = restored.map_err(|error| {
            AgentdError::GenerationFenced(format!("Joint checkpoint restore failed: {error}"))
        })?;
        if current.as_ref() != Some(&self.snapshot) {
            return Err(AgentdError::GenerationFenced(
                "Joint prepared snapshot is not the current original checkpoint".into(),
            ));
        }
        Ok(())
    }
}

/// Original, already-open objects supplied by the admitted in-process owner.
/// No pathname, replacement signer, serialized Memory grant or generic factory
/// is accepted. The prepared request fixes this bootstrap to one iteration.
pub struct JointTextTrainingOwnerInputsV1 {
    pub agent_id: AgentId,
    pub spawn_generation: u64,
    pub checkpoint: Arc<LearningIterationCheckpointOwnerV1>,
    pub memory: Arc<CognitiveStore>,
    pub ledger: Arc<Mutex<LedgerWriter>>,
    pub prepared: PreparedJointTextTrainingRequestV1,
    pub predecessor: Vec<u8>,
}

#[derive(Debug, thiserror::Error)]
pub enum JointTextTrainingOwnerErrorV1 {
    #[error("Joint owner queue is full")]
    QueueFull,
    #[error("Joint owner channel is unavailable")]
    Unavailable,
    #[error("Joint owner acknowledgement is unknown; reconcile the original identity")]
    Uncertain,
    #[error("Joint owner binding or custody: {0}")]
    Owner(#[from] AgentdError),
    #[error("Joint unsigned completion: {0}")]
    Completion(#[from] JointTextTrainingErrorV1),
}

enum Command {
    Stage(oneshot::Sender<Result<JointTextInputRefV1, JointTextTrainingOwnerErrorV1>>),
    Complete {
        job: JointTextJobIdentityV1,
        response:
            oneshot::Sender<Result<JointTextTrainingCompletionV1, JointTextTrainingOwnerErrorV1>>,
    },
}

/// Kept by the actual in-process request producer. Sending cannot change the
/// fixed prepared request, inject output bytes, select a path, or start a job.
#[derive(Clone)]
pub struct JointTextTrainingOwnerHandleV1 {
    sender: mpsc::Sender<Command>,
}

impl JointTextTrainingOwnerHandleV1 {
    /// Stage this bootstrap's exact original input. A descriptor is data only;
    /// the ordinary authorized effect route remains necessary for Start.
    pub async fn stage(&self) -> Result<JointTextInputRefV1, JointTextTrainingOwnerErrorV1> {
        let (response, receive) = oneshot::channel();
        self.sender
            .try_send(Command::Stage(response))
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => JointTextTrainingOwnerErrorV1::QueueFull,
                mpsc::error::TrySendError::Closed(_) => JointTextTrainingOwnerErrorV1::Unavailable,
            })?;
        receive
            .await
            .map_err(|_| JointTextTrainingOwnerErrorV1::Uncertain)?
    }

    /// Read the original bound job through the actual custody owner. Unknown,
    /// failed or changed jobs do not trigger Start or an automatic retry.
    pub async fn completed_candidate(
        &self,
        job: JointTextJobIdentityV1,
    ) -> Result<JointTextTrainingCompletionV1, JointTextTrainingOwnerErrorV1> {
        job.validate()
            .map_err(|_| AgentdError::Invalid("invalid Joint job identity".into()))?;
        let (response, receive) = oneshot::channel();
        self.sender
            .try_send(Command::Complete { job, response })
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => JointTextTrainingOwnerErrorV1::QueueFull,
                mpsc::error::TrySendError::Closed(_) => JointTextTrainingOwnerErrorV1::Unavailable,
            })?;
        receive
            .await
            .map_err(|_| JointTextTrainingOwnerErrorV1::Uncertain)?
    }
}

/// Consumed once by the ordinary runtime after its effect host has opened.
/// This service returns unsigned data and never implements stage attestations,
/// adoption, proposal preparation, or the original checkpoint CAS mutation.
pub struct JointTextTrainingOwnerBootstrapV1 {
    agent_id: AgentId,
    spawn_generation: u64,
    checkpoint: Arc<JointTextCheckpointBindingV1>,
    memory: Arc<CognitiveStore>,
    ledger: Arc<Mutex<LedgerWriter>>,
    prepared: PreparedJointTextTrainingRequestV1,
    predecessor: Vec<u8>,
    input: JointTextInputRefV1,
    receiver: mpsc::Receiver<Command>,
}

pub fn joint_text_training_owner_channel_v1(
    inputs: JointTextTrainingOwnerInputsV1,
    capacity: usize,
) -> Result<
    (
        JointTextTrainingOwnerHandleV1,
        JointTextTrainingOwnerBootstrapV1,
    ),
    AgentdError,
> {
    if inputs.spawn_generation == 0
        || !(1..=MAX_OWNER_QUEUE).contains(&capacity)
        || inputs
            .prepared
            .iteration_snapshot()
            .request
            .agent_id
            .as_str()
            != inputs.agent_id.as_str()
    {
        return Err(AgentdError::Invalid(
            "Joint owner requires the original agent, generation and bounded queue".into(),
        ));
    }
    let input = inputs
        .prepared
        .input_reference(&inputs.predecessor)
        .map_err(|error| AgentdError::Invalid(format!("Joint prepared input: {error}")))?;
    let checkpoint = Arc::new(JointTextCheckpointBindingV1::bind(
        inputs.checkpoint,
        inputs.prepared.iteration_snapshot().clone(),
    )?);
    let (sender, receiver) = mpsc::channel(capacity);
    Ok((
        JointTextTrainingOwnerHandleV1 { sender },
        JointTextTrainingOwnerBootstrapV1 {
            agent_id: inputs.agent_id,
            spawn_generation: inputs.spawn_generation,
            checkpoint,
            memory: inputs.memory,
            ledger: inputs.ledger,
            prepared: inputs.prepared,
            predecessor: inputs.predecessor,
            input,
            receiver,
        },
    ))
}

impl JointTextTrainingOwnerBootstrapV1 {
    pub(crate) fn require_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if self.agent_id != identity.agent_id || self.spawn_generation != identity.spawn_generation
        {
            return Err(AgentdError::GenerationFenced(
                "Joint owner bootstrap differs from the actual Agentd incarnation".into(),
            ));
        }
        Ok(())
    }

    pub(crate) async fn run(
        mut self,
        state: Arc<AgentdState>,
        host: Arc<AgentdAutomationEffectHost>,
        store: AutomationStore,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        self.require_identity(state.identity())?;
        loop {
            let command = tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                command = self.receiver.recv() => command,
            };
            let Some(command) = command else {
                // No request producer means no work. Never manufacture a
                // request or label an idle channel as a complete profile.
                cancellation.cancelled().await;
                return Ok(());
            };
            match command {
                Command::Stage(response) => {
                    if response.is_closed() {
                        continue;
                    }
                    let result = self.stage(&state, &host);
                    let _ = response.send(result);
                }
                Command::Complete { job, response } => {
                    if response.is_closed() {
                        continue;
                    }
                    let result = tokio::select! {
                        _ = cancellation.cancelled() => {
                            let _ = response.send(Err(JointTextTrainingOwnerErrorV1::Uncertain));
                            return Ok(());
                        }
                        result = self.complete(&state, &host, &store, &job) => result,
                    };
                    let _ = response.send(result);
                }
            }
        }
    }

    fn stage(
        &self,
        state: &AgentdState,
        host: &AgentdAutomationEffectHost,
    ) -> Result<JointTextInputRefV1, JointTextTrainingOwnerErrorV1> {
        self.require_live_owner(state)?;
        self.checkpoint.require_current()?;
        // The opened effect host rejects non-Joint/unsigned deployments, verifies
        // sources and held custody, and retains this same current guard for
        // every actual Start contact through the original FinalUse driver.
        let input = host.stage_joint_text_input(
            &self.prepared,
            &self.predecessor,
            Arc::clone(&self.checkpoint),
        )?;
        if input != self.input {
            return Err(AgentdError::Protocol("Joint staged descriptor changed".into()).into());
        }
        self.checkpoint.require_current()?;
        self.require_live_owner(state)?;
        Ok(input)
    }

    async fn complete(
        &self,
        state: &AgentdState,
        host: &AgentdAutomationEffectHost,
        store: &AutomationStore,
        job: &JointTextJobIdentityV1,
    ) -> Result<JointTextTrainingCompletionV1, JointTextTrainingOwnerErrorV1> {
        self.require_live_owner(state)?;
        self.checkpoint.require_current()?;
        job.validate()
            .map_err(|_| AgentdError::Invalid("invalid Joint job identity".into()))?;
        let wire = self
            .input
            .encode()
            .map_err(|_| AgentdError::Invalid("invalid original Joint descriptor".into()))?;
        if job.payload_sha256 != Sha256Digest::for_bytes(&wire) {
            return Err(
                AgentdError::GenerationFenced("Joint job selects another input".into()).into(),
            );
        }
        let now_ms = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|_| AgentdError::Protocol("Joint owner clock precedes Unix epoch".into()))?
                .as_millis(),
        )
        .map_err(|_| AgentdError::Protocol("Joint owner clock overflow".into()))?;
        // Only this fixed-custody API reads outputs. It verifies the recorded
        // original TaskFlow binding/current fence and rejects failed markers;
        // no caller supplies candidate bytes or infers a run ID from Ledger.
        let output = host
            .read_joint_text_training_output(store, job, &self.input, now_ms)
            .await?;
        self.checkpoint.require_current()?;
        let candidate = revalidate_joint_text_training_output_v1(
            &self.memory,
            &self.ledger,
            self.checkpoint.iteration_snapshot(),
            &self.prepared,
            JointTextTrainingOutputBytesV1 {
                started: &output.started,
                candidate: &output.candidate,
                observation: &output.observation,
                completed: &output.completed,
                failed: None,
            },
        )
        .await?;
        self.checkpoint.require_current()?;
        self.require_live_owner(state)?;
        // These measurements and the digest come from the same verified
        // original terminal, not from H-B output claims or a second run.
        Ok(JointTextTrainingCompletionV1 {
            candidate,
            terminal_digest: output.terminal_digest,
            runner_wall_nanoseconds: output.runner_wall_nanoseconds,
            runner_child_cpu_nanoseconds: output.runner_child_cpu_nanoseconds,
            scope: "joint_text_runner_claim_to_terminal_v1",
            full_history_cost: None,
        })
    }

    fn require_live_owner(&self, state: &AgentdState) -> Result<(), AgentdError> {
        self.require_identity(state.identity())?;
        if !state.automation_admission_ready()? || !state.automation_is_available()? {
            return Err(AgentdError::GenerationFenced(
                "Joint owner requires the ordinary running and ready automation host".into(),
            ));
        }
        Ok(())
    }
}
