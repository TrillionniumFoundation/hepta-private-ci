//! Sealed evidence inputs resolved from the store owner's private registry.
//!
//! Schema V2 adds a strictly monotonic generation and predecessor digest.  The
//! registry is not self-authorizing: production accepts V2 only when the whole
//! file digest is pinned by an independently signed recovery frontier and then
//! records that generation in the durable trust-acceptance lineage.

use std::collections::BTreeSet;
use std::fs::OpenOptions;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::EvidenceError;
use crate::EvidenceIssuerRoleV1;
use crate::EvidenceIssuerTrustBindingV1;
use crate::HeptaEvidenceStore;
use crate::canonical::canonical_json;

const MAX_REGISTRY_BYTES: u64 = 32_768;
const LEGACY_REGISTRY_SCHEMA_VERSION: u32 = 1;
const MONOTONIC_REGISTRY_SCHEMA_VERSION: u32 = 2;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OwnerRegistryV1 {
    schema_version: u32,
    agent_id: String,
    issuers: Vec<OwnerIssuerV1>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OwnerRegistryV2 {
    schema_version: u32,
    agent_id: String,
    generation: u64,
    predecessor_sha256: Option<Sha256Digest>,
    issuers: Vec<OwnerIssuerV1>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OwnerIssuerV1 {
    issuer_id: String,
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
    roles: Vec<String>,
}

struct TrustPin {
    store_path: PathBuf,
    registry_path: PathBuf,
    agent_id: String,
    registry_generation: u64,
    predecessor_sha256: Option<Sha256Digest>,
    registry_sha256: Sha256Digest,
    monotonic: bool,
}

impl TrustPin {
    fn validate(&self, store: &HeptaEvidenceStore) -> Result<(), EvidenceError> {
        if self.store_path != store.path() {
            return Err(invalid("verified evidence trust belongs to another store"));
        }
        let bytes = read_owner_registry(store.path(), &self.registry_path)?;
        if Sha256Digest::for_bytes(&bytes) != self.registry_sha256 {
            return Err(invalid(
                "evidence trust registry changed after verification; reload or re-admit the generation",
            ));
        }
        Ok(())
    }

    fn registry_generation_for_admission(&self) -> Option<u64> {
        self.monotonic.then_some(self.registry_generation)
    }

    fn registry_sha256_for_admission(&self) -> Option<&Sha256Digest> {
        self.monotonic.then_some(&self.registry_sha256)
    }
}

/// Fields are private and there is no Deserialize or raw-binding constructor.
/// The factory reads a private owner file in the SAME store's canonical home.
/// External-frontier admission remains the source of production authority.
///
/// ```compile_fail
/// use codex_hepta_evidence::{EvidenceIssuerTrustBindingV1, EvidenceTrustSnapshotView};
/// fn accepts<T: EvidenceTrustSnapshotView + ?Sized>(_: &T) {}
/// fn forged(bindings: &[EvidenceIssuerTrustBindingV1]) { accepts(bindings); }
/// ```
pub struct VerifiedEvidenceTrustSnapshot {
    pin: Arc<TrustPin>,
    issuers: Vec<OwnerIssuerV1>,
    bindings: Vec<EvidenceIssuerTrustBindingV1>,
}

pub struct VerifiedEvidenceIssuer {
    pin: Arc<TrustPin>,
    registration: IssuerRegistration,
    role: EvidenceIssuerRoleV1,
}

impl VerifiedEvidenceTrustSnapshot {
    pub fn load_owner_registry(
        store: &HeptaEvidenceStore,
        path: &Path,
        expected_agent_id: &str,
        independently_admitted_digest: Option<&Sha256Digest>,
    ) -> Result<Self, EvidenceError> {
        let bytes = read_owner_registry(store.path(), path)?;
        let registry_sha256 = Sha256Digest::for_bytes(&bytes);
        if independently_admitted_digest.is_some_and(|expected| *expected != registry_sha256) {
            return Err(invalid(
                "owner registry differs from the independently admitted trust digest",
            ));
        }
        let value: serde_json::Value = serde_json::from_slice(&bytes)
            .map_err(|error| invalid(&format!("invalid evidence owner registry: {error}")))?;
        let schema_version = value
            .get("schema_version")
            .and_then(serde_json::Value::as_u64)
            .ok_or_else(|| invalid("evidence registry has no schema_version"))?;
        let (agent_id, generation, predecessor_sha256, issuers, monotonic) = match u32::try_from(
            schema_version,
        )
        .ok()
        {
            Some(LEGACY_REGISTRY_SCHEMA_VERSION) => {
                if independently_admitted_digest.is_some() {
                    return Err(invalid(
                        "production evidence trust requires monotonic owner registry schema V2",
                    ));
                }
                let registry: OwnerRegistryV1 =
                    serde_json::from_slice(&bytes).map_err(|error| {
                        invalid(&format!("invalid legacy evidence owner registry: {error}"))
                    })?;
                if registry.schema_version != LEGACY_REGISTRY_SCHEMA_VERSION {
                    return Err(invalid("legacy evidence registry schema is invalid"));
                }
                (registry.agent_id, 0, None, registry.issuers, false)
            }
            Some(MONOTONIC_REGISTRY_SCHEMA_VERSION) => {
                let registry: OwnerRegistryV2 =
                    serde_json::from_slice(&bytes).map_err(|error| {
                        invalid(&format!(
                            "invalid monotonic evidence owner registry: {error}"
                        ))
                    })?;
                if canonical_json(&registry)? != bytes {
                    return Err(invalid(
                        "monotonic evidence registry must use canonical JSON without duplicate keys",
                    ));
                }
                if registry.schema_version != MONOTONIC_REGISTRY_SCHEMA_VERSION
                    || registry.generation == 0
                {
                    return Err(invalid(
                        "monotonic evidence registry schema or generation is invalid",
                    ));
                }
                match (registry.generation, registry.predecessor_sha256.as_ref()) {
                    (1, None) => {}
                    (1, Some(_)) | (_, None) => {
                        return Err(invalid(
                            "evidence trust predecessor is inconsistent with its generation",
                        ));
                    }
                    (_, Some(predecessor)) => {
                        Sha256Digest::parse(predecessor.as_str().to_string())
                            .map_err(EvidenceError::InvalidRecord)?;
                    }
                }
                (
                    registry.agent_id,
                    registry.generation,
                    registry.predecessor_sha256,
                    registry.issuers,
                    true,
                )
            }
            _ => return Err(invalid("unsupported evidence owner registry schema")),
        };
        if agent_id != expected_agent_id || issuers.is_empty() || issuers.len() > 32 {
            return Err(invalid(
                "evidence registry owner or issuer bound is invalid",
            ));
        }
        let mut identities = BTreeSet::new();
        let mut bindings = Vec::new();
        let mut previous_identity: Option<(&str, u64)> = None;
        for issuer in &issuers {
            let registration = registration(issuer)?;
            let identity = (issuer.issuer_id.as_str(), issuer.key_epoch);
            if !identities.insert((issuer.issuer_id.clone(), issuer.key_epoch))
                || issuer.roles.is_empty()
                || issuer.roles.len() > 16
                || (monotonic && previous_identity.is_some_and(|previous| previous >= identity))
            {
                return Err(invalid(
                    "duplicate, unordered or invalid evidence issuer role bound",
                ));
            }
            previous_identity = Some(identity);
            let mut roles = BTreeSet::new();
            let mut previous_role: Option<&str> = None;
            for role in &issuer.roles {
                let parsed =
                    EvidenceIssuerRoleV1::parse(role).map_err(EvidenceError::InvalidRecord)?;
                if !roles.insert(parsed)
                    || (monotonic
                        && previous_role.is_some_and(|previous| previous >= role.as_str()))
                {
                    return Err(invalid(
                        "evidence registry contains duplicate or unordered roles",
                    ));
                }
                previous_role = Some(role.as_str());
                if !issuer.revoked {
                    bindings.push(EvidenceIssuerTrustBindingV1::from_registration(
                        &registration,
                        parsed,
                    ));
                }
            }
        }
        Ok(Self {
            pin: Arc::new(TrustPin {
                store_path: store.path().to_path_buf(),
                registry_path: path.to_path_buf(),
                agent_id,
                registry_generation: generation,
                predecessor_sha256,
                registry_sha256,
                monotonic,
            }),
            issuers,
            bindings,
        })
    }

    pub fn agent_id(&self) -> &str {
        &self.pin.agent_id
    }

    pub fn registry_generation(&self) -> u64 {
        self.pin.registry_generation
    }

    pub fn predecessor_sha256(&self) -> Option<&Sha256Digest> {
        self.pin.predecessor_sha256.as_ref()
    }

    pub fn registry_sha256(&self) -> &Sha256Digest {
        &self.pin.registry_sha256
    }

    pub fn is_monotonic(&self) -> bool {
        self.pin.monotonic
    }

    pub fn issuer_for(
        &self,
        issuer_id: &str,
        key_epoch: u64,
        role: EvidenceIssuerRoleV1,
    ) -> Result<VerifiedEvidenceIssuer, EvidenceError> {
        let issuer = self
            .issuers
            .iter()
            .find(|issuer| issuer.issuer_id == issuer_id && issuer.key_epoch == key_epoch)
            .ok_or_else(|| invalid("evidence issuer/key epoch is not registered"))?;
        if issuer.revoked || !issuer.roles.iter().any(|value| value == role.as_str()) {
            return Err(invalid(
                "evidence issuer is revoked or is not enrolled for this role",
            ));
        }
        Ok(VerifiedEvidenceIssuer {
            pin: Arc::clone(&self.pin),
            registration: registration(issuer)?,
            role,
        })
    }
}

mod sealed {
    pub trait Sealed {}
}

pub trait EvidenceTrustSnapshotView: sealed::Sealed {
    #[doc(hidden)]
    fn evidence_bindings(&self) -> &[EvidenceIssuerTrustBindingV1];
    #[doc(hidden)]
    fn validate_store(&self, store: &HeptaEvidenceStore) -> Result<(), EvidenceError>;
}

/// Raw registrations are intentionally not implementors in product builds.
///
/// ```compile_fail
/// use codex_hepta_authbus::IssuerRegistration;
/// use codex_hepta_evidence::EvidenceIssuerView;
/// fn accepts<T: EvidenceIssuerView>(_: &T) {}
/// fn forged(issuer: &IssuerRegistration) { accepts(issuer); }
/// ```
pub trait EvidenceIssuerView: sealed::Sealed {
    #[doc(hidden)]
    fn registration(&self) -> &IssuerRegistration;
    #[doc(hidden)]
    fn validate_for(
        &self,
        store: &HeptaEvidenceStore,
        role: EvidenceIssuerRoleV1,
    ) -> Result<(), EvidenceError>;
    #[doc(hidden)]
    fn trust_registry_generation(&self) -> Option<u64>;
    #[doc(hidden)]
    fn trust_registry_sha256(&self) -> Option<&Sha256Digest>;
}

impl sealed::Sealed for VerifiedEvidenceTrustSnapshot {}
impl EvidenceTrustSnapshotView for VerifiedEvidenceTrustSnapshot {
    fn evidence_bindings(&self) -> &[EvidenceIssuerTrustBindingV1] {
        &self.bindings
    }

    fn validate_store(&self, store: &HeptaEvidenceStore) -> Result<(), EvidenceError> {
        self.pin.validate(store)
    }
}

impl sealed::Sealed for VerifiedEvidenceIssuer {}
impl EvidenceIssuerView for VerifiedEvidenceIssuer {
    fn registration(&self) -> &IssuerRegistration {
        &self.registration
    }

    fn validate_for(
        &self,
        store: &HeptaEvidenceStore,
        role: EvidenceIssuerRoleV1,
    ) -> Result<(), EvidenceError> {
        if role != self.role || self.registration.revoked {
            return Err(invalid(
                "verified evidence issuer is not valid for the requested role",
            ));
        }
        self.pin.validate(store)
    }

    fn trust_registry_generation(&self) -> Option<u64> {
        self.pin.registry_generation_for_admission()
    }

    fn trust_registry_sha256(&self) -> Option<&Sha256Digest> {
        self.pin.registry_sha256_for_admission()
    }
}

fn registration(issuer: &OwnerIssuerV1) -> Result<IssuerRegistration, EvidenceError> {
    let bytes = issuer.public_key_hex.as_bytes();
    if bytes.len() != 64 {
        return Err(invalid(
            "evidence public key must be 32-byte lowercase hexadecimal",
        ));
    }
    let digit = |byte| match byte {
        b'0'..=b'9' => Ok(byte - b'0'),
        b'a'..=b'f' => Ok(byte - b'a' + 10),
        _ => Err(invalid("evidence public key is not lowercase hexadecimal")),
    };
    let mut key = [0_u8; 32];
    for (index, pair) in bytes.chunks_exact(2).enumerate() {
        key[index] = (digit(pair[0])? << 4) | digit(pair[1])?;
    }
    Ok(IssuerRegistration {
        issuer_id: StableId::new(issuer.issuer_id.clone())
            .map_err(|error| invalid(&error.to_string()))?,
        key_epoch: Generation::new(issuer.key_epoch)
            .map_err(|error| invalid(&error.to_string()))?,
        verifying_key: VerifyingKey::from_bytes(&key)
            .map_err(|_| invalid("invalid evidence Ed25519 key"))?,
        revoked: issuer.revoked,
    })
}

#[cfg(unix)]
fn read_owner_registry(store_path: &Path, path: &Path) -> Result<Vec<u8>, EvidenceError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    let home = store_path
        .parent()
        .ok_or_else(|| invalid("evidence store has no home"))?;
    if !path.is_absolute()
        || path.parent() != Some(home)
        || home.canonicalize().map_err(io_error)? != home
    {
        return Err(invalid(
            "evidence registry must be a direct child of the canonical store home",
        ));
    }
    let directory = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_DIRECTORY | libc::O_NOFOLLOW)
        .open(home)
        .map_err(io_error)?;
    let home_before = directory.metadata().map_err(io_error)?;
    let before = std::fs::symlink_metadata(path).map_err(io_error)?;
    if !home_before.is_dir()
        || home_before.mode() & 0o077 != 0
        || !before.is_file()
        || before.nlink() != 1
        || before.uid() != home_before.uid()
        || before.mode() & 0o077 != 0
        || before.len() == 0
        || before.len() > MAX_REGISTRY_BYTES
    {
        return Err(invalid(
            "evidence registry is not a bounded private owner file",
        ));
    }
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)
        .map_err(io_error)?;
    let identity = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.uid(),
            metadata.mode(),
            metadata.nlink(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    if identity(&file.metadata().map_err(io_error)?) != identity(&before) {
        return Err(invalid("evidence registry changed during open"));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(MAX_REGISTRY_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(io_error)?;
    let after = std::fs::symlink_metadata(path).map_err(io_error)?;
    let home_after = std::fs::symlink_metadata(home).map_err(io_error)?;
    if bytes.len() as u64 != before.len()
        || identity(&after) != identity(&before)
        || identity(&file.metadata().map_err(io_error)?) != identity(&before)
        || (
            home_after.dev(),
            home_after.ino(),
            home_after.uid(),
            home_after.mode(),
        ) != (
            home_before.dev(),
            home_before.ino(),
            home_before.uid(),
            home_before.mode(),
        )
    {
        return Err(invalid(
            "evidence registry or store home changed during read",
        ));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_owner_registry(_store_path: &Path, _path: &Path) -> Result<Vec<u8>, EvidenceError> {
    Err(invalid(
        "owner-verified evidence trust requires the Unix file identity profile",
    ))
}

fn invalid(message: &str) -> EvidenceError {
    EvidenceError::InvalidRecord(message.to_string())
}

fn io_error(error: std::io::Error) -> EvidenceError {
    EvidenceError::Unavailable(error.to_string())
}

// Product builds never enable this adapter. It exists only for this crate's
// unit tests and downstream integration tests that explicitly opt into the
// non-default `test-support` feature. Ordinary and release builds retain the
// sealed owner-registry-only API.
#[cfg(any(test, feature = "test-support"))]
impl sealed::Sealed for IssuerRegistration {}
#[cfg(any(test, feature = "test-support"))]
impl EvidenceIssuerView for IssuerRegistration {
    fn registration(&self) -> &IssuerRegistration {
        self
    }

    fn validate_for(
        &self,
        _store: &HeptaEvidenceStore,
        _role: EvidenceIssuerRoleV1,
    ) -> Result<(), EvidenceError> {
        Ok(())
    }

    fn trust_registry_generation(&self) -> Option<u64> {
        None
    }

    fn trust_registry_sha256(&self) -> Option<&Sha256Digest> {
        None
    }
}

#[cfg(any(test, feature = "test-support"))]
impl sealed::Sealed for [EvidenceIssuerTrustBindingV1] {}
#[cfg(any(test, feature = "test-support"))]
impl EvidenceTrustSnapshotView for [EvidenceIssuerTrustBindingV1] {
    fn evidence_bindings(&self) -> &[EvidenceIssuerTrustBindingV1] {
        self
    }

    fn validate_store(&self, _store: &HeptaEvidenceStore) -> Result<(), EvidenceError> {
        Ok(())
    }
}

#[cfg(any(test, feature = "test-support"))]
impl<const N: usize> sealed::Sealed for [EvidenceIssuerTrustBindingV1; N] {}
#[cfg(any(test, feature = "test-support"))]
impl<const N: usize> EvidenceTrustSnapshotView for [EvidenceIssuerTrustBindingV1; N] {
    fn evidence_bindings(&self) -> &[EvidenceIssuerTrustBindingV1] {
        self
    }

    fn validate_store(&self, _store: &HeptaEvidenceStore) -> Result<(), EvidenceError> {
        Ok(())
    }
}

#[cfg(any(test, feature = "test-support"))]
impl sealed::Sealed for Vec<EvidenceIssuerTrustBindingV1> {}
#[cfg(any(test, feature = "test-support"))]
impl EvidenceTrustSnapshotView for Vec<EvidenceIssuerTrustBindingV1> {
    fn evidence_bindings(&self) -> &[EvidenceIssuerTrustBindingV1] {
        self
    }

    fn validate_store(&self, _store: &HeptaEvidenceStore) -> Result<(), EvidenceError> {
        Ok(())
    }
}
