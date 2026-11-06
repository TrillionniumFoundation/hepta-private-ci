use super::RunnerLogonError;
use super::retry_runner_spawn_once;
use crate::identity::SandboxCreds;
use crate::winutil::to_wide;
use anyhow::Context;
use anyhow::Result;
use anyhow::anyhow;
use anyhow::bail;
use anyhow::ensure;
use rand::RngCore;
use rand::rngs::OsRng;
use std::cell::Cell;
use std::ptr;
use std::sync::mpsc;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_LOGON_FAILURE;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::NetworkManagement::NetManagement::NERR_Success;
use windows_sys::Win32::NetworkManagement::NetManagement::NetUserAdd;
use windows_sys::Win32::NetworkManagement::NetManagement::NetUserDel;
use windows_sys::Win32::NetworkManagement::NetManagement::NetUserSetInfo;
use windows_sys::Win32::NetworkManagement::NetManagement::UF_DONT_EXPIRE_PASSWD;
use windows_sys::Win32::NetworkManagement::NetManagement::UF_SCRIPT;
use windows_sys::Win32::NetworkManagement::NetManagement::USER_INFO_1;
use windows_sys::Win32::NetworkManagement::NetManagement::USER_INFO_1003;
use windows_sys::Win32::NetworkManagement::NetManagement::USER_PRIV_USER;
use windows_sys::Win32::Security::LOGON32_LOGON_INTERACTIVE;
use windows_sys::Win32::Security::LOGON32_PROVIDER_DEFAULT;
use windows_sys::Win32::Security::LogonUserW;

struct TestAccount {
    username: String,
    removed: bool,
}

impl TestAccount {
    fn create(username: String, password: &str) -> Result<Self> {
        let name = to_wide(&username);
        let password = to_wide(password);
        let info = USER_INFO_1 {
            usri1_name: name.as_ptr().cast_mut(),
            usri1_password: password.as_ptr().cast_mut(),
            usri1_password_age: 0,
            usri1_priv: USER_PRIV_USER,
            usri1_home_dir: ptr::null_mut(),
            usri1_comment: ptr::null_mut(),
            usri1_flags: UF_SCRIPT | UF_DONT_EXPIRE_PASSWD,
            usri1_script_path: ptr::null_mut(),
        };
        let status = unsafe {
            NetUserAdd(
                ptr::null(),
                /*level*/ 1,
                (&info as *const USER_INFO_1).cast(),
                ptr::null_mut(),
            )
        };
        eprintln!("PROBE_CREATE_STATUS {status}");
        if status != NERR_Success {
            // Never change or delete an account that this probe did not create.
            bail!("create disposable probe account failed with code {status}");
        }
        Ok(Self {
            username,
            removed: false,
        })
    }

    fn remove(mut self) -> Result<()> {
        let name = to_wide(&self.username);
        let status = unsafe { NetUserDel(ptr::null(), name.as_ptr()) };
        eprintln!("PROBE_REMOVE_STATUS {status}");
        if status != NERR_Success {
            bail!("remove disposable probe account failed with code {status}");
        }
        self.removed = true;
        Ok(())
    }
}

impl Drop for TestAccount {
    fn drop(&mut self) {
        if !self.removed {
            let name = to_wide(&self.username);
            // A failed/panicking diagnostic still attempts cleanup of only its own account.
            let status = unsafe { NetUserDel(ptr::null(), name.as_ptr()) };
            eprintln!("PROBE_DROP_REMOVE_STATUS {status}");
        }
    }
}

fn rotate_password(username: &str, password: &str) -> Result<()> {
    let username = to_wide(username);
    let password = to_wide(password);
    let info = USER_INFO_1003 {
        usri1003_password: password.as_ptr().cast_mut(),
    };
    let status = unsafe {
        NetUserSetInfo(
            ptr::null(),
            username.as_ptr(),
            /*level*/ 1003,
            (&info as *const USER_INFO_1003).cast(),
            ptr::null_mut(),
        )
    };
    if status != NERR_Success {
        bail!("rotate disposable probe account failed with code {status}");
    }
    Ok(())
}

fn authenticate(username: &str, password: &str) -> std::result::Result<(), u32> {
    let username = to_wide(username);
    let password = to_wide(password);
    let domain = to_wide(".");
    let mut token = 0;
    let success = unsafe {
        LogonUserW(
            username.as_ptr(),
            domain.as_ptr(),
            password.as_ptr(),
            LOGON32_LOGON_INTERACTIVE,
            LOGON32_PROVIDER_DEFAULT,
            &mut token,
        )
    };
    if success == 0 {
        return Err(unsafe { GetLastError() });
    }
    let closed = unsafe { CloseHandle(token) };
    if closed == 0 {
        return Err(unsafe { GetLastError() });
    }
    Ok(())
}

