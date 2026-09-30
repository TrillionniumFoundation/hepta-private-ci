use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use super::*;
use std::path::PathBuf;

type Response = oneshot::Sender<Result<AgentdSelfIterationRecordV1, AgentdError>>;
enum Command {
    Freeze(Box<AgentdSelfIterationCandidateV1>, Response),
    Evaluate(Digest32, Box<AgentdSignedEvaluationV1>, Response),
    Select(Digest32, SignedLearningEvidenceV1, Response),
    Observe(
        Digest32,
        AgentdSelfIterationCanaryVerdictV1,
        SignedLearningEvidenceV1,
        Response,
    ),
}

impl Command {
    fn reject(self, error: AgentdError) {
        let response = match self {
            Self::Freeze(_, response)
            | Self::Evaluate(_, _, response)
            | Self::Select(_, _, response)
            | Self::Observe(_, _, _, response) => response,
        };
        let _ = response.send(Err(error));
    }
}

/// Bounded product handle. The caller receives neither signing material nor
/// mutable journal/controller access. Model assessments alone cannot select.
#[derive(Clone)]
pub struct AgentdSelfIterationHandleV1 {
    sender: mpsc::Sender<Command>,
}
impl AgentdSelfIterationHandleV1 {
    pub async fn freeze(
        &self,
        candidate: AgentdSelfIterationCandidateV1,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(Command::Freeze(Box::new(candidate), response), receive)
            .await
    }
    pub async fn evaluate(
        &self,
        frozen: Digest32,
        evaluation: AgentdSignedEvaluationV1,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::Evaluate(frozen, Box::new(evaluation), response),
            receive,
        )
        .await
    }
    pub async fn select(
        &self,
        frozen: Digest32,
        attestation: SignedLearningEvidenceV1,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(Command::Select(frozen, attestation, response), receive)
            .await
    }
    pub async fn observe(
        &self,
        frozen: Digest32,
        verdict: AgentdSelfIterationCanaryVerdictV1,
        attestation: SignedLearningEvidenceV1,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::Observe(frozen, verdict, attestation, response),
            receive,
        )
        .await
    }
    async fn send(
        &self,
        command: Command,
        receive: oneshot::Receiver<Result<AgentdSelfIterationRecordV1, AgentdError>>,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        self.sender
            .try_send(command)
            .map_err(|error| invalid(format!("self-iteration admission: {error}")))?;
        // Cancellation or timeout drops only the reply. The sole runtime owner
        // retains work and capacity until the actual operation has retired.
        tokio::time::timeout(std::time::Duration::from_secs(15), receive)
            .await
            .map_err(|_| invalid("self-iteration reply timed out; recover exact candidate"))?
            .map_err(|_| invalid("self-iteration owner closed"))?
    }
}

pub struct AgentdSelfIterationRuntimeConfigV1 {
    journal: IterationJournal,
    trust: Arc<ActivatedLearningTrustV1>,
    receiver: mpsc::Receiver<Command>,
}
impl AgentdSelfIterationRuntimeConfigV1 {
    pub fn new(
        journal_path: PathBuf,
        trust: Arc<ActivatedLearningTrustV1>,
    ) -> Result<(Self, AgentdSelfIterationHandleV1), AgentdError> {
        if !journal_path.is_absolute() || journal_path.file_name().is_none() {
            return Err(invalid("iteration journal path must be absolute"));
        }
        let journal = IterationJournal::open(journal_path)?;
        let (sender, receiver) = mpsc::channel(8);
        Ok((
            Self {
                journal,
                trust,
                receiver,
            },
            AgentdSelfIterationHandleV1 { sender },
        ))
    }
    pub(crate) fn unresolved_apply(&self) -> bool {
        self.journal.unresolved_apply()
    }

    pub(crate) fn start(
        self,
        host: Arc<AgentdNeuronRuntimeV2Host>,
    ) -> Result<SelfIterationRuntime, AgentdError> {
        let owner = SelfIterationOwner::open(self.journal, self.trust, host)?;
        Ok(SelfIterationRuntime {
            owner: Arc::new(std::sync::Mutex::new(owner)),
            receiver: self.receiver,
        })
    }
}

pub(crate) struct SelfIterationRuntime {
    owner: Arc<std::sync::Mutex<SelfIterationOwner>>,
    receiver: mpsc::Receiver<Command>,
}
impl SelfIterationRuntime {
    pub(crate) async fn run(mut self, cancellation: CancellationToken) -> Result<(), AgentdError> {
        self.owner
            .lock()
            .map_err(|_| invalid("self-iteration owner poisoned"))?
            .cancellation = cancellation.clone();
        let mut receiver_closed = false;
        let mut interval = tokio::time::interval(std::time::Duration::from_secs(1));
        interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            let command = tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                _ = interval.tick() => None,
                command = self.receiver.recv(), if !receiver_closed => match command {
                    Some(command) => Some(command),
                    None => { receiver_closed = true; continue; }
                },
            };
            let owner = Arc::clone(&self.owner);
            let lifetime = cancellation.clone();
            // Only one worker is ever admitted. This owner awaits actual worker
            // retirement rather than spawning another after request timeout.
            tokio::task::spawn_blocking(move || {
                if lifetime.is_cancelled() {
                    return Ok(());
                }
                let now = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map_err(|_| invalid("self-iteration clock"))?
                    .as_millis()
                    .try_into()
                    .map_err(|_| invalid("self-iteration clock overflow"))?;
                let mut owner = owner
                    .lock()
                    .map_err(|_| invalid("self-iteration owner poisoned"))?;
                match owner.expire(now) {
                    Ok(()) => {}
                    Err(error @ AgentdError::Overloaded { .. }) => {
                        if let Some(command) = command {
                            command.reject(error);
                        }
                        return Ok(());
                    }
                    Err(error) => return Err(error),
                }
                if let Some(command) = command {
                    let (result, response) = match command {
                        Command::Freeze(candidate, response) => {
                            (owner.freeze(*candidate, now), response)
                        }
                        Command::Evaluate(frozen, signed, response) => {
                            (owner.evaluate(frozen, *signed, now), response)
                        }
                        Command::Select(frozen, signed, response) => {
                            (owner.select(frozen, signed, now), response)
                        }
                        Command::Observe(frozen, verdict, signed, response) => {
                            (owner.observe(frozen, verdict, signed, now), response)
                        }
                    };
                    let _ = response.send(result);
                }
                Ok::<_, AgentdError>(())
            })
            .await
            .map_err(|error| invalid(format!("self-iteration worker: {error}")))??;
        }
    }
}
