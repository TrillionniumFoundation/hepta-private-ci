use super::*;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::ffi::OsString;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::symlink;

#[derive(Debug)]
struct RecoveryFixture {
    home: PathBuf,
    database: PathBuf,
    sqlite: SqliteConfig,
}

impl RecoveryFixture {
    fn with_complete_file_set() -> Self {
        let home = unique_temp_dir();
        std::fs::create_dir(&home).expect("create recovery home");
        std::fs::set_permissions(&home, std::fs::Permissions::from_mode(0o700))
            .expect("protect recovery home");
        let database = home.join("recovery.sqlite3");
        write_private(&database, b"database bytes");
        write_private(&sidecar_path(&database, "-wal"), b"wal bytes");
        write_private(&sidecar_path(&database, "-shm"), b"shm bytes");
        write_private(&sidecar_path(&database, "-journal"), b"journal bytes");
        let sqlite = SqliteConfig::new_for_testing(home.as_path().abs());
        Self {
            home,
            database,
            sqlite,
        }
    }
}

impl Drop for RecoveryFixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.home);
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct TreeImage {
    directory: MetadataImage,
    entries: BTreeMap<OsString, EntryImage>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct MetadataImage {
    device: u64,
    inode: u64,
    mode: u32,
    links: u64,
    length: u64,
    modified_seconds: i64,
    modified_nanoseconds: i64,
    changed_seconds: i64,
    changed_nanoseconds: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct EntryImage {
    metadata: MetadataImage,
    payload: EntryPayload,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum EntryPayload {
    Bytes(Vec<u8>),
    Symlink(PathBuf),
}

#[derive(Clone, Copy, Debug)]
enum FileRole {
    Database,
    Wal,
    Shm,
    Journal,
}

impl FileRole {
    fn path(self, database: &Path) -> PathBuf {
        match self {
            Self::Database => database.to_path_buf(),
            Self::Wal => sidecar_path(database, "-wal"),
            Self::Shm => sidecar_path(database, "-shm"),
            Self::Journal => sidecar_path(database, "-journal"),
        }
    }
}

#[derive(Clone, Copy, Debug)]
enum IdentityAttack {
    Symlink,
    Hardlink,
    Mode,
}

#[tokio::test]
async fn validated_file_set_is_unavailable_without_mutation_or_reconnect() {
    let fixture = RecoveryFixture::with_complete_file_set();
    let before = capture_tree(&fixture.home);
    let guard = fixture
        .sqlite
        .bind_existing_recovery_database(&fixture.database)
        .expect("retain a valid identity bundle");
    assert_eq!(capture_tree(&fixture.home), before);
    guard
        .verify_inspection_unchanged()
        .expect("read-only binding is unchanged");

    let retained_descriptor_count = matching_open_descriptor_count(&fixture.database);
    assert_eq!(retained_descriptor_count, 1);
    let legacy_error = match fixture
        .sqlite
        .open_existing_durable_evidence_pool(&fixture.database)
        .await
    {
        Ok(_) => panic!("legacy path recovery unexpectedly returned a pool"),
        Err(error) => error,
    };
    assert!(
        legacy_error
            .to_string()
            .contains("path-based SQLite recovery is disabled")
    );
    assert_eq!(
        matching_open_descriptor_count(&fixture.database),
        retained_descriptor_count
    );
    assert_eq!(capture_tree(&fixture.home), before);
    for _ in 0..32 {
        let inspection_error = match fixture.sqlite.open_immutable_recovery_pool(&guard).await {
            Ok(_) => panic!("fail-closed inspection unexpectedly returned a pool"),
            Err(error) => error,
        };
        let writer_error = match fixture
            .sqlite
            .open_identity_bound_durable_evidence_pool(guard.clone())
            .await
        {
            Ok(_) => panic!("fail-closed writer unexpectedly returned a pool"),
            Err(error) => error,
        };
        assert_eq!(
            (inspection_error, writer_error),
            (
                SqliteRecoveryError::Unavailable,
                SqliteRecoveryError::Unavailable,
            )
        );
        assert_eq!(
            matching_open_descriptor_count(&fixture.database),
            retained_descriptor_count
        );
        assert_eq!(capture_tree(&fixture.home), before);
    }
}

#[tokio::test]
async fn rename_replacement_is_indeterminate_without_mutation_or_reconnect() {
    let fixture = RecoveryFixture::with_complete_file_set();
    let guard = fixture
        .sqlite
        .bind_existing_recovery_database(&fixture.database)
        .expect("retain original identity bundle");
    let moved = fixture.home.join("original.sqlite3");
    std::fs::rename(&fixture.database, &moved).expect("move retained database");
    std::fs::copy(&moved, &fixture.database).expect("install byte-identical replacement");
    std::fs::set_permissions(&fixture.database, std::fs::Permissions::from_mode(0o600))
        .expect("protect replacement");
    let attacked = capture_tree(&fixture.home);
    let retained_descriptor_count = matching_open_descriptor_count(&moved);
    assert_eq!(retained_descriptor_count, 1);

    let inspection_error = match fixture.sqlite.open_immutable_recovery_pool(&guard).await {
        Ok(_) => panic!("rename replacement unexpectedly returned an inspection pool"),
        Err(error) => error,
    };
    let writer_error = match fixture
        .sqlite
        .open_identity_bound_durable_evidence_pool(guard.clone())
        .await
    {
        Ok(_) => panic!("rename replacement unexpectedly returned a writer pool"),
        Err(error) => error,
    };
    assert_eq!(
        (
            guard.verify_inspection_unchanged(),
            inspection_error,
            writer_error,
        ),
        (
            Err(SqliteRecoveryError::Indeterminate),
            SqliteRecoveryError::Indeterminate,
            SqliteRecoveryError::Indeterminate,
        )
    );
    assert_eq!(
        matching_open_descriptor_count(&moved),
        retained_descriptor_count
    );
    assert_eq!(capture_tree(&fixture.home), attacked);
}

#[test]
fn symlink_hardlink_and_mode_inputs_are_indeterminate_and_unchanged() {
    let roles = [
        FileRole::Database,
        FileRole::Wal,
        FileRole::Shm,
        FileRole::Journal,
    ];
    let attacks = [
        IdentityAttack::Symlink,
        IdentityAttack::Hardlink,
        IdentityAttack::Mode,
    ];

    for role in roles {
        for attack in attacks {
            let fixture = RecoveryFixture::with_complete_file_set();
            install_identity_attack(&fixture, role, attack);
            let attacked = capture_tree(&fixture.home);
            let error = match fixture
                .sqlite
                .bind_existing_recovery_database(&fixture.database)
            {
                Ok(_) => panic!("{role:?} {attack:?} unexpectedly produced a guard"),
                Err(error) => error,
            };
            assert_eq!(error, SqliteRecoveryError::Indeterminate);
            assert_eq!(
                matching_open_descriptor_count(&role.path(&fixture.database)),
                0
            );
            assert_eq!(capture_tree(&fixture.home), attacked);
        }
    }
}

#[tokio::test]
async fn sidecar_appearance_after_binding_is_indeterminate_and_unchanged() {
    let fixture = RecoveryFixture::with_complete_file_set();
    std::fs::remove_file(sidecar_path(&fixture.database, "-journal"))
        .expect("remove journal before binding");
    let guard = fixture
        .sqlite
        .bind_existing_recovery_database(&fixture.database)
        .expect("retain absent journal identity");
    let journal = sidecar_path(&fixture.database, "-journal");
    write_private(&journal, b"late journal");
    let attacked = capture_tree(&fixture.home);
    let descriptor_count = matching_open_descriptor_count(&fixture.database);
    assert_eq!(descriptor_count, 1);

    let error = match fixture.sqlite.open_immutable_recovery_pool(&guard).await {
        Ok(_) => panic!("late journal unexpectedly returned a pool"),
        Err(error) => error,
    };
    assert_eq!(error, SqliteRecoveryError::Indeterminate);
    assert_eq!(
        matching_open_descriptor_count(&fixture.database),
        descriptor_count
    );
    assert_eq!(capture_tree(&fixture.home), attacked);
}

fn install_identity_attack(fixture: &RecoveryFixture, role: FileRole, attack: IdentityAttack) {
    let path = role.path(&fixture.database);
    match attack {
        IdentityAttack::Symlink => {
            let retained = path.with_extension("retained");
            std::fs::rename(&path, &retained).expect("retain symlink target");
            symlink(retained.file_name().expect("retained file name"), &path)
                .expect("install symlink");
        }
        IdentityAttack::Hardlink => {
            let second_link = path.with_extension("hardlink");
            std::fs::hard_link(&path, second_link).expect("install hard link");
        }
        IdentityAttack::Mode => {
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o640))
                .expect("widen file mode");
        }
    }
}

fn write_private(path: &Path, bytes: &[u8]) {
    std::fs::write(path, bytes).expect("write fixture file");
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
        .expect("protect fixture file");
}

fn sidecar_path(database: &Path, suffix: &str) -> PathBuf {
    let mut path = database.as_os_str().to_os_string();
    path.push(suffix);
    PathBuf::from(path)
}

fn capture_tree(home: &Path) -> TreeImage {
    let directory = MetadataImage::capture(&std::fs::symlink_metadata(home).expect("stat home"));
    let mut entries = BTreeMap::new();
    for entry in std::fs::read_dir(home).expect("read recovery home") {
        let entry = entry.expect("read recovery entry");
        let path = entry.path();
        let metadata = std::fs::symlink_metadata(&path).expect("stat recovery entry");
        let payload = if metadata.file_type().is_symlink() {
            EntryPayload::Symlink(std::fs::read_link(&path).expect("read symlink target"))
        } else {
            EntryPayload::Bytes(std::fs::read(&path).expect("read recovery bytes"))
        };
        entries.insert(
            entry.file_name(),
            EntryImage {
                metadata: MetadataImage::capture(&metadata),
                payload,
            },
        );
    }
    TreeImage { directory, entries }
}

impl MetadataImage {
    fn capture(metadata: &std::fs::Metadata) -> Self {
        Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            mode: metadata.mode(),
            links: metadata.nlink(),
            length: metadata.len(),
            modified_seconds: metadata.mtime(),
            modified_nanoseconds: metadata.mtime_nsec(),
            changed_seconds: metadata.ctime(),
            changed_nanoseconds: metadata.ctime_nsec(),
        }
    }
}

fn matching_open_descriptor_count(path: &Path) -> usize {
    let metadata = std::fs::metadata(path).expect("stat descriptor target");
    (0..4096)
        .filter(|descriptor| {
            // SAFETY: `status` points to writable storage for `fstat`; probing
            // an invalid descriptor safely returns an error.
            let mut status: libc::stat = unsafe { std::mem::zeroed() };
            // SAFETY: `fstat` does not take ownership of the descriptor and the
            // pointer remains valid for the duration of the call.
            let result = unsafe { libc::fstat(*descriptor, &mut status) };
            result == 0
                && i128::from(status.st_dev) == i128::from(metadata.dev())
                && i128::from(status.st_ino) == i128::from(metadata.ino())
        })
        .count()
}
