//! Inverse of the existing V2 digest encoding; no new manifest identity.
use super::*;

pub(crate) fn decode_manifest(
    bytes: &[u8],
    now: u64,
) -> Result<ValidatedArtifactManifestV2, ArtifactClosureError> {
    if bytes.len() > MAX_ENCODED_MANIFEST_BYTES {
        return Err(ArtifactClosureError::ManifestEncoding);
    }
    let mut r = Reader(
        bytes
            .strip_prefix(b"hepta.learning-artifacts.manifest.v2")
            .ok_or(ArtifactClosureError::ManifestEncoding)?,
    );
    let artifact_id = r.id()?;
    let kind = match r.byte()? {
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
        _ => return Err(ArtifactClosureError::ManifestEncoding),
    };
    let generation =
        Generation::new(r.u64()?).map_err(|_| ArtifactClosureError::ManifestEncoding)?;
    let provenance_mode = match r.byte()? {
        0 => ProvenanceModeV1::DatasetDerived,
        1 => ProvenanceModeV1::DatasetIndependent,
        _ => return Err(ArtifactClosureError::ManifestEncoding),
    };
    let source_dataset_digests = r.digests(MAX_DATASET_INPUTS)?;
    let lineage_digests = r.digests(MAX_LINEAGE_DIGESTS)?;
    let predecessors = r.count(MAX_PREDECESSORS)?;
    let predecessor_ids = (0..predecessors)
        .map(|_| r.id())
        .collect::<Result<Vec<_>, _>>()?;
    let rollback_predecessor = match r.byte()? {
        0 => None,
        1 => Some(r.id()?),
        _ => return Err(ArtifactClosureError::ManifestEncoding),
    };
    let bytes_digest = r.digest()?;
    let training_code_digest = r.digest()?;
    let runtime_tuple_digest = r.digest()?;
    let device_profile_digest = r.digest()?;
    let objective_class_digest = r.digest()?;
    let compatibility_digest = r.digest()?;
    let schema_profile_digest = r.digest()?;
    let normalization_digest = r.digest()?;
    let manifest = LearningArtifactManifestV2 {
        artifact_id,
        kind,
        generation,
        provenance_mode,
        source_dataset_digests,
        lineage_digests,
        predecessor_ids,
        rollback_predecessor,
        bytes_digest,
        training_code_digest,
        runtime_tuple_digest,
        device_profile_digest,
        objective_class_digest,
        compatibility_digest,
        schema_profile_digest,
        normalization_digest,
        encoded_size_bytes: r.u64()?,
        producer_id: r.id()?,
        created_at: r.u64()?,
        expires_at: r.u64()?,
    };
    let validated = validate_artifact_manifest_v2(manifest, now)?;
    if !r.0.is_empty() || encode_manifest(&validated.manifest)? != bytes {
        return Err(ArtifactClosureError::ManifestEncoding);
    }
    Ok(validated)
}

struct Reader<'a>(&'a [u8]);
impl<'a> Reader<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8], ArtifactClosureError> {
        let (head, tail) = self
            .0
            .split_at_checked(n)
            .ok_or(ArtifactClosureError::ManifestEncoding)?;
        self.0 = tail;
        Ok(head)
    }
    fn array<const N: usize>(&mut self) -> Result<[u8; N], ArtifactClosureError> {
        self.take(N)?
            .try_into()
            .map_err(|_| ArtifactClosureError::ManifestEncoding)
    }
    fn byte(&mut self) -> Result<u8, ArtifactClosureError> {
        Ok(self.array::<1>()?[0])
    }
    fn u64(&mut self) -> Result<u64, ArtifactClosureError> {
        Ok(u64::from_be_bytes(self.array()?))
    }
    fn count(&mut self, max: usize) -> Result<usize, ArtifactClosureError> {
        let n = usize::try_from(u32::from_be_bytes(self.array()?))
            .map_err(|_| ArtifactClosureError::ManifestEncoding)?;
        if n > max {
            return Err(ArtifactClosureError::ManifestEncoding);
        }
        Ok(n)
    }
    fn id(&mut self) -> Result<StableId, ArtifactClosureError> {
        let n = self.count(256)?;
        let text = std::str::from_utf8(self.take(n)?)
            .map_err(|_| ArtifactClosureError::ManifestEncoding)?;
        StableId::new(text).map_err(|_| ArtifactClosureError::ManifestEncoding)
    }
    fn digest(&mut self) -> Result<Digest32, ArtifactClosureError> {
        Ok(Digest32::from_array(self.array()?))
    }
    fn digests(&mut self, max: usize) -> Result<Vec<Digest32>, ArtifactClosureError> {
        let n = self.count(max)?;
        (0..n).map(|_| self.digest()).collect()
    }
}
