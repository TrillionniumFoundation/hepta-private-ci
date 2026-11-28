use super::HomeSetupGuard;
use super::private_identity_security;
use super::retained_home_key;
use crate::sandbox_dir;
use crate::setup;
use crate::setup_error::SetupErrorCode;
use crate::setup_error::extract_failure;
use crate::to_wide;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use pretty_assertions::assert_eq;
use rand::RngCore;
use rand::SeedableRng;
use rand::rngs::SmallRng;
use std::ffi::c_void;
use std::fs;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use tempfile::TempDir;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::System::Threading::CreateEventW;
use windows_sys::Win32::System::Threading::CreateMutexW;
use windows_sys::Win32::System::Threading::EVENT_ALL_ACCESS;
use windows_sys::Win32::System::Threading::OpenEventW;
use windows_sys::Win32::System::Threading::SetEvent;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

const WORKER_INPUT: &str = "HIA_HOME_READINESS_TEST_INPUT";

struct Event {
    handle: OwnedHandle,
    name: String,
}

impl Event {
    fn create(label: &str) -> Result<Self> {
        let nonce = SmallRng::from_entropy().next_u64();
        let name = format!("Local\\HiaHomeReadiness.{label}.{nonce:016x}");
        let raw = unsafe { CreateEventW(std::ptr::null(), 1, 0, to_wide(&name).as_ptr()) };
        ensure!(raw != 0, "create owned readiness event");
        Ok(Self {
            handle: unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) },
            name,
        })
    }
    fn wait(&self, milliseconds: u32) -> u32 {
        unsafe { WaitForSingleObject(self.handle.as_raw_handle() as HANDLE, milliseconds) }
    }
}
fn signal(name: &str) -> Result<()> {
    let raw = unsafe { OpenEventW(EVENT_ALL_ACCESS, 0, to_wide(name).as_ptr()) };
    ensure!(raw != 0, "open parent readiness event");
    let handle = unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) };
    ensure!(
        unsafe { SetEvent(handle.as_raw_handle() as HANDLE) } != 0,
        "signal readiness parent"
    );
    Ok(())
}

