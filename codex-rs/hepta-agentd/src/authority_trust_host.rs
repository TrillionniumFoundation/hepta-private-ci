//! Agentd-owned protected time and external anti-rollback frontier for FinalUse.
//!
//! This store lives outside the Agent home rollback domain. It persists a
//! monotonic wall-clock floor and the exact FinalUse frontier under one
//! single-writer lock. It is a concrete host composition, not an attestation or
//! a substitute for target-platform qualification.

use std::fmt;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseFrontier;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;

const TRUST_SCHEMA_VERSION: u32 = 1;
const TRUST_LOCK_FILE: &str = "kernel-authority-trust.lock";
const TRUST_STATE_FILE: &str = "kernel-authority-trust.json";
const TRUST_NEXT_FILE: &str = "kernel-authority-trust.next";
const MAX_TRUST_STATE_BYTES: usize = 64 * 1024;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PersistedTrustState {
    schema_version: u32,
    owner_id: String,
    clock_floor_unix_ms: u64,
    frontier: Option<FinalUseFrontier>,
}

struct RuntimeTrustState {
    persisted: PersistedTrustState,
    failed: bool,
}

struct TrustDisk {
    root: File,
    _lock: File,
}

/// One Agentd process owns this concrete external trust store. Clones are
/// shared through `Arc` by the authority clock and frontier traits.
pub(crate) struct AgentdFinalUseTrustStore {
    state: Mutex<RuntimeTrustState>,
    disk: TrustDisk,
}

impl fmt::Debug for AgentdFinalUseTrustStore {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("AgentdFinalUseTrustStore([PROTECTED HOST STATE])")
    }
}

impl AgentdFinalUseTrustStore {
    pub(crate) fn open(
        root: &Path,
        agent_home: &Path,
        owner_id: &str,
    ) -> Result<Self, AgentdError> {
        if !identifier(owner_id) {
            return Err(invalid("owner id is invalid"));
        }
        let root = prepare_external_directory(root, agent_home)?;
        let lock_exists = entry_exists(&root, TRUST_LOCK_FILE)?;
        let state_exists = entry_exists(&root, TRUST_STATE_FILE)?;
        if lock_exists != state_exists {
            return Err(recovery_required(
                "trust initialization is incomplete; operator recovery is required",
            ));
        }
        let lock = open_private(&root, TRUST_LOCK_FILE, Access::Create)?;
        lock.try_lock()
            .map_err(|_| recovery_required("another authority trust owner holds the lock"))?;
        let disk = TrustDisk { root, _lock: lock };
        let persisted = if state_exists {
            let persisted = disk.read()?;
            validate_persisted(&persisted, owner_id)?;
            let now = system_time_millis().map_err(|_| {
                recovery_required("the host clock is unavailable while opening authority trust")
            })?;
            if now < persisted.clock_floor_unix_ms {
                return Err(recovery_required(
                    "the host clock moved behind the persisted authority floor",
                ));
            }
            persisted
        } else {
            let now = system_time_millis().map_err(|_| {
                recovery_required(
                    "the host clock is unavailable while initializing authority trust",
                )
            })?;
            let persisted = PersistedTrustState {
                schema_version: TRUST_SCHEMA_VERSION,
                owner_id: owner_id.to_owned(),
                clock_floor_unix_ms: now,
                frontier: None,
            };
            disk.persist(&persisted)?;
            persisted
        };
        Ok(Self {
            state: Mutex::new(RuntimeTrustState {
                persisted,
                failed: false,
            }),
            disk,
        })
    }

    /// Initialize the external frontier only for a never-initialized local
    /// authority owner. An existing external frontier is never reset from
    /// configuration or a restored local directory.
    pub(crate) fn ensure_initial_frontier(
        &self,
        initial: FinalUseFrontier,
        local_authority_uninitialized: bool,
    ) -> Result<(), AgentdError> {
        if !valid_frontier(initial) {
            return Err(invalid("initial FinalUse frontier is invalid"));
        }
        let mut state = self
            .state
            .lock()
            .map_err(|_| recovery_required("authority trust mutex is poisoned"))?;
        if state.failed {
            return Err(recovery_required("authority trust owner is fenced"));
        }
        if state.persisted.frontier.is_some() {
            return Ok(());
        }
        if !local_authority_uninitialized {
            return Err(recovery_required(
                "external frontier is missing for an initialized local authority",
            ));
        }
        let mut next = state.persisted.clone();
        next.frontier = Some(initial);
        if self.disk.persist(&next).is_err() {
            state.failed = true;
            return Err(recovery_required(
                "failed to durably initialize the external authority frontier",
            ));
        }
        state.persisted = next;
        Ok(())
    }

