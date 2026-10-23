//! Native mechanism experiments only. The fixture contains disposable sentinel
//! bytes, not authoritative state or a substitute for held immutable inputs.
//! Every required operation must execute; unsupported APIs are test failures.

use std::fs;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::process::Command;

use anyhow::Result;
use anyhow::ensure;
use pretty_assertions::assert_eq;
use serde_json::json;
use windows_sys::Win32::Foundation::ERROR_SHARING_VIOLATION;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;

#[path = "private_state_native_probe_support.rs"]
mod support;
use support::FILE_CREATE;
use support::FILE_OPEN;
use support::emit;
use support::identity;
use support::native_flush;
use support::open_relative;
use support::open_relative_directory;
use support::open_root;
use support::record_filesystem;
use support::record_io;
use support::rename_relative;

const WRITE_ACCESS: u32 = FILE_GENERIC_READ | FILE_GENERIC_WRITE | DELETE;

fn relative_rename_body(root_path: &Path) -> Result<()> {
    let root = open_root(root_path)?;
    let original_root = identity(&root)?;
    let mut old = open_relative(
        &root,
        "state.json",
        WRITE_ACCESS,
        FILE_SHARE_READ,
        FILE_CREATE,
    )?;
    old.write_all(b"old state")?;
    old.sync_all()?;
    drop(old);
    let mut staged = open_relative(
        &root,
        "state.next",
        WRITE_ACCESS,
        FILE_SHARE_READ,
        FILE_CREATE,
    )?;
    staged.write_all(b"new state")?;
    staged.sync_all()?;
    let staged_identity = identity(&staged)?;
    rename_relative(&root, &staged, "state.json")?;
    assert_eq!(identity(&staged)?, staged_identity);
    assert_eq!(identity(&root)?, original_root);
    staged.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    staged.read_to_end(&mut bytes)?;
    assert_eq!(bytes, b"new state");
    drop(staged);
    let mut published = open_relative(
        &root,
        "state.json",
        FILE_GENERIC_READ,
        FILE_SHARE_READ,
        FILE_OPEN,
    )?;
    assert_eq!(identity(&published)?, staged_identity);
    bytes.clear();
    published.read_to_end(&mut bytes)?;
    assert_eq!(bytes, b"new state");
    let absent = open_relative(
        &root,
        "state.next",
        FILE_GENERIC_READ,
        FILE_SHARE_READ,
        FILE_OPEN,
    );
    record_io("renamed_source_is_absent", &absent);
    ensure!(absent.is_err_and(|error| error.kind() == std::io::ErrorKind::NotFound));
    // The child's CWD has a colliding leaf. A path-relative implementation
    // would have overwritten it instead of using ObjectAttributes.RootDirectory.
    assert_eq!(fs::read("state.json")?, b"decoy state");
    emit(
        "relative_rename_complete",
        json!({"held_root_and_source_identity_preserved": true}),
    );
    Ok(())
}

#[test]
fn relative_open_and_rename_remain_bound_to_held_root() -> Result<()> {
    const CHILD_ROOT: &str = "HEPTA_PRIVATE_STATE_PROBE_CHILD_ROOT";
    if let Some(root) = std::env::var_os(CHILD_ROOT) {
        return relative_rename_body(Path::new(&root));
    }
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("state");
    let decoy = temporary.path().join("decoy");
    fs::create_dir(&root)?;
    fs::create_dir(&decoy)?;
    fs::write(decoy.join("state.json"), b"decoy state")?;
    // Change only a child process's CWD: no concurrent parent environment or
    // current-directory mutation, and a wrong API cannot touch repository files.
    let output = Command::new(std::env::current_exe()?)
        .args([
            "--exact",
            "private_state_native_probe::relative_open_and_rename_remain_bound_to_held_root",
            "--nocapture",
            "--test-threads=1",
        ])
        .env(CHILD_ROOT, &root)
        .current_dir(&decoy)
        .output()?;
    println!("{}", String::from_utf8_lossy(&output.stdout));
    eprintln!("{}", String::from_utf8_lossy(&output.stderr));
    assert_eq!(fs::read(decoy.join("state.json"))?, b"decoy state");
    ensure!(
        output.status.success(),
        "native relative-open/rename child failed: {}",
        output.status
    );
    ensure!(
        String::from_utf8_lossy(&output.stdout).contains("\"stage\":\"relative_rename_complete\""),
        "exact native child selector did not complete"
    );
    assert_eq!(fs::read(root.join("state.json"))?, b"new state");
    Ok(())
}

