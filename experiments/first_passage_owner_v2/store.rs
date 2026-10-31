//! Linux process-crash persistence; trusted private directory, bounded records.
use serde::Serialize;
use serde::de::DeserializeOwned;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::fs::{self};
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

pub const MAX_BYTES: u64 = 131_072;
pub const OPEN_FLAGS: i32 = libc::O_NOFOLLOW | libc::O_NONBLOCK;

#[derive(Default)]
pub struct Fault {
    pub point: String,
    pub marker: PathBuf,
}

impl Fault {
    pub fn at(&self, point: &str) -> Result<(), String> {
        if self.point != point {
            return Ok(());
        }
        let mut marker = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&self.marker)
            .map_err(|e| e.to_string())?;
        marker
            .write_all(point.as_bytes())
            .and_then(|()| marker.sync_all())
            .map_err(|e| e.to_string())?;
        let started = std::time::Instant::now();
        while started.elapsed().as_secs() < 30 {
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        Err("explicit fault probe timed out without external SIGKILL".into())
    }
}

pub struct Store {
    pub root: PathBuf,
    _lock: File,
}

pub fn regular_exists(path: &Path) -> Result<bool, String> {
    let m = match fs::symlink_metadata(path) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error.to_string()),
    };
    if !m.is_file() || m.file_type().is_symlink() {
        return Err("nonregular record".into());
    }
    Ok(true)
}

impl Store {
    pub fn open(root: &Path) -> Result<Self, String> {
        match fs::symlink_metadata(root) {
            Ok(m)
                if m.is_dir()
                    && !m.file_type().is_symlink()
                    && m.permissions().mode() & 0o077 == 0 => {}
            Ok(_) => return Err("owner directory must be private and ordinary".into()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                fs::DirBuilder::new()
                    .mode(0o700)
                    .create(root)
                    .map_err(|e| e.to_string())?;
                File::open(root.parent().ok_or("owner requires parent directory")?)
                    .and_then(|f| f.sync_all())
                    .map_err(|e| e.to_string())?;
            }
            Err(error) => return Err(error.to_string()),
        }
        let root = root.canonicalize().map_err(|e| e.to_string())?;
        let path = root.join("owner.lock");
        regular_exists(&path)?;
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(OPEN_FLAGS)
            .open(path)
            .map_err(|e| e.to_string())?;
        if !lock.metadata().map_err(|e| e.to_string())?.is_file() {
            return Err("nonregular lock handle".into());
        }
        match lock.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => {
                return Err("Busy: another research owner holds the run".into());
            }
            Err(TryLockError::Error(e)) => return Err(e.to_string()),
        }
        let store = Self { root, _lock: lock };
        store.sync()?;
        if fs::read_dir(&store.root)
            .map_err(|e| e.to_string())?
            .take(1025)
            .count()
            > 1024
        {
            return Err("owner directory exceeds bounded record census".into());
        }
        Ok(store)
    }

    pub fn sync(&self) -> Result<(), String> {
        File::open(&self.root)
            .and_then(|f| f.sync_all())
            .map_err(|e| e.to_string())
    }

    pub fn read<T: DeserializeOwned>(&self, name: &str) -> Result<Option<T>, String> {
        let path = self.root.join(name);
        if !regular_exists(&path)? {
            return Ok(None);
        }
        let mut data = Vec::new();
        OpenOptions::new()
            .read(true)
            .custom_flags(OPEN_FLAGS)
            .open(path)
            .map_err(|e| e.to_string())?
            .take(MAX_BYTES + 1)
            .read_to_end(&mut data)
            .map_err(|e| e.to_string())?;
        if data.len() as u64 > MAX_BYTES {
            return Err("oversized owner record".into());
        }
        serde_json::from_slice(&data)
            .map(Some)
            .map_err(|e| format!("invalid owner record: {e}"))
    }

    pub fn publish<T: Serialize>(
        &self,
        name: &str,
        value: &T,
        fault: &Fault,
    ) -> Result<(), String> {
        let mut bytes = serde_json::to_vec(value).map_err(|e| e.to_string())?;
        bytes.push(b'\n');
        if bytes.len() as u64 > MAX_BYTES {
            return Err("oversized publication".into());
        }
        let final_path = self.root.join(name);
        if regular_exists(&final_path)? {
            if fs::read(final_path).map_err(|e| e.to_string())? != bytes {
                return Err("immutable publication conflict".into());
            }
            return Ok(());
        }
        let temp = self.root.join(format!(".{name}.pending"));
        if regular_exists(&temp)? {
            fs::remove_file(&temp).map_err(|e| e.to_string())?;
        }
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&temp)
            .map_err(|e| e.to_string())?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|e| e.to_string())?;
        if name.starts_with("settled-") {
            fault.at("record_synced")?;
        }
        // A hard-link publication is atomic and refuses to replace another record.
        fs::hard_link(&temp, &final_path).map_err(|e| e.to_string())?;
        self.sync()?;
        fs::remove_file(temp).map_err(|e| e.to_string())?;
        self.sync()?;
        Ok(())
    }
}

impl Drop for Store {
    fn drop(&mut self) {
        let _ = self._lock.unlock();
    }
}