    #[cfg(test)]
    fn persisted_for_test(&self) -> PersistedTrustState {
        self.state.lock().unwrap().persisted.clone()
    }

    #[cfg(test)]
    fn replace_for_test(&self, persisted: PersistedTrustState) {
        self.disk.persist(&persisted).unwrap();
        self.state.lock().unwrap().persisted = persisted;
    }
}

impl AuthorityClock for AgentdFinalUseTrustStore {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if state.failed {
            return Err(AuthorityTrustError::Unavailable);
        }
        let now = system_time_millis()?;
        if now < state.persisted.clock_floor_unix_ms {
            state.failed = true;
            return Err(AuthorityTrustError::Unavailable);
        }
        if now > state.persisted.clock_floor_unix_ms {
            let mut next = state.persisted.clone();
            next.clock_floor_unix_ms = now;
            if self.disk.persist(&next).is_err() {
                state.failed = true;
                return Err(AuthorityTrustError::Unavailable);
            }
            state.persisted = next;
        }
        Ok(now)
    }
}

impl AuthorityFrontierStore<FinalUseFrontier> for AgentdFinalUseTrustStore {
    fn load(&self, owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        let state = self
            .state
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if state.failed {
            return Err(AuthorityTrustError::Unavailable);
        }
        if state.persisted.owner_id != owner_id {
            return Err(AuthorityTrustError::Invalid);
        }
        state.persisted.frontier.ok_or(AuthorityTrustError::Invalid)
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        if !valid_frontier(*next) {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut state = self
            .state
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if state.failed {
            return Err(AuthorityTrustError::Unavailable);
        }
        if state.persisted.owner_id != owner_id {
            return Err(AuthorityTrustError::Invalid);
        }
        let current = state
            .persisted
            .frontier
            .ok_or(AuthorityTrustError::Invalid)?;
        if current != *expected {
            return Err(AuthorityTrustError::Conflict);
        }
        if next.authority_epoch < current.authority_epoch
            || next.revocation_revision < current.revocation_revision
        {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut persisted = state.persisted.clone();
        persisted.frontier = Some(*next);
        if self.disk.persist(&persisted).is_err() {
            state.failed = true;
            return Err(AuthorityTrustError::Unavailable);
        }
        state.persisted = persisted;
        Ok(())
    }
}

impl TrustDisk {
    fn read(&self) -> Result<PersistedTrustState, AgentdError> {
        let mut bytes = Vec::new();
        open_private(&self.root, TRUST_STATE_FILE, Access::Read)?
            .take((MAX_TRUST_STATE_BYTES + 1) as u64)
            .read_to_end(&mut bytes)?;
        if bytes.len() > MAX_TRUST_STATE_BYTES {
            return Err(recovery_required("authority trust state exceeds its bound"));
        }
        serde_json::from_slice(&bytes)
            .map_err(|error| recovery_required(&format!("invalid authority trust state: {error}")))
    }

    fn persist(&self, state: &PersistedTrustState) -> Result<(), AgentdError> {
        let bytes = serde_json::to_vec(state)?;
        if bytes.len() > MAX_TRUST_STATE_BYTES {
            return Err(invalid("authority trust state exceeds its bound"));
        }
        let mut file = open_private(&self.root, TRUST_NEXT_FILE, Access::Create)?;
        file.set_len(0)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        replace_state(&self.root)?;
        self.root.sync_all()?;
        Ok(())
    }
}

fn validate_persisted(state: &PersistedTrustState, owner_id: &str) -> Result<(), AgentdError> {
    if state.schema_version != TRUST_SCHEMA_VERSION
        || state.owner_id != owner_id
        || state.clock_floor_unix_ms == 0
        || state
            .frontier
            .is_some_and(|frontier| !valid_frontier(frontier))
    {
        return Err(recovery_required(
            "authority trust state schema, owner, clock or frontier is invalid",
        ));
    }
    Ok(())
}

fn valid_frontier(frontier: FinalUseFrontier) -> bool {
    frontier.authority_epoch > 0
        && frontier.revocation_revision > 0
        && frontier.state_sha256 != [0; 32]
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
}

fn system_time_millis() -> Result<u64, AuthorityTrustError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AuthorityTrustError::Unavailable)?
        .as_millis();
    u64::try_from(millis).map_err(|_| AuthorityTrustError::Unavailable)
}

enum Access {
    Read,
    Create,
}

