//! Joint-only signed deployment under the existing ordinary FinalUse owner.
//! This loader consumes pinned public trust and existing authority services.
//! It cannot initialize a root, create a permission or sign a Training receipt.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::time::Duration;

use codex_hepta_automation::AuthorizedEffectDispatchRequest;
use codex_hepta_automation::JointTextInputRefV1;
use codex_hepta_automation::JointTextProcessSupervisor;
use codex_hepta_automation::JointTextProcessSupervisorConfig;
use codex_hepta_automation::JointTextProfileV1;
use codex_hepta_automation::JointTextRootIdentityV1;
use codex_hepta_automation::JointTextSupervisorError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::PqAuthorityTrustKey;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::pq_auth::PqNativeVerifier;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::automation_joint_text_inputs::JointTextInputCustodyV1;
use crate::pq_final_use::LockedDispatchLease;
use crate::pq_final_use::PqDispatchLease;
use crate::pq_final_use::PqFinalUseConfig;
use crate::pq_final_use::PqFinalUseGate;

use super::AgentdAutomationEffectHost;
use super::EffectProvider;
use super::joint::JointTextProvider;
use super::joint::RetainedJointTextDriver;
use super::joint_source::JointTextSourceManifestV1;
use super::validate_host_identifier;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct JointTextPqHostFileV4 {
    schema_version: u32,
    provider: ProviderKind,
    authority_profile: ProductionProfile,
    deployment: JointTextDeploymentV1,
    deployment_key: PqAuthorityTrustKey,
    deployment_signature: Vec<u8>,
    final_use: PqFinalUseConfig,
}

#[derive(Debug, Deserialize)]
enum ProviderKind {
    #[serde(rename = "joint_text_process_v1")]
    JointText,
}

