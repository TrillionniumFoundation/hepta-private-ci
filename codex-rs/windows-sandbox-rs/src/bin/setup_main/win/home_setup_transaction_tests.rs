use super::super::sandbox_users::commit_setup_marker;
use super::super::sandbox_users::prepare_setup_marker;
use super::*;
use anyhow::Context;
use codex_windows_sandbox::to_wide;
use pretty_assertions::assert_eq;
use rand::RngCore;
use rand::SeedableRng;
use rand::rngs::SmallRng;
use std::fs;
use std::os::windows::io::FromRawHandle;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use tempfile::TempDir;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::System::Threading::CreateEventW;
use windows_sys::Win32::System::Threading::EVENT_ALL_ACCESS;
use windows_sys::Win32::System::Threading::OpenEventW;
use windows_sys::Win32::System::Threading::SetEvent;
use windows_sys::Win32::System::Threading::WaitForSingleObject;
use windows_sys::Win32::System::WindowsProgramming::GetUserNameW;

const WORKER_INPUT: &str = "HIA_HOME_SETUP_TEST_INPUT";

struct Event {
    handle: OwnedHandle,
    name: String,
}

impl Event {
    fn create(label: &str) -> Result<Self> {
        let nonce = SmallRng::from_entropy().next_u64();
        let name = format!("Local\\HiaHomeSetup.{label}.{nonce:016x}");
        let wide = to_wide(&name);
        let handle = unsafe {
            CreateEventW(
                std::ptr::null(),
                /*bmanualreset*/ 1,
                /*binitialstate*/ 0,
                wide.as_ptr(),
            )
        };
        ensure!(handle != 0, "create owned test event: {}", unsafe {
            GetLastError()
        });
        Ok(Self {
            handle: unsafe { OwnedHandle::from_raw_handle(handle as *mut c_void) },
            name,
        })
    }

    fn wait(&self, milliseconds: u32) -> u32 {
        unsafe { WaitForSingleObject(self.handle.as_raw_handle() as HANDLE, milliseconds) }
    }
}

struct Worker(Option<Child>);

impl Worker {
    fn start(home: &Path, started: &Event, acquired: &Event) -> Result<Self> {
        let input = serde_json::to_string(&(home, &started.name, &acquired.name))?;
        Ok(Self(Some(
            Command::new(std::env::current_exe()?)
                .args([
                    "--ignored",
                    "--exact",
                    "win::home_setup_transaction::tests::setup_marker_worker",
                    "--nocapture",
                ])
                .env(WORKER_INPUT, input)
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()?,
        )))
    }

    fn finish(mut self) -> Result<()> {
        let child = self.0.take().context("worker was already consumed")?;
        let pid = child.id();
        let output = child.wait_with_output()?;
        println!(
            "HIA_HOME_SETUP_WORKER pid={pid} exit={:?}\n{}\n{}",
            output.status.code(),
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr),
        );
        ensure!(output.status.success(), "actual marker worker failed");
        ensure!(
            String::from_utf8_lossy(&output.stdout).contains("1 passed; 0 failed; 0 ignored"),
            "marker worker did not execute its exact control"
        );
        Ok(())
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        if let Some(child) = self.0.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn real_user() -> Result<String> {
    let mut name = [0u16; 257];
    let mut length = name.len() as u32;
    ensure!(
        unsafe { GetUserNameW(name.as_mut_ptr(), &mut length) } != 0,
        "read actual setup test user"
    );
    Ok(String::from_utf16(&name[..length as usize - 1])?)
}

fn signal(name: &str) -> Result<()> {
    let wide = to_wide(name);
    let raw = unsafe {
        OpenEventW(EVENT_ALL_ACCESS, /*binherithandle*/ 0, wide.as_ptr())
    };
    ensure!(raw != 0, "open owned parent event");
    let event = unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) };
    ensure!(
        unsafe { SetEvent(event.as_raw_handle() as HANDLE) } != 0,
        "signal owned parent event"
    );
    Ok(())
}

