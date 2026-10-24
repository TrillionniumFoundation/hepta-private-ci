use super::*;
use pretty_assertions::assert_eq;
use std::cell::Cell;
use std::os::unix::fs::PermissionsExt;

const OWNER: &str = "root-exact-initialization";

fn fixture() -> (tempfile::TempDir, Arc<RootAuthorityDirectory>) {
    assert_eq!(rustix::process::geteuid().as_raw(), 0);
    let directory = tempfile::Builder::new()
        .prefix("hepta-exact-genesis-")
        .tempdir_in("/run")
        .unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let root = RootAuthorityDirectory::open(directory.path()).unwrap();
    (directory, root)
}

fn prepare_actual_candidate(store: &HostAuthorityFrontierStore<u64>, value: u64) -> File {
    let name = format!("{}.next", store.name);
    let mut file = store
        .root
        .open_private(&name, OFlags::RDWR | OFlags::CREATE | OFlags::EXCL)
        .unwrap();
    file.write_all(&store.encode(&value).unwrap()).unwrap();
    file.sync_all().unwrap();
    store.root.sync_directory().unwrap();
    file
}

#[test]
#[ignore = "explicit Root exact canonical genesis reuses the original durable inode and refuses replacement"]
fn root_exact_initialization_reads_only_the_same_canonical_genesis() {
    let (directory, root) = fixture();
    let store = HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 7_u64).unwrap();
    let path = directory.path().join(&store.name);
    let before = std::fs::read(&path).unwrap();
    let inode = std::fs::metadata(&path).unwrap().ino();
    drop(store);
    let resumed =
        HostAuthorityFrontierStore::resume_initialization(root.clone(), OWNER.into(), 7_u64)
            .unwrap();
    assert_eq!(resumed.load(OWNER), Ok(7));
    assert_eq!(std::fs::metadata(&path).unwrap().ino(), inode);
    assert_eq!(std::fs::read(&path).unwrap(), before);
    assert!(matches!(
        HostAuthorityFrontierStore::resume_initialization(root, OWNER.into(), 8_u64),
        Err(AuthorityTrustError::Conflict)
    ));
    assert_eq!(std::fs::read(&path).unwrap(), before);
}

#[test]
#[ignore = "explicit Root complete original candidate publication retains inode and full value"]
fn root_exact_initialization_publishes_the_complete_matching_candidate() {
    let (directory, root) = fixture();
    let store = HostAuthorityFrontierStore::<u64>::configured(root.clone(), OWNER.into()).unwrap();
    let candidate = prepare_actual_candidate(&store, 17);
    let inode = candidate.metadata().unwrap().ino();
    let before = std::fs::read(directory.path().join(format!("{}.next", store.name))).unwrap();
    assert!(HostAuthorityFrontierStore::<u64>::open(root.clone(), OWNER.into()).is_err());
    let resumed =
        HostAuthorityFrontierStore::resume_initialization(root, OWNER.into(), 17_u64).unwrap();
    assert_eq!(resumed.load(OWNER), Ok(17));
    let path = directory.path().join(&resumed.name);
    assert_eq!(std::fs::metadata(&path).unwrap().ino(), inode);
    assert_eq!(std::fs::read(&path).unwrap(), before);
    assert!(
        !directory
            .path()
            .join(format!("{}.next", resumed.name))
            .exists()
    );
}

#[test]
#[ignore = "explicit Root different, malformed and wrongly protected candidates are retained and refused"]
fn root_exact_initialization_never_truncates_bad_or_later_candidates() {
    for case in ["later", "malformed", "wrong-owner", "unknown-field", "mode"] {
        let (directory, root) = fixture();
        let store =
            HostAuthorityFrontierStore::<u64>::configured(root.clone(), OWNER.into()).unwrap();
        let file = prepare_actual_candidate(&store, 17);
        drop(file);
        let path = directory.path().join(format!("{}.next", store.name));
        if case == "later" {
            std::fs::write(&path, store.encode(&18).unwrap()).unwrap();
        } else if case == "malformed" {
            std::fs::write(&path, b"{").unwrap();
        } else if case == "wrong-owner" || case == "unknown-field" {
            let mut record: serde_json::Value =
                serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
            if case == "wrong-owner" {
                record["owner_id"] = "another-owner".into();
            } else {
                record["unexpected"] = true.into();
            }
            std::fs::write(&path, serde_json::to_vec(&record).unwrap()).unwrap();
        } else {
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o400)).unwrap();
        }
        let retained = std::fs::read(&path).unwrap();
        assert!(
            HostAuthorityFrontierStore::resume_initialization(root, OWNER.into(), 17_u64).is_err(),
            "negative {case} must be refused"
        );
        assert_eq!(std::fs::read(&path).unwrap(), retained);
        assert!(!directory.path().join(&store.name).exists());
    }
}

