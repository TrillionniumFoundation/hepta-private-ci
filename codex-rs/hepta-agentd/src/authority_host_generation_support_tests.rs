//! Explicit engineering fixtures for the real Root host factory. CURRENT,
//! issuer, lease Registry, clock and consumer frontier use protected original
//! factories. Artifact/model/task fixtures remain declared mechanism inputs;
//! no test here is an independently authorized useful A/B/C deployment.

use super::*;
use std::fs::File;
use std::io::Write as _;
use std::os::unix::fs::DirBuilderExt as _;
use std::os::unix::fs::MetadataExt as _;
use std::os::unix::fs::OpenOptionsExt as _;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::HostAuthorityClock;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;

use crate::DeploymentFinalUseIssuer;
use crate::DeploymentGrantPolicy;
use crate::HostAuthorityBootstrap;
use crate::PreparedHostAuthoritySession;
use crate::PreparedRootHostInitialGenerationV1;
use crate::RootHostInitialGenerationInputsV1;
use crate::RootHostInitialGenerationRecoveryV1;
use crate::authority_host_config::HostAuthorityBindIdentity;
use crate::authority_host_config::HostAuthorityRegisteredIdentity;
use crate::authority_host_config::HostAuthorityServiceConfig;
use crate::authority_host_config::HostAuthoritySocketPaths;
use crate::authority_host_config::HostIssuerRecordProfile;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRecoveryV1;

#[path = "authority_host_generation_peer_support_tests.rs"]
mod process;
use process::OriginalRegistrationPeer;

type HostGeneration = PreparedRootHostInitialGenerationV1<FileAnchorWitnessStore>;

enum OriginalHeadCase {
    Current,
    GrantRevoked,
    ConsumerStale,
}

struct HostFixture {
    original: RootFixture,
    _directory: tempfile::TempDir,
    config_path: std::path::PathBuf,
    registration_path: std::path::PathBuf,
    state: std::path::PathBuf,
    peer: Option<OriginalRegistrationPeer>,
    consumer: Arc<FinalUseAuthority>,
    inputs: Option<RootHostInitialGenerationInputsV1<FileAnchorWitnessStore>>,
    binding: codex_hepta_contracts::FinalUseBinding,
    signed: SignedFinalUseGrant,
}

