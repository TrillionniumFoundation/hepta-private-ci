//! Actual bounded Source/Cell data from Root's fixed successor files. Every
//! caller must enclose this I/O and its postchecks in the publication refusal
//! arm. None of these values grants currentness, execution or Dataset access.

use super::*;
use crate::AgentdIdentity;
use crate::HistoricalCircuitTaskSourceV1;
use crate::OriginalSingleQ24SourceConfigurationV1;
use crate::RootHistoricalSourceInputsV1;
use crate::authority_host_service::generation_initial::cell_retention::OriginalCellFiles;
use crate::authority_host_service::generation_initial::cell_retention::RootHistoricalCellInputsV1;
use crate::authority_host_service::generation_initial::historical_source_pin::RetainedRootHistoricalSourceInputsV1;
use crate::circuit_task::RootHistoricalTaskPublicationDataV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::observe_original_file_anchor_v1;

/// Persisted data only. There is no raw cut-to-capability conversion.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RootSuccessorTaskCutV1 {
    pub(crate) configuration: String,
    pub(crate) source_sequence: u64,
    pub(crate) source_checkpoint: String,
    pub(crate) cell_sequence: u64,
    pub(crate) cell_checkpoint: String,
    pub(crate) definition: String,
    pub(crate) writer_epoch: u64,
    pub(crate) publication: RootHistoricalTaskPublicationDataV1,
}

impl RootOriginalSuccessorFilesV1 {
    pub(crate) fn deployment_digest(&self) -> io::Result<Digest32> {
        self.data.require_bounds()?;
        Ok(Digest32::of_parts(&[
            b"hepta.root.original-successor-files.v1\0",
            &serde_json::to_vec(&self.data).map_err(io::Error::other)?,
        ]))
    }

    /// Existing witness headers are observed, never created. The ordinary C
    /// preparation must have created them before CURRENT can be reserved.
    pub(crate) fn require_registered_baseline(
        &self,
        identity: &AgentdIdentity,
        target: &CellGenerationOwnerBindingV1,
    ) -> io::Result<Digest32> {
        self.with_inputs(identity, target, |source, cell, configuration| {
            for _ in 0..2 {
                if source.journal.metadata()?.len() != 0
                    || observe_original_file_anchor_v1(
                        &source.witness,
                        source.witness_scope,
                        source.witness_generation,
                        source.witness_records,
                    )
                    .map_err(io::Error::other)?
                    .is_some()
                {
                    return Err(io::Error::other("successor Source baseline is not empty"));
                }
                OriginalCellFiles::require_original_cell_baseline(&cell)?;
            }
            Ok(configuration)
        })
    }

    pub(crate) fn observe_original_successor(
        &self,
        identity: &AgentdIdentity,
        target: &CellGenerationOwnerBindingV1,
    ) -> io::Result<RootSuccessorTaskCutV1> {
        self.with_inputs(identity, target, |inputs, cell, configuration| {
            if inputs.witness.metadata()?.len() == 0 {
                return Err(io::Error::other("original successor witness missing"));
            }
            let witness = FileAnchorWitnessStore::open(
                inputs.witness,
                inputs.witness_scope,
                inputs.witness_generation,
                inputs.witness_records,
            )
            .map_err(io::Error::other)?;
            let mut source = HistoricalCircuitTaskSourceV1::open(
                inputs.journal,
                witness,
                identity,
                &inputs.fence,
                &inputs.registry,
                vec![inputs.source.clone()],
            )
            .map_err(io::Error::other)?;
            let before = source
                .observe_run_publication(&inputs.source.scope.run_id)
                .map_err(io::Error::other)?;
            let (cell_anchor, decision) = OriginalCellFiles::read_original_successor_cell(
                &cell,
                &inputs.definition,
                &inputs.source,
                before.publication(),
                target,
            )?;
            let publication =
                RootHistoricalTaskPublicationDataV1::from_original_observation(&before, &decision)
                    .map_err(io::Error::other)?;
            let after = source
                .observe_run_publication(&inputs.source.scope.run_id)
                .map_err(io::Error::other)?;
            if before.publication() != after.publication()
                || before.journal_anchor() != after.journal_anchor()
                || before.binding_digest() != after.binding_digest()
            {
                return Err(io::Error::other(
                    "original successor Source changed across Cell read",
                ));
            }
            Ok(RootSuccessorTaskCutV1 {
                configuration: configuration.to_string(),
                source_sequence: after.journal_anchor().sequence,
                source_checkpoint: after.journal_anchor().checkpoint_digest.to_string(),
                cell_sequence: cell_anchor.sequence,
                cell_checkpoint: cell_anchor.checkpoint_digest.to_string(),
                definition: inputs
                    .definition
                    .semantic_digest()
                    .map_err(io::Error::other)?
                    .to_string(),
                writer_epoch: target.writer_epoch(),
                publication,
            })
        })
    }

