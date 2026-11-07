//! Real file owners with explicit test-only issuer keys and custody.
//! No fixture here asserts root deployment, model quality or power-loss safety.

use std::collections::BTreeSet;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::NeuronGenerationCurrentOwnerV1;
use super::store::CurrentStore;
use super::types::CurrentHead;
use super::types::scope_digest;
use crate::neuron_generation_update::AgentdGenerationUpdateTargetV1;
use crate::neuron_generation_update_live::AgentdGenerationUpdateAuthoritiesV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

#[path = "neuron_generation_update_test_artifacts.rs"]
mod artifacts;
#[path = "neuron_generation_drained_tests.rs"]
mod drained_tests;
#[path = "neuron_generation_update_test_store.rs"]
mod files;
#[path = "neuron_generation_update_initial_test_support.rs"]
mod initial_fixture;

use artifacts::ArtifactFiles;
use files::FileCas;
use files::NOW;
pub(crate) use files::TestClock;

pub(crate) const RECORDS: u64 = 128;
pub(crate) type Journal = CellGenerationJournalV2<FileAnchorWitnessStore>;

pub(crate) struct Fixture {
    directory: tempfile::TempDir,
    pub(crate) old_config: CellGenerationConfigV2,
    pub(crate) target_config: CellGenerationConfigV2,
    pub(crate) current: Arc<NeuronGenerationCurrentOwnerV1>,
    pub(crate) authority: Arc<FinalUseAuthority>,
    pub(crate) artifacts: Arc<Mutex<LearningArtifactOwnerService>>,
    pub(crate) clock: Arc<TestClock>,
    current_file: Arc<FileCas<CurrentHead>>,
    final_use_file: Arc<FileCas<FinalUseFrontier>>,
    artifact_files: ArtifactFiles,
    issuer: SigningKey,
}

impl Fixture {
    pub(crate) fn new(old_config: CellGenerationConfigV2) -> anyhow::Result<Self> {
        let mut target_config = old_config.clone();
        target_config.initial.scope.run_id.push_str("-next-task");
        target_config.initial.generation += 1;
        target_config.initial.writer_epoch += 1;
        target_config.task_digest =
            Digest32::of_parts(&[b"test-next-task", &old_config.task_digest]).into_array();
        target_config.manifest.bundle_digest =
            Digest32::of_parts(&[b"test-next-bundle", &old_config.manifest.bundle_digest])
                .into_array();
        target_config.initial.manifest_digest = target_config.manifest.digest()?;
        Self::new_with_target(old_config, target_config)
    }

    pub(crate) fn new_with_target(
        old_config: CellGenerationConfigV2,
        target_config: CellGenerationConfigV2,
    ) -> anyhow::Result<Self> {
        Self::create(old_config, target_config, None)
    }

