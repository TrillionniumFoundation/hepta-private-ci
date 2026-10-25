//! Root-retained real Ed25519 issuer, constrained by the original lease owner.

use super::*;
use crate::AuthorityClock;
use crate::FinalUseBinding;
use crate::FinalUseError;
use crate::FinalUseGrant;
use crate::FinalUseIssuerTrustKey;
use crate::SignedFinalUseGrant;
use crate::authority_lease::AuthorityLeaseBinding;
use crate::authority_lease::AuthorityLeaseError;
use crate::authority_lease::AuthorityLeaseVerifier;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use zeroize::Zeroize;
use zeroize::Zeroizing;

const OPERATION_CLASS: &str = "runtime.agentd.production_operation";
const GRANT_LIFETIME_MS: u64 = 30_000;

/// Fail-closed backend diagnostics; no secret or request is included.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HostIssuerError {
    Trust(AuthorityTrustError),
    Lease(AuthorityLeaseError),
    FinalUse(FinalUseError),
}

impl std::fmt::Display for HostIssuerError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for HostIssuerError {}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct KeyRecord {
    schema: u32,
    signer_id: String,
    key_id: String,
    authority_epoch: u64,
    seed: [u8; 32],
}

impl Drop for KeyRecord {
    fn drop(&mut self) {
        self.seed.zeroize();
    }
}

/// A new local issuer under the host's root boundary. Initialization creates
/// fresh OS-random key material; opening never regenerates a missing key.
/// It creates neither CognitiveStore cuts nor leases, and owns no effect log.
pub struct HostFinalUseIssuer {
    signing_key: SigningKey,
    signer_id: String,
    key_id: String,
    authority_epoch: u64,
    clock: Arc<dyn AuthorityClock>,
}

