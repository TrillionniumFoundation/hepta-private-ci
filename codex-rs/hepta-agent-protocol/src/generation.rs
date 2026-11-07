//! Optional local generation control. These are references to the sole owner's
//! committed facts, never model selection, adoption or publication grants.

use serde::Deserialize;
use serde::Serialize;

pub const AGENTD_GENERATION_CONTROL_CAPABILITY: &str = "cell.generation.control";
pub const MAX_GENERATION_CONTROL_INPUT_BYTES: usize = 8_192;
pub const MAX_GENERATION_OUTPUT_PAGE_BYTES: u16 = 8_192;

/// The owner derives a content-bound operation ID from this complete request.
/// Exact retries inspect that operation even after its deadline or a reopen.
/// Admission time and the full predecessor bytes are supplied only by the owner.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationStepV1 {
    pub client_operation_id: String,
    pub expected_snapshot_digest: [u8; 32],
    pub task_digest: [u8; 32],
    pub source_frontier: [u8; 32],
    pub input: Vec<u8>,
    /// Uses the host clock epoch observed in Status, not a client wall clock.
    pub deadline_micros: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
pub enum GenerationControlRequestV1 {
    // Empty struct variants retain strict field validation for tagged JSON.
    Status {},
    Step {
        request: Box<GenerationStepV1>,
    },
    Reconcile {
        request_digest: [u8; 32],
    },
    Cancel {
        request_digest: [u8; 32],
    },
    Output {
        expected_chunk_digest: [u8; 32],
        offset: u32,
        limit: u16,
    },
    Acknowledge {
        delivery: GenerationOutputReferenceV1,
        acknowledgement: [u8; 32],
    },
    Cost {},
    Drain {},
    Resume {},
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationPendingV1 {
    pub operation_id: String,
    pub request_digest: [u8; 32],
    pub admitted_at_micros: u64,
    pub deadline_micros: u64,
}

/// Identifies one whole immutable outbox chunk. Pages never acknowledge it.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationOutputReferenceV1 {
    pub operation_id: String,
    pub request_digest: [u8; 32],
    pub prefix_offset: u64,
    pub bytes: u32,
    pub chunk_digest: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationStatusV1 {
    pub snapshot_digest: [u8; 32],
    pub manifest_digest: [u8; 32],
    pub principal_digest: [u8; 32],
    pub agent_id: String,
    pub cell_id: String,
    pub run_id: String,
    pub generation: u64,
    pub writer_epoch: u64,
    pub revision: u64,
    pub state_bytes: u32,
    pub prefix_bytes: u32,
    pub stopped: bool,
    pub drained: bool,
    pub observed_at_micros: u64,
    pub pending: Option<GenerationPendingV1>,
    pub output: Option<GenerationOutputReferenceV1>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum GenerationDispositionV1 {
    Advanced,
    Stopped,
    Cancelled,
    Failed,
    Rejected,
    DeadlineExceeded,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationReceiptV1 {
    pub operation_id: String,
    pub request_digest: [u8; 32],
    pub proposal_digest: [u8; 32],
    pub checkpoint_after: [u8; 32],
    pub disposition: GenerationDispositionV1,
    pub cost_digest: [u8; 32],
    pub cost_entries: u32,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationCostTotalV1 {
    pub known_sum: u64,
    pub unknown_entries: u32,
}

/// Observed subtotals and explicit missing coverage, not full physical cost.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationCostSummaryV1 {
    pub task_digest: [u8; 32],
    pub source_digest: [u8; 32],
    pub ledger_digest: [u8; 32],
    pub wall_work_micros: GenerationCostTotalV1,
    pub cpu_micros: GenerationCostTotalV1,
    pub energy_microjoules: GenerationCostTotalV1,
    pub storage_read_bytes: GenerationCostTotalV1,
    pub storage_write_bytes: GenerationCostTotalV1,
    pub storage_byte_micros: GenerationCostTotalV1,
    pub communication_bytes: GenerationCostTotalV1,
    pub missing_stages: Vec<String>,
    pub exclusive_entries: u32,
    pub inclusive_envelopes: u32,
    pub unsuccessful_entries: u32,
    pub unknown_outcome_entries: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "outcome", rename_all = "snake_case", deny_unknown_fields)]
pub enum GenerationControlResponseV1 {
    Status(Box<GenerationStatusV1>),
    Receipt(GenerationReceiptV1),
    Pending(GenerationPendingV1),
    Output {
        delivery: GenerationOutputReferenceV1,
        offset: u32,
        bytes: Vec<u8>,
        complete: bool,
    },
    Cost(Box<GenerationCostSummaryV1>),
    Acknowledged {},
    CancelRequested {},
    Drain {
        complete: bool,
    },
    Resumed {},
}

#[cfg(test)]
#[path = "generation_tests.rs"]
mod tests;
