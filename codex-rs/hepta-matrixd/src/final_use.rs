use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_matrix_sdk::MatrixAuthorityError;
use codex_hepta_matrix_sdk::MatrixFinalUseRequest;
use codex_hepta_matrix_sdk::MatrixGrantFuture;
use codex_hepta_matrix_sdk::MatrixOutboundAuthorizer;
use codex_hepta_paths::HeptaAgentLayout;
use serde::Deserialize;
use serde::Serialize;

const HOST_CONFIG_FILE: &str = "final-use.json";
const REVOCATIONS_FILE: &str = "final-use-revocations.json";
const STATE_DIRECTORY: &str = "final-use-authority-state";
const HOST_CONFIG_MAX_BYTES: usize = 32 * 1024;
const REVOCATIONS_MAX_BYTES: usize = 2 * 1024 * 1024;
const BROKER_FRAME_MAX_BYTES: usize = 128 * 1024;
const MIN_BROKER_TIMEOUT_MS: u64 = 100;
const MAX_BROKER_TIMEOUT_MS: u64 = 10_000;
const BROKER_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct MatrixFinalUseHostConfig {
    schema_version: u32,
    signer_id: String,
    verifying_key: [u8; 32],
    broker_socket: String,
    request_timeout_ms: u64,
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct MatrixGrantBrokerRequest<'a> {
    schema_version: u32,
    request: &'a MatrixFinalUseRequest,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct MatrixGrantBrokerResponse {
    schema_version: u32,
    grant: SignedFinalUseGrant,
}

#[cfg(unix)]
pub(crate) struct MatrixFinalUseBroker {
    authority: FinalUseAuthority,
    broker_socket: PathBuf,
    revocations_file: PathBuf,
    request_timeout: Duration,
}

#[cfg(unix)]
impl MatrixFinalUseBroker {
    pub(crate) async fn open(layout: &HeptaAgentLayout) -> Result<Self, MatrixFinalUseBrokerError> {
        let config_path = layout.matrix_secrets_root().join(HOST_CONFIG_FILE);
        let revocations_file = layout.matrix_secrets_root().join(REVOCATIONS_FILE);
        let config: MatrixFinalUseHostConfig =
            read_private_json(&config_path, HOST_CONFIG_MAX_BYTES)?;
        if config.schema_version != BROKER_SCHEMA_VERSION
            || !(MIN_BROKER_TIMEOUT_MS..=MAX_BROKER_TIMEOUT_MS).contains(&config.request_timeout_ms)
        {
            return Err(MatrixFinalUseBrokerError::InvalidConfiguration);
        }
        let broker_socket = PathBuf::from(&config.broker_socket);
        validate_private_socket(&broker_socket)?;
        let head: FinalUseRevocations =
            read_private_json(&revocations_file, REVOCATIONS_MAX_BYTES)?;
        let authority = FinalUseAuthority::open_state_dir(
            &layout.matrix_root().join(STATE_DIRECTORY),
            config.signer_id,
            config.verifying_key,
            head,
        )?;
        let broker = Self {
            authority,
            broker_socket,
            revocations_file,
            request_timeout: Duration::from_millis(config.request_timeout_ms),
        };
        broker.probe().await?;
        Ok(broker)
    }

    async fn probe(&self) -> Result<(), MatrixFinalUseBrokerError> {
        validate_private_socket(&self.broker_socket)?;
        tokio::time::timeout(
            self.request_timeout,
            tokio::net::UnixStream::connect(&self.broker_socket),
        )
        .await
        .map_err(|_| MatrixFinalUseBrokerError::BrokerUnavailable)?
        .map(drop)
        .map_err(|_| MatrixFinalUseBrokerError::BrokerUnavailable)
    }

    fn refresh_revocations(&self) -> Result<(), MatrixAuthorityError> {
        let head: FinalUseRevocations =
            read_private_json(&self.revocations_file, REVOCATIONS_MAX_BYTES)
                .map_err(|_| MatrixAuthorityError::Unavailable)?;
        let current = self
            .authority
            .revocation_head()
            .map_err(|_| MatrixAuthorityError::Unavailable)?;
        if head.authority_epoch == current.authority_epoch && head.revision == current.revision {
            return Ok(());
        }
        if head.authority_epoch < current.authority_epoch
            || (head.authority_epoch == current.authority_epoch
                && head.revision <= current.revision)
        {
            return Err(MatrixAuthorityError::Rejected);
        }
        self.authority
            .update_revocations(head)
            .map_err(|_| MatrixAuthorityError::Rejected)
    }

