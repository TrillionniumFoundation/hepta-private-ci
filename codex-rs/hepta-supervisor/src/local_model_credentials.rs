//! Refresh the operator's existing Codex login as its actual owner UID.
//! Credentials cross only an anonymous pipe into the root model service.

use std::path::Path;
use std::process::Stdio;
use std::time::Duration;

use anyhow::Context;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use codex_login::AuthCredentialsStoreMode;
use codex_login::AuthKeyringBackendKind;
use codex_login::AuthManager;
use codex_login::AuthRouteConfig;
use serde::Deserialize;
use serde::Serialize;
use tokio::io::AsyncReadExt;
use zeroize::Zeroizing;

use super::relay_policy::ModelRelayPolicy;

const MAX_CREDENTIAL_RESPONSE_BYTES: u64 = 32 * 1024;
// A profile's refresh token is one mutable resource. Fleet calls remain
// bounded and independent of the Fleet owner while refreshes are serialized.
static CREDENTIAL_REFRESH: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CredentialHeaders {
    pub bearer: String,
    pub account_id: Option<String>,
    pub uses_codex_backend: bool,
}

/// Only the startup-owned model executable calls this child mode. The child
/// has no root privileges, authority keys, or connection to an Agent.
pub async fn run_credential_worker(profile: &Path) -> anyhow::Result<()> {
    use std::os::unix::fs::MetadataExt;
    let uid = rustix::process::geteuid().as_raw();
    anyhow::ensure!(
        uid != 0 && profile.is_absolute(),
        "invalid credential worker identity"
    );
    let metadata = std::fs::symlink_metadata(profile)?;
    anyhow::ensure!(
        metadata.is_dir() && metadata.uid() == uid && metadata.mode() & 0o077 == 0,
        "credential profile must be private to its actual owner"
    );
    let manager = AuthManager::new(
        profile.to_owned(),
        /*enable_codex_api_key_env*/ false,
        AuthCredentialsStoreMode::Auto,
        /*forced_chatgpt_workspace_id*/ None,
        /*chatgpt_base_url*/ None,
        AuthKeyringBackendKind::default(),
        AuthRouteConfig::from_http_client_factory(HttpClientFactory::new(
            OutboundProxyPolicy::RespectSystemProxy,
        )),
    )
    .await;
    let auth = manager
        .auth()
        .await
        .context("model credential unavailable")?;
    anyhow::ensure!(
        auth.is_api_key_auth() || auth.is_chatgpt_auth(),
        "unsupported model login route"
    );
    let headers = CredentialHeaders {
        bearer: auth.get_token()?,
        account_id: auth.get_account_id(),
        uses_codex_backend: auth.uses_codex_backend(),
    };
    headers.validate()?;
    let bytes = Zeroizing::new(serde_json::to_vec(&headers)?);
    anyhow::ensure!(
        bytes.len() <= MAX_CREDENTIAL_RESPONSE_BYTES as usize,
        "credential bound"
    );
    use std::io::Write;
    std::io::stdout().lock().write_all(&bytes)?;
    Ok(())
}

impl CredentialHeaders {
    fn validate(&self) -> anyhow::Result<()> {
        anyhow::ensure!(
            !self.bearer.is_empty()
                && self.bearer.len() <= 16 * 1024
                && self.bearer.bytes().all(|byte| byte.is_ascii_graphic())
                && self.account_id.as_ref().is_none_or(|account| {
                    !account.is_empty()
                        && account.len() <= 256
                        && account.bytes().all(|byte| byte.is_ascii_graphic())
                }),
            "invalid model credential material"
        );
        anyhow::ensure!(
            !self.uses_codex_backend || self.account_id.is_some(),
            "ChatGPT login account is missing"
        );
        Ok(())
    }
}

impl Drop for CredentialHeaders {
    fn drop(&mut self) {
        use zeroize::Zeroize;
        self.bearer.zeroize();
    }
}

