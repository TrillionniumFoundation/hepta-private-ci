//! Actual protected Root storage, original issuer and Registry qualification.
//! Only explicitly selected Root tests provision these temporary test owners.
//! The metadata fixture does not represent an ordinary learning experiment.

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use pretty_assertions::assert_eq;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

use super::super::super::RootResidentLearningProfileV3;
use super::super::super::RootResidentLearningReadbackAuthorizationV3;
use super::super::super::RootResidentLearningRegistrationV3;
use crate::DeploymentGrantPolicy;
use crate::HostAuthorityBindIdentity;
use crate::HostAuthorityBootstrap;
use crate::HostAuthorityServiceConfig;
use crate::HostAuthoritySocketPaths;
use crate::HostIssuerRecordProfile;

pub(super) struct ResidentRootFixture {
    _protected: tempfile::TempDir,
    pub(super) config_file: PathBuf,
    pub(super) config: HostAuthorityServiceConfig,
    pub(super) profile: RootResidentLearningProfileV3,
    pub(super) registration: Option<RootResidentLearningRegistrationV3>,
    readback_intent: SignedFinalUseGrant,
    readback_lease: AuthorityLease,
}

fn write_new_json(path: &Path, value: &impl serde::Serialize) -> anyhow::Result<()> {
    let mut file = OpenOptions::new().create_new(true).write(true).mode(0o600).open(path)?;
    file.write_all(&serde_json::to_vec(value)?)?;
    file.sync_all()?;
    Ok(())
}

fn issuing_binding(binding: &FinalUseBinding) -> AuthorityLeaseBinding {
    AuthorityLeaseBinding {
        principal_id: binding.subject_id.clone(),
        operation_class: "runtime.agentd.production_operation".into(),
        destination_id: binding.destination_id.clone(),
        scope_sha256: binding.scope_sha256,
        payload_sha256: binding.payload_sha256,
    }
}

impl ResidentRootFixture {
    /// This helper consumes real metadata inputs but issues test-only Root
    /// grants in its own new protected directory. It never fabricates a Gate.
    pub(super) fn new(
        initial: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        verifier: &LearningEvidenceVerifierV1,
    ) -> anyhow::Result<Self> {
        Self::with_test_lifetime(initial, scope, verifier, /*lifetime_ms*/ 600_000)
    }

    /// Explicit test Root authorization covers the already-original request.
    /// No Training/Evaluation timestamp, signature or work window is changed.
    pub(super) fn for_original_evaluation_window(
        initial: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        verifier: &LearningEvidenceVerifierV1,
    ) -> anyhow::Result<Self> {
        let deadline = initial.request.envelope.expiry_unix_seconds.checked_mul(1_000)
            .ok_or_else(|| anyhow::anyhow!("original Evaluation deadline overflow"))?;
        let current = u64::try_from(std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?.as_millis())?;
        let remaining = deadline.checked_sub(current)
            .filter(|remaining| *remaining > 0)
            .ok_or_else(|| anyhow::anyhow!("original Evaluation fixture window expired"))?;
        let lifetime_ms = remaining.checked_add(60_000)
            .filter(|lifetime| *lifetime <= 3_600_000)
            .ok_or_else(|| anyhow::anyhow!("bounded explicit Root fixture window"))?;
        Self::with_test_lifetime(initial, scope, verifier, lifetime_ms)
    }