    async fn request_grant(
        &self,
        request: &MatrixFinalUseRequest,
    ) -> Result<SignedFinalUseGrant, MatrixAuthorityError> {
        request.validate()?;
        self.refresh_revocations()?;
        validate_private_socket(&self.broker_socket)
            .map_err(|_| MatrixAuthorityError::Unavailable)?;
        let frame = serde_json::to_vec(&MatrixGrantBrokerRequest {
            schema_version: BROKER_SCHEMA_VERSION,
            request,
        })
        .map_err(|_| MatrixAuthorityError::InvalidBinding)?;
        if frame.len() > BROKER_FRAME_MAX_BYTES {
            return Err(MatrixAuthorityError::InvalidBinding);
        }

        let response = tokio::time::timeout(self.request_timeout, async {
            use tokio::io::AsyncReadExt;
            use tokio::io::AsyncWriteExt;

            let mut stream = tokio::net::UnixStream::connect(&self.broker_socket)
                .await
                .map_err(|_| MatrixAuthorityError::Unavailable)?;
            stream
                .write_all(&frame)
                .await
                .map_err(|_| MatrixAuthorityError::Unavailable)?;
            stream
                .write_all(b"\n")
                .await
                .map_err(|_| MatrixAuthorityError::Unavailable)?;
            stream
                .shutdown()
                .await
                .map_err(|_| MatrixAuthorityError::Unavailable)?;
            let mut response = Vec::new();
            stream
                .take((BROKER_FRAME_MAX_BYTES + 1) as u64)
                .read_to_end(&mut response)
                .await
                .map_err(|_| MatrixAuthorityError::Unavailable)?;
            if response.len() > BROKER_FRAME_MAX_BYTES {
                return Err(MatrixAuthorityError::Rejected);
            }
            Ok::<_, MatrixAuthorityError>(response)
        })
        .await
        .map_err(|_| MatrixAuthorityError::Unavailable)??;

        let response: MatrixGrantBrokerResponse =
            serde_json::from_slice(&response).map_err(|_| MatrixAuthorityError::Rejected)?;
        if response.schema_version != BROKER_SCHEMA_VERSION
            || response.grant.grant.binding != request.binding
        {
            return Err(MatrixAuthorityError::Rejected);
        }
        Ok(response.grant)
    }
}

#[cfg(unix)]
impl MatrixOutboundAuthorizer for MatrixFinalUseBroker {
    fn authority(&self) -> &FinalUseAuthority {
        &self.authority
    }

    fn signed_grant<'a>(&'a self, request: &'a MatrixFinalUseRequest) -> MatrixGrantFuture<'a> {
        Box::pin(async move { self.request_grant(request).await })
    }

    fn refresh_revocations(&self) -> Result<(), MatrixAuthorityError> {
        MatrixFinalUseBroker::refresh_revocations(self)
    }
}

#[cfg(not(unix))]
pub(crate) struct MatrixFinalUseBroker;

#[cfg(not(unix))]
impl MatrixFinalUseBroker {
    pub(crate) async fn open(
        _layout: &HeptaAgentLayout,
    ) -> Result<Self, MatrixFinalUseBrokerError> {
        Err(MatrixFinalUseBrokerError::UnsupportedPlatform)
    }
}

#[cfg(not(unix))]
impl MatrixOutboundAuthorizer for MatrixFinalUseBroker {
    fn authority(&self) -> &FinalUseAuthority {
        panic!("Matrix final-use authority cannot open on this platform")
    }

    fn signed_grant<'a>(&'a self, _request: &'a MatrixFinalUseRequest) -> MatrixGrantFuture<'a> {
        Box::pin(async { Err(MatrixAuthorityError::Unavailable) })
    }

    fn refresh_revocations(&self) -> Result<(), MatrixAuthorityError> {
        Err(MatrixAuthorityError::Unavailable)
    }
}

