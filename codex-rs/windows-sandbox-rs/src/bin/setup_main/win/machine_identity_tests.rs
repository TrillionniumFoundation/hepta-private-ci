use super::super::private_identity_publication::PrivateSecrets;
use super::super::private_identity_security::protected_descriptor;
use super::super::sandbox_users::provision_sandbox_users;
use super::*;
use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use codex_windows_sandbox::dpapi_unprotect;
use codex_windows_sandbox::sandbox_secrets_dir;
use rand::RngCore;
use rand::SeedableRng;
use rand::rngs::SmallRng;
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use tempfile::TempDir;
use windows_sys::Win32::NetworkManagement::NetManagement::NetUserDel;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::System::Threading::CreateMutexW;
use windows_sys::Win32::System::WindowsProgramming::GetUserNameW;

const WORKER_INPUT: &str = "HIA_MACHINE_IDENTITY_TEST_INPUT";

struct Fixture {
    offline: String,
    online: String,
    real_user: String,
    root: TempDir,
    owned_sids: HashMap<String, String>,
}

impl Fixture {
    fn new() -> Result<Self> {
        let nonce = SmallRng::from_entropy().next_u64() & 0x00ff_ffff_ffff_ffff;
        let offline = format!("CdxQ{nonce:014x}O");
        let online = format!("CdxQ{nonce:014x}N");
        ensure!(
            existing_sid(&offline)?.is_none() && existing_sid(&online)?.is_none(),
            "owned test account name was already occupied"
        );
        let mut username = [0u16; 257];
        let mut size = username.len() as u32;
        ensure!(
            unsafe { GetUserNameW(username.as_mut_ptr(), &mut size) } != 0,
            "read actual test account"
        );
        let real_user = String::from_utf16(&username[..size as usize - 1])?;
        let result = Self {
            offline,
            online,
            real_user,
            root: TempDir::new()?,
            owned_sids: HashMap::new(),
        };
        ensure!(
            result.store()?.load()?.is_none(),
            "owned test authority key was already occupied"
        );
        Ok(result)
    }

    fn store(&self) -> Result<Store> {
        Store::open(&identity_key(&self.offline, &self.online)?)
    }

    fn record(&self) -> Result<Record> {
        Record::decode(
            &self
                .store()?
                .load()?
                .context("owned test authority is missing")?,
            &self.offline,
            &self.online,
        )
    }

    fn home(&self, name: &str) -> Result<PathBuf> {
        let home = self.root.path().join(name);
        fs::create_dir(&home)?;
        Ok(home)
    }

    fn provision(&mut self, home: &Path) -> Result<()> {
        provision_sandbox_users(
            home,
            &self.real_user,
            &self.offline,
            &self.online,
            &mut Vec::new(),
        )?;
        self.remember_owned_accounts()
    }

    fn remember_owned_accounts(&mut self) -> Result<()> {
        let record = self.record()?;
        for account in [&record.offline, &record.online] {
            if let Some(sid) = &account.sid {
                ensure!(
                    existing_sid(&account.username)?.as_ref() == Some(sid),
                    "owned test account changed"
                );
                self.owned_sids
                    .insert(account.username.clone(), sid.clone());
            }
        }
        Ok(())
    }

    fn cleanup(&mut self) -> Result<()> {
        if let Ok(record) = self.record() {
            for account in [&record.offline, &record.online] {
                if let Some(actual) = existing_sid(&account.username)? {
                    if account.sid.as_ref() == Some(&actual) || logon_matches(account, &actual)? {
                        self.owned_sids
                            .entry(account.username.clone())
                            .or_insert(actual);
                    }
                }
            }
        }
        for (name, owned) in &self.owned_sids {
            if let Some(actual) = existing_sid(name)? {
                ensure!(
                    &actual == owned,
                    "refusing cleanup of a replaced test account"
                );
                let wide = to_wide(name);
                ensure!(
                    unsafe { NetUserDel(std::ptr::null(), wide.as_ptr()) } == NERR_Success,
                    "remove owned test account"
                );
            }
        }
        let mut store = self.store()?;
        if store.load()?.is_some() {
            store.remove()?;
        }
        Ok(())
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        if let Err(error) = self.cleanup() {
            eprintln!("owned machine identity test cleanup failed: {error:#}");
        }
    }
}

