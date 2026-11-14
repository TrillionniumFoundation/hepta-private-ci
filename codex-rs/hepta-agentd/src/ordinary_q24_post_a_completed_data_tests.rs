//! Physical DATA after both original production processes have really exited.
//! This observer cannot resume a writer, renew an old business window, issue a
//! grant, or stand in for the later new-Root CaptureRetired/ReadFinalized path.

use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::CellStatePartitionV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalSnapshotReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::read_dataset_withdrawal_snapshot;
use codex_hepta_neuron::CellGenerationJournalObservedV1;
use codex_hepta_neuron::CellGenerationJournalObserverV1;
use codex_hepta_neuron::CellGenerationObserverConfigV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_neuron::CellJournalPartitionV1;
use codex_hepta_neuron::CellOriginalJournalFilesV1;
use codex_hepta_neuron::CellOriginalJournalObservationV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::SparseCheckpoint;
use codex_hepta_neuron::canonical_cell_step_request_digest_v1;
use codex_hepta_neuron::observe_original_guarded_cell_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;

use super::post_a_file::OriginalFileData;
use super::post_a_plan::OriginalPostAPlan;
use super::post_a_selection::OriginalSelectedArtifactData;
use crate::AgentdIdentity;
use crate::CircuitTaskSourcePublicationV1;
use crate::HistoricalCircuitTaskSourceV1;
use crate::OriginalSingleQ24SourceConfigurationV1;
use crate::neuron_generation_current::types::CurrentHead;
use crate::neuron_generation_current::types::NeuronGenerationPredecessorCompletionV1;
use crate::neuron_generation_current::types::scope_digest;
use crate::ordinary_q24_cold_snapshot_tests::OriginalBusinessSnapshot;
use crate::ordinary_q24_process_child_tests::ExitedOriginalProcess;

#[derive(Debug, Eq, PartialEq)]
pub(super) struct OriginalCompletedCData {
    pub(super) source: CircuitTaskSourcePublicationV1,
    pub(super) cell: CellOriginalJournalObservationV1,
    pub(super) generation: CellGenerationJournalObservedV1,
    pub(super) current: CurrentHead,
    pub(super) terminal: LearningIterationSnapshotV1,
}