#[test]
fn concurrent_account_rotation_invalidates_both_bounded_logon_attempts() -> Result<()> {
    let mut rng = OsRng;
    let username = format!("CdxRace{:012x}", rng.next_u64() & 0xffff_ffff_ffff);
    let nonce = format!("{:016x}{:016x}", rng.next_u64(), rng.next_u64());
    let passwords = ["A", "B", "C", "D"].map(|suffix| format!("Ct1!{nonce}{suffix}"));
    let account = TestAccount::create(username, &passwords[0])?;
    let trial = (|| -> Result<()> {
        authenticate(&account.username, &passwords[0])
            .map_err(|code| anyhow!("initial valid credential control failed with code {code}"))?;
        eprintln!("PROBE_VALID_CONTROL initial");
        let attempts = Cell::new(0);
        let refreshes = Cell::new(0);
        std::thread::scope(|scope| -> Result<()> {
            let (update_sender, update_receiver) = mpsc::channel::<String>();
            let (ack_sender, ack_receiver) = mpsc::channel();
            let username = &account.username;
            let worker = scope.spawn(move || -> Result<usize> {
                let mut rotations = 0;
                for password in update_receiver {
                    let changed = rotate_password(username, &password);
                    rotations += 1;
                    ack_sender
                        .send(changed)
                        .map_err(|_| anyhow!("rotation receiver closed"))?;
                }
                Ok(rotations)
            });
            let mut interference = [passwords[1].clone(), passwords[3].clone()].into_iter();
            let mut observed_logon_codes = Vec::new();
            let outcome = retry_runner_spawn_once(
                SandboxCreds {
                    username: username.clone(),
                    password: passwords[0].clone(),
                },
                &[],
                |credentials| {
                    attempts.set(attempts.get() + 1);
                    let password = interference
                        .next()
                        .context("unexpected extra logon attempt")?;
                    update_sender
                        .send(password)
                        .map_err(|_| anyhow!("rotation worker closed"))?;
                    ack_receiver
                        .recv()
                        .context("rotation acknowledgement missing")??;
                    let result = authenticate(&credentials.username, &credentials.password);
                    observed_logon_codes.push(result.as_ref().err().copied());
                    result.map_err(|code| anyhow::Error::new(RunnerLogonError { code }))
                },
                || {
                    refreshes.set(refreshes.get() + 1);
                    rotate_password(username, &passwords[2])?;
                    authenticate(username, &passwords[2]).map_err(|code| {
                        anyhow!("refreshed valid credential control failed with code {code}")
                    })?;
                    eprintln!("PROBE_VALID_CONTROL refreshed");
                    Ok(SandboxCreds {
                        username: username.clone(),
                        password: passwords[2].clone(),
                    })
                },
            );
            drop(update_sender);
            let rotations = worker
                .join()
                .map_err(|_| anyhow!("rotation worker panicked"))??;
            ensure!(
                (attempts.get(), refreshes.get(), rotations) == (2, 1, 2),
                "diagnostic did not execute exactly two logons, one refresh and two rotations"
            );
            eprintln!("PROBE_STALE_LOGON_CODES {observed_logon_codes:?}");
            ensure!(
                observed_logon_codes.as_slice()
                    == [Some(ERROR_LOGON_FAILURE), Some(ERROR_LOGON_FAILURE)],
                "unexpected stale logon error codes: {observed_logon_codes:?}"
            );
            let Err(error) = outcome else {
                bail!("stale credentials unexpectedly authenticated after acknowledged rotation");
            };
            ensure!(
                error
                    .downcast_ref::<RunnerLogonError>()
                    .map(|error| error.code)
                    == Some(ERROR_LOGON_FAILURE),
                "final stale credential returned an unexpected error class"
            );
            authenticate(username, &passwords[3]).map_err(|code| {
                anyhow!("final valid credential control failed with code {code}")
            })?;
            eprintln!("PROBE_VALID_CONTROL final");
            Ok(())
        })
    })();
    let cleanup = account.remove();
    eprintln!(
        "PROBE_TRIAL_OK {} CLEANUP_OK {}",
        trial.is_ok(),
        cleanup.is_ok()
    );
    match (trial, cleanup) {
        (Ok(()), Ok(())) => Ok(()),
        (Err(error), Ok(())) | (Ok(()), Err(error)) => Err(error),
        (Err(error), Err(cleanup_error)) => Err(error.context(cleanup_error)),
    }
}
