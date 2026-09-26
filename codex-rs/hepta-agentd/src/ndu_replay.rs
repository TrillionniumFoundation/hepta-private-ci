//! Durable, bounded replay state for external utility.ndu admission.
//!
//! The projection store's exclusive owner lock also fences this sidecar: only
//! the selected Agentd owner process may open it. Every transition writes a
//! complete checksummed image, synchronizes the file, atomically renames it and
//! synchronizes the parent directory. A post-rename directory-sync failure is
//! indeterminate and poisons the handle until reopen/reconciliation.

#![cfg_attr(
    test,
    expect(
        clippy::expect_used,
        reason = "replay-store tests use explicit fixture assertions"
    )
)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_agent_protocol::NduControlResultV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

const REPLAY_SCHEMA_V2: &str = "hepta.agentd.ndu-external-replay.v2";
const REPLAY_FILE_NAME: &str = ".ndu-external-replay-v2.json";
const REPLAY_TEMP_FILE_NAME: &str = ".ndu-external-replay-v2.tmp";
const MAX_REPLAY_ENTRIES_V2: usize = 4096;
const MAX_REPLAY_IMAGE_BYTES_V2: u64 = 16 * 1024 * 1024;
const MAX_REPLAY_CALLER_BYTES_V2: usize = 256;
const MAX_REPLAY_KEY_BYTES_V2: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
struct NduExternalReplayBindingV2 {
    binding_digest: Digest32,
    deadline_unix_ms: u64,
    result: Option<NduControlResultV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum NduExternalReplayBeginV2 {
    Fresh,
    Cached(NduControlResultV1),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum NduExternalReplayStoreErrorV2 {
    UnsupportedPlatform,
    Symlink,
    NotRegular,
    TooLarge,
    Corrupt,
    Capacity,
    Conflict,
    Pending,
    MissingEntry,
    Indeterminate,
    Io(io::ErrorKind),
}

impl fmt::Display for NduExternalReplayStoreErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduExternalReplayStoreErrorV2 {}

impl From<io::Error> for NduExternalReplayStoreErrorV2 {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct NduExternalReplayEntryV2 {
    caller_id: String,
    idempotency_key: String,
    binding_digest: [u8; 32],
    deadline_unix_ms: u64,
    result: Option<NduControlResultV1>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct NduExternalReplayImageV2 {
    schema: String,
    records_digest: [u8; 32],
    entries: Vec<NduExternalReplayEntryV2>,
}

#[derive(Debug)]
pub(crate) struct NduExternalReplayStoreV2 {
    root: PathBuf,
    replay_path: PathBuf,
    temp_path: PathBuf,
    entries: BTreeMap<(String, String), NduExternalReplayBindingV2>,
    indeterminate: bool,
}

impl NduExternalReplayStoreV2 {
    pub(crate) fn open(
        root: impl AsRef<Path>,
    ) -> Result<Self, NduExternalReplayStoreErrorV2> {
        if !cfg!(unix) {
            return Err(NduExternalReplayStoreErrorV2::UnsupportedPlatform);
        }
        let root = root.as_ref().to_path_buf();
        let root_metadata = fs::symlink_metadata(&root)?;
        if root_metadata.file_type().is_symlink() {
            return Err(NduExternalReplayStoreErrorV2::Symlink);
        }
        if !root_metadata.is_dir() {
            return Err(NduExternalReplayStoreErrorV2::NotRegular);
        }
        let replay_path = root.join(REPLAY_FILE_NAME);
        let temp_path = root.join(REPLAY_TEMP_FILE_NAME);
        remove_stale_temp(&temp_path)?;
        let loaded = load_image(&replay_path)?;
        let initialized = loaded.is_some();
        let mut store = Self {
            root,
            replay_path,
            temp_path,
            entries: loaded.unwrap_or_default(),
            indeterminate: false,
        };
        if !initialized {
            store.commit(BTreeMap::new())?;
        }
        Ok(store)
    }

    pub(crate) fn begin(
        &mut self,
        key: (String, String),
        binding_digest: Digest32,
        deadline_unix_ms: u64,
        now_unix_ms: u64,
    ) -> Result<NduExternalReplayBeginV2, NduExternalReplayStoreErrorV2> {
        self.require_authoritative()?;
        validate_text(&key.0, MAX_REPLAY_CALLER_BYTES_V2)?;
        validate_text(&key.1, MAX_REPLAY_KEY_BYTES_V2)?;
        if binding_digest.is_zero() || deadline_unix_ms == 0 {
            return Err(NduExternalReplayStoreErrorV2::Corrupt);
        }

        let mut next = self.entries.clone();
        next.retain(|_, binding| binding.deadline_unix_ms >= now_unix_ms);
        let pruned = next.len() != self.entries.len();
        if let Some(existing) = next.get(&key) {
            let existing_digest = existing.binding_digest;
            let existing_result = existing.result.clone();
            if pruned {
                self.commit(next)?;
            }
            if existing_digest != binding_digest {
                return Err(NduExternalReplayStoreErrorV2::Conflict);
            }
            return existing_result.map_or_else(
                || Err(NduExternalReplayStoreErrorV2::Pending),
                |result| Ok(NduExternalReplayBeginV2::Cached(result)),
            );
        }
        if next.len() >= MAX_REPLAY_ENTRIES_V2 {
            if pruned {
                self.commit(next)?;
            }
            return Err(NduExternalReplayStoreErrorV2::Capacity);
        }
        let replaced = next.insert(
            key,
            NduExternalReplayBindingV2 {
                binding_digest,
                deadline_unix_ms,
                result: None,
            },
        );
        if replaced.is_some() {
            return Err(NduExternalReplayStoreErrorV2::Conflict);
        }
        self.commit(next)?;
        Ok(NduExternalReplayBeginV2::Fresh)
    }

    pub(crate) fn complete(
        &mut self,
        key: &(String, String),
        binding_digest: Digest32,
        result: NduControlResultV1,
    ) -> Result<(), NduExternalReplayStoreErrorV2> {
        self.require_authoritative()?;
        let mut next = self.entries.clone();
        let existing = next
            .get_mut(key)
            .ok_or(NduExternalReplayStoreErrorV2::MissingEntry)?;
        if existing.binding_digest != binding_digest {
            return Err(NduExternalReplayStoreErrorV2::Conflict);
        }
        match &existing.result {
            Some(cached) if cached == &result => return Ok(()),
            Some(_) => return Err(NduExternalReplayStoreErrorV2::Conflict),
            None => existing.result = Some(result),
        }
        self.commit(next)
    }

    fn require_authoritative(&self) -> Result<(), NduExternalReplayStoreErrorV2> {
        if self.indeterminate {
            Err(NduExternalReplayStoreErrorV2::Indeterminate)
        } else {
            Ok(())
        }
    }

    fn commit(
        &mut self,
        next: BTreeMap<(String, String), NduExternalReplayBindingV2>,
    ) -> Result<(), NduExternalReplayStoreErrorV2> {
        self.require_authoritative()?;
        let entries = entries_from_map(&next);
        let records = serde_json::to_vec(&entries)
            .map_err(|_| NduExternalReplayStoreErrorV2::Corrupt)?;
        let image = NduExternalReplayImageV2 {
            schema: REPLAY_SCHEMA_V2.to_string(),
            records_digest: *Digest32::of_bytes(&records).as_array(),
            entries,
        };
        let bytes = serde_json::to_vec(&image)
            .map_err(|_| NduExternalReplayStoreErrorV2::Corrupt)?;
        let byte_len = u64::try_from(bytes.len())
            .map_err(|_| NduExternalReplayStoreErrorV2::TooLarge)?;
        if byte_len > MAX_REPLAY_IMAGE_BYTES_V2 {
            return Err(NduExternalReplayStoreErrorV2::TooLarge);
        }

        remove_stale_temp(&self.temp_path)?;
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut temporary = options.open(&self.temp_path)?;
        temporary.write_all(&bytes)?;
        temporary.sync_all()?;
        drop(temporary);
        fs::rename(&self.temp_path, &self.replay_path)?;
        self.entries = next;
        if sync_parent(&self.root).is_err() {
            self.indeterminate = true;
            return Err(NduExternalReplayStoreErrorV2::Indeterminate);
        }
        Ok(())
    }
}

fn entries_from_map(
    entries: &BTreeMap<(String, String), NduExternalReplayBindingV2>,
) -> Vec<NduExternalReplayEntryV2> {
    entries
        .iter()
        .map(|((caller_id, idempotency_key), binding)| NduExternalReplayEntryV2 {
            caller_id: caller_id.clone(),
            idempotency_key: idempotency_key.clone(),
            binding_digest: *binding.binding_digest.as_array(),
            deadline_unix_ms: binding.deadline_unix_ms,
            result: binding.result.clone(),
        })
        .collect()
}

fn load_image(
    path: &Path,
) -> Result<
    Option<BTreeMap<(String, String), NduExternalReplayBindingV2>>,
    NduExternalReplayStoreErrorV2,
> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    if metadata.file_type().is_symlink() {
        return Err(NduExternalReplayStoreErrorV2::Symlink);
    }
    if !metadata.is_file() {
        return Err(NduExternalReplayStoreErrorV2::NotRegular);
    }
    if metadata.len() > MAX_REPLAY_IMAGE_BYTES_V2 {
        return Err(NduExternalReplayStoreErrorV2::TooLarge);
    }
    let capacity = usize::try_from(metadata.len())
        .map_err(|_| NduExternalReplayStoreErrorV2::TooLarge)?;
    let mut bytes = Vec::with_capacity(capacity);
    File::open(path)?
        .take(MAX_REPLAY_IMAGE_BYTES_V2.saturating_add(1))
        .read_to_end(&mut bytes)?;
    let byte_len = u64::try_from(bytes.len())
        .map_err(|_| NduExternalReplayStoreErrorV2::TooLarge)?;
    if byte_len > MAX_REPLAY_IMAGE_BYTES_V2 {
        return Err(NduExternalReplayStoreErrorV2::TooLarge);
    }
    let image: NduExternalReplayImageV2 =
        serde_json::from_slice(&bytes).map_err(|_| NduExternalReplayStoreErrorV2::Corrupt)?;
    if image.schema != REPLAY_SCHEMA_V2 || image.entries.len() > MAX_REPLAY_ENTRIES_V2 {
        return Err(NduExternalReplayStoreErrorV2::Corrupt);
    }
    let records = serde_json::to_vec(&image.entries)
        .map_err(|_| NduExternalReplayStoreErrorV2::Corrupt)?;
    if image.records_digest != *Digest32::of_bytes(&records).as_array() {
        return Err(NduExternalReplayStoreErrorV2::Corrupt);
    }

    let mut entries = BTreeMap::new();
    let mut previous: Option<(String, String)> = None;
    for entry in image.entries {
        validate_text(&entry.caller_id, MAX_REPLAY_CALLER_BYTES_V2)?;
        validate_text(&entry.idempotency_key, MAX_REPLAY_KEY_BYTES_V2)?;
        let key = (entry.caller_id, entry.idempotency_key);
        if let Some(previous_key) = &previous {
            if previous_key >= &key {
                return Err(NduExternalReplayStoreErrorV2::Corrupt);
            }
        }
        let binding_digest = Digest32::from_array(entry.binding_digest);
        if binding_digest.is_zero() || entry.deadline_unix_ms == 0 {
            return Err(NduExternalReplayStoreErrorV2::Corrupt);
        }
        let replaced = entries.insert(
            key.clone(),
            NduExternalReplayBindingV2 {
                binding_digest,
                deadline_unix_ms: entry.deadline_unix_ms,
                result: entry.result,
            },
        );
        if replaced.is_some() {
            return Err(NduExternalReplayStoreErrorV2::Corrupt);
        }
        previous = Some(key);
    }
    Ok(Some(entries))
}

fn validate_text(
    value: &str,
    maximum: usize,
) -> Result<(), NduExternalReplayStoreErrorV2> {
    if value.is_empty() || value.len() > maximum || value.chars().any(char::is_control) {
        Err(NduExternalReplayStoreErrorV2::Corrupt)
    } else {
        Ok(())
    }
}

fn remove_stale_temp(path: &Path) -> Result<(), NduExternalReplayStoreErrorV2> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            Err(NduExternalReplayStoreErrorV2::Symlink)
        }
        Ok(metadata) if !metadata.is_file() => {
            Err(NduExternalReplayStoreErrorV2::NotRegular)
        }
        Ok(_) => fs::remove_file(path).map_err(Into::into),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn sync_parent(root: &Path) -> Result<(), NduExternalReplayStoreErrorV2> {
    #[cfg(unix)]
    {
        File::open(root)?.sync_all()?;
        Ok(())
    }
    #[cfg(not(unix))]
    {
        let _ = root;
        Err(NduExternalReplayStoreErrorV2::UnsupportedPlatform)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn private_root() -> tempfile::TempDir {
        let root = tempfile::tempdir().expect("temporary replay root");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))
                .expect("private replay root");
        }
        root
    }

