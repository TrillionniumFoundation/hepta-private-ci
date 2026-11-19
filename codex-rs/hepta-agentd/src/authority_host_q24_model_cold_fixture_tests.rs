//! Protected setup for the actual two-Root-process factory qualification.
//! Learning request/material data are synthetic; no learning result is minted.

use super::*;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;

#[derive(serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Setup {
    pub(super) config: crate::HostAuthorityServiceConfig,
    pub(super) identity: crate::HostAuthorityRegisteredIdentity,
    pub(super) initial_data: crate::HostAuthorityLearningProfileV1,
}

pub(super) struct Fixture {
    pub(super) protected: tempfile::TempDir,
    pub(super) witnesses: tempfile::TempDir,
    _scope_files: tempfile::TempDir,
}

impl Fixture {
    pub(super) fn new() -> anyhow::Result<Self> {
        let bind = original_bind(
            "HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT",
            "HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE",
        )?;
        let witness_bind = original_bind(
            "HEPTA_Q24_FACTORY_WITNESS_BIND",
            "HEPTA_Q24_FACTORY_WITNESS_SOURCE",
        )?;
        anyhow::ensure!((bind.device, bind.inode) != (witness_bind.device, witness_bind.inode));
        let protected = tempfile::Builder::new()
            .prefix("factory-v2-cold-")
            .tempdir_in(&bind.mountpoint)?;
        let witnesses = tempfile::Builder::new()
            .prefix("factory-v2-cold-")
            .tempdir_in(&witness_bind.mountpoint)?;
        for directory in [protected.path(), witnesses.path()] {
            std::fs::set_permissions(directory, std::fs::Permissions::from_mode(0o700))?;
        }
        let (scope_files, identity, coordinator) =
            crate::learning_iteration_checkpoint::learning_test_support::fixture()?;
        let mut request = coordinator.snapshot().request.clone();
        request.envelope.expiry_unix_seconds = now_ms()? / 1000 + 120;
        let initial =
            LearningIterationCoordinatorV1::new(request, coordinator.snapshot().owners.clone())?;
        // This seed profile is data only. Each service process constructs its
        // actual learning profile from a newly verified canonical Root proof.
        let initial_data = crate::HostAuthorityLearningProfileV1::new_scoped_v2(
            &identity,
            [7; 32],
            initial.snapshot().request.clone(),
            initial.snapshot().owners.clone(),
            codex_hepta_learning_artifacts::LearningUpdateScopeV2::Cell,
            Digest32::of_bytes(UPDATE_RULE),
        )?;
        let registered = crate::HostAuthorityRegisteredIdentity {
            agent_id: identity.agent_id.clone(),
            spawn_generation: identity.spawn_generation,
            fleet_root: identity.fleet_root.clone(),
            workspace: identity.workspace.clone(),
            resources: identity.resources.clone(),
        };
        let bootstrap_path = protected.path().join("bootstrap.json");
        support::write_json(
            &bootstrap_path,
            &crate::HostAuthorityBootstrap {
                schema_version: 1,
                required_bind: bind.clone(),
                signer_id: "factory-cold-original-root".into(),
                policies: vec![crate::DeploymentGrantPolicy {
                    subject_id: identity.agent_id.to_string(),
                    destination_id: "qualification.factory.no-effect".into(),
                    scope_sha256: [2; 32],
                    lifetime_ms: 30_000,
                }],
                lease_id: "factory-cold-original-root".into(),
                lease_binding: AuthorityLeaseBinding {
                    principal_id: identity.agent_id.to_string(),
                    operation_class: "runtime.agentd.production_operation".into(),
                    destination_id: "qualification.factory.no-effect".into(),
                    scope_sha256: [2; 32],
                    payload_sha256: [3; 32],
                },
                lease_lifetime_ms: 60_000,
            },
        )?;
        let state = protected.path().join("authority");
        let initialized = crate::initialize_host_authority(&state, &bootstrap_path)?;
        anyhow::ensure!(!initialized.production_ready);
        let now = now_ms()?;
        let config = crate::HostAuthorityServiceConfig {
            schema_version: 1,
            issuer_record_profile: crate::HostIssuerRecordProfile::Standard,
            state_dir: state,
            required_bind: bind,
            signer_id: initialized.signer_id,
            expected_verifying_key: initialized.verifying_key,
            lease_id: initialized.lease_id,
            lease_revision: initialized.lease_revision,
            writer: Some(crate::HostAuthorityWriterRegistration {
                registered_agent_id: identity.agent_id.clone(),
                spawn_generation: identity.spawn_generation,
                owner_epoch: 1,
                local_lease_id: "factory-cold-local-writer".into(),
                local_lease_generation: 1,
                authority_lease: AuthorityLease {
                    schema_version: 1,
                    lease_id: "factory-cold-writer-first".into(),
                    revision: 1,
                    authority_epoch: 1,
                    binding: AuthorityLeaseBinding {
                        principal_id: identity.agent_id.to_string(),
                        operation_class: "runtime.agentd.production_writer".into(),
                        destination_id: "qualification.factory.no-effect.cognitive-owner".into(),
                        scope_sha256: [6; 32],
                        payload_sha256: [7; 32],
                    },
                    issued_at_unix_ms: now,
                    expires_at_unix_ms: now + 5_000,
                },
            }),
            checkpoint_state_dir: None,
            consumers: None,
            sockets: crate::HostAuthoritySocketPaths {
                observation: PathBuf::from("/run/unbound-factory-cold/observation.sock"),
                issuer: PathBuf::from("/run/unbound-factory-cold/issuer.sock"),
                checkpoint: PathBuf::from("/run/unbound-factory-cold/checkpoint.sock"),
                device_frontier: None,
                notes_frontier: None,
            },
            peer_uid: 60001,
            peer_gid: 60001,
            timeout_ms: 500,
            lifetime_ms: 5_000,
        };
        support::write_json(
            &protected.path().join("setup.json"),
            &Setup {
                config,
                identity: registered,
                initial_data,
            },
        )?;
        support::write_json(
            &protected.path().join("reservation.json"),
            &crate::HostAuthorityQ24ModelFactoryReservationV1 {
                schema_version: 1,
                witness_bind,
                witness_directory: witnesses.path().to_owned(),
                local_policy_digest: Digest32::of_bytes(b"original-cold-precommitted-policy")
                    .to_string(),
            },
        )?;
        Ok(Self {
            protected,
            witnesses,
            _scope_files: scope_files,
        })
    }
}

pub(super) fn now_ms() -> anyhow::Result<u64> {
    Ok(std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_millis()
        .try_into()?)
}

fn original_bind(
    parent_variable: &str,
    source_variable: &str,
) -> anyhow::Result<crate::HostAuthorityBindIdentity> {
    let mountpoint = PathBuf::from(
        std::env::var_os(parent_variable)
            .ok_or_else(|| anyhow::anyhow!("{parent_variable} required"))?,
    );
    let source_path = PathBuf::from(
        std::env::var_os(source_variable)
            .ok_or_else(|| anyhow::anyhow!("{source_variable} required"))?,
    );
    let metadata = std::fs::metadata(&mountpoint)?;
    let bind = crate::HostAuthorityBindIdentity {
        mountpoint,
        source_path,
        device: metadata.dev(),
        inode: metadata.ino(),
    };
    bind.verify()?;
    Ok(bind)
}