#[derive(Debug, Deserialize)]
enum ProductionProfile {
    #[serde(rename = "production_ml_dsa65_v2")]
    MlDsa65,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct JointTextDeploymentV1 {
    schema_version: u32,
    profile: JointTextProfileV1,
    operations: [String; 2],
    contract_id: String,
    authority_epoch: u64,
    provider_scope: String,
    final_use_scope_sha256: Sha256Digest,
    python_executable: PathBuf,
    python_sha256: Sha256Digest,
    repository_root: PathBuf,
    supervisor_sha256: Sha256Digest,
    source_manifest: JointTextSourceManifestV1,
    durable_root: PathBuf,
    root_identity: JointTextRootIdentityV1,
    timeout_ms: u64,
}

impl JointTextDeploymentV1 {
    fn signing_bytes(&self) -> Result<Vec<u8>, AgentdError> {
        if self.schema_version != 1
            || self.authority_epoch == 0
            || !(1..=30_000).contains(&self.timeout_ms)
            || self.operations != ["joint.text.training.start", "joint.text.training.cancel"]
        {
            return Err(AgentdError::Invalid(
                "invalid Joint deployment profile or limits".to_string(),
            ));
        }
        self.root_identity.validate().map_err(|_| {
            AgentdError::Invalid("invalid Joint deployment root identity".to_string())
        })?;
        validate_host_identifier("contract_id", &self.contract_id)?;
        validate_host_identifier("provider_scope", &self.provider_scope)?;
        let mut bytes = b"hepta.joint.text.deployment-contract.pq.v1\0".to_vec();
        bytes.extend(serde_json::to_vec(self)?);
        Ok(bytes)
    }
}

impl AgentdAutomationEffectHost {
    pub(super) fn open_joint_text_pq(
        identity: &AgentdIdentity,
        config: JointTextPqHostFileV4,
    ) -> Result<Self, AgentdError> {
        let ProviderKind::JointText = config.provider;
        let ProductionProfile::MlDsa65 = config.authority_profile;
        let deployment = config.deployment;
        validate_host_identifier("deployment_key.key_id", &config.deployment_key.key_id)?;
        if config.schema_version != 4
            || deployment.authority_epoch != config.final_use.head.authority_epoch
            || config.deployment_key.not_before_authority_epoch == 0
            || config.deployment_key.not_after_authority_epoch
                < config.deployment_key.not_before_authority_epoch
            || deployment.authority_epoch < config.deployment_key.not_before_authority_epoch
            || deployment.authority_epoch > config.deployment_key.not_after_authority_epoch
        {
            return Err(AgentdError::Invalid(
                "invalid production Joint profile or epoch".to_string(),
            ));
        }
        PqNativeVerifier::from_pinned_spki(
            &config.deployment_key.public_key_spki,
            config.deployment_key.public_key_id,
        )
        .and_then(|key| {
            let bytes = deployment
                .signing_bytes()
                .map_err(|_| codex_hepta_contracts::pq_auth::PqNativeError::SignatureRejected)?;
            key.verify_exact_message(&bytes, &config.deployment_signature)
                .map(|_| ())
        })
        .map_err(|error| AgentdError::Invalid(format!("Joint deployment attestation: {error}")))?;
        deployment
            .source_manifest
            .verify(&deployment.repository_root)
            .map_err(|error| AgentdError::Invalid(format!("Joint source attestation: {error}")))?;
        let custody = Arc::new(JointTextInputCustodyV1::open_existing(
            &deployment.durable_root,
            &deployment.root_identity,
        )?);
        let source_manifest = Arc::new(deployment.source_manifest);
        let supervisor = JointTextProcessSupervisorConfig {
            python_executable: deployment.python_executable,
            python_sha256: deployment.python_sha256,
            repository_root: deployment.repository_root,
            supervisor_sha256: deployment.supervisor_sha256,
            durable_root: deployment.durable_root,
            root_identity: deployment.root_identity,
            deadline: Duration::from_millis(deployment.timeout_ms),
        };
        let authority_root = identity
            .layout
            .automation_root()
            .join("final-use-authority");
        let revocations_file = config.final_use.signed_revocations_file.clone();
        let frontier = (
            config.final_use.head.authority_epoch,
            config.final_use.head.revision,
        );
        let (authority, gate) = config
            .final_use
            .open(&authority_root, &[&config.deployment_key])
            .map_err(|error| AgentdError::Invalid(format!("production Joint trust: {error}")))?;
        gate.refresh(&authority, &revocations_file)
            .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
        let gate = Arc::new(gate);
        let provider = JointTextProvider {
            provider_scope: deployment.provider_scope.clone(),
            config: supervisor,
            custody,
            source_manifest,
            checkpoints: Arc::default(),
        };
        // Validate the fixed transport configuration without contacting it.
        // The mandatory closure retains actual custody and current trust; no
        // default-success or engineering supervisor is constructed here.
        let guard_provider = provider.clone();
        let guard_gate = Arc::clone(&gate);
        let guard_authority = authority.clone();
        let guard_revocations = revocations_file.clone();
        JointTextProcessSupervisor::new_with_contact_guard(provider.config.clone(), move || {
            guard_provider.verify_sources_and_custody(None)?;
            guard_gate
                .refresh(&guard_authority, &guard_revocations)
                .map_err(|_| JointTextSupervisorError::BeforeContact)
        })
        .map_err(|_| {
            AgentdError::Invalid("Joint supervisor deployment pins rejected".to_string())
        })?;
        Ok(Self {
            agent_id: identity.agent_id.clone(),
            provider_scope: deployment.provider_scope.clone(),
            destination_id: deployment.provider_scope,
            final_use_scope_digest: deployment.final_use_scope_sha256,
            authority,
            revocations_file,
            revocation_frontier: Arc::new(Mutex::new(frontier)),
            pq_gate: Some(gate),
            adapter: EffectProvider::JointText(provider),
        })
    }
}

pub(super) struct JointTextClaim {
    pub(super) lease: PqDispatchLease,
    pub(super) admitted: Arc<OnceLock<LockedDispatchLease>>,
}

impl JointTextProvider {
    pub(super) fn driver_with_lease(
        &self,
        request: &AuthorizedEffectDispatchRequest<'_>,
        lease: PqDispatchLease,
        gate: Arc<PqFinalUseGate>,
        authority: FinalUseAuthority,
        revocations_file: PathBuf,
    ) -> Result<RetainedJointTextDriver, AgentdError> {
        let checkpoint = if request.intent.operation_id == "joint.text.training.start" {
            let input = JointTextInputRefV1::decode(request.wire_payload)
                .map_err(|_| AgentdError::Invalid("invalid Joint Start descriptor".to_string()))?;
            Some(self.checkpoint_for(&input)?)
        } else {
            None
        };
        let grant = request.signed_grant.clone();
        let admitted = Arc::new(OnceLock::<LockedDispatchLease>::new());
        let at_contact = Arc::clone(&admitted);
        let mut driver = self.driver_with_contact_guard(
            &request.intent.operation_id,
            request.wire_payload,
            move || {
                if let Some(checkpoint) = &checkpoint {
                    let checkpoint_current = checkpoint.require_current();
                    checkpoint_current.map_err(|_| JointTextSupervisorError::BeforeContact)?;
                }
                at_contact
                    .get()
                    .ok_or(JointTextSupervisorError::BeforeContact)?
                    .check()
                    .map_err(|_| JointTextSupervisorError::BeforeContact)?;
                gate.authenticate(&authority, &revocations_file, &grant)
                    .and_then(|current| current.check().map_err(Into::into))
                    .map_err(|_| JointTextSupervisorError::BeforeContact)
            },
        )?;
        driver.claim = Some(JointTextClaim { lease, admitted });
        Ok(driver)
    }
}