    fn with_inputs<T>(
        &self,
        identity: &AgentdIdentity,
        target: &CellGenerationOwnerBindingV1,
        action: impl FnOnce(RootHistoricalSourceInputsV1, OriginalCellFiles, Digest32) -> io::Result<T>,
    ) -> io::Result<T> {
        original_root()?;
        self.require_original()?;
        let cold;
        let files: &[RetainedMaterial] = if let Some(files) = &self.files {
            files
        } else {
            cold = self
                .data
                .files()
                .iter()
                .map(|data| RetainedMaterial::open_original((*data).clone(), self.uid, self.gid))
                .collect::<io::Result<Vec<_>>>()?;
            cold.as_slice()
        };
        let source = files[0]
            .observe_ready()?
            .ok_or_else(|| io::Error::other("original Source configuration absent"))?;
        let target_data = files[1]
            .observe_ready()?
            .ok_or_else(|| io::Error::other("original target configuration absent"))?;
        let ingress = files[2]
            .observe_ready()?
            .ok_or_else(|| io::Error::other("original C ingress absent"))?;
        let original = OriginalSingleQ24SourceConfigurationV1::from_original_deployment_bytes(
            source.bytes(),
            identity,
        )
        .map_err(io::Error::other)?;
        if original.source_journal != self.data.source_journal.path
            || original.source_witness != self.data.source_witness.path
        {
            return Err(io::Error::other(
                "successor configuration selected different files",
            ));
        }
        let data: crate::authority_host_runtime::publication_data::ObserverData =
            serde_json::from_slice(target_data.bytes()).map_err(io::Error::other)?;
        let config = data.original_observer_config()?;
        if CellGenerationOwnerBindingV1::new(&config.generation, config.journal_records)
            .map_err(io::Error::other)?
            != *target
        {
            return Err(io::Error::other(
                "successor configuration differs from full Root target",
            ));
        }
        let configuration = Digest32::of_parts(&[
            b"hepta.root.original-successor-configuration.v1\0",
            self.deployment_digest()?.as_array(),
            source.bytes(),
            target_data.bytes(),
            ingress.bytes(),
        ]);
        let registry = original.registry().map_err(io::Error::other)?;
        let source_inputs = RootHistoricalSourceInputsV1 {
            journal: RetainedMaterial::original_readonly_description(&files[3])?,
            witness: RetainedMaterial::original_readonly_description(&files[4])?,
            witness_scope: original.witness_scope,
            witness_generation: original.witness_generation,
            witness_records: original.witness_records,
            fence: original.fence,
            registry,
            definition: original.definition,
            source: original.source,
        };
        let retained = RootHistoricalSourceInputsV1::retain_original(
            source_inputs,
            identity,
            target,
            self.uid,
            self.gid,
        )?;
        let source_inputs = RetainedRootHistoricalSourceInputsV1::into_registered(
            retained, identity, target, self.uid, self.gid,
        )?;
        let cell = OriginalCellFiles::retain_original_cell(
            RootHistoricalCellInputsV1 {
                journal: RetainedMaterial::original_readonly_description(&files[5])?,
                witness: RetainedMaterial::original_readonly_description(&files[6])?,
                witness_scope: JournalScope {
                    scope_digest: Digest32::from_array(self.data.cell_witness_scope),
                    objective_digest: Digest32::from_array(self.data.cell_witness_objective),
                },
                witness_generation: Generation::new(self.data.cell_witness_generation)
                    .map_err(io::Error::other)?,
                witness_records: self.data.cell_witness_records,
                maximum_records: self.data.maximum_cell_records,
            },
            self.uid,
            self.gid,
        )?;
        let result = action(source_inputs, cell, configuration)?;
        source.require_unchanged()?;
        target_data.require_unchanged()?;
        ingress.require_unchanged()?;
        for file in files {
            file.require_original()?;
        }
        self.require_original()?;
        Ok(result)
    }
}
