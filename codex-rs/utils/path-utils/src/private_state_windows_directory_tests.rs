//! Deterministic native regressions for the directory acquisition boundary.

use std::cell::Cell;
use std::cell::RefCell;
use std::fs;
use std::fs::File;
use std::io;
use std::path::Path;
use std::process::Command;
use std::rc::Rc;

use pretty_assertions::assert_eq;
use windows_sys::Win32::Storage::FileSystem::CreateDirectoryW;

use super::super::final_path;
use super::super::open_private_state_directory;
use super::super::wide_path;
use super::super::with_private_security;

type BeforeOpenHook = Box<dyn FnOnce() -> io::Result<()>>;
thread_local! {
    static BEFORE_OPEN: RefCell<Option<BeforeOpenHook>> = const { RefCell::new(None) };
}

pub(super) fn before_open() -> io::Result<()> {
    // Remove it before invocation, so setup failures or nested opens cannot
    // consume it twice or leave a RefCell borrowed across filesystem operations.
    let hook = BEFORE_OPEN.with(|slot| slot.borrow_mut().take());
    match hook {
        Some(hook) => hook(),
        None => Ok(()),
    }
}

struct HookGuard;

impl HookGuard {
    fn install(hook: impl FnOnce() -> io::Result<()> + 'static) -> Self {
        let previous = BEFORE_OPEN.with(|slot| slot.borrow_mut().replace(Box::new(hook)));
        assert!(previous.is_none(), "only one acquisition hook per thread");
        Self
    }
}

impl Drop for HookGuard {
    fn drop(&mut self) {
        BEFORE_OPEN.with(|slot| slot.borrow_mut().take());
    }
}

fn junction(target: &Path, alias: &Path) -> io::Result<()> {
    // Directory junctions require no symlink privilege. Failure is a fixture
    // failure, never an optional skip or evidence that acquisition was denied.
    let output = Command::new("cmd")
        .args(["/C", "mklink", "/J"])
        .arg(alias)
        .arg(target)
        .output()?;
    if !output.status.success() {
        return Err(io::Error::other(format!(
            "mklink /J failed: stdout={} stderr={}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        )));
    }
    Ok(())
}

fn private_directory_fixture(path: &Path) -> io::Result<File> {
    let wide = wide_path(path)?;
    with_private_security(|security| {
        if unsafe { CreateDirectoryW(wide.as_ptr(), security) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    })?;
    open_private_state_directory(path)
}

#[test]
fn rejects_junction_before_creating_private_leaf() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let outside = temporary.path().join("outside");
    let alias = temporary.path().join("alias");
    fs::create_dir(&outside)?;
    junction(&outside, &alias)?;
    let outside_leaf = outside.join("registry");
    assert!(!outside_leaf.try_exists()?);

    let result = open_private_state_directory(&alias.join("registry"));
    let denied = result.is_err();
    drop(result);
    let created = outside_leaf.try_exists()?;
    fs::remove_dir(&alias)?;
    eprintln!("PRIVATE_STATE_ACQUISITION creation denied={denied} created={created}");
    assert!(denied, "a reparse ancestor must be rejected");
    assert!(
        !created,
        "rejection must not first create the redirected leaf"
    );
    Ok(())
}

#[test]
fn rejects_ancestor_substitution_at_retained_open() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let ancestor = temporary.path().join("ancestor");
    let parked = temporary.path().join("parked");
    let outside = temporary.path().join("outside");
    fs::create_dir(&ancestor)?;
    fs::create_dir(&outside)?;
    let root = ancestor.join("registry");
    let outside_root = outside.join("registry");
    // Both leaves have the actual private current-user descriptor. A redirected
    // open therefore cannot be rejected merely because our fixture has bad ACLs.
    drop(private_directory_fixture(&root)?);
    let outside_handle = private_directory_fixture(&outside_root)?;
    let expected_redirect = final_path(&outside_handle)?;
    drop(outside_handle);

    let substituted = Rc::new(Cell::new(false));
    let observed = Rc::clone(&substituted);
    let hook_ancestor = ancestor.clone();
    let hook = HookGuard::install(move || {
        fs::rename(&hook_ancestor, &parked)?;
        junction(&outside, &hook_ancestor)?;
        observed.set(true);
        Ok(())
    });
    let result = open_private_state_directory(&root);
    drop(hook);
    let denied = result.is_err();
    let redirected = match &result {
        Ok(handle) => final_path(handle)? == expected_redirect,
        Err(_) => false,
    };
    drop(result);
    assert!(
        substituted.get(),
        "the real ancestor substitution must complete"
    );
    fs::remove_dir(&ancestor)?;
    eprintln!(
        "PRIVATE_STATE_ACQUISITION substitution swapped=true denied={denied} redirected={redirected}"
    );
    assert_eq!((denied, redirected), (true, false));
    Ok(())
}

#[test]
fn create_new_directory_is_private_and_keeps_its_pin() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("new-registry");
    let directory = super::super::create_new_private_state_directory(&root)?;
    drop(super::super::open_existing_private_state_directory(&root)?);
    let moved = temporary.path().join("moved-registry");
    assert!(fs::rename(&root, &moved).is_err());
    drop(directory);
    fs::rename(&root, &moved)?;
    drop(super::super::open_existing_private_state_directory(&moved)?);
    Ok(())
}

#[test]
fn create_new_directory_rejects_existing_directory_and_file() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("existing-registry");
    drop(super::super::create_new_private_state_directory(&root)?);
    fs::write(root.join("marker"), b"original directory")?;
    let error = super::super::create_new_private_state_directory(&root)
        .expect_err("an occupied directory must not be adopted");
    assert_eq!(error.kind(), io::ErrorKind::AlreadyExists);
    assert_eq!(fs::read(root.join("marker"))?, b"original directory");

    let file = temporary.path().join("existing-file");
    fs::write(&file, b"original file")?;
    let error = super::super::create_new_private_state_directory(&file)
        .expect_err("an occupied file must not be replaced");
    assert_eq!(error.kind(), io::ErrorKind::AlreadyExists);
    assert_eq!(fs::read(&file)?, b"original file");
    Ok(())
}

#[test]
fn create_new_directory_rejects_a_leaf_occupied_at_acquisition() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("raced-registry");
    let occupied = root.clone();
    let hook = HookGuard::install(move || {
        fs::create_dir(&occupied)?;
        fs::write(occupied.join("marker"), b"occupied before atomic creation")
    });
    let result = super::super::create_new_private_state_directory(&root);
    drop(hook);
    let error = result.expect_err("create-new must not reopen a competing directory");
    assert_eq!(error.kind(), io::ErrorKind::AlreadyExists);
    assert_eq!(
        fs::read(root.join("marker"))?,
        b"occupied before atomic creation"
    );
    Ok(())
}