impl HostFixture {
    async fn new(run: &str, head_case: OriginalHeadCase) -> anyhow::Result<Self> {
        let mut original = RootFixture::new(run).await?;
        let generation = original.providers.target_config.clone();
        // Reuse the existing real-clock Artifact fixture. Its test CURRENT and
        // consumer are not supplied to the Root host or the new production API.
        original.providers = VersionFixture::new_research(generation.clone(), generation)?;
        let target = original.providers.target_create()?;
        let selected = original.providers.selection()?;
        let binding = NeuronGenerationCurrentOwnerV1::original_initial_publication_binding(
            OPERATION.into(),
            crate::neuron_generation_initial::validate_initial_target(&selected, &target)?,
            &selected,
        )?;
        let runtime = &original.admission.as_ref().ok_or_else(|| anyhow::anyhow!("original admission missing"))?.runtime;
        let identity = HostAuthorityRegisteredIdentity {
            agent_id: runtime.identity.agent_id.clone(),
            spawn_generation: runtime.identity.spawn_generation,
            fleet_root: runtime.identity.fleet_root.clone(),
            workspace: runtime.identity.workspace.clone(),
            resources: runtime.identity.resources.clone(),
        };
        // These are the existing privileged qualification's actual bind inputs.
        // Missing/wrong/missing-mount values are errors at the original factory.
        let parent = std::path::PathBuf::from(std::env::var_os(
            "HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT",
        ).ok_or_else(|| anyhow::anyhow!("original protected bind parent is required"))?);
        let source_path = std::path::PathBuf::from(std::env::var_os(
            "HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE",
        ).ok_or_else(|| anyhow::anyhow!("original protected bind source is required"))?);
        let directory = tempfile::Builder::new().prefix("root-product-initial-").tempdir_in(&parent)?;
        fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700))?;
        let metadata = fs::metadata(&parent)?;
        let required_bind = HostAuthorityBindIdentity {
            mountpoint: parent,
            source_path,
            device: metadata.dev(),
            inode: metadata.ino(),
        };
        let bootstrap_path = directory.path().join("bootstrap.json");
        write_original_json(&bootstrap_path, &HostAuthorityBootstrap {
            schema_version: 1,
            required_bind: required_bind.clone(),
            signer_id: "root-product-generation-test".into(),
            policies: vec![DeploymentGrantPolicy {
                subject_id: binding.subject_id.clone(),
                destination_id: binding.destination_id.clone(),
                scope_sha256: binding.scope_sha256,
                lifetime_ms: 30_000,
            }],
            lease_id: "root-product-generation-test".into(),
            lease_binding: AuthorityLeaseBinding {
                principal_id: binding.subject_id.clone(),
                operation_class: "runtime.agentd.production_operation".into(),
                destination_id: binding.destination_id.clone(),
                scope_sha256: binding.scope_sha256,
                payload_sha256: binding.payload_sha256,
            },
            lease_lifetime_ms: 60_000,
        })?;
        let state = directory.path().join("authority");
        // Explicit test administration creates these owners once, outside the
        // proposed product entry. No seed or grant creator is added to product.
        let initialized = crate::initialize_host_authority(&state, &bootstrap_path)?;
        let root = RootAuthorityDirectory::open(&state)?;
        let clock = Arc::new(HostAuthorityClock::open(Arc::clone(&root), "root-authority-clock-v1".into())?);
        let registry_frontier = Arc::new(HostAuthorityFrontierStore::<AuthorityLeaseFrontier>::open(
            Arc::clone(&root), "root-authority-leases-v1".into(),
        )?);
        let registry = AuthorityLeaseRegistry::open_state_dir_with_trust(
            &state.join("leases"), "root-authority-leases-v1".into(), clock.clone(), registry_frontier,
        )?;
        let issuer = DeploymentFinalUseIssuer::open_protected(
            &state.join("issuer"), clock.clone(), registry.verifier(),
            initialized.lease_id.clone(), initialized.lease_revision,
        )?;
        let signed = issuer.issue(&binding)?.ok_or_else(|| anyhow::anyhow!("original test policy refused exact grant"))?;
        let original_head = issuer.revocations()?;
        match head_case {
            OriginalHeadCase::Current => {}
            OriginalHeadCase::GrantRevoked => { issuer.revoke(&signed.grant.grant_id)?; }
            OriginalHeadCase::ConsumerStale => { issuer.revoke("unrelated-original-generation-grant")?; }
        }
        let consumer_root = state.join("generation-consumer");
        fs::DirBuilder::new().mode(0o700).create(&consumer_root)?;
        let frontier = Arc::new(HostAuthorityFrontierStore::initialize(
            Arc::clone(&root), initialized.signer_id.clone(), FinalUseFrontier::for_initial_head(&original_head)?,
        )?);
        let consumer = Arc::new(FinalUseAuthority::open_state_dir_with_trust(
            &consumer_root, initialized.signer_id.clone(), initialized.verifying_key,
            original_head, clock, frontier,
        )?);
        // No duplicate live Registry owner is smuggled into Session::open.
        drop(issuer);
        drop(registry);
        let peer = OriginalRegistrationPeer::start(identity)?;
        let registration_path = directory.path().join("registration.json");
        write_original_json(&registration_path, &peer.registration)?;
        let config_path = directory.path().join("service.json");
        write_original_json(&config_path, &HostAuthorityServiceConfig {
            schema_version: 1,
            state_dir: state.clone(),
            required_bind,
            signer_id: initialized.signer_id,
            expected_verifying_key: initialized.verifying_key,
            lease_id: initialized.lease_id,
            lease_revision: initialized.lease_revision,
            writer: None,
            checkpoint_state_dir: None,
            consumers: None,
            sockets: HostAuthoritySocketPaths {
                observation: directory.path().join("observation.sock"),
                issuer: directory.path().join("issuer.sock"),
                checkpoint: directory.path().join("checkpoint.sock"),
                device_frontier: None,
                notes_frontier: None,
            },
            peer_uid: 60001,
            peer_gid: 60001,
            timeout_ms: 10_000,
            lifetime_ms: 20_000,
            issuer_record_profile: HostIssuerRecordProfile::Standard,
        })?;
        let inputs = RootHostInitialGenerationInputsV1 {
            artifacts: Arc::clone(&original.providers.artifacts),
            final_use: Arc::clone(&consumer),
            selected,
            target,
            request: AgentdGenerationUpdateRequestV1 { operation_id: OPERATION.into() },
            signed: signed.clone(),
        };
        Ok(Self { original, _directory: directory, config_path, registration_path, state,
            peer: Some(peer), consumer, inputs: Some(inputs), binding, signed })
    }

    fn session(&self) -> anyhow::Result<PreparedHostAuthoritySession> {
        Ok(PreparedHostAuthoritySession::open(
            &self.config_path, &self.registration_path,
            self.peer.as_ref().ok_or_else(|| anyhow::anyhow!("original peer missing"))?.pidfd()?,
        )?)
    }

    fn bind(&mut self) -> anyhow::Result<HostGeneration> {
        let session = self.session()?;
        let inputs = self.inputs.take().ok_or_else(|| anyhow::anyhow!("original inputs consumed"))?;
        Ok(PreparedHostAuthoritySession::bind_original_initial_generation(session, inputs)?)
    }

    fn recovery_inputs(&self) -> anyhow::Result<RootHostInitialGenerationRecoveryV1<FileAnchorWitnessStore>> {
        Ok(RootHostInitialGenerationRecoveryV1 {
            artifacts: Arc::clone(&self.original.providers.artifacts),
            final_use: Arc::clone(&self.consumer),
            selected: self.original.providers.selection()?,
            target: self.original.providers.target_reopen()?,
            recovery: AgentdGenerationUpdateRecoveryV1 {
                operation_id: OPERATION.into(),
                intent_digest: Digest32::from_array(self.binding.request_sha256),
            },
        })
    }

    fn protected_files(&self) -> anyhow::Result<Vec<String>> {
        // Clock reads may advance their own trusted state. Compare the complete
        // protected namespace, rather than falsely claiming all clock bytes are inert.
        fn visit(root: &std::path::Path, here: &std::path::Path, files: &mut Vec<String>) -> anyhow::Result<()> {
            for entry in fs::read_dir(here)? {
                let entry = entry?;
                if entry.file_type()?.is_dir() { visit(root, &entry.path(), files)?; }
                else { files.push(entry.path().strip_prefix(root)?.to_string_lossy().into_owned()); }
            }
            Ok(())
        }
        let mut files = Vec::new();
        visit(&self.state, &self.state, &mut files)?;
        files.sort();
        Ok(files)
    }

    fn finish(mut self) -> anyhow::Result<()> {
        let peer = self.peer.take().ok_or_else(|| anyhow::anyhow!("original peer already finished"))?;
        peer.finish()
    }
}

fn write_original_json(path: &std::path::Path, value: &impl serde::Serialize) -> anyhow::Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600).open(path)?;
    file.write_all(&serde_json::to_vec(value)?)?;
    file.sync_all()?;
    File::open(path.parent().ok_or_else(|| anyhow::anyhow!("missing original parent"))?)?.sync_all()?;
    Ok(())
}

#[path = "authority_host_generation_tests.rs"]
mod tests;