pub(super) async fn load(policy: &ModelRelayPolicy) -> anyhow::Result<CredentialHeaders> {
    let _refresh = CREDENTIAL_REFRESH.lock().await;
    use std::os::unix::fs::MetadataExt;
    super::store::protected_directory(Path::new("/usr/bin"))?;
    let launcher = Path::new("/usr/bin/setpriv");
    let metadata = std::fs::symlink_metadata(launcher)?;
    anyhow::ensure!(
        metadata.is_file() && metadata.uid() == 0 && metadata.mode() & 0o022 == 0,
        "credential identity launcher is not root protected"
    );
    let executable = std::env::current_exe()?;
    super::store::protected_directory(executable.parent().context("credential binary parent")?)?;
    let metadata = std::fs::symlink_metadata(&executable)?;
    anyhow::ensure!(
        metadata.is_file() && metadata.uid() == 0 && metadata.mode() & 0o022 == 0,
        "credential executable is not root protected"
    );
    let mut command = tokio::process::Command::new(launcher);
    command
        .arg("--reuid")
        .arg(policy.credential_uid.to_string())
        .arg("--regid")
        .arg(policy.credential_gid.to_string())
        .arg("--clear-groups")
        .arg("--no-new-privs")
        .arg("--")
        .arg(executable)
        .arg("--credential-worker")
        .arg(&policy.credential_profile_home)
        .env_clear()
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    for name in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "CODEX_CA_CERTIFICATE",
        "SSL_CERT_FILE",
        "DBUS_SESSION_BUS_ADDRESS",
    ] {
        if let Some(value) = std::env::var_os(name) {
            command.env(name, value);
        }
    }
    let mut child = command.spawn()?;
    let result = tokio::time::timeout(Duration::from_millis(policy.credential_timeout_ms), async {
        let output = child
            .stdout
            .take()
            .context("credential worker output missing")?;
        let mut bytes = Zeroizing::new(Vec::new());
        output
            .take(MAX_CREDENTIAL_RESPONSE_BYTES + 1)
            .read_to_end(&mut bytes)
            .await?;
        anyhow::ensure!(
            bytes.len() <= MAX_CREDENTIAL_RESPONSE_BYTES as usize,
            "credential output bound"
        );
        anyhow::ensure!(child.wait().await?.success(), "credential worker failed");
        let headers: CredentialHeaders = serde_json::from_slice(&bytes)?;
        headers.validate()?;
        Ok::<_, anyhow::Error>(headers)
    })
    .await;
    if result.is_err() || result.as_ref().is_ok_and(std::result::Result::is_err) {
        let _ = child.kill().await;
        let _ = child.wait().await;
    }
    result.context("credential worker timed out")?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn credential_headers_reject_injection_and_missing_backend_account() {
        let mut headers = CredentialHeaders {
            bearer: "test-token".to_owned(),
            account_id: None,
            uses_codex_backend: false,
        };
        assert!(headers.validate().is_ok());
        headers.uses_codex_backend = true;
        assert!(headers.validate().is_err());
        headers.account_id = Some("test-account".to_owned());
        assert!(headers.validate().is_ok());
        headers.bearer = "token\r\nHeader:value".to_owned();
        assert!(headers.validate().is_err());
        headers.bearer = "test-token".to_owned();
        headers.account_id = Some("account\nHeader:value".to_owned());
        assert!(headers.validate().is_err());
    }

    #[tokio::test]
    async fn worker_rejects_a_shared_profile_before_loading_any_login() {
        use std::os::unix::fs::PermissionsExt;
        let profile = tempfile::tempdir().unwrap();
        std::fs::set_permissions(profile.path(), std::fs::Permissions::from_mode(0o755)).unwrap();
        assert!(run_credential_worker(profile.path()).await.is_err());
        assert!(
            run_credential_worker(Path::new("relative/profile"))
                .await
                .is_err()
        );
    }
}
