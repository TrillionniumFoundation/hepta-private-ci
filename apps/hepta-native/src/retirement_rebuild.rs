//! Rebuild an index from the complete authority chain using bounded private
//! spools. A spool is scratch data, authenticated against its in-memory digest;
//! it never becomes a retirement head or an executable receipt.

use std::collections::BTreeMap;
use std::collections::HashSet;
use std::collections::btree_map::Entry;
use std::fs::File;
use std::io::BufWriter;
use std::io::Read as _;
use std::io::Seek as _;
use std::io::SeekFrom;
use std::io::Write as _;
use std::path::PathBuf;

use sha2::Digest as _;
use sha2::Sha256;

use super::BUCKET_SCHEMA;
use super::Checkpoint;
use super::Head;
use super::INDEX_BUCKET_BYTES;
use super::IndexBucket;
use super::MAX_INDEX_BUCKET_ENTRIES;
use super::MAX_LEGACY_REBUILD_SEGMENTS;
use super::RetirementStore;
use super::index_prefix;
use super::read_archived_record;
use super::read_segment;
use super::validate_bucket;
use super::write_content_addressed;
use crate::error::ShellError;
use crate::journal_storage::FileAccess;
use crate::private_state::PrivateStateRoot;

const SPOOL_ENTRY_BYTES: usize = 128;
const MAX_SPOOL_BYTES: u64 = (MAX_INDEX_BUCKET_ENTRIES * SPOOL_ENTRY_BYTES) as u64;
const MAX_BUCKET_PUBLISHERS: usize = 4;

#[derive(Clone, Copy)]
enum RebuildBoundary {
    SegmentsSpooled,
    BucketPublished,
}

struct Spool {
    root: PrivateStateRoot,
    path: PathBuf,
    writer: Option<BufWriter<File>>,
    owned: bool,
    checksum: Sha256,
    entries: usize,
}

impl Drop for Spool {
    fn drop(&mut self) {
        drop(self.writer.take());
        if self.owned {
            let _ = crate::journal_storage::remove_private_file_in(&self.root, &self.path);
        }
    }
}

impl Spool {
    fn create(root: &PrivateStateRoot, nonce: &str, prefix: &str) -> Result<Self, ShellError> {
        let mut spool = Self {
            root: root.clone(),
            path: root
                .path()
                .join(format!(".retirement-rebuild-{nonce}-{prefix}.tmp")),
            writer: None,
            owned: false,
            checksum: Sha256::new(),
            entries: 0,
        };
        let file = crate::journal_storage::open_private_file_in(
            root,
            &spool.path,
            FileAccess::CreateNew,
            /*preexisting*/ false,
        )?;
        spool.owned = true;
        spool.writer = Some(BufWriter::new(file));
        Ok(spool)
    }

    fn append(&mut self, identity: &str, record_digest: Option<&String>) -> Result<(), ShellError> {
        if self.entries >= MAX_INDEX_BUCKET_ENTRIES {
            return Err(ShellError::State(
                "retirement rebuild bucket exceeds its entry limit".to_owned(),
            ));
        }
        let mut bytes = [0u8; SPOOL_ENTRY_BYTES];
        bytes[..64].copy_from_slice(identity.as_bytes());
        if let Some(digest) = record_digest {
            bytes[64..].copy_from_slice(digest.as_bytes());
        }
        self.writer
            .as_mut()
            .ok_or_else(|| ShellError::State("retirement spool is closed".to_owned()))?
            .write_all(&bytes)?;
        self.checksum.update(bytes);
        self.entries += 1;
        Ok(())
    }

    fn flush(&mut self) -> Result<(), ShellError> {
        self.writer
            .as_mut()
            .ok_or_else(|| ShellError::State("retirement spool is closed".to_owned()))?
            .flush()
            .map_err(ShellError::from)
    }

