use std::io::ErrorKind;
use std::os::unix::fs::symlink;
use std::path::Path;

use anyhow::Result;
use pretty_assertions::assert_eq;

use super::loader_path;
use super::readonly_from_mountinfo;

fn mount_evidence(root: &Path, writable: &Path) -> String {
    let root = root
        .display()
        .to_string()
        .replace('\\', "\\134")
        .replace(' ', "\\040")
        .replace('\t', "\\011")
        .replace('\n', "\\012");
    let writable = writable
        .display()
        .to_string()
        .replace('\\', "\\134")
        .replace(' ', "\\040")
        .replace('\t', "\\011")
        .replace('\n', "\\012");
    format!("1 0 0:1 / {root} ro - none none ro\n2 1 0:2 / {writable} rw - none none rw\n")
}

#[test]
fn readonly_rejects_parent_path_to_writable_mount() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().canonicalize()?;
    let immutable = root.join("usr");
    let writable = root.join("writable");
    std::fs::create_dir(&immutable)?;
    std::fs::create_dir(&writable)?;
    let path = immutable.join("../writable");
    assert_eq!(path.canonicalize()?, writable);
    let mounts = mount_evidence(&root, &writable);
    readonly_from_mountinfo(&immutable, &mounts)?;
    let Err(error) = readonly_from_mountinfo(&path, &mounts) else {
        panic!("parent traversal concealed a writable mount");
    };
    assert_eq!(
        error.to_string(),
        format!(
            "qualification authority must be mounted read-only: {}",
            writable.display()
        )
    );
    Ok(())
}

#[test]
fn readonly_rejects_symlink_to_writable_mount() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().canonicalize()?;
    let immutable = root.join("usr");
    let writable = root.join("writable");
    std::fs::create_dir(&immutable)?;
    std::fs::create_dir(&writable)?;
    let path = immutable.join("alias");
    symlink(&writable, &path)?;
    assert_eq!(path.canonicalize()?, writable);
    let mounts = mount_evidence(&root, &writable);
    readonly_from_mountinfo(&immutable, &mounts)?;
    let Err(error) = readonly_from_mountinfo(&path, &mounts) else {
        panic!("symlink concealed a writable mount");
    };
    assert_eq!(
        error.to_string(),
        format!(
            "qualification authority must be mounted read-only: {}",
            writable.display()
        )
    );
    Ok(())
}

#[test]
fn loader_path_rejects_escaped_or_unresolved_targets() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().canonicalize()?;
    let immutable = root.join("usr");
    let writable = root.join("writable");
    std::fs::create_dir(&immutable)?;
    std::fs::create_dir(&writable)?;
    symlink(&writable, immutable.join("alias"))?;
    symlink(writable.join("missing"), immutable.join("dangling"))?;
    let roots = [immutable.as_path()];
    let Err(error) = loader_path(&immutable.join("../writable"), &roots) else {
        panic!("parent traversal was accepted as a loader path");
    };
    assert_eq!(
        error.to_string(),
        "nextest loader path must be absolute and must not traverse parents"
    );
    for path in [immutable.join("alias"), immutable.join("alias/not-created")] {
        let Err(error) = loader_path(&path, &roots) else {
            panic!("escaped loader path was accepted: {}", path.display());
        };
        assert_eq!(
            error.to_string(),
            "nextest loader path resolved outside frozen executable/sysroot authority"
        );
    }
    let Err(error) = loader_path(&immutable.join("dangling"), &roots) else {
        panic!("dangling symlink was accepted as an absent loader directory");
    };
    assert_eq!(
        error
            .downcast_ref::<std::io::Error>()
            .map(std::io::Error::kind),
        Some(ErrorKind::NotFound)
    );
    assert!(!writable.join("not-created").exists());
    assert!(!writable.join("missing").exists());
    Ok(())
}

#[test]
fn loader_path_preserves_allowed_alias_and_absent_directories() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().canonicalize()?;
    let immutable = root.join("usr");
    let library = immutable.join("lib");
    let alias = root.join("lib");
    let frozen = root.join("frozen-test");
    let writable = root.join("writable");
    std::fs::create_dir_all(&library)?;
    std::fs::create_dir(&frozen)?;
    std::fs::create_dir(&writable)?;
    symlink(&library, &alias)?;
    let roots = [frozen.as_path(), immutable.as_path(), alias.as_path()];
    let mounts = mount_evidence(&root, &writable);
    for path in [
        library.clone(),
        alias.clone(),
        alias.join("not-created"),
        frozen.join("not-created/deps"),
    ] {
        let checked = loader_path(&path, &roots)?;
        readonly_from_mountinfo(&checked, &mounts)?;
    }
    assert_eq!(std::fs::read_link(alias)?, library);
    assert!(!frozen.join("not-created").exists());
    Ok(())
}

#[test]
fn readonly_decodes_all_mount_path_escapes_without_double_decoding() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().canonicalize()?;
    let writable = root.join("writable with\tline\nliteral\\040");
    std::fs::create_dir(&writable)?;
    assert_eq!(writable.canonicalize()?, writable);
    let mounts = mount_evidence(&root, &writable);
    readonly_from_mountinfo(&root, &mounts)?;
    let Err(error) = readonly_from_mountinfo(&writable, &mounts) else {
        panic!("escaped mount name concealed a writable submount");
    };
    assert_eq!(
        error.to_string(),
        format!(
            "qualification authority must be mounted read-only: {}",
            writable.display()
        )
    );
    Ok(())
}
