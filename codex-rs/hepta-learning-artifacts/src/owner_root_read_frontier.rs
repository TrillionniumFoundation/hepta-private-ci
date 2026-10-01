//! Root publishes the read frontier only after the actual owner's durable ACK.
//! This contains public state, never a writer lease or any signing material.
use super::*;
use std::io::Read;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::MetadataExt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

const MAGIC: &str = "HEPTA-ARTIFACT-ROOT-READ-FRONTIER-V1";
const NAME: &str = "READ-CURRENT";
const MAXIMUM: u64 = 16 * 1024;
static NEXT: AtomicU64 = AtomicU64::new(1);

pub(super) struct RootReadFrontier {
    pub(super) trust: Digest32,
    pub(super) withdrawal_scope: Digest32,
    pub(super) withdrawal_head: Digest32,
    pub(super) current: SignedCurrentArtifactHeadV1,
}
fn encode(root: &Path, frontier: &RootReadFrontier) -> Vec<u8> {
    let mut bytes = format!(
        "{MAGIC}\n{}\n{}\n{}\n{}\n",
        Digest32::of_bytes(root.as_os_str().as_bytes()),
        frontier.trust,
        frontier.withdrawal_scope,
        frontier.withdrawal_head
    )
    .into_bytes();
    bytes.extend_from_slice(&encode_signed_head(&frontier.current));
    bytes
}
fn decode(root: &Path, bytes: &[u8]) -> Result<RootReadFrontier, ArtifactOwnerHostError> {
    let text = std::str::from_utf8(bytes).map_err(|_| ArtifactOwnerHostError::PathBoundary)?;
    let fields = text.splitn(6, '\n').collect::<Vec<_>>();
    if fields.len() != 6
        || fields[0] != MAGIC
        || parse_digest(fields[1])? != Digest32::of_bytes(root.as_os_str().as_bytes())
    {
        return Err(ArtifactOwnerHostError::PathBoundary);
    }
    let frontier = RootReadFrontier {
        trust: parse_digest(fields[2])?,
        withdrawal_scope: parse_digest(fields[3])?,
        withdrawal_head: parse_digest(fields[4])?,
        current: decode_signed_head(fields[5].as_bytes())?,
    };
    if frontier.trust.is_zero()
        || frontier.withdrawal_scope.is_zero()
        || encode(root, &frontier) != bytes
    {
        return Err(ArtifactOwnerHostError::CurrentHeadContext);
    }
    Ok(frontier)
}
pub(super) fn protected_root(root: &Path) -> Result<(), ArtifactOwnerHostError> {
    if !root.is_absolute() || fs::canonicalize(root)? != root {
        return Err(ArtifactOwnerHostError::PathBoundary);
    }
    for ancestor in root.ancestors() {
        let metadata = fs::symlink_metadata(ancestor)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err(ArtifactOwnerHostError::PathBoundary);
        }
    }
    Ok(())
}
pub(super) fn read_frontier(
    root: &Path,
) -> Result<(RootReadFrontier, Vec<u8>), ArtifactOwnerHostError> {
    protected_root(root)?;
    let path = root.join(NAME);
    let before = fs::symlink_metadata(&path)?;
    if !before.is_file()
        || before.uid() != 0
        || before.nlink() != 1
        || before.mode() & 0o022 != 0
        || before.len() > MAXIMUM
    {
        return Err(ArtifactOwnerHostError::PathBoundary);
    }
    let file = File::open(path)?;
    let after = file.metadata()?;
    if before.dev() != after.dev() || before.ino() != after.ino() {
        return Err(ArtifactOwnerHostError::PathBoundary);
    }
    let mut bytes = Vec::new();
    file.take(MAXIMUM + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != before.len() {
        return Err(ArtifactOwnerHostError::PathBoundary);
    }
    Ok((decode(root, &bytes)?, bytes))
}
/// The reader must reject symlinks, writable entries and foreign ownership even
/// when their bytes happen to match a copied signed snapshot.
pub(super) fn protected_inventory(root: &Path) -> Result<(), ArtifactOwnerHostError> {
    protected_root(root)?;
    for name in [
        "writer",
        "transactions",
        "payloads",
        "registries",
        "witnesses",
        "heads",
        "admissions",
    ] {
        let directory = root.join(name);
        let metadata = fs::symlink_metadata(&directory)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err(ArtifactOwnerHostError::PathBoundary);
        }
        for (index, entry) in fs::read_dir(directory)?.enumerate() {
            if index >= MAX_HEAD_RECORDS * 6 {
                return Err(ArtifactOwnerHostError::Capacity);
            }
            let metadata = fs::symlink_metadata(entry?.path())?;
            if !metadata.is_file()
                || metadata.uid() != 0
                || metadata.mode() & 0o022 != 0
                || !(1..=2).contains(&metadata.nlink())
            {
                return Err(ArtifactOwnerHostError::PathBoundary);
            }
        }
    }
    Ok(())
}
impl LearningArtifactOwnerHost {
    /// Publish the exact public read frontier from this Root-owned writer after
    /// its real fsync/CURRENT/ACK chain. A caller DTO cannot create this record.
    pub fn publish_root_read_frontier(
        &self,
        withdrawals: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<(), ArtifactOwnerHostError> {
        let status = fs::read_to_string("/proc/self/status")?;
        let uid = status
            .lines()
            .find_map(|line| line.strip_prefix("Uid:"))
            .ok_or(ArtifactOwnerHostError::PathBoundary)?;
        if uid.split_whitespace().count() != 4 || uid.split_whitespace().any(|value| value != "0") {
            return Err(ArtifactOwnerHostError::PathBoundary);
        }
        self.require_current_writer(now)?;
        protected_inventory(&self.root)?;
        if withdrawals.scope_digest() != Some(self.verifier.trust.withdrawal_scope_digest) {
            return Err(ArtifactOwnerHostError::ProvenanceMismatch);
        }
        let current = self
            .discover_current_head(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        let context = self.read_context();
        let acknowledged = records::all_checkpoints(&context)?
            .into_iter()
            .any(|checkpoint| {
                checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged
                    && checkpoint.registry_receipt.is_some_and(|receipt| {
                        receipt.head_digest == current.signed.witness.head_digest
                            && receipt.binding == current.signed.binding
                    })
                    && checkpoint.witness_receipt.is_some_and(|receipt| {
                        receipt.witness_digest == current.witness_digest
                            && receipt.binding == current.signed.binding
                    })
            });
        if !acknowledged {
            return Err(ArtifactOwnerHostError::CheckpointMissing);
        }
        context.current_registry_view(now)?;
        let frontier = RootReadFrontier {
            trust: self.trust_digest(),
            withdrawal_scope: self.verifier.trust.withdrawal_scope_digest,
            withdrawal_head: withdrawals.head_digest(),
            current: current.signed,
        };
        let bytes = encode(&self.root, &frontier);
        let path = self.root.join(NAME);
        if path.exists() && read_frontier(&self.root)?.1 == bytes {
            return Ok(());
        }
        let temporary = self.root.join(format!(
            ".READ-CURRENT-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o644)
            .open(&temporary)?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
        fs::rename(&temporary, &path).map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
        File::open(&self.root)?
            .sync_all()
            .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
        Ok(())
    }
}
