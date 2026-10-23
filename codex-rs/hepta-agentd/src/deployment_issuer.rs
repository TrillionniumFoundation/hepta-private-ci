//! A user-provisioned Linux final-use issuer using the original grant protocol.
//!
//! Keep this service and its private directory outside Agentd's rollback set.
//! The host explicitly chooses a bounded subject/destination/scope policy;
//! renderer requests cannot create policy or install a trust key.

use std::collections::BTreeSet;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde::Serialize;

use crate::DeploymentFrontierStore;

#[path = "deployment_authbus.rs"]
mod authbus;

const STATE_OWNER: &str = "local-final-use-issuer";
const EXCHANGE_DEADLINE: Duration = Duration::from_secs(2);

/// Host policy permits only this exact original owner, target and scope.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DeploymentGrantPolicy {
    pub subject_id: String,
    pub destination_id: String,
    pub scope_sha256: [u8; 32],
    pub lifetime_ms: u64,
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct IssuerState {
    signer_id: String,
    policies: Vec<DeploymentGrantPolicy>,
    head: FinalUseRevocations,
    sequence: u64,
}

/// Independent signer; private key bytes are neither serialized nor logged.
pub struct DeploymentFinalUseIssuer {
    store: DeploymentFrontierStore<IssuerState>,
    key: SigningKey,
    clock: Arc<dyn AuthorityClock>,
    request_lock: Mutex<()>,
}

/// Read-only view of the independently retained issuer revocation head.
/// It never opens, holds, or derives a private signing key. The trusted host
/// pins its public verification key separately during provisioning.
pub struct DeploymentIssuerObserver {
    store: DeploymentFrontierStore<IssuerState>,
}

impl DeploymentIssuerObserver {
    pub fn open(directory: &Path) -> io::Result<Self> {
        let observer = Self {
            store: DeploymentFrontierStore::open(directory)?,
        };
        observer.revocations()?;
        Ok(observer)
    }

    pub fn revocations(&self) -> io::Result<FinalUseRevocations> {
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        if state.head.authority_epoch == 0 || state.head.revision == 0 {
            return Err(io::Error::other("invalid issuer revocation head"));
        }
        Ok(state.head)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u32,
    operation: String,
    binding: FinalUseBinding,
}

#[derive(Serialize)]
struct Response {
    schema_version: u32,
    revocations: FinalUseRevocations,
    grant: Option<SignedFinalUseGrant>,
    denial_reason: Option<&'static str>,
}

fn random_bytes() -> io::Result<[u8; 32]> {
    let mut bytes = [0; 32];
    File::open("/dev/urandom")?.read_exact(&mut bytes)?;
    Ok(bytes)
}

impl DeploymentFinalUseIssuer {
    /// Provision once under the user's explicit host policy. Existing paths,
    /// including incomplete previous provisioning, are never overwritten.
    pub fn create(
        directory: &Path,
        signer_id: String,
        policies: Vec<DeploymentGrantPolicy>,
        clock: Arc<dyn AuthorityClock>,
    ) -> io::Result<Self> {
        if signer_id.is_empty()
            || signer_id.len() > 64
            || policies.is_empty()
            || policies.len() > 16
        {
            return Err(io::Error::other("invalid local issuer policy"));
        }
        for policy in &policies {
            let probe = FinalUseGrant {
                schema_version: 1,
                signer_id: signer_id.clone(),
                authority_epoch: 1,
                grant_id: "policy-validation".into(),
                nonce: [1; 32],
                binding: FinalUseBinding {
                    subject_id: policy.subject_id.clone(),
                    destination_id: policy.destination_id.clone(),
                    request_sha256: [1; 32],
                    scope_sha256: policy.scope_sha256,
                    payload_sha256: [1; 32],
                },
                not_before_unix_ms: 1,
                expires_at_unix_ms: 1_u64
                    .checked_add(policy.lifetime_ms)
                    .ok_or_else(|| io::Error::other("invalid lifetime"))?,
            };
            probe.signing_bytes().map_err(io::Error::other)?;
        }
        clock.now_unix_ms().map_err(io::Error::other)?;
        let store = DeploymentFrontierStore::create(directory)?;
        let key_bytes = random_bytes()?;
        let mut key_file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(directory.join("issuer.key"))?;
        key_file.write_all(&key_bytes)?;
        key_file.sync_all()?;
        store.provision(
            STATE_OWNER,
            &IssuerState {
                signer_id,
                policies,
                head: FinalUseRevocations {
                    authority_epoch: 1,
                    revision: 1,
                    revoked_grant_ids: BTreeSet::new(),
                },
                sequence: 0,
            },
        )?;
        File::open(directory)?.sync_all()?;
        Self::open(directory, clock)
    }

