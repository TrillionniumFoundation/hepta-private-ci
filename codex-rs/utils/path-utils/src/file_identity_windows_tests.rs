use super::*;
use std::fs;

#[test]
fn independently_opened_handles_to_one_file_match() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("same-file");
    fs::write(&path, b"retained bytes")?;
    let left = File::open(&path)?;
    let right = File::open(&path)?;
    assert!(same_file_handles(&left, &right)?);
    assert!(same_file_handles(&right, &left)?);
    Ok(())
}

#[test]
fn equal_contents_and_lengths_do_not_make_different_files_match() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let left_path = directory.path().join("left");
    let right_path = directory.path().join("right");
    fs::write(&left_path, b"same contents")?;
    fs::write(&right_path, b"same contents")?;
    let left = File::open(left_path)?;
    let right = File::open(right_path)?;
    assert!(!same_file_handles(&left, &right)?);
    assert!(!same_file_handles(&right, &left)?);
    Ok(())
}

#[test]
fn cloned_handle_preserves_identity() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("cloned");
    fs::write(&path, b"retained bytes")?;
    let original = File::open(path)?;
    let duplicate = original.try_clone()?;
    assert!(same_file_handles(&original, &duplicate)?);
    Ok(())
}

#[test]
fn retained_handle_distinguishes_a_same_size_path_replacement() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("current");
    let retired_path = directory.path().join("retired");
    fs::write(&path, b"same contents")?;
    let original = File::open(&path)?;
    fs::rename(&path, &retired_path)?;
    fs::write(&path, b"same contents")?;
    let replacement = File::open(&path)?;
    let retired = File::open(&retired_path)?;
    assert!(!same_file_handles(&original, &replacement)?);
    assert!(same_file_handles(&original, &retired)?);
    Ok(())
}

#[test]
fn an_unavailable_identity_is_an_error_on_either_side() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("regular");
    fs::write(&path, b"regular bytes")?;
    let regular = File::open(path)?;
    let device = File::open(r"\\.\NUL")?;
    assert!(same_file_handles(&device, &regular).is_err());
    assert!(same_file_handles(&regular, &device).is_err());
    Ok(())
}