#[cfg(unix)]
fn read_private_json<T: serde::de::DeserializeOwned>(
    path: &Path,
    maximum: usize,
) -> Result<T, MatrixFinalUseBrokerError> {
    use std::fs::File;
    use std::io::Read;
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute()
        || std::fs::canonicalize(path).map_err(|_| MatrixFinalUseBrokerError::UnsafePath)? != path
    {
        return Err(MatrixFinalUseBrokerError::UnsafePath);
    }
    let file: File = rustix::fs::open(
        path,
        rustix::fs::OFlags::RDONLY | rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| MatrixFinalUseBrokerError::UnsafePath)?
    .into();
    let metadata = file
        .metadata()
        .map_err(|_| MatrixFinalUseBrokerError::UnsafePath)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
        || metadata.len() > maximum as u64
    {
        return Err(MatrixFinalUseBrokerError::UnsafePath);
    }
    let mut bytes = Vec::new();
    file.take((maximum + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| MatrixFinalUseBrokerError::UnsafePath)?;
    if bytes.len() > maximum {
        return Err(MatrixFinalUseBrokerError::UnsafePath);
    }
    serde_json::from_slice(&bytes).map_err(|_| MatrixFinalUseBrokerError::InvalidConfiguration)
}

#[cfg(unix)]
fn validate_private_socket(path: &Path) -> Result<(), MatrixFinalUseBrokerError> {
    use std::os::unix::fs::FileTypeExt;
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() {
        return Err(MatrixFinalUseBrokerError::UnsafePath);
    }
    let parent = path.parent().ok_or(MatrixFinalUseBrokerError::UnsafePath)?;
    if std::fs::canonicalize(parent).map_err(|_| MatrixFinalUseBrokerError::UnsafePath)? != parent {
        return Err(MatrixFinalUseBrokerError::UnsafePath);
    }
    let parent_metadata =
        std::fs::symlink_metadata(parent).map_err(|_| MatrixFinalUseBrokerError::UnsafePath)?;
    if !parent_metadata.is_dir()
        || parent_metadata.mode() & 0o077 != 0
        || parent_metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(MatrixFinalUseBrokerError::UnsafePath);
    }
    if std::fs::canonicalize(path).map_err(|_| MatrixFinalUseBrokerError::UnsafePath)? != path {
        return Err(MatrixFinalUseBrokerError::UnsafePath);
    }
    let metadata =
        std::fs::symlink_metadata(path).map_err(|_| MatrixFinalUseBrokerError::UnsafePath)?;
    if !metadata.file_type().is_socket()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(MatrixFinalUseBrokerError::UnsafePath);
    }
    Ok(())
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum MatrixFinalUseBrokerError {
    #[error("Matrix final-use configuration is invalid")]
    InvalidConfiguration,
    #[error("Matrix final-use trust or broker path is unsafe")]
    UnsafePath,
    #[error("Matrix final-use broker is unavailable")]
    BrokerUnavailable,
    #[error("Matrix final-use authority is unsupported on this platform")]
    UnsupportedPlatform,
    #[error(transparent)]
    Authority(#[from] FinalUseError),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(unix)]
    use std::collections::BTreeSet;
    #[cfg(unix)]
    use std::error::Error;
    #[cfg(unix)]
    use std::os::unix::fs::PermissionsExt;

    #[cfg(unix)]
    use ed25519_dalek::SigningKey;
    #[cfg(unix)]
    use tempfile::TempDir;

    #[cfg(unix)]
    type TestResult<T = ()> = Result<T, Box<dyn Error>>;

    #[cfg(unix)]
    fn head(epoch: u64, revision: u64, revoked: &[&str]) -> FinalUseRevocations {
        FinalUseRevocations {
            authority_epoch: epoch,
            revision,
            revoked_grant_ids: revoked.iter().map(|value| (*value).to_string()).collect(),
        }
    }

    #[cfg(unix)]
    fn write_private_json(path: &Path, value: &FinalUseRevocations) -> TestResult {
        std::fs::write(path, serde_json::to_vec(value)?)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        Ok(())
    }

    #[cfg(unix)]
    fn test_broker(
        initial: FinalUseRevocations,
        file_head: FinalUseRevocations,
    ) -> TestResult<(TempDir, MatrixFinalUseBroker)> {
        let directory = TempDir::new()?;
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
        let signer = SigningKey::from_bytes(&[71; 32]);
        let revocations_file = directory.path().join("revocations.json");
        write_private_json(&revocations_file, &file_head)?;
        let authority = FinalUseAuthority::open_state_dir(
            &directory.path().join("authority"),
            "matrix-broker-test".to_string(),
            signer.verifying_key().to_bytes(),
            initial,
        )?;
        let broker = MatrixFinalUseBroker {
            authority,
            broker_socket: directory.path().join("broker.sock"),
            revocations_file,
            request_timeout: Duration::from_millis(MIN_BROKER_TIMEOUT_MS),
        };
        Ok((directory, broker))
    }

    #[test]
    fn config_constants_remain_bounded() {
        assert!(HOST_CONFIG_MAX_BYTES <= BROKER_FRAME_MAX_BYTES);
        assert!(MIN_BROKER_TIMEOUT_MS > 0);
        assert!(MAX_BROKER_TIMEOUT_MS <= 10_000);
        assert!(REVOCATIONS_MAX_BYTES <= 2 * 1024 * 1024);
    }

    #[cfg(unix)]
    #[test]
    fn revocation_file_rollback_and_stale_head_fail_closed() -> TestResult {
        let (_directory, broker) =
            test_broker(head(17, 3, &["revoked-a"]), head(17, 2, &[]))?;
        assert_eq!(
            broker.refresh_revocations(),
            Err(MatrixAuthorityError::Rejected),
        );
        assert_eq!(broker.authority.revocation_head()?.revision, 3);
        Ok(())
    }

    #[cfg(unix)]
    #[test]
    fn stronger_revocation_file_is_adopted_monotonically() -> TestResult {
        let (_directory, broker) =
            test_broker(head(17, 1, &[]), head(17, 2, &["revoked-a"]))?;
        broker.refresh_revocations()?;
        let frontier = broker.authority.revocation_head()?;
        assert_eq!(frontier.authority_epoch, 17);
        assert_eq!(frontier.revision, 2);
        Ok(())
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn broker_socket_death_fails_probe_closed() -> TestResult {
        let (directory, mut broker) = test_broker(head(17, 1, &[]), head(17, 1, &[]))?;
        let socket = directory.path().join("broker.sock");
        let listener = tokio::net::UnixListener::bind(&socket)?;
        std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o700))?;
        broker.broker_socket = socket;
        broker.probe().await?;
        drop(listener);
        assert!(matches!(
            broker.probe().await,
            Err(MatrixFinalUseBrokerError::BrokerUnavailable)
        ));
        Ok(())
    }
}
