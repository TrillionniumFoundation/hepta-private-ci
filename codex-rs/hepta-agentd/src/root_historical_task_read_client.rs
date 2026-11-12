//! Same original Root historical read lane. Only actual responses can form a
//! receipt; every later physical read is enclosed by live Root revalidation.

use std::io;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;

use crate::AgentdError;
use crate::AgentdRootAuthoritySession;
use crate::root_generation_current_client::OriginalPublicationStream;
use crate::root_historical_learning_trust_data::HistoricalLearningTrustPinV1;
use crate::root_historical_learning_trust_data::HistoricalLearningTrustResponseV1;
use crate::root_historical_learning_trust_data::require_original_trust_reply;
use crate::root_historical_ledger_data::RootHistoricalLedgerReadDataV1;
use crate::root_historical_task_read_protocol::HistoricalReadOperationV1;
use crate::root_historical_task_read_protocol::HistoricalTaskReadDataV1;
use crate::root_historical_task_read_protocol::HistoricalTaskReadRequestV1;
use crate::root_historical_task_read_protocol::MAX_READS;
use crate::root_historical_task_read_protocol::PURPOSE;
use crate::root_historical_task_read_protocol::require_complete_reply;
use crate::root_production_inputs::RootHistoricalTaskReadConnectionV1;

#[path = "root_historical_task_read_inputs.rs"]
mod inputs;
#[path = "root_historical_learning_trust_client.rs"]
mod learning_trust;
pub(crate) use learning_trust::OriginalHistoricalLearningTrustV1;

struct Lane {
    stream: OriginalPublicationStream,
    sequence: u64,
}

enum Reply {
    Task(Box<HistoricalTaskReadDataV1>),
    LearningTrust(Box<HistoricalLearningTrustResponseV1>),
}

pub(crate) struct RootHistoricalTaskReadClientV1 {
    connection: RootHistoricalTaskReadConnectionV1,
    profile: String,
    initial: LearningIterationSnapshotV1,
    learning_trust: HistoricalLearningTrustPinV1,
    lane: Mutex<Option<Lane>>,
    fenced: AtomicBool,
}

/// Opaque same-client receipt. Serialized reply data alone cannot construct it
/// or admit a Dataset view. The actual Root route remains required per read.
pub(crate) struct OriginalHistoricalTaskReadReceiptV1 {
    client: Arc<RootHistoricalTaskReadClientV1>,
    data: HistoricalTaskReadDataV1,
}

impl RootHistoricalTaskReadClientV1 {
    fn from_original_stream(
        stream: OriginalPublicationStream,
        connection: RootHistoricalTaskReadConnectionV1,
        profile: String,
        initial: LearningIterationSnapshotV1,
        learning_trust: HistoricalLearningTrustPinV1,
    ) -> Result<Self, AgentdError> {
        connection.require_original_session()?;
        learning_trust.require_initial(&initial)?;
        Ok(Self {
            connection,
            profile,
            initial,
            learning_trust,
            lane: Mutex::new(Some(Lane {
                stream,
                sequence: 1,
            })),
            fenced: AtomicBool::new(false),
        })
    }

    pub(crate) fn require_same_original_session(
        &self,
        session: &AgentdRootAuthoritySession,
    ) -> Result<(), AgentdError> {
        let result = if self.fenced.load(Ordering::Acquire) {
            Err(AgentdError::GenerationFenced(
                "original historical read is fenced".into(),
            ))
        } else {
            self.connection.require_same_original_session(session)
        };
        if result.is_err() {
            self.fence();
        }
        result
    }

    pub(crate) fn observe_original_task(
        self: &Arc<Self>,
    ) -> io::Result<OriginalHistoricalTaskReadReceiptV1> {
        let data = self.observe()?;
        Ok(OriginalHistoricalTaskReadReceiptV1 {
            client: Arc::clone(self),
            data,
        })
    }

    fn observe(&self) -> io::Result<HistoricalTaskReadDataV1> {
        match self.exchange(HistoricalReadOperationV1::Task)? {
            Reply::Task(data) => Ok(*data),
            Reply::LearningTrust(_) => {
                self.fence();
                Err(refused())
            }
        }
    }