fn home_passwords(home: &Path) -> Result<[String; 2]> {
    let value: serde_json::Value = serde_json::from_slice(&fs::read(
        sandbox_secrets_dir(home).join("sandbox_users.json"),
    )?)?;
    let decode = |role: &str| -> Result<String> {
        let blob = STANDARD.decode(
            value[role]["password"]
                .as_str()
                .context("missing test password blob")?,
        )?;
        Ok(String::from_utf8(dpapi_unprotect(&blob)?)?)
    };
    Ok([decode("offline")?, decode("online")?])
}

#[test]
#[ignore = "This real process worker is launched twice and checked by cross_process_homes_keep_the_first_credentials."]
fn credential_provisioning_worker() -> Result<()> {
    let input =
        std::env::var(WORKER_INPUT).context("worker must be launched by its parent control")?;
    let (home, real_user, offline, online): (PathBuf, String, String, String) =
        serde_json::from_str(&input)?;
    provision_sandbox_users(&home, &real_user, &offline, &online, &mut Vec::new())
}

#[test]
fn cross_process_homes_keep_the_first_credentials() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let first = fixture.home("first")?;
    let second = fixture.home("second")?;
    let executable = std::env::current_exe()?;
    let mut children = Vec::new();
    for home in [&first, &second] {
        let input =
            serde_json::to_string(&(home, &fixture.real_user, &fixture.offline, &fixture.online))?;
        children.push(
            Command::new(&executable)
                .args([
                    "--ignored",
                    "--exact",
                    "win::machine_identity::tests::credential_provisioning_worker",
                    "--nocapture",
                ])
                .env(WORKER_INPUT, input)
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()?,
        );
    }
    let outputs = children
        .into_iter()
        .map(|child| {
            let pid = child.id();
            child.wait_with_output().map(|output| (pid, output))
        })
        .collect::<std::io::Result<Vec<_>>>()?;
    for (index, (pid, output)) in outputs.iter().enumerate() {
        println!(
            "HIA_MACHINE_IDENTITY_WORKER_TERMINAL {}",
            serde_json::to_string(&serde_json::json!({
                "schema": "hia.windows.machine-identity-worker-terminal.v1",
                "worker": index,
                "pid": pid,
                "exit_code": output.status.code(),
                "same_test_binary": executable,
                "method": "win::machine_identity::tests::credential_provisioning_worker",
                "arguments": ["--ignored", "--exact", "win::machine_identity::tests::credential_provisioning_worker", "--nocapture"],
                "stdout_bytes": output.stdout.len(),
                "stdout_base64": STANDARD.encode(&output.stdout),
                "stderr_bytes": output.stderr.len(),
                "stderr_base64": STANDARD.encode(&output.stderr),
                "wait_completed": true
            }))?
        );
    }
    for (_, output) in outputs {
        ensure!(
            output.status.success(),
            "actual provisioning worker failed: {} {}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        ensure!(
            String::from_utf8_lossy(&output.stdout).contains("1 passed; 0 failed; 0 ignored"),
            "provisioning worker did not execute its exact control"
        );
    }
    fixture.remember_owned_accounts()?;
    let first_passwords = home_passwords(&first)?;
    ensure!(
        first_passwords == home_passwords(&second)?,
        "a second home rotated the first home's credentials"
    );
    let record = fixture.record()?;
    ensure!(
        first_passwords
            == [
                record.offline.password.clone(),
                record.online.password.clone()
            ],
        "home credentials are not bound to the machine authority"
    );
    validate_ready(&record.offline)?;
    validate_ready(&record.online)?;
    let third = fixture.home("third")?;
    fixture.provision(&third)?;
    ensure!(
        first_passwords == home_passwords(&third)?,
        "sequential setup rotated existing credentials"
    );
    validate_ready(&record.offline)?;
    validate_ready(&record.online)?;
    println!(
        "HIA_MACHINE_IDENTITY_CONTROL cross_process_homes: PASS; workers=2; first_credentials_still_valid=true"
    );
    fixture.cleanup()
}

