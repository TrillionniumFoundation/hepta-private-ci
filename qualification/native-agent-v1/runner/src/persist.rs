//! Private, single-writer qualification checkpoints. This is conversation state,
//! never the jobs registry or a production admission authority.
use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex;

pub struct Store {
    pub root: PathBuf,
    _lock: File,
    head: Mutex<(usize, String)>,
}

pub fn private_dir(path: &Path) -> Result<()> {
    match std::fs::symlink_metadata(path) {
        Ok(meta) => {
            if !meta.file_type().is_dir()
                || meta.permissions().mode() & 0o7777 != 0o700
                || meta.uid() != rustix::process::geteuid().as_raw()
            {
                bail!("qualification directory must already be a private real directory");
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            std::fs::DirBuilder::new().mode(0o700).create(path)?;
        }
        Err(error) => return Err(error.into()),
    }
    Ok(())
}

pub fn read_regular(path: &Path) -> Result<Vec<u8>> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)?;
    let meta = file.metadata()?;
    if !meta.is_file()
        || meta.nlink() != 1
        || meta.permissions().mode() & 0o7777 != 0o600
        || meta.uid() != rustix::process::geteuid().as_raw()
    {
        bail!("qualification record is not a private single-link regular file");
    }
    if meta.len() > 4 * 1024 * 1024 {
        bail!("qualification record byte limit");
    }
    use std::io::Read;
    let mut bytes = Vec::new();
    file.take(4 * 1024 * 1024 + 1).read_to_end(&mut bytes)?;
    if bytes.len() > 4 * 1024 * 1024 {
        bail!("qualification record grew beyond byte limit");
    }
    Ok(bytes)
}

impl Store {
    pub fn open(root: PathBuf, manifest: &Value) -> Result<(Self, Option<Value>)> {
        private_dir(&root)?;
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(root.join("owner.lock"))?;
        let meta = lock.metadata()?;
        if !meta.is_file()
            || meta.nlink() != 1
            || meta.permissions().mode() & 0o7777 != 0o600
            || meta.uid() != rustix::process::geteuid().as_raw()
        {
            bail!("unsafe qualification owner lock");
        }
        lock.try_lock()
            .context("qualification session is already owned")?;
        let mut store = Self {
            root,
            _lock: lock,
            head: Mutex::new((0, String::new())),
        };
        store.immutable("manifest.json", &serde_json::to_vec(manifest)?)?;
        let mut paths = std::fs::read_dir(&store.root)?.collect::<std::io::Result<Vec<_>>>()?;
        paths.sort_by_key(|entry| entry.file_name());
        let mut previous = String::new();
        let mut sequence = 0;
        let mut latest = None;
        for entry in paths {
            let name = entry.file_name().to_string_lossy().into_owned();
            if !name.starts_with("snapshot-") {
                continue;
            }
            let expected = format!("snapshot-{sequence:08}.json");
            if name != expected {
                bail!("checkpoint chain has a gap or unexpected record");
            }
            let bytes = read_regular(&entry.path())?;
            let record: Value = serde_json::from_slice(&bytes)?;
            if record["sequence"] != sequence || record["previous"] != previous {
                bail!("checkpoint predecessor mismatch");
            }
            latest = Some(record["state"].clone());
            previous = Digest32::of_bytes(&bytes).to_string();
            sequence += 1;
        }
        store.head = Mutex::new((sequence, previous));
        Ok((store, latest))
    }

    pub fn immutable(&self, name: &str, bytes: &[u8]) -> Result<()> {
        if name.contains('/') || name.starts_with('.') || bytes.len() > 4 * 1024 * 1024 {
            bail!("invalid qualification record");
        }
        let path = self.root.join(name);
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)
        {
            Ok(mut file) => {
                file.write_all(bytes)?;
                file.sync_all()?;
                File::open(&self.root)?.sync_all()?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                if read_regular(&path)? != bytes {
                    bail!("immutable admission changed: {name}");
                }
                OpenOptions::new()
                    .read(true)
                    .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
                    .open(&path)?
                    .sync_all()?;
                File::open(&self.root)?.sync_all()?;
            }
            Err(error) => return Err(error.into()),
        }
        Ok(())
    }

    pub fn checkpoint(&self, state: Value) -> Result<()> {
        let mut head = self
            .head
            .lock()
            .map_err(|_| anyhow::anyhow!("checkpoint lock poisoned"))?;
        let bytes =
            serde_json::to_vec(&json!({"sequence":head.0,"previous":head.1,"state":state}))?;
        self.immutable(&format!("snapshot-{:08}.json", head.0), &bytes)?;
        head.0 += 1;
        head.1 = Digest32::of_bytes(&bytes).to_string();
        Ok(())
    }
}