impl HostFinalUseIssuer {
    pub fn initialize(
        root: Arc<RootAuthorityDirectory>,
        signer_id: String,
        key_id: String,
        authority_epoch: u64,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, AuthorityTrustError> {
        let name = key_name(&signer_id, &key_id, authority_epoch)?;
        let _lock = root.lock(&format!("{name}.lock"))?;
        if root.exists(&name)? {
            return Err(AuthorityTrustError::Conflict);
        }
        clock.now_unix_ms()?;
        let record = KeyRecord {
            schema: 1,
            signer_id,
            key_id,
            authority_epoch,
            seed: *random_bytes()?,
        };
        let bytes =
            Zeroizing::new(serde_json::to_vec(&record).map_err(|_| AuthorityTrustError::Invalid)?);
        root.replace(&format!("{name}.next"), &name, &bytes)?;
        Ok(Self::from_record(&record, clock))
    }

    pub fn open(
        root: Arc<RootAuthorityDirectory>,
        signer_id: String,
        key_id: String,
        authority_epoch: u64,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, AuthorityTrustError> {
        let name = key_name(&signer_id, &key_id, authority_epoch)?;
        let file = root.open_private(&name, OFlags::RDONLY)?;
        let mut bytes = Zeroizing::new(Vec::new());
        file.take(MAX_RECORD_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(unavailable)?;
        if bytes.len() as u64 > MAX_RECORD_BYTES {
            return Err(AuthorityTrustError::Invalid);
        }
        let record: KeyRecord =
            serde_json::from_slice(&bytes).map_err(|_| AuthorityTrustError::Invalid)?;
        if record.schema != 1
            || record.signer_id != signer_id
            || record.key_id != key_id
            || record.authority_epoch != authority_epoch
            || record.seed == [0; 32]
        {
            return Err(AuthorityTrustError::Invalid);
        }
        clock.now_unix_ms()?;
        Ok(Self::from_record(&record, clock))
    }

    fn from_record(record: &KeyRecord, clock: Arc<dyn AuthorityClock>) -> Self {
        Self {
            signing_key: SigningKey::from_bytes(&record.seed),
            signer_id: record.signer_id.clone(),
            key_id: record.key_id.clone(),
            authority_epoch: record.authority_epoch,
            clock,
        }
    }

    pub fn trust_key(&self) -> FinalUseIssuerTrustKey {
        FinalUseIssuerTrustKey {
            key_id: self.key_id.clone(),
            verifying_key: self.signing_key.verifying_key().to_bytes(),
            not_before_authority_epoch: self.authority_epoch,
            not_after_authority_epoch: self.authority_epoch,
        }
    }

    /// Sign one exact binding only under an existing live original lease.
    /// No lease is inferred from the caller's binding. Lease policy/creation is
    /// a separate root administration action. Consumers still use the original
    /// FinalUse verifier, nonce claim and effect-entry boundary. Revocation of a
    /// lease stops new issuance; already issued grants also need the original
    /// FinalUse revocation protocol (or expire in at most thirty seconds).
    pub fn issue(
        &self,
        leases: &AuthorityLeaseVerifier,
        lease_id: &str,
        lease_revision: u64,
        binding: &FinalUseBinding,
    ) -> Result<SignedFinalUseGrant, HostIssuerError> {
        let expected = AuthorityLeaseBinding {
            principal_id: binding.subject_id.clone(),
            operation_class: OPERATION_CLASS.into(),
            destination_id: binding.destination_id.clone(),
            scope_sha256: binding.scope_sha256,
            payload_sha256: binding.payload_sha256,
        };
        let lease = leases
            .read_lease(lease_id)
            .map_err(HostIssuerError::Lease)?
            .ok_or(HostIssuerError::Lease(AuthorityLeaseError::LeaseNotFound))?
            .lease;
        // The requested revision may become current between read_lease and
        // verify_use. Expiry/epoch must come from that exact revision; the
        // original lease owner makes same-revision contents immutable.
        if lease.revision != lease_revision {
            return Err(HostIssuerError::Lease(
                AuthorityLeaseError::RevisionMismatch,
            ));
        }
        let token = leases
            .verify_use(lease_id, lease_revision, &expected)
            .map_err(HostIssuerError::Lease)?;
        leases
            .with_dispatch_boundary(token, &expected, || {
                if lease.authority_epoch != self.authority_epoch {
                    return Err(HostIssuerError::Trust(AuthorityTrustError::Invalid));
                }
                let now = self.clock.now_unix_ms().map_err(HostIssuerError::Trust)?;
                let expires = now
                    .checked_add(GRANT_LIFETIME_MS)
                    .ok_or(HostIssuerError::Trust(AuthorityTrustError::Invalid))?
                    .min(lease.expires_at_unix_ms);
                let nonce = *random_bytes().map_err(HostIssuerError::Trust)?;
                let suffix: String = nonce.iter().map(|byte| format!("{byte:02x}")).collect();
                let grant = FinalUseGrant {
                    schema_version: 1,
                    signer_id: self.signer_id.clone(),
                    authority_epoch: self.authority_epoch,
                    grant_id: format!("local-{suffix}"),
                    nonce,
                    binding: binding.clone(),
                    not_before_unix_ms: now,
                    expires_at_unix_ms: expires,
                };
                let signature = self
                    .signing_key
                    .sign(&grant.signing_bytes().map_err(HostIssuerError::FinalUse)?)
                    .to_bytes()
                    .to_vec();
                if self.clock.now_unix_ms().map_err(HostIssuerError::Trust)? >= expires {
                    return Err(HostIssuerError::FinalUse(FinalUseError::Expired));
                }
                Ok(SignedFinalUseGrant { grant, signature })
            })
            .map_err(HostIssuerError::Lease)?
    }
}

fn key_name(
    signer_id: &str,
    key_id: &str,
    authority_epoch: u64,
) -> Result<String, AuthorityTrustError> {
    let identifier = |value: &str| {
        !value.is_empty()
            && value.len() <= 128
            && value
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
    };
    if !identifier(signer_id) || !identifier(key_id) || authority_epoch == 0 {
        return Err(AuthorityTrustError::Invalid);
    }
    let digest = Sha256::digest(
        serde_json::to_vec(&(signer_id, key_id, authority_epoch))
            .map_err(|_| AuthorityTrustError::Invalid)?,
    );
    let suffix: String = digest.iter().map(|byte| format!("{byte:02x}")).collect();
    Ok(format!("issuer-v1-{suffix}.json"))
}

fn random_bytes() -> Result<Zeroizing<[u8; 32]>, AuthorityTrustError> {
    let mut bytes = Zeroizing::new([0; 32]);
    File::open("/dev/urandom")
        .map_err(unavailable)?
        .read_exact(bytes.as_mut())
        .map_err(unavailable)?;
    if *bytes == [0; 32] {
        return Err(AuthorityTrustError::Unavailable);
    }
    Ok(bytes)
}
