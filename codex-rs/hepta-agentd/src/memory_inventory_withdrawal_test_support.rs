//! Test-only handoff of a parent-retained frontier receipt. The existing
//! snapshot codec checks bytes and chain; production must authenticate the
//! frontier owner and retain its rollback floor outside the snapshot itself.

use std::fs::File;
use std::path::Path;

use codex_hepta_learning_artifacts::{DatasetWithdrawalRegistry, DatasetWithdrawalSnapshotReceiptV1,
    read_dataset_withdrawal_snapshot, write_dataset_withdrawal_snapshot_beneath};
use serde::{Deserialize, Serialize};

use crate::memory_cell_release::test_support::digest;

const FRONTIER_FILE: &str = "inventory-withdrawal-frontier.snapshot";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct InventoryWithdrawalCheckpoint {
    binding: String,
    scope_digest: String,
    head_digest: String,
    file_digest: String,
    records: usize,
    encoded_bytes: usize,
}

impl InventoryWithdrawalCheckpoint {
    pub fn capture(root: &Path, registry: &DatasetWithdrawalRegistry) -> Self {
        let receipt = write_dataset_withdrawal_snapshot_beneath(root, FRONTIER_FILE, registry,
            digest("inventory-native-actual-withdrawal-storage-binding")).expect("existing create-only withdrawal snapshot writer");
        Self { binding:receipt.binding.to_string(), scope_digest:receipt.scope_digest.to_string(),
            head_digest:receipt.head_digest.to_string(), file_digest:receipt.file_digest.to_string(), records:receipt.records, encoded_bytes:receipt.encoded_bytes }
    }

    pub fn restore(&self, root: &Path) -> DatasetWithdrawalRegistry {
        let receipt = DatasetWithdrawalSnapshotReceiptV1 {
            binding:self.binding.parse().expect("retained withdrawal binding"),
            scope_digest:self.scope_digest.parse().expect("retained withdrawal scope"),
            head_digest:self.head_digest.parse().expect("retained withdrawal head"),
            file_digest:self.file_digest.parse().expect("retained withdrawal file digest"),
            records:self.records, encoded_bytes:self.encoded_bytes,
        };
        read_dataset_withdrawal_snapshot(File::open(root.join(FRONTIER_FILE)).expect("saved owner frontier"), receipt)
            .expect("existing bounded frontier reader with independent expected receipt")
    }
}
