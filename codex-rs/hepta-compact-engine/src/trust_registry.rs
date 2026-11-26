//! Root-authenticated, immutable compaction trust manifests.
//!
//! A request never enrolls its own signing key. The embedding owner pins the
//! root out of band, persists each signed manifest, and fences publication on
//! its exact active manifest digest. These values carry no database authority.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::CompactionTrustRoleV1;
use crate::TrustEnrollmentV1;
use crate::archive_codec::Decoder;
use crate::archive_codec::Encoder;
use crate::archive_codec::Wire;
use crate::archive_codec::WireError;
use crate::archive_codec::wire_struct;

const MANIFEST_DOMAIN: &[u8] = b"hepta.compaction.trust-manifest.v1\0";
const MANIFEST_SIGNATURE_DOMAIN: &[u8] = b"hepta.compaction.trust-manifest-signature.v1\0";
pub const MAX_COMPACTION_TRUST_ENTRIES_V1: usize = 1_024;
pub const MAX_COMPACTION_TRUST_MANIFEST_BYTES_V1: usize = 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionTrustedPrincipalV1 {
    pub enrollment: TrustEnrollmentV1,
    /// Administrative principal, distinct from a key ID or evaluator ID.
    pub principal_id: StableId,
    /// Logical evaluator/selector/generator/tokenizer identity.
    pub subject_id: StableId,
    /// Model digest for generators; tokenizer digest for tokenizers; registered
    /// implementation profile for selectors and evaluators.
    pub artifact_digest: Digest32,
}

wire_struct!(CompactionTrustedPrincipalV1 {
    enrollment: TrustEnrollmentV1,
    principal_id: StableId,
    subject_id: StableId,
    artifact_digest: Digest32
});

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedCompactionTrustManifestV1 {
    pub schema_version: u32,
    pub owner_id: StableId,
    pub sequence: u64,
    pub predecessor_manifest_digest: Option<Digest32>,
    pub valid_from_unix_seconds: u64,
    pub valid_until_unix_seconds: u64,
    pub entries: Vec<CompactionTrustedPrincipalV1>,
    pub signature: [u8; 64],
}

wire_struct!(SignedCompactionTrustManifestV1 {
    schema_version: u32,
    owner_id: StableId,
    sequence: u64,
    predecessor_manifest_digest: Option<Digest32>,
    valid_from_unix_seconds: u64,
    valid_until_unix_seconds: u64,
    entries: Vec<CompactionTrustedPrincipalV1>,
    signature: [u8; 64]
});

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CompactionAdmissionErrorV1 {
    Invalid(&'static str),
    Trust(String),
    Encoding(&'static str),
}

impl fmt::Display for CompactionAdmissionErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(reason) => write!(f, "compaction admission: {reason}"),
            Self::Trust(reason) => write!(f, "compaction trust: {reason}"),
            Self::Encoding(reason) => write!(f, "compaction archive: {reason}"),
        }
    }
}

impl Error for CompactionAdmissionErrorV1 {}

impl From<WireError> for CompactionAdmissionErrorV1 {
    fn from(error: WireError) -> Self {
        Self::Encoding(error.0)
    }
}

impl SignedCompactionTrustManifestV1 {
    fn ordered_entries(&self) -> Vec<CompactionTrustedPrincipalV1> {
        let mut entries = self.entries.clone();
        entries.sort_by(|a, b| {
            a.enrollment.role.cmp(&b.enrollment.role)
                .then_with(|| a.principal_id.cmp(&b.principal_id))
                .then_with(|| a.subject_id.cmp(&b.subject_id))
                .then_with(|| a.enrollment.trust_epoch.cmp(&b.enrollment.trust_epoch))
                .then_with(|| a.enrollment.key_id.cmp(&b.enrollment.key_id))
        });
        entries
    }

