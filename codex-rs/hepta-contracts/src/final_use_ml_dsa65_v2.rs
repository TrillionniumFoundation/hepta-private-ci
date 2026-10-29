//! Explicit ML-DSA-65 grant verification in the original FinalUse owner.
//! This selects no legacy trust, starts no second nonce ledger, and performs
//! no migration from an existing Ed25519 owner directory.

use super::*;
use ml_dsa::EncodedVerifyingKey;
use ml_dsa::MlDsa65;
use ml_dsa::Signature as MlDsaSignature;
use ml_dsa::VerifyingKey as MlDsaVerifyingKey;

pub const FINAL_USE_ML_DSA65_V2_CONTEXT: &[u8] = b"hepta.kernel.final-use.ml-dsa-65.v2";
const SIGNING_DOMAIN: &[u8] = b"hepta.kernel.authority.final-use.ml-dsa-65.v2\0";
const SIGNATURE_BYTES: usize = 3_309;
const PUBLIC_KEY_BYTES: usize = 1_952;
const FRAME_PREFIX: &[u8; 6] = b"HFU2\x65\0";

/// One host-pinned ML-DSA-65 issuer generation, never a request-supplied key.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseMlDsa65IssuerTrustKeyV2 {
    pub key_id: String,
    pub verifying_key: Vec<u8>,
    pub not_before_authority_epoch: u64,
    pub not_after_authority_epoch: u64,
}

#[derive(Clone)]
pub(super) enum IssuerVerifier {
    Ed25519V1(VerifyingKey),
    MlDsa65V2(Box<MlDsaVerifyingKey<MlDsa65>>),
}

impl IssuerVerifier {
    pub(super) fn signing_bytes(&self, grant: &FinalUseGrant) -> Result<Vec<u8>, FinalUseError> {
        match self {
            Self::Ed25519V1(_) => grant.signing_bytes(),
            Self::MlDsa65V2(_) => grant.canonical_signing_bytes(/*schema*/ 2, SIGNING_DOMAIN),
        }
    }

    pub(super) fn verify_strict(
        &self,
        schema: u32,
        key_id: &str,
        input: &[u8],
        frame: &[u8],
    ) -> bool {
        match (self, schema) {
            (Self::Ed25519V1(key), 1) => ed25519_dalek::Signature::from_slice(frame)
                .is_ok_and(|signature| key.verify_strict(input, &signature).is_ok()),
            (Self::MlDsa65V2(key), 2) => {
                let Some((actual_key_id, raw)) = decode_signature(frame) else {
                    return false;
                };
                if actual_key_id != key_id {
                    return false;
                }
                let Ok(signature) = MlDsaSignature::<MlDsa65>::try_from(raw) else {
                    return false;
                };
                let Ok(input) = bind_key_id(input, key_id) else {
                    return false;
                };
                key.verify_with_context(&input, FINAL_USE_ML_DSA65_V2_CONTEXT, &signature)
            }
            (Self::Ed25519V1(_) | Self::MlDsa65V2(_), _) => false,
        }
    }
}

fn bind_key_id(input: &[u8], key_id: &str) -> Result<Vec<u8>, FinalUseError> {
    if !identifier(key_id) {
        return Err(FinalUseError::InvalidTrust);
    }
    let mut bound = input.to_vec();
    let length = u16::try_from(key_id.len()).map_err(|_| FinalUseError::InvalidTrust)?;
    bound.extend_from_slice(&length.to_be_bytes());
    bound.extend_from_slice(key_id.as_bytes());
    Ok(bound)
}

impl FinalUseGrant {
    /// Exact V2 issuer input. Sign with the fixed FIPS 204 context exported by
    /// this module, then frame the signature with the same trusted key ID.
    pub fn ml_dsa65_v2_signing_bytes(&self, key_id: &str) -> Result<Vec<u8>, FinalUseError> {
        if self.schema_version != 2 {
            return Err(FinalUseError::InvalidGrant);
        }
        bind_key_id(
            &self.canonical_signing_bytes(/*schema*/ 2, SIGNING_DOMAIN)?,
            key_id,
        )
    }
}

/// Encode only the bounded V2 signature carrier; this does not verify a grant.
/// The original outer grant JSON and its V1 representation remain unchanged.
/// The carrier is `HFU2`, suite byte `0x65`, reserved byte zero, a big-endian
/// u16 key-ID length, its ASCII key ID, and exactly 3309 signature bytes.
pub fn encode_ml_dsa65_final_use_signature_v2(
    key_id: &str,
    signature: &[u8],
) -> Result<Vec<u8>, FinalUseError> {
    if !identifier(key_id) || signature.len() != SIGNATURE_BYTES {
        return Err(FinalUseError::InvalidSignature);
    }
    let mut frame = FRAME_PREFIX.to_vec();
    let length = u16::try_from(key_id.len()).map_err(|_| FinalUseError::InvalidSignature)?;
    frame.extend_from_slice(&length.to_be_bytes());
    frame.extend_from_slice(key_id.as_bytes());
    frame.extend_from_slice(signature);
    Ok(frame)
}