#[test]
#[ignore = "explicit Root original lock contention and lost directory-sync acknowledgement"]
fn root_exact_initialization_keeps_lock_and_durability_failures_visible() {
    let (directory, root) = fixture();
    let store = HostAuthorityFrontierStore::<u64>::configured(root.clone(), OWNER.into()).unwrap();
    let lock = store.publication_lock().unwrap();
    assert!(matches!(
        HostAuthorityFrontierStore::resume_initialization(root.clone(), OWNER.into(), 23_u64),
        Err(AuthorityTrustError::Conflict)
    ));
    assert!(!directory.path().join(&store.name).exists());
    drop(lock);
    *root.before_directory_sync.lock().unwrap() = Some(Arc::new(|| {
        Err(std::io::Error::other(
            "controlled original directory-sync acknowledgement failure",
        ))
    }));
    assert!(matches!(
        HostAuthorityFrontierStore::resume_initialization(root.clone(), OWNER.into(), 23_u64),
        Err(AuthorityTrustError::Unavailable)
    ));
    let path = directory.path().join(&store.name);
    let visible = std::fs::read(&path).unwrap();
    let inode = std::fs::metadata(&path).unwrap().ino();
    *root.before_directory_sync.lock().unwrap() = None;
    let resumed =
        HostAuthorityFrontierStore::resume_initialization(root, OWNER.into(), 23_u64).unwrap();
    assert_eq!(resumed.load(OWNER), Ok(23));
    assert_eq!(std::fs::metadata(&path).unwrap().ino(), inode);
    assert_eq!(std::fs::read(&path).unwrap(), visible);
}

#[test]
#[ignore = "explicit Root locked absence refuses any existing canonical or candidate entry"]
fn root_absent_initialization_checks_both_names_and_retains_the_original_lock() {
    let (directory, root) = fixture();
    let configured =
        HostAuthorityFrontierStore::<u64>::configured(root.clone(), OWNER.into()).unwrap();
    let called = Cell::new(false);
    let result = HostAuthorityFrontierStore::<u64>::with_absent_initialization(
        root.clone(),
        OWNER.into(),
        || {
            called.set(true);
            assert!(matches!(
                HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 1_u64),
                Err(AuthorityTrustError::Conflict)
            ));
            7
        },
    );
    assert_eq!(result, Ok(7));
    assert!(called.get());
    assert!(!directory.path().join(&configured.name).exists());
    assert!(
        !directory
            .path()
            .join(format!("{}.next", configured.name))
            .exists()
    );

    for case in [
        "canonical",
        "complete-next",
        "partial-next",
        "directory-next",
    ] {
        let (directory, root) = fixture();
        let configured =
            HostAuthorityFrontierStore::<u64>::configured(root.clone(), OWNER.into()).unwrap();
        if case == "canonical" {
            drop(
                HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 1_u64).unwrap(),
            );
        } else if case == "complete-next" {
            drop(prepare_actual_candidate(&configured, 1));
        } else {
            let next = directory.path().join(format!("{}.next", configured.name));
            if case == "partial-next" {
                let mut file = configured
                    .root
                    .open_private(
                        &format!("{}.next", configured.name),
                        OFlags::RDWR | OFlags::CREATE | OFlags::EXCL,
                    )
                    .unwrap();
                file.write_all(b"{").unwrap();
            } else {
                std::fs::create_dir(next).unwrap();
            }
        }
        let called = Cell::new(false);
        assert!(matches!(
            HostAuthorityFrontierStore::<u64>::with_absent_initialization(
                root,
                OWNER.into(),
                || called.set(true),
            ),
            Err(AuthorityTrustError::Conflict)
        ));
        assert!(
            !called.get(),
            "existing {case} must not invoke the callback"
        );
    }
}

#[test]
#[ignore = "explicit Root absence postcondition also runs after an error-valued callback"]
fn root_absent_initialization_rechecks_publication_names_after_callback_errors() {
    let (directory, root) = fixture();
    let configured =
        HostAuthorityFrontierStore::<u64>::configured(root.clone(), OWNER.into()).unwrap();
    let inner_error = HostAuthorityFrontierStore::<u64>::with_absent_initialization(
        root.clone(),
        OWNER.into(),
        || Err::<(), _>(AuthorityTrustError::Invalid),
    );
    assert_eq!(inner_error, Ok(Err(AuthorityTrustError::Invalid)));
    let after_mutation =
        HostAuthorityFrontierStore::<u64>::with_absent_initialization(root, OWNER.into(), || {
            drop(prepare_actual_candidate(&configured, 1));
            Err::<(), _>(AuthorityTrustError::Invalid)
        });
    assert_eq!(after_mutation, Err(AuthorityTrustError::Unavailable));
    let next = directory.path().join(format!("{}.next", configured.name));
    assert!(next.is_file());
    assert!(!directory.path().join(&configured.name).exists());
}
