use super::*;
use pretty_assertions::assert_eq;
use std::io::Write;

#[test]
fn bootstrap_creates_private_source_and_preserves_existing_bytes()
-> Result<(), Box<dyn std::error::Error>> {
    let temporary = tempfile::tempdir()?;
    let root = temporary
        .path()
        .canonicalize()?
        .join("agent")
        .join("cognitive");
    create_private_directories(&root)?;
    let path = root.join("database.sqlite3");
    prepare_database(&root, &path)?;
    std::fs::write(&path, b"existing source")?;
    prepare_database(&root, &path)?;
    validate_database(&path)?;
    assert_eq!(std::fs::read(&path)?, b"existing source");
    let directory = open_existing_private_state_directory(&root)?;
    let retained = open_frozen_private_state_child(&directory, "database.sqlite3")?;
    assert!(std::fs::OpenOptions::new().write(true).open(&path).is_err());
    drop(retained);
    Ok(())
}

#[test]
fn bootstrap_refuses_existing_hard_link_without_adopting_or_changing_it()
-> Result<(), Box<dyn std::error::Error>> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().canonicalize()?.join("private");
    create_private_directories(&root)?;
    let path = root.join("database.sqlite3");
    prepare_database(&root, &path)?;
    std::fs::write(&path, b"original")?;
    std::fs::hard_link(&path, root.join("alias"))?;
    assert!(prepare_database(&root, &path).is_err());
    assert!(validate_database(&path).is_err());
    assert_eq!(std::fs::read(&path)?, b"original");
    assert_eq!(std::fs::read(root.join("alias"))?, b"original");
    Ok(())
}

#[test]
fn pointer_stage_collision_preserves_the_original_private_file()
-> Result<(), Box<dyn std::error::Error>> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().canonicalize()?.join("private");
    create_private_directories(&root)?;
    let path = root.join(".cognitive-active-v1.tmp-test");
    let mut stage = create_pointer_stage(&root, &path)?;
    stage.write_all(b"original generation\n")?;
    stage.sync_all()?;
    drop(stage);
    assert!(create_pointer_stage(&root, &path).is_err());
    assert_eq!(std::fs::read(&path)?, b"original generation\n");
    Ok(())
}