#[cfg(unix)]
fn prepare_external_directory(root: &Path, agent_home: &Path) -> Result<File, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !root.is_absolute() || !agent_home.is_absolute() {
        return Err(invalid("trust and Agent home paths must be absolute"));
    }
    let canonical_root = root.canonicalize()?;
    let canonical_home = agent_home.canonicalize()?;
    if canonical_root != root
        || canonical_root.starts_with(&canonical_home)
        || canonical_home.starts_with(&canonical_root)
    {
        return Err(invalid(
            "authority trust root must be canonical and outside the Agent home rollback domain",
        ));
    }
    let directory: File = rustix::fs::open(
        root,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| invalid("authority trust root cannot be opened safely"))?
    .into();
    let metadata = directory.metadata()?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(invalid(
            "authority trust root must be an owner-only directory",
        ));
    }
    Ok(directory)
}

#[cfg(not(unix))]
fn prepare_external_directory(_root: &Path, _agent_home: &Path) -> Result<File, AgentdError> {
    Err(invalid(
        "the Agentd authority trust host currently requires Unix file identity semantics",
    ))
}

#[cfg(unix)]
fn open_private(directory: &File, name: &str, access: Access) -> Result<File, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    let flags = match access {
        Access::Read => rustix::fs::OFlags::RDONLY,
        Access::Create => rustix::fs::OFlags::RDWR | rustix::fs::OFlags::CREATE,
    } | rustix::fs::OFlags::NOFOLLOW
        | rustix::fs::OFlags::CLOEXEC;
    let file: File = rustix::fs::openat(
        directory,
        name,
        flags,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
    )
    .map_err(|_| recovery_required("authority trust file cannot be opened safely"))?
    .into();
    let metadata = file.metadata()?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(recovery_required(
            "authority trust file is not private owner-controlled state",
        ));
    }
    Ok(file)
}

#[cfg(not(unix))]
fn open_private(_directory: &File, _name: &str, _access: Access) -> Result<File, AgentdError> {
    Err(invalid(
        "the Agentd authority trust host currently requires Unix file identity semantics",
    ))
}

#[cfg(unix)]
fn entry_exists(directory: &File, name: &str) -> Result<bool, AgentdError> {
    match rustix::fs::statat(directory, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(_) => Err(recovery_required(
            "authority trust directory cannot be inspected",
        )),
    }
}

#[cfg(not(unix))]
fn entry_exists(_directory: &File, _name: &str) -> Result<bool, AgentdError> {
    Err(invalid(
        "the Agentd authority trust host currently requires Unix file identity semantics",
    ))
}

#[cfg(unix)]
fn replace_state(directory: &File) -> Result<(), AgentdError> {
    rustix::fs::renameat(directory, TRUST_NEXT_FILE, directory, TRUST_STATE_FILE)
        .map_err(|_| recovery_required("authority trust state replacement failed"))
}

#[cfg(not(unix))]
fn replace_state(_directory: &File) -> Result<(), AgentdError> {
    Err(invalid(
        "the Agentd authority trust host currently requires Unix file identity semantics",
    ))
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.authority host trust: {message}"))
}

fn recovery_required(message: &str) -> AgentdError {
    AgentdError::Protocol(format!(
        "kernel.authority host trust recovery_required: {message}"
    ))
}

#[cfg(all(test, unix))]
mod tests {
    use std::collections::BTreeSet;
    use std::fs;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::Arc;

    use codex_hepta_contracts::FinalUseAuthority;
    use codex_hepta_contracts::FinalUseBinding;
    use codex_hepta_contracts::FinalUseError;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseIssuerTrustKey;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use super::*;

    fn roots() -> (tempfile::TempDir, std::path::PathBuf, std::path::PathBuf) {
        let temp = tempfile::tempdir().unwrap();
        let home = temp.path().join("agent-home");
        let trust = temp.path().join("authority-trust");
        fs::create_dir(&home).unwrap();
        fs::create_dir(&trust).unwrap();
        fs::set_permissions(&home, fs::Permissions::from_mode(0o700)).unwrap();
        fs::set_permissions(&trust, fs::Permissions::from_mode(0o700)).unwrap();
        (
            temp,
            home.canonicalize().unwrap(),
            trust.canonicalize().unwrap(),
        )
    }

    fn frontier(revision: u64, marker: u8) -> FinalUseFrontier {
        FinalUseFrontier {
            authority_epoch: 7,
            revocation_revision: revision,
            state_sha256: [marker; 32],
        }
    }