    fn with_test_lifetime(
        initial: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        verifier: &LearningEvidenceVerifierV1,
        lifetime_ms: u64,
    ) -> anyhow::Result<Self> {
        assert_eq!(rustix::process::getuid().as_raw(), 0);
        assert_eq!(rustix::process::geteuid().as_raw(), 0);
        let parent = PathBuf::from(std::env::var_os(
            "HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT",
        ).ok_or_else(|| anyhow::anyhow!("explicit protected Root bind parent required"))?);
        let source = PathBuf::from(std::env::var_os(
            "HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE",
        ).ok_or_else(|| anyhow::anyhow!("explicit original bind source required"))?);
        let metadata = std::fs::metadata(&parent)?;
        let required_bind = HostAuthorityBindIdentity {
            mountpoint: parent.clone(), source_path: source,
            device: metadata.dev(), inode: metadata.ino(),
        };
        let protected = tempfile::Builder::new().prefix("lr3-").tempdir_in(parent)?;
        std::fs::set_permissions(protected.path(), std::fs::Permissions::from_mode(0o700))?;
        let admission = RootResidentLearningProfileV3::admission_binding(&initial, &scope, verifier)?;
        let state = protected.path().join("authority");
        let bootstrap_file = protected.path().join("bootstrap.json");
        let policies = [
            crate::ROOT_RESIDENT_LEARNING_EXECUTE_V3,
            crate::ROOT_RESIDENT_LEARNING_READBACK_V3,
        ].into_iter().map(|purpose| DeploymentGrantPolicy {
            subject_id: admission.subject_id.clone(), destination_id: purpose.into(),
            scope_sha256: admission.scope_sha256, lifetime_ms,
        }).collect();
        write_new_json(&bootstrap_file, &HostAuthorityBootstrap {
            schema_version: 1, required_bind: required_bind.clone(),
            signer_id: "resident-root-qualification".into(), policies,
            lease_id: "resident-root-issuing-execute".into(),
            lease_binding: issuing_binding(&admission), lease_lifetime_ms: lifetime_ms,
        })?;
        let initialized = crate::initialize_host_authority(&state, &bootstrap_file)?;
        assert!(!initialized.production_ready);
        let mut config = HostAuthorityServiceConfig {
            schema_version: 1, issuer_record_profile: HostIssuerRecordProfile::Standard,
            state_dir: state.clone(), required_bind,
            signer_id: initialized.signer_id, expected_verifying_key: initialized.verifying_key,
            lease_id: initialized.lease_id, lease_revision: initialized.lease_revision,
            writer: None, checkpoint_state_dir: None, consumers: None,
            sockets: HostAuthoritySocketPaths {
                observation: protected.path().join("observation"),
                issuer: protected.path().join("issuer"),
                checkpoint: protected.path().join("checkpoint"),
                device_frontier: None, notes_frontier: None,
            },
            peer_uid: 60001, peer_gid: 60001, timeout_ms: 500, lifetime_ms: 300_000,
        };
        let (clock, leases, issuer) =
            crate::authority_host_runtime::open_registered_issuer(&config)?;
        let intent = issuer.issue(&admission)?.ok_or_else(|| anyhow::anyhow!("original Root intent"))?;
        let now = clock.now_unix_ms()?;
        let lease = AuthorityLease {
            schema_version: 1, lease_id: "resident-root-execution".into(),
            revision: 1, authority_epoch: 1,
            binding: super::super::super::profile::lease_binding(&admission),
            issued_at_unix_ms: now, expires_at_unix_ms: now.checked_add(lifetime_ms)
                .ok_or_else(|| anyhow::anyhow!("explicit Root lease window overflow"))?,
        };
        leases.put_lease(lease.clone(), /*expected_revision*/ 0)?;
        let profile = RootResidentLearningProfileV3::new(initial, scope, verifier, intent, lease)?;
        let readonly = profile.readback_binding()?;
        let issuing_readback = AuthorityLease {
            schema_version: 1, lease_id: "resident-root-issuing-readback".into(),
            revision: 1, authority_epoch: 1, binding: issuing_binding(&readonly),
            issued_at_unix_ms: now, expires_at_unix_ms: now.checked_add(lifetime_ms)
                .ok_or_else(|| anyhow::anyhow!("explicit Root lease window overflow"))?,
        };
        leases.put_lease(issuing_readback.clone(), /*expected_revision*/ 0)?;
        let readback_lease = AuthorityLease {
            schema_version: 1, lease_id: "resident-root-observation".into(),
            revision: 1, authority_epoch: 1,
            binding: super::super::super::profile::lease_binding(&readonly),
            issued_at_unix_ms: now, expires_at_unix_ms: now.checked_add(lifetime_ms)
                .ok_or_else(|| anyhow::anyhow!("explicit Root lease window overflow"))?,
        };
        leases.put_lease(readback_lease.clone(), /*expected_revision*/ 0)?;
        // Explicit setup closes the original issuing owner before opening it
        // under the separately registered read-only issuing purpose. No writer
        // or key is cloned; runtime never performs these fixture admin steps.
        drop(issuer);
        drop(leases);
        drop(clock);
        config.lease_id = issuing_readback.lease_id;
        let (clock, leases, issuer) =
            crate::authority_host_runtime::open_registered_issuer(&config)?;
        let readback_intent = issuer.issue(&readonly)?
            .ok_or_else(|| anyhow::anyhow!("original readback intent"))?;
        drop(issuer);
        drop(leases);
        drop(clock);
        config.lease_id = "resident-root-issuing-execute".into();
        let config_file = protected.path().join("resident.json");
        write_new_json(&config_file, &config)?;
        let registration = crate::register_host_resident_learning_v3(&config_file, profile.clone())?;
        Ok(Self { _protected: protected, config_file, config, profile,
            registration: Some(registration), readback_intent, readback_lease })
    }

    pub(super) fn readonly_authorization(&self) -> anyhow::Result<RootResidentLearningReadbackAuthorizationV3> {
        Ok(RootResidentLearningReadbackAuthorizationV3::from_original_root(
            &self.profile, self.readback_intent.clone(), self.readback_lease.clone(),
        )?)
    }

    pub(super) fn recover(&mut self) -> anyhow::Result<()> {
        self.registration.take();
        let recovered = crate::recover_host_resident_learning_v3(
            &self.config_file, self.profile.clone(), self.readonly_authorization()?,
        )?;
        self.registration = Some(recovered);
        Ok(())
    }
}
