//! Dedicated component setup. CURRENT, Root frontiers and the UID60001 nonce
//! owner are production implementations; no FileCas/test authority is used.

use super::*;
use crate::DeploymentGrantPolicy;
use crate::HostAuthorityBootstrap;
use crate::HostAuthorityConsumerConfig;
use crate::HostAuthorityConsumersConfig;
use crate::HostAuthoritySocketPaths;
use crate::HostAuthorityWriterRegistration;
use crate::HostIssuerRecordProfile;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

type Journal = CellGenerationJournalV2<FileAnchorWitnessStore>;

pub(super) struct Fixture {
    pub(super) child: support::ChildOwner,
    _protected: tempfile::TempDir,
    _runtime: tempfile::TempDir,
    _witnesses: tempfile::TempDir,
    pub(super) config: HostAuthorityServiceConfig,
    config_file: PathBuf,
    registration_file: PathBuf,
    profile_file: PathBuf,
    pub(super) local: PathBuf,
    pub(super) current_path: PathBuf,
    current_directory: Arc<RootAuthorityDirectory>,
    pub(super) current: Arc<NeuronGenerationCurrentOwnerV1>,
    _previous: Journal,
    previous_config: CellGenerationObserverConfigV1,
    target_config: CellGenerationObserverConfigV1,
    previous_journal: PathBuf,
    previous_witness: PathBuf,
    target_journal: PathBuf,
    target_witness: PathBuf,
    target_store: Option<FileAnchorWitnessStore>,
    target: Option<Journal>,
    artifacts: artifacts::Artifacts,
    pub(super) intent: types::UpdateIntent,
    offer: UnixDatagram,
    pin: OwnedFd,
}

impl Fixture {
    pub(super) fn new() -> anyhow::Result<Self> {
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
        let workspace = protected.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let fleet = HeptaFleetRoot::parse(protected.path().join("fleet"))?;
        let registry = FleetRegistry::initialize(fleet.clone())?;
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
            fleet_root: protected.path().join("fleet"),
            workspace,
            resources: ResourceBudget::local_default(),
        };
        drop(registry);
        let identity = registered.identity()?;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let fresh = runtime.block_on(crate::FreshHostCognitiveState::prepare(&registered))?;
        let runtime_directory = tempfile::Builder::new().prefix("hgp-").tempdir_in("/run")?;
        owned_mode(
            runtime_directory.path(),
            /*uid*/ 0,
            /*gid*/ 60001,
            /*mode*/ 0o2710,
        )?;
        let local = runtime_directory.path().join("consumer-local");
        std::fs::create_dir(&local)?;
        owned_mode(
            &local, /*uid*/ 60001, /*gid*/ 60001, /*mode*/ 0o700,
        )?;

