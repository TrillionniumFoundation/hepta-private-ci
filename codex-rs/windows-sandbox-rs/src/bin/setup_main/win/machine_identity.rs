//! One recoverable credential authority for the fixed machine accounts.
//! Per-home setup must not rotate passwords used by other homes or processes.
use super::machine_identity_mutex::ProvisionGuard;
use super::machine_identity_store::Store;
use super::private_identity_security::token_user_sid;
use super::sandbox_users::SANDBOX_USERS_GROUP;
use super::sandbox_users::create_sandbox_user;
use super::sandbox_users::ensure_local_group_member;
use super::sandbox_users::ensure_sandbox_user;
use super::sandbox_users::random_password;
use super::sandbox_users::resolve_sid;
use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_windows_sandbox::string_from_sid_bytes;
use codex_windows_sandbox::to_wide;
use serde::Deserialize;
use serde::Serialize;
use std::ffi::c_void;
use std::io::Write;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::ERROR_LOGON_FAILURE;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::NetworkManagement::NetManagement::NERR_Success;
use windows_sys::Win32::NetworkManagement::NetManagement::NERR_UserNotFound;
use windows_sys::Win32::NetworkManagement::NetManagement::NetApiBufferFree;
use windows_sys::Win32::NetworkManagement::NetManagement::NetUserGetInfo;
use windows_sys::Win32::Security::LOGON32_LOGON_INTERACTIVE;
use windows_sys::Win32::Security::LOGON32_PROVIDER_DEFAULT;
use windows_sys::Win32::Security::LogonUserW;

#[derive(Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
enum State {
    #[serde(rename = "p")]
    Pending,
    #[serde(rename = "r")]
    Ready,
}

struct Account {
    username: String,
    sid: Option<String>,
    password: String,
}

struct Record {
    state: State,
    offline: Account,
    online: Account,
}

// Compact tuples keep both SID-bound accounts below the documented 512-byte
// LSA secret limit. All tuple lengths, version and state are checked on decode.
type WireAccount = (String, Option<String>, String);
type WireRecord = (u32, State, WireAccount, WireAccount);

impl Account {
    fn wire(&self) -> (&str, Option<&str>, &str) {
        (&self.username, self.sid.as_deref(), &self.password)
    }

    fn from_wire((username, sid, password): WireAccount) -> Self {
        Self {
            username,
            sid,
            password,
        }
    }
}

impl Record {
    fn encode(&self) -> Result<String> {
        Ok(serde_json::to_string(&(
            1u32,
            self.state,
            self.offline.wire(),
            self.online.wire(),
        ))?)
    }

    fn decode(text: &str, offline: &str, online: &str) -> Result<Self> {
        let (version, state, offline_account, online_account): WireRecord =
            serde_json::from_str(text).context("decode machine credential transaction")?;
        ensure!(
            version == 1,
            "unknown machine credential transaction version"
        );
        let result = Self {
            state,
            offline: Account::from_wire(offline_account),
            online: Account::from_wire(online_account),
        };
        for (record, requested) in [(&result.offline, offline), (&result.online, online)] {
            ensure!(
                record.username.eq_ignore_ascii_case(requested),
                "machine credential account name mismatch"
            );
            ensure!(
                record.password.len() == 24
                    && record
                        .password
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b"!@#$%^&*()-_=+".contains(&b)),
                "invalid machine credential password encoding"
            );
            if state == State::Ready {
                ensure!(
                    record.sid.is_some(),
                    "ready machine credential has no account SID"
                );
            }
        }
        Ok(result)
    }
}

fn identity_key(offline: &str, online: &str) -> Result<String> {
    for name in [offline, online] {
        ensure!(
            !name.is_empty()
                && name.len() <= 20
                && name
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-'),
            "invalid sandbox local account name"
        );
    }
    ensure!(
        !offline.eq_ignore_ascii_case(online),
        "sandbox network identities must be distinct"
    );
    Ok(format!(
        "{}.{}",
        offline.to_ascii_lowercase(),
        online.to_ascii_lowercase()
    ))
}

fn existing_sid(username: &str) -> Result<Option<String>> {
    let name = to_wide(username);
    let mut buffer = std::ptr::null_mut();
    let status = unsafe { NetUserGetInfo(std::ptr::null(), name.as_ptr(), 0, &mut buffer) };
    if status == NERR_UserNotFound {
        return Ok(None);
    }
    if status != NERR_Success {
        return Err(std::io::Error::from_raw_os_error(status as i32))
            .context("inspect sandbox local account");
    }
    unsafe {
        NetApiBufferFree(buffer.cast());
    }
    Ok(Some(
        string_from_sid_bytes(&resolve_sid(username)?).map_err(anyhow::Error::msg)?,
    ))
}

