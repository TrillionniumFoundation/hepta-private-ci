//! Root-owned descriptor assembly. This loader neither initializes an output
//! nor reads heldout labels. Fresh registration and existing recovery are
//! separate operations in the original Root record owner.

use std::io;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationObserverConfigV1;
use codex_hepta_neuron::CellGenerationUnpublishedObserverV1;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;

use super::admission::OriginalBAuthorities;
use super::admission::RootIndependentBTrustData;
use super::files::OriginalBFile;
use super::files::OriginalBFileAccess;
use super::files::OriginalBFileIdentity;
use super::files::OriginalBFiles;
use super::protocol::OriginalBProtocolData;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Deployment {
    schema: u8,
    purpose: String,
    protocol: PathBuf,
    trust: PathBuf,
    protocol_statement: PathBuf,
    source: PathBuf,
    candidate_data: PathBuf,
    observed_statement: PathBuf,
    policy_statement: PathBuf,
    realized_plan_statement: PathBuf,
    evaluator_key: PathBuf,
    candidate: JournalFilesData,
    model: super::model_data::ModelData,
    fixed_expert: CellFilesData,
    holdout: PathBuf,
    executions: PathBuf,
    execution_signature: JournalFilesData,
    qualification_signature: JournalFilesData,
    publication: JournalFilesData,
    receipt: JournalFilesData,
    maximum_signature_lifetime_seconds: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CellFilesData {
    journal: PathBuf,
    witness: PathBuf,
    original: CellGenerationConfigV2,
    journal_records: u64,
    witness_scope: [u8; 32],
    witness_objective: [u8; 32],
    witness_generation: u64,
    witness_records: usize,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct JournalFilesData {
    journal: PathBuf,
    witness: PathBuf,
}

pub(super) struct OriginalBJournalFiles {
    pub(super) journal: OriginalBFile,
    pub(super) witness: OriginalBFile,
}

pub(super) struct OriginalBCellFiles {
    pub(super) journal: OriginalBFile,
    pub(super) witness: OriginalBFile,
    pub(super) config: CellGenerationObserverConfigV1,
}

pub(super) struct OriginalBInputs {
    deployment: OriginalBFile,
    deployment_digest: Digest32,
    protocol_file: OriginalBFile,
    protocol_digest: Digest32,
    trust_file: OriginalBFile,
    trust_digest: Digest32,
    protocol_statement: OriginalBFile,
    protocol_statement_digest: Digest32,
    pub(super) source: OriginalBFile,
    pub(super) candidate_data: OriginalBFile,
    pub(super) observed_statement: OriginalBFile,
    pub(super) policy_statement: OriginalBFile,
    pub(super) realized_plan_statement: OriginalBFile,
    pub(super) evaluator_key: OriginalBFile,
    pub(super) candidate: OriginalBCellFiles,
    pub(super) model: super::model_data::OriginalBModelFiles,
    pub(super) fixed_expert: OriginalBCellFiles,
    pub(super) holdout: OriginalBFile,
    pub(super) executions: OriginalBFile,
    pub(super) execution_signature: OriginalBJournalFiles,
    pub(super) qualification_signature: OriginalBJournalFiles,
    pub(super) publication: OriginalBJournalFiles,
    pub(super) receipt: OriginalBJournalFiles,
    pub(super) maximum_signature_lifetime_seconds: u64,
}

impl OriginalBInputs {
    pub(super) fn open(path: &Path) -> io::Result<Self> {
        let mut tracker = OriginalBFiles::default();
        let deployment = tracker.open(path, OriginalBFileAccess::ReadOnly)?;
        let bytes = deployment.read_stable(65_536)?;
        let data: Deployment = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if serde_json::to_vec(&data).map_err(io::Error::other)? != bytes
            || data.schema != 1
            || data.purpose != "runtime.learning.independent-b-deployment.v1"
            || data.maximum_signature_lifetime_seconds == 0
            || data.maximum_signature_lifetime_seconds > 86_400
        {
            return Err(io::Error::other(
                "canonical bounded original B deployment required",
            ));
        }
        let protocol_file = tracker.open(&data.protocol, OriginalBFileAccess::ReadOnly)?;
        let protocol_digest = Digest32::of_bytes(&protocol_file.read_stable(65_536)?);
        let trust_file = tracker.open(&data.trust, OriginalBFileAccess::ReadOnly)?;
        let trust_digest = Digest32::of_bytes(&trust_file.read_stable(65_536)?);
        let protocol_statement =
            tracker.open(&data.protocol_statement, OriginalBFileAccess::ReadOnly)?;
        let protocol_statement_digest =
            Digest32::of_bytes(&protocol_statement.read_stable(65_536)?);
        let fixed_expert = data.fixed_expert.open(&mut tracker)?;
        let candidate = OriginalBCellFiles {
            journal: tracker.open(&data.candidate.journal, OriginalBFileAccess::OwnerWriter)?,
            witness: tracker.open(&data.candidate.witness, OriginalBFileAccess::OwnerWriter)?,
            config: fixed_expert.config.clone(),
        };
        let model = data.model.open(&mut tracker)?;
        let inputs = Self {
            deployment,
            deployment_digest: Digest32::of_bytes(&bytes),
            protocol_file,
            protocol_digest,
            trust_file,
            trust_digest,
            protocol_statement,
            protocol_statement_digest,
            source: tracker.open(&data.source, OriginalBFileAccess::ReadOnly)?,
            candidate_data: tracker.open(&data.candidate_data, OriginalBFileAccess::OwnerWriter)?,
            observed_statement: tracker
                .open(&data.observed_statement, OriginalBFileAccess::ReadOnly)?,
            policy_statement: tracker
                .open(&data.policy_statement, OriginalBFileAccess::ReadOnly)?,
            realized_plan_statement: tracker
                .open(&data.realized_plan_statement, OriginalBFileAccess::ReadOnly)?,
            evaluator_key: tracker.open(&data.evaluator_key, OriginalBFileAccess::ReadOnly)?,
            candidate,
            fixed_expert,
            model,
            holdout: tracker.open(&data.holdout, OriginalBFileAccess::OwnerWriter)?,
            executions: tracker.open(&data.executions, OriginalBFileAccess::OwnerWriter)?,
            execution_signature: data.execution_signature.open(&mut tracker)?,
            qualification_signature: data.qualification_signature.open(&mut tracker)?,
            publication: data.publication.open(&mut tracker)?,
            receipt: data.receipt.open(&mut tracker)?,
            maximum_signature_lifetime_seconds: data.maximum_signature_lifetime_seconds,
        };
        inputs.require_original_files()?;
        Ok(inputs)
    }

    pub(super) fn admitted_protocol(
        &self,
        initial: &LearningIterationSnapshotV1,
        now: u64,
    ) -> io::Result<(OriginalBProtocolData, OriginalBAuthorities)> {
        self.require_original_files()?;
        let protocol = OriginalBProtocolData::decode(
            &self
                .protocol_file
                .require_digest(self.protocol_digest, 65_536)?,
            initial.request.evaluation_profile,
        )?;
        let trust = RootIndependentBTrustData::decode(
            &self.trust_file.require_digest(self.trust_digest, 65_536)?,
        )?
        .activate(initial, now)?;
        trust.require_statement(
            &self.protocol_statement,
            LearningEvidenceRoleV1::Generator,
            initial.request.evaluation_profile.as_array(),
            now,
        )?;
        self.require_original_files()?;
        Ok((protocol, trust))
    }

    pub(super) fn require_empty_reservation(&self) -> io::Result<()> {
        self.require_original_files()?;
        // The source and its per-observation signatures cannot already expose
        // labels when Root records the original protocol registration.
        for file in [
            &self.source,
            &self.candidate_data,
            &self.candidate.journal,
            &self.candidate.witness,
            &self.fixed_expert.journal,
            &self.fixed_expert.witness,
            &self.observed_statement,
            &self.policy_statement,
            &self.realized_plan_statement,
            &self.holdout,
            &self.executions,
            &self.execution_signature.journal,
            &self.execution_signature.witness,
            &self.qualification_signature.journal,
            &self.qualification_signature.witness,
            &self.publication.journal,
            &self.publication.witness,
            &self.receipt.journal,
            &self.receipt.witness,
        ] {
            file.require_empty()?;
        }
        self.require_original_files()
    }

    pub(super) fn deployment_digest(&self) -> Digest32 {
        self.deployment_digest
    }

    pub(super) fn protocol_statement_digest(&self) -> Digest32 {
        self.protocol_statement_digest
    }

    pub(super) fn file_identities(&self) -> Vec<OriginalBFileIdentity> {
        self.all_files()
            .into_iter()
            .map(|file| file.identity().clone())
            .collect()
    }

    pub(super) fn require_original_files(&self) -> io::Result<()> {
        for file in self.all_files() {
            file.require_original()?;
        }
        self.deployment
            .require_digest(self.deployment_digest, 65_536)?;
        self.protocol_file
            .require_digest(self.protocol_digest, 65_536)?;
        self.trust_file.require_digest(self.trust_digest, 65_536)?;
        self.protocol_statement
            .require_digest(self.protocol_statement_digest, 65_536)?;
        Ok(())
    }

    fn all_files(&self) -> Vec<&OriginalBFile> {
        let mut files = vec![
            &self.deployment,
            &self.protocol_file,
            &self.trust_file,
            &self.protocol_statement,
            &self.source,
            &self.candidate_data,
            &self.observed_statement,
            &self.policy_statement,
            &self.realized_plan_statement,
            &self.evaluator_key,
            &self.candidate.journal,
            &self.candidate.witness,
            &self.fixed_expert.journal,
            &self.fixed_expert.witness,
            &self.holdout,
            &self.executions,
            &self.execution_signature.journal,
            &self.execution_signature.witness,
            &self.qualification_signature.journal,
            &self.qualification_signature.witness,
            &self.publication.journal,
            &self.publication.witness,
            &self.receipt.journal,
            &self.receipt.witness,
        ];
        files.extend(self.model.all_files());
        files
    }
}

impl CellFilesData {
    fn open(self, tracker: &mut OriginalBFiles) -> io::Result<OriginalBCellFiles> {
        Ok(OriginalBCellFiles {
            journal: tracker.open(&self.journal, OriginalBFileAccess::OwnerWriter)?,
            witness: tracker.open(&self.witness, OriginalBFileAccess::OwnerWriter)?,
            config: CellGenerationObserverConfigV1 {
                generation: self.original,
                journal_records: self.journal_records,
                witness_scope: JournalScope {
                    scope_digest: Digest32::from_array(self.witness_scope),
                    objective_digest: Digest32::from_array(self.witness_objective),
                },
                witness_generation: Generation::new(self.witness_generation)
                    .map_err(io::Error::other)?,
                witness_records: self.witness_records,
            },
        })
    }
}

impl OriginalBCellFiles {
    pub(super) fn lock_original(&self) -> io::Result<OriginalBCellReadGuard> {
        let journal = self.journal.original_readonly()?;
        journal.try_lock_shared().map_err(io::Error::other)?;
        let witness = self.witness.original_readonly()?;
        witness.try_lock_shared().map_err(io::Error::other)?;
        self.journal.require_original()?;
        self.witness.require_original()?;
        Ok(OriginalBCellReadGuard { journal, witness })
    }

    pub(super) fn observer(&self) -> io::Result<CellGenerationUnpublishedObserverV1> {
        CellGenerationUnpublishedObserverV1::from_original_files(
            self.journal.original_readonly()?,
            self.witness.original_readonly()?,
            self.config.clone(),
        )
        .map_err(io::Error::other)
    }
    pub(super) fn manifest(&self) -> &codex_hepta_neuron::CellBackendManifestV2 {
        &self.config.generation.manifest
    }
}

pub(super) struct OriginalBCellReadGuard {
    journal: std::fs::File,
    witness: std::fs::File,
}

impl Drop for OriginalBCellReadGuard {
    fn drop(&mut self) {
        let _ = self.witness.unlock();
        let _ = self.journal.unlock();
    }
}

impl JournalFilesData {
    fn open(self, tracker: &mut OriginalBFiles) -> io::Result<OriginalBJournalFiles> {
        Ok(OriginalBJournalFiles {
            journal: tracker.open(&self.journal, OriginalBFileAccess::OwnerWriter)?,
            witness: tracker.open(&self.witness, OriginalBFileAccess::OwnerWriter)?,
        })
    }
}
