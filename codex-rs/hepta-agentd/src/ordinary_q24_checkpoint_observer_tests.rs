//! Test administrator observation of an already registered Root record. These
//! bytes only schedule external input production; they are never a grant, a
//! checkpoint owner, an attestation or a successful whole-process result.

use std::path::Path;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;

use super::LearningIterationCheckpointRecordV1;
use super::codec;

const OWNER: &str = "root-learning-checkpoint-v1";

pub(crate) struct OriginalCheckpointData {
    pub(crate) scope_binding: Digest32,
    pub(crate) snapshot: Option<LearningIterationSnapshotV1>,
}

impl OriginalCheckpointData {
    pub(crate) fn read_existing(
        directory: &Path,
        initial: &LearningIterationSnapshotV1,
    ) -> anyhow::Result<Self> {
        // Opening this concrete existing store performs no registration and
        // acquires no old writer lease or local evidence database owner.
        let store = HostAuthorityFrontierStore::<LearningIterationCheckpointRecordV1>::open(
            RootAuthorityDirectory::open(directory)?,
            OWNER.into(),
        )?;
        let record = store.load(OWNER)?;
        anyhow::ensure!(record.schema == 2, "original scoped Root checkpoint data");
        let scope_binding: Digest32 = record.binding.parse()?;
        anyhow::ensure!(
            !scope_binding.is_zero(),
            "original frozen scope data absent"
        );
        let Some(encoded) = &record.snapshot else {
            anyhow::ensure!(
                record.predecessor == Digest32::ZERO.to_string(),
                "vacant original Root checkpoint has a predecessor"
            );
            return Ok(Self {
                scope_binding,
                snapshot: None,
            });
        };
        anyhow::ensure!(
            encoded.len() <= codec::MAX_BYTES.div_ceil(3) * 4,
            "original checkpoint image exceeds its existing codec bound"
        );
        let mut bytes = [0_u8; codec::MAX_BYTES];
        let length = STANDARD_NO_PAD.decode_slice(encoded, &mut bytes)?;
        let bytes = &bytes[..length];
        anyhow::ensure!(
            STANDARD_NO_PAD.encode(bytes) == *encoded,
            "original checkpoint encoding is not canonical"
        );
        let snapshot = codec::decode(bytes)?;
        anyhow::ensure!(
            snapshot.request == initial.request && snapshot.owners == initial.owners,
            "Root checkpoint belongs to another original request or owner set"
        );
        let predecessor = snapshot
            .receipts
            .last()
            .map_or(Digest32::ZERO, |receipt| receipt.predecessor);
        anyhow::ensure!(
            record.predecessor == predecessor.to_string(),
            "original checkpoint predecessor differs"
        );
        Ok(Self {
            scope_binding,
            snapshot: Some(snapshot),
        })
    }

    pub(crate) fn require_same_or_extended(&self, previous: &Self) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.scope_binding == previous.scope_binding,
            "actual Root frozen scope changed"
        );
        match (&previous.snapshot, &self.snapshot) {
            (None, _) => Ok(()),
            (Some(_), None) => anyhow::bail!("actual Root checkpoint became vacant"),
            (Some(before), Some(after)) => {
                anyhow::ensure!(
                    after.request == before.request
                        && after.owners == before.owners
                        && after.receipts.starts_with(&before.receipts)
                        && (after.receipts.len() != before.receipts.len() || after == before),
                    "actual Root checkpoint is not the same original receipt prefix"
                );
                Ok(())
            }
        }
    }
}
