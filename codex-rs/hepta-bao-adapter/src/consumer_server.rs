//! Production port for an independently owned, durable credential consumer.

use std::future::Future;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_types::Digest32;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde::Serialize;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixListener;
use tokio::net::UnixStream;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tokio::time::timeout;
use zeroize::Zeroizing;

use super::ConsumerPortError;
use super::consumer_owner::CredentialConsumerOwner;
use super::consumer_wire::ConsumerRequest;
use super::consumer_wire::ConsumerResponse;
use super::consumer_wire::MAX_FRAME_BYTES;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CredentialConsumerServiceConfig {
    pub schema_version: u32,
    pub consumer_id: String,
    pub socket_path: PathBuf,
    pub ipc_group_gid: u32,
    pub allowed_caller_uid: u32,
    pub database_path: PathBuf,
    pub credential_file: PathBuf,
    pub credential_sha256: [u8; 32],
    pub acknowledgement_signing_key_file: PathBuf,
    pub acknowledgement_verifying_key: [u8; 32],
    pub request_timeout_ms: u64,
    pub shutdown_drain_ms: u64,
}

impl CredentialConsumerServiceConfig {
    /// Only root-owned, non-writable policy can enroll the service's peer,
    /// credential and ACK pin. Private credential/signing files remain owned
    /// by this consumer's independent OS identity.
    pub fn load_root_owned(path: &Path) -> Result<Self, ConsumerPortError> {
        use std::io::Read;
        if !path.is_absolute()
            || path.components().any(|component| {
                matches!(
                    component,
                    std::path::Component::ParentDir | std::path::Component::CurDir
                )
            })
        {
            return Err(ConsumerPortError::Invalid);
        }
        for ancestor in path.parent().ok_or(ConsumerPortError::Invalid)?.ancestors() {
            let metadata = std::fs::symlink_metadata(ancestor).map_err(unavailable)?;
            if !metadata.is_dir()
                || metadata.file_type().is_symlink()
                || metadata.uid() != 0
                || metadata.mode() & 0o022 != 0
            {
                return Err(ConsumerPortError::Invalid);
            }
        }
        let mut file = std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(
                (rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::NONBLOCK).bits() as i32,
            )
            .open(path)
            .map_err(unavailable)?;
        let metadata = file.metadata().map_err(unavailable)?;
        if !metadata.is_file()
            || metadata.nlink() != 1
            || metadata.uid() != 0
            || metadata.mode() & 0o027 != 0
            || metadata.len() > MAX_FRAME_BYTES as u64
        {
            return Err(ConsumerPortError::Invalid);
        }
        let mut bytes = Vec::new();
        Read::take(&mut file, MAX_FRAME_BYTES as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(unavailable)?;
        if bytes.len() > MAX_FRAME_BYTES {
            return Err(ConsumerPortError::Invalid);
        }
        serde_json::from_slice(&bytes).map_err(unavailable)
    }
}

pub async fn serve_credential_consumer(
    config: CredentialConsumerServiceConfig,
    shutdown: impl Future<Output = ()>,
) -> Result<(), ConsumerPortError> {
    if config.schema_version != 1
        || config.request_timeout_ms == 0
        || config.request_timeout_ms > 5_000
        || config.shutdown_drain_ms < config.request_timeout_ms
        || config.shutdown_drain_ms > 10_000
    {
        return Err(ConsumerPortError::Invalid);
    }
    super::consumer_wire::ConsumerIntent {
        schema_version: 1,
        consumer_id: config.consumer_id.clone(),
        operation_id: "service-configuration".into(),
        semantic_sha256: [1; 32],
    }
    .validate()?;
    let credential = read_private(&config.credential_file, 8192)?;
    if credential.is_empty()
        || Digest32::of_bytes(&credential).into_array() != config.credential_sha256
    {
        return Err(ConsumerPortError::Invalid);
    }
    let signing_bytes = read_private(&config.acknowledgement_signing_key_file, 32)?;
    let signing_bytes: &[u8; 32] = signing_bytes
        .as_slice()
        .try_into()
        .map_err(|_| ConsumerPortError::Invalid)?;
    let key = SigningKey::from_bytes(signing_bytes);
    if key.verifying_key().to_bytes() != config.acknowledgement_verifying_key {
        return Err(ConsumerPortError::Invalid);
    }
    // Own the stable endpoint lock before any database access. A second
    // service cannot migrate or observe the live writer's owner first.
    let mut endpoint = BoundSocket::bind(&config.socket_path, config.ipc_group_gid)?;
    let owner = Arc::new(
        CredentialConsumerOwner::open(&config.database_path, config.acknowledgement_verifying_key)
            .await?,
    );
    let listener = endpoint.listener()?;
    let key = Arc::new(key);
    let credential = Arc::new(credential);
    let config = Arc::new(config);
    let permits = Arc::new(Semaphore::new(4));
    let mut tasks = JoinSet::new();
    tokio::pin!(shutdown);
    loop {
        tokio::select! {
            biased;
            _ = &mut shutdown => break,
            result = tasks.join_next(), if !tasks.is_empty() => {
                if result.is_some_and(|result| result.is_err()) {
                    owner.fence_writer();
                }
            }
            accepted = listener.accept() => {
                let (stream, _) = accepted.map_err(unavailable)?;
                let Ok(permit) = Arc::clone(&permits).try_acquire_owned() else {
                    drop(stream);
                    continue;
                };
                let owner = Arc::clone(&owner);
                let config = Arc::clone(&config);
                let key = Arc::clone(&key);
                let credential = Arc::clone(&credential);
                tasks.spawn(async move {
                    let _permit = permit;
                    let duration = Duration::from_millis(config.request_timeout_ms);
                    if timeout(duration, handle(
                        stream, &config, &owner, &credential, &key,
                    )).await.is_err() {
                        // An already-started transaction or reply can have
                        // committed. Keep Status available and close new effects.
                        owner.fence_writer();
                    }
                });
            }
        }
    }
    // Shutdown stops admission immediately. There is no grace period in which
    // new commands may enter. The same absolute drain covers all joins/close.
    drop(listener);
    let drain = async {
        while let Some(result) = tasks.join_next().await {
            if result.is_err() {
                owner.fence_writer();
            }
        }
        owner.close().await;
    };
    if timeout(Duration::from_millis(config.shutdown_drain_ms), drain)
        .await
        .is_err()
    {
        owner.fence_writer();
        tasks.abort_all();
        // No cancellation or timeout is reported as an absent effect.
        return Err(ConsumerPortError::Unavailable);
    }
    drop(endpoint);
    Ok(())
}

async fn handle(
    mut stream: UnixStream,
    config: &CredentialConsumerServiceConfig,
    owner: &CredentialConsumerOwner,
    credential: &[u8],
    key: &SigningKey,
) -> Result<(), ConsumerPortError> {
    if stream.peer_cred().map_err(unavailable)?.uid() != config.allowed_caller_uid {
        return Err(ConsumerPortError::Rejected);
    }
    let length = stream.read_u32().await.map_err(unavailable)? as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        return Err(ConsumerPortError::Invalid);
    }
    let mut bytes = vec![0; length];
    stream.read_exact(&mut bytes).await.map_err(unavailable)?;
    let request: ConsumerRequest = serde_json::from_slice(&bytes).map_err(unavailable)?;
    if stream.peer_cred().map_err(unavailable)?.uid() != config.allowed_caller_uid {
        return Err(ConsumerPortError::Rejected);
    }
    let response = match request {
        ConsumerRequest::Authenticate { intent, proof } => {
            if intent.consumer_id != config.consumer_id {
                return Err(ConsumerPortError::Rejected);
            }
            match owner.authenticate(&intent, credential, &proof, key).await {
                Ok(receipt) => ConsumerResponse::Confirmed { receipt },
                Err(ConsumerPortError::Conflict) => ConsumerResponse::Conflict,
                Err(ConsumerPortError::Rejected) => ConsumerResponse::Rejected,
                Err(_) => ConsumerResponse::Unknown,
            }
        }
        ConsumerRequest::Status { intent } => {
            if intent.consumer_id != config.consumer_id {
                return Err(ConsumerPortError::Rejected);
            }
            match owner.status(&intent).await {
                Ok(Some(receipt)) => ConsumerResponse::Confirmed { receipt },
                Ok(None) => ConsumerResponse::Unknown,
                Err(ConsumerPortError::Conflict) => ConsumerResponse::Conflict,
                Err(_) => ConsumerResponse::Unknown,
            }
        }
    };
    let response = serde_json::to_vec(&response).map_err(unavailable)?;
    if response.len() > MAX_FRAME_BYTES {
        return Err(ConsumerPortError::Unavailable);
    }
    stream
        .write_u32(response.len() as u32)
        .await
        .map_err(unavailable)?;
    stream.write_all(&response).await.map_err(unavailable)?;
    stream.shutdown().await.map_err(unavailable)
}