    fn outcome() -> NduControlResultV1 {
        NduControlResultV1::Outcome { entry: None }
    }

    #[test]
    fn completed_and_pending_admissions_survive_reopen() {
        let root = private_root();
        let key = ("control-plane".to_string(), "idem-complete".to_string());
        let digest = Digest32::of_bytes(b"complete-binding");
        let mut store =
            NduExternalReplayStoreV2::open(root.path()).expect("open replay store");
        assert_eq!(
            store
                .begin(key.clone(), digest, 10_000, 1_000)
                .expect("fresh admission"),
            NduExternalReplayBeginV2::Fresh
        );
        store
            .complete(&key, digest, outcome())
            .expect("complete replay result");
        drop(store);

        let mut reopened = NduExternalReplayStoreV2::open(root.path()).expect("reopen replay");
        assert_eq!(
            reopened
                .begin(key.clone(), digest, 10_000, 1_100)
                .expect("cached admission"),
            NduExternalReplayBeginV2::Cached(outcome())
        );
        assert_eq!(
            reopened.begin(
                key,
                Digest32::of_bytes(b"different-binding"),
                10_000,
                1_100,
            ),
            Err(NduExternalReplayStoreErrorV2::Conflict)
        );

        let pending = ("control-plane".to_string(), "idem-pending".to_string());
        assert_eq!(
            reopened
                .begin(
                    pending.clone(),
                    Digest32::of_bytes(b"pending-binding"),
                    10_000,
                    1_100,
                )
                .expect("fresh pending admission"),
            NduExternalReplayBeginV2::Fresh
        );
        drop(reopened);
        let mut reopened = NduExternalReplayStoreV2::open(root.path()).expect("reopen pending");
        assert_eq!(
            reopened.begin(
                pending,
                Digest32::of_bytes(b"pending-binding"),
                10_000,
                1_200,
            ),
            Err(NduExternalReplayStoreErrorV2::Pending)
        );
    }

    #[test]
    fn corrupt_image_and_symlink_fail_closed() {
        let root = private_root();
        drop(NduExternalReplayStoreV2::open(root.path()).expect("initialize replay store"));
        fs::write(root.path().join(REPLAY_FILE_NAME), b"{}")
            .expect("replace replay with corrupt image");
        assert_eq!(
            NduExternalReplayStoreV2::open(root.path()).expect_err("corruption must reject"),
            NduExternalReplayStoreErrorV2::Corrupt
        );

        #[cfg(unix)]
        {
            use std::os::unix::fs::symlink;
            let root = private_root();
            symlink("missing-target", root.path().join(REPLAY_TEMP_FILE_NAME))
                .expect("create hostile temp symlink");
            assert_eq!(
                NduExternalReplayStoreV2::open(root.path())
                    .expect_err("temp symlink must reject"),
                NduExternalReplayStoreErrorV2::Symlink
            );
        }
    }
}
