//! Actual special-file opens in a bounded, test-owned child. No Agentd,
//! provider login, production authority or preexisting configuration is used.

use anyhow::Context;
use pretty_assertions::assert_eq;
use std::ffi::CString;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

fn check_fifo_in_owned_child(directory: &Path, reader: &str) -> anyhow::Result<()> {
    let fifo = directory.join("configuration.json");
    let encoded = CString::new(fifo.as_os_str().as_bytes())?;
    // SAFETY: the CString is live and terminated. The test owns the new private
    // directory, and no process opens a writer on this FIFO.
    if unsafe {
        libc::mkfifo(encoded.as_ptr(), /*mode*/ 0o600)
    } != 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    std::fs::set_permissions(&fifo, std::fs::Permissions::from_mode(0o600))?;
    let mut child = Command::new(std::env::current_exe()?)
        .args([
            "--exact",
            "text_session::provider::tests::fifo_reader_child",
            "--ignored",
            "--nocapture",
        ])
        .env("HEPTA_ROUTE_FIFO_TEST_PATH", &fifo)
        .env("HEPTA_ROUTE_FIFO_TEST_READER", reader)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()?;
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) if Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(10));
            }
            observed => {
                // Only our special-file probe is killed/reaped, never a build
                // or product process. Old blocking-open behavior must fail CI.
                let _ = child.kill();
                child.wait()?;
                anyhow::bail!("{reader} reader did not reject its no-writer FIFO: {observed:?}");
            }
        }
    }
    let output = child.wait_with_output()?;
    anyhow::ensure!(output.status.success(), "{reader} FIFO child failed");
    let marker = format!("HEPTA_ROUTE_FIFO_REJECTED_V1:{reader}");
    anyhow::ensure!(
        String::from_utf8(output.stdout)?.contains(&marker),
        "{reader} child did not execute the exact rejection gate"
    );
    Ok(())
}

#[test]
fn provider_route_fifo_is_rejected_before_read() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    check_fifo_in_owned_child(directory.path(), "provider")
}

#[cfg(target_os = "linux")]
#[test]
#[ignore = "explicit root-only qualification under an existing protected state parent"]
fn root_configuration_fifo_is_rejected_before_read() -> anyhow::Result<()> {
    // SAFETY: geteuid observes only the current process identity.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let parent = std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT")
        .context("the existing protected qualification parent is required")?;
    let directory = tempfile::Builder::new()
        .prefix("root-config-fifo-")
        .tempdir_in(parent)?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    codex_hepta_contracts::RootAuthorityDirectory::open(directory.path())
        .map_err(anyhow::Error::msg)?;
    check_fifo_in_owned_child(directory.path(), "root")
}

#[test]
#[ignore = "executed only by the bounded FIFO parent process"]
fn fifo_reader_child() -> anyhow::Result<()> {
    let path = std::env::var_os("HEPTA_ROUTE_FIFO_TEST_PATH")
        .context("the bounded parent must supply its owned FIFO")?;
    let reader = std::env::var("HEPTA_ROUTE_FIFO_TEST_READER")?;
    match reader.as_str() {
        "provider" => {
            let error = super::read_route(Path::new(&path)).unwrap_err();
            anyhow::ensure!(
                error
                    .to_string()
                    .contains("route must be a current-user0600 regular single-link file"),
                "provider must reject the actual opened nonregular descriptor: {error}"
            );
        }
        #[cfg(target_os = "linux")]
        "root" => {
            let error =
                crate::authority_host_config::read_root_json::<serde_json::Value>(Path::new(&path))
                    .unwrap_err();
            assert_eq!(
                error.to_string(),
                "configuration must be root0600 regular single-link file"
            );
        }
        _ => anyhow::bail!("unknown reader fixture"),
    }
    println!("HEPTA_ROUTE_FIFO_REJECTED_V1:{reader}");
    Ok(())
}
