//! C has separate original files and an external Objective input. Its selected
//! model data is filled only after the actual learning decision is observed;
//! this setup does not publish CURRENT, run C or construct a completion.

use std::path::Path;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellGenerationObserverConfigV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::Value;
use serde_json::json;

use super::RetainedOriginalAPhase;
use super::deployment::digest;
use super::inputs::ObjectiveInputs;
use super::post_a_file::OriginalFileData;
use super::recovery::OriginalSuccessorAdministration;
use crate::CircuitTaskSourceInputV1;
use crate::LoadedCellQ24ModelV1;

pub(super) struct OriginalCInputFiles {
    pub(super) source_configuration: OriginalFileData,
    pub(super) target_configuration: OriginalFileData,
    pub(super) signed_ingress: OriginalFileData,
    pub(super) source_journal: OriginalFileData,
    pub(super) source_witness: OriginalFileData,
    pub(super) cell_journal: OriginalFileData,
    pub(super) cell_witness: OriginalFileData,
    pub(super) inference: OriginalFileData,
    pub(super) generation_journal: OriginalFileData,
    pub(super) generation_witness: OriginalFileData,
    pub(super) publication_material: OriginalFileData,
    objective: ObjectiveInputs,
    source: CircuitTaskSourceInputV1,
}

impl OriginalCInputFiles {
    pub(super) fn reserve(
        original: &RetainedOriginalAPhase,
        successor: &OriginalSuccessorAdministration,
        data: &Path,
        witnesses: &Path,
        actual_replay_frontier: Digest32,
    ) -> anyhow::Result<Self> {
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        anyhow::ensure!(
            !actual_replay_frontier.is_zero(),
            "original retained replay frontier"
        );
        let (_, baseline, _) =
            super::super::material::load(&original.plan.runtime.path().join("model"))?;
        let objective = ObjectiveInputs::successor(
            &successor.identity,
            &baseline,
            crate::authbus_ingress::now_ms()?,
        )?;
        let mut source = super::super::material::source(successor.identity.agent_id.as_str())?;
        source.scope.run_id = StableId::new(super::inputs::C_RUN)?;
        // A used [1, 1/4]. C is a separate, explicitly supplied ordinary
        // input [1, 1/2], fixed before Training or the decision is available.
        // The original encoder still validates these canonical HQ24I001 bytes.
        source.observation = b"HQ24I001".to_vec();
        source.observation.extend_from_slice(&2_u16.to_le_bytes());
        for value in [1_i64 << 24, 1_i64 << 23] {
            source.observation.extend_from_slice(&value.to_le_bytes());
        }
        source.source_frontier = actual_replay_frontier;
        source.objective_digest = objective.objective;
        source.monotonic_micros = super::fixture::monotonic_micros()?;
        source.deadline_micros = source
            .monotonic_micros
            .checked_add(120_000_000)
            .ok_or_else(|| anyhow::anyhow!("original C deadline overflow"))?;
        source.lease_duration_ms = 120_000;
        let reserve = |directory: &Path, name: &str| {
            OriginalFileData::reserve(directory.join(name), /*uid*/ 60001, /*gid*/ 60001)
        };
        Ok(Self {
            source_configuration: reserve(data, "c-source.json")?,
            target_configuration: reserve(data, "c-target.json")?,
            signed_ingress: reserve(data, "c-original-objective.json")?,
            source_journal: reserve(data, "c-source.journal")?,
            source_witness: reserve(witnesses, "c-source.witness")?,
            cell_journal: reserve(data, "c-cell.journal")?,
            cell_witness: reserve(witnesses, "c-cell.witness")?,
            inference: reserve(data, "c-inference-control")?,
            generation_journal: reserve(data, "c-generation.journal")?,
            generation_witness: reserve(witnesses, "c-generation.witness")?,
            publication_material: reserve(data, "original-publication-material.json")?,
            objective,
            source,
        })
    }

    pub(super) fn root_successor_data(&self) -> Value {
        json!({
            "source_configuration": self.source_configuration,
            "target_configuration": self.target_configuration,
            "signed_ingress": self.signed_ingress,
            "source_journal": self.source_journal,
            "source_witness": self.source_witness,
            "cell_journal": self.cell_journal,
            "cell_witness": self.cell_witness,
            "inference_control": self.inference,
            "cell_witness_scope": digest("ordinary-original-c-cell"),
            "cell_witness_objective": self.objective.objective.into_array(),
            "cell_witness_generation": 1,
            "cell_witness_records": 128,
            "maximum_cell_records": 4,
            "inference_capacity": 4,
            "worker_generation": 1
        })
    }

