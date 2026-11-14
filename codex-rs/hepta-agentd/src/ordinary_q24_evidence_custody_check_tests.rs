//! Real filesystem checks for evidence survival, separate from business or
//! native Root qualification. The outer temporary directory owns cleanup.

use std::fs::File;
use std::io;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use pretty_assertions::assert_eq;

use super::OriginalEvidenceDirectory;
use super::OriginalEvidenceDirectoryKind;

fn physical(path: &Path) -> io::Result<(u64, u64, u32, u32, u32, u64)> {
    let original = std::fs::symlink_metadata(path)?;
    Ok((
        original.dev(),
        original.ino(),
        original.uid(),
        original.gid(),
        original.mode(),
        original.len(),
    ))
}

#[test]
fn original_fixture_error_preserves_existing_directory_and_business_bytes() -> anyhow::Result<()> {
    let cleanup = tempfile::tempdir()?;
    let original = OriginalEvidenceDirectory::new(
        tempfile::tempdir_in(cleanup.path())?,
        OriginalEvidenceDirectoryKind::AProtected,
    );
    std::fs::set_permissions(original.path(), std::fs::Permissions::from_mode(0o700))?;
    let path = original.path().to_path_buf();
    let business = path.join("original-record");
    let mut file = File::create_new(&business)?;
    file.write_all(b"original input retained before failed fixture preparation")?;
    file.sync_all()?;
    drop(file);
    let before = (
        physical(&path)?,
        physical(&business)?,
        std::fs::read(&business)?,
    );
    let failure: io::Result<()> = (move || {
        let _original = original;
        Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "actual fixture preparation failed before producing a holder",
        ))
    })();
    assert_eq!(
        failure
            .expect_err("fixture failure must remain an error")
            .kind(),
        io::ErrorKind::InvalidData
    );
    assert_eq!(
        (
            physical(&path)?,
            physical(&business)?,
            std::fs::read(&business)?
        ),
        before
    );
    Ok(())
}

#[test]
fn original_fixture_explicit_keep_preserves_the_same_independent_directory() -> anyhow::Result<()> {
    let cleanup = tempfile::tempdir()?;
    let original = OriginalEvidenceDirectory::new(
        tempfile::tempdir_in(cleanup.path())?,
        OriginalEvidenceDirectoryKind::IndependentBBusiness,
    );
    let path = original.path().to_path_buf();
    let before = physical(&path)?;
    assert_eq!(original.keep(), path);
    assert_eq!(physical(&path)?, before);
    Ok(())
}
