//! Actual Root0600, immutable trust material. These original descriptors stay
//! in Root; the peer can only request the already registered signed data.

use std::io;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use serde::Deserialize;

use super::shared_files::MetadataFile;
use crate::AgentdIdentity;
use crate::HostGenerationInitialDeploymentV1;
use crate::OriginalSingleQ24SourceConfigurationV1;
use crate::root_initial_learning_trust_data::LearningTrustDistributionDataV1;
use crate::root_initial_learning_trust_data::LearningTrustPayloadV1;
use crate::root_initial_learning_trust_data::LearningTrustPinV1;
use crate::root_initial_learning_trust_data::LearningTrustRoleSelectionV1;
use crate::root_initial_learning_trust_data::LearningTrustRootDataV1;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Deployment {
    schema: u8,
    mode: String,
    deployment: HostGenerationInitialDeploymentV1,
    learning_scope: [u8; 32],
    objective: [u8; 32],
    root_key: PathBuf,
    distribution: PathBuf,
    source_deployment: PathBuf,
    generator: LearningTrustRoleSelectionV1,
    observer: LearningTrustRoleSelectionV1,
}

/// Root-only immutable input custody, before it is bound to a real registration.
/// It is not a signer, an activated trust object or a claim of A completion.
pub struct RootInitialLearningTrustFilesV1 {
    descriptor: MetadataFile,
    root: MetadataFile,
    distribution: MetadataFile,
    source: MetadataFile,
    source_bytes: Vec<u8>,
    expected: Deployment,
    payload: LearningTrustPayloadV1,
}

pub(crate) struct RegisteredInitialLearningTrustV1 {
    files: Arc<RootInitialLearningTrustFilesV1>,
    identity: AgentdIdentity,
    deployment: HostGenerationInitialDeploymentV1,
    pub(crate) pin: LearningTrustPinV1,
}

impl RootInitialLearningTrustFilesV1 {
    /// The original administrator supplies already signed material. No daemon
    /// key, generated issuer, path fallback or Missing initialization is used.
    pub fn open_original_learning_trust(path: &Path) -> io::Result<Self> {
        crate::authority_host_service::generation_initial::original_root()?;
        let (descriptor, bytes) = MetadataFile::open_metadata(path)?;
        let expected: Deployment = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if expected.schema != 1
            || expected.mode != "pinned_genesis_v1"
            || expected.learning_scope == [0; 32]
            || expected.objective == [0; 32]
        {
            return Err(io::Error::other(
                "explicit original genesis trust mapping required",
            ));
        }
        let paths = [
            path,
            &expected.root_key,
            &expected.distribution,
            &expected.source_deployment,
        ];
        for (index, original) in paths.iter().enumerate() {
            if paths[..index].contains(original) {
                return Err(io::Error::other(
                    "distinct original trust metadata required",
                ));
            }
        }
        let (root, bytes) = MetadataFile::open_metadata(&expected.root_key)?;
        let root_data: LearningTrustRootDataV1 =
            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        let (distribution, bytes) = MetadataFile::open_metadata(&expected.distribution)?;
        let distribution_data: LearningTrustDistributionDataV1 =
            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        let (source, source_bytes) = MetadataFile::open_metadata(&expected.source_deployment)?;
        let payload = LearningTrustPayloadV1 {
            root: root_data,
            distribution: distribution_data,
            generator: expected.generator.clone(),
            observer: expected.observer.clone(),
        };
        // Leave a fixed envelope budget within the unchanged 16KiB lane. The
        // handler additionally checks its complete actual encoded response.
        if serde_json::to_vec(&payload)
            .map_err(io::Error::other)?
            .len()
            > 12 * 1024
        {
            return Err(io::Error::other(
                "original trust payload exceeds bounded lane",
            ));
        }
        let files = Self {
            descriptor,
            root,
            distribution,
            source,
            source_bytes,
            expected,
            payload,
        };
        files.require_original_files()?;
        Ok(files)
    }

