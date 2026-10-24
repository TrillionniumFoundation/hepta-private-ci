use super::replace_synced_state_stage;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::os::windows::fs::OpenOptionsExt;
use std::path::Path;

const DELETE: u32 = 0x0001_0000;
const GENERIC_READ_WRITE: u32 = 0xc000_0000;
const SHARE_READ_WRITE: u32 = 3;
const BACKUP_SEMANTICS: u32 = 0x0200_0000;

fn root(path: &Path) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .share_mode(SHARE_READ_WRITE)
        .custom_flags(BACKUP_SEMANTICS)
        .open(path)
}

fn stage(path: &Path, contents: &[u8], access: u32) -> io::Result<File> {
    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
        .access_mode(access)
        .share_mode(SHARE_READ_WRITE)
        .create_new(true)
        .open(path)?;
    file.write_all(contents)?;
    Ok(file)
}

#[test]
fn windows_stage_replaces_relative_to_held_directory_using_exact_source() -> io::Result<()> {
    // Non-authoritative fixture: none of these Files qualify a private owner.
    let temp = tempfile::tempdir().expect("temporary directory");
    let directory = root(temp.path())?;
    let source = stage(
        &temp.path().join("authority.next"),
        b"held-stage",
        GENERIC_READ_WRITE | DELETE,
    )?;
    replace_synced_state_stage(&directory, &source, "moved.next").expect("move held stage");
    std::fs::write(temp.path().join("authority.next"), b"name-replacement")
        .expect("replace former source name");
    std::fs::write(temp.path().join("authority.json"), b"previous").expect("existing destination");
    replace_synced_state_stage(&directory, &source, "authority.json").expect("replace by handle");
    assert_eq!(
        std::fs::read(temp.path().join("authority.json")).expect("published bytes"),
        b"held-stage"
    );
    assert_eq!(
        std::fs::read(temp.path().join("authority.next")).expect("unselected replacement"),
        b"name-replacement"
    );
    assert!(!temp.path().join("moved.next").exists());
    Ok(())
}

#[test]
fn windows_stage_without_delete_access_cannot_replace() -> io::Result<()> {
    let temp = tempfile::tempdir().expect("temporary directory");
    let directory = root(temp.path())?;
    let source = stage(
        &temp.path().join("authority.next"),
        b"stage",
        GENERIC_READ_WRITE,
    )?;
    std::fs::write(temp.path().join("authority.json"), b"previous").expect("destination");
    assert!(replace_synced_state_stage(&directory, &source, "authority.json").is_err());
    assert_eq!(
        std::fs::read(temp.path().join("authority.json")).expect("old bytes"),
        b"previous"
    );
    assert_eq!(
        std::fs::read(temp.path().join("authority.next")).expect("stage bytes"),
        b"stage"
    );
    Ok(())
}

#[test]
fn windows_stage_respects_destination_delete_sharing() -> io::Result<()> {
    let temp = tempfile::tempdir().expect("temporary directory");
    let directory = root(temp.path())?;
    let source = stage(
        &temp.path().join("registry.next"),
        b"stage",
        GENERIC_READ_WRITE | DELETE,
    )?;
    std::fs::write(temp.path().join("registry.json"), b"previous").expect("destination");
    let _held_destination = OpenOptions::new()
        .read(true)
        .share_mode(SHARE_READ_WRITE)
        .open(temp.path().join("registry.json"))
        .expect("deny destination delete sharing");
    assert!(replace_synced_state_stage(&directory, &source, "registry.json").is_err());
    assert_eq!(
        std::fs::read(temp.path().join("registry.json")).expect("old bytes"),
        b"previous"
    );
    assert_eq!(
        std::fs::read(temp.path().join("registry.next")).expect("stage bytes"),
        b"stage"
    );
    Ok(())
}

#[test]
fn windows_stage_rejects_escaped_leaf_without_publication() -> io::Result<()> {
    let temp = tempfile::tempdir().expect("temporary directory");
    let directory = root(temp.path())?;
    let source = stage(
        &temp.path().join("registry.next"),
        b"stage",
        GENERIC_READ_WRITE | DELETE,
    )?;
    for leaf in [
        "../outside",
        "nested/file",
        "stream:name",
        "..",
        "trailing.",
    ] {
        assert_eq!(
            replace_synced_state_stage(&directory, &source, leaf)
                .expect_err("invalid leaf")
                .kind(),
            std::io::ErrorKind::InvalidInput
        );
    }
    assert_eq!(
        std::fs::read(temp.path().join("registry.next")).expect("stage bytes"),
        b"stage"
    );
    Ok(())
}
