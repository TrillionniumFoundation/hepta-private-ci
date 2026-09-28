//! Append-only retirement identities under the journal's existing single owner.
//! Publish immutable segments, then a durable head, then remove active records.
//! A head ahead of the journal is safe: those identities remain non-replayable.
//! This detects partial rollback; it is not an independent anti-rollback authority.
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

const SCHEMA: &str = "hepta.native-retirement.v2";
const LEGACY_SCHEMA: &str = "hepta.native-retirement.v1";
const SEGMENT_ENTRIES: usize = 1024;
const SEGMENT_BYTES: u64 = 512 * 1024;
const RECORD_BYTES: u64 = 32 * 1024;

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
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Segment {
    schema: String,
    previous: Checkpoint,
    digests: Vec<String>,
    #[serde(default)]
    record_digests: BTreeMap<String, String>,
}

#[derive(Debug)]
pub(crate) struct RetirementStore {
    root: PrivateStateRoot,
    checkpoint: Checkpoint,
    identities: HashSet<String>,
    record_digests: HashMap<String, String>,
    checkpoints: HashMap<String, usize>,
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
        if std::fs::symlink_metadata(&path).is_err_and(|e| e.kind() == std::io::ErrorKind::NotFound)
        {
            if expected.is_some() {
                return Err(ShellError::State(
                    "referenced retirement store is missing".to_owned(),
                ));
            }
            return Ok(None);
        }
        let root = PrivateStateRoot::open_existing(path)?;
        let head: Head = crate::file_input::read_json_file(&root.path().join("head.json"), 4096)?;
        if !matches!(head.schema.as_str(), SCHEMA | LEGACY_SCHEMA) {
            return Err(ShellError::State("unsupported retirement head".to_owned()));
        }
        let mut store = Self {
            root,
            checkpoint: head.checkpoint.clone(),
            identities: HashSet::new(),
            record_digests: HashMap::new(),
            checkpoints: HashMap::new(),
        };
        let mut cursor = head.checkpoint;
        while let Some(digest) = cursor.head.as_ref() {
            validate_digest(digest, "retirement.segment")?;
            if store
                .checkpoints
                .insert(digest.clone(), cursor.count)
                .is_some()
            {
                return Err(ShellError::State("retirement segment cycle".to_owned()));
            }
            let bytes = crate::file_input::read_bytes(
                &store.root.path().join(format!("{digest}.json")),
                SEGMENT_BYTES,
            )?;
            if sha256_hex(&bytes) != *digest {
                return Err(ShellError::State(
                    "retirement segment digest mismatch".to_owned(),
                ));
            }
            let segment: Segment = serde_json::from_slice(&bytes)?;
            if !matches!(segment.schema.as_str(), SCHEMA | LEGACY_SCHEMA)
                || (segment.schema == LEGACY_SCHEMA && !segment.record_digests.is_empty())
                || segment.digests.is_empty()
                || segment.digests.len() > SEGMENT_ENTRIES
                || segment.previous.count.checked_add(segment.digests.len()) != Some(cursor.count)
                || segment.digests.windows(2).any(|pair| pair[0] >= pair[1])
            {
                return Err(ShellError::State(
                    "invalid retirement segment sequence".to_owned(),
                ));
            }
            for (identity, record_digest) in segment.record_digests {
                validate_digest(&record_digest, "retirement.record")?;
                if segment.digests.binary_search(&identity).is_err() {
                    return Err(ShellError::State(
                        "retirement record has no committed identity".to_owned(),
                    ));
                }
                store.record_digests.insert(identity, record_digest);
            }
            for identity in segment.digests {
                validate_digest(&identity, "retirement.identity")?;
                if !store.identities.insert(identity) {
                    return Err(ShellError::State(
                        "duplicate retirement identity".to_owned(),
                    ));
                }
            }
            cursor = segment.previous;
        }
        if cursor.count != 0 || store.identities.len() != store.checkpoint.count {
            return Err(ShellError::State(
                "retirement chain is incomplete".to_owned(),
            ));
        }
        if let Some(expected) = expected {
            let found = match &expected.head {
                None => expected.count == 0,
                Some(digest) => store.checkpoints.get(digest) == Some(&expected.count),
            };
            if !found {
                return Err(ShellError::State(
                    "retirement head regressed or belongs to another journal".to_owned(),
                ));
            }
        }
        Ok(Some(store))
    }

    pub(crate) fn create(journal: &Path) -> Result<Self, ShellError> {
        if let Some(store) = Self::open(journal, None)? {
            return Ok(store);
        }
        let root = PrivateStateRoot::open(directory(journal))?;
        let store = Self {
            root,
            checkpoint: Checkpoint::default(),
            identities: HashSet::new(),
            record_digests: HashMap::new(),
            checkpoints: HashMap::new(),
        };
        store.publish(&store.checkpoint)?;
        Ok(store)
    }

    fn publish(&self, checkpoint: &Checkpoint) -> Result<(), ShellError> {
        self.root.verify()?;
        crate::journal_storage::write(
            &self.root.path().join("head.json"),
            &serde_json::to_vec(&Head {
                schema: SCHEMA.to_owned(),
                checkpoint: checkpoint.clone(),
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
            if self.contains(&identity) && !self.record_digests.contains_key(&identity) {
                return Err(ShellError::State(
                    "legacy retirement identity cannot acquire an uncommitted receipt".to_owned(),
                ));
            }
            let bytes = serde_json::to_vec(record)?;
            if bytes.len() as u64 > RECORD_BYTES {
                return Err(ShellError::State(
                    "archived record exceeds byte limit".to_owned(),
                ));
            }
            let digest = sha256_hex(&bytes);
            if let Some(previous) = self.record_digests.get(&identity) {
                if previous != &digest {
                    return Err(ShellError::State(
                        "retired observation is immutable".to_owned(),
                    ));
                }
            }
            if record_digests.insert(identity, digest).is_some() {
                return Err(ShellError::State("duplicate archived operation".to_owned()));
            }
        }
        // No semantic rejection below can partially admit another record in a
        // mixed batch. These immutable records are published before references.
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
                    crate::journal_storage::write(&path, &bytes)?;
                }
                Err(error) => return Err(error.into()),
            }
        }
        let mut added: Vec<_> = identities
            .iter()
            .filter(|digest| !self.contains(digest))
            .cloned()
            .collect();
        added.sort_unstable();
        added.dedup();
        if added.is_empty() {
            return Ok(());
        }
        let mut checkpoint = self.checkpoint.clone();
        let mut checkpoints = Vec::new();
        for chunk in added.chunks(SEGMENT_ENTRIES) {
            let segment = Segment {
                schema: SCHEMA.to_owned(),
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
            let bytes = serde_json::to_vec(&segment)?;
            if bytes.len() as u64 > SEGMENT_BYTES {
                return Err(ShellError::State(
                    "retirement segment exceeds byte limit".to_owned(),
                ));
            }
            let digest = sha256_hex(&bytes);
            let path = self.root.path().join(format!("{digest}.json"));
            if std::fs::symlink_metadata(&path).is_ok() {
                if crate::file_input::read_bytes(&path, SEGMENT_BYTES)? != bytes {
                    return Err(ShellError::State(
                        "existing retirement segment changed".to_owned(),
                    ));
                }
            } else {
                crate::journal_storage::write(&path, &bytes)?;
            }
            checkpoint = Checkpoint {
                head: Some(digest.clone()),
                count: checkpoint
                    .count
                    .checked_add(chunk.len())
                    .ok_or_else(|| ShellError::State("retirement count overflow".to_owned()))?,
            };
            checkpoints.push((digest, checkpoint.count));
        }
        self.publish(&checkpoint)?;
        self.checkpoint = checkpoint;
        self.checkpoints.extend(checkpoints);
        self.identities.extend(added);
        self.record_digests.extend(record_digests);
        Ok(())
    }

    pub(crate) fn read_record(
        &self,
        identity: &str,
    ) -> Result<Option<OperationRecord>, ShellError> {
        self.root.verify()?;
        let Some(digest) = self.record_digests.get(identity) else {
            return Ok(None);
        };
        let bytes = crate::file_input::read_bytes(
            &self.root.path().join(format!("record-{digest}.json")),
            RECORD_BYTES,
        )?;
        if sha256_hex(&bytes) != *digest {
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
        Ok(Some(record))
    }

    pub(crate) fn contains(&self, digest: &str) -> bool {
        self.identities.contains(digest)
    }
    pub(crate) fn len(&self) -> usize {
        self.identities.len()
    }
    pub(crate) fn segments(&self) -> usize {
        self.checkpoints.len()
    }
    pub(crate) fn checkpoint(&self) -> Checkpoint {
        self.checkpoint.clone()
    }
}

#[cfg(test)]
#[path = "retirement_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "retirement_claim_tests.rs"]
mod claim_tests;