    pub(super) fn business_files(&self) -> Vec<std::path::PathBuf> {
        [
            &self.source_configuration,
            &self.target_configuration,
            &self.signed_ingress,
            &self.source_journal,
            &self.source_witness,
            &self.cell_journal,
            &self.cell_witness,
            &self.inference,
            &self.generation_journal,
            &self.generation_witness,
            &self.publication_material,
        ]
        .into_iter()
        .map(|file| file.path.clone())
        .collect()
    }

    pub(super) fn daemon_task_data(&self) -> Value {
        let files = json!({
            "cell_journal": self.cell_journal.path,
            "cell_witness": self.cell_witness.path,
            "cell_witness_scope": digest("ordinary-original-c-cell"),
            "cell_witness_objective": self.objective.objective.into_array(),
            "cell_witness_generation": 1,
            "cell_witness_records": 128,
            "maximum_cell_records": 4,
            "inference_control": self.inference.path,
            "inference_capacity": 4,
            "worker_generation": 1
        });
        json!({
            "source": self.source_configuration.path,
            "target": self.target_configuration.path,
            "signed_ingress": self.signed_ingress.path,
            "mode": "create",
            "recovery": null,
            "clock_domain": "linux_clock_monotonic_micros_v1",
            "files": files
        })
    }

    pub(super) fn publish_selected_input_data(
        &self,
        successor: &OriginalSuccessorAdministration,
        bundle: &CellCompatibilityBundleV1,
        model: &LoadedCellQ24ModelV1,
        selected_manifest: &CellBackendManifestV2,
    ) -> anyhow::Result<CellGenerationObserverConfigV1> {
        anyhow::ensure!(
            super::fixture::monotonic_micros()? < self.source.deadline_micros
                && crate::authbus_ingress::now_ms()? < self.objective.request.expires_at_ms
                && model.components() == &bundle.components,
            "actual selected C data or original deadline differs"
        );
        crate::cell_composed_q24::validate_manifest(bundle, selected_manifest)?;
        let mut definition = super::super::material::definition(model, bundle)?;
        definition.max_queue_age_micros = 120_000_000;
        let mut generation = super::super::material::configuration(
            model,
            bundle,
            &definition,
            &self.source,
            /*generation*/ 2,
        )?;
        generation.manifest = selected_manifest.clone();
        generation.initial.manifest_digest = selected_manifest.digest()?;
        let target = super::super::observer_config(generation)?;
        // This initializes only the pre-reserved new witness header. The
        // original product still must open its empty target journal, obtain
        // the real Root/FinalUse admission, publish and execute C.
        let witness = FileAnchorWitnessStore::open(
            self.generation_witness.open_empty_writer()?,
            target.witness_scope,
            target.witness_generation,
            target.witness_records,
        )?;
        drop(witness);
        let mut source = super::deployment::source_data_for_original_files(
            [
                &self.source_journal.path,
                &self.source_witness.path,
                &self.cell_journal.path,
                &self.cell_witness.path,
            ],
            &successor.identity,
            &definition,
            &self.source,
            /*ledger_deployment*/ None,
        )?;
        source["witness_scope"] = json!(digest("ordinary-original-c-source"));
        source["cell_files"]["witness_scope"] = json!(digest("ordinary-original-c-cell"));
        source["fence"]["owner_id"] = json!("ordinary-original-c-circuit-owner");
        source["fence"]["fencing_token"] = json!("ordinary-original-c-circuit-fence");
        let source_bytes = serde_json::to_vec(&source)?;
        crate::OriginalSingleQ24SourceConfigurationV1::from_original_deployment_bytes(
            &source_bytes,
            &successor.identity,
        )?;
        let mut request = self.objective.request.clone();
        request.body.model_tuple_digest = bundle.digest()?.to_string();
        request.body.artifact_set_digest = request.body.model_tuple_digest.clone();
        request.signature_hex = super::inputs::hex(
            &SigningKey::from_bytes(&[91; 32])
                .sign(
                    &crate::authbus_objective_claims(&successor.identity, &request)?
                        .signing_bytes(),
                )
                .to_bytes(),
        );
        // These are externally supplied, signed inputs. Their visibility does
        // not imply admission; the daemon verifies every original binding.
        self.target_configuration
            .write_original_once(&serde_json::to_vec(
                &super::super::data::ObserverData::from_original_observer(&target),
            )?)?;
        self.source_configuration
            .write_original_once(&source_bytes)?;
        self.signed_ingress
            .write_original_once(&serde_json::to_vec(&request)?)?;
        Ok(target)
    }
}
