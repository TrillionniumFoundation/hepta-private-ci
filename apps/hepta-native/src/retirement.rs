//! Append-only retirement identities under the journal's existing single owner.
//!
//! Immutable segments remain the authoritative audit chain. A content-addressed,
//! checkpoint-bound bucket index makes ordinary startup and exact lookup bounded:
//! startup loads only the head and a small manifest, while a lookup reads one
//! bounded bucket. A missing or corrupt index never makes an identity replayable;
//! legacy v1/v2 heads are rebuilt under the same owner before being promoted to v3.
use std::cell::RefCell;
use std::collections::BTreeMap;
use std::collections::HashMap;
use std::collections::HashSet;
use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

use crate::error::ShellError;
use crate::journal::OperationPhase;
use crate::journal::OperationRecord;
use crate::journal::retirement_digest;
use crate::model::sha256_hex;
use crate::model::validate_digest;
use crate::private_state::PrivateStateRoot;

#[path = "retirement_membership.rs"]
mod membership;
pub(crate) use membership::RetirementMembership;

const HEAD_SCHEMA: &str = "hepta.native-retirement.v3";
const SEGMENT_SCHEMA: &str = "hepta.native-retirement.v2";
const LEGACY_SCHEMA: &str = "hepta.native-retirement.v1";
const INDEX_SCHEMA: &str = "hepta.native-retirement-index.v1";
const BUCKET_SCHEMA: &str = "hepta.native-retirement-index-bucket.v1";
const SEGMENT_ENTRIES: usize = 1024;
const SEGMENT_BYTES: u64 = 512 * 1024;
const RECORD_BYTES: u64 = 32 * 1024;
const INDEX_MANIFEST_BYTES: u64 = 256 * 1024;
const INDEX_BUCKET_BYTES: u64 = 8 * 1024 * 1024;
const INDEX_PREFIX_HEX: usize = 2;
const MAX_INDEX_BUCKETS: usize = 1 << (INDEX_PREFIX_HEX * 4);
const MAX_INDEX_BUCKET_ENTRIES: usize = 65_536;
const MAX_INDEX_CACHE_ENTRIES: usize = 65_536;
const MAX_LEGACY_REBUILD_SEGMENTS: usize = 65_536;
const MAX_HEAD_AHEAD_SEGMENTS: usize = 16;

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Checkpoint {
    pub(crate) head: Option<String>,
    pub(crate) count: usize,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Head {
    schema: String,
    checkpoint: Checkpoint,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    index_manifest: Option<String>,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Segment {
    schema: String,
    previous: Checkpoint,
    digests: Vec<String>,
    #[serde(default)]
    record_digests: BTreeMap<String, String>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct IndexManifest {
    schema: String,
    checkpoint: Checkpoint,
    segment_count: usize,
    buckets: BTreeMap<String, String>,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct IndexBucket {
    schema: String,
    prefix: String,
    entries: BTreeMap<String, Option<String>>,
}

#[derive(Debug, Default)]
struct BucketCache {
    buckets: HashMap<String, BTreeMap<String, Option<String>>>,
    entries: usize,
}

#[derive(Debug)]
pub(crate) struct RetirementStore {
    root: PrivateStateRoot,
    checkpoint: Checkpoint,
    segment_count: usize,
    buckets: BTreeMap<String, String>,
    cache: RefCell<BucketCache>,
}

pub(crate) fn directory(journal: &Path) -> PathBuf {
    let mut name = journal.as_os_str().to_os_string();
    name.push(".retirement");
    PathBuf::from(name)
}

impl RetirementStore {
    pub(crate) fn open(
        journal: &Path,
        expected: Option<&Checkpoint>,
    ) -> Result<Option<Self>, ShellError> {
        let path = directory(journal);
        if std::fs::symlink_metadata(&path)
            .is_err_and(|error| error.kind() == std::io::ErrorKind::NotFound)
        {
            if expected.is_some() {
                return Err(ShellError::State(
                    "referenced retirement store is missing".to_owned(),
                ));
            }
            return Ok(None);
        }
        let root = PrivateStateRoot::open_existing(path)?;
        let head: Head = crate::file_input::read_json_file(&root.path().join("head.json"), 8192)?;
        match head.schema.as_str() {
            HEAD_SCHEMA => Self::open_indexed(root, head, expected).map(Some),
            SEGMENT_SCHEMA | LEGACY_SCHEMA => Self::migrate_legacy(root, head, expected).map(Some),
            _ => Err(ShellError::State("unsupported retirement head".to_owned())),
        }
    }

    pub(crate) fn create(journal: &Path) -> Result<Self, ShellError> {
        if let Some(store) = Self::open(journal, None)? {
            return Ok(store);
        }
        let root = PrivateStateRoot::open(directory(journal))?;
        let mut store = Self {
            root,
            checkpoint: Checkpoint::default(),
            segment_count: 0,
            buckets: BTreeMap::new(),
            cache: RefCell::new(BucketCache::default()),
        };
        store.publish_indexed_head()?;
        Ok(store)
    }

    fn open_indexed(
        root: PrivateStateRoot,
        head: Head,
        expected: Option<&Checkpoint>,
    ) -> Result<Self, ShellError> {
        let manifest_digest = head.index_manifest.ok_or_else(|| {
            ShellError::State("indexed retirement head lacks its manifest".to_owned())
        })?;
        validate_digest(&manifest_digest, "retirement.index_manifest")?;
        let manifest = read_manifest(&root, &manifest_digest)?;
        if manifest.checkpoint != head.checkpoint {
            return Err(ShellError::State(
                "retirement index checkpoint does not match the published head".to_owned(),
            ));
        }
        validate_manifest(&manifest)?;
        if let Some(head_digest) = head.checkpoint.head.as_ref() {
            let _ = read_segment(&root, head_digest, Some(head.checkpoint.count))?;
        } else if head.checkpoint.count != 0 || manifest.segment_count != 0 {
            return Err(ShellError::State(
                "empty retirement head has non-empty counters".to_owned(),
            ));
        }
        if let Some(expected) = expected
            && !checkpoint_visible(&root, &head.checkpoint, expected)?
        {
            return Err(ShellError::State(
                "retirement head regressed or belongs to another journal".to_owned(),
            ));
        }
        Ok(Self {
            root,
            checkpoint: head.checkpoint,
            segment_count: manifest.segment_count,
            buckets: manifest.buckets,
            cache: RefCell::new(BucketCache::default()),
        })
    }

    fn migrate_legacy(
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

        let mut store = Self {
            root,
            checkpoint: head.checkpoint,
            segment_count: segment_digests.len(),
            buckets: BTreeMap::new(),
            cache: RefCell::new(BucketCache::default()),
        };
        for digest in segment_digests.iter().rev() {
            let segment = read_segment(&store.root, digest, None)?;
            store.merge_segment_into_index(&segment)?;
        }
        store.publish_indexed_head()?;
        Ok(store)
    }

    fn publish_indexed_head(&mut self) -> Result<(), ShellError> {
        self.root.verify()?;
        let manifest = IndexManifest {
            schema: INDEX_SCHEMA.to_owned(),
            checkpoint: self.checkpoint.clone(),
            segment_count: self.segment_count,
            buckets: self.buckets.clone(),
        };
        validate_manifest(&manifest)?;
        let manifest_bytes = serde_json::to_vec(&manifest)?;
        if manifest_bytes.len() as u64 > INDEX_MANIFEST_BYTES {
            return Err(ShellError::State(
                "retirement index manifest exceeds its byte budget".to_owned(),
            ));
        }
        let manifest_digest =
            write_content_addressed(&self.root, "index", &manifest_bytes, INDEX_MANIFEST_BYTES)?;
        crate::journal_storage::write_private(
            &self.root,
            &self.root.path().join("head.json"),
            &serde_json::to_vec(&Head {
                schema: HEAD_SCHEMA.to_owned(),
                checkpoint: self.checkpoint.clone(),
                index_manifest: Some(manifest_digest),
            })?,
        )
    }

    #[cfg(test)]
    pub(crate) fn append(&mut self, identities: &[String]) -> Result<(), ShellError> {
        self.append_records(identities, &[])
    }

    /// Validate the complete batch before writing records. An identity-only
    /// legacy tombstone cannot acquire a receipt absent from its committed chain.
    pub(crate) fn append_records(
        &mut self,
        identities: &[String],
        records: &[OperationRecord],
    ) -> Result<(), ShellError> {
        self.root.verify()?;
        for identity in identities {
            validate_digest(identity, "retirement.identity")?;
        }
        let mut record_digests = BTreeMap::new();
        let identity_set: HashSet<_> = identities.iter().collect();
        for record in records {
            record.validate()?;
            if !matches!(
                record.phase,
                OperationPhase::Terminal | OperationPhase::ObservationClosed
            ) {
                return Err(ShellError::State(
                    "cannot archive an open observation".to_owned(),
                ));
            }
            let identity = retirement_digest(&record.endpoint_id, &record.key)?;
            if !identity_set.contains(&identity) {
                return Err(ShellError::State(
                    "archive is not in the retirement transaction".to_owned(),
                ));
            }
            let bytes = serde_json::to_vec(record)?;
            if bytes.len() as u64 > RECORD_BYTES {
                return Err(ShellError::State(
                    "archived record exceeds byte limit".to_owned(),
                ));
            }
            let digest = sha256_hex(&bytes);
            match self.lookup_entry(&identity)? {
                Some(None) => {
                    return Err(ShellError::State(
                        "legacy retirement identity cannot acquire an uncommitted receipt"
                            .to_owned(),
                    ));
                }
                Some(Some(previous)) if previous != digest => {
                    return Err(ShellError::State(
                        "retired observation is immutable".to_owned(),
                    ));
                }
                _ => {}
            }
            if record_digests.insert(identity, digest).is_some() {
                return Err(ShellError::State("duplicate archived operation".to_owned()));
            }
        }

        for record in records {
            let bytes = serde_json::to_vec(record)?;
            let digest = sha256_hex(&bytes);
            let path = self.root.path().join(format!("record-{digest}.json"));
            match std::fs::symlink_metadata(&path) {
                Ok(_) => {
                    if crate::file_input::read_bytes(&path, RECORD_BYTES)? != bytes {
                        return Err(ShellError::State(
                            "archived record content changed".to_owned(),
                        ));
                    }
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    crate::journal_storage::write_private(&self.root, &path, &bytes)?;
                }
                Err(error) => return Err(error.into()),
            }
        }

        let mut added = Vec::new();
        for identity in identities {
            if self.lookup_entry(identity)?.is_none() {
                added.push(identity.clone());
            }
        }
        added.sort_unstable();
        added.dedup();
        if added.is_empty() {
            return Ok(());
        }

        let mut checkpoint = self.checkpoint.clone();
        let mut new_segments = 0usize;
        for chunk in added.chunks(SEGMENT_ENTRIES) {
            let segment = Segment {
                schema: SEGMENT_SCHEMA.to_owned(),
                previous: checkpoint.clone(),
                digests: chunk.to_vec(),
                record_digests: chunk
                    .iter()
                    .filter_map(|identity| {
                        record_digests
                            .get(identity)
                            .map(|digest| (identity.clone(), digest.clone()))
                    })
                    .collect(),
            };
            validate_segment(&segment, None)?;
            let bytes = serde_json::to_vec(&segment)?;
            if bytes.len() as u64 > SEGMENT_BYTES {
                return Err(ShellError::State(
                    "retirement segment exceeds byte limit".to_owned(),
                ));
            }
            let digest = write_content_addressed(&self.root, "segment", &bytes, SEGMENT_BYTES)?;
            checkpoint = Checkpoint {
                head: Some(digest),
                count: checkpoint
                    .count
                    .checked_add(chunk.len())
                    .ok_or_else(|| ShellError::State("retirement count overflow".to_owned()))?,
            };
            new_segments = new_segments
                .checked_add(1)
                .ok_or_else(|| ShellError::State("retirement segment count overflow".to_owned()))?;
        }

        let mut grouped: BTreeMap<String, Vec<(String, Option<String>)>> = BTreeMap::new();
        for identity in &added {
            grouped
                .entry(index_prefix(identity)?)
                .or_default()
                .push((identity.clone(), record_digests.get(identity).cloned()));
        }
        let mut next_buckets = self.buckets.clone();
        for (prefix, entries) in grouped {
            let mut bucket = load_bucket_from_manifest(&self.root, &next_buckets, &prefix)?;
            for (identity, record_digest) in entries {
                if bucket.entries.insert(identity, record_digest).is_some() {
                    return Err(ShellError::State(
                        "retirement index attempted to replace an existing identity".to_owned(),
                    ));
                }
            }
            validate_bucket(&bucket)?;
            let bytes = serde_json::to_vec(&bucket)?;
            if bytes.len() as u64 > INDEX_BUCKET_BYTES {
                return Err(ShellError::State(
                    "retirement index bucket exceeds its byte budget".to_owned(),
                ));
            }
            let digest = write_content_addressed(&self.root, "bucket", &bytes, INDEX_BUCKET_BYTES)?;
            next_buckets.insert(prefix, digest);
        }

        let previous_checkpoint = self.checkpoint.clone();
        let previous_segments = self.segment_count;
        let previous_buckets = std::mem::replace(&mut self.buckets, next_buckets);
        self.checkpoint = checkpoint;
        self.segment_count = self
            .segment_count
            .checked_add(new_segments)
            .ok_or_else(|| ShellError::State("retirement segment count overflow".to_owned()))?;
        if let Err(error) = self.publish_indexed_head() {
            self.checkpoint = previous_checkpoint;
            self.segment_count = previous_segments;
            self.buckets = previous_buckets;
            return Err(error);
        }
        self.cache.borrow_mut().buckets.clear();
        self.cache.borrow_mut().entries = 0;
        Ok(())
    }

    pub(crate) fn read_record(
        &self,
        identity: &str,
    ) -> Result<Option<OperationRecord>, ShellError> {
        self.root.verify()?;
        let Some(Some(digest)) = self.lookup_entry(identity)? else {
            return Ok(None);
        };
        self.read_archived_record(identity, &digest).map(Some)
    }

    fn read_archived_record(
        &self,
        identity: &str,
        digest: &str,
    ) -> Result<OperationRecord, ShellError> {
        self.root.verify()?;
        let bytes = crate::file_input::read_bytes(
            &self.root.path().join(format!("record-{digest}.json")),
            RECORD_BYTES,
        )?;
        if sha256_hex(&bytes) != digest {
            return Err(ShellError::State(
                "archived record digest mismatch".to_owned(),
            ));
        }
        let record: OperationRecord = serde_json::from_slice(&bytes)?;
        record.validate()?;
        if retirement_digest(&record.endpoint_id, &record.key)? != identity
            || !matches!(
                record.phase,
                OperationPhase::Terminal | OperationPhase::ObservationClosed
            )
        {
            return Err(ShellError::State(
                "archived record identity or phase mismatch".to_owned(),
            ));
        }
        Ok(record)
    }

    fn lookup_entry(&self, identity: &str) -> Result<Option<Option<String>>, ShellError> {
        self.root.verify()?;
        validate_digest(identity, "retirement.identity")?;
        let prefix = index_prefix(identity)?;
        if let Some(entries) = self.cache.borrow().buckets.get(&prefix) {
            return Ok(entries.get(identity).cloned());
        }
        let bucket = load_bucket_from_manifest(&self.root, &self.buckets, &prefix)?;
        let result = bucket.entries.get(identity).cloned();
        let bucket_entries = bucket.entries.len();
        if bucket_entries <= MAX_INDEX_CACHE_ENTRIES {
            let mut cache = self.cache.borrow_mut();
            if cache.entries.saturating_add(bucket_entries) > MAX_INDEX_CACHE_ENTRIES {
                cache.buckets.clear();
                cache.entries = 0;
            }
            cache.entries = cache.entries.saturating_add(bucket_entries);
            cache.buckets.insert(prefix, bucket.entries);
        }
        Ok(result)
    }

    pub(crate) fn contains(&self, digest: &str) -> bool {
        // Index uncertainty is fail-closed: it may reject an operation, never
        // make a retired identity executable.
        self.lookup_entry(digest)
            .map(|entry| entry.is_some())
            .unwrap_or(true)
    }

    pub(crate) fn len(&self) -> usize {
        self.checkpoint.count
    }

    pub(crate) fn segments(&self) -> usize {
        self.segment_count
    }

    pub(crate) fn checkpoint(&self) -> Checkpoint {
        self.checkpoint.clone()
    }

    fn merge_segment_into_index(&mut self, segment: &Segment) -> Result<(), ShellError> {
        let mut grouped: BTreeMap<String, Vec<(String, Option<String>)>> = BTreeMap::new();
        for identity in &segment.digests {
            grouped.entry(index_prefix(identity)?).or_default().push((
                identity.clone(),
                segment.record_digests.get(identity).cloned(),
            ));
        }
        for (prefix, entries) in grouped {
            let mut bucket = load_bucket_from_manifest(&self.root, &self.buckets, &prefix)?;
            for (identity, record_digest) in entries {
                if bucket.entries.insert(identity, record_digest).is_some() {
                    return Err(ShellError::State(
                        "duplicate retirement identity".to_owned(),
                    ));
                }
            }
            validate_bucket(&bucket)?;
            let bytes = serde_json::to_vec(&bucket)?;
            let digest = write_content_addressed(&self.root, "bucket", &bytes, INDEX_BUCKET_BYTES)?;
            self.buckets.insert(prefix, digest);
        }
        Ok(())
    }
}

fn validate_manifest(manifest: &IndexManifest) -> Result<(), ShellError> {
    if manifest.schema != INDEX_SCHEMA || manifest.buckets.len() > MAX_INDEX_BUCKETS {
        return Err(ShellError::State(
            "invalid retirement index manifest".to_owned(),
        ));
    }
    for (prefix, digest) in &manifest.buckets {
        validate_prefix(prefix)?;
        validate_digest(digest, "retirement.index_bucket")?;
    }
    Ok(())
}

fn read_manifest(root: &PrivateStateRoot, digest: &str) -> Result<IndexManifest, ShellError> {
    let bytes = crate::file_input::read_bytes(
        &root.path().join(format!("index-{digest}.json")),
        INDEX_MANIFEST_BYTES,
    )?;
    if sha256_hex(&bytes) != digest {
        return Err(ShellError::State(
            "retirement index manifest digest mismatch".to_owned(),
        ));
    }
    let manifest: IndexManifest = serde_json::from_slice(&bytes)?;
    validate_manifest(&manifest)?;
    Ok(manifest)
}

fn load_bucket_from_manifest(
    root: &PrivateStateRoot,
    manifest: &BTreeMap<String, String>,
    prefix: &str,
) -> Result<IndexBucket, ShellError> {
    validate_prefix(prefix)?;
    let Some(digest) = manifest.get(prefix) else {
        return Ok(IndexBucket {
            schema: BUCKET_SCHEMA.to_owned(),
            prefix: prefix.to_owned(),
            entries: BTreeMap::new(),
        });
    };
    let bytes = crate::file_input::read_bytes(
        &root.path().join(format!("bucket-{digest}.json")),
        INDEX_BUCKET_BYTES,
    )?;
    if sha256_hex(&bytes) != *digest {
        return Err(ShellError::State(
            "retirement index bucket digest mismatch".to_owned(),
        ));
    }
    let bucket: IndexBucket = serde_json::from_slice(&bytes)?;
    validate_bucket(&bucket)?;
    if bucket.prefix != prefix {
        return Err(ShellError::State(
            "retirement index bucket prefix mismatch".to_owned(),
        ));
    }
    Ok(bucket)
}

fn validate_bucket(bucket: &IndexBucket) -> Result<(), ShellError> {
    if bucket.schema != BUCKET_SCHEMA || bucket.entries.len() > MAX_INDEX_BUCKET_ENTRIES {
        return Err(ShellError::State(
            "invalid or oversized retirement index bucket".to_owned(),
        ));
    }
    validate_prefix(&bucket.prefix)?;
    for (identity, record_digest) in &bucket.entries {
        validate_digest(identity, "retirement.identity")?;
        if index_prefix(identity)? != bucket.prefix {
            return Err(ShellError::State(
                "retirement index entry is in the wrong bucket".to_owned(),
            ));
        }
        if let Some(digest) = record_digest {
            validate_digest(digest, "retirement.record")?;
        }
    }
    Ok(())
}

fn read_segment(
    root: &PrivateStateRoot,
    digest: &str,
    expected_count: Option<usize>,
) -> Result<Segment, ShellError> {
    validate_digest(digest, "retirement.segment")?;
    let bytes =
        crate::file_input::read_bytes(&root.path().join(format!("{digest}.json")), SEGMENT_BYTES)?;
    if sha256_hex(&bytes) != digest {
        return Err(ShellError::State(
            "retirement segment digest mismatch".to_owned(),
        ));
    }
    let segment: Segment = serde_json::from_slice(&bytes)?;
    validate_segment(&segment, expected_count)?;
    Ok(segment)
}

fn validate_segment(segment: &Segment, expected_count: Option<usize>) -> Result<(), ShellError> {
    if !matches!(segment.schema.as_str(), SEGMENT_SCHEMA | LEGACY_SCHEMA)
        || (segment.schema == LEGACY_SCHEMA && !segment.record_digests.is_empty())
        || segment.digests.is_empty()
        || segment.digests.len() > SEGMENT_ENTRIES
        || segment.digests.windows(2).any(|pair| pair[0] >= pair[1])
        || expected_count.is_some_and(|count| {
            segment.previous.count.checked_add(segment.digests.len()) != Some(count)
        })
    {
        return Err(ShellError::State(
            "invalid retirement segment sequence".to_owned(),
        ));
    }
    for identity in &segment.digests {
        validate_digest(identity, "retirement.identity")?;
    }
    for (identity, record_digest) in &segment.record_digests {
        validate_digest(record_digest, "retirement.record")?;
        if segment.digests.binary_search(identity).is_err() {
            return Err(ShellError::State(
                "retirement record has no committed identity".to_owned(),
            ));
        }
    }
    Ok(())
}

fn checkpoint_visible(
    root: &PrivateStateRoot,
    current: &Checkpoint,
    expected: &Checkpoint,
) -> Result<bool, ShellError> {
    if current == expected || expected == &Checkpoint::default() {
        return Ok(true);
    }
    if expected.count >= current.count {
        return Ok(false);
    }
    let mut cursor = current.clone();
    for _ in 0..MAX_HEAD_AHEAD_SEGMENTS {
        if &cursor == expected {
            return Ok(true);
        }
        let Some(digest) = cursor.head.as_ref() else {
            return Ok(false);
        };
        let segment = read_segment(root, digest, Some(cursor.count))?;
        cursor = segment.previous;
        if cursor.count < expected.count {
            return Ok(false);
        }
    }
    Ok(&cursor == expected)
}

fn index_prefix(identity: &str) -> Result<String, ShellError> {
    validate_digest(identity, "retirement.identity")?;
    Ok(identity[..INDEX_PREFIX_HEX].to_owned())
}

fn validate_prefix(prefix: &str) -> Result<(), ShellError> {
    if prefix.len() != INDEX_PREFIX_HEX
        || !prefix
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(ShellError::State(
            "invalid retirement index prefix".to_owned(),
        ));
    }
    Ok(())
}

fn write_content_addressed(
    root: &PrivateStateRoot,
    kind: &str,
    bytes: &[u8],
    maximum: u64,
) -> Result<String, ShellError> {
    if bytes.len() as u64 > maximum {
        return Err(ShellError::State(format!(
            "retirement {kind} exceeds its byte budget"
        )));
    }
    let digest = sha256_hex(bytes);
    // Segments keep their historical bare digest name. Publish directly at
    // that name so there is no second path-based rename after the rooted write.
    let name = if kind == "segment" {
        format!("{digest}.json")
    } else {
        format!("{kind}-{digest}.json")
    };
    let path = root.path().join(name);
    match std::fs::symlink_metadata(&path) {
        Ok(_) => {
            if crate::file_input::read_bytes(&path, maximum)? != bytes {
                return Err(ShellError::State(format!(
                    "existing retirement {kind} content changed"
                )));
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            crate::journal_storage::write_private(root, &path, bytes)?;
        }
        Err(error) => return Err(error.into()),
    }
    Ok(digest)
}

#[cfg(test)]
#[path = "retirement_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "retirement_claim_tests.rs"]
mod claim_tests;
