//! Windows owner construction currently refuses the Unix-only checkpoint contract.
//! Exercise the public constructors and retain evidence of unchanged owned state.

use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::io::Read;
use std::os::windows::fs::MetadataExt;
use std::path::Path;
use std::path::PathBuf;

use pretty_assertions::assert_eq;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityOwner;

const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
const MAX_FIXTURE_ENTRIES: usize = 32;
const MAX_FIXTURE_FILE_BYTES: u64 = 64 * 1024;

#[derive(Clone, Copy)]
enum Constructor {
    Bootstrap,
    BootstrapPq,
    Open,
    OpenPq,
}

#[derive(Debug, PartialEq, Eq)]
enum EntryKind {
    Directory,
    File,
}

#[derive(Debug, PartialEq, Eq)]
struct EntrySnapshot {
    kind: EntryKind,
    attributes: u32,
    creation_time: u64,
    last_write_time: u64,
    bytes: Vec<u8>,
}

fn snapshot(root: &Path) -> io::Result<BTreeMap<PathBuf, EntrySnapshot>> {
    let mut entries = BTreeMap::new();
    let mut pending = vec![root.to_path_buf()];
    while let Some(path) = pending.pop() {
        if entries.len() >= MAX_FIXTURE_ENTRIES {
            return Err(io::Error::other("owned fixture exceeded its entry bound"));
        }
        let relative = path
            .strip_prefix(root)
            .map_err(io::Error::other)?
            .to_path_buf();
        let metadata = fs::symlink_metadata(&path)?;
        let attributes = metadata.file_attributes();
        if attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Err(io::Error::other(format!(
                "unexpected reparse point in owned fixture: {relative:?}"
            )));
        }
        let (kind, bytes) = if metadata.is_dir() {
            for child in fs::read_dir(&path)? {
                if entries.len() + pending.len() + 1 >= MAX_FIXTURE_ENTRIES {
                    return Err(io::Error::other("owned fixture exceeded its entry bound"));
                }
                pending.push(child?.path());
            }
            (EntryKind::Directory, Vec::new())
        } else if metadata.is_file() {
            let mut bytes = Vec::new();
            fs::File::open(&path)?
                .take(MAX_FIXTURE_FILE_BYTES + 1)
                .read_to_end(&mut bytes)?;
            if bytes.len() as u64 > MAX_FIXTURE_FILE_BYTES {
                return Err(io::Error::other(
                    "owned fixture exceeded its file byte bound",
                ));
            }
            (EntryKind::File, bytes)
        } else {
            return Err(io::Error::other("unexpected entry in owned fixture"));
        };
        entries.insert(
            relative,
            EntrySnapshot {
                kind,
                attributes,
                creation_time: metadata.creation_time(),
                last_write_time: metadata.last_write_time(),
                bytes,
            },
        );
    }
    Ok(entries)
}

async fn assert_windows_owner_refusal(constructor: Constructor) -> io::Result<()> {
    let fixture = tempfile::tempdir()?;
    let database_parent = fixture.path().join("database-parent");
    let checkpoint_parent = fixture.path().join("checkpoint-parent");
    fs::create_dir(&database_parent)?;
    fs::create_dir(&checkpoint_parent)?;
    fs::write(fixture.path().join("root-sentinel.bin"), b"root\0\xff")?;
    fs::write(database_parent.join("sentinel.bin"), b"database\0\xfe")?;
    fs::write(checkpoint_parent.join("sentinel.bin"), b"checkpoint\0\xfd")?;
    let database_path = database_parent.canonicalize()?.join("authority.sqlite");
    let checkpoint_path = checkpoint_parent.canonicalize()?.join("checkpoint.json");
    if matches!(constructor, Constructor::Open | Constructor::OpenPq) {
        // Refusal precedes reading or adopting these existing opaque artifacts.
        fs::write(&database_path, b"original database bytes\0\xfc")?;
        fs::write(&checkpoint_path, b"original checkpoint bytes\0\xfb")?;
    }
    let before = snapshot(fixture.path())?;
    let owner_id = "windows-owner-refusal";
    let result = match constructor {
        Constructor::Bootstrap => {
            AuthBusAuthorityOwner::bootstrap_new(&database_path, checkpoint_path, owner_id).await
        }
        Constructor::BootstrapPq => {
            AuthBusAuthorityOwner::bootstrap_new_pq(&database_path, checkpoint_path, owner_id).await
        }
        Constructor::Open => {
            AuthBusAuthorityOwner::open(&database_path, checkpoint_path, owner_id).await
        }
        Constructor::OpenPq => {
            AuthBusAuthorityOwner::open_pq(&database_path, checkpoint_path, owner_id).await
        }
    };
    let after = snapshot(fixture.path())?;
    assert_eq!(after, before, "owner refusal changed the owned fixture");
    let Err(error) = result else {
        panic!("Windows owner construction must refuse");
    };
    assert!(
        matches!(&error, AuthBusAuthorityError::UnsafeCheckpoint),
        "unexpected Windows owner refusal: {error:?}"
    );
    Ok(())
}

#[tokio::test]
async fn windows_bootstrap_refuses_without_creating_artifacts() -> io::Result<()> {
    assert_windows_owner_refusal(Constructor::Bootstrap).await
}

#[tokio::test]
async fn windows_pq_bootstrap_refuses_without_creating_artifacts() -> io::Result<()> {
    assert_windows_owner_refusal(Constructor::BootstrapPq).await
}

#[tokio::test]
async fn windows_open_refuses_without_modifying_existing_artifacts() -> io::Result<()> {
    assert_windows_owner_refusal(Constructor::Open).await
}

#[tokio::test]
async fn windows_pq_open_refuses_without_modifying_existing_artifacts() -> io::Result<()> {
    assert_windows_owner_refusal(Constructor::OpenPq).await
}