    fn create(
        old_config: CellGenerationConfigV2,
        target_config: CellGenerationConfigV2,
        initial_operation: Option<&str>,
    ) -> anyhow::Result<Self> {
        let directory = tempfile::tempdir()?;
        fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700))?;
        let clock = Arc::new(TestClock(AtomicU64::new(NOW)));
        let issuer = SigningKey::from_bytes(&[63; 32]);
        let head = FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let final_use_file = Arc::new(FileCas::create(
            &directory.path().join("final-use-frontier.json"),
            "test-control-authority".into(),
            &FinalUseFrontier::for_initial_head(&head)?,
        )?);
        let authority_path = directory.path().join("final-use");
        fs::create_dir(&authority_path)?;
        fs::set_permissions(&authority_path, fs::Permissions::from_mode(0o700))?;
        let authority = Arc::new(FinalUseAuthority::open_state_dir_with_trust(
            &authority_path,
            "test-control-authority".into(),
            issuer.verifying_key().to_bytes(),
            head,
            clock.clone(),
            final_use_file.clone(),
        )?);
        let artifact_files =
            ArtifactFiles::new(&directory.path().join("artifacts"), &target_config.manifest)?;
        let artifacts = artifact_files.owner.clone();
        let head = initial_fixture::current_head(
            &old_config,
            &target_config,
            &artifact_files,
            initial_operation,
        )?;
        let current_file = Arc::new(FileCas::create(
            &directory.path().join("current.json"),
            current_id(&old_config)?,
            &head,
        )?);
        let current = Arc::new(NeuronGenerationCurrentOwnerV1 {
            store: CurrentStore::from_test_store(&old_config.initial.scope, current_file.clone())?,
        });
        if initial_operation.is_none() {
            for name in ["old-journal", "old-witness"] {
                let file = OpenOptions::new()
                    .create_new(true)
                    .read(true)
                    .write(true)
                    .open(directory.path().join(name))?;
                file.sync_all()?;
            }
        }
        File::open(directory.path())?.sync_all()?;
        Ok(Self {
            directory,
            old_config,
            target_config,
            current,
            authority,
            artifacts,
            clock,
            current_file,
            final_use_file,
            artifact_files,
            issuer,
        })
    }

    pub(crate) fn old_journal(&self) -> anyhow::Result<Journal> {
        Ok(CellGenerationJournalV2::open_guarded(
            self.file("old-journal")?,
            self.witness("old-witness", &self.old_config)?,
            self.old_config.clone(),
            RECORDS,
            self.current.clone(),
        )?)
    }

    pub(crate) fn stopped_old(&self) -> anyhow::Result<Journal> {
        let mut journal = self.old_journal()?;
        let request = request(&journal, &self.old_config, "old-stop")?;
        journal.admit(request.clone(), /*now_micros*/ 10)?;
        journal.commit(
            CellGenerationProposalV2 {
                request_digest: request.digest()?,
                bundle_digest: self.old_config.manifest.bundle_digest,
                runtime_digest: self.old_config.manifest.runtime_digest,
                device_digest: self.old_config.manifest.device_digest,
                successor_state: request.predecessor.state,
                output_delta: vec![42],
                disposition: CellGenerationDispositionV2::Stopped,
                cost: cost(&self.old_config, "stop", CellCostStageV2::Inference)?,
            },
            /*now_micros*/ 11,
        )?;
        let chunk = journal
            .pending_output()?
            .cloned()
            .ok_or_else(|| anyhow::anyhow!("missing actual stop output"))?;
        let mut delivered = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(self.directory.path().join("delivered-output"))?;
        delivered.write_all(&chunk.bytes)?;
        delivered.sync_all()?;
        journal.acknowledge(
            chunk,
            Digest32::of_bytes(b"test-delivery-ack").into_array(),
            cost(&self.old_config, "ack", CellCostStageV2::Communication)?,
        )?;
        journal.drain()?;
        anyhow::ensure!(
            journal.is_drained()? && journal.observe_generation()?.is_terminal(),
            "fixture must have real STOP/ACK/drain records"
        );
        Ok(journal)
    }

    pub(crate) fn target_create(
        &self,
    ) -> anyhow::Result<AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>> {
        self.named_target_create(
            "target-journal",
            "target-witness",
            self.target_config.clone(),
        )
    }

    pub(crate) fn named_target_create(
        &self,
        journal: &str,
        witness: &str,
        config: CellGenerationConfigV2,
    ) -> anyhow::Result<AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>> {
        for name in [journal, witness] {
            OpenOptions::new()
                .create_new(true)
                .read(true)
                .write(true)
                .open(self.directory.path().join(name))?
                .sync_all()?;
        }
        File::open(self.directory.path())?.sync_all()?;
        Ok(AgentdGenerationUpdateTargetV1 {
            file: self.file(journal)?,
            witness: self.witness(witness, &config)?,
            config,
            max_records: RECORDS,
        })
    }

    pub(crate) fn target_reopen(
        &self,
    ) -> anyhow::Result<AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>> {
        Ok(AgentdGenerationUpdateTargetV1 {
            file: self.file("target-journal")?,
            witness: self.witness("target-witness", &self.target_config)?,
            config: self.target_config.clone(),
            max_records: RECORDS,
        })
    }

    pub(crate) fn selection(&self) -> anyhow::Result<AgentdSelectedGenerationV1> {
        self.artifact_files.selection(self.clock.now_unix_ms()?)
    }

    pub(crate) fn authorities(&self) -> anyhow::Result<AgentdGenerationUpdateAuthoritiesV1> {
        Ok(AgentdGenerationUpdateAuthoritiesV1::new(
            self.artifacts.clone(),
            self.authority.clone(),
            self.clock.clone(),
        )?)
    }

    pub(crate) fn sign(&self, binding: &FinalUseBinding) -> anyhow::Result<SignedFinalUseGrant> {
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "test-control-authority".into(),
            authority_epoch: 1,
            grant_id: format!(
                "test-replace-{}",
                Digest32::from_array(binding.request_sha256)
            ),
            nonce: Digest32::of_parts(&[b"test-independent-nonce", &serde_json::to_vec(binding)?])
                .into_array(),
            binding: binding.clone(),
            not_before_unix_ms: 1,
            expires_at_unix_ms: 9_000,
        };
        Ok(SignedFinalUseGrant {
            signature: self
                .issuer
                .sign(&grant.signing_bytes()?)
                .to_bytes()
                .to_vec(),
            grant,
        })
    }

    pub(crate) fn reopen_current(&self) -> anyhow::Result<Arc<NeuronGenerationCurrentOwnerV1>> {
        let (current, _lose_publication_ack) = self.reopen_current_with_ack_loss_hook()?;
        Ok(current)
    }

    pub(crate) fn reopen_current_with_ack_loss_hook(
        &self,
    ) -> anyhow::Result<(Arc<NeuronGenerationCurrentOwnerV1>, impl FnOnce())> {
        let store = Arc::new(FileCas::<CurrentHead>::reopen(
            &self.directory.path().join("current.json"),
            current_id(&self.old_config)?,
        )?);
        let current = NeuronGenerationCurrentOwnerV1 {
            store: CurrentStore::from_test_store(&self.old_config.initial.scope, store.clone())?,
        };
        current.store.load()?;
        // Arm this reopened owner only after preparation has committed its own CAS.
        Ok((Arc::new(current), move || store.lose_next_ack()))
    }

    pub(crate) fn lose_publication_ack(&self) {
        self.current_file.lose_next_ack();
    }
    pub(crate) fn reject_publication_write(&self) {
        self.current_file.reject_next_write();
    }

    pub(crate) fn expire_selection_after_claim(&self) -> anyhow::Result<()> {
        let clock = self.clock.clone();
        self.final_use_file.after_next_commit(Box::new(move || {
            clock.0.store(2_001, Ordering::SeqCst);
            Ok(())
        }))
    }

    pub(crate) fn advance_artifact_current(&self) -> anyhow::Result<()> {
        self.artifact_files
            .advance_current(&self.target_config.manifest)
    }

    pub(crate) fn publish_next_selection(
        &self,
        manifest: &CellBackendManifestV2,
        name: &str,
    ) -> anyhow::Result<AgentdSelectedGenerationV1> {
        self.artifact_files
            .publish_next_selection(manifest, name, self.clock.now_unix_ms()?)
    }

    pub(crate) fn withdraw(&self) -> anyhow::Result<()> {
        self.artifact_files.withdraw()
    }

    pub(crate) fn bytes(&self, name: &str) -> anyhow::Result<Vec<u8>> {
        Ok(fs::read(self.directory.path().join(name))?)
    }

    pub(crate) fn file(&self, name: &str) -> anyhow::Result<File> {
        Ok(OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.directory.path().join(name))?)
    }

    pub(crate) fn witness(
        &self,
        name: &str,
        config: &CellGenerationConfigV2,
    ) -> anyhow::Result<FileAnchorWitnessStore> {
        let binding = CellGenerationOwnerBindingV1::new(config, RECORDS)?;
        Ok(FileAnchorWitnessStore::open(
            self.file(name)?,
            JournalScope {
                scope_digest: Digest32::from_array(binding.digest()?),
                objective_digest: Digest32::from_array(config.task_digest),
            },
            Generation::new(config.initial.generation)?,
            /*max_records*/ 256,
        )?)
    }
}

