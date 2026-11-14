//! Bounded Root-record DATA without acquiring a live Root's nonblocking lock.
//! A fully validated atomic replacement is retried; malformed bytes never are.

use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeOwned;

const RECORD_BOUND: u64 = 65_536;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Envelope<T> {
    schema: u8,
    owner_id: String,
    frontier: T,
}

pub(super) fn observe_original_record<T: DeserializeOwned + Serialize>(
    directory: &Path,
    owner: &str,
    validate: impl Fn(&T) -> anyhow::Result<()>,
) -> anyhow::Result<Option<T>> {
    RootAuthorityDirectory::open(directory)?;
    let path = directory.join(format!(
        "frontier-v1-{}.json",
        Digest32::of_bytes(owner.as_bytes())
    ));
    let first = Image::read(&path)?;
    let second = Image::read(&path)?;
    let decode = |image: &Image| -> anyhow::Result<T> {
        let envelope: Envelope<T> = serde_json::from_slice(&image.bytes)?;
        anyhow::ensure!(
            envelope.schema == 1
                && envelope.owner_id == owner
                && serde_json::to_vec(&envelope)? == image.bytes,
            "actual Root record envelope or canonical bytes differ"
        );
        validate(&envelope.frontier)?;
        Ok(envelope.frontier)
    };
    let _first_data = decode(&first)?;
    let data = decode(&second)?;
    let before = first.require_unchanged()?;
    let after = second.require_unchanged()?;
    RootAuthorityDirectory::open(directory)?;
    let named = std::fs::symlink_metadata(&path)?;
    require_private(&named)?;
    anyhow::ensure!(named.nlink() == 1, "Root named record is not published");
    if (before.dev(), before.ino()) != (after.dev(), after.ino()) {
        anyhow::ensure!(
            before.nlink() == 0,
            "Root record changed without atomic replacement"
        );
        return Ok(None);
    }
    if (named.dev(), named.ino()) != (after.dev(), after.ino()) {
        anyhow::ensure!(
            after.nlink() == 0,
            "Root replacement retained an unexpected link"
        );
        return Ok(None);
    }
    anyhow::ensure!(
        after.nlink() == 1 && first.bytes == second.bytes,
        "Root image mutated in place"
    );
    Ok(Some(data))
}

struct Image {
    file: File,
    metadata: std::fs::Metadata,
    bytes: Vec<u8>,
}

impl Image {
    fn read(path: &Path) -> anyhow::Result<Self> {
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(path)?;
        let metadata = file.metadata()?;
        require_private(&metadata)?;
        let mut bytes = vec![0; usize::try_from(metadata.len())?];
        file.read_exact_at(&mut bytes, /*offset*/ 0)?;
        let image = Self {
            file,
            metadata,
            bytes,
        };
        image.require_unchanged()?;
        Ok(image)
    }

    fn require_unchanged(&self) -> anyhow::Result<std::fs::Metadata> {
        let stamp = |value: &std::fs::Metadata| {
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
        let require = |now: &std::fs::Metadata| -> anyhow::Result<()> {
            require_private(now)?;
            anyhow::ensure!(
                stamp(now) == stamp(&self.metadata) && now.nlink() <= self.metadata.nlink(),
                "original Root inode changed"
            );
            if now.nlink() == self.metadata.nlink() {
                anyhow::ensure!(
                    (now.ctime(), now.ctime_nsec())
                        == (self.metadata.ctime(), self.metadata.ctime_nsec()),
                    "original Root inode mutation observed"
                );
            }
            Ok(())
        };
        require(&self.file.metadata()?)?;
        let mut again = vec![0; self.bytes.len()];
        self.file.read_exact_at(&mut again, /*offset*/ 0)?;
        anyhow::ensure!(again == self.bytes, "Root physical bytes changed");
        let after = self.file.metadata()?;
        require(&after)?;
        Ok(after)
    }
}

fn require_private(metadata: &std::fs::Metadata) -> anyhow::Result<()> {
    anyhow::ensure!(
        metadata.is_file()
            && metadata.uid() == 0
            && metadata.mode() == 0o100600
            && metadata.nlink() <= 1
            && (1..=RECORD_BOUND).contains(&metadata.len()),
        "existing private bounded Root record required"
    );
    Ok(())
}
