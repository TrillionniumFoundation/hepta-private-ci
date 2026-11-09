//! Explicit ML-DSA-65 HCSN composition under the existing effect owner.
//! Configuration carries only pinned public trust. External clock/frontier
//! services must already exist; this loader neither creates nor seeds them.

use std::sync::OnceLock;

use codex_hepta_contracts::PqAuthorityTrustKey;
use codex_hepta_contracts::pq_auth::PqNativeVerifier;
use serde::Serialize;

use crate::pq_final_use::LockedDispatchLease;
use crate::pq_final_use::PqDispatchLease;
use crate::pq_final_use::PqFinalUseConfig;
use crate::pq_final_use::PqFinalUseGate;

use super::*;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct HcsnPqHostFileV3 {
    schema_version: u32,
    provider: HcsnProvider,
    authority_profile: HcsnProductionProfile,
    deployment: HcsnDeploymentV1,
    deployment_key: PqAuthorityTrustKey,
    deployment_signature: Vec<u8>,
    final_use: PqFinalUseConfig,
}

#[derive(Debug, Deserialize)]
enum HcsnProvider {
    #[serde(rename = "hcsn_process_v1")]
    Process,
}

#[derive(Debug, Deserialize)]
enum HcsnProductionProfile {
    #[serde(rename = "production_ml_dsa65_v2")]
    MlDsa65,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct HcsnDeploymentV1 {
    schema_version: u32,
    contract_id: String,
    authority_epoch: u64,
    provider_scope: String,
    final_use_scope_sha256: Sha256Digest,
    python_executable: PathBuf,
    python_sha256: Sha256Digest,
    repository_root: PathBuf,
    supervisor_sha256: Sha256Digest,
    source_manifest: super::hcsn_source::HcsnSourceManifest,
    durable_root: PathBuf,
    timeout_ms: u64,
}

impl HcsnDeploymentV1 {
    fn signing_bytes(&self) -> Result<Vec<u8>, AgentdError> {
        if self.schema_version != 1
            || self.authority_epoch == 0
            || !(1..=30_000).contains(&self.timeout_ms)
        {
            return Err(AgentdError::Invalid(
                "invalid HCSN deployment limits".to_string(),
            ));
        }
        validate_host_identifier("contract_id", &self.contract_id)?;
        validate_host_identifier("provider_scope", &self.provider_scope)?;
        let mut bytes = b"hepta.hcsn.deployment-contract.pq.v1\0".to_vec();
        bytes.extend(serde_json::to_vec(self)?);
        Ok(bytes)
    }
}

impl AgentdAutomationEffectHost {
    pub(super) fn open_hcsn_pq(
        identity: &AgentdIdentity,
        config: HcsnPqHostFileV3,
    ) -> Result<Self, AgentdError> {
        let HcsnProvider::Process = config.provider;
        let HcsnProductionProfile::MlDsa65 = config.authority_profile;
        let deployment = config.deployment;
        validate_host_identifier("deployment_key.key_id", &config.deployment_key.key_id)?;
        if config.schema_version != 3
            || deployment.authority_epoch != config.final_use.head.authority_epoch
            || config.deployment_key.not_before_authority_epoch == 0
            || config.deployment_key.not_after_authority_epoch
                < config.deployment_key.not_before_authority_epoch
            || deployment.authority_epoch < config.deployment_key.not_before_authority_epoch
            || deployment.authority_epoch > config.deployment_key.not_after_authority_epoch
        {
            return Err(AgentdError::Invalid(
                "invalid PQ HCSN profile or epoch".to_string(),
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
        .map_err(|error| AgentdError::Invalid(format!("HCSN deployment attestation: {error}")))?;
        deployment
            .source_manifest
            .verify(&deployment.repository_root)
            .map_err(|error| AgentdError::Invalid(format!("HCSN source attestation: {error}")))?;
        let source_manifest = Arc::new(deployment.source_manifest);
        let supervisor = codex_hepta_automation::HcsnProcessSupervisorConfig {
            python_executable: deployment.python_executable,
            python_sha256: deployment.python_sha256,
            repository_root: deployment.repository_root,
            supervisor_sha256: deployment.supervisor_sha256,
            durable_root: deployment.durable_root,
            deadline: Duration::from_millis(deployment.timeout_ms),
        };
        codex_hepta_automation::HcsnProcessSupervisor::new(supervisor.clone()).map_err(|_| {
            AgentdError::Invalid("HCSN supervisor deployment pins rejected".to_string())
        })?;
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
            .map_err(|error| AgentdError::Invalid(format!("PQ HCSN trust: {error}")))?;
        gate.refresh(&authority, &revocations_file)
            .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
        let requests_root = supervisor.durable_root.join("taskflow-requests");
        hcsn::create_private_directory(&requests_root)?;
        let provider = hcsn::HcsnProvider {
            provider_scope: deployment.provider_scope.clone(),
            config: supervisor,
            requests_root,
            source_manifest: Some(source_manifest),
        };
        Ok(Self {
            agent_id: identity.agent_id.clone(),
            provider_scope: deployment.provider_scope.clone(),
            destination_id: deployment.provider_scope,
            final_use_scope_digest: deployment.final_use_scope_sha256,
            authority,
            revocations_file,
            revocation_frontier: Arc::new(Mutex::new(frontier)),
            pq_gate: Some(Arc::new(gate)),
            adapter: EffectProvider::Hcsn(provider),
        })
    }
}

pub(super) struct HcsnClaim {
    pub(super) lease: PqDispatchLease,
    pub(super) admitted: Arc<OnceLock<LockedDispatchLease>>,
}

impl hcsn::HcsnProvider {
    pub(super) fn driver_with_lease(
        &self,
        operation: &str,
        lease: PqDispatchLease,
        gate: Arc<PqFinalUseGate>,
        authority: FinalUseAuthority,
        revocations_file: PathBuf,
        grant: SignedFinalUseGrant,
    ) -> Result<hcsn::RetainedDriver, AgentdError> {
        let admitted = Arc::new(OnceLock::<LockedDispatchLease>::new());
        let at_contact = Arc::clone(&admitted);
        let mut driver = self.driver_with_contact_guard(operation, move || {
            at_contact
                .get()
                .ok_or(codex_hepta_automation::HcsnSupervisorError::BeforeContact)?
                .check()
                .map_err(|_| codex_hepta_automation::HcsnSupervisorError::BeforeContact)?;
            // with_verified_effect holds an active-effect fence, not its mutex.
            // A newer feed cannot commit while active; that refusal prevents
            // contact. Reconfirming the same authenticated head remains valid.
            gate.authenticate(&authority, &revocations_file, &grant)
                .and_then(|current| current.check().map_err(Into::into))
                .map_err(|_| codex_hepta_automation::HcsnSupervisorError::BeforeContact)
        })?;
        driver.pq_claim = Some(HcsnClaim { lease, admitted });
        Ok(driver)
    }
}

#[cfg(test)]
#[path = "automation_hcsn_pq_tests.rs"]
mod tests;