pub(crate) fn request(
    journal: &Journal,
    config: &CellGenerationConfigV2,
    operation: &str,
) -> anyhow::Result<CellGenerationRequestV2> {
    Ok(CellGenerationRequestV2 {
        operation_id: operation.into(),
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        predecessor: journal.snapshot()?.clone(),
        input: vec![7],
        admitted_at_micros: 10,
        deadline_micros: 100,
    })
}

fn current_id(config: &CellGenerationConfigV2) -> anyhow::Result<String> {
    let digest = scope_digest(&config.initial.scope)?;
    let hex: String = digest
        .as_array()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    Ok(format!("cell-generation/{hex}"))
}

fn cost(
    config: &CellGenerationConfigV2,
    label: &str,
    stage: CellCostStageV2,
) -> anyhow::Result<CellTaskCostV2> {
    let identity = CellTaskCostIdentityV2 {
        task_digest: config.task_digest,
        source_digest: config.manifest.source_digest,
    };
    let mut cost = CellTaskCostV2::new(identity)?;
    // Explicit synthetic mechanism-test measurement; never model evidence.
    cost.record(CellCostEntryV2 {
        event_id: Digest32::of_bytes(label.as_bytes()).into_array(),
        identity,
        stage,
        outcome: CellCostOutcomeV2::Succeeded,
        accounting: CellCostAccountingV2::Exclusive,
        metrics: CellCostMetricsV2 {
            wall_micros: Some(1),
            ..CellCostMetricsV2::default()
        },
    })?;
    Ok(cost)
}

pub(super) fn config() -> anyhow::Result<CellGenerationConfigV2> {
    let manifest = CellBackendManifestV2 {
        profile: "generation-update-file-test".into(),
        source_digest: [1; 32],
        bundle_digest: [2; 32],
        encoder: Some([3; 32]),
        head: None,
        memory: None,
        world_model: None,
        decoder: None,
        runtime_digest: [4; 32],
        device_digest: [5; 32],
        input_schema: [6; 32],
        state_schema: [7; 32],
        output_schema: [8; 32],
        learning: CellLearningBindingV2::Frozen { weights: [9; 32] },
        evolution: CellEvolutionBindingV2 {
            structure: [10; 32],
            lineage: [11; 32],
            source_dependencies: [12; 32],
            adoption_receipt: [13; 32],
        },
        max_input_bytes: 256,
        max_state_bytes: 256,
        max_delta_bytes: 256,
        max_prefix_bytes: 1_024,
        max_step_cost_entries: 4,
        max_ack_cost_entries: 4,
    };
    let initial = CellRuntimeSnapshotV2 {
        scope: CellGenerationScopeV2 {
            principal_digest: [14; 32],
            agent_id: "agent".into(),
            cell_id: "cell".into(),
            run_id: "old-run".into(),
        },
        manifest_digest: manifest.digest()?,
        generation: 1,
        writer_epoch: 1,
        revision: 0,
        state: vec![1],
        prefix: Vec::new(),
        stopped: false,
    };
    Ok(CellGenerationConfigV2 {
        manifest,
        initial,
        source_frontier: [15; 32],
        task_digest: [16; 32],
    })
}
