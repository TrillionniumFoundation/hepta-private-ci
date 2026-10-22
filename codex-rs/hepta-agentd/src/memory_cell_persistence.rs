//! Explicit host-owned MemoryCell persistence on the already recovered writer.
//! A committed checkpoint whose independent witness cannot be retained blocks
//! further use until the host acknowledges the exact committed cut.

use std::sync::Arc;

use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::DurableCognitiveSnapshot;
use codex_hepta_memory::MemoryCellCheckpointReceiptV1;
use codex_hepta_memory::MemoryCellPersistencePlanV1;
use codex_hepta_memory::MemoryCellPersistencePositionV1;
use codex_hepta_memory::OwnerMemoryCellExecutionV1;
use codex_hepta_memory::PreparedMemoryCellRetrievalV1;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_memory::ProductionMemoryCellStateCapability;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_memory::prepare_memory_cell_retrieval_v1;
use codex_hepta_types::Digest32;
use tokio::sync::Mutex;
use tokio::sync::OwnedMutexGuard;

use crate::CurrentMemoryRetrievalContext;

#[derive(Clone, Debug)]
pub struct PendingMemoryCellCheckpointV1 {
    pub expected_plan: MemoryCellPersistencePlanV1,
    pub receipt: MemoryCellCheckpointReceiptV1,
    pub recovery_anchor: Option<CognitiveRecoveryAnchor>,
    /// The pure tick's candidate, never used as the persisted checkpoint pin.
    pub shadow_candidate_digest: Option<Digest32>,
}

pub struct AgentdMemoryCellPersistenceHostV1 {
    writer: Arc<ProductionDurableWriter>,
    capability: ProductionMemoryCellStateCapability,
    current: Arc<dyn CurrentMemoryRetrievalContext>,
    operation: Arc<Mutex<()>>,
    pending: Mutex<Option<PendingMemoryCellCheckpointV1>>,
}

pub(crate) struct PreparedAgentdMemoryCellV1 {
    pub(crate) prepared: PreparedMemoryCellRetrievalV1,
    _guard: OwnedMutexGuard<()>,
}

impl AgentdMemoryCellPersistenceHostV1 {
    pub(crate) fn new(
        writer: Arc<ProductionDurableWriter>,
        current: Arc<dyn CurrentMemoryRetrievalContext>,
    ) -> Result<Self, String> {
        let capability = writer
            .memory_cell_state_capability()
            .map_err(|error| error.to_string())?;
        let context = current.current(writer.owner_agent_id(), writer.generation())?;
        current
            .checkpoint_plan(writer.owner_agent_id(), writer.generation())?
            .validate_context(&context)
            .map_err(|error| error.to_string())?;
        Ok(Self {
            writer,
            capability,
            current,
            operation: Arc::new(Mutex::new(())),
            pending: Mutex::new(None),
        })
    }

    pub async fn pending_checkpoint(&self) -> Option<PendingMemoryCellCheckpointV1> {
        self.pending.lock().await.clone()
    }

    /// Clear only a host-retained exact receipt/anchor after an interrupted
    /// acknowledgement. This never bootstraps, rewrites bytes, or chooses an
    /// older anchor. Retention remains the independently authenticated host's job.
    pub async fn acknowledge_retained_checkpoint(&self) -> Result<(), String> {
        let _guard = self.operation.lock().await;
        let pending = self
            .pending
            .lock()
            .await
            .clone()
            .ok_or("no pending checkpoint")?;
        self.writer
            .verify_current_authority()
            .await
            .map_err(|error| error.to_string())?;
        let expected_anchor = pending.recovery_anchor.as_ref().ok_or("committed checkpoint lacks a captured recovery anchor; explicit host recovery required")?;
        if self
            .writer
            .recovery_anchor()
            .await
            .map_err(|error| error.to_string())?
            != *expected_anchor
        {
            return Err("pending checkpoint recovery cut changed".into());
        }
        let plan = self.current_plan().await?;
        if !retains(&plan, &pending) {
            return Err("host has not retained the exact committed checkpoint".into());
        }
        *self.pending.lock().await = None;
        Ok(())
    }

    async fn current_plan(&self) -> Result<MemoryCellPersistencePlanV1, String> {
        let current = Arc::clone(&self.current);
        let owner = self.writer.owner_agent_id().clone();
        let generation = self.writer.generation();
        tokio::task::spawn_blocking(move || {
            let context = current.current(&owner, generation)?;
            let plan = current.checkpoint_plan(&owner, generation)?;
            plan.validate_context(&context)
                .map_err(|error| error.to_string())?;
            Ok(plan)
        })
        .await
        .map_err(|error| error.to_string())?
    }