impl OriginalCompletedCData {
    pub(super) fn observe_after_original_exit(
        plan: &OriginalPostAPlan,
        selected: &OriginalSelectedArtifactData,
        target: &CellGenerationObserverConfigV1,
        terminal: &LearningIterationSnapshotV1,
        daemon: &ExitedOriginalProcess,
        root: &ExitedOriginalProcess,
    ) -> anyhow::Result<Self> {
        daemon.require_dead()?;
        root.require_dead()?;
        plan.resources.original.daemon.require_dead()?;
        plan.resources.original.root.require_dead()?;
        let c = &plan.resources.c;
        let binding =
            CellGenerationOwnerBindingV1::new(&target.generation, target.journal_records)?;
        let owner = format!("cell-generation/{}", scope_digest(binding.scope())?);
        let record = format!("frontier-v1-{}.json", Digest32::of_bytes(owner.as_bytes()));
        let current_paths = [
            plan.root.publication_inputs.current_directory.join(&record),
            plan.root
                .publication_inputs
                .current_directory
                .join(format!("{record}.lock")),
        ];
        // The existing store takes its original O_RDWR lock. Require that
        // lock to exist before open; neither missing lock nor primary data
        // may be created, replaced or repaired by this observation.
        let current_unchanged = OriginalBusinessSnapshot::capture(&current_paths)?;
        let mut paths = c.business_files();
        paths.extend([
            plan.resources.original.plan.files.source.clone(),
            plan.resources.original.plan.files.source_witness.clone(),
            plan.root.publication_inputs.previous_journal.clone(),
            plan.root.publication_inputs.previous_witness.clone(),
            plan.resources.owners.independent_selection.path.clone(),
            plan.root.publication_inputs.withdrawal_file.clone(),
        ]);
        let unchanged = OriginalBusinessSnapshot::capture(&paths)?;
        let result = (|| {
            let registration: crate::HostAuthorityRegistration = serde_json::from_slice(
                &super::observer::read_private(&plan.resources.successor.registration, 16 * 1024)?,
            )?;
            anyhow::ensure!(
                registration.peer_pid == daemon.lifetime().pid
                    && registration.boot_id == daemon.lifetime().boot_id
                    && registration.process_start_ticks == daemon.lifetime().start_ticks
                    && daemon.lifetime() != root.lifetime()
                    && daemon.lifetime() != plan.resources.original.daemon.lifetime()
                    && root.lifetime() != plan.resources.original.root.lifetime(),
                "original exited processes differ from the actual successor registration"
            );
            let coordinator = LearningIterationCoordinatorV1::from_snapshot(terminal.clone())?;
            anyhow::ensure!(
                coordinator.next_stage().is_none()
                    && coordinator.disposition() == LearningIterationDispositionV1::UsedByNextTask,
                "actual terminal Selection and NextUse receipts are required"
            );
            let selected_bundle = coordinator
                .next_task_bundle()
                .ok_or_else(|| anyhow::anyhow!("terminal selected bundle absent"))?
                .digest()?;
            let bytes = c.source_configuration.read_original(/*maximum*/ 65_536)?;
            let original = OriginalSingleQ24SourceConfigurationV1::from_original_deployment_bytes(
                &bytes,
                &plan.resources.successor.identity,
            )?;
            let cell_files: CellFilesData = serde_json::from_value(
                serde_json::from_slice::<serde_json::Value>(&bytes)?["cell_files"].clone(),
            )?;
            anyhow::ensure!(
                original.source_journal == c.source_journal.path
                    && original.source_witness == c.source_witness.path
                    && cell_files.journal == c.cell_journal.path
                    && cell_files.witness == c.cell_witness.path
                    && original.source.scope.run_id.as_str() == super::inputs::C_RUN
                    && original.definition.bundle_digest == selected_bundle
                    && selected.manifest.bundle_digest == selected_bundle.into_array()
                    && target.generation.manifest == selected.manifest
                    && crate::circuit_feature_task_digest_v1(
                        &original.definition,
                        &original.source
                    )?
                    .into_array()
                        == binding.task_digest(),
                "original C configuration, actual selected manifest or full target differs"
            );
            let declared = c.root_successor_data();
            anyhow::ensure!(
                serde_json::to_value(cell_files.witness_scope)? == declared["cell_witness_scope"]
                    && serde_json::to_value(cell_files.witness_objective)?
                        == declared["cell_witness_objective"]
                    && cell_files.witness_generation == declared["cell_witness_generation"]
                    && cell_files.witness_records == declared["cell_witness_records"]
                    && cell_files.maximum_records == declared["maximum_cell_records"],
                "original Cell witness context differs from the Root-fixed C deployment"
            );
            let mut source = open_source(
                &original,
                &plan.resources.successor.identity,
                open_original(&c.source_journal)?,
                open_original(&c.source_witness)?,
            )?;
            let before = source.observe_run_publication(&original.source.scope.run_id)?;
            let publication = before.publication();
            anyhow::ensure!(
                publication.input()
                    == &original
                        .source
                        .input(publication.input().operation_id.clone())
                    && publication.bundle_digest() == selected_bundle,
                "actual completed C Source differs from its fixed input"
            );
            let read_cell = || {
                observe_original_guarded_cell_v1(
                    CellOriginalJournalFilesV1 {
                        journal: open_original(&c.cell_journal)?,
                        witness: open_original(&c.cell_witness)?,
                        witness_scope: JournalScope {
                            scope_digest: Digest32::from_array(cell_files.witness_scope),
                            objective_digest: Digest32::from_array(cell_files.witness_objective),
                        },
                        witness_generation: Generation::new(cell_files.witness_generation)?,
                        witness_records: cell_files.witness_records,
                    },
                    CellJournalPartitionV1 {
                        scope: original.source.scope.clone(),
                        definition: original.definition.clone(),
                        source_frontier: original.source.source_frontier,
                        writer_epoch: binding.writer_epoch(),
                    },
                    cell_files.maximum_records,
                    &binding,
                    &publication.input().operation_id,
                    canonical_cell_step_request_digest_v1(
                        &original.definition,
                        publication.input(),
                    )?,
                )
                .map_err(anyhow::Error::from)
            };
            let cell = read_cell()?;
            publication.require_decision(&cell.decision)?;
            anyhow::ensure!(
                cell.snapshot.revision == 1
                    && cell.snapshot.scope == original.source.scope
                    && cell.snapshot.writer_epoch == binding.writer_epoch()
                    && cell
                        .snapshot
                        .checkpoint
                        .as_ref()
                        .map(SparseCheckpoint::digest)
                        == Some(cell.decision.checkpoint_after)
                    && cell.decision.checkpoint_after == publication.checkpoint_digest()
                    && cell.decision.bundle_digest == selected_bundle
                    && cell.decision.authority == AuthorityPosture::DENY_ALL,
                "C requires one actual committed Cell revision and its complete decision"
            );
            let generation_reader = CellGenerationJournalObserverV1::from_original_files(
                open_original(&c.generation_journal)?,
                open_original(&c.generation_witness)?,
                target.clone(),
            )?;
            let generation = generation_reader.observe()?;
            let observed = generation.observation();
            anyhow::ensure!(
                generation.owner_binding() == &binding
                    && generation.is_drained()
                    && observed.manifest_digest() == selected.manifest.digest()?
                    && observed.snapshot().revision == 0
                    && observed.snapshot().prefix.is_empty()
                    && !observed.snapshot().stopped
                    && observed.pending_request_digest().is_none()
                    && observed.pending_output().is_none(),
                "Feature C must drain its original Generation owner without Generation inference"
            );
            // Existing protected DATA only: no Current owner, publisher or
            // live writer lease is reconstructed after the original exit.
            let store = HostAuthorityFrontierStore::<CurrentHead>::open(
                RootAuthorityDirectory::open(&plan.root.publication_inputs.current_directory)?,
                owner.clone(),
            )?;
            let current = store.load(&owner)?;
            anyhow::ensure!(
                current.schema_version == 1
                    && current.current == binding
                    && current.prepared.is_none()
                    && current.initial.is_none(),
                "actual Root CURRENT has no completed original successor publication"
            );
            let published = current
                .published
                .as_ref()
                .ok_or_else(|| anyhow::anyhow!("actual Root published record absent"))?;
            let intent = &published.intent;
            anyhow::ensure!(
                intent.target == binding
                    && intent.previous == plan.resources.original.plan.deployment.target
                    && intent.genesis_checkpoint == binding.genesis_checkpoint().into_array()
                    && published.signed.grant.binding == intent.binding()?
                    && published.signed_grant_digest
                        == crate::neuron_generation_current::signed_grant_digest(
                            &published.signed
                        )?
                        .into_array(),
                "actual CURRENT intent, FinalUse bytes or original predecessor differs"
            );
            let previous_inputs = &plan.root.publication_inputs;
            let previous_reader = CellGenerationJournalObserverV1::from_original_files(
                open_original(&OriginalFileData::capture(
                    &previous_inputs.previous_journal,
                )?)?,
                open_original(&OriginalFileData::capture(
                    &previous_inputs.previous_witness,
                )?)?,
                previous_inputs.previous.original_observer_config()?,
            )?;
            let previous = previous_reader.observe()?;
            anyhow::ensure!(
                previous.is_drained()
                    && previous.owner_binding() == &intent.previous
                    && previous.observation().owner_checkpoint().into_array()
                        == intent.previous_checkpoint
                    && previous.observation().digest()? == intent.previous_observation,
                "original physical A Generation cut differs from the published CURRENT predecessor"
            );
            let selection_digest = original_selection_digest(plan, selected)?;
            anyhow::ensure!(
                intent.selection == selection_digest.into_array(),
                "actual CURRENT selection differs from the original independent signed input"
            );
            let publication_digest = Digest32::of_parts(&[
                b"hepta.agentd.generation-publication.v1\0",
                &serde_json::to_vec(published)?,
            ]);
            let a = read_original_a(plan)?;
            anyhow::ensure!(
                a.input().scope.run_id == terminal.request.source_run_id
                    && a.input().scope.run_id != publication.input().scope.run_id
                    && a.input().observation != publication.input().observation,
                "C must use its distinct original run and externally fixed observation"
            );
            let scope = &cell.decision.scope;
            let partition = CellStatePartitionV1 {
                principal_id: StableId::new(scope.principal_digest.to_string())?,
                agent_id: scope.agent_id.clone(),
                cell_id: scope.cell_id.clone(),
                run_id: scope.run_id.clone(),
            };
            let committed = Digest32::of_parts(&[
                b"hepta.agentd.learning-circuit-feature-use.v1\0",
                publication.publication_digest().as_array(),
                &crate::circuit_cell_output::encode_receipt(&cell.decision)?,
            ]);
            let retained =
                coordinator.next_task_bundle() == Some(&terminal.request.selected_bundle);
            let expected_use = if retained {
                anyhow::ensure!(
                    intent.completion
                        == NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel,
                    "retained-model C has the wrong original task boundary"
                );
                LearningIterationObservationV1::RetainedModelNextUse {
                    retained_bundle: selected_bundle,
                    state_partition: partition,
                    checkpoint_digest: cell.decision.checkpoint_after,
                    selection_digest,
                    committed_step_receipt: committed,
                    task_owner_publication: publication_digest,
                }
            } else {
                anyhow::ensure!(
                    intent.completion == NeuronGenerationPredecessorCompletionV1::OwnerDrained,
                    "adopted C has the wrong original task boundary"
                );
                let reset = Digest32::of_parts(&[
                    b"hepta.agentd.learning-published-feature-reset.v1\0",
                    publication_digest.as_array(),
                    &intent.previous.digest()?,
                    &binding.digest()?,
                    a.publication_digest().as_array(),
                    a.checkpoint_digest().as_array(),
                    cell.decision.checkpoint_before.as_array(),
                    original.definition.semantic_digest()?.as_array(),
                    partition.digest().as_array(),
                ]);
                LearningIterationObservationV1::NextUse {
                    candidate_bundle: selected_bundle,
                    state_partition: partition,
                    checkpoint_digest: cell.decision.checkpoint_after,
                    selection_digest,
                    committed_step_receipt: committed,
                    state_cutover_receipt: reset,
                }
            };
            let last = terminal
                .receipts
                .len()
                .checked_sub(1)
                .ok_or_else(|| anyhow::anyhow!("terminal NextUse receipt missing"))?;
            let selection_index = last
                .checked_sub(1)
                .ok_or_else(|| anyhow::anyhow!("terminal Selection receipt missing"))?;
            anyhow::ensure!(
                terminal.receipts[selection_index].observation
                    == LearningIterationObservationV1::Selection {
                        candidate_bundle: selected_bundle,
                        selection_digest,
                    }
                    && terminal.receipts[last].observation == expected_use,
                "actual terminal Selection/NextUse differs from original Source, Cell and CURRENT data"
            );
            let after = source.observe_run_publication(&original.source.scope.run_id)?;
            anyhow::ensure!(
                after.publication() == publication
                    && after.journal_anchor() == before.journal_anchor()
                    && after.binding_digest() == before.binding_digest()
                    && read_cell()? == cell
                    && generation_reader.observe()? == generation
                    && previous_reader.observe()? == previous
                    && store.load(&owner)? == current,
                "original physical C/A/Root data changed during the complete observation"
            );
            Ok(Self {
                source: publication.clone(),
                cell,
                generation,
                current,
                terminal: terminal.clone(),
            })
        })();
        // Error paths cannot skip the no-write and real-exit checks either.
        unchanged.require_unchanged(&paths)?;
        current_unchanged.require_unchanged(&current_paths)?;
        daemon.require_dead()?;
        root.require_dead()?;
        plan.resources.original.daemon.require_dead()?;
        plan.resources.original.root.require_dead()?;
        result
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CellFilesData {
    journal: PathBuf,
    witness: PathBuf,
    witness_scope: [u8; 32],
    witness_objective: [u8; 32],
    witness_generation: u64,
    witness_records: usize,
    maximum_records: usize,
}

fn open_original(declared: &OriginalFileData) -> anyhow::Result<File> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(&declared.path)?;
    declared.require_file(&file)?;
    anyhow::ensure!(
        file.metadata()?.len() != 0,
        "existing original data cannot be initialized or repaired"
    );
    Ok(file)
}

fn open_source(
    config: &OriginalSingleQ24SourceConfigurationV1,
    identity: &AgentdIdentity,
    journal: File,
    witness: File,
) -> anyhow::Result<HistoricalCircuitTaskSourceV1<FileAnchorWitnessStore>> {
    let witness = FileAnchorWitnessStore::open(
        witness,
        config.witness_scope,
        config.witness_generation,
        config.witness_records,
    )?;
    Ok(HistoricalCircuitTaskSourceV1::open(
        journal,
        witness,
        identity,
        &config.fence,
        &config.registry()?,
        vec![config.source.clone()],
    )?)
}

fn read_original_a(plan: &OriginalPostAPlan) -> anyhow::Result<CircuitTaskSourcePublicationV1> {
    let a = &plan.resources.original.plan;
    let bytes = super::observer::read_private(&a.root.source, 65_536)?;
    let config = OriginalSingleQ24SourceConfigurationV1::from_original_deployment_bytes(
        &bytes,
        &a.identity,
    )?;
    anyhow::ensure!(
        config.source_journal == a.files.source && config.source_witness == a.files.source_witness,
        "original A source deployment selects another file"
    );
    let mut source = open_source(
        &config,
        &a.identity,
        open_original(&OriginalFileData::capture(&a.files.source)?)?,
        open_original(&OriginalFileData::capture(&a.files.source_witness)?)?,
    )?;
    let observed = source.read_run_publication(&config.source.scope.run_id)?;
    anyhow::ensure!(
        source.read_run_publication(&config.source.scope.run_id)? == observed,
        "original A Source changed during data readback"
    );
    Ok(observed)
}

fn original_selection_digest(
    plan: &OriginalPostAPlan,
    selected: &OriginalSelectedArtifactData,
) -> anyhow::Result<Digest32> {
    let inputs = &plan.root.publication_inputs;
    let signed = &selected.selection;
    let original = super::super::data::SelectionData::from_original_selection(signed)?;
    anyhow::ensure!(
        plan.resources
            .owners
            .independent_selection
            .read_original(/*maximum*/ 16 * 1024)?
            == serde_json::to_vec(&original)?
            && selected.registry.head_digest == signed.registry_head_digest
            && Digest32::of_bytes(&serde_json::to_vec(&selected.manifest)?)
                == signed.content_digest
            && selected.manifest.digest()? == signed.compatibility_digest.into_array(),
        "original independent selection, registry or complete manifest data differs"
    );
    let receipt = &inputs.withdrawal;
    let withdrawal = read_dataset_withdrawal_snapshot(
        open_original(&OriginalFileData::capture(&inputs.withdrawal_file)?)?,
        DatasetWithdrawalSnapshotReceiptV1 {
            binding: Digest32::from_array(receipt.binding),
            scope_digest: Digest32::from_array(receipt.scope),
            head_digest: Digest32::from_array(receipt.head),
            file_digest: Digest32::from_array(receipt.file_digest),
            records: receipt.records,
            encoded_bytes: receipt.encoded_bytes,
        },
    )?;
    anyhow::ensure!(
        withdrawal.scope_digest() == Some(signed.withdrawal_scope_digest),
        "original independent withdrawal scope differs"
    );
    let verifier = inputs
        .selector_trust
        .original_selector(&inputs.owner_trust.original_owner_trust()?)?;
    let mut signed_bytes = signed.signing_bytes();
    signed_bytes.extend_from_slice(&signed.signature);
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.generation-selection.v1\0",
        Digest32::of_bytes(&signed_bytes).as_array(),
        signed.registry_head_digest.as_array(),
        signed.current_witness_digest.as_array(),
        signed.current_trust_digest.as_array(),
        verifier.trust_digest().as_array(),
        signed.withdrawal_scope_digest.as_array(),
        withdrawal.head_digest().as_array(),
        signed.content_digest.as_array(),
        &selected.manifest.digest()?,
    ]))
}