    pub(crate) fn bind_original(
        self: Arc<Self>,
        identity: &AgentdIdentity,
        deployment: &HostGenerationInitialDeploymentV1,
        now_millis: u64,
    ) -> io::Result<RegisteredInitialLearningTrustV1> {
        crate::authority_host_service::generation_initial::original_root()?;
        let pin = self.observe_original(identity, deployment, now_millis)?;
        Ok(RegisteredInitialLearningTrustV1 {
            files: self,
            identity: identity.clone(),
            deployment: deployment.clone(),
            pin,
        })
    }

    pub(super) fn require_original_files(&self) -> io::Result<()> {
        self.descriptor.require_metadata_unchanged()?;
        self.root.require_metadata_unchanged()?;
        self.distribution.require_metadata_unchanged()?;
        self.source.require_metadata_unchanged()
    }

    fn observe_original(
        &self,
        identity: &AgentdIdentity,
        deployment: &HostGenerationInitialDeploymentV1,
        now_millis: u64,
    ) -> io::Result<LearningTrustPinV1> {
        crate::authority_host_service::generation_initial::original_root()?;
        self.require_original_files()?;
        if &self.expected.deployment != deployment {
            return Err(io::Error::other(
                "trust mapping is not the actual Initial deployment",
            ));
        }
        let source = OriginalSingleQ24SourceConfigurationV1::from_original_deployment_bytes(
            &self.source_bytes,
            identity,
        )?;
        require_actual_source(identity, deployment, &source)?;
        let (activated, _, _) = self.payload.activate_pinned_genesis(now_millis / 1_000)?;
        if activated.verifier().scope_digest().into_array() != self.expected.learning_scope
            || activated.verifier().objective_digest().into_array() != self.expected.objective
            || activated.verifier().objective_digest() != source.source.objective_digest
        {
            return Err(io::Error::other(
                "original trust scope/objective mapping differs",
            ));
        }
        let pin = LearningTrustPinV1 {
            mapping: self.descriptor.digest().to_string(),
            target: Digest32::from_array(deployment.target.digest().map_err(io::Error::other)?)
                .to_string(),
            task: Digest32::from_array(deployment.target.task_digest()).to_string(),
            source_metadata: self.source.digest().to_string(),
            root: activated.root_digest().to_string(),
            distribution: activated.distribution_digest().to_string(),
            trust: activated.verifier().trust_digest().to_string(),
            learning_scope: activated.verifier().scope_digest().to_string(),
            objective: activated.verifier().objective_digest().to_string(),
            roles: self.payload.role_digest()?.to_string(),
        };
        pin.require_target(&deployment.target)?;
        self.require_original_files()?;
        Ok(pin)
    }
}

impl RegisteredInitialLearningTrustV1 {
    pub(crate) fn revalidate(&self, now_millis: u64) -> io::Result<()> {
        if self
            .files
            .observe_original(&self.identity, &self.deployment, now_millis)?
            != self.pin
        {
            return Err(io::Error::other(
                "original registered learning trust changed",
            ));
        }
        Ok(())
    }

    pub(crate) fn read_original_payload(
        &self,
        now_millis: u64,
    ) -> io::Result<LearningTrustPayloadV1> {
        self.revalidate(now_millis)?;
        let payload = self.files.payload.clone();
        self.revalidate(now_millis)?;
        Ok(payload)
    }
}

fn require_actual_source(
    identity: &AgentdIdentity,
    deployment: &HostGenerationInitialDeploymentV1,
    original: &OriginalSingleQ24SourceConfigurationV1,
) -> io::Result<()> {
    let source = &original.source;
    let target = &deployment.target;
    let scope = target.scope();
    if scope.agent_id != identity.agent_id.as_str()
        || original.fence.owner_agent_id != identity.agent_id
        || identity.spawn_generation.checked_add(1) != Some(original.fence.generation)
        || scope.agent_id != source.scope.agent_id.as_str()
        || scope.cell_id != source.scope.cell_id.as_str()
        || scope.run_id != source.scope.run_id.as_str()
        || scope.principal_digest != source.scope.principal_digest.into_array()
        || target.source_frontier() != source.source_frontier.into_array()
        || target.task_digest()
            != crate::circuit_feature_task_digest_v1(&original.definition, source)
                .map_err(io::Error::other)?
                .into_array()
    {
        return Err(io::Error::other(
            "learning trust Source is not the actual Initial task",
        ));
    }
    Ok(())
}
