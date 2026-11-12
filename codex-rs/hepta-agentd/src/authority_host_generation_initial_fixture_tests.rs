//! Actual Root/UID60001 initial deployment. Model and Artifact role keys are
//! component inputs; no learning checkpoint, earlier CURRENT, fabricated task
//! completion or FileCAS is created.

use super::*;
use crate::DeploymentGrantPolicy;
use crate::HostAuthorityBootstrap;
use crate::HostAuthorityConsumerConfig;
use crate::HostAuthorityConsumersConfig;
use crate::HostAuthoritySocketPaths;
use crate::HostAuthorityWriterRegistration;
use crate::HostIssuerRecordProfile;
use anyhow::Context;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

pub(super) struct Fixture {
    pub(super) child: support::ChildOwner,
    _protected: tempfile::TempDir,
    _runtime: tempfile::TempDir,
    _witnesses: tempfile::TempDir,
    config_file: PathBuf,
    registration_file: PathBuf,
    pub(super) local: PathBuf,
    pub(super) current_path: PathBuf,
    root: Arc<RootAuthorityDirectory>,
    pub(super) deployment: crate::HostGenerationInitialDeploymentV1,
    target_config: CellGenerationObserverConfigV1,
    pub(super) target_journal: PathBuf,
    target_witness: PathBuf,
    model_directory: PathBuf,
    artifacts: artifacts::Transfer,
    offer: UnixDatagram,
    pin: OwnedFd,
    drop_ack: bool,
}