    #[test]
    fn external_frontier_is_exact_cas_and_survives_restart() {
        let (_temp, home, trust) = roots();
        let store = Arc::new(AgentdFinalUseTrustStore::open(&trust, &home, "owner").unwrap());
        store.ensure_initial_frontier(frontier(1, 1), true).unwrap();
        assert_eq!(store.load("owner").unwrap(), frontier(1, 1));
        store
            .compare_and_set("owner", &frontier(1, 1), &frontier(2, 2))
            .unwrap();
        assert_eq!(
            store.compare_and_set("owner", &frontier(1, 1), &frontier(3, 3)),
            Err(AuthorityTrustError::Conflict)
        );
        drop(store);
        let reopened = AgentdFinalUseTrustStore::open(&trust, &home, "owner").unwrap();
        assert_eq!(reopened.load("owner").unwrap(), frontier(2, 2));
    }

    #[test]
    fn single_writer_lock_fences_concurrent_owner_and_hands_off_after_drop() {
        let (_temp, home, trust) = roots();
        let first = AgentdFinalUseTrustStore::open(&trust, &home, "owner").unwrap();
        assert!(AgentdFinalUseTrustStore::open(&trust, &home, "owner").is_err());
        drop(first);
        AgentdFinalUseTrustStore::open(&trust, &home, "owner").unwrap();
    }

    #[test]
    fn restored_local_authority_snapshot_is_rejected_by_external_frontier() {
        let (_temp, home, trust) = roots();
        let authority_root = home.join("final-use-authority");
        fs::create_dir(&authority_root).unwrap();
        fs::set_permissions(&authority_root, fs::Permissions::from_mode(0o700)).unwrap();

        let signer = SigningKey::from_bytes(&[41; 32]);
        let head = FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let initial = FinalUseFrontier::for_initial_head(&head).unwrap();
        let trust_store = Arc::new(AgentdFinalUseTrustStore::open(&trust, &home, "owner").unwrap());
        trust_store.ensure_initial_frontier(initial, true).unwrap();
        let now = trust_store.now_unix_ms().unwrap();
        let authority = FinalUseAuthority::open_state_dir_with_issuer_keys(
            &authority_root,
            "owner".to_string(),
            vec![FinalUseIssuerTrustKey {
                key_id: "issuer-a".to_string(),
                verifying_key: signer.verifying_key().to_bytes(),
                not_before_authority_epoch: 1,
                not_after_authority_epoch: u64::MAX,
            }],
            head.clone(),
            trust_store.clone(),
            trust_store.clone(),
        )
        .unwrap();
        let claims_path = authority_root.join("authority.claims");
        let claims_before = fs::read(&claims_path).unwrap();
        let binding = FinalUseBinding {
            subject_id: "agent-one".to_string(),
            destination_id: "provider:fixture".to_string(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        };
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "owner".to_string(),
            authority_epoch: 7,
            grant_id: "grant-one".to_string(),
            nonce: [4; 32],
            binding: binding.clone(),
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 60_000,
        };
        let signed = SignedFinalUseGrant {
            signature: signer
                .sign(&grant.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            grant,
        };
        let token = authority.claim(&signed, &binding).unwrap();
        drop(token);
        drop(authority);
        drop(trust_store);

        fs::write(&claims_path, claims_before).unwrap();
        fs::set_permissions(&claims_path, fs::Permissions::from_mode(0o600)).unwrap();

        let reopened_trust =
            Arc::new(AgentdFinalUseTrustStore::open(&trust, &home, "owner").unwrap());
        let error = FinalUseAuthority::open_state_dir_with_issuer_keys(
            &authority_root,
            "owner".to_string(),
            vec![FinalUseIssuerTrustKey {
                key_id: "issuer-a".to_string(),
                verifying_key: signer.verifying_key().to_bytes(),
                not_before_authority_epoch: 1,
                not_after_authority_epoch: u64::MAX,
            }],
            head,
            reopened_trust.clone(),
            reopened_trust,
        )
        .unwrap_err();
        assert_eq!(error, FinalUseError::AntiRollbackViolation);
    }

    #[test]
    fn missing_frontier_cannot_be_created_for_existing_local_authority() {
        let (_temp, home, trust) = roots();
        let store = AgentdFinalUseTrustStore::open(&trust, &home, "owner").unwrap();
        assert!(
            store
                .ensure_initial_frontier(frontier(1, 1), false)
                .is_err()
        );
    }

    #[test]
    fn persisted_future_clock_floor_fails_closed_on_reopen() {
        let (_temp, home, trust) = roots();
        let store = AgentdFinalUseTrustStore::open(&trust, &home, "owner").unwrap();
        let mut persisted = store.persisted_for_test();
        persisted.clock_floor_unix_ms = system_time_millis().unwrap() + 3_600_000;
        store.replace_for_test(persisted);
        drop(store);
        assert!(AgentdFinalUseTrustStore::open(&trust, &home, "owner").is_err());
    }
}
