//! Filesystem mechanics for a host-selected private directory. The host must
//! control all ancestor directories. The advisory lock coordinates cooperative
//! writers; it is not isolation from an adversary with the same OS credentials.

use std::collections::BTreeSet;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

use super::Entry;
use super::PlannerStoreError;
use super::PlannerStoreOptionsV1;
use super::codec;
use super::codec::HEADER_BYTES;
use super::codec::Header;

pub(super) struct StoreFiles {
    pub root: PathBuf,
    pub active: File,
    pub header: Header,
    _lock: File,
}

pub(super) struct Loaded {
    pub entries: Vec<Entry>,
    pub active_frame_ends: Vec<(u64, usize)>,
    pub active_bytes: usize,
    pub complete_active_bytes: usize,
}

impl StoreFiles {
    pub fn open(root: &Path, store_id: Digest32, initialize: bool) -> Result<Self, PlannerStoreError> {
        private_dir(root)?;
        private_dir(&root.join("segments"))?;
        let lock_path = root.join("writer.lock");
        reject_link(&lock_path)?;
        let lock = open_options().create(true).truncate(false).open(lock_path)?;
        match lock.try_lock() {
            Ok(()) => (),
            Err(fs::TryLockError::WouldBlock) => return Err(PlannerStoreError::Locked),
            Err(fs::TryLockError::Error(error)) => return Err(error.into()),
        }
        let path = root.join("active.hcp");
        reject_link(&path)?;
        if !path.exists() {
            if !initialize {
                return Err(PlannerStoreError::Rollback);
            }
            atomic_replace(&path, &Header::genesis(store_id).encode())?;
        }
        let mut active = open_options().open(&path)?;
        let mut bytes = [0_u8; HEADER_BYTES];
        active.read_exact(&mut bytes)?;
        let header = Header::decode(&bytes)?;
        if header.store_id != store_id {
            return Err(PlannerStoreError::Corrupt);
        }
        Ok(Self { root: root.to_path_buf(), active, header, _lock: lock })
    }

    pub fn load(&self, options: &PlannerStoreOptionsV1) -> Result<Loaded, PlannerStoreError> {
        self.check_capacity(options, 0, false)?;
        let bytes = read_bounded(&self.root.join("active.hcp"), options.maximum_bytes)?;
        let active = codec::decode_segment(&bytes)?;
        let active_frame_ends = active.frame_ends.clone();
        let complete_active_bytes = active.complete_bytes;
        let mut archive = active.header.archive_digest;
        let mut segments = vec![active];
        let mut seen = BTreeSet::new();
        while !archive.is_zero() {
            if !seen.insert(archive) || seen.len() > options.maximum_segments {
                return Err(PlannerStoreError::LimitExceeded);
            }
            let path = self.root.join("segments").join(format!("{archive}.segment"));
            let archived = read_bounded(&path, options.maximum_bytes)?;
            if Digest32::of_bytes(&archived) != archive {
                return Err(PlannerStoreError::Corrupt);
            }
            let decoded = codec::decode_segment(&archived)?;
            if decoded.complete_bytes != archived.len() {
                return Err(PlannerStoreError::Corrupt);
            }
            archive = decoded.header.archive_digest;
            segments.push(decoded);
        }
        segments.reverse();
        let genesis = Header::genesis(self.header.store_id);
        let mut sequence = 0;
        let mut head = genesis.base_head;
        let mut entries = Vec::new();
        for segment in segments {
            if segment.header.store_id != self.header.store_id
                || segment.header.base_sequence != sequence
                || segment.header.base_head != head
            {
                return Err(PlannerStoreError::Corrupt);
            }
            if let Some(last) = segment.entries.last() {
                sequence = last.sequence;
                head = last.digest;
            }
            entries.extend(segment.entries);
            if entries.len() > options.maximum_records {
                return Err(PlannerStoreError::LimitExceeded);
            }
        }
        Ok(Loaded {
            entries,
            active_frame_ends,
            active_bytes: bytes.len(),
            complete_active_bytes,
        })
    }

    pub fn check_capacity(
        &self,
        options: &PlannerStoreOptionsV1,
        additional: usize,
        new_segment: bool,
    ) -> Result<(), PlannerStoreError> {
        let mut total = self.active.metadata()?.len();
        let mut count = usize::from(new_segment);
        for entry in fs::read_dir(self.root.join("segments"))? {
            let entry = entry?;
            count = count.checked_add(1).ok_or(PlannerStoreError::LimitExceeded)?;
            if count > options.maximum_segments {
                return Err(PlannerStoreError::LimitExceeded);
            }
            let metadata = fs::symlink_metadata(entry.path())?;
            if !metadata.is_file() || metadata.file_type().is_symlink() {
                return Err(PlannerStoreError::Corrupt);
            }
            total = total.checked_add(metadata.len()).ok_or(PlannerStoreError::LimitExceeded)?;
        }
        let additional = u64::try_from(additional).map_err(|_| PlannerStoreError::LimitExceeded)?;
        if total.checked_add(additional).is_none_or(|size| size > options.maximum_bytes) {
            return Err(PlannerStoreError::LimitExceeded);
        }
        Ok(())
    }