#[test]
fn pending_creation_recovers_the_same_password_after_interruption() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let pending = Record {
        state: State::Pending,
        offline: Account {
            username: fixture.offline.clone(),
            sid: None,
            password: random_password(),
        },
        online: Account {
            username: fixture.online.clone(),
            sid: None,
            password: random_password(),
        },
    };
    fixture.store()?.save(&pending.encode()?)?;
    super::super::sandbox_users::ensure_sandbox_users_group(&mut Vec::new())?;
    create_sandbox_user(&fixture.offline, &pending.offline.password, &mut Vec::new())?;
    let sid = existing_sid(&fixture.offline)?.context("created test account")?;
    fixture
        .owned_sids
        .insert(fixture.offline.clone(), sid.clone());
    // The actual account exists, but the persisted intent still has no SID:
    // this is the interruption between account creation and record publication.
    let home = fixture.home("recovered")?;
    fixture.provision(&home)?;
    let ready = fixture.record()?;
    ensure!(
        ready.state == State::Ready && ready.offline.sid.as_deref() == Some(sid.as_str()),
        "pending identity was not recovered"
    );
    ensure!(
        ready.offline.password == pending.offline.password
            && ready.online.password == pending.online.password,
        "recovery generated a replacement password"
    );
    ensure!(
        home_passwords(&home)? == [pending.offline.password, pending.online.password],
        "recovered home received different credentials"
    );
    fixture.cleanup()
}

#[test]
fn ready_identity_rejects_same_name_account_replacement() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let first = fixture.home("initial")?;
    fixture.provision(&first)?;
    let before = fixture.store()?.load()?.context("ready authority")?;
    let record = fixture.record()?;
    let name = to_wide(&fixture.offline);
    ensure!(
        unsafe { NetUserDel(std::ptr::null(), name.as_ptr()) } == NERR_Success,
        "remove owned fixture account"
    );
    create_sandbox_user(&fixture.offline, &record.offline.password, &mut Vec::new())?;
    let replacement = existing_sid(&fixture.offline)?.context("replacement account")?;
    ensure!(
        record.offline.sid.as_ref() != Some(&replacement),
        "replacement must have a new actual SID"
    );
    fixture
        .owned_sids
        .insert(fixture.offline.clone(), replacement);
    let second = fixture.home("refused")?;
    let error = provision_sandbox_users(
        &second,
        &fixture.real_user,
        &fixture.offline,
        &fixture.online,
        &mut Vec::new(),
    )
    .expect_err("same-name replacement must be refused");
    ensure!(
        error.to_string().contains("removed or replaced"),
        "wrong refusal: {error:#}"
    );
    ensure!(
        !sandbox_secrets_dir(&second)
            .join("sandbox_users.json")
            .exists(),
        "refused identity published credentials"
    );
    ensure!(
        fixture.store()?.load()?.as_deref() == Some(before.as_str()),
        "refusal changed the machine authority"
    );
    fixture.cleanup()
}

#[test]
fn unsafe_preexisting_mutex_cannot_start_provisioning() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let key = identity_key(&fixture.offline, &fixture.online)?;
    let unsafe_descriptor = protected_descriptor(Some("S-1-1-0"), "")?;
    let attributes = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: unsafe_descriptor.0,
        bInheritHandle: 0,
    };
    let name = to_wide(format!("Global\\CodexSandbox.Identity.v1.{key}"));
    let handle = unsafe { CreateMutexW(&attributes, 0, name.as_ptr()) };
    ensure!(handle != 0, "create owned unsafe mutex fixture");
    let handle = unsafe { OwnedHandle::from_raw_handle(handle as *mut c_void) };
    let home = fixture.home("unsafe-mutex")?;
    let result = provision_sandbox_users(
        &home,
        &fixture.real_user,
        &fixture.offline,
        &fixture.online,
        &mut Vec::new(),
    );
    ensure!(
        result.is_err(),
        "unsafe preexisting synchronization object was accepted"
    );
    ensure!(
        fixture.store()?.load()?.is_none(),
        "unsafe mutex caused secret creation"
    );
    ensure!(
        existing_sid(&fixture.offline)?.is_none() && existing_sid(&fixture.online)?.is_none(),
        "unsafe mutex caused account creation"
    );
    drop(handle);
    fixture.cleanup()
}

#[test]
fn private_home_publication_holds_its_directory_identity() -> Result<()> {
    let fixture = Fixture::new()?;
    let home = fixture.home("private-publication")?;
    let publication = PrivateSecrets::prepare(&home, &fixture.real_user)?;
    let path = sandbox_secrets_dir(&home);
    ensure!(
        fs::rename(&path, home.join("moved-secrets")).is_err(),
        "credential directory could be replaced while held"
    );
    publication.publish(b"owned publication control")?;
    ensure!(
        fs::read(path.join("sandbox_users.json"))? == b"owned publication control",
        "private publication changed bytes"
    );
    drop(publication);
    Ok(())
}