fn read_private(path: &Path, maximum: usize) -> Result<Zeroizing<Vec<u8>>, ConsumerPortError> {
    use std::io::Read;
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags((rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::NONBLOCK).bits() as i32)
        .open(path)
        .map_err(unavailable)?;
    let metadata = file.metadata().map_err(unavailable)?;
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
        || metadata.mode() & 0o077 != 0
        || metadata.len() > maximum as u64
    {
        return Err(ConsumerPortError::Invalid);
    }
    let mut bytes = Zeroizing::new(Vec::new());
    Read::take(&mut file, maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(unavailable)?;
    if bytes.len() > maximum {
        return Err(ConsumerPortError::Invalid);
    }
    Ok(bytes)
}

struct BoundSocket {
    path: PathBuf,
    identity: (u64, u64),
    _lock: std::fs::File,
    listener: Option<std::os::unix::net::UnixListener>,
}

impl BoundSocket {
    fn bind(path: &Path, group: u32) -> Result<Self, ConsumerPortError> {
        let parent = path.parent().ok_or(ConsumerPortError::Invalid)?;
        let directory = std::fs::symlink_metadata(parent).map_err(unavailable)?;
        let uid = rustix::process::geteuid().as_raw();
        if !path.is_absolute()
            || directory.file_type().is_symlink()
            || !directory.is_dir()
            || directory.uid() != uid
            || directory.gid() != group
            || directory.mode() & 0o027 != 0
        {
            return Err(ConsumerPortError::Invalid);
        }
        let lock_path = path.with_extension("stable-writer.lock");
        let lock = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .mode(0o600)
            .custom_flags(
                (rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::NONBLOCK).bits() as i32,
            )
            .open(lock_path)
            .map_err(unavailable)?;
        let metadata = lock.metadata().map_err(unavailable)?;
        if !metadata.is_file()
            || metadata.uid() != uid
            || metadata.nlink() != 1
            || metadata.mode() & 0o077 != 0
        {
            return Err(ConsumerPortError::Invalid);
        }
        lock.try_lock().map_err(unavailable)?;
        if let Ok(metadata) = std::fs::symlink_metadata(path) {
            if !metadata.file_type().is_socket() || metadata.uid() != uid || metadata.nlink() != 1 {
                return Err(ConsumerPortError::Invalid);
            }
            let address = rustix::net::SocketAddrUnix::new(path).map_err(unavailable)?;
            let descriptor = rustix::net::socket_with(
                rustix::net::AddressFamily::UNIX,
                rustix::net::SocketType::STREAM,
                rustix::net::SocketFlags::NONBLOCK | rustix::net::SocketFlags::CLOEXEC,
                None,
            )
            .map_err(unavailable)?;
            match rustix::net::connect(&descriptor, &address) {
                Err(rustix::io::Errno::CONNREFUSED) => {
                    // Stable writer ownership and this exact stale inode were
                    // verified before unlink. A busy/live socket is never removed.
                    let current = std::fs::symlink_metadata(path).map_err(unavailable)?;
                    if (metadata.dev(), metadata.ino()) != (current.dev(), current.ino()) {
                        return Err(ConsumerPortError::Unavailable);
                    }
                    std::fs::remove_file(path).map_err(unavailable)?;
                }
                _ => return Err(ConsumerPortError::Unavailable),
            }
        }
        let listener = std::os::unix::net::UnixListener::bind(path).map_err(unavailable)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o660))
            .map_err(unavailable)?;
        listener.set_nonblocking(true).map_err(unavailable)?;
        let metadata = std::fs::symlink_metadata(path).map_err(unavailable)?;
        Ok(Self {
            path: path.to_owned(),
            identity: (metadata.dev(), metadata.ino()),
            _lock: lock,
            listener: Some(listener),
        })
    }
    fn listener(&mut self) -> Result<UnixListener, ConsumerPortError> {
        UnixListener::from_std(self.listener.take().ok_or(ConsumerPortError::Unavailable)?)
            .map_err(unavailable)
    }
}

impl Drop for BoundSocket {
    fn drop(&mut self) {
        if let Ok(metadata) = std::fs::symlink_metadata(&self.path)
            && (metadata.dev(), metadata.ino()) == self.identity
            && metadata.file_type().is_socket()
        {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}

fn unavailable(_error: impl std::fmt::Display) -> ConsumerPortError {
    ConsumerPortError::Unavailable
}
