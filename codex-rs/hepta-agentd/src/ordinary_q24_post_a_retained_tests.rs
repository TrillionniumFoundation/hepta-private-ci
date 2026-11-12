//! Evidence custody for real ordinary cases and their subsequent cold runs.
//! The values here are data and actual exited-process observations. They do
//! not create a historical admission, a learning result or a CURRENT owner.

use std::path::PathBuf;

use codex_hepta_neuron::CellGenerationObserverConfigV1;
use serde_json::json;

use super::b_evaluate::OriginalBusinessCase;
use super::b_evaluate::OriginalIndependentBEvaluationInputs;
use super::post_a_completed_data::OriginalCompletedCData;
use super::post_a_plan::OriginalPostAPlan;
use super::post_a_selection::OriginalSelectedArtifactData;
use super::source_keeper::OriginalSourceObservation;
use crate::OriginalRootBPublicationDataV2;
use crate::cell_q24_publication_driver::validation::Decision;
use crate::learning_iteration_checkpoint::ordinary_observer::OriginalCheckpointData;
use crate::ordinary_q24_cold_snapshot_tests::OriginalBusinessSnapshot;
use crate::ordinary_q24_process_child_tests::ExitedOriginalProcess;

pub(super) struct RetainedOrdinaryQ24Fixture {
    pub(super) case: OriginalBusinessCase,
    pub(super) plan: OriginalPostAPlan,
    pub(super) independent: OriginalIndependentBEvaluationInputs,
    pub(super) decision: Decision,
    pub(super) selected: OriginalSelectedArtifactData,
    pub(super) target: CellGenerationObserverConfigV1,
    pub(super) terminal: OriginalCheckpointData,
    pub(super) completed: OriginalCompletedCData,
    pub(super) daemon: ExitedOriginalProcess,
    pub(super) root: ExitedOriginalProcess,
    pub(super) source: ExitedOriginalProcess,
    pub(super) source_data: OriginalSourceObservation,
    pub(super) publication: OriginalRootBPublicationDataV2,
}

impl RetainedOrdinaryQ24Fixture {
    pub(super) fn business_files(&self) -> Vec<PathBuf> {
        let resources = &self.plan.resources;
        let mut paths = resources.original.business_files();
        paths.extend(resources.owners.business_files());
        paths.extend(resources.c.business_files());
        paths.extend(self.independent.business_files());
        paths.extend(resources.trust.keys.values().cloned());
        paths.push(resources.trust.payload_file.clone());
        let inputs = &self.plan.root.publication_inputs;
        paths.push(inputs.withdrawal_file.clone());
        paths.push(inputs.artifact_root.join("registries").join(format!(
            "{}-{}.snapshot",
            self.selected.registry.head_digest, self.selected.registry.file_digest
        )));
        paths.push(inputs.artifact_root.join("payloads").join(format!(
            "{}-{}.bin",
            self.selected.selection.artifact_id, self.selected.selection.content_digest
        )));
        // The fixed sets share some original paths. Collapse only identical
        // path names; the physical snapshot still refuses distinct aliases.
        paths.sort();
        paths.dedup();
        paths
    }

    pub(super) fn original_processes(&self) -> (&ExitedOriginalProcess, &ExitedOriginalProcess) {
        (&self.daemon, &self.root)
    }

    pub(super) fn archive_actual_phase(self) -> anyhow::Result<()> {
        let original = &self.plan.resources.original;
        let directory = original.plan.protected.path().join("ordinary-whole-phase");
        std::fs::create_dir(&directory)?;
        super::super::owned_mode(&directory, 0, 0, 0o700)?;
        for (name, child) in [
            ("a-daemon", &original.daemon),
            ("a-root", &original.root),
            ("a-observer", &original.observer),
            ("post-a-daemon", &self.daemon),
            ("post-a-root", &self.root),
            ("independent-source", &self.source),
        ] {
            child.require_dead()?;
            let logs = directory.join(name);
            std::fs::create_dir(&logs)?;
            super::super::owned_mode(&logs, 0, 0, 0o700)?;
            child.archive_original_logs(&logs)?;
        }
        let files = self.business_files();
        let physical = OriginalBusinessSnapshot::capture(&files)?;
        super::root::write_bytes(
            &directory.join("original-business-images.txt"),
            format!("{physical:#?}\n").as_bytes(),
        )?;
        super::root::write_json(
            &directory.join("original-b-publication.json"),
            &self.publication,
        )?;
        super::root::write_json(
            &directory.join("original-source-observation.json"),
            &self.source_data,
        )?;
        super::root::write_json(
            &directory.join("original-selected-artifact.json"),
            &super::super::data::SelectionData::from_original_selection(&self.selected.selection)?,
        )?;
        super::root::write_json(
            &directory.join("original-c-target.json"),
            &super::super::data::ObserverData::from_original_observer(&self.target),
        )?;
        super::root::write_bytes(
            &directory.join("original-c-cell-decision.bin"),
            &crate::circuit_cell_output::encode_receipt(&self.completed.cell.decision)?,
        )?;
        super::root::write_bytes(
            &directory.join("original-c-source-result.bin"),
            self.completed.source.result_bytes(),
        )?;
        super::root::write_json(
            &directory.join("actual-root-current.json"),
            &self.completed.current,
        )?;
        let snapshot = self.terminal.snapshot.as_ref().ok_or_else(|| {
            anyhow::anyhow!("actual final Root checkpoint missing while archiving")
        })?;
        super::root::write_bytes(
            &directory.join("actual-terminal-snapshot.txt"),
            format!("{snapshot:#?}\n").as_bytes(),
        )?;
        let process = |child: &ExitedOriginalProcess| {
            let actual = child.lifetime();
            json!({"pid":actual.pid,"start_ticks":actual.start_ticks,"boot_id":actual.boot_id})
        };
        super::root::write_json(
            &directory.join("actual-case.json"),
            &json!({
                "schema":1,"business_case":format!("{:?}", self.case),
                "source_commit":std::env::var("HEPTA_ORDINARY_SOURCE_COMMIT")?,
                "source_tree":std::env::var("HEPTA_ORDINARY_SOURCE_TREE")?,
                "initial":self.plan.profile.original_initial_data()?.head_digest.to_string(),
                "decision_head":self.decision.snapshot.head_digest.to_string(),
                "terminal_head":snapshot.head_digest.to_string(),
                "scope":self.terminal.scope_binding.to_string(),
                "actual_receipts":snapshot.receipts.len(),"business_files":files,
                "actual_c_revision":self.completed.cell.snapshot.revision,
                "actual_c_publication":self.completed.source.publication_digest().to_string(),
                "actual_c_checkpoint":self.completed.source.checkpoint_digest().to_string(),
                "original_a_daemon":process(&original.daemon),"original_a_root":process(&original.root),
                "original_observer":process(&original.observer),
                "post_a_daemon":process(&self.daemon),"post_a_root":process(&self.root),
                "independent_source":process(&self.source)
            }),
        )?;
        // This is the original Root record, retained in place with its data
        // directory. No reconstructed checkpoint is handed to a product owner.
        physical.require_unchanged(&self.business_files())?;
        eprintln!("ORDINARY_Q24_ACTUAL_WHOLE_EVIDENCE={}", directory.display());
        let _ = self.plan.resources.model_witness.keep();
        let _ = self.plan.resources.original.plan.runtime.keep();
        let _ = self.plan.resources.original.plan.protected.keep();
        let _ = self.independent.preserve_original_business_directory();
        Ok(())
    }
}
