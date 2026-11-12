//! Bounded canonical transport data. Decoding yields explicitly untrusted
//! claims, never an original writer proof or a publication continuation.

use codex_hepta_types::Digest32;

use super::super::decode_checkpoint;
use super::super::decode_signed_head;
use super::super::encode_checkpoint;
use super::super::encode_signed_head;
use super::ArtifactHeadSigningConfigV1;
use super::Error;
use super::UntrustedArtifactRegistryDurableV1;
use crate::ArtifactRegistry;
use crate::OriginalArtifactRegistryDurableV1;
use crate::SignedCurrentArtifactHeadV1;

const MAGIC: &[u8; 8] = b"HARDP001";
const MAX_BYTES: usize = 16_384;

impl OriginalArtifactRegistryDurableV1 {
    /// Only an actual original-writer read can encode this source response.
    /// The receiving process must separately authenticate its original peer.
    pub fn encode_for_original_head_source(
        &self,
        config: &ArtifactHeadSigningConfigV1,
    ) -> Result<Vec<u8>, Error> {
        if self.writer_lease() != &config.writer_lease
            || self.trust_digest()
                != super::super::ArtifactOwnerVerifierV1::new(config.trust.clone())?.trust_digest()
        {
            return Err(Error::WriterLeaseContext);
        }
        let registry = ArtifactRegistry::from_snapshot(self.registry_snapshot().clone())?;
        let registry_bytes =
            crate::storage::encode_snapshot(&registry, self.registry_receipt().binding)?;
        let checkpoint = encode_checkpoint(self.checkpoint());
        let head = self
            .current_head()
            .map(encode_signed_head)
            .unwrap_or_default();
        let mut lease = self.writer_lease().signing_bytes();
        lease.extend_from_slice(&self.writer_lease().signature);
        let mut bytes = MAGIC.to_vec();
        for value in [&checkpoint, &registry_bytes, &head, &lease] {
            push_field(&mut bytes, value)?;
        }
        bytes.extend_from_slice(self.trust_digest().as_array());
        bytes.extend_from_slice(&self.observed_unix_millis().to_be_bytes());
        if bytes.len() > MAX_BYTES {
            return Err(Error::Capacity);
        }
        let decoded = decode_source(&bytes, config)?;
        decoded.authenticate_current(config, self.observed_unix_millis())?;
        Ok(bytes)
    }
}

pub(super) fn decode_source(
    bytes: &[u8],
    config: &ArtifactHeadSigningConfigV1,
) -> Result<UntrustedArtifactRegistryDurableV1, Error> {
    if bytes.len() > MAX_BYTES || bytes.get(..8) != Some(MAGIC.as_slice()) {
        return Err(Error::CheckpointMismatch);
    }
    let mut cursor = &bytes[8..];
    let checkpoint_bytes = field(&mut cursor)?;
    let registry_bytes = field(&mut cursor)?;
    let head_bytes = field(&mut cursor)?;
    let lease_bytes = field(&mut cursor)?;
    if cursor.len() != 40 {
        return Err(Error::CheckpointMismatch);
    }
    let trust_digest = Digest32::from_array(
        cursor[..32]
            .try_into()
            .map_err(|_| Error::CheckpointMismatch)?,
    );
    let observed_at = u64::from_be_bytes(
        cursor[32..]
            .try_into()
            .map_err(|_| Error::CheckpointMismatch)?,
    );
    let checkpoint = decode_checkpoint(checkpoint_bytes)?;
    if encode_checkpoint(&checkpoint) != checkpoint_bytes {
        return Err(Error::CheckpointMismatch);
    }
    let receipt = checkpoint
        .registry_receipt
        .ok_or(Error::CheckpointMismatch)?;
    let registry =
        crate::storage::decode_registry_snapshot_bytes(registry_bytes, receipt)?.snapshot();
    let current = if head_bytes.is_empty() {
        None
    } else {
        let signed = decode_artifact_head_bytes_v1(head_bytes)?;
        Some(signed)
    };
    let mut expected_lease = config.writer_lease.signing_bytes();
    expected_lease.extend_from_slice(&config.writer_lease.signature);
    if lease_bytes != expected_lease {
        return Err(Error::WriterLeaseContext);
    }
    let value = UntrustedArtifactRegistryDurableV1 {
        checkpoint,
        registry,
        receipt,
        current,
        writer_lease_digest: Digest32::of_bytes(lease_bytes),
        trust_digest,
        observed_at,
    };
    // Structural and original-signature checks at the source's asserted time
    // are not CURRENT. The typed client repeats this after its last real I/O.
    value.authenticate_current(config, observed_at)?;
    Ok(value)
}

pub fn encode_artifact_head_bytes_v1(
    value: &SignedCurrentArtifactHeadV1,
) -> Result<Vec<u8>, Error> {
    let bytes = encode_signed_head(value);
    if bytes.len() > MAX_BYTES {
        return Err(Error::Capacity);
    }
    Ok(bytes)
}

pub fn decode_artifact_head_bytes_v1(bytes: &[u8]) -> Result<SignedCurrentArtifactHeadV1, Error> {
    if bytes.is_empty() || bytes.len() > MAX_BYTES {
        return Err(Error::Capacity);
    }
    let value = decode_signed_head(bytes)?;
    if encode_signed_head(&value) != bytes {
        return Err(Error::CurrentHeadContext);
    }
    Ok(value)
}

fn push_field(bytes: &mut Vec<u8>, field: &[u8]) -> Result<(), Error> {
    let total = bytes
        .len()
        .checked_add(4)
        .and_then(|n| n.checked_add(field.len()))
        .ok_or(Error::Capacity)?;
    if total > MAX_BYTES {
        return Err(Error::Capacity);
    }
    let length = u32::try_from(field.len()).map_err(|_| Error::Capacity)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(field);
    Ok(())
}

fn field<'a>(cursor: &mut &'a [u8]) -> Result<&'a [u8], Error> {
    let length = cursor.get(..4).ok_or(Error::CheckpointMismatch)?;
    let length =
        u32::from_be_bytes(length.try_into().map_err(|_| Error::CheckpointMismatch)?) as usize;
    let rest = &cursor[4..];
    if length > MAX_BYTES || length > rest.len() {
        return Err(Error::CheckpointMismatch);
    }
    let (value, tail) = rest.split_at(length);
    *cursor = tail;
    Ok(value)
}
