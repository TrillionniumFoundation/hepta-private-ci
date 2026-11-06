//! File-backed test custody, never a substitute for the production root store.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::marker::PhantomData;
use std::path::Path;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use serde::Serialize;
use serde::de::DeserializeOwned;

pub(crate) const NOW: u64 = 1_000;

pub(crate) struct TestClock(pub(crate) AtomicU64);

impl AuthorityClock for TestClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

type AfterCommit = Box<dyn FnOnce() -> std::io::Result<()> + Send>;

pub(super) struct FileCas<T> {
    owner: String,
    file: Mutex<File>,
    failure: AtomicU8,
    after_commit: Mutex<Option<AfterCommit>>,
    marker: PhantomData<fn() -> T>,
}

impl<T: DeserializeOwned + Serialize + PartialEq> FileCas<T> {
    pub(super) fn create(path: &Path, owner: String, initial: &T) -> anyhow::Result<Self> {
        let mut file = OpenOptions::new().create_new(true).read(true).write(true).open(path)?;
        write_value(&mut file, initial)?;
        if let Some(parent) = path.parent() {
            File::open(parent)?.sync_all()?;
        }
        Ok(Self::from_file(owner, file))
    }

    pub(super) fn reopen(path: &Path, owner: String) -> anyhow::Result<Self> {
        let file = OpenOptions::new().read(true).write(true).open(path)?;
        let result = Self::from_file(owner.clone(), file);
        result.load(&owner)?;
        Ok(result)
    }

    fn from_file(owner: String, file: File) -> Self {
        Self {
            owner,
            file: Mutex::new(file),
            failure: AtomicU8::new(0),
            after_commit: Mutex::new(None),
            marker: PhantomData,
        }
    }

    pub(super) fn lose_next_ack(&self) {
        self.failure.store(2, Ordering::SeqCst);
    }

    pub(super) fn reject_next_write(&self) {
        self.failure.store(1, Ordering::SeqCst);
    }

    pub(super) fn after_next_commit(&self, callback: AfterCommit) -> anyhow::Result<()> {
        let mut slot = self.after_commit.lock().map_err(|_| anyhow::anyhow!("test hook poisoned"))?;
        anyhow::ensure!(slot.is_none(), "one bounded test hook at a time");
        *slot = Some(callback);
        Ok(())
    }

    fn locked<R>(&self, owner: &str, body: impl FnOnce(&mut File) -> Result<R, AuthorityTrustError>) -> Result<R, AuthorityTrustError> {
        if owner != self.owner {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut file = self.file.lock().map_err(|_| AuthorityTrustError::Unavailable)?;
        file.try_lock().map_err(|_| AuthorityTrustError::Conflict)?;
        let result = body(&mut file);
        file.unlock().map_err(|_| AuthorityTrustError::Unavailable)?;
        result
    }
}

impl<T: DeserializeOwned + Serialize + PartialEq> AuthorityFrontierStore<T> for FileCas<T> {
    fn load(&self, owner: &str) -> Result<T, AuthorityTrustError> {
        self.locked(owner, |file| read_value(file).map_err(|_| AuthorityTrustError::Invalid))
    }

    fn compare_and_set(&self, owner: &str, expected: &T, next: &T) -> Result<(), AuthorityTrustError> {
        self.locked(owner, |file| {
            let actual: T = read_value(file).map_err(|_| AuthorityTrustError::Invalid)?;
            if &actual != expected {
                return Err(AuthorityTrustError::Conflict);
            }
            let failure = self.failure.swap(0, Ordering::SeqCst);
            if failure == 1 {
                return Err(AuthorityTrustError::Unavailable);
            }
            write_value(file, next).map_err(|_| AuthorityTrustError::Unavailable)?;
            if let Some(callback) = self.after_commit.lock().map_err(|_| AuthorityTrustError::Unavailable)?.take() {
                callback().map_err(|_| AuthorityTrustError::Unavailable)?;
            }
            if failure == 2 {
                return Err(AuthorityTrustError::Unavailable);
            }
            Ok(())
        })
    }
}

fn read_value<T: DeserializeOwned>(file: &mut File) -> std::io::Result<T> {
    if !file.metadata()?.is_file() || file.metadata()?.len() > 65_536 {
        return Err(std::io::Error::other("test frontier is not a bounded regular file"));
    }
    file.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn write_value<T: Serialize>(file: &mut File, value: &T) -> std::io::Result<()> {
    let bytes = serde_json::to_vec(value)?;
    if bytes.len() > 65_536 {
        return Err(std::io::Error::other("test frontier exceeds its bound"));
    }
    file.seek(SeekFrom::Start(0))?;
    file.write_all(&bytes)?;
    file.set_len(bytes.len() as u64)?;
    file.sync_all()
}
