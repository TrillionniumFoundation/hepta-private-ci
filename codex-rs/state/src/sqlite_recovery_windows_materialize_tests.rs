use super::super::super::descriptor_io;
use super::super::super::sqlite_sidecar_path;
use super::super::Kind;
use super::super::identity;
use super::Fixture;
use anyhow::Context as _;
use pretty_assertions::assert_eq;
use std::fs::File;

#[test]
fn retained_windows_materialization_preserves_bound_source_bundle() -> anyhow::Result<()> {
    let subscriber = tracing_subscriber::fmt().with_test_writer().finish();
    tracing::subscriber::with_default(subscriber, || {
        let fixture = Fixture::bundle()?;
        let paths = fixture.paths();
        let files = paths
            .iter()
            .map(File::open)
            .collect::<std::io::Result<Vec<_>>>()?;
        let snapshots = files
            .iter()
            .map(|file| identity::snapshot(file, Kind::File))
            .collect::<Result<Vec<_>, _>>()?;
        let bytes = files
            .iter()
            .map(retained_bytes)
            .collect::<anyhow::Result<Vec<_>>>()?;
        let guard = fixture
            .sqlite
            .bind_existing_recovery_database(&fixture.path)
            .context("bind retained source")?;
        let candidate = fixture.home.join("materialized.sqlite3");

        fixture
            .sqlite
            .materialize_identity_bound_recovery_copy(&guard, &candidate)
            .context("materialize bound candidate")?;

        for (index, suffix) in [(0, ""), (1, "-wal"), (3, "-journal")] {
            assert_eq!(
                std::fs::read(sqlite_sidecar_path(&candidate, suffix))?,
                bytes[index]
            );
        }
        assert!(!sqlite_sidecar_path(&candidate, "-shm").try_exists()?);

        // Creating the separate candidate changes the parent directory. Every
        // original component must retain its complete identity and bytes.
        for ((file, snapshot), original_bytes) in files.iter().zip(&snapshots).zip(&bytes) {
            assert_eq!(&identity::snapshot(file, Kind::File)?, snapshot);
            assert_eq!(&retained_bytes(file)?, original_bytes);
        }
        for (path, snapshot) in paths.iter().zip(&snapshots) {
            assert_eq!(
                &identity::snapshot(&File::open(path)?, Kind::File)?,
                snapshot
            );
        }
        Ok(())
    })
}

fn retained_bytes(file: &File) -> anyhow::Result<Vec<u8>> {
    let length = usize::try_from(file.metadata()?.len())?;
    let mut bytes = vec![0; length];
    descriptor_io::read_exact_at(file, &mut bytes)?;
    Ok(bytes)
}