    /// Open the same trust identity. Missing state/key material is an error.
    pub fn open(directory: &Path, clock: Arc<dyn AuthorityClock>) -> io::Result<Self> {
        let store = DeploymentFrontierStore::open(directory)?;
        let state: IssuerState = store.load(STATE_OWNER).map_err(io::Error::other)?;
        let mut file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(directory.join("issuer.key"))?;
        let metadata = file.metadata()?;
        // SAFETY: geteuid has no arguments or borrowed memory.
        let uid = unsafe { libc::geteuid() };
        if !metadata.is_file()
            || metadata.uid() != uid
            || metadata.mode() & 0o777 != 0o600
            || metadata.nlink() != 1
            || metadata.len() != 32
        {
            return Err(io::Error::other(
                "issuer key must be private owned 0600 with exact length",
            ));
        }
        let mut bytes = [0; 32];
        file.read_exact(&mut bytes)?;
        if state.head.authority_epoch == 0 || state.head.revision == 0 {
            return Err(io::Error::other("invalid issuer epoch"));
        }
        clock.now_unix_ms().map_err(io::Error::other)?;
        Ok(Self {
            store,
            key: SigningKey::from_bytes(&bytes),
            clock,
            request_lock: Mutex::new(()),
        })
    }

    pub fn trust_key(&self) -> io::Result<FinalUseIssuerTrustKey> {
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        Ok(FinalUseIssuerTrustKey {
            key_id: state.signer_id,
            verifying_key: self.key.verifying_key().to_bytes(),
            not_before_authority_epoch: state.head.authority_epoch,
            not_after_authority_epoch: state.head.authority_epoch,
        })
    }

    pub fn revocations(&self) -> io::Result<FinalUseRevocations> {
        self.store
            .load(STATE_OWNER)
            .map(|state| state.head)
            .map_err(io::Error::other)
    }

    /// Produce a grant only for the provisioned scope. The counter is durable
    /// before reply; interrupted delivery can lose an id, never reuse one.
    pub fn issue(&self, binding: &FinalUseBinding) -> io::Result<Option<SignedFinalUseGrant>> {
        let _guard = self
            .request_lock
            .lock()
            .map_err(|_| io::Error::other("issuer fenced"))?;
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        let Some(policy) = state.policies.iter().find(|policy| {
            policy.subject_id == binding.subject_id
                && policy.destination_id == binding.destination_id
                && policy.scope_sha256 == binding.scope_sha256
        }) else {
            return Ok(None);
        };
        let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
        let mut next = state.clone();
        next.sequence = next
            .sequence
            .checked_add(1)
            .ok_or_else(|| io::Error::other("issuer counter exhausted"))?;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: state.signer_id.clone(),
            authority_epoch: state.head.authority_epoch,
            grant_id: format!(
                "{}:{}:{}",
                state.signer_id, state.head.authority_epoch, next.sequence
            ),
            nonce: random_bytes()?,
            binding: binding.clone(),
            not_before_unix_ms: now,
            expires_at_unix_ms: now
                .checked_add(policy.lifetime_ms)
                .ok_or_else(|| io::Error::other("issuer clock overflow"))?,
        };
        let bytes = grant.signing_bytes().map_err(io::Error::other)?;
        self.store
            .compare_and_set(STATE_OWNER, &state, &next)
            .map_err(io::Error::other)?;
        Ok(Some(SignedFinalUseGrant {
            grant,
            signature: self.key.sign(&bytes).to_bytes().to_vec(),
        }))
    }