fn logon_matches(account: &Account, expected_sid: &str) -> Result<bool> {
    let username = to_wide(&account.username);
    let password = to_wide(&account.password);
    let domain = to_wide(".");
    let mut token = 0;
    let ok = unsafe {
        LogonUserW(
            username.as_ptr(),
            domain.as_ptr(),
            password.as_ptr(),
            LOGON32_LOGON_INTERACTIVE,
            LOGON32_PROVIDER_DEFAULT,
            &mut token,
        )
    };
    if ok == 0 {
        let error = unsafe { GetLastError() };
        if error == ERROR_LOGON_FAILURE {
            return Ok(false);
        }
        return Err(std::io::Error::from_raw_os_error(error as i32))
            .context("validate sandbox account logon");
    }
    let token = unsafe { OwnedHandle::from_raw_handle(token as *mut c_void) };
    ensure!(
        token_user_sid(token.as_raw_handle() as _)? == expected_sid,
        "sandbox logon resolved to a different SID"
    );
    Ok(true)
}

fn validate_ready(account: &Account) -> Result<()> {
    let expected = account
        .sid
        .as_deref()
        .context("ready sandbox account has no SID")?;
    ensure!(
        existing_sid(&account.username)?.as_deref() == Some(expected),
        "sandbox account was removed or replaced; refusing an automatic identity takeover"
    );
    ensure!(
        logon_matches(account, expected)?,
        "machine sandbox credential no longer authenticates"
    );
    Ok(())
}

fn reconcile_pending(account: &mut Account, fresh_intent: bool, log: &mut dyn Write) -> Result<()> {
    let observed = existing_sid(&account.username)?;
    match (account.sid.as_deref(), observed.as_deref()) {
        (Some(expected), Some(actual)) => {
            ensure!(expected == actual, "pending sandbox account was replaced");
            if fresh_intent || !logon_matches(account, expected)? {
                // Only a first, SID-bound migration can set a pre-existing
                // account password. A Ready authority never takes this path.
                ensure_sandbox_user(&account.username, &account.password, log)?;
            }
        }
        (Some(_), None) => bail!("pending sandbox account disappeared"),
        (None, Some(actual)) => {
            // A previous helper may have created this account immediately
            // before interruption. Its persisted password must authenticate;
            // an unrelated same-name account must never be reset.
            ensure!(
                logon_matches(account, actual)?,
                "a different account occupied the pending sandbox name"
            );
        }
        (None, None) => {
            create_sandbox_user(&account.username, &account.password, log)?;
        }
    }
    let actual =
        existing_sid(&account.username)?.context("sandbox account creation did not persist")?;
    if let Some(expected) = &account.sid {
        ensure!(
            expected == &actual,
            "sandbox SID changed during provisioning"
        );
    }
    ensure!(
        logon_matches(account, &actual)?,
        "pending sandbox credential did not authenticate"
    );
    account.sid = Some(actual);
    ensure_local_group_member(SANDBOX_USERS_GROUP, &account.username)?;
    Ok(())
}

pub(super) fn with_credentials(
    offline: &str,
    online: &str,
    log: &mut dyn Write,
    publish: impl FnOnce(&str, &str) -> Result<()>,
) -> Result<()> {
    let key = identity_key(offline, online)?;
    let _guard = ProvisionGuard::acquire(&key)?;
    let mut store = Store::open(&key)?;
    let (mut record, fresh_intent) = match store.load()? {
        Some(raw) => (Record::decode(&raw, offline, online)?, false),
        None => {
            let pending = Record {
                state: State::Pending,
                offline: Account {
                    username: offline.to_string(),
                    sid: existing_sid(offline)?,
                    password: random_password(),
                },
                online: Account {
                    username: online.to_string(),
                    sid: existing_sid(online)?,
                    password: random_password(),
                },
            };
            // Persist the chosen passwords and existing identities before any
            // account creation or password mutation. Recovery reuses this intent.
            store.save(&pending.encode()?)?;
            (pending, true)
        }
    };
    if record.state == State::Pending {
        reconcile_pending(&mut record.offline, fresh_intent, log)?;
        store.save(&record.encode()?)?;
        reconcile_pending(&mut record.online, fresh_intent, log)?;
        store.save(&record.encode()?)?;
        record.state = State::Ready;
        store.save(&record.encode()?)?;
    }
    validate_ready(&record.offline)?;
    validate_ready(&record.online)?;
    let ready = record.encode()?;
    publish(&record.offline.password, &record.online.password)?;
    ensure!(
        store.load()?.as_deref() == Some(ready.as_str()),
        "machine credential authority changed during publication"
    );
    validate_ready(&record.offline)?;
    validate_ready(&record.online)?;
    Ok(())
}

#[cfg(test)]
#[path = "machine_identity_tests.rs"]
mod tests;