    pub fn append_and_sync(&mut self, frame: &[u8]) -> Result<(), PlannerStoreError> {
        self.active.seek(SeekFrom::End(0))?;
        self.active.write_all(frame)?;
        self.active.sync_all()?;
        Ok(())
    }

    pub fn recover_prefix(
        &mut self,
        end: usize,
        options: &PlannerStoreOptionsV1,
    ) -> Result<Option<Digest32>, PlannerStoreError> {
        let bytes = read_bounded(&self.root.join("active.hcp"), options.maximum_bytes)?;
        if end > bytes.len() || end < HEADER_BYTES {
            return Err(PlannerStoreError::Corrupt);
        }
        if end == bytes.len() {
            return Ok(None);
        }
        let tail = &bytes[end..];
        let digest = Digest32::of_bytes(tail);
        let path = self.root.join("segments").join(format!("{digest}.orphan"));
        self.check_capacity(options, tail.len(), !path.exists())?;
        atomic_create(&path, tail)?;
        self.active.set_len(u64::try_from(end).map_err(|_| PlannerStoreError::LimitExceeded)?)?;
        self.active.sync_all()?;
        sync_directory(&self.root)?;
        Ok(Some(digest))
    }

    pub fn compact(
        &mut self,
        sequence: u64,
        head: Digest32,
        options: &PlannerStoreOptionsV1,
    ) -> Result<(), PlannerStoreError> {
        if sequence == self.header.base_sequence {
            return Ok(());
        }
        let current = read_bounded(&self.root.join("active.hcp"), options.maximum_bytes)?;
        let digest = Digest32::of_bytes(&current);
        let archive = self.root.join("segments").join(format!("{digest}.segment"));
        self.check_capacity(options, current.len() + HEADER_BYTES, !archive.exists())?;
        atomic_create(&archive, &current)?;
        let header = Header {
            store_id: self.header.store_id,
            base_sequence: sequence,
            base_head: head,
            archive_digest: digest,
        };
        self.replace_active(&header.encode())?;
        self.header = header;
        Ok(())
    }

    pub fn replace_active(&mut self, bytes: &[u8]) -> Result<(), PlannerStoreError> {
        atomic_replace(&self.root.join("active.hcp"), bytes)?;
        self.active = open_options().open(self.root.join("active.hcp"))?;
        self.header = Header::decode(bytes)?;
        Ok(())
    }
}

pub(super) fn read_bounded(path: &Path, maximum: u64) -> Result<Vec<u8>, PlannerStoreError> {
    reject_link(path)?;
    let file = File::open(path)?;
    if !file.metadata()?.is_file() || file.metadata()?.len() > maximum {
        return Err(PlannerStoreError::LimitExceeded);
    }
    let mut bytes = Vec::new();
    file.take(maximum.saturating_add(1)).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum {
        return Err(PlannerStoreError::LimitExceeded);
    }
    Ok(bytes)
}

pub(super) fn private_dir(path: &Path) -> Result<(), PlannerStoreError> {
    if !path.exists() {
        fs::create_dir_all(path)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
        }
        if let Some(parent) = path.parent() {
            sync_directory(parent)?;
        }
    }
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(PlannerStoreError::Corrupt);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(PlannerStoreError::UnsafePermissions);
        }
    }
    Ok(())
}

fn reject_link(path: &Path) -> Result<(), PlannerStoreError> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            Err(PlannerStoreError::Corrupt)
        }
        Ok(_) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn open_options() -> OpenOptions {
    let mut options = OpenOptions::new();
    options.read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options
}

pub(super) fn atomic_create(path: &Path, bytes: &[u8]) -> Result<(), PlannerStoreError> {
    reject_link(path)?;
    if path.exists() {
        let current = read_bounded(path, bytes.len() as u64)?;
        return if current == bytes { Ok(()) } else { Err(PlannerStoreError::IdentityConflict) };
    }
    atomic_replace(path, bytes)
}

fn atomic_replace(path: &Path, bytes: &[u8]) -> Result<(), PlannerStoreError> {
    reject_link(path)?;
    let parent = path.parent().ok_or(PlannerStoreError::Corrupt)?;
    let temporary = path.with_extension("next");
    reject_link(&temporary)?;
    if temporary.exists() {
        fs::remove_file(&temporary)?;
    }
    let mut file = open_options().create_new(true).open(&temporary)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(file);
    fs::rename(&temporary, path)?;
    sync_directory(parent)?;
    Ok(())
}

fn sync_directory(path: &Path) -> Result<(), PlannerStoreError> {
    File::open(path)?.sync_all()?;
    Ok(())
}