#[test]
#[ignore = "This real process worker is explicitly launched and checked by both home transaction controls."]
fn setup_marker_worker() -> Result<()> {
    let input = std::env::var(WORKER_INPUT).context("worker requires its parent input")?;
    let (home, started, acquired): (PathBuf, String, String) = serde_json::from_str(&input)?;
    signal(&started)?;
    let _transaction = HomeSetupGuard::acquire(&home)?;
    prepare_setup_marker(&home, &real_user()?)?;
    signal(&acquired)?;
    commit_setup_marker(
        &home,
        "worker-offline",
        "worker-online",
        &[],
        /*allow_local_binding*/ false,
    )?;
    Ok(())
}

#[test]
fn same_physical_home_waits_through_marker_commit_across_processes() -> Result<()> {
    let root = TempDir::new()?;
    let home = root.path().join("same-home");
    fs::create_dir_all(sandbox_dir(&home))?;
    let transaction = HomeSetupGuard::acquire(&home)?;
    prepare_setup_marker(&home, &real_user()?)?;
    let alias = fs::canonicalize(&home)?;
    let started = Event::create("same-started")?;
    let acquired = Event::create("same-acquired")?;
    let worker = Worker::start(&alias, &started, &acquired)?;
    assert_eq!(started.wait(5000), WAIT_OBJECT_0);
    // The child has entered the control; a bounded wait checks that it cannot
    // publish while the first physical-home transaction is still held.
    assert_eq!(acquired.wait(100), WAIT_TIMEOUT);
    assert_eq!(fs::read(sandbox_dir(&home).join("setup_marker.json"))?, b"");
    commit_setup_marker(
        &home,
        "parent-offline",
        "parent-online",
        &[],
        /*allow_local_binding*/ false,
    )?;
    drop(transaction);
    assert_eq!(acquired.wait(5000), WAIT_OBJECT_0);
    worker.finish()?;
    let marker: serde_json::Value =
        serde_json::from_slice(&fs::read(sandbox_dir(&home).join("setup_marker.json"))?)?;
    assert_eq!(marker["offline_username"], "worker-offline");
    assert_eq!(marker["online_username"], "worker-online");
    println!(
        "HIA_HOME_SETUP_CONTROL same_physical_home: PASS; real_worker=true; protected_create_new=true"
    );
    Ok(())
}

#[test]
fn different_home_marker_transaction_runs_while_first_home_is_held() -> Result<()> {
    let root = TempDir::new()?;
    let first = root.path().join("first");
    let second = root.path().join("second");
    fs::create_dir_all(sandbox_dir(&first))?;
    fs::create_dir_all(sandbox_dir(&second))?;
    let _first = HomeSetupGuard::acquire(&first)?;
    let started = Event::create("other-started")?;
    let acquired = Event::create("other-acquired")?;
    let worker = Worker::start(&second, &started, &acquired)?;
    assert_eq!(started.wait(5000), WAIT_OBJECT_0);
    assert_eq!(acquired.wait(5000), WAIT_OBJECT_0);
    worker.finish()?;
    assert!(!sandbox_dir(&first).join("setup_marker.json").exists());
    println!("HIA_HOME_SETUP_CONTROL different_homes: PASS; first_lock_still_held=true");
    Ok(())
}

#[test]
fn transaction_holds_the_existing_leaf_and_never_creates_missing_home() -> Result<()> {
    let root = TempDir::new()?;
    let home = root.path().join("retained");
    fs::create_dir_all(sandbox_dir(&home))?;
    let transaction = HomeSetupGuard::acquire(&home)?;
    assert!(fs::rename(sandbox_dir(&home), home.join("replaced")).is_err());
    assert!(sandbox_dir(&home).is_dir());
    drop(transaction);
    fs::rename(sandbox_dir(&home), home.join("replaced"))?;
    assert!(HomeSetupGuard::acquire(&home).is_err());
    assert!(!sandbox_dir(&home).exists());
    Ok(())
}
