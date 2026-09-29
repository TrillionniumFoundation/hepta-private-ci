use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

const REQUEST_MAGIC: &str = "HEPTA-LEARNING-ARTIFACTD-REQUEST-V1";
const MAX_CLIENTS: usize = 64;
const MAX_ACTIONS_PER_CLIENT: usize = 16;
const MAX_PAYLOAD_BYTES: usize = 1024 * 1024;
const MAX_REQUEST_LIFETIME_SECONDS: u64 = 120;
const MAX_FUTURE_SKEW_SECONDS: u64 = 5;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ArtifactOwnerActionV1 {
    Health,
    Ready,
    Status,
    Metrics,
    Publish,
    RecoverPublish,
    InstallWithdrawalFrontier,
    ReloadAuthz,
    Backup,
    Shutdown,
}

impl ArtifactOwnerActionV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Health => "health",
            Self::Ready => "ready",
            Self::Status => "status",
            Self::Metrics => "metrics",
            Self::Publish => "publish",
            Self::RecoverPublish => "recover_publish",
            Self::InstallWithdrawalFrontier => "install_withdrawal_frontier",
            Self::ReloadAuthz => "reload_authz",
            Self::Backup => "backup",
            Self::Shutdown => "shutdown",
        }
    }

    pub fn parse(value: &str) -> Result<Self, ArtifactOwnerCapabilityError> {
        match value {
            "health" => Ok(Self::Health),
            "ready" => Ok(Self::Ready),
            "status" => Ok(Self::Status),
            "metrics" => Ok(Self::Metrics),
            "publish" => Ok(Self::Publish),
            "recover_publish" => Ok(Self::RecoverPublish),
            "install_withdrawal_frontier" => Ok(Self::InstallWithdrawalFrontier),
            "reload_authz" => Ok(Self::ReloadAuthz),
            "backup" => Ok(Self::Backup),
            "shutdown" => Ok(Self::Shutdown),
            _ => Err(ArtifactOwnerCapabilityError::UnknownAction),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerClientGrantV1 {
    pub client_id: StableId,
    pub verifying_key: [u8; 32],
    pub valid_from: u64,
    pub expires_at: u64,
    pub revoked_at: Option<u64>,
    pub allowed_actions: BTreeSet<ArtifactOwnerActionV1>,
}

#[derive(Clone, Debug)]
pub struct ArtifactOwnerKeyringV1 {
    generation: u64,
    grants: BTreeMap<StableId, ArtifactOwnerClientGrantV1>,
    digest: Digest32,
}

impl ArtifactOwnerKeyringV1 {
    pub fn new(
        generation: u64,
        mut grants: Vec<ArtifactOwnerClientGrantV1>,
    ) -> Result<Self, ArtifactOwnerCapabilityError> {
        if generation == 0 || grants.is_empty() || grants.len() > MAX_CLIENTS {
            return Err(ArtifactOwnerCapabilityError::InvalidKeyring);
        }
        grants.sort_by(|left, right| left.client_id.cmp(&right.client_id));
        let mut by_id = BTreeMap::new();
        let mut digest_bytes = b"hepta.learning-artifactd.authz.v1".to_vec();
        digest_bytes.extend_from_slice(&generation.to_be_bytes());
        digest_bytes.extend_from_slice(&(grants.len() as u64).to_be_bytes());
        for grant in grants {
            if grant.allowed_actions.is_empty()
                || grant.allowed_actions.len() > MAX_ACTIONS_PER_CLIENT
                || grant.valid_from > grant.expires_at
                || grant
                    .revoked_at
                    .is_some_and(|revoked| revoked < grant.valid_from)
                || VerifyingKey::from_bytes(&grant.verifying_key).is_err()
            {
                return Err(ArtifactOwnerCapabilityError::InvalidGrant);
            }
            if by_id.contains_key(&grant.client_id) {
                return Err(ArtifactOwnerCapabilityError::DuplicateClient);
            }
            push_id(&mut digest_bytes, &grant.client_id);
            digest_bytes.extend_from_slice(&grant.verifying_key);
            digest_bytes.extend_from_slice(&grant.valid_from.to_be_bytes());
            digest_bytes.extend_from_slice(&grant.expires_at.to_be_bytes());
            match grant.revoked_at {
                Some(value) => {
                    digest_bytes.push(1);
                    digest_bytes.extend_from_slice(&value.to_be_bytes());
                }
                None => digest_bytes.push(0),
            }
            digest_bytes.extend_from_slice(&(grant.allowed_actions.len() as u64).to_be_bytes());
            for action in &grant.allowed_actions {
                push_atom(&mut digest_bytes, action.as_str());
            }
            by_id.insert(grant.client_id.clone(), grant);
        }
        Ok(Self {
            generation,
            grants: by_id,
            digest: Digest32::of_bytes(&digest_bytes),
        })
    }

    #[must_use]
    pub const fn generation(&self) -> u64 {
        self.generation
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.digest
    }

    pub(crate) fn verify(
        &self,
        request: &SignedArtifactOwnerRequestV1,
        now: u64,
    ) -> Result<VerifiedArtifactOwnerRequestV1, ArtifactOwnerCapabilityError> {
        if request.keyring_generation != self.generation
            || request.nonce != request.request_id
            || request.payload.len() > MAX_PAYLOAD_BYTES
            || request.issued_at > request.expires_at
            || request.expires_at.saturating_sub(request.issued_at)
                > MAX_REQUEST_LIFETIME_SECONDS
            || request.issued_at > now.saturating_add(MAX_FUTURE_SKEW_SECONDS)
            || now > request.expires_at
        {
            return Err(ArtifactOwnerCapabilityError::RequestContext);
        }
        let grant = self
            .grants
            .get(&request.client_id)
            .ok_or(ArtifactOwnerCapabilityError::UnknownClient)?;
        if request.issued_at < grant.valid_from
            || request.issued_at > grant.expires_at
            || now > grant.expires_at
            || grant
                .revoked_at
                .is_some_and(|revoked| request.issued_at >= revoked || now >= revoked)
        {
            return Err(ArtifactOwnerCapabilityError::ClientRevoked);
        }
        if !grant.allowed_actions.contains(&request.action) {
            return Err(ArtifactOwnerCapabilityError::ActionDenied);
        }
        VerifyingKey::from_bytes(&grant.verifying_key)
            .map_err(|_| ArtifactOwnerCapabilityError::InvalidGrant)?
            .verify_strict(
                &request.signing_bytes(),
                &Signature::from_bytes(&request.signature),
            )
            .map_err(|_| ArtifactOwnerCapabilityError::InvalidSignature)?;
        Ok(VerifiedArtifactOwnerRequestV1 {
            request: request.clone(),
            request_digest: request.request_digest(),
            keyring_digest: self.digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedArtifactOwnerRequestV1 {
    pub keyring_generation: u64,
    pub request_id: StableId,
    pub client_id: StableId,
    pub action: ArtifactOwnerActionV1,
    pub issued_at: u64,
    pub expires_at: u64,
    pub nonce: StableId,
    pub payload: Vec<u8>,
    pub signature: [u8; 64],
}

impl SignedArtifactOwnerRequestV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let payload_digest = Digest32::of_bytes(&self.payload);
        let mut bytes = b"hepta.learning-artifactd.request.v1".to_vec();
        bytes.extend_from_slice(&self.keyring_generation.to_be_bytes());
        push_id(&mut bytes, &self.request_id);
        push_id(&mut bytes, &self.client_id);
        push_atom(&mut bytes, self.action.as_str());
        bytes.extend_from_slice(&self.issued_at.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at.to_be_bytes());
        push_id(&mut bytes, &self.nonce);
        bytes.extend_from_slice(&(self.payload.len() as u64).to_be_bytes());
        bytes.extend_from_slice(payload_digest.as_array());
        bytes
    }

    #[must_use]
    pub fn request_digest(&self) -> Digest32 {
        let mut bytes = self.signing_bytes();
        bytes.extend_from_slice(&self.signature);
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn encode(&self) -> Vec<u8> {
        format!(
            "{REQUEST_MAGIC}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n",
            self.keyring_generation,
            self.request_id,
            self.client_id,
            self.action.as_str(),
            self.issued_at,
            self.expires_at,
            self.nonce,
            encode_hex(&self.payload),
            encode_hex(&self.signature),
        )
        .into_bytes()
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, ArtifactOwnerCapabilityError> {
        if bytes.len() > MAX_PAYLOAD_BYTES * 2 + 4096 {
            return Err(ArtifactOwnerCapabilityError::Capacity);
        }
        let text = std::str::from_utf8(bytes)
            .map_err(|_| ArtifactOwnerCapabilityError::InvalidEncoding)?;
        let lines: Vec<_> = text.lines().collect();
        if lines.len() != 10 || lines[0] != REQUEST_MAGIC || !text.ends_with('\n') {
            return Err(ArtifactOwnerCapabilityError::InvalidEncoding);
        }
        let payload = decode_hex(lines[8])?;
        if payload.len() > MAX_PAYLOAD_BYTES {
            return Err(ArtifactOwnerCapabilityError::Capacity);
        }
        Ok(Self {
            keyring_generation: parse_u64(lines[1])?,
            request_id: parse_id(lines[2])?,
            client_id: parse_id(lines[3])?,
            action: ArtifactOwnerActionV1::parse(lines[4])?,
            issued_at: parse_u64(lines[5])?,
            expires_at: parse_u64(lines[6])?,
            nonce: parse_id(lines[7])?,
            payload,
            signature: decode_fixed_hex::<64>(lines[9])?,
        })
    }
}

#[derive(Clone, Debug)]
pub(crate) struct VerifiedArtifactOwnerRequestV1 {
    pub request: SignedArtifactOwnerRequestV1,
    pub request_digest: Digest32,
    pub keyring_digest: Digest32,
    pub authority: AuthorityPosture,
}

fn parse_id(value: &str) -> Result<StableId, ArtifactOwnerCapabilityError> {
    StableId::new(value.to_owned()).map_err(|_| ArtifactOwnerCapabilityError::InvalidEncoding)
}

fn parse_u64(value: &str) -> Result<u64, ArtifactOwnerCapabilityError> {
    value
        .parse::<u64>()
        .map_err(|_| ArtifactOwnerCapabilityError::InvalidEncoding)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

fn push_atom(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn encode_hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}

fn decode_hex(value: &str) -> Result<Vec<u8>, ArtifactOwnerCapabilityError> {
    if !value.len().is_multiple_of(2) {
        return Err(ArtifactOwnerCapabilityError::InvalidEncoding);
    }
    let mut output = Vec::with_capacity(value.len() / 2);
    for pair in value.as_bytes().chunks_exact(2) {
        let high = decode_nibble(pair[0]).ok_or(ArtifactOwnerCapabilityError::InvalidEncoding)?;
        let low = decode_nibble(pair[1]).ok_or(ArtifactOwnerCapabilityError::InvalidEncoding)?;
        output.push((high << 4) | low);
    }
    Ok(output)
}

fn decode_fixed_hex<const N: usize>(
    value: &str,
) -> Result<[u8; N], ArtifactOwnerCapabilityError> {
    let bytes = decode_hex(value)?;
    bytes
        .try_into()
        .map_err(|_| ArtifactOwnerCapabilityError::InvalidEncoding)
}

const fn decode_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactOwnerCapabilityError {
    InvalidKeyring,
    InvalidGrant,
    DuplicateClient,
    UnknownClient,
    ClientRevoked,
    UnknownAction,
    ActionDenied,
    RequestContext,
    InvalidSignature,
    InvalidEncoding,
    Capacity,
}

impl fmt::Display for ArtifactOwnerCapabilityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactOwnerCapabilityError {}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }

    #[test]
    fn signed_request_is_action_scoped_current_and_replay_identified() {
        let key = SigningKey::from_bytes(&[41; 32]);
        let keyring = ArtifactOwnerKeyringV1::new(
            7,
            vec![ArtifactOwnerClientGrantV1 {
                client_id: id("operator"),
                verifying_key: key.verifying_key().to_bytes(),
                valid_from: 10,
                expires_at: 100,
                revoked_at: None,
                allowed_actions: BTreeSet::from([ArtifactOwnerActionV1::Status]),
            }],
        )
        .expect("keyring");
        let mut request = SignedArtifactOwnerRequestV1 {
            keyring_generation: 7,
            request_id: id("request-one"),
            client_id: id("operator"),
            action: ArtifactOwnerActionV1::Status,
            issued_at: 20,
            expires_at: 30,
            nonce: id("request-one"),
            payload: Vec::new(),
            signature: [0; 64],
        };
        request.signature = key.sign(&request.signing_bytes()).to_bytes();
        let encoded = request.encode();
        let decoded = SignedArtifactOwnerRequestV1::decode(&encoded).expect("decode");
        let verified = keyring.verify(&decoded, 21).expect("verify");
        assert_eq!(verified.request_digest, request.request_digest());
        assert_eq!(verified.keyring_digest, keyring.digest());
        assert!(!verified.authority.grants_any());

        let mut denied = request;
        denied.action = ArtifactOwnerActionV1::Shutdown;
        denied.signature = key.sign(&denied.signing_bytes()).to_bytes();
        assert_eq!(
            keyring.verify(&denied, 21).expect_err("denied action"),
            ArtifactOwnerCapabilityError::ActionDenied
        );
    }
}
