//! Public product-learning receipts and terminal bindings.

use codex_hepta_intelligence::CanonicalIntelligenceError;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::IntelligenceLearningAppendStateV1;
use crate::IntelligenceLearningOutboxErrorV1;
use crate::RunPhase;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceLearningAppendReceiptV1 {
    pub operation_id: String,
    pub outbox_revision: u64,
    pub state: IntelligenceLearningAppendStateV1,
    pub append: AppendReceipt,
}

/// Exact terminal observation binding produced only after the Agentd run owner
/// has observed a physical terminal state. Fields are crate-private so external
/// callers cannot mint a binding without `PreparedAgentdIntelligenceRunV1`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceTerminalBindingV1 {
    pub(crate) run_id: StableId,
    pub(crate) run_revision: u64,
    pub(crate) phase: RunPhase,
    pub(crate) selected_candidate_id: StableId,
    pub(crate) run_snapshot_digest: Digest32,
    pub(crate) context_digest: Digest32,
    pub(crate) envelope_digest: Digest32,
    pub(crate) physical_terminal_digest: Digest32,
}

impl AgentdIntelligenceTerminalBindingV1 {
    #[must_use]
    pub fn run_id(&self) -> &StableId {
        &self.run_id
    }

    #[must_use]
    pub const fn run_revision(&self) -> u64 {
        self.run_revision
    }

    #[must_use]
    pub const fn phase(&self) -> RunPhase {
        self.phase
    }

    #[must_use]
    pub fn selected_candidate_id(&self) -> &StableId {
        &self.selected_candidate_id
    }

    #[must_use]
    pub const fn run_snapshot_digest(&self) -> Digest32 {
        self.run_snapshot_digest
    }

    #[must_use]
    pub const fn physical_terminal_digest(&self) -> Digest32 {
        self.physical_terminal_digest
    }
}

#[derive(Debug, thiserror::Error)]
pub enum AgentdIntelligenceLearningErrorV1 {
    #[error("canonical intelligence learning binding: {0}")]
    Binding(&'static str),
    #[error("canonical intelligence currentness: {0}")]
    Currentness(#[source] CanonicalIntelligenceError),
    #[error("canonical intelligence learning outbox: {0}")]
    Outbox(#[from] IntelligenceLearningOutboxErrorV1),
    #[error("canonical intelligence learning ledger: {0}")]
    Ledger(#[source] ProductionLedgerError),
    #[error("canonical intelligence learning append is indeterminate: {operation_id}")]
    Indeterminate {
        operation_id: String,
        receipt: Option<AppendReceipt>,
    },
}