    fn bucket(&mut self, prefix: &str) -> Result<IndexBucket, ShellError> {
        let mut file = self
            .writer
            .take()
            .ok_or_else(|| ShellError::State("retirement spool is closed".to_owned()))?
            .into_inner()
            .map_err(|error| error.into_error())?;
        let expected_bytes = (self.entries * SPOOL_ENTRY_BYTES) as u64;
        if file.metadata()?.len() != expected_bytes || expected_bytes > MAX_SPOOL_BYTES {
            return Err(ShellError::State(
                "retirement rebuild spool has invalid length".to_owned(),
            ));
        }
        file.seek(SeekFrom::Start(0))?;
        let mut bytes = Vec::with_capacity(expected_bytes as usize);
        file.take(MAX_SPOOL_BYTES + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 != expected_bytes
            || Sha256::digest(&bytes) != self.checksum.clone().finalize()
        {
            return Err(ShellError::State(
                "retirement rebuild spool content changed".to_owned(),
            ));
        }
        let mut entries = BTreeMap::new();
        for chunk in bytes.chunks_exact(SPOOL_ENTRY_BYTES) {
            let identity = std::str::from_utf8(&chunk[..64])
                .map_err(|_| {
                    ShellError::State("retirement spool identity is not UTF-8".to_owned())
                })?
                .to_owned();
            let record_digest = if chunk[64..].iter().all(|byte| *byte == 0) {
                None
            } else {
                Some(
                    std::str::from_utf8(&chunk[64..])
                        .map_err(|_| {
                            ShellError::State(
                                "retirement spool record digest is not UTF-8".to_owned(),
                            )
                        })?
                        .to_owned(),
                )
            };
            if entries.insert(identity, record_digest).is_some() {
                return Err(ShellError::State(
                    "duplicate retirement identity".to_owned(),
                ));
            }
        }
        let bucket = IndexBucket {
            schema: BUCKET_SCHEMA.to_owned(),
            prefix: prefix.to_owned(),
            entries,
        };
        validate_bucket(&bucket)?;
        Ok(bucket)
    }
}

fn rebuild_buckets(
    root: &PrivateStateRoot,
    segment_digests: &[String],
    mut observe: impl FnMut(RebuildBoundary) -> Result<(), ShellError>,
) -> Result<BTreeMap<String, String>, ShellError> {
    root.verify()?;
    // The same authority chain always owns the same scratch namespace. A
    // crashed attempt therefore blocks at create_new instead of accumulating
    // a fresh set of unproven orphan files on every restart.
    let nonce = spool_nonce(segment_digests);
    let mut spools = BTreeMap::<String, Spool>::new();
    for digest in segment_digests.iter().rev() {
        root.verify()?;
        let segment = read_segment(root, digest, None)?;
        for identity in &segment.digests {
            if let Some(record_digest) = segment.record_digests.get(identity) {
                let _ = read_archived_record(root, identity, record_digest)?;
            }
            let prefix = index_prefix(identity)?;
            let spool = match spools.entry(prefix) {
                Entry::Occupied(entry) => entry.into_mut(),
                Entry::Vacant(entry) => {
                    let spool = Spool::create(root, &nonce, entry.key())?;
                    entry.insert(spool)
                }
            };
            spool.append(identity, segment.record_digests.get(identity))?;
        }
    }
    for spool in spools.values_mut() {
        spool.flush()?;
    }
    observe(RebuildBoundary::SegmentsSpooled)?;
    let mut buckets = BTreeMap::new();
    let mut spools = spools.into_iter();
    loop {
        let mut batch = Vec::with_capacity(MAX_BUCKET_PUBLISHERS);
        // Validate one spool at a time and retain at most four serialized
        // buckets. Every publisher still performs the original durable write.
        for (prefix, mut spool) in spools.by_ref().take(MAX_BUCKET_PUBLISHERS) {
            let bucket = spool.bucket(&prefix)?;
            batch.push((prefix, serde_json::to_vec(&bucket)?));
        }
        if batch.is_empty() {
            break;
        }
        for (prefix, digest) in publish_bucket_batch(root, batch)? {
            buckets.insert(prefix, digest);
            observe(RebuildBoundary::BucketPublished)?;
        }
    }
    root.verify()?;
    Ok(buckets)
}

fn publish_bucket_batch(
    root: &PrivateStateRoot,
    batch: Vec<(String, Vec<u8>)>,
) -> Result<Vec<(String, String)>, ShellError> {
    std::thread::scope(|scope| {
        let mut workers = Vec::with_capacity(batch.len());
        let mut failure = None;
        for (prefix, bytes) in batch {
            match std::thread::Builder::new()
                .name("hepta-retirement-bucket".to_owned())
                .spawn_scoped(scope, move || {
                    let digest =
                        write_content_addressed(root, "bucket", &bytes, INDEX_BUCKET_BYTES)?;
                    Ok::<_, ShellError>((prefix, digest))
                }) {
                Ok(worker) => workers.push(worker),
                Err(error) => {
                    failure = Some(error.into());
                    break;
                }
            }
        }
        let mut published = Vec::with_capacity(workers.len());
        // Join every physical writer, including after a spawn failure, I/O
        // failure or panic. No writer may outlive the failed rebuild attempt.
        for worker in workers {
            match worker.join() {
                Ok(Ok(bucket)) => published.push(bucket),
                Ok(Err(error)) => {
                    failure.get_or_insert(error);
                }
                Err(_) => {
                    failure.get_or_insert_with(|| {
                        ShellError::State("retirement bucket publisher panicked".to_owned())
                    });
                }
            }
        }
        match failure {
            Some(error) => Err(error),
            None => Ok(published),
        }
    })
}

fn spool_nonce(segment_digests: &[String]) -> String {
    let mut identity = Sha256::new();
    identity.update(b"hepta.native-retirement-rebuild-spool.v1");
    for digest in segment_digests {
        identity.update(digest.as_bytes());
    }
    crate::model::sha256_hex(identity.finalize())
}

impl RetirementStore {
    pub(super) fn migrate_legacy(
        root: PrivateStateRoot,
        head: Head,
        expected: Option<&Checkpoint>,
    ) -> Result<Self, ShellError> {
        let mut cursor = head.checkpoint.clone();
        let mut segment_digests = Vec::new();
        let mut seen = HashSet::new();
        let mut expected_seen = expected.is_none_or(|value| value == &Checkpoint::default());
        while let Some(digest) = cursor.head.clone() {
            if segment_digests.len() >= MAX_LEGACY_REBUILD_SEGMENTS {
                return Err(ShellError::State(format!(
                    "retirement index rebuild exceeds {MAX_LEGACY_REBUILD_SEGMENTS} segments"
                )));
            }
            if !seen.insert(digest.clone()) {
                return Err(ShellError::State("retirement segment cycle".to_owned()));
            }
            if expected.is_some_and(|value| value == &cursor) {
                expected_seen = true;
            }
            let segment = read_segment(&root, &digest, Some(cursor.count))?;
            segment_digests.push(digest);
            cursor = segment.previous;
        }
        if cursor.count != 0 {
            return Err(ShellError::State(
                "retirement chain is incomplete".to_owned(),
            ));
        }
        if expected.is_some_and(|value| value == &cursor) {
            expected_seen = true;
        }
        if !expected_seen {
            return Err(ShellError::State(
                "retirement head regressed or belongs to another journal".to_owned(),
            ));
        }
        let buckets = rebuild_buckets(&root, &segment_digests, |_| Ok(()))?;
        let mut store = Self {
            root,
            checkpoint: head.checkpoint,
            segment_count: segment_digests.len(),
            buckets,
            cache: Default::default(),
        };
        store.publish_indexed_head()?;
        Ok(store)
    }
}

#[cfg(test)]
#[path = "retirement_rebuild_tests.rs"]
mod tests;
