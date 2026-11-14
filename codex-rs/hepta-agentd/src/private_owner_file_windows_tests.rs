use std::io::Write;

use anyhow::Result;
use codex_utils_path::windows_private_fs::PrivateDirectory;
use pretty_assertions::assert_eq;

use super::read;

#[test]
fn owner_configuration_reads_are_bounded_and_non_mutating() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let home = temp.path().join("home");
    let directory = PrivateDirectory::open_or_create(&home)?;
    let bytes = b"owner configuration";
    let mut file = directory.create_new("trust.json")?;
    file.write_all(bytes)?;
    file.sync_all()?;
    directory.sync_all()?;
    let limit = u64::try_from(bytes.len())?;
    assert_eq!(read(&home.join("trust.json"), &home, limit)?, bytes);
    assert!(read(&home.join("trust.json"), &home, limit - 1).is_err());
    assert_eq!(std::fs::read(home.join("trust.json"))?, bytes);
    Ok(())
}

#[test]
fn trust_file_cannot_escape_the_owner_home_or_share_a_hard_link() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let home = temp.path().join("home");
    let sibling = temp.path().join("sibling");
    let directory = PrivateDirectory::open_or_create(&home)?;
    let other = PrivateDirectory::open_or_create(&sibling)?;
    let mut file = directory.create_new("trust.json")?;
    file.write_all(b"owner")?;
    file.sync_all()?;
    other.create_new("trust.json")?.sync_all()?;
    assert!(read(&sibling.join("trust.json"), &home, 16_384).is_err());
    std::fs::hard_link(home.join("trust.json"), home.join("alias.json"))?;
    assert!(read(&home.join("trust.json"), &home, 16_384).is_err());
    assert_eq!(std::fs::read(home.join("trust.json"))?, b"owner");
    Ok(())
}
