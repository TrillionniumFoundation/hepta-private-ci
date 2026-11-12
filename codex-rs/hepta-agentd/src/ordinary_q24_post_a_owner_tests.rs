//! First post-A input reservations. These are existing empty descriptors and
//! the administrator's original role keys; the product alone opens owners,
//! signs completed stages and freezes the actual historical Dataset.

use std::path::Path;
use std::path::PathBuf;

use serde::Serialize;
use serde_json::Value;
use serde_json::json;

use super::post_a_file::OriginalFileData;
use super::post_a_trust::FREEZER;
use super::post_a_trust::OriginalPostATrust;
use super::post_a_trust::TRAINER;

const SIGNATURE_LIFETIME_SECONDS: u64 = 120;

#[derive(Serialize)]
pub(super) struct OriginalJournalData {
    journal: PathBuf,
    witness: PathBuf,
    scope: [u8; 32],
    generation: u64,
    max_records: usize,
}

impl OriginalJournalData {
    fn reserve(data: &Path, witnesses: &Path, name: &str) -> anyhow::Result<Self> {
        let journal =
            OriginalFileData::reserve(data.join(format!("{name}.journal")), 60001, 60001)?;
        let witness =
            OriginalFileData::reserve(witnesses.join(format!("{name}.witness")), 60001, 60001)?;
        Ok(Self {
            journal: journal.path,
            witness: witness.path,
            scope: super::deployment::digest(&format!("ordinary-post-a-{name}")),
            generation: 1,
            // Explicit original capacity includes Training and its separate
            // Generator B plan signature. No product capacity is increased.
            max_records: 32,
        })
    }

    fn append_paths(&self, paths: &mut Vec<PathBuf>) {
        paths.extend([self.journal.clone(), self.witness.clone()]);
    }
}

#[derive(Serialize)]
pub(super) struct OriginalSigningData {
    owner: OriginalJournalData,
    key: PathBuf,
    signature_lifetime_seconds: u64,
}

impl OriginalSigningData {
    fn reserve(
        data: &Path,
        witnesses: &Path,
        name: &str,
        trust: &OriginalPostATrust,
        role: &str,
    ) -> anyhow::Result<Self> {
        Ok(Self {
            owner: OriginalJournalData::reserve(data, witnesses, name)?,
            key: trust.key(role)?.to_path_buf(),
            signature_lifetime_seconds: SIGNATURE_LIFETIME_SECONDS,
        })
    }
}

pub(super) struct OriginalPostAOwnerInputs {
    freeze: OriginalSigningData,
    experience: OriginalSigningData,
    dataset: OriginalSigningData,
    training: OriginalJournalData,
    training_receipt: OriginalSigningData,
    local: OriginalSigningData,
    selection: OriginalSigningData,
    next_use: OriginalSigningData,
    delivery: OriginalJournalData,
    pub(super) writer_lease: OriginalFileData,
    pub(super) candidate_head: OriginalFileData,
    pub(super) independent_selection: OriginalFileData,
}

impl OriginalPostAOwnerInputs {
    pub(super) fn reserve(
        data: &Path,
        witnesses: &Path,
        trust: &OriginalPostATrust,
    ) -> anyhow::Result<Self> {
        Ok(Self {
            freeze: OriginalSigningData::reserve(data, witnesses, "freeze", trust, FREEZER)?,
            experience: OriginalSigningData::reserve(
                data,
                witnesses,
                "experience",
                trust,
                "ordinary-experience-observer",
            )?,
            dataset: OriginalSigningData::reserve(
                data,
                witnesses,
                "dataset",
                trust,
                "ordinary-dataset-observer",
            )?,
            training: OriginalJournalData::reserve(data, witnesses, "training")?,
            training_receipt: OriginalSigningData::reserve(
                data,
                witnesses,
                "training-receipt",
                trust,
                TRAINER,
            )?,
            local: OriginalSigningData::reserve(
                data,
                witnesses,
                "local-decision",
                trust,
                "ordinary-local-selector",
            )?,
            selection: OriginalSigningData::reserve(
                data,
                witnesses,
                "selection",
                trust,
                "ordinary-local-selector",
            )?,
            next_use: OriginalSigningData::reserve(
                data,
                witnesses,
                "next-use",
                trust,
                "ordinary-next-use-observer",
            )?,
            delivery: OriginalJournalData::reserve(data, witnesses, "delivery")?,
            writer_lease: OriginalFileData::reserve(
                data.join("artifact-writer.json"),
                60001,
                60001,
            )?,
            candidate_head: OriginalFileData::reserve(
                data.join("artifact-candidate.json"),
                60001,
                60001,
            )?,
            independent_selection: OriginalFileData::reserve(
                data.join("artifact-selection.json"),
                60001,
                60001,
            )?,
        })
    }

    pub(super) fn stage_data(&self) -> Value {
        json!({
            "mode":"create", "experience":self.experience, "dataset":self.dataset,
            "training":self.training, "training_receipt":self.training_receipt,
            "local":self.local, "local_policy":"adopt_qualified"
        })
    }

    pub(super) fn freeze_data(&self) -> anyhow::Result<Value> {
        Ok(serde_json::to_value(&self.freeze)?)
    }

    pub(super) fn root_freeze_data(&self) -> anyhow::Result<Value> {
        Ok(json!({
            "journal":OriginalFileData::capture(&self.freeze.owner.journal)?,
            "witness":OriginalFileData::capture(&self.freeze.owner.witness)?,
            "scope":self.freeze.owner.scope, "generation":self.freeze.owner.generation,
            "maximum_records":self.freeze.owner.max_records
        }))
    }

    pub(super) fn delivery_data(&self) -> anyhow::Result<Value> {
        Ok(serde_json::to_value(&self.delivery)?)
    }

    pub(super) fn generation_data(&self) -> Value {
        json!({
            "selection":self.selection,"next_use":self.next_use,
            "selection_mode":"create","next_use_mode":"create"
        })
    }

    pub(super) fn artifact_data(&self) -> Value {
        json!({
            "writer_lease":self.writer_lease.path,
            "candidate_head":self.candidate_head.path,
            "independent_selection":self.independent_selection.path
        })
    }

    pub(super) fn signature_lifetime_seconds(&self) -> u64 {
        self.freeze.signature_lifetime_seconds
    }

    pub(super) fn business_files(&self) -> Vec<PathBuf> {
        let mut paths = Vec::new();
        for signed in [
            &self.freeze,
            &self.experience,
            &self.dataset,
            &self.training_receipt,
            &self.local,
            &self.selection,
            &self.next_use,
        ] {
            signed.owner.append_paths(&mut paths);
        }
        self.training.append_paths(&mut paths);
        self.delivery.append_paths(&mut paths);
        paths.extend([
            self.writer_lease.path.clone(),
            self.candidate_head.path.clone(),
            self.independent_selection.path.clone(),
        ]);
        paths
    }
}