    /// Revoke an issued id durably. The trusted host must feed this head through
    /// the original authenticated revocation path; unsigned RPC reply heads
    /// must never update FinalUseAuthority on their own.
    pub fn revoke(&self, grant_id: &str) -> io::Result<FinalUseRevocations> {
        let _guard = self
            .request_lock
            .lock()
            .map_err(|_| io::Error::other("issuer fenced"))?;
        if grant_id.is_empty()
            || grant_id.len() > 128
            || !grant_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
        {
            return Err(io::Error::other("invalid grant id"));
        }
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        let mut next = state.clone();
        if next.head.revoked_grant_ids.contains(grant_id) {
            return Ok(next.head);
        }
        if next.head.revoked_grant_ids.len() >= 256 {
            return Err(io::Error::other(
                "local revocation capacity exhausted; rotate epoch explicitly",
            ));
        }
        next.head.revoked_grant_ids.insert(grant_id.to_string());
        next.head.revision = next
            .head
            .revision
            .checked_add(1)
            .ok_or_else(|| io::Error::other("revocation counter exhausted"))?;
        self.store
            .compare_and_set(STATE_OWNER, &state, &next)
            .map_err(io::Error::other)?;
        Ok(next.head)
    }

    /// Serve one original u32-BE request over a host-authenticated descriptor.
    /// Idle time before the first byte does not consume an exchange deadline.
    /// Returns false on orderly peer close. A malformed exchange closes at the
    /// caller; it is never retried by this service.
    pub fn serve_next(&self, stream: &mut UnixStream) -> io::Result<bool> {
        stream.set_read_timeout(None)?;
        let mut length = [0; 4];
        match stream.read(&mut length[..1])? {
            0 => return Ok(false),
            1 => {}
            _ => unreachable!(),
        }
        let deadline = Instant::now() + EXCHANGE_DEADLINE;
        read_until(stream, &mut length[1..], deadline)?;
        let length = u32::from_be_bytes(length) as usize;
        if length == 0 || length > 16 * 1024 {
            return Err(io::Error::other("invalid issuer request length"));
        }
        let mut bytes = vec![0; length];
        read_until(stream, &mut bytes, deadline)?;
        let request: Request = serde_json::from_slice(&bytes)?;
        if request.schema_version != 1 || request.operation != "runtime.agentd.production_operation"
        {
            return Err(io::Error::other("invalid issuer operation"));
        }
        let grant = self.issue(&request.binding)?;
        let response = Response {
            schema_version: 1,
            revocations: self.revocations()?,
            denial_reason: if grant.is_none() {
                Some("outside configured host scope")
            } else {
                None
            },
            grant,
        };
        let response = serde_json::to_vec(&response)?;
        if response.len() > 64 * 1024 {
            return Err(io::Error::other("issuer response is oversized"));
        }
        write_until(stream, &(response.len() as u32).to_be_bytes(), deadline)?;
        write_until(stream, &response, deadline)?;
        Ok(true)
    }
}

fn remaining(deadline: Instant) -> io::Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero())
        .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "issuer deadline elapsed"))
}

fn read_until(stream: &mut UnixStream, mut bytes: &mut [u8], deadline: Instant) -> io::Result<()> {
    while !bytes.is_empty() {
        stream.set_read_timeout(Some(remaining(deadline)?))?;
        match stream.read(bytes) {
            Ok(0) => {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "issuer peer closed",
                ));
            }
            Ok(count) => bytes = &mut bytes[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

fn write_until(stream: &mut UnixStream, mut bytes: &[u8], deadline: Instant) -> io::Result<()> {
    while !bytes.is_empty() {
        stream.set_write_timeout(Some(remaining(deadline)?))?;
        match stream.write(bytes) {
            Ok(0) => {
                return Err(io::Error::new(
                    io::ErrorKind::WriteZero,
                    "issuer peer closed",
                ));
            }
            Ok(count) => bytes = &bytes[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "deployment_issuer_tests.rs"]
mod tests;
