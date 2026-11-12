//! The successor administrator fixes new inputs after real A retirement.
//! Ordinary binaries still have to recover the original physical material,
//! admit history, freeze, train, evaluate, publish and execute C themselves.

use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::path::PathBuf;
use std::time::Instant;

use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_types::Digest32;

use super::RetainedOriginalAPhase;
use super::post_a_c_inputs::OriginalCInputFiles;
use super::post_a_owner::OriginalPostAOwnerInputs;
use super::post_a_trust::OriginalPostATrust;
use super::recovery::OriginalSuccessorAdministration;

pub(super) const SNAPSHOT_ID: &str = "ordinary-original-a-frozen-dataset";
pub(super) const EPOCHS: u16 = 2;
pub(super) const LEARNING_RATE_Q24: i64 = (1 << 24) / 2;

pub(super) struct OriginalPostAResources {
    pub(super) original: RetainedOriginalAPhase,
    pub(super) successor: OriginalSuccessorAdministration,
    pub(super) trust: OriginalPostATrust,
    pub(super) owners: OriginalPostAOwnerInputs,
    pub(super) c: OriginalCInputFiles,
    pub(super) data: PathBuf,
    pub(super) witness_files: PathBuf,
    pub(super) model_reservation: PathBuf,
    pub(super) model_witness: tempfile::TempDir,
    pub(super) end: Instant,
}

pub(super) struct OriginalPostAPlan {
    pub(super) resources: OriginalPostAResources,
    pub(super) profile: crate::HostAuthorityLearningProfileV1,
    pub(super) root: super::post_a_deployment::OriginalPostARootPlans,
    pub(super) sealed: File,
}

impl OriginalPostAResources {
    pub(super) fn reserve_after_original_retirement(
        mut original: RetainedOriginalAPhase,
        runtime: &tokio::runtime::Runtime,
        end: Instant,
    ) -> anyhow::Result<Self> {
        anyhow::ensure!(
            Instant::now() < end,
            "original successor preparation deadline"
        );
        let successor = OriginalSuccessorAdministration::prepare(&original, end)?;
        original.plan.release_retired_artifact_writer()?;
        let data = original.plan.runtime.path().join("post-a-data");
        let witness_files = original.plan.runtime.path().join("post-a-witnesses");
        for directory in [&data, &witness_files] {
            std::fs::create_dir(directory)?;
            super::super::owned_mode(directory, 60001, 60001, 0o700)?;
        }
        let trust = OriginalPostATrust::prepare(&original, &data)?;
        let owners = OriginalPostAOwnerInputs::reserve(&data, &witness_files, &trust)?;
        let frontier = runtime.block_on(read_retired_original_frontier(&original))?;
        let c =
            OriginalCInputFiles::reserve(&original, &successor, &data, &witness_files, frontier)?;
        let model_reservation = original.plan.protected.path().join("post-a-model.json");
        let model_witness = reserve_original_model_witness(&model_reservation)?;
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        anyhow::ensure!(
            Instant::now() < end,
            "original successor preparation deadline"
        );
        Ok(Self {
            original,
            successor,
            trust,
            owners,
            c,
            data,
            witness_files,
            model_reservation,
            model_witness,
            end,
        })
    }

    pub(super) fn configure_original_evaluation(
        self,
        evaluation_profile: Digest32,
    ) -> anyhow::Result<OriginalPostAPlan> {
        anyhow::ensure!(
            Instant::now() < self.end && !evaluation_profile.is_zero(),
            "actual fixed evaluation protocol and original deadline required"
        );
        let profile =
            self.trust
                .original_profile(&self.original, &self.successor, evaluation_profile)?;
        let root = super::post_a_deployment::write_original_root_plans(&self, &profile)?;
        let bytes = super::post_a_deployment::original_daemon_data(&self)?;
        let sealed = crate::authority_host_bootstrap_seal::seal_bytes(&bytes)?;
        anyhow::ensure!(
            Instant::now() < self.end,
            "original successor configuration deadline"
        );
        Ok(OriginalPostAPlan {
            resources: self,
            profile,
            root,
            sealed,
        })
    }
}

async fn read_retired_original_frontier(
    original: &RetainedOriginalAPhase,
) -> anyhow::Result<Digest32> {
    original.daemon.require_dead()?;
    original.root.require_dead()?;
    let store =
        HeptaEvidenceStore::open_existing_read_only(&codex_state::SqliteConfig::from_sqlite_home(
            codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(
                &original.plan.identity.home_root,
            )?,
        ))
        .await?;
    let frontier = store.authbus_replay_frontier_digest().await;
    store.close().await;
    let frontier = frontier?;
    let (_, checkpoint) = crate::authbus_checkpoint::ReplayCheckpointFile::open(
        original.plan.replay_checkpoint.clone(),
        &original.plan.identity,
    )?;
    anyhow::ensure!(
        checkpoint.digest == frontier,
        "retired original replay database and existing independent checkpoint differ"
    );
    original.daemon.require_dead()?;
    original.root.require_dead()?;
    Ok(frontier)
}

fn reserve_original_model_witness(path: &std::path::Path) -> anyhow::Result<tempfile::TempDir> {
    let mountpoint = PathBuf::from(
        std::env::var_os("HEPTA_Q24_FACTORY_WITNESS_BIND")
            .ok_or_else(|| anyhow::anyhow!("actual registered model witness bind required"))?,
    );
    let source_path = PathBuf::from(
        std::env::var_os("HEPTA_Q24_FACTORY_WITNESS_SOURCE")
            .ok_or_else(|| anyhow::anyhow!("actual model witness bind source required"))?,
    );
    let metadata = std::fs::metadata(&mountpoint)?;
    let witness_bind = crate::HostAuthorityBindIdentity {
        mountpoint: mountpoint.clone(),
        source_path,
        device: metadata.dev(),
        inode: metadata.ino(),
    };
    witness_bind.verify()?;
    let directory = tempfile::Builder::new()
        .prefix("ordinary-post-a-model-")
        .tempdir_in(&mountpoint)?;
    super::super::owned_mode(directory.path(), 0, 0, 0o700)?;
    super::root::write_json(
        path,
        &crate::HostAuthorityQ24ModelFactoryReservationV1 {
            schema_version: 1,
            witness_bind,
            witness_directory: directory.path().to_path_buf(),
            local_policy_digest: crate::CellQ24LocalPolicyV1::AdoptQualified
                .digest()
                .to_string(),
        },
    )?;
    Ok(directory)
}
