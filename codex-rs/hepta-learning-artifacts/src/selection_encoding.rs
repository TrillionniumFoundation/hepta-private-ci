//! Bounded encoding of the existing signed selection, not another authority.
use super::*;

const MAX_SELECTION_BYTES: usize = 16 * 1024;
const DOMAIN: &[u8] = b"hepta.learning-artifacts.selection.v1";

impl SignedArtifactSelectionV1 {
    pub(crate) fn persisted_bytes(&self) -> Vec<u8> {
        let mut bytes = self.signing_bytes();
        bytes.extend_from_slice(&self.signature);
        bytes
    }

    pub(crate) fn from_persisted_bytes(bytes: &[u8]) -> Result<Self, ArtifactSelectionError> {
        if bytes.len() > MAX_SELECTION_BYTES {
            return Err(ArtifactSelectionError::SelectionContext);
        }
        let mut r = Reader(
            bytes
                .strip_prefix(DOMAIN)
                .ok_or(ArtifactSelectionError::SelectionContext)?,
        );
        let selection_id = r.id()?;
        let artifact_id = r.id()?;
        let registry_id = r.id()?;
        let withdrawal_scope_digest = r.digest()?;
        let registry_head_digest = r.digest()?;
        let current_witness_digest = r.digest()?;
        let current_trust_digest = r.digest()?;
        let artifact_kind = match r.array::<1>()?[0] {
            0 => ArtifactKind::Prompt,
            1 => ArtifactKind::Policy,
            2 => ArtifactKind::Model,
            3 => ArtifactKind::Workflow,
            4 => ArtifactKind::Skill,
            5 => ArtifactKind::Parameters,
            6 => ArtifactKind::Topology,
            7 => ArtifactKind::Code,
            8 => ArtifactKind::ExternalAdapter,
            9 => ArtifactKind::SensorCore,
            _ => return Err(ArtifactSelectionError::SelectionContext),
        };
        let artifact_generation =
            Generation::new(r.u64()?).map_err(|_| ArtifactSelectionError::SelectionContext)?;
        let predecessor_id = match r.array::<1>()?[0] {
            0 => None,
            1 => Some(r.id()?),
            _ => return Err(ArtifactSelectionError::SelectionContext),
        };
        let signed = Self {
            selection_id,
            artifact_id,
            registry_id,
            withdrawal_scope_digest,
            registry_head_digest,
            current_witness_digest,
            current_trust_digest,
            artifact_kind,
            artifact_generation,
            predecessor_id,
            content_digest: r.digest()?,
            objective_digest: r.digest()?,
            support_digest: r.digest()?,
            compatibility_digest: r.digest()?,
            encoded_size_bytes: r.u64()?,
            selector_id: r.id()?,
            selector_credential_digest: r.digest()?,
            signing_key_digest: r.digest()?,
            authority_epoch: r.u64()?,
            issued_at: r.u64()?,
            expires_at: r.u64()?,
            signature: r.array()?,
        };
        if !r.0.is_empty() || signed.persisted_bytes() != bytes {
            return Err(ArtifactSelectionError::SelectionContext);
        }
        Ok(signed)
    }
}

struct Reader<'a>(&'a [u8]);
impl<'a> Reader<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8], ArtifactSelectionError> {
        let (value, tail) = self
            .0
            .split_at_checked(n)
            .ok_or(ArtifactSelectionError::SelectionContext)?;
        self.0 = tail;
        Ok(value)
    }
    fn array<const N: usize>(&mut self) -> Result<[u8; N], ArtifactSelectionError> {
        self.take(N)?
            .try_into()
            .map_err(|_| ArtifactSelectionError::SelectionContext)
    }
    fn u64(&mut self) -> Result<u64, ArtifactSelectionError> {
        Ok(u64::from_be_bytes(self.array()?))
    }
    fn digest(&mut self) -> Result<Digest32, ArtifactSelectionError> {
        Ok(Digest32::from_array(self.array()?))
    }
    fn id(&mut self) -> Result<StableId, ArtifactSelectionError> {
        let n =
            usize::try_from(self.u64()?).map_err(|_| ArtifactSelectionError::SelectionContext)?;
        if n > 256 {
            return Err(ArtifactSelectionError::SelectionContext);
        }
        let value = std::str::from_utf8(self.take(n)?)
            .map_err(|_| ArtifactSelectionError::SelectionContext)?;
        StableId::new(value.to_owned()).map_err(|_| ArtifactSelectionError::SelectionContext)
    }
}

#[cfg(test)]
#[path = "selection_encoding_tests.rs"]
mod tests;
