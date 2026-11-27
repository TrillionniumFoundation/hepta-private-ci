//! Deterministic descriptor-lifetime checks; no fork, sleeps or scheduling hooks.
use super::*;
use crate::DurableFinalHoldoutJournalV1;
use crate::FinalHoldoutCasAnchorV1;
use crate::HoldoutAnchorV1;
use crate::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use std::any::Any;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);
pub(super) struct Fixture(PathBuf);
impl Fixture {
    pub(super) fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "hepta-lock-lifecycle-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        if let Err(error) = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&path)
        {
            panic!("create lifecycle fixture: {error}");
        }
        Self(path)
    }
    pub(super) fn open(&self) -> File {
        match OpenOptions::new().read(true).write(true).open(&self.0) {
            Ok(file) => file,
            Err(error) => panic!("open lifecycle fixture: {error}"),
        }
    }
    pub(super) fn assert_busy(&self) {
        assert!(matches!(
            self.open().try_lock(),
            Err(TryLockError::WouldBlock)
        ));
    }
    fn assert_available(&self) {
        let file = self.open();
        if let Err(error) = file.try_lock() {
            panic!("expected available lifecycle lock: {error}");
        }
        if let Err(error) = file.unlock() {
            panic!("release lifecycle probe lock: {error}");
        }
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

#[derive(Clone, Copy)]
enum Backend {
    Durable,
    Fenced,
}
const BACKENDS: [Backend; 2] = [Backend::Durable, Backend::Fenced];
fn binding() -> Digest32 {
    Digest32::of_bytes(b"lock lifecycle")
}
fn empty_anchor() -> HoldoutAnchorV1 {
    HoldoutAnchorV1 {
        sequence: 0,
        head: Digest32::ZERO,
    }
}
impl Backend {
    fn create(self, file: File) -> Result<Box<dyn Any>, String> {
        match self {
            Self::Durable => DurableFinalHoldoutJournalV1::create(file, binding())
                .map(|store| Box::new(store) as Box<dyn Any>)
                .map_err(|e| format!("{e:?}")),
            Self::Fenced => LockedFileFinalHoldoutCasStoreV1::create(file, binding())
                .map(|store| Box::new(store) as Box<dyn Any>)
                .map_err(|e| format!("{e:?}")),
        }
    }
    fn recover(self, file: File) -> Result<Box<dyn Any>, String> {
        match self {
            Self::Durable => DurableFinalHoldoutJournalV1::recover(file, binding(), empty_anchor())
                .map(|store| Box::new(store) as Box<dyn Any>)
                .map_err(|e| format!("{e:?}")),
            Self::Fenced => LockedFileFinalHoldoutCasStoreV1::recover(file, binding(), None)
                .map(|store| Box::new(store) as Box<dyn Any>)
                .map_err(|e| format!("{e:?}")),
        }
    }
}

#[test]
fn passive_reference_does_not_extend_either_owner_lifetime() {
    for backend in BACKENDS {
        let fixture = Fixture::new();
        let file = fixture.open();
        let passive = file.try_clone().unwrap();
        let owner = backend.create(file).unwrap();
        fixture.assert_busy();
        drop(owner);
        fixture.assert_available();
        let successor = backend.recover(fixture.open()).unwrap();
        // Closing an old OFD must not release the successor's independent lock.
        drop(passive);
        fixture.assert_busy();
        drop(successor);
        fixture.assert_available();
    }
}

#[test]
fn cloned_and_independent_contenders_cannot_unlock_any_backend_pair() {
    for owner_backend in BACKENDS {
        for contender_backend in BACKENDS {
            let fixture = Fixture::new();
            let file = fixture.open();
            let passive = file.try_clone().unwrap();
            let owner = owner_backend.create(file).unwrap();
            assert_eq!(
                contender_backend
                    .create(passive.try_clone().unwrap())
                    .err()
                    .as_deref(),
                Some("Busy")
            );
            fixture.assert_busy();
            assert_eq!(
                contender_backend
                    .recover(passive.try_clone().unwrap())
                    .err()
                    .as_deref(),
                Some("Busy")
            );
            fixture.assert_busy();
            assert_eq!(
                contender_backend.create(fixture.open()).err().as_deref(),
                Some("Busy")
            );
            assert_eq!(
                contender_backend.recover(fixture.open()).err().as_deref(),
                Some("Busy")
            );
            fixture.assert_busy();
            drop(owner);
            fixture.assert_available();
            let next = owner_backend.recover(fixture.open()).unwrap();
            drop(passive);
            fixture.assert_busy();
            drop(next);
        }
    }
}

#[test]
fn constructor_validation_errors_release_despite_passive_references() {
    for backend in BACKENDS {
        let fixture = Fixture::new();
        let file = fixture.open();
        let passive = file.try_clone().unwrap();
        assert_eq!(
            backend.recover(file).err().as_deref(),
            Some("MissingHeader")
        );
        fixture.assert_available();
        drop(passive);
        drop(backend.create(fixture.open()).unwrap());
        let file = fixture.open();
        let passive = file.try_clone().unwrap();
        assert_eq!(
            backend.create(file).err().as_deref(),
            Some("AlreadyInitialized")
        );
        fixture.assert_available();
        drop(passive);
        let mut file = fixture.open();
        file.write_all(b"corrupt!").unwrap();
        let passive = file.try_clone().unwrap();
        assert_eq!(backend.recover(file).err().as_deref(), Some("Corrupt"));
        fixture.assert_available();
        drop(passive);
        let file = fixture.open();
        file.set_len(33 * 1024 * 1024).unwrap();
        let passive = file.try_clone().unwrap();
        assert_eq!(backend.recover(file).err().as_deref(), Some("Capacity"));
        fixture.assert_available();
        drop(passive);
    }
}

#[test]
fn post_acquisition_write_failure_releases_despite_passive_reference() {
    for backend in BACKENDS {
        let fixture = Fixture::new();
        // Unix flock is permitted on a read-only descriptor; header write is not.
        let file = File::open(&fixture.0).unwrap();
        let passive = file.try_clone().unwrap();
        assert_eq!(backend.create(file).err().as_deref(), Some("Indeterminate"));
        fixture.assert_available();
        drop(passive);
    }
}

#[test]
fn invalid_minimum_and_rollback_errors_release_acquired_lock() {
    let fixture = Fixture::new();
    drop(Backend::Durable.create(fixture.open()).unwrap());
    let file = fixture.open();
    let passive = file.try_clone().unwrap();
    let bad = HoldoutAnchorV1 {
        sequence: 1,
        head: Digest32::ZERO,
    };
    assert!(matches!(
        DurableFinalHoldoutJournalV1::recover(file, binding(), bad),
        Err(crate::DurableHoldoutError::Binding)
    ));
    fixture.assert_available();
    drop(passive);
    let file = fixture.open();
    let passive = file.try_clone().unwrap();
    let absent = HoldoutAnchorV1 {
        sequence: 1,
        head: binding(),
    };
    assert!(matches!(
        DurableFinalHoldoutJournalV1::recover(file, binding(), absent),
        Err(crate::DurableHoldoutError::MissingAcknowledgedHistory)
    ));
    fixture.assert_available();
    drop(passive);

    let fixture = Fixture::new();
    drop(Backend::Fenced.create(fixture.open()).unwrap());
    let file = fixture.open();
    let passive = file.try_clone().unwrap();
    let minimum = FinalHoldoutCasAnchorV1 {
        fence_generation: 1,
        record_count: 1,
        state_digest: binding(),
    };
    assert!(matches!(
        LockedFileFinalHoldoutCasStoreV1::recover(file, binding(), Some(minimum)),
        Err(crate::LockedFileCasErrorV1::Rollback)
    ));
    fixture.assert_available();
    drop(passive);
}

#[test]
fn unsuccessful_os_acquisition_does_not_unlock_external_owner() {
    // Independent OFD: valid contention, not the unsupported prelocked alias case.
    for backend in BACKENDS {
        let fixture = Fixture::new();
        let external = fixture.open();
        external.try_lock().unwrap();
        assert_eq!(
            backend.create(fixture.open()).err().as_deref(),
            Some("Busy")
        );
        fixture.assert_busy();
        external.unlock().unwrap();
        drop(backend.create(fixture.open()).unwrap());
        fixture.assert_available();
    }
}

#[test]
fn pre_acquisition_binding_error_does_not_unlock_live_alias() {
    for backend in BACKENDS {
        let fixture = Fixture::new();
        let file = fixture.open();
        let alias = file.try_clone().unwrap();
        let owner = backend.create(file).unwrap();
        assert!(matches!(
            DurableFinalHoldoutJournalV1::create(alias.try_clone().unwrap(), Digest32::ZERO),
            Err(crate::DurableHoldoutError::Binding)
        ));
        assert!(matches!(
            LockedFileFinalHoldoutCasStoreV1::recover(alias, Digest32::ZERO, /*minimum*/ None),
            Err(crate::LockedFileCasErrorV1::Binding)
        ));
        fixture.assert_busy();
        drop(owner);
        fixture.assert_available();
    }
}

#[test]
fn into_store_moves_ownership_without_releasing_the_lock() {
    let fixture = Fixture::new();
    let file = fixture.open();
    let passive = file.try_clone().unwrap();
    let store = LockedFileFinalHoldoutCasStoreV1::create(file, binding()).unwrap();
    let mut issuer = crate::HoldoutFenceIssuerV1::resume(
        codex_hepta_types::StableId::new("lifecycle-owner").unwrap(),
        binding(),
        /*minimum*/ None,
    )
    .unwrap();
    let owner = crate::FencedFinalHoldoutOwnerV1::initialize(
        store,
        binding(),
        issuer.issue(binding()).unwrap(),
    )
    .unwrap();
    let store = owner.into_store();
    fixture.assert_busy();
    drop(store);
    fixture.assert_available();
    drop(passive);
}