#[test]
fn sharing_denies_directory_replacement_and_held_input_mutation() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let path = temporary.path().join("state");
    let moved = temporary.path().join("moved-state");
    fs::create_dir(&path)?;
    let root = open_root(&path)?;
    let root_identity = identity(&root)?;
    let directory_move = fs::rename(&path, &moved);
    record_io("held_directory_rename_attack", &directory_move);
    ensure!(directory_move.is_err(), "held root was replaceable");
    assert_eq!(identity(&root)?, root_identity);
    ensure!(path.is_dir() && !moved.exists());

    let mut writer = open_relative(&root, "input", WRITE_ACCESS, FILE_SHARE_READ, FILE_CREATE)?;
    writer.write_all(b"held input")?;
    writer.sync_all()?;
    drop(writer);
    let mut held = open_relative(
        &root,
        "input",
        FILE_GENERIC_READ,
        FILE_SHARE_READ,
        FILE_OPEN,
    )?;
    let held_identity = identity(&held)?;
    let mutation = OpenOptions::new().write(true).open(path.join("input"));
    record_io("held_input_write_attack", &mutation);
    ensure!(
        mutation.is_err_and(|error| error.raw_os_error() == Some(ERROR_SHARING_VIOLATION as i32)),
        "a writable open must fail due to the held input's share mode"
    );
    let replacement = fs::rename(path.join("input"), path.join("moved-input"));
    record_io("held_input_rename_attack", &replacement);
    ensure!(replacement.is_err(), "held input was replaceable");
    let mut candidate = open_relative(
        &root,
        "replacement.next",
        WRITE_ACCESS,
        FILE_SHARE_READ,
        FILE_CREATE,
    )?;
    candidate.write_all(b"replacement candidate")?;
    candidate.sync_all()?;
    let candidate_identity = identity(&candidate)?;
    let held_target_replace = rename_relative(&root, &candidate, "input");
    record_io(
        "held_destination_relative_rename_attack",
        &held_target_replace,
    );
    ensure!(
        held_target_replace.is_err(),
        "relative rename bypassed the held destination's sharing denial"
    );
    assert_eq!(identity(&candidate)?, candidate_identity);
    assert_eq!(
        fs::read(path.join("replacement.next"))?,
        b"replacement candidate"
    );
    let mut bytes = Vec::new();
    held.read_to_end(&mut bytes)?;
    assert_eq!(bytes, b"held input");
    assert_eq!(identity(&held)?, held_identity);
    drop(held);
    // Positive controls prove this was sharing denial, not an unwritable fixture.
    let mut after_close = OpenOptions::new().write(true).open(path.join("input"))?;
    after_close.write_all(b"after close")?;
    drop(after_close);
    let unheld_target_replace = rename_relative(&root, &candidate, "input");
    record_io(
        "unheld_destination_relative_rename_control",
        &unheld_target_replace,
    );
    unheld_target_replace?;
    assert_eq!(identity(&candidate)?, candidate_identity);
    drop(candidate);
    assert_eq!(fs::read(path.join("input"))?, b"replacement candidate");
    fs::rename(path.join("input"), path.join("moved-input"))?;
    drop(root);
    fs::rename(&path, &moved)?;
    assert_eq!(identity(&open_root(&moved)?)?, root_identity);
    emit(
        "sharing_complete",
        json!({"attacks_denied_while_held": true, "controls_succeeded_after_drop": true}),
    );
    Ok(())
}

