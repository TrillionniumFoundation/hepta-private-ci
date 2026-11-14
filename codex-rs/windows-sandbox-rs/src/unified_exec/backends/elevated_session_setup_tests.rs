use super::with_active_request;
use crate::identity::SandboxCreds;
use crate::ipc_framed::ErrorPayload;
use crate::ipc_framed::ErrorStage;
use crate::runner_client::RunnerStartupError;
use crate::runner_client::retry_runner_spawn_once;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::cell::Cell;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use windows_sys::Win32::Foundation::ERROR_NO_SUCH_LOGON_SESSION;

#[test]
fn cancelled_request_does_not_enter_first_spawn() -> Result<()> {
    let active = AtomicBool::new(false);
    let attempts = Cell::new(0);
    let result = with_active_request(&active, || {
        attempts.set(attempts.get() + 1);
        Ok(())
    });
    let Err(error) = result else {
        anyhow::bail!("cancelled request entered the spawn operation");
    };
    assert_eq!(error.to_string(), "sandbox session request was cancelled");
    assert_eq!(attempts.get(), 0);
    Ok(())
}

#[test]
fn cancellation_during_credential_refresh_prevents_second_spawn() -> Result<()> {
    let active = AtomicBool::new(true);
    let attempts = Cell::new(0);
    let refreshes = Cell::new(0);
    let result = retry_runner_spawn_once(
        SandboxCreds {
            username: "stale".to_string(),
            password: "old".to_string(),
        },
        &["cmd.exe".to_string()],
        |_creds| {
            with_active_request(&active, || {
                attempts.set(attempts.get() + 1);
                Err::<(), _>(
                    RunnerStartupError::new(ErrorPayload {
                        message: "fixture logon needs credential refresh".to_string(),
                        stage: ErrorStage::SpawnChild,
                        windows_error_code: Some(ERROR_NO_SUCH_LOGON_SESSION),
                    })
                    .into(),
                )
            })
        },
        || {
            refreshes.set(refreshes.get() + 1);
            active.store(false, Ordering::Release);
            Ok(SandboxCreds {
                username: "refreshed".to_string(),
                password: "new".to_string(),
            })
        },
    );
    let Err(error) = result else {
        anyhow::bail!("cancelled request retried the runner");
    };
    assert_eq!(error.to_string(), "sandbox session request was cancelled");
    assert_eq!(attempts.get(), 1);
    assert_eq!(refreshes.get(), 1);
    Ok(())
}