    pub(crate) async fn prepare(
        &self,
        cut: &DurableCognitiveSnapshot,
        context: &RetrievalExecutionContextV1,
        now_unix_seconds: i64,
    ) -> Result<PreparedAgentdMemoryCellV1, String> {
        let guard = Arc::clone(&self.operation).lock_owned().await;
        if self.pending.lock().await.is_some() {
            return Err(
                "a committed MemoryCell checkpoint awaits exact host witness retention".into(),
            );
        }
        self.writer
            .verify_current_authority()
            .await
            .map_err(|error| error.to_string())?;
        if context.generation_vector.authority_epoch != self.writer.authority().authority_epoch {
            return Err("retrieval context and recovered writer authority epochs differ".into());
        }
        let plan = self.current_plan().await?;
        let prepared = prepare_memory_cell_retrieval_v1(
            &self.capability,
            &CognitiveAccess::agent_private(self.writer.owner_agent_id().clone()),
            &CognitiveScope::AgentPrivate,
            cut,
            context,
            &plan,
            now_unix_seconds,
        )
        .await
        .map_err(|error| error.to_string())?;
        Ok(PreparedAgentdMemoryCellV1 {
            prepared,
            _guard: guard,
        })
    }

    pub(crate) async fn persist(
        self: &Arc<Self>,
        session: PreparedAgentdMemoryCellV1,
        executed: OwnerMemoryCellExecutionV1,
        now_unix_seconds: i64,
    ) -> Result<(), String> {
        // The owned task completes the custody/retention attempt if a control
        // request is cancelled after SQLite commits. Any failed acknowledgement
        // remains observable through pending_checkpoint and blocks new work.
        let host = Arc::clone(self);
        tokio::spawn(async move {
            host.persist_owned(session, &executed, now_unix_seconds)
                .await
        })
        .await
        .map_err(|error| error.to_string())?
    }

    async fn persist_owned(
        &self,
        session: PreparedAgentdMemoryCellV1,
        executed: &OwnerMemoryCellExecutionV1,
        now_unix_seconds: i64,
    ) -> Result<(), String> {
        let expected = session.prepared.plan().clone();
        if self.current_plan().await? != expected {
            return Err("host MemoryCell manifest or current checkpoint changed".into());
        }
        let draft = session
            .prepared
            .checkpoint_draft(executed)
            .map_err(|error| error.to_string())?;
        let receipt = self
            .capability
            .commit(
                &CognitiveAccess::agent_private(self.writer.owner_agent_id().clone()),
                &CognitiveScope::AgentPrivate,
                &draft,
                now_unix_seconds,
            )
            .await
            .map_err(|error| error.to_string())?;
        let mut pending = PendingMemoryCellCheckpointV1 {
            expected_plan: expected,
            receipt,
            recovery_anchor: None,
            shadow_candidate_digest: executed
                .tick()
                .successor_checkpoint_digest
                .map(|value| value.digest()),
        };
        *self.pending.lock().await = Some(pending.clone());
        let anchor = self
            .writer
            .recovery_anchor()
            .await
            .map_err(|error| error.to_string())?;
        pending.recovery_anchor = Some(anchor.clone());
        *self.pending.lock().await = Some(pending.clone());
        let current = Arc::clone(&self.current);
        let owner = self.writer.owner_agent_id().clone();
        let generation = self.writer.generation();
        let committed = pending.clone();
        tokio::task::spawn_blocking(move || {
            current.retain_checkpoint(
                &owner,
                generation,
                &committed.expected_plan,
                &committed.receipt,
                &anchor,
            )
        })
        .await
        .map_err(|error| error.to_string())??;
        if !retains(&self.current_plan().await?, &pending) {
            return Err("host retention did not publish exact MemoryCell resume pins".into());
        }
        *self.pending.lock().await = None;
        Ok(())
    }
}

fn retains(plan: &MemoryCellPersistencePlanV1, pending: &PendingMemoryCellCheckpointV1) -> bool {
    let mut expected = pending.expected_plan.clone();
    expected.position = MemoryCellPersistencePositionV1::Resume(
        codex_hepta_memory::MemoryCellCheckpointReadPinsV1 {
            manifest: expected.manifest.clone(),
            checkpoint_digest: pending.receipt.checkpoint_digest,
            owner_cut_digest: pending.receipt.owner_cut_digest,
        },
    );
    // Identical pins cannot acknowledge a changed authenticated context,
    // objective, NDU state or resource budget after the commit.
    *plan == expected
}