impl Fixture {
    pub(super) fn new(drop_ack: bool) -> anyhow::Result<Self> {
        let parent = PathBuf::from(
            std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT")
                .ok_or_else(|| anyhow::anyhow!("original protected bind required"))?,
        );
        let source = PathBuf::from(
            std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE")
                .ok_or_else(|| anyhow::anyhow!("original protected bind source required"))?,
        );
        let metadata = std::fs::metadata(&parent)?;
        let required_bind = HostAuthorityBindIdentity {
            mountpoint: parent.clone(),
            source_path: source,
            device: metadata.dev(),
            inode: metadata.ino(),
        };
        let protected = tempfile::Builder::new()
            .prefix("root-publication-")
            .tempdir_in(&parent)?;
        std::fs::set_permissions(protected.path(), std::fs::Permissions::from_mode(0o700))?;
        let witness_parent = PathBuf::from(
            std::env::var_os("HEPTA_Q24_FACTORY_WITNESS_BIND").ok_or_else(|| {
                anyhow::anyhow!("original separate physical witness bind required")
            })?,
        );
        let witness_source = PathBuf::from(
            std::env::var_os("HEPTA_Q24_FACTORY_WITNESS_SOURCE")
                .ok_or_else(|| anyhow::anyhow!("original witness source required"))?,
        );
        let wm = std::fs::metadata(&witness_parent)?;
        HostAuthorityBindIdentity {
            mountpoint: witness_parent.clone(),
            source_path: witness_source,
            device: wm.dev(),
            inode: wm.ino(),
        }
        .verify()?;
        anyhow::ensure!(
            (metadata.dev(), metadata.ino()) != (wm.dev(), wm.ino()),
            "separate original witness domain"
        );
        let witnesses = tempfile::Builder::new()
            .prefix("publication-witness-")
            .tempdir_in(witness_parent)?;
        std::fs::set_permissions(witnesses.path(), std::fs::Permissions::from_mode(0o700))?;
        let runtime_directory = tempfile::Builder::new().prefix("hgp-").tempdir_in("/run")?;
        owned_mode(
            runtime_directory.path(),
            /*uid*/ 0,
            /*gid*/ 60001,
            /*mode*/ 0o2710,
        )?;
        // Ordinary identity paths must be traversable by the dedicated child.
        // Root authority, CURRENT and witnesses remain in their private domains.
        let workspace = runtime_directory.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let fleet = HeptaFleetRoot::parse(runtime_directory.path().join("fleet"))?;
        let registry = FleetRegistry::initialize(fleet.clone())?;
        owned_mode(
            &workspace, /*uid*/ 0, /*gid*/ 60001, /*mode*/ 0o710,
        )?;
        owned_mode(
            fleet.as_path(),
            /*uid*/ 0,
            /*gid*/ 60001,
            /*mode*/ 0o710,
        )?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace.clone(), &fleet)?,
            ResourceBudget::local_default(),
        )?)?;
        let registry_genesis = 0;
        let starting =
            registry.compare_and_transition(&agent, registry_genesis, AgentLifecycle::Starting)?;
        let registered = HostAuthorityRegisteredIdentity {
            agent_id: agent.clone(),
            spawn_generation: starting.generation,
            fleet_root: fleet.as_path().to_path_buf(),
            workspace,
            resources: ResourceBudget::local_default(),
        };
        drop(registry);
        let identity = registered.identity()?;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let fresh = runtime.block_on(crate::FreshHostCognitiveState::prepare(&registered))?;
        let local = runtime_directory.path().join("consumer-local");
        std::fs::create_dir(&local)?;
        owned_mode(
            &local, /*uid*/ 60001, /*gid*/ 60001, /*mode*/ 0o700,
        )?;

        let model_directory = runtime_directory.path().join("model");
        std::fs::create_dir(&model_directory)?;
        let (model, bundle, definition) = material::model(&model_directory)?;
        let source = material::source(agent.as_str())?;
        let generation =
            material::configuration(&model, &bundle, &definition, &source, /*generation*/ 1)?;
        crate::circuit_feature_initial_root::require_feature(
            &generation,
            &bundle,
            &model,
            &definition,
            &source,
        )?;
        let target_config = observer_config(generation)?;
        assign_component_artifacts(&model_directory)?;
        let current_path = protected.path().join("generation-current");
        std::fs::create_dir(&current_path)?;
        std::fs::set_permissions(&current_path, std::fs::Permissions::from_mode(0o700))?;
        let root = RootAuthorityDirectory::open(&current_path)?;
        let target_journal = protected.path().join("initial.journal");
        let target_witness = witnesses.path().join("initial.witness");
        let _ = private_file(&target_journal)?;
        drop(FileAnchorWitnessStore::open(
            private_file(&target_witness)?,
            target_config.witness_scope,
            target_config.witness_generation,
            target_config.witness_records,
        )?);
        owned_mode(
            &target_journal,
            /*uid*/ 60001,
            /*gid*/ 60001,
            /*mode*/ 0o600,
        )?;
        owned_mode(
            &target_witness,
            /*uid*/ 60001,
            /*gid*/ 60001,
            /*mode*/ 0o600,
        )?;
        let artifact_path = runtime_directory.path().join("artifacts");
        let artifacts = artifacts::Artifacts::new(
            &artifact_path,
            &target_config.generation.manifest,
            now_ms()?,
        )?;
        assign_component_artifacts(&artifact_path)?;
        let selected = artifacts.selection(now_ms()?)?;
        let deployment = crate::HostGenerationInitialDeploymentV1::new(
            "original-initial-component".into(),
            &target_config,
        )?;
        let (_, description) = initial_root::original_initial_description(
            deployment.operation.clone(),
            deployment.target.clone(),
            &selected,
        )?;
        let binding = description.final_use_binding().clone();
        // Release this actual Artifact writer before the child opens the same
        // original files with its original signed lease and required CURRENT.
        let artifacts = artifacts.into_transfer(now_ms()?)?;
        let state = protected.path().join("authority");
        let bootstrap_file = protected.path().join("bootstrap.json");
        support::write_json(
            &bootstrap_file,
            &HostAuthorityBootstrap {
                schema_version: 1,
                required_bind: required_bind.clone(),
                signer_id: "initial-component-root".into(),
                policies: vec![DeploymentGrantPolicy {
                    subject_id: binding.subject_id.clone(),
                    destination_id: binding.destination_id.clone(),
                    scope_sha256: binding.scope_sha256,
                    lifetime_ms: 30_000,
                }],
                lease_id: "initial-component-root".into(),
                lease_binding: AuthorityLeaseBinding {
                    principal_id: binding.subject_id,
                    operation_class: "runtime.agentd.production_operation".into(),
                    destination_id: binding.destination_id,
                    scope_sha256: binding.scope_sha256,
                    payload_sha256: binding.payload_sha256,
                },
                lease_lifetime_ms: 60_000,
            },
        )?;
        let initialized = crate::initialize_host_authority(&state, &bootstrap_file)?;
        let now = now_ms()?;
        let config = HostAuthorityServiceConfig {
            schema_version: 1,
            issuer_record_profile: HostIssuerRecordProfile::Standard,
            state_dir: state.clone(),
            required_bind,
            signer_id: initialized.signer_id.clone(),
            expected_verifying_key: initialized.verifying_key,
            lease_id: initialized.lease_id,
            lease_revision: initialized.lease_revision,
            writer: Some(HostAuthorityWriterRegistration {
                registered_agent_id: agent.clone(),
                spawn_generation: identity.spawn_generation,
                owner_epoch: 1,
                local_lease_id: "initial-component-local-writer".into(),
                local_lease_generation: 1,
                authority_lease: AuthorityLease {
                    schema_version: 1,
                    lease_id: "initial-component-root-writer".into(),
                    revision: 1,
                    authority_epoch: 1,
                    binding: AuthorityLeaseBinding {
                        principal_id: agent.to_string(),
                        operation_class: "runtime.agentd.production_writer".into(),
                        destination_id: "publication.component.cognitive-owner".into(),
                        scope_sha256: [6; 32],
                        payload_sha256: [7; 32],
                    },
                    issued_at_unix_ms: now,
                    expires_at_unix_ms: now + 60_000,
                },
            }),
            checkpoint_state_dir: Some(state.join("checkpoint")),
            consumers: Some(HostAuthorityConsumersConfig {
                device: HostAuthorityConsumerConfig {
                    state_dir: state.join("device-consumer"),
                    owner_id: initialized.signer_id.clone(),
                },
                notes: HostAuthorityConsumerConfig {
                    state_dir: state.join("notes-consumer"),
                    owner_id: initialized.signer_id,
                },
            }),
            sockets: HostAuthoritySocketPaths {
                observation: runtime_directory.path().join("observation.sock"),
                issuer: runtime_directory.path().join("issuer.sock"),
                checkpoint: runtime_directory.path().join("checkpoint.sock"),
                device_frontier: Some(runtime_directory.path().join("device-frontier.sock")),
                notes_frontier: Some(runtime_directory.path().join("notes-frontier.sock")),
            },
            peer_uid: 60001,
            peer_gid: 60001,
            timeout_ms: 500,
            lifetime_ms: 15_000,
        };
        let config_file = protected.path().join("service.json");
        support::write_json(&config_file, &config)?;

        crate::register_host_writer_authorization(&config_file)?;
        let (offer, receive) = UnixDatagram::pair()?;
        let child = support::ChildOwner::spawn(receive, &state)?;
        let pin = support::pidfd(child.pid()?)?;
        let end = Instant::now() + Duration::from_secs(2);
        while crate::authority_host_runtime::verify_process_credentials(child.pid()?, 60001, 60001)
            .is_err()
        {
            anyhow::ensure!(
                Instant::now() < end,
                "actual non-Root child credential deadline"
            );
            std::thread::sleep(Duration::from_millis(5));
        }
        let registration = HostAuthorityRegistration {
            schema_version: 1,
            peer_pid: child.pid()?,
            boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
                .trim()
                .into(),
            process_start_ticks: support::start_ticks(child.pid()?)?,
            registered_identity: registered,
            checkpoint_owner_agent_id: agent,
            publisher_epoch: 1,
        };
        let registration_file = protected.path().join("spawn.json");
        support::write_json(&registration_file, &registration)?;
        drop(PreparedHostAuthoritySession::initialize_fresh(
            &config_file,
            &registration_file,
            pin.try_clone()?,
            fresh,
        )?);

        Ok(Self {
            child,
            _protected: protected,
            _runtime: runtime_directory,
            _witnesses: witnesses,
            config_file,
            registration_file,
            local,
            current_path,
            root,
            deployment,
            target_config,
            target_journal,
            target_witness,
            model_directory,
            artifacts,
            offer,
            pin,
            drop_ack,
        })
    }

    pub(super) fn head(&self) -> anyhow::Result<types::CurrentHead> {
        Ok(
            NeuronGenerationCurrentOwnerV1::open(
                self.root.clone(),
                self.deployment.target.scope(),
            )?
            .original_broker_head()?,
        )
    }

    pub(super) fn run_phase(&mut self, phase: Phase) -> anyhow::Result<()> {
        let mut prepared = PreparedHostAuthoritySession::open(
            &self.config_file,
            &self.registration_file,
            self.pin.try_clone()?,
        )?;
        let mut sealed = prepared.seal_bootstrap(&self.local)?;
        let mut raw = Vec::new();
        sealed.rewind()?;
        sealed.read_to_end(&mut raw)?;
        let bootstrap: HostAuthorityPublicBootstrapV1 = serde_json::from_slice(&raw)?;
        sealed.rewind()?;
        let inputs = crate::RootGenerationInitialEnrollmentV1 {
            mode: if matches!(phase, Phase::Publish | Phase::ReserveExisting) {
                crate::RootGenerationInitialModeV1::Reserve
            } else {
                crate::RootGenerationInitialModeV1::Recover
            },
            current_directory: self.root.clone(),
            target: RootGenerationJournalInputsV1 {
                journal: File::open(&self.target_journal)?,
                witness: File::open(&self.target_witness)?,
                config: self.target_config.clone(),
            },
            artifacts: self.artifacts.inputs()?,
            consumer: RootPublicationFinalUseConsumerV1::Device,
            consumer_state_root: self.local.clone(),
            issuer_keys: vec![FinalUseIssuerTrustKey::from(bootstrap.issuer_key)],
        };
        let deployment_directory = tempfile::Builder::new()
            .prefix("initial-deployment-")
            .tempdir_in(self._protected.path())?;
        std::fs::set_permissions(
            deployment_directory.path(),
            std::fs::Permissions::from_mode(0o700),
        )?;
        let files = crate::RootGenerationInitialDeploymentFilesV1::component_initial_files(
            deployment_directory.path(),
            &[
                self.current_path.clone(),
                self.target_journal.clone(),
                self.target_witness.clone(),
            ],
            self.deployment.operation.clone(),
            &self.artifacts.selector_description()?,
            &inputs,
        )?;
        assert_eq!(files.deployment(), &self.deployment);
        let (capability, initial) =
            prepared.enable_generation_initial(files.deployment().clone())?;
        let before_retained = support::protected_files(&self.current_path)?;
        assert!(prepared.serve_retained().is_err());
        assert_eq!(
            support::protected_files(&self.current_path)?,
            before_retained
        );
        let capability: crate::RootGenerationInitialEnrollmentCapabilityV1 = capability;
        let deployment = capability.with_original_initial_deployment(files)?;
        let target_writer = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.target_journal)?;
        let witness_writer = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.target_witness)?;
        let plan = Plan {
            phase,
            lose_ack: self.drop_ack,
            model_directory: self.model_directory.clone(),
            artifacts: self.artifacts.clone(),
            target: data::ObserverData::from_original_observer(&self.target_config),
        };
        let root_pin = support::pidfd(std::process::id())?;
        let send = self.offer.try_clone()?;
        if phase == Phase::Publish && self.drop_ack {
            crate::authority_host_service::generation_initial::drop_next_test_publication_ack();
        }
        let reject = matches!(
            phase,
            Phase::ReserveExisting | Phase::Corrupt | Phase::Restored
        );
        std::thread::scope(|scope| -> anyhow::Result<()> {
            let registration = scope.spawn(|| -> anyhow::Result<()> {
                control(&self.offer, b"ORIGINAL_INPUTS_READY").with_context(|| {
                    format!("initial parent {phase:?}: awaiting ORIGINAL_INPUTS_READY")
                })?;
                // The original child has now opened both real nonce owners.
                // The production loader invokes the original same-PID cap.
                let unchanged = support::protected_files(&self.current_path)?;
                let claims_before = std::fs::read(self.local.join("device/authority.claims"))?;
                deployment.component_trigger_initial()?;
                assert_eq!(support::protected_files(&self.current_path)?, unchanged);
                assert_eq!(
                    std::fs::read(self.local.join("device/authority.claims"))?,
                    claims_before
                );
                let stopping = std::sync::atomic::AtomicBool::new(/*val*/ false);
                let deployment: crate::RootGenerationInitialDeploymentV1 = deployment;
                let outcome = deployment.wait_and_register_initial(&stopping);
                if reject {
                    anyhow::ensure!(
                        outcome.is_err(),
                        "original bad or sticky fenced target rejected"
                    );
                    send_data(&self.offer, &false)?;
                } else {
                    let registered = outcome.with_context(|| {
                        format!("initial parent {phase:?}: registering original deployment")
                    })?;
                    anyhow::ensure!(!registered.binding().parse::<Digest32>()?.is_zero());
                    send_data(&self.offer, &true)?;
                }
                if phase == Phase::RetiredSession {
                    control(&self.offer, b"RETIRE_READY").with_context(|| {
                        format!("initial parent {phase:?}: awaiting RETIRE_READY")
                    })?;
                    assert_eq!(self.offer.send(b"RETIRE")?, 6);
                }
                control(&self.offer, b"STABLE")
                    .with_context(|| format!("initial parent {phase:?}: awaiting STABLE"))?;
                if !reject {
                    let head = self.head()?;
                    anyhow::ensure!(
                        matches!(head.initial, Some(InitialState::Published(_))),
                        "actual original initial publication"
                    );
                }
                assert_eq!(self.offer.send(b"CHECKED")?, 7);
                control(&self.offer, b"DONE")
                    .with_context(|| format!("initial parent {phase:?}: awaiting DONE"))?;
                assert_eq!(self.offer.send(b"STOP")?, 4);
                control(&self.offer, b"CLOSED")
                    .with_context(|| format!("initial parent {phase:?}: awaiting CLOSED"))?;
                Ok(())
            });
            let served = prepared.serve_with_ready(move || {
                crate::send_root_production_handoff(send.try_clone()?, &sealed, &root_pin, TIMEOUT)
                    .with_context(|| {
                        format!("initial parent {phase:?}: sending original production handoff")
                    })
                    .map_err(io::Error::other)?;
                crate::send_root_generation_initial_handoff(
                    send.try_clone()?,
                    initial,
                    &root_pin,
                    TIMEOUT,
                )
                .with_context(|| {
                    format!("initial parent {phase:?}: sending original initial handoff")
                })
                .map_err(io::Error::other)?;
                send_data(&send, &plan)
                    .with_context(|| format!("initial parent {phase:?}: sending component plan"))
                    .map_err(io::Error::other)?;
                send_target_files(&send, target_writer, witness_writer)
                    .with_context(|| {
                        format!("initial parent {phase:?}: sending original target descriptors")
                    })
                    .map_err(io::Error::other)
            });
            let registered = registration
                .join()
                .map_err(|_| anyhow::anyhow!("initial registration thread panicked"))
                .and_then(|outcome| outcome);
            if let Err(error) = registered {
                return Err(error.context(format!(
                    "initial parent {phase:?}, controlled_ack_loss={}: original Root serve result: {served:?}",
                    self.drop_ack
                )));
            }
            if reject || (phase == Phase::Publish && self.drop_ack) {
                anyhow::ensure!(
                    served.is_err(),
                    "source refusal or controlled ACK loss closes original lane"
                );
            } else {
                served
                    .with_context(|| format!("initial parent {phase:?}: original Root serving"))?;
            }
            // CLOSED alone is insufficient: all original service threads and
            // the original success/refusal result above must also be complete.
            assert_eq!(self.offer.send(b"PHASE_COMPLETE")?, 14);
            Ok(())
        })
    }
}

fn assign_component_artifacts(root: &Path) -> anyhow::Result<()> {
    let mut paths = vec![root.to_owned()];
    let mut index = 0;
    while index < paths.len() {
        anyhow::ensure!(paths.len() <= 256, "bounded owned artifact fixture");
        let path = paths[index].clone();
        let metadata = std::fs::symlink_metadata(&path)?;
        anyhow::ensure!(
            !metadata.file_type().is_symlink(),
            "fixture is not a symlink"
        );
        if metadata.is_dir() {
            for entry in std::fs::read_dir(&path)? {
                paths.push(entry?.path());
            }
        }
        owned_mode(
            &path,
            /*uid*/ 60001,
            /*gid*/ 60001,
            if metadata.is_dir() { 0o700 } else { 0o600 },
        )?;
        index += 1;
    }
    Ok(())
}
