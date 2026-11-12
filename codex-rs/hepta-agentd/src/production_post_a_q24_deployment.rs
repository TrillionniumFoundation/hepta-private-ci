//! Sealed deployment data cannot supply a request, trust root, signer role or
//! completed task. Those are obtained from the same actual Root recipient.

use std::io::Read;
use std::io::Seek;
use std::path::PathBuf;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;

use super::*;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Deployment {
    schema: String,
    identity_digest: String,
    baseline: BaselineFiles,
    head: Head,
    epochs: u16,
    learning_rate_q24: i64,
    inherited_inclusion_policy: [u8; 32],
    unit_profile_digest: [u8; 32],
    snapshot_id: String,
    pub(super) freeze: owners::SigningFilesData,
    pub(super) freeze_mode: owners::OpenMode,
    pub(super) stages: owners::StageFilesData,
    pub(super) delivery: owners::JournalData,
    pub(super) delivery_mode: owners::OpenMode,
    pub(super) queue_capacity: usize,
    pub(super) continuation: ContinuationData,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ContinuationData {
    pub(super) artifacts: artifacts::ArtifactFilesData,
    pub(super) task: c_task::CTaskData,
    pub(super) generation: generation::GenerationFilesData,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BaselineFiles {
    base: PathBuf,
    organ_adapter: Option<PathBuf>,
    cell_adapter: Option<PathBuf>,
    encoder: PathBuf,
    heads: PathBuf,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Head {
    Drive { index: u16 },
    Prediction { index: u16 },
}

impl Deployment {
    pub(super) fn read(mut file: File, identity: &AgentdIdentity) -> Result<Self, AgentdError> {
        let length = file.metadata()?.len();
        if !(1..=1_048_576).contains(&length) {
            return Err(refused("bounded sealed post-A deployment required"));
        }
        crate::authority_host_bootstrap_seal::validate_sealed(&file, length)?;
        file.rewind()?;
        let mut bytes = Vec::with_capacity(length as usize);
        Read::by_ref(&mut file)
            .take(length + 1)
            .read_to_end(&mut bytes)?;
        crate::authority_host_bootstrap_seal::validate_sealed(&file, length)?;
        if bytes.len() as u64 != length {
            return Err(refused("post-A deployment length changed"));
        }
        let data: Self = serde_json::from_slice(&bytes)?;
        if data.schema != "hepta.agentd.original_post_a_q24_launch.v1"
            || data.identity_digest.parse::<Digest32>().map_err(refused)?
                != crate::neuron_generation_process_identity_digest_v1(identity)?
            || !(1..=64).contains(&data.queue_capacity)
            || !(1..=256).contains(&data.epochs)
            || !(1..=16_777_216).contains(&data.learning_rate_q24)
        {
            return Err(refused("post-A identity, SGD or capacity differs"));
        }
        StableId::new(&data.snapshot_id).map_err(refused)?;
        Ok(data)
    }

    pub(super) fn preparation_config(
        &self,
        initial: &LearningIterationSnapshotV1,
        files: &mut OriginalFiles,
    ) -> Result<crate::CellQ24LearningPreparationConfigV1, AgentdError> {
        let baseline = Arc::new(
            crate::LoadedCellQ24ModelV1::open_files(crate::CellQ24ModelFilesV1 {
                base: files.read(&self.baseline.base)?,
                organ_adapter: self
                    .baseline
                    .organ_adapter
                    .as_deref()
                    .map(|path| files.read(path))
                    .transpose()?,
                cell_adapter: self
                    .baseline
                    .cell_adapter
                    .as_deref()
                    .map(|path| files.read(path))
                    .transpose()?,
                encoder: files.read(&self.baseline.encoder)?,
                heads: files.read(&self.baseline.heads)?,
            })
            .map_err(refused)?,
        );
        if baseline.components() != &initial.request.selected_bundle.components {
            return Err(refused(
                "actual baseline differs from original Root request",
            ));
        }
        let projection = crate::CellQ24DatasetProjectionV1 {
            inherited_inclusion_policy: Digest32::from_array(self.inherited_inclusion_policy),
            unit_profile_digest: Digest32::from_array(self.unit_profile_digest),
            baseline_bundle: initial.request.selected_bundle.digest().map_err(refused)?,
            input_width: u16::try_from(baseline.input_width()).map_err(refused)?,
        };
        projection.inclusion_policy_digest().map_err(refused)?;
        Ok(crate::CellQ24LearningPreparationConfigV1 {
            request: initial.request.clone(),
            owners: initial.owners.clone(),
            baseline,
            head: match self.head {
                Head::Drive { index } => crate::CellQ24PrivateHeadV1::Drive { index },
                Head::Prediction { index } => crate::CellQ24PrivateHeadV1::Prediction { index },
            },
            rule: crate::CellQ24SgdRuleV1 {
                epochs: self.epochs,
                learning_rate_q24: self.learning_rate_q24,
            },
            projection,
            snapshot_id: StableId::new(&self.snapshot_id).map_err(refused)?,
        })
    }
}
