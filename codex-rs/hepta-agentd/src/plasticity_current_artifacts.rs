//! Fresh CURRENT at the original plasticity append boundary.
use super::*;
use crate::CurrentArtifactRegistrySourceV1;
use codex_hepta_agent_components::learning_artifacts::VerifiedCurrentRegistryUseWindowV1;
use codex_hepta_agent_components::types::StableId;

pub(crate) struct PlasticityCurrentArtifactsV1 {
    source: CurrentArtifactRegistrySourceV1,
    policy_ids: [StableId; 3],
}

impl PlasticityRuntimeBootstrapV1 {
    /// Bind the original update rule, mutation policy and broadcast to their
    /// live read-only owner. A new registry head requires explicit whole input-context admission;
    /// the current proposal's immutable admission is never silently rewritten.
    pub fn with_current_artifacts(
        mut self,
        source: CurrentArtifactRegistrySourceV1,
        policy_ids: [StableId; 3],
    ) -> Result<Self, AgentdError> {
        self.current_artifacts = Some(PlasticityCurrentArtifactsV1::new(
            source,
            policy_ids,
            &self.artifacts,
            &self.owner_evidence_policy,
        )?);
        Ok(self)
    }
}

impl PlasticityCurrentArtifactsV1 {
    pub(crate) fn new(
        source: CurrentArtifactRegistrySourceV1,
        policy_ids: [StableId; 3],
        artifacts: &ArtifactRegistry,
        policy: &PlasticityOwnerEvidencePolicyV1,
    ) -> Result<Self, AgentdError> {
        if policy_ids
            .iter()
            .collect::<std::collections::BTreeSet<_>>()
            .len()
            != 3
            || policy_ids.iter().zip([
                crate::PlasticityOwnerEvidenceKindV1::UpdateRule,
                crate::PlasticityOwnerEvidenceKindV1::MutationPolicy,
                crate::PlasticityOwnerEvidenceKindV1::ModulatorBroadcast,
            ]).any(|(id, kind)| {
                !artifacts.is_eligible(id)
                    || artifacts.manifest(id).is_none_or(|manifest| {
                        manifest.kind != codex_hepta_agent_components::learning_artifacts::ArtifactKind::Policy
                            || !policy.allows(kind, &manifest.producer_id)
                    })
            })
        {
            return Err(AgentdError::Invalid(
                "plasticity CURRENT policy bindings".to_string(),
            ));
        }
        Ok(Self { source, policy_ids })
    }

    pub(crate) fn verify(
        &self,
        frozen: &ArtifactRegistry,
        baseline: &StableId,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryUseWindowV1, AgentdError> {
        let view = self.source.read_at(now).map_err(|error| {
            AgentdError::Invalid(format!("plasticity CURRENT unavailable: {error}"))
        })?;
        if view.receipt().head_digest != frozen.head_digest()
            || self
                .policy_ids
                .iter()
                .chain(std::iter::once(baseline))
                .any(|id| {
                    frozen.manifest(id).is_none()
                        || view.eligible_manifest(id) != frozen.manifest(id)
                })
        {
            return Err(AgentdError::Invalid(
                "plasticity CURRENT admission changed".to_string(),
            ));
        }
        view.use_window()
            .map_err(|error| AgentdError::Invalid(error.to_string()))
    }
}

#[cfg(test)]
pub(super) fn fixture_current_artifacts(
    artifacts: &ArtifactRegistry,
) -> PlasticityCurrentArtifactsV1 {
    let registry = artifacts.clone();
    fixture_current_reader(move |_| fixture_verified_registry(&registry))
}

#[cfg(test)]
pub(super) fn fixture_current_reader(
    reader: impl Fn(
        u64,
    ) -> Result<
        codex_hepta_agent_components::learning_artifacts::VerifiedCurrentRegistryViewV1,
        String,
    > + Send
    + Sync
    + 'static,
) -> PlasticityCurrentArtifactsV1 {
    PlasticityCurrentArtifactsV1 {
        source: CurrentArtifactRegistrySourceV1::fixture(reader),
        policy_ids: ["policy:update-rule", "policy:mutation", "policy:broadcast"]
            .map(|id| StableId::new(id).expect("fixture policy id")),
    }
}

#[cfg(test)]
pub(super) fn fixture_verified_registry(
    registry: &ArtifactRegistry,
) -> Result<codex_hepta_agent_components::learning_artifacts::VerifiedCurrentRegistryViewV1, String>
{
    let root = tempfile::tempdir().map_err(|error| error.to_string())?;
    let path = root.path().join("snapshot");
    let receipt = codex_hepta_agent_components::learning_artifacts::write_registry_snapshot(
        codex_hepta_agent_components::learning_artifacts::CreateOnlyArtifactFile::create(&path)
            .map_err(|error| error.to_string())?,
        registry,
        codex_hepta_agent_components::types::Digest32::of_bytes(b"plasticity-current-fixture"),
    )
    .map_err(|error| error.to_string())?;
    crate::cognitive_ranker::verified_fixture_current_view(
        std::fs::File::open(path).map_err(|error| error.to_string())?,
        receipt,
        codex_hepta_agent_components::types::Digest32::ZERO,
    )
}