fn directory_junction(target: &Path, alias: &Path) -> Result<()> {
    // Reuse the repository's native junction fixture without requiring the
    // symlink privilege; /D disables any cmd AutoRun configuration.
    let output = Command::new("cmd.exe")
        .args(["/D", "/C", "mklink", "/J"])
        .arg(alias)
        .arg(target)
        .output()?;
    ensure!(
        output.status.success(),
        "junction fixture failed: stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    Ok(())
}

#[test]
fn rejects_reparse_paths_hardlinks_and_non_leaf_names() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let state = temporary.path().join("state");
    let outside = temporary.path().join("outside");
    let alias = temporary.path().join("root-alias");
    fs::create_dir(&state)?;
    fs::create_dir(&outside)?;
    fs::create_dir(outside.join("nested"))?;
    fs::write(outside.join("sentinel"), b"unchanged")?;
    directory_junction(&outside, &alias)?;
    let leaf_reparse = open_root(&alias);
    record_io("root_leaf_reparse", &leaf_reparse);
    ensure!(leaf_reparse.is_err(), "root junction was followed");
    let parent_reparse = open_root(&alias.join("nested"));
    record_io("root_ancestor_reparse", &parent_reparse);
    ensure!(parent_reparse.is_err(), "ancestor junction was followed");
    let root = open_root(&state)?;
    directory_junction(&outside, &state.join("child-alias"))?;
    let child_reparse = open_relative_directory(&root, "child-alias");
    record_io("held_root_child_reparse", &child_reparse);
    ensure!(
        child_reparse.is_err(),
        "relative child junction was followed"
    );
    fs::hard_link(outside.join("sentinel"), state.join("linked-input"))?;
    let hardlink = open_relative(
        &root,
        "linked-input",
        FILE_GENERIC_READ,
        FILE_SHARE_READ,
        FILE_OPEN,
    );
    record_io("multiple_links_rejected", &hardlink);
    ensure!(hardlink.is_err_and(|error| error.kind() == std::io::ErrorKind::InvalidInput));
    for invalid_name in [
        "",
        ".",
        "..",
        "../sentinel",
        "child\\sentinel",
        "input:stream",
        "trailing.",
        "trailing ",
    ] {
        let result = open_relative(
            &root,
            invalid_name,
            FILE_GENERIC_READ,
            FILE_SHARE_READ,
            FILE_OPEN,
        );
        record_io("invalid_leaf_rejected", &result);
        ensure!(result.is_err_and(|error| error.kind() == std::io::ErrorKind::InvalidInput));
    }
    // A normal relative open still works; denial is not blanket unsupported.
    let mut normal = open_relative(&root, "normal", WRITE_ACCESS, FILE_SHARE_READ, FILE_CREATE)?;
    normal.write_all(b"normal")?;
    assert_eq!(fs::read(outside.join("sentinel"))?, b"unchanged");
    fs::remove_dir(state.join("child-alias"))?;
    fs::remove_dir(&alias)?;
    emit(
        "reparse_complete",
        json!({"junctions_hardlinks_and_name_aliases_denied": true}),
    );
    Ok(())
}

#[test]
fn file_and_directory_flush_results_are_distinct() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let path = temporary.path().join("state");
    fs::create_dir(&path)?;
    let root = open_root(&path)?;
    let filesystem = record_filesystem(&root)?;
    let mut staged = open_relative(
        &root,
        "flush.next",
        WRITE_ACCESS,
        FILE_SHARE_READ,
        FILE_CREATE,
    )?;
    staged.write_all(b"native flush sentinel")?;
    let file_before = staged.sync_all();
    record_io("file_FlushFileBuffers_before_rename", &file_before);
    let rename = rename_relative(&root, &staged, "flush.json");
    let file_after = staged.sync_all();
    record_io("file_FlushFileBuffers_after_rename", &file_after);
    let directory = root.sync_all();
    record_io("directory_FlushFileBuffers", &directory);
    let native_directory = native_flush(&root);
    record_io("directory_native_normal_flush", &native_directory);
    drop(staged);
    // Record every requested flush before asserting any outcome. A failed
    // directory flush is retained as failure, never replaced by file success.
    ensure!(
        file_before.is_ok() && rename.is_ok() && file_after.is_ok(),
        "file publication primitive failed"
    );
    let read_only = open_relative(
        &root,
        "flush.json",
        FILE_GENERIC_READ,
        FILE_SHARE_READ,
        FILE_OPEN,
    )?;
    let read_only_flush = read_only.sync_all();
    record_io("read_only_file_flush_negative_control", &read_only_flush);
    ensure!(
        read_only_flush.is_err(),
        "read-only flush unexpectedly succeeded; contract needs review"
    );
    ensure!(
        filesystem == "NTFS",
        "probe filesystem is {filesystem}, outside this NTFS experiment"
    );
    ensure!(
        directory.is_ok(),
        "directory FlushFileBuffers failed; private-state backend remains unsupported"
    );
    ensure!(
        native_directory.is_ok(),
        "native directory flush failed; private-state backend remains unsupported"
    );
    emit(
        "flush_complete",
        json!({"file_and_directory_api_calls_succeeded": true, "power_loss_test_performed": false}),
    );
    Ok(())
}
