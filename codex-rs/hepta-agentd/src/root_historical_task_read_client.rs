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
use crate::root_historical_ledger_data::RootHistoricalLedgerReadDataV1;
use crate::root_historical_task_read_protocol::HistoricalTaskReadDataV1;
use crate::root_historical_task_read_protocol::HistoricalTaskReadRequestV1;
use crate::root_historical_task_read_protocol::MAX_READS;
use crate::root_historical_task_read_protocol::PURPOSE;
use crate::root_historical_task_read_protocol::require_complete_reply;
use crate::root_production_inputs::RootHistoricalTaskReadConnectionV1;

#[path = "root_historical_task_read_inputs.rs"]
mod inputs;

struct Lane {
    stream: OriginalPublicationStream,
    sequence: u64,
}

pub(crate) struct RootHistoricalTaskReadClientV1 {
    connection: RootHistoricalTaskReadConnectionV1,
    profile: String,
    initial: LearningIterationSnapshotV1,
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
    ) -> Result<Self, AgentdError> {
        connection.require_original_session()?;
        Ok(Self {
            connection,
            profile,
            initial,
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
                purpose: PURPOSE.into(),
                request_id,
                profile: self.profile.clone(),
            })
            .map_err(io::Error::other)?;
            let bytes = lane.stream.exchange(&request)?;
            let data = require_complete_reply(&bytes, request_id, &self.profile)?;
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

    /// The caller performs real readonly file validation in this callback.
    /// No caller-supplied cut can replace either live original Root reply.
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