        let mut model_files = Vec::new();
        for (name, rows) in [("base", 1_u16), ("encoder", 1), ("heads", 2)] {
            let path = protected.path().join(name);
            let mut file = private_file(&path)?;
            file.write_all(b"HQ24M001")?;
            file.write_all(&rows.to_le_bytes())?;
            file.write_all(&1_u16.to_le_bytes())?;
            for _ in 0..rows {
                file.write_all(&(1_i64 << 24).to_le_bytes())?;
            }
            file.sync_all()?;
            model_files.push(File::open(path)?);
        }
        let mut model_files = model_files.into_iter();
        let model = crate::LoadedCellQ24ModelV1::open_files(crate::CellQ24ModelFilesV1 {
            base: model_files.next().ok_or_else(|| anyhow::anyhow!("base"))?,
            organ_adapter: None,
            cell_adapter: None,
            encoder: model_files
                .next()
                .ok_or_else(|| anyhow::anyhow!("encoder"))?,
            heads: model_files.next().ok_or_else(|| anyhow::anyhow!("heads"))?,
        })?;
        let baseline = CellCompatibilityBundleV1 {
            artifact_id: StableId::new("selected-candidate")?,
            generation: Generation::new(1)?,
            components: model.components().clone(),
            training_lineage: None,
            rollback_predecessor: None,
        };
        // Only the pure manifest template is reused; its FileCas fixture is not.
        let mut old = crate::neuron_generation_current::test_support::config()?;
        old.initial.scope.agent_id = agent.to_string();
        old.initial.scope.cell_id = "publication-component-cell".into();
        old.initial.scope.run_id = "publication-component-A".into();
        old.initial.state.clear();
        old.manifest.profile = crate::CellQ24GenerationWorkerV1::PROFILE.into();
        old.manifest.bundle_digest = baseline.digest()?.into_array();
        old.manifest.encoder = Some(model.components().encoder.into_array());
        old.manifest.head = Some(model.components().heads.into_array());
        old.manifest.input_schema = crate::CellQ24GenerationWorkerV1::input_schema_digest();
        old.manifest.state_schema = model.components().state_schema.into_array();
        old.manifest.output_schema = model.components().output_schema.into_array();
        old.manifest.learning = CellLearningBindingV2::Frozen {
            weights: model.effective_weights_digest().into_array(),
        };
        old.manifest.max_input_bytes = 18;
        old.manifest.max_state_bytes = 1;
        old.manifest.max_delta_bytes = 26;
        old.manifest.max_prefix_bytes = 26;
        old.initial.manifest_digest = old.manifest.digest()?;
        crate::cell_composed_q24::validate_manifest(&baseline, &old.manifest)?;
        let mut next = old.clone();
        next.initial.scope.run_id = "publication-component-C".into();
        next.initial.generation += 1;
        next.initial.writer_epoch += 1;
        next.task_digest = digest("component-successor-task").into_array();
        let previous_config = observer_config(old)?;
        let target_config = observer_config(next)?;
        let current_path = protected.path().join("generation-current");
        std::fs::create_dir(&current_path)?;
        std::fs::set_permissions(&current_path, std::fs::Permissions::from_mode(0o700))?;
        let current_directory = RootAuthorityDirectory::open(&current_path)?;
        let current = Arc::new(NeuronGenerationCurrentOwnerV1::initialize(
            current_directory.clone(),
            CellGenerationOwnerBindingV1::new(&previous_config.generation, RECORDS)?,
        )?);
        let previous_journal = protected.path().join("previous.journal");
        let previous_witness = witnesses.path().join("previous.witness");
        let target_journal = protected.path().join("target.journal");
        let target_witness = witnesses.path().join("target.witness");
        let old_witness = FileAnchorWitnessStore::open(
            private_file(&previous_witness)?,
            previous_config.witness_scope,
            previous_config.witness_generation,
            previous_config.witness_records,
        )?;
        let mut previous = CellGenerationJournalV2::open_guarded(
            private_file(&previous_journal)?,
            old_witness,
            previous_config.generation.clone(),
            RECORDS,
            current.clone(),
        )?;
        previous.drain()?;
        let _ = private_file(&target_journal)?;
        let target_store = FileAnchorWitnessStore::open(
            private_file(&target_witness)?,
            target_config.witness_scope,
            target_config.witness_generation,
            target_config.witness_records,
        )?;
        let artifact_path = runtime_directory.path().join("artifacts");
        let artifacts = artifacts::Artifacts::new(
            &artifact_path,
            &previous_config.generation.manifest,
            now_ms()?,
        )?;
        assign_component_artifacts(&artifact_path)?;
        let selected = artifacts.selection(now_ms()?)?;
        let initial = initial(&identity, baseline, &previous_config.generation)?;
        let decision = record_component_decision(initial.clone())?;
        let old_observation = previous.observe_generation()?;
        let target_binding = CellGenerationOwnerBindingV1::new(&target_config.generation, RECORDS)?;
        let intent = types::UpdateIntent {
            operation_id: learning_retained_task_operation_id_v1(&decision)?.to_string(),
            supersedes: None,
            previous: previous
                .owner_binding()
                .ok_or_else(|| anyhow::anyhow!("guarded previous"))?
                .clone(),
            previous_checkpoint: old_observation.owner_checkpoint().into_array(),
            previous_observation: old_observation.digest()?,
            target: target_binding.clone(),
            genesis_checkpoint: target_binding.genesis_checkpoint().into_array(),
            selection: selected.observation().digest().into_array(),
            completion: NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel,
        };
        let binding = intent.binding()?;
        let state = protected.path().join("authority");
        let bootstrap_file = protected.path().join("bootstrap.json");
        support::write_json(
            &bootstrap_file,
            &HostAuthorityBootstrap {
                schema_version: 1,
                required_bind: required_bind.clone(),
                signer_id: "publication-component-root".into(),
                policies: vec![DeploymentGrantPolicy {
                    subject_id: binding.subject_id.clone(),
                    destination_id: binding.destination_id.clone(),
                    scope_sha256: binding.scope_sha256,
                    lifetime_ms: 30_000,
                }],
                lease_id: "publication-component-root".into(),
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
                local_lease_id: "publication-component-local-writer".into(),
                local_lease_generation: 1,
                authority_lease: AuthorityLease {
                    schema_version: 1,
                    lease_id: "publication-component-root-writer".into(),
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
            lifetime_ms: 10_000,
        };
        let config_file = protected.path().join("service.json");
        support::write_json(&config_file, &config)?;
        let proof = crate::register_host_writer_authorization(&config_file)?;
        let proof: Digest32 = proof.sha256()?.as_str().parse()?;
        let profile = HostAuthorityLearningProfileV1::new_scoped_v2(
            &identity,
            proof.into_array(),
            initial.request.clone(),
            initial.owners.clone(),
            LearningUpdateScopeV2::Cell,
            digest("component-update-rule"),
        )?;
        let profile_file = protected.path().join("learning.json");
        support::write_json(&profile_file, &profile)?;
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
        crate::register_host_learning_checkpoint(
            &config_file,
            &registration_file,
            &profile_file,
            &pin,
        )?;
        Ok(Self {
            _protected: protected,
            _runtime: runtime_directory,
            _witnesses: witnesses,
            config,
            config_file,
            registration_file,
            profile_file,
            local,
            current_path,
            current_directory,
            current,
            _previous: previous,
            previous_config,
            target_config,
            previous_journal,
            previous_witness,
            target_journal,
            target_witness,
            target_store: Some(target_store),
            target: None,
            artifacts,
            intent,
            offer,
            pin,
            child,
        })
    }

    pub(super) fn run_phase(&mut self, phase: Phase) -> anyhow::Result<()> {
        let mut prepared = PreparedHostAuthoritySession::open(
            &self.config_file,
            &self.registration_file,
            self.pin.try_clone()?,
        )?
        .with_registered_learning(&self.profile_file)?;
        let mut sealed = prepared.seal_bootstrap(&self.local)?;
        let mut raw = Vec::new();
        sealed.rewind()?;
        sealed.read_to_end(&mut raw)?;
        let bootstrap: HostAuthorityPublicBootstrapV1 = serde_json::from_slice(&raw)?;
        sealed.rewind()?;
        let learning = prepared.seal_learning_bootstrap()?;
        // Publish starts with the genuinely vacant original checkpoint. This
        // must not require a late decision before the learning service serves.
        let (capability, publication) = prepared.enable_generation_publication()?;
        assert!(prepared.enable_generation_publication().is_err());
        let inputs = RootGenerationPublicationEnrollmentV1 {
            mode: match phase {
                Phase::Publish => RootGenerationPublicationModeV1::Reserve,
                Phase::Recover | Phase::RetiredSession | Phase::Revoked => {
                    RootGenerationPublicationModeV1::Recover
                }
            },
            current_directory: self.current_directory.clone(),
            previous: RootGenerationJournalInputsV1 {
                journal: File::open(&self.previous_journal)?,
                witness: File::open(&self.previous_witness)?,
                config: self.previous_config.clone(),
            },
            target: RootGenerationJournalInputsV1 {
                journal: File::open(&self.target_journal)?,
                witness: File::open(&self.target_witness)?,
                config: self.target_config.clone(),
            },
            artifacts: self.artifacts.inputs(now_ms()?)?,
            consumer: RootPublicationFinalUseConsumerV1::Device,
            consumer_state_root: self.local.clone(),
            issuer_keys: vec![FinalUseIssuerTrustKey::from(bootstrap.issuer_key)],
        };
        let deployment_directory = self._protected.path().join(format!("deployment-{phase:?}"));
        let (deployment, late_material) = capability.component_original_deployment(
            &deployment_directory,
            &[
                self.current_path.clone(),
                self.previous_journal.clone(),
                self.previous_witness.clone(),
                self.target_journal.clone(),
                self.target_witness.clone(),
            ],
            &self.artifacts.selector_trust,
            inputs,
        )?;
        if !matches!(phase, Phase::Publish) {
            let before = (
                std::fs::read(&self.profile_file)?,
                support::protected_files(&self.current_path)?,
                std::fs::read(self.local.join("device/authority.claims"))?,
            );
            deployment.component_reject_previous_trigger(
                &self
                    ._protected
                    .path()
                    .join("deployment-Publish/trigger.json"),
            )?;
            assert_eq!(
                (
                    std::fs::read(&self.profile_file)?,
                    support::protected_files(&self.current_path)?,
                    std::fs::read(self.local.join("device/authority.claims"))?,
                ),
                before
            );
        }
        let root_pin = support::pidfd(std::process::id())?;
        let send = self.offer.try_clone()?;
        let snapshot = std::thread::scope(|scope| {
            let registration = scope.spawn(|| -> anyhow::Result<_> {
                control(&self.offer, b"LEARNING_AND_ORIGINAL_INPUTS_READY")?;
                deployment.component_trigger_original(&late_material)?;
                let stopping = std::sync::atomic::AtomicBool::new(/*val*/ false);
                let registered = deployment.wait_and_register(&stopping)?;
                anyhow::ensure!(
                    !registered.binding().parse::<Digest32>()?.is_zero(),
                    "actual Root acknowledgement"
                );
                send_data(&self.offer, &self.intent)?;
                if matches!(phase, Phase::Publish) {
                    control(&self.offer, b"PREPARED")?;
                    let file = OpenOptions::new()
                        .read(true)
                        .write(true)
                        .open(&self.target_journal)?;
                    self.target = Some(CellGenerationJournalV2::open_guarded(
                        file,
                        self.target_store
                            .take()
                            .ok_or_else(|| anyhow::anyhow!("original target witness"))?,
                        self.target_config.generation.clone(),
                        RECORDS,
                        self.current.clone(),
                    )?);
                    assert_eq!(self.offer.send(b"GENESIS")?, 7);
                }
                control(&self.offer, b"STABLE")?;
                let snapshot = (
                    support::protected_files(&self.current_path)?,
                    std::fs::read(self.local.join("device/authority.claims"))?,
                );
                assert_eq!(self.offer.send(b"CHECKED")?, 7);
                control(&self.offer, b"DONE")?;
                Ok(snapshot)
            });
            let served = prepared.serve_with_ready(|| {
                crate::send_root_production_handoff(send.try_clone()?, &sealed, &root_pin, TIMEOUT)
                    .map_err(io::Error::other)?;
                crate::send_root_learning_handoff(send.try_clone()?, &learning, &root_pin, TIMEOUT)
                    .map_err(io::Error::other)?;
                crate::send_root_generation_publication_handoff(
                    send,
                    publication,
                    &root_pin,
                    TIMEOUT,
                )
                .map_err(io::Error::other)
            });
            let result = registration
                .join()
                .map_err(|_| anyhow::anyhow!("original Root registration worker panicked"))??;
            // A deliberate refused frame can close its worker before or during
            // the original fixed-lane shutdown. The child asserts that refusal.
            println!("ROOT_PUBLICATION_COMPONENT phase={phase:?} service={served:?}");
            Ok::<_, anyhow::Error>(result)
        })?;
        assert_eq!(
            (
                support::protected_files(&self.current_path)?,
                std::fs::read(self.local.join("device/authority.claims"))?
            ),
            snapshot
        );
        Ok(())
    }
}

fn initial(
    identity: &crate::AgentdIdentity,
    baseline: CellCompatibilityBundleV1,
    config: &CellGenerationConfigV2,
) -> anyhow::Result<LearningIterationSnapshotV1> {
    let request = LearningIterationRequestV1 {
        operation_id: StableId::new("publication-component-learning")?,
        principal_id: StableId::new(
            Digest32::from_array(config.initial.scope.principal_digest).to_string(),
        )?,
        agent_id: StableId::new(identity.agent_id.as_str())?,
        cell_id: StableId::new(&config.initial.scope.cell_id)?,
        source_run_id: StableId::new(&config.initial.scope.run_id)?,
        completed_task_receipt: digest("component-completed-task"),
        selected_artifact_digest: baseline.components.base,
        evaluation_profile: digest("component-evaluation"),
        selected_bundle: baseline,
        envelope: IterationEnvelopeV1 {
            envelope_id: StableId::new("publication-component-envelope")?,
            base_commit: digest("component-commit"),
            base_tree: digest("component-tree"),
            objective_digest: digest("component-objective"),
            grammar_digest: digest("component-grammar"),
            maximum_files: 1,
            maximum_diff_bytes: 128,
            maximum_candidates: 1,
            maximum_parallel_sandboxes: 1,
            expiry_unix_seconds: now_ms()? / 1000 + 300,
        },
        budget: LearningIterationBudgetV1 {
            maximum_dataset_rows: 1,
            maximum_dataset_bytes: 128,
            maximum_training_steps: 1,
            maximum_training_milliseconds: 1,
            maximum_artifact_bytes: 128,
        },
    };
    Ok(LearningIterationCoordinatorV1::new(
        request,
        LearningIterationOwnersV1 {
            evidence_trust_digest: digest("component-role-trust"),
            experience: StableId::new("component-experience")?,
            dataset: StableId::new("component-dataset")?,
            trainer: StableId::new("component-trainer")?,
            evaluator: StableId::new("component-evaluator")?,
            proposal: StableId::new("component-proposal")?,
            selector: StableId::new("component-selector")?,
            next_use_observer: StableId::new("component-next-use")?,
        },
    )?
    .snapshot()
    .clone())
}

fn observer_config(
    generation: CellGenerationConfigV2,
) -> anyhow::Result<CellGenerationObserverConfigV1> {
    let binding = CellGenerationOwnerBindingV1::new(&generation, RECORDS)?;
    Ok(CellGenerationObserverConfigV1 {
        witness_scope: JournalScope {
            scope_digest: Digest32::from_array(binding.digest()?),
            objective_digest: Digest32::from_array(generation.task_digest),
        },
        witness_generation: Generation::new(generation.initial.generation)?,
        generation,
        journal_records: RECORDS,
        witness_records: 256,
    })
}

fn private_file(path: &Path) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
}

fn owned_mode(path: &Path, uid: u32, gid: u32, mode: u32) -> anyhow::Result<()> {
    let name = std::ffi::CString::new(path.as_os_str().as_encoded_bytes())?;
    // SAFETY: only this test's newly created path, never a deployment directory.
    anyhow::ensure!(
        unsafe { libc::chown(name.as_ptr(), uid, gid) } == 0,
        "{}",
        io::Error::last_os_error()
    );
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))?;
    Ok(())
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
