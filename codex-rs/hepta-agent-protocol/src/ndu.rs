//! Bounded local control transport, never a substitute for final-use authority.
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NduMutationOperationV1 {
    AppendPreference,
    AppendUtility,
    Select,
    Revoke,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NduMutationV1 {
    pub operation: NduMutationOperationV1,
    pub identity: [u8; 32],
    pub objective: [u8; 32],
    pub subject: [u8; 32],
    pub projection: [u8; 32],
    pub expected_predecessor: Option<[u8; 32]>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
pub enum NduControlRequestV1 {
    Context,
    Prepare {
        mutation: NduMutationV1,
        expected_head: [u8; 32],
    },
    Apply {
        mutation: NduMutationV1,
        expected_head: [u8; 32],
        grant: SignedFinalUseGrant,
    },
    Selection {
        objective: [u8; 32],
        subject: [u8; 32],
    },
    Outcome {
        identity: [u8; 32],
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NduCommittedEntryV1 {
    pub operation: NduMutationOperationV1,
    pub sequence: u64,
    pub identity: [u8; 32],
    pub objective: [u8; 32],
    pub subject: [u8; 32],
    pub projection: [u8; 32],
    pub predecessor_entry: [u8; 32],
    pub entry_digest: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "result", rename_all = "snake_case", deny_unknown_fields)]
pub enum NduControlResultV1 {
    Context {
        journal_head: [u8; 32],
        revocation_head: [u8; 32],
        principal_id: String,
        host_generation: u64,
        policy_digest: [u8; 32],
    },
    Prepared {
        journal_head: [u8; 32],
        binding: FinalUseBinding,
    },
    Committed {
        entry: NduCommittedEntryV1,
    },
    Selection {
        journal_head: [u8; 32],
        projection: Option<[u8; 32]>,
    },
    Outcome {
        entry: Option<NduCommittedEntryV1>,
    },
}
