use super::*;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

const REGISTERED_UID: u32 = 60001;

struct Fixture {
    root: PathBuf,
    source: SqliteConfig,
    destination: SqliteConfig,
    database: PathBuf,
}

impl Fixture {
    fn root_owned() -> anyhow::Result<Self> {
        assert_eq!(super::super::OwnerRule::CurrentUser.expected_uid()?, 0);
        let root = crate::test_support::unique_temp_dir();
        std::fs::create_dir(&root)?;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))?;
        let root = root.canonicalize()?;
        let source = root.join("registered");
        let protected = PathBuf::from(
            std::env::var_os("HEPTA_TEST_ROOT_MATERIAL_DESTINATION").ok_or_else(|| {
                anyhow::anyhow!("actual Root fixture must supply its protected destination")
            })?,
        );
        let destination = protected.join(root.file_name().expect("unique fixture basename"));
        for path in [&source, &destination] {
            std::fs::create_dir(path)?;
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
        }
        let database = source.join("cognitive.sqlite");
        for (suffix, bytes) in [
            ("", b"database".as_slice()),
            ("-wal", b"wal"),
            ("-shm", b"shm"),
            ("-journal", b"journal"),
        ] {
            let path = PathBuf::from(format!("{}{suffix}", database.display()));
            std::fs::write(&path, bytes)?;
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
            std::os::unix::fs::chown(&path, Some(REGISTERED_UID), None)?;
        }
        std::os::unix::fs::chown(&source, Some(REGISTERED_UID), None)?;
        Ok(Self {
            source: SqliteConfig::new_for_testing(source.as_path().abs()),
            destination: SqliteConfig::new_for_testing(destination.as_path().abs()),
            root,
            database,
        })
    }

    fn bind(&self) -> Result<RootSqliteMaterialSource, SqliteRecoveryError> {
        RootSqliteMaterialSource::bind_registered(
            &self.source,
            &self.database,
            REGISTERED_UID,
            &self.destination,
        )
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
        let _ = std::fs::remove_dir_all(self.destination.home());
    }
}

#[test]
fn registered_material_refuses_zero_source_before_filesystem_access() -> anyhow::Result<()> {
    let home = crate::test_support::unique_temp_dir();
    let source = SqliteConfig::new_for_testing(home.as_path().abs());
    let destination = SqliteConfig::new_for_testing(home.join("absent").as_path().abs());
    assert!(
        RootSqliteMaterialSource::bind_registered(
            &source,
            &home.join("absent.sqlite"),
            /*registered_uid*/ 0,
            &destination,
        )
        .is_err()
    );
    assert!(
        super::super::RootSqliteMaterialRegistration::bind_registered(
            &source,
            &home.join("absent.sqlite"),
            /*registered_uid*/ 0,
        )
        .is_err()
    );
    let actual = super::super::OwnerRule::CurrentUser.expected_uid()?;
    if actual != 0 {
        assert!(
            super::super::RootSqliteMaterialRegistration::bind_registered(
                &source,
                &home.join("absent.sqlite"),
                actual,
            )
            .is_err()
        );
        assert!(
            RootSqliteMaterialSource::bind_registered(
                &source,
                &home.join("absent.sqlite"),
                actual,
                &destination,
            )
            .is_err()
        );
    }
    assert!(!home.exists());
    Ok(())
}

#[test]
#[ignore = "run explicitly in an actual Root fixture; never relax the Root UID check"]
fn root_material_copies_registered_descriptors_without_opening_or_mutating_source()
-> anyhow::Result<()> {
    let fixture = Fixture::root_owned()?;
    // Default admission still refuses this non-Root source while running Root.
    assert!(
        fixture
            .source
            .bind_existing_recovery_database(&fixture.database)
            .is_err()
    );
    let before = std::fs::read(&fixture.database)?;
    let source_identity = std::fs::metadata(&fixture.database)?;
    let candidate = fixture
        .bind()?
        .materialize_private_candidate(OsStr::new("candidate.sqlite"))?;
    assert_eq!(std::fs::read(&candidate)?, b"database");
    assert_eq!(
        std::fs::read(candidate.with_extension("sqlite-wal"))?,
        b"wal"
    );
    assert_eq!(
        std::fs::read(candidate.with_extension("sqlite-journal"))?,
        b"journal"
    );
    assert!(!candidate.with_extension("sqlite-shm").exists());
    for path in [
        &candidate,
        &candidate.with_extension("sqlite-wal"),
        &candidate.with_extension("sqlite-journal"),
    ] {
        let metadata = std::fs::metadata(path)?;
        assert_eq!(
            (metadata.uid(), metadata.mode() & 0o7777, metadata.nlink()),
            (0, 0o600, 1)
        );
    }
    let after = std::fs::metadata(&fixture.database)?;
    assert_eq!(
        (
            after.dev(),
            after.ino(),
            after.uid(),
            after.mode(),
            after.mtime(),
            after.mtime_nsec(),
            after.ctime(),
            after.ctime_nsec()
        ),
        (
            source_identity.dev(),
            source_identity.ino(),
            source_identity.uid(),
            source_identity.mode(),
            source_identity.mtime(),
            source_identity.mtime_nsec(),
            source_identity.ctime(),
            source_identity.ctime_nsec()
        )
    );
    assert_eq!(std::fs::read(&fixture.database)?, before);
    Ok(())
}

