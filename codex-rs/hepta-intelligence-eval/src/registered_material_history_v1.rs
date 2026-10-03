//! Original completed publication history under the actual live Root frontier.
//! Historical ACK authenticates a prefix, never restores current eligibility.
use super::*;

pub struct HistoricalRegisteredArtifactFactsV1 {
    facts: RegisteredArtifactCurrentFactsV3,
    current_head: SignedCurrentArtifactHeadV1,
}
impl HistoricalRegisteredArtifactFactsV1 {
    pub fn artifact_root(&self) -> &Path {
        self.facts.artifact_root()
    }
    pub fn original_head(&self) -> &SignedCurrentArtifactHeadV1 {
        &self.facts.head
    }
    pub fn current_view(&self) -> &VerifiedCurrentRegistryViewV1 {
        &self.facts.view
    }
    pub fn acknowledgement(&self) -> &ArtifactOwnerPublicationCheckpointV1 {
        &self.facts.acknowledgement
    }
    pub fn manifests(&self) -> &[ValidatedArtifactManifestV2; 3] {
        &self.facts.manifests
    }
    pub fn expires_at(&self) -> u64 {
        self.facts.expiry
    }
    pub fn revalidate_historical(&self, now: u64) -> HostResult<()> {
        for (source, limit) in &self.facts.sources {
            source.read(*limit)?;
        }
        if now >= self.facts.expiry
            || self.facts.owner.protected_current_head(now)? != self.current_head
            || self.facts.owner.current_registry_view(now)?.receipt() != self.facts.view.receipt()
            || self
                .facts
                .owner
                .acknowledged_publication(
                    &self.facts.acknowledgement.operation_id,
                    &self.facts.head,
                    now,
                )?
                .as_ref()
                != Some(&self.facts.acknowledgement)
        {
            return Err("original historical ACK/current eligibility changed or expired".into());
        }
        let receipt = self
            .facts
            .acknowledgement
            .registry_receipt
            .ok_or("historical original registry receipt")?;
        for manifest in &self.facts.manifests {
            for dataset in &manifest.manifest.source_dataset_digests {
                if !self
                    .facts
                    .owner
                    .historical_dataset_members(receipt, *dataset, now)?
                    .contains(&manifest.manifest.artifact_id)
                {
                    return Err("original historical dataset/manifest prefix changed".into());
                }
            }
        }
        Ok(())
    }
}
/// Reuse the original authenticated head chain, completed ACK, registry-prefix
/// reader and current withdrawal eligibility. A raw signed-head DTO cannot
/// supply a completed checkpoint, forge an ancestor or bypass the live owner.
pub fn inspect_historical_registered_artifact_material_v1(
    path: &Path,
    pin: Digest32,
    plan: &NeuronGenerationMaterialV2,
    subject: &StableId,
    original_head: &SignedCurrentArtifactHeadV1,
    now: u64,
) -> HostResult<HistoricalRegisteredArtifactFactsV1> {
    let source = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    let bytes = source.read(64 * 1024)?;
    let registration: Registration = serde_json::from_slice(&bytes)?;
    let mut facts = inspect_material_frontier(
        &registration,
        plan,
        subject,
        now,
        super::material_inspection::MaterialHeadV1::Historical(original_head),
    )?;
    facts.sources.push((source.clone(), 64 * 1024));
    let current_head = facts.owner.protected_current_head(now)?;
    if source.read(64 * 1024)? != bytes {
        return Err("original historical configuration changed".into());
    }
    let history = HistoricalRegisteredArtifactFactsV1 {
        facts,
        current_head,
    };
    history.revalidate_historical(now)?;
    Ok(history)
}