struct Worker(Option<Child>);
impl Worker {
    fn start(home: &Path, started: &Event, finished: &Event, expect_ready: bool) -> Result<Self> {
        let input = serde_json::to_string(&(home, &started.name, &finished.name, expect_ready))?;
        Ok(Self(Some(
            Command::new(std::env::current_exe()?)
                .args([
                    "--ignored",
                    "--exact",
                    "setup_home::tests::readiness_worker",
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
        let child = self.0.take().context("readiness worker consumed")?;
        let pid = child.id();
        let output = child.wait_with_output()?;
        println!(
            "HIA_HOME_READINESS_WORKER pid={pid} exit={:?}\n{}\n{}",
            output.status.code(),
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        ensure!(output.status.success(), "real readiness worker failed");
        ensure!(
            String::from_utf8_lossy(&output.stdout).contains("1 passed; 0 failed; 0 ignored"),
            "real worker did not execute its exact readiness control"
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

fn write_ready(home: &Path) -> Result<()> {
    let marker = setup::SetupMarker {
        version: setup::SETUP_VERSION,
        offline_username: "readiness-offline".into(),
        online_username: "readiness-online".into(),
        created_at: None,
        proxy_ports: Vec::new(),
        allow_local_binding: false,
    };
    let users = setup::SandboxUsersFile {
        version: setup::SETUP_VERSION,
        offline: setup::SandboxUserRecord {
            username: "readiness-offline".into(),
            password: String::new(),
        },
        online: setup::SandboxUserRecord {
            username: "readiness-online".into(),
            password: String::new(),
        },
    };
    let users_path = setup::sandbox_users_path(home);
    fs::create_dir_all(users_path.parent().context("users parent")?)?;
    fs::write(users_path, serde_json::to_vec(&users)?)?;
    fs::write(setup::setup_marker_path(home), serde_json::to_vec(&marker)?)?;
    Ok(())
}

#[test]
#[ignore = "A real separate process explicitly invoked and checked by the readiness controls."]
fn readiness_worker() -> Result<()> {
    let (home, started, finished, expect_ready): (PathBuf, String, String, bool) =
        serde_json::from_str(&std::env::var(WORKER_INPUT).context("worker parent input")?)?;
    signal(&started)?;
    let result = setup::verify_setup_completed(&home);
    if expect_ready {
        result?;
    } else {
        let error = result.expect_err("the current failed generation must stay incomplete");
        assert_eq!(
            extract_failure(&error).map(|failure| failure.code),
            Some(SetupErrorCode::OrchestratorHelperIncomplete)
        );
    }
    signal(&finished)?;
    Ok(())
}

#[test]
fn current_ready_read_waits_for_another_full_transaction() -> Result<()> {
    let root = TempDir::new()?;
    fs::create_dir_all(sandbox_dir(root.path()))?;
    write_ready(root.path())?;
    let transaction = HomeSetupGuard::acquire_for_current_user(root.path())?;
    // The original writer invalidates readiness before provisioning. Its
    // original protected CREATE_NEW behavior has separate unchanged controls.
    fs::write(setup::setup_marker_path(root.path()), b"")?;
    let alias = fs::canonicalize(root.path())?;
    let started = Event::create("ready-started")?;
    let finished = Event::create("ready-finished")?;
    let worker = Worker::start(&alias, &started, &finished, true)?;
    assert_eq!(started.wait(5000), WAIT_OBJECT_0);
    assert_eq!(finished.wait(100), WAIT_TIMEOUT);
    write_ready(root.path())?;
    drop(transaction);
    assert_eq!(finished.wait(5000), WAIT_OBJECT_0);
    worker.finish()?;
    println!("HIA_HOME_READINESS_CONTROL current_complete_after_writer: PASS");
    Ok(())
}

#[test]
fn failed_later_transaction_cannot_borrow_previous_completion() -> Result<()> {
    let root = TempDir::new()?;
    fs::create_dir_all(sandbox_dir(root.path()))?;
    write_ready(root.path())?;
    setup::verify_setup_completed(root.path())?;
    let transaction = HomeSetupGuard::acquire_for_current_user(root.path())?;
    fs::write(setup::setup_marker_path(root.path()), b"")?;
    let started = Event::create("failed-started")?;
    let finished = Event::create("failed-finished")?;
    let worker = Worker::start(root.path(), &started, &finished, false)?;
    assert_eq!(started.wait(5000), WAIT_OBJECT_0);
    assert_eq!(finished.wait(100), WAIT_TIMEOUT);
    drop(transaction);
    assert_eq!(finished.wait(5000), WAIT_OBJECT_0);
    worker.finish()?;
    assert_eq!(fs::read(setup::setup_marker_path(root.path()))?, b"");
    println!("HIA_HOME_READINESS_CONTROL failed_current_generation_rejected: PASS");
    Ok(())
}

#[test]
fn different_home_readiness_does_not_wait_for_unrelated_full_setup() -> Result<()> {
    let root = TempDir::new()?;
    let first = root.path().join("first");
    let second = root.path().join("second");
    fs::create_dir_all(sandbox_dir(&first))?;
    fs::create_dir_all(sandbox_dir(&second))?;
    write_ready(&second)?;
    let _transaction = HomeSetupGuard::acquire_for_current_user(&first)?;
    let started = Event::create("other-started")?;
    let finished = Event::create("other-finished")?;
    let worker = Worker::start(&second, &started, &finished, true)?;
    assert_eq!(started.wait(5000), WAIT_OBJECT_0);
    assert_eq!(finished.wait(5000), WAIT_OBJECT_0);
    worker.finish()?;
    println!("HIA_HOME_READINESS_CONTROL unrelated_home_independent: PASS");
    Ok(())
}

#[test]
fn current_marker_with_incomplete_users_still_fails_original_readiness() -> Result<()> {
    let root = TempDir::new()?;
    fs::create_dir_all(sandbox_dir(root.path()))?;
    write_ready(root.path())?;
    fs::write(setup::sandbox_users_path(root.path()), b"")?;
    let error =
        setup::verify_setup_completed(root.path()).expect_err("incomplete actual credentials");
    assert_eq!(
        extract_failure(&error).map(|failure| failure.code),
        Some(SetupErrorCode::OrchestratorHelperIncomplete)
    );
    Ok(())
}

#[test]
fn a_wide_preexisting_home_mutex_is_rejected_without_waiting() -> Result<()> {
    let root = TempDir::new()?;
    fs::create_dir_all(sandbox_dir(root.path()))?;
    let (_directory, key) = retained_home_key(root.path())?;
    let mut raw_descriptor = std::ptr::null_mut();
    ensure!(
        unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                to_wide("D:P(A;;GA;;;WD)").as_ptr(),
                SDDL_REVISION_1,
                &mut raw_descriptor,
                std::ptr::null_mut(),
            )
        } != 0,
        "create deliberately wide test descriptor"
    );
    let descriptor = private_identity_security::Descriptor(raw_descriptor);
    let attributes = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: descriptor.0,
        bInheritHandle: 0,
    };
    let name = to_wide(format!("Global\\CodexSandbox.Identity.v1.{key}"));
    let raw = unsafe { CreateMutexW(&attributes, 0, name.as_ptr()) };
    ensure!(raw != 0, "create owned deliberately unsafe mutex");
    let _mutex = unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) };
    assert!(HomeSetupGuard::acquire_for_current_user(root.path()).is_err());
    Ok(())
}

#[test]
fn existing_admin_only_transaction_cannot_create_a_parallel_user_lock() -> Result<()> {
    let root = TempDir::new()?;
    fs::create_dir_all(sandbox_dir(root.path()))?;
    let sid = private_identity_security::current_user_sid()?;
    ensure!(
        sid != private_identity_security::SYSTEM_SID
            && sid != private_identity_security::ADMINISTRATORS_SID,
        "control requires an actual user token, not SYSTEM or a group identity"
    );
    let _old = HomeSetupGuard::acquire(root.path())?;
    assert!(HomeSetupGuard::acquire_for_current_user(root.path()).is_err());
    Ok(())
}

#[test]
#[ignore = "Explicit token-identity workers are launched and checked by the parent control."]
fn setup_account_worker() -> Result<()> {
    let home = PathBuf::from(std::env::var("HIA_ACCOUNT_HOME").context("owned account home")?);
    let expected = std::env::var("HIA_ACCOUNT_SID").context("parent actual process SID")?;
    assert_eq!(private_identity_security::current_user_sid()?, expected);
    let account = super::current_setup_account()?;
    let actual = crate::string_from_sid_bytes(&crate::winutil::resolve_sid(&account)?)
        .map_err(anyhow::Error::msg)?;
    assert_eq!(actual, expected);
    assert_ne!(account, "Administrators");
    assert_ne!(account, "HiaMissingUnrelatedAccount");
    let _writer = HomeSetupGuard::acquire_for_user(&home, &actual)?;
    // The same authority crosses the production parent completion boundary.
    setup::verify_setup_completed_for_user(&home, &actual)?;
    setup::verify_setup_completed(&home)?;
    signal(&std::env::var("HIA_ACCOUNT_DONE").context("owned completion event")?)?;
    println!("HIA_SETUP_ACCOUNT_WORKER actual_token_authority: PASS");
    Ok(())
}

#[test]
fn setup_account_ignores_absent_and_unrelated_username_environment() -> Result<()> {
    let root = TempDir::new()?;
    let expected = private_identity_security::current_user_sid()?;
    ensure!(
        expected != private_identity_security::SYSTEM_SID
            && expected != private_identity_security::ADMINISTRATORS_SID,
        "control requires the actual CI user token"
    );
    for (index, username) in [
        None,
        Some("Administrators"),
        Some("HiaMissingUnrelatedAccount"),
    ]
    .into_iter()
    .enumerate()
    {
        let home = root.path().join(format!("case-{index}"));
        fs::create_dir_all(sandbox_dir(&home))?;
        write_ready(&home)?;
        let mut command = Command::new(std::env::current_exe()?);
        command
            .args([
                "--ignored",
                "--exact",
                "setup_home::tests::setup_account_worker",
                "--nocapture",
            ])
            .env("HIA_ACCOUNT_HOME", &home)
            .env("HIA_ACCOUNT_SID", &expected)
            .env_remove("USERNAME")
            .stdin(Stdio::null());
        if let Some(value) = username {
            command.env("USERNAME", value);
        }
        let finished = Event::create("account-completed")?;
        command
            .env("HIA_ACCOUNT_DONE", &finished.name)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let worker = Worker(Some(command.spawn()?));
        assert_eq!(finished.wait(5000), WAIT_OBJECT_0);
        worker.finish()?;
    }
    println!("HIA_HOME_READINESS_CONTROL token_account_ignores_environment: PASS; workers=3");
    Ok(())
}

#[test]
fn explicit_target_completion_retains_the_writer_authority() -> Result<()> {
    let root = TempDir::new()?;
    fs::create_dir_all(sandbox_dir(root.path()))?;
    write_ready(root.path())?;
    let actual = private_identity_security::current_user_sid()?;
    ensure!(
        actual != private_identity_security::SYSTEM_SID
            && actual != private_identity_security::ADMINISTRATORS_SID,
        "control requires an explicit target different from the actual caller"
    );
    // ProvisionOnly can target another account. Its completion must validate the
    // exact writer authority, without accepting that ACL as the current user's.
    let target = private_identity_security::SYSTEM_SID;
    let _writer = HomeSetupGuard::acquire_for_user(root.path(), target)?;
    setup::verify_setup_completed_for_user(root.path(), target)?;
    assert!(setup::verify_setup_completed(root.path()).is_err());
    println!("HIA_HOME_READINESS_CONTROL explicit_target_exact_authority: PASS");
    Ok(())
}