#[test]
#[ignore = "run explicitly in an actual Root fixture; never relax the Root UID check"]
fn root_material_refuses_registered_identity_drift_and_unsafe_destination() -> anyhow::Result<()> {
    let fixture = Fixture::root_owned()?;
    assert!(
        RootSqliteMaterialSource::bind_registered(
            &fixture.source,
            &fixture.database,
            /*registered_uid*/ 60002,
            &fixture.destination
        )
        .is_err()
    );
    std::fs::set_permissions(
        fixture.destination.home(),
        std::fs::Permissions::from_mode(0o755),
    )?;
    assert!(fixture.bind().is_err());
    std::fs::set_permissions(
        fixture.destination.home(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let captured = fixture.bind()?;
    std::fs::rename(&fixture.database, fixture.database.with_extension("old"))?;
    std::fs::write(&fixture.database, b"replacement")?;
    std::fs::set_permissions(&fixture.database, std::fs::Permissions::from_mode(0o600))?;
    std::os::unix::fs::chown(&fixture.database, Some(REGISTERED_UID), None)?;
    assert!(
        captured
            .materialize_private_candidate(OsStr::new("candidate.sqlite"))
            .is_err()
    );
    assert!(!fixture.destination.home().join("candidate.sqlite").exists());
    Ok(())
}

#[test]
#[ignore = "run explicitly in an actual Root fixture; never relax the Root UID check"]
fn root_material_cannot_escape_home_or_overwrite_existing_material() -> anyhow::Result<()> {
    let fixture = Fixture::root_owned()?;
    for name in ["../escaped", "/absolute", "", "."] {
        assert!(
            fixture
                .bind()?
                .materialize_private_candidate(OsStr::new(name))
                .is_err()
        );
    }
    for suffix in ["-wal", "-shm", "-journal"] {
        let sidecar = fixture
            .destination
            .home()
            .join(format!("candidate.sqlite{suffix}"));
        std::fs::write(&sidecar, b"existing sidecar must remain untouched")?;
        std::fs::set_permissions(&sidecar, std::fs::Permissions::from_mode(0o600))?;
        assert!(
            fixture
                .bind()?
                .materialize_private_candidate(OsStr::new("candidate.sqlite"))
                .is_err()
        );
        assert_eq!(
            std::fs::read(&sidecar)?,
            b"existing sidecar must remain untouched"
        );
        assert!(!fixture.destination.home().join("candidate.sqlite").exists());
        std::fs::remove_file(sidecar)?;
    }
    let existing = fixture.destination.home().join("candidate.sqlite");
    std::fs::write(&existing, b"retain this previous material")?;
    std::fs::set_permissions(&existing, std::fs::Permissions::from_mode(0o600))?;
    assert!(
        fixture
            .bind()?
            .materialize_private_candidate(OsStr::new("candidate.sqlite"))
            .is_err()
    );
    assert_eq!(std::fs::read(existing)?, b"retain this previous material");
    assert!(!fixture.root.join("escaped").exists());
    Ok(())
}

#[test]
#[ignore = "requires actual Root0, a protected destination and private /data TMP"]
fn root_registration_keeps_inode_while_new_capture_admits_changed_contents() -> anyhow::Result<()> {
    let fixture = Fixture::root_owned()?;
    let registered = super::super::RootSqliteMaterialRegistration::bind_registered(
        &fixture.source,
        &fixture.database,
        REGISTERED_UID,
    )?;
    let identity = registered.identity().clone();
    registered
        .bind_capture(&fixture.destination)?
        .materialize_private_candidate(OsStr::new("first.sqlite"))?;
    std::fs::write(&fixture.database, b"new contents in the registered inode")?;
    registered.verify_registered()?;
    let second = registered
        .bind_capture(&fixture.destination)?
        .materialize_private_candidate(OsStr::new("second.sqlite"))?;
    assert_eq!(
        std::fs::read(second)?,
        b"new contents in the registered inode"
    );
    assert_eq!(registered.identity(), &identity);
    std::fs::rename(
        &fixture.database,
        fixture.database.with_extension("retired"),
    )?;
    std::fs::write(&fixture.database, b"replacement is not registered")?;
    std::fs::set_permissions(&fixture.database, std::fs::Permissions::from_mode(0o600))?;
    std::os::unix::fs::chown(&fixture.database, Some(REGISTERED_UID), None)?;
    assert!(registered.verify_registered().is_err());
    assert!(registered.bind_capture(&fixture.destination).is_err());

    let fixture = Fixture::root_owned()?;
    let registered = super::super::RootSqliteMaterialRegistration::bind_registered(
        &fixture.source,
        &fixture.database,
        REGISTERED_UID,
    )?;
    let old_parent = fixture.root.join("retired-parent");
    std::fs::rename(fixture.source.home(), &old_parent)?;
    std::fs::create_dir(fixture.source.home())?;
    std::fs::set_permissions(
        fixture.source.home(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    std::os::unix::fs::chown(fixture.source.home(), Some(REGISTERED_UID), None)?;
    std::fs::copy(old_parent.join("cognitive.sqlite"), &fixture.database)?;
    std::fs::set_permissions(&fixture.database, std::fs::Permissions::from_mode(0o600))?;
    std::os::unix::fs::chown(&fixture.database, Some(REGISTERED_UID), None)?;
    assert!(
        registered.verify_registered().is_err(),
        "a replaced parent is not registered"
    );
    assert!(registered.bind_capture(&fixture.destination).is_err());
    Ok(())
}
