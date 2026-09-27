//! Reopen is a durability boundary, including after a lost rename acknowledgement.
use std::fs;
use std::fs::File;
use std::io;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::FsProjectionPersistenceV1;
use super::JOURNAL_FILE;
use super::NduProjectionStoreError;
use super::NduProjectionStoreV1;
use super::ProjectionPersistenceV1;
use crate::NduOwnerContextV1;
use crate::NduProjectionKindV1;

#[derive(Clone, Copy, Eq, PartialEq)]
enum RecoveryCut {
    None,
    FileSync,
    DirectorySync,
    MutationDirectorySync,
}

struct RecoveryPersistence {
    cut: RecoveryCut,
    observations: AtomicUsize,
}

impl ProjectionPersistenceV1 for RecoveryPersistence {
    fn write_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()> {
        FsProjectionPersistenceV1.write_temp(path, bytes)
    }

    fn sync_temp(&self, path: &Path) -> io::Result<()> {
        FsProjectionPersistenceV1.sync_temp(path)
    }

    fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
        FsProjectionPersistenceV1.rename(from, to)
    }

    fn sync_parent(&self, root: &Path) -> io::Result<()> {
        if self.cut == RecoveryCut::MutationDirectorySync {
            return Err(io::Error::other("injected lost mutation acknowledgement"));
        }
        FsProjectionPersistenceV1.sync_parent(root)
    }

    fn confirm_recovered(&self, journal: &File, root: &Path) -> io::Result<()> {
        self.observations.fetch_add(1, Ordering::SeqCst);
        if self.cut == RecoveryCut::FileSync {
            return Err(io::Error::other("injected recovery file-sync failure"));
        }
        journal.sync_all()?;
        if self.cut == RecoveryCut::DirectorySync {
            return Err(io::Error::other("injected recovery directory-sync failure"));
        }
        FsProjectionPersistenceV1.sync_parent(root)
    }
}

#[test]
fn projection_store_reopen_requires_recovery_barriers_before_exact_replay()
-> Result<(), Box<dyn std::error::Error>> {
    let root = tempfile::tempdir()?;
    let value = Digest32::of_bytes(b"recovery-identity");
    let mut store = NduProjectionStoreV1::open_durable(root.path())?;
    let expected =
        store.append_projection(NduProjectionKindV1::Preference, value, value, value, value)?;
    let bytes = store.backup_bytes()?;
    drop(store);
    for cut in [RecoveryCut::FileSync, RecoveryCut::DirectorySync] {
        let persistence = Arc::new(RecoveryPersistence {
            cut,
            observations: AtomicUsize::new(0),
        });
        assert!(matches!(
            NduProjectionStoreV1::open_with_persistence(root.path(), persistence.clone()),
            Err(NduProjectionStoreError::Indeterminate)
        ));
        assert_eq!(persistence.observations.load(Ordering::SeqCst), 1);
        assert_eq!(fs::read(root.path().join(JOURNAL_FILE))?, bytes);
    }
    let persistence = Arc::new(RecoveryPersistence {
        cut: RecoveryCut::None,
        observations: AtomicUsize::new(0),
    });
    let mut store = NduProjectionStoreV1::open_with_persistence(root.path(), persistence.clone())?;
    assert_eq!(persistence.observations.load(Ordering::SeqCst), 1);
    let replay =
        store.append_projection(NduProjectionKindV1::Preference, value, value, value, value)?;
    assert_eq!(replay, expected);
    assert_eq!(store.backup_bytes()?, bytes);
    Ok(())
}

#[test]
fn projection_store_corrupt_image_is_not_confirmed_as_recovered()
-> Result<(), Box<dyn std::error::Error>> {
    let root = tempfile::tempdir()?;
    drop(NduProjectionStoreV1::open_durable(root.path())?);
    fs::write(root.path().join(JOURNAL_FILE), b"corrupt")?;
    let persistence = Arc::new(RecoveryPersistence {
        cut: RecoveryCut::None,
        observations: AtomicUsize::new(0),
    });
    assert!(matches!(
        NduProjectionStoreV1::open_with_persistence(root.path(), persistence.clone()),
        Err(NduProjectionStoreError::Journal(_))
    ));
    assert_eq!(persistence.observations.load(Ordering::SeqCst), 0);
    Ok(())
}

#[test]
fn projection_store_owner_binding_rejects_writable_and_hardlinked_history()
-> Result<(), Box<dyn std::error::Error>> {
    let root = tempfile::tempdir()?;
    let value = Digest32::of_bytes(b"binding-context");
    let context = NduOwnerContextV1 {
        principal_id: StableId::new("owner")?,
        owner_id: StableId::new("utility.ndu")?,
        host_generation: 1,
        principal_scope_digest: value,
        fence_digest: value,
        revocation_frontier_digest: value,
    };
    // The caller must retain the writer lock throughout binding/recovery.
    let _store = NduProjectionStoreV1::open_durable(root.path())?;
    crate::owner_binding::bind_owner(root.path(), &context, value, /*empty*/ true)?;
    let binding = root.path().join("owner-binding.v1");
    assert_eq!(fs::metadata(&binding)?.permissions().mode() & 0o777, 0o600);
    fs::set_permissions(&binding, fs::Permissions::from_mode(0o666))?;
    assert!(
        crate::owner_binding::bind_owner(root.path(), &context, value, /*empty*/ false).is_err()
    );
    fs::set_permissions(&binding, fs::Permissions::from_mode(0o600))?;
    let link = root.path().join("linked-binding");
    fs::hard_link(&binding, &link)?;
    assert!(
        crate::owner_binding::bind_owner(root.path(), &context, value, /*empty*/ false).is_err()
    );
    fs::remove_file(link)?;
    crate::owner_binding::bind_owner(root.path(), &context, value, /*empty*/ false)?;
    Ok(())
}

#[test]
fn projection_store_lost_rename_ack_cannot_be_laundered_by_reopen()
-> Result<(), Box<dyn std::error::Error>> {
    let root = tempfile::tempdir()?;
    drop(NduProjectionStoreV1::open_durable(root.path())?);
    let value = Digest32::of_bytes(b"lost-rename-ack");
    let mut store = NduProjectionStoreV1::open_with_persistence(
        root.path(),
        Arc::new(RecoveryPersistence {
            cut: RecoveryCut::MutationDirectorySync,
            observations: AtomicUsize::new(0),
        }),
    )?;
    assert_eq!(
        store.append_projection(NduProjectionKindV1::Utility, value, value, value, value),
        Err(NduProjectionStoreError::Indeterminate)
    );
    assert!(store.is_indeterminate());
    drop(store);
    assert!(matches!(
        NduProjectionStoreV1::open_with_persistence(
            root.path(),
            Arc::new(RecoveryPersistence {
                cut: RecoveryCut::DirectorySync,
                observations: AtomicUsize::new(0),
            }),
        ),
        Err(NduProjectionStoreError::Indeterminate)
    ));
    let mut recovered = NduProjectionStoreV1::open_durable(root.path())?;
    let replay =
        recovered.append_projection(NduProjectionKindV1::Utility, value, value, value, value)?;
    assert_eq!(replay.sequence, 1);
    assert_eq!(recovered.entries()?.len(), 1);
    Ok(())
}