    fn exchange(&self, operation: HistoricalReadOperationV1) -> io::Result<Reply> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(refused());
        }
        let mut held = self.lane.try_lock().map_err(|_| {
            self.fenced.store(true, Ordering::Release);
            refused()
        })?;
        let result = (|| {
            self.connection
                .require_original_session()
                .map_err(io::Error::other)?;
            let mut lane = held.take().ok_or_else(refused)?;
            let request_id = lane.sequence;
            if !(1..=MAX_READS).contains(&request_id) {
                return Err(refused());
            }
            let request = serde_json::to_vec(&HistoricalTaskReadRequestV1 {
                schema: 1,
                purpose: operation.purpose().into(),
                request_id,
                profile: self.profile.clone(),
            })
            .map_err(io::Error::other)?;
            let bytes = lane.stream.exchange(&request)?;
            let data =
                match operation {
                    HistoricalReadOperationV1::Task => Reply::Task(Box::new(
                        require_complete_reply(&bytes, request_id, &self.profile)?,
                    )),
                    HistoricalReadOperationV1::LearningTrust => {
                        Reply::LearningTrust(Box::new(require_original_trust_reply(
                            &bytes,
                            request_id,
                            &self.profile,
                            &self.learning_trust,
                            &self.initial,
                        )?))
                    }
                };
            self.connection
                .require_original_session()
                .map_err(io::Error::other)?;
            if self.fenced.load(Ordering::Acquire) {
                return Err(refused());
            }
            lane.sequence = request_id.checked_add(1).ok_or_else(refused)?;
            *held = Some(lane);
            Ok(data)
        })();
        if result.is_err() {
            self.fenced.store(true, Ordering::Release);
            held.take();
        }
        result
    }

    fn fence(&self) {
        self.fenced.store(true, Ordering::Release);
        if let Ok(mut held) = self.lane.try_lock() {
            held.take();
        }
    }
}

impl OriginalHistoricalTaskReadReceiptV1 {
    pub(crate) fn require_original_client(
        &self,
        client: &Arc<RootHistoricalTaskReadClientV1>,
        session: &AgentdRootAuthoritySession,
    ) -> Result<(), AgentdError> {
        RootHistoricalTaskReadClientV1::require_same_original_session(&self.client, session)?;
        if !Arc::ptr_eq(&self.client, client) {
            self.client.fence();
            return Err(AgentdError::GenerationFenced(
                "historical receipt belongs to another actual Root client".into(),
            ));
        }
        RootHistoricalTaskReadClientV1::require_same_original_session(&self.client, session)
    }

    pub(crate) fn initial_snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.client.initial
    }

    /// Return only data from another complete physical read by the same Root.
    /// No consumer-side Source or Cell file is opened after the refusal arms
    /// return; pure decoding cannot hide a second physical read failure.
    pub(crate) fn read_original_publication(
        &self,
    ) -> io::Result<(
        crate::CircuitTaskSourcePublicationV1,
        codex_hepta_neuron::CellDecisionReceiptV1,
    )> {
        let result = (|| {
            let observed: HistoricalTaskReadDataV1 = self.client.observe()?;
            if observed != self.data {
                return Err(refused());
            }
            observed
                .publication
                .validate_against(&observed.ledger)
                .map_err(io::Error::other)
        })();
        if result.is_err() {
            self.client.fence();
        }
        result
    }

    /// Pure decoding and current recipient checks use the Root-observed image.
    /// No second consumer file read can escape Root's persistent refusal arms.
    pub(crate) fn with_current_read<T>(
        &self,
        action: impl FnOnce(&RootHistoricalLedgerReadDataV1) -> io::Result<T>,
    ) -> io::Result<T> {
        let result = (|| {
            if self.client.observe()? != self.data {
                return Err(refused());
            }
            let value = action(&self.data.ledger)?;
            if self.client.observe()? != self.data {
                return Err(refused());
            }
            Ok(value)
        })();
        if result.is_err() {
            self.client.fence();
        }
        result
    }
}

fn refused() -> io::Error {
    io::Error::other("original complete historical task read unavailable")
}