fn decode_signature(frame: &[u8]) -> Option<(&str, &[u8])> {
    if frame.len() < 9 + SIGNATURE_BYTES
        || frame.len() > 8 + 128 + SIGNATURE_BYTES
        || !frame.starts_with(FRAME_PREFIX)
    {
        return None;
    }
    let length = usize::from(u16::from_be_bytes([frame[6], frame[7]]));
    if !(1..=128).contains(&length) || frame.len() != 8 + length + SIGNATURE_BYTES {
        return None;
    }
    let key_id = std::str::from_utf8(&frame[8..8 + length]).ok()?;
    if !identifier(key_id) {
        return None;
    }
    Some((key_id, &frame[8 + length..]))
}

fn pin_keys(
    mut keys: Vec<FinalUseMlDsa65IssuerTrustKeyV2>,
) -> Result<(Vec<PinnedIssuerKey>, [u8; 32]), FinalUseError> {
    if keys.is_empty() || keys.len() > MAX_ISSUER_TRUST_KEYS {
        return Err(FinalUseError::InvalidTrust);
    }
    keys.sort_by(|left, right| left.key_id.cmp(&right.key_id));
    let mut ids = BTreeSet::new();
    let mut public_keys = BTreeSet::new();
    let mut digest = Sha256::new();
    digest.update(b"hepta.kernel.authority.final-use-issuer-trust.ml-dsa-65.v2\0");
    let mut pinned = Vec::with_capacity(keys.len());
    for candidate in keys {
        if !identifier(&candidate.key_id)
            || candidate.verifying_key.len() != PUBLIC_KEY_BYTES
            || candidate.not_before_authority_epoch == 0
            || candidate.not_after_authority_epoch < candidate.not_before_authority_epoch
            || !ids.insert(candidate.key_id.clone())
            || !public_keys.insert(candidate.verifying_key.clone())
        {
            return Err(FinalUseError::InvalidTrust);
        }
        let encoded = EncodedVerifyingKey::<MlDsa65>::try_from(candidate.verifying_key.as_slice())
            .map_err(|_| FinalUseError::InvalidTrust)?;
        digest.update((candidate.key_id.len() as u64).to_le_bytes());
        digest.update(candidate.key_id.as_bytes());
        digest.update(&candidate.verifying_key);
        digest.update(candidate.not_before_authority_epoch.to_le_bytes());
        digest.update(candidate.not_after_authority_epoch.to_le_bytes());
        pinned.push(PinnedIssuerKey {
            key_id: candidate.key_id,
            key: IssuerVerifier::MlDsa65V2(Box::new(MlDsaVerifyingKey::<MlDsa65>::decode(
                &encoded,
            ))),
            not_before_authority_epoch: candidate.not_before_authority_epoch,
            not_after_authority_epoch: candidate.not_after_authority_epoch,
        });
    }
    Ok((pinned, digest.finalize().into()))
}

impl FinalUseAuthority {
    /// Explicit fresh/reopen V2 owner using the original claim/revocation store.
    /// Existing classical trust formats reject; no claims, epochs or revocations
    /// are reset. The host must supply the original clock and external CAS
    /// interfaces; this constructor does not attest their deployment.
    pub fn open_state_dir_with_ml_dsa65_v2(
        directory: &std::path::Path,
        signer_id: String,
        issuer_keys: Vec<FinalUseMlDsa65IssuerTrustKeyV2>,
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self, FinalUseError> {
        if !identifier(&signer_id) || !valid_head(&head) {
            return Err(FinalUseError::InvalidTrust);
        }
        clock.now_unix_ms().map_err(map_trust_error)?;
        let (issuer_keys, issuer_trust_sha256) = pin_keys(issuer_keys)?;
        let (store, state) = store::Store::open_ml_dsa65_key_ring_exact(
            directory,
            &signer_id,
            issuer_trust_sha256,
            head,
        )?;
        let observed = frontier_for_state(&state);
        if frontier_store.load(&signer_id).map_err(map_trust_error)? != observed {
            return Err(FinalUseError::AntiRollbackViolation);
        }
        Ok(Self(Arc::new(Inner {
            signer_id,
            issuer_keys,
            state: Mutex::new(state),
            active_dispatches: AtomicUsize::new(0),
            store,
            clock,
            frontier_store: Some(frontier_store),
        })))
    }
}

#[cfg(all(test, unix))]
#[path = "final_use_ml_dsa65_v2_tests.rs"]
mod tests;