    fn validate_shape(&self) -> Result<(), CompactionAdmissionErrorV1> {
        if self.schema_version != 1 || self.sequence == 0 {
            return Err(CompactionAdmissionErrorV1::Invalid("manifest schema or sequence"));
        }
        if self.valid_from_unix_seconds >= self.valid_until_unix_seconds {
            return Err(CompactionAdmissionErrorV1::Invalid("manifest validity interval"));
        }
        if self.entries.is_empty() || self.entries.len() > MAX_COMPACTION_TRUST_ENTRIES_V1 {
            return Err(CompactionAdmissionErrorV1::Invalid("manifest entry limit"));
        }
        if (self.sequence == 1) != self.predecessor_manifest_digest.is_none()
            || self.predecessor_manifest_digest.is_some_and(Digest32::is_zero)
        {
            return Err(CompactionAdmissionErrorV1::Invalid("manifest predecessor"));
        }
        let mut identities = BTreeSet::new();
        let mut keys = BTreeSet::new();
        let mut previous = BTreeMap::<(CompactionTrustRoleV1, StableId, StableId), TrustEnrollmentV1>::new();
        for entry in self.ordered_entries() {
            entry.enrollment.validate().map_err(|e| CompactionAdmissionErrorV1::Trust(e.to_string()))?;
            if entry.artifact_digest.is_zero() {
                return Err(CompactionAdmissionErrorV1::Invalid("empty registered artifact"));
            }
            let identity = (entry.enrollment.role, entry.enrollment.key_id.clone(), entry.enrollment.trust_epoch);
            if !identities.insert(identity) || !keys.insert(entry.enrollment.key_digest()) {
                return Err(CompactionAdmissionErrorV1::Invalid("duplicate signing identity or key reuse"));
            }
            let principal = (entry.enrollment.role, entry.principal_id, entry.subject_id);
            if let Some(prior) = previous.get(&principal) {
                if prior.trust_epoch.checked_add(1) != Some(entry.enrollment.trust_epoch) {
                    return Err(CompactionAdmissionErrorV1::Invalid("noncontiguous key epoch"));
                }
                entry.enrollment.validate_rotation_from(prior).map_err(|e| CompactionAdmissionErrorV1::Trust(e.to_string()))?;
            } else if entry.enrollment.trust_epoch != 1 || entry.enrollment.predecessor_key_digest.is_some() {
                return Err(CompactionAdmissionErrorV1::Invalid("missing key history"));
            }
            previous.insert(principal, entry.enrollment);
        }
        Ok(())
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>, CompactionAdmissionErrorV1> {
        self.validate_shape()?;
        let mut output = Encoder::new(MANIFEST_SIGNATURE_DOMAIN)?;
        self.schema_version.write(&mut output)?;
        self.owner_id.write(&mut output)?;
        self.sequence.write(&mut output)?;
        self.predecessor_manifest_digest.write(&mut output)?;
        self.valid_from_unix_seconds.write(&mut output)?;
        self.valid_until_unix_seconds.write(&mut output)?;
        self.ordered_entries().write(&mut output)?;
        Ok(output.finish())
    }

    pub fn encode(&self) -> Result<Vec<u8>, CompactionAdmissionErrorV1> {
        self.validate_shape()?;
        let mut canonical = self.clone();
        canonical.entries = self.ordered_entries();
        let mut output = Encoder::new(MANIFEST_DOMAIN)?;
        canonical.write(&mut output)?;
        let bytes = output.finish();
        if bytes.len() > MAX_COMPACTION_TRUST_MANIFEST_BYTES_V1 {
            return Err(CompactionAdmissionErrorV1::Invalid("manifest byte limit"));
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, CompactionAdmissionErrorV1> {
        if bytes.len() > MAX_COMPACTION_TRUST_MANIFEST_BYTES_V1 {
            return Err(CompactionAdmissionErrorV1::Invalid("manifest byte limit"));
        }
        let mut input = Decoder::new(bytes, MANIFEST_DOMAIN)?;
        let result = Self::read(&mut input)?;
        input.finish()?;
        if result.encode()?.as_slice() != bytes {
            return Err(CompactionAdmissionErrorV1::Invalid("noncanonical manifest"));
        }
        Ok(result)
    }
}

/// Sealed verified manifest. Construction proves a signature against a pin,
/// not the provenance of that pin. Only the production owner installs pins;
/// proposal requests must never choose or replace them.
#[derive(Clone, Debug)]
pub struct VerifiedCompactionTrustRegistryV1 {
    manifest: SignedCompactionTrustManifestV1,
    root_key_digest: Digest32,
    manifest_digest: Digest32,
}

impl VerifiedCompactionTrustRegistryV1 {
    pub fn verify(
        pinned_root_key: [u8; 32],
        bytes: &[u8],
    ) -> Result<Self, CompactionAdmissionErrorV1> {
        let manifest = SignedCompactionTrustManifestV1::decode(bytes)?;
        let key = VerifyingKey::from_bytes(&pinned_root_key).map_err(|_| CompactionAdmissionErrorV1::Invalid("invalid pinned root key"))?;
        if key.is_weak() || manifest.entries.iter().any(|entry| entry.enrollment.verifying_key == pinned_root_key) {
            return Err(CompactionAdmissionErrorV1::Invalid("weak root or root used as worker key"));
        }
        key.verify_strict(&manifest.signing_bytes()?, &Signature::from_bytes(&manifest.signature))
            .map_err(|_| CompactionAdmissionErrorV1::Invalid("manifest signature"))?;
        Ok(Self { manifest, root_key_digest: Digest32::of_bytes(&pinned_root_key), manifest_digest: Digest32::of_bytes(bytes) })
    }

    pub fn manifest(&self) -> &SignedCompactionTrustManifestV1 { &self.manifest }
    pub fn manifest_digest(&self) -> Digest32 { self.manifest_digest }
    pub fn root_key_digest(&self) -> Digest32 { self.root_key_digest }
    pub fn owner_id(&self) -> &StableId { &self.manifest.owner_id }

    pub fn validate_current_at(&self, now: u64) -> Result<(), CompactionAdmissionErrorV1> {
        if now < self.manifest.valid_from_unix_seconds || now >= self.manifest.valid_until_unix_seconds {
            return Err(CompactionAdmissionErrorV1::Invalid("manifest is not currently valid"));
        }
        Ok(())
    }

    /// Full-history manifests are append-only. Existing enrollments may acquire
    /// a revocation timestamp exactly once; all other fields stay immutable.
    pub fn validate_successor_of(&self, previous: &Self) -> Result<(), CompactionAdmissionErrorV1> {
        if self.owner_id() != previous.owner_id()
            || self.root_key_digest != previous.root_key_digest
            || previous.manifest.sequence.checked_add(1) != Some(self.manifest.sequence)
            || self.manifest.predecessor_manifest_digest != Some(previous.manifest_digest)
        {
            return Err(CompactionAdmissionErrorV1::Invalid("manifest CAS or root substitution"));
        }
        for old in &previous.manifest.entries {
            let new = self.lookup(old.enrollment.role, &old.enrollment.key_id, old.enrollment.trust_epoch)?;
            let mut expected = old.clone();
            if old.enrollment.revoked_at_unix_seconds.is_some()
                && old.enrollment.revoked_at_unix_seconds != new.enrollment.revoked_at_unix_seconds
            {
                return Err(CompactionAdmissionErrorV1::Invalid("revocation cannot be delayed or removed"));
            }
            expected.enrollment.revoked_at_unix_seconds = new.enrollment.revoked_at_unix_seconds;
            if &expected != new {
                return Err(CompactionAdmissionErrorV1::Invalid("historical enrollment mutation"));
            }
        }
        Ok(())
    }

    pub(crate) fn lookup(&self, role: CompactionTrustRoleV1, key_id: &StableId, epoch: u64) -> Result<&CompactionTrustedPrincipalV1, CompactionAdmissionErrorV1> {
        self.manifest.entries.iter().find(|entry| entry.enrollment.role == role && &entry.enrollment.key_id == key_id && entry.enrollment.trust_epoch == epoch)
            .ok_or(CompactionAdmissionErrorV1::Invalid("unknown or wrong-purpose signing identity"))
    }

    pub(crate) fn resolve(&self, role: CompactionTrustRoleV1, key_id: &StableId, epoch: u64, accepted_at: u64) -> Result<&CompactionTrustedPrincipalV1, CompactionAdmissionErrorV1> {
        let entry = self.lookup(role, key_id, epoch)?;
        entry.enrollment.validate_historical_at(accepted_at).map_err(|e| CompactionAdmissionErrorV1::Trust(e.to_string()))?;
        Ok(entry)
    }

    /// Read-time admission is deliberately separate from historical signature
    /// validity. A signed old artifact does not override a current revocation.
    pub fn readmit_principal(&self, expected: &CompactionTrustedPrincipalV1, now: u64) -> Result<(), CompactionAdmissionErrorV1> {
        self.validate_current_at(now)?;
        let current = self.lookup(expected.enrollment.role, &expected.enrollment.key_id, expected.enrollment.trust_epoch)?;
        let mut immutable = expected.clone();
        immutable.enrollment.revoked_at_unix_seconds = current.enrollment.revoked_at_unix_seconds;
        if &immutable != current {
            return Err(CompactionAdmissionErrorV1::Invalid("signer registration substitution"));
        }
        current.enrollment.validate_current_at(now).map_err(|e| CompactionAdmissionErrorV1::Trust(e.to_string()))?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use super::*;

    fn signed(sequence: u64, predecessor: Option<Digest32>, revoked: Option<u64>) -> (SigningKey, Vec<u8>) {
        let root = SigningKey::from_bytes(&[7; 32]);
        let worker = SigningKey::from_bytes(&[8; 32]);
        let mut manifest = SignedCompactionTrustManifestV1 {
            schema_version: 1,
            owner_id: StableId::new("owner-test").expect("owner"),
            sequence,
            predecessor_manifest_digest: predecessor,
            valid_from_unix_seconds: 10,
            valid_until_unix_seconds: 1000,
            entries: vec![CompactionTrustedPrincipalV1 {
                enrollment: TrustEnrollmentV1 {
                    schema_version: 1, role: CompactionTrustRoleV1::Evaluator,
                    key_id: StableId::new("evaluator-key").expect("key"), trust_epoch: 1,
                    valid_from_unix_seconds: 10, valid_until_unix_seconds: 1000,
                    revoked_at_unix_seconds: revoked, predecessor_key_digest: None,
                    implementation_digest: Digest32::of_bytes(b"evaluator-impl"),
                    attestation_digest: Digest32::of_bytes(b"evaluator-attestation"),
                    verifying_key: worker.verifying_key().to_bytes(),
                },
                principal_id: StableId::new("independent-evaluator").expect("principal"),
                subject_id: StableId::new("retained-query-evaluator").expect("subject"),
                artifact_digest: Digest32::of_bytes(b"evaluation-profile"),
            }],
            signature: [0; 64],
        };
        manifest.signature = root.sign(&manifest.signing_bytes().expect("signing bytes")).to_bytes();
        (root, manifest.encode().expect("manifest"))
    }

    #[test]
    fn forged_root_tampering_and_trailing_bytes_are_rejected() {
        let (root, bytes) = signed(1, None, None);
        let other = SigningKey::from_bytes(&[9; 32]);
        assert!(VerifiedCompactionTrustRegistryV1::verify(other.verifying_key().to_bytes(), &bytes).is_err());
        for index in 0..bytes.len() {
            let mut tampered = bytes.clone();
            tampered[index] ^= 0x80;
            assert!(VerifiedCompactionTrustRegistryV1::verify(root.verifying_key().to_bytes(), &tampered).is_err());
        }
        let mut trailing = bytes;
        trailing.push(0);
        assert!(VerifiedCompactionTrustRegistryV1::verify(root.verifying_key().to_bytes(), &trailing).is_err());
    }

    #[test]
    fn historical_validity_does_not_resurrect_a_revoked_signer() {
        let (root, bytes) = signed(1, None, None);
        let first = VerifiedCompactionTrustRegistryV1::verify(root.verifying_key().to_bytes(), &bytes).expect("first");
        let (_, bytes) = signed(2, Some(first.manifest_digest()), Some(50));
        let second = VerifiedCompactionTrustRegistryV1::verify(root.verifying_key().to_bytes(), &bytes).expect("second");
        second.validate_successor_of(&first).expect("successor");
        let entry = &first.manifest().entries[0];
        entry.enrollment.validate_historical_at(20).expect("historical evidence");
        assert!(second.readmit_principal(entry, 50).is_err());
        assert!(second.validate_current_at(1000).is_err());
        let (_, bytes) = signed(3, Some(second.manifest_digest()), None);
        let third = VerifiedCompactionTrustRegistryV1::verify(root.verifying_key().to_bytes(), &bytes).expect("signed but invalid transition");
        assert!(third.validate_successor_of(&second).is_err());
    }
}
