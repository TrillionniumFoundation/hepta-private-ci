//! Test administrator observation of an already registered Root record. These
//! bytes only schedule external input production; they are never a grant, a
//! checkpoint owner, an attestation or a successful whole-process result.

use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use sha2::Digest;
use sha2::Sha256;

use super::LearningIterationCheckpointRecordV1;
use super::codec;

const OWNER: &str = "root-learning-checkpoint-v1";
const RECORD_BYTES: usize = 16 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct OriginalCheckpointData {
    pub(crate) scope_binding: Digest32,
    pub(crate) snapshot: Option<LearningIterationSnapshotV1>,
}

impl OriginalCheckpointData {
    /// Scheduling DATA only. Never acquire the publication lock while the
    /// real Root is running: its nonblocking CAS uses that same exclusive lock.
    /// A replaced, fully valid immutable image is retried; malformed or missing
    /// records fail. The final observation still uses the concrete owner below.
    pub(crate) fn observe_live(
        directory: &Path,
        initial: &LearningIterationSnapshotV1,
    ) -> anyhow::Result<Option<Self>> {
        let _original_directory = RootAuthorityDirectory::open(directory)?;
        let suffix = Sha256::digest(OWNER.as_bytes());
        let path = directory.join(format!("frontier-v1-{suffix:x}.json"));
        let first = RecordImage::read(&path, initial)?;
        let second = RecordImage::read(&path, initial)?;
        RootAuthorityDirectory::open(directory)?;
        let named = std::fs::symlink_metadata(&path)?;
        require_private_record(&named)?;
        anyhow::ensure!(named.nlink() == 1, "named Root record is not published");
        // Both complete images were strictly decoded before classifying a
        // rename. A corrupt replacement is not an absent or completed cut.
        let first_now = first.require_unchanged_bytes()?;
        let second_now = second.require_unchanged_bytes()?;
        if (first_now.dev(), first_now.ino()) != (second_now.dev(), second_now.ino()) {
            anyhow::ensure!(
                first_now.nlink() == 0,
                "original checkpoint changed without replacing the old inode"
            );
            return Ok(None);
        }
        if (named.dev(), named.ino()) != (second_now.dev(), second_now.ino()) {
            anyhow::ensure!(
                second_now.nlink() == 0,
                "original checkpoint path changed without an immutable replacement"
            );
            return Ok(None);
        }
        anyhow::ensure!(
            second_now.nlink() == 1 && first.bytes == second.bytes,
            "original checkpoint image changed in place"
        );
        Ok(Some(second.data))
    }

    /// Use only after the actual original Root process has exited. This
    /// concrete existing owner performs the final durable-data confirmation.
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
        Self::from_record(record, initial)
    }

    fn from_record(
        record: LearningIterationCheckpointRecordV1,
        initial: &LearningIterationSnapshotV1,
    ) -> anyhow::Result<Self> {
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

// This is exactly the existing HostAuthorityFrontierStore data envelope. It
// cannot create the concrete store, a writer, or a checkpoint capability.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OriginalEnvelope {
    schema: u32,
    owner_id: String,
    frontier: LearningIterationCheckpointRecordV1,
}

struct RecordImage {
    file: File,
    original: std::fs::Metadata,
    bytes: Vec<u8>,
    data: OriginalCheckpointData,
}

impl RecordImage {
    fn read(path: &Path, initial: &LearningIterationSnapshotV1) -> anyhow::Result<Self> {
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open(path)?;
        let original = file.metadata()?;
        require_private_record(&original)?;
        let mut bytes = vec![0_u8; usize::try_from(original.len())?];
        file.read_exact_at(&mut bytes, 0)?;
        let envelope: OriginalEnvelope = serde_json::from_slice(&bytes)?;
        anyhow::ensure!(
            envelope.schema == 1 && envelope.owner_id == OWNER,
            "original Root checkpoint envelope differs"
        );
        let image = Self {
            data: OriginalCheckpointData::from_record(envelope.frontier, initial)?,
            file,
            original,
            bytes,
        };
        image.require_unchanged_bytes()?;
        Ok(image)
    }

    fn require_unchanged_bytes(&self) -> anyhow::Result<std::fs::Metadata> {
        let immutable = |value: &std::fs::Metadata| {
            (
                value.dev(),
                value.ino(),
                value.uid(),
                value.gid(),
                value.mode(),
                value.len(),
                value.mtime(),
                value.mtime_nsec(),
            )
        };
        let require_metadata = |current: &std::fs::Metadata| -> anyhow::Result<()> {
            anyhow::ensure!(
                immutable(current) == immutable(&self.original)
                    && current.nlink() <= self.original.nlink(),
                "original Root checkpoint inode changed in place"
            );
            if current.nlink() == self.original.nlink() {
                anyhow::ensure!(
                    (current.ctime(), current.ctime_nsec())
                        == (self.original.ctime(), self.original.ctime_nsec()),
                    "original Root checkpoint inode mutation observed"
                );
            }
            Ok(())
        };
        require_metadata(&self.file.metadata()?)?;
        let mut again = vec![0_u8; self.bytes.len()];
        self.file.read_exact_at(&mut again, 0)?;
        anyhow::ensure!(
            again == self.bytes,
            "original Root checkpoint bytes changed"
        );
        let current = self.file.metadata()?;
        require_metadata(&current)?;
        Ok(current)
    }
}

fn require_private_record(metadata: &std::fs::Metadata) -> anyhow::Result<()> {
    anyhow::ensure!(
        metadata.is_file()
            && metadata.uid() == 0
            && metadata.mode() == 0o100600
            // The original descriptor may have been unlinked by Root's
            // immutable rename. The caller must observe the replacement.
            && metadata.nlink() <= 1
            && (1..=RECORD_BYTES as u64).contains(&metadata.len()),
        "existing bounded private Root checkpoint record required"
    );
    Ok(())
}
