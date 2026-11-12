//! Root fixes the original empty completion files before post-A work. Cold
//! readers change only the explicit read phase; they cannot initialize a fact,
//! select other files or reopen any original learning writer.

use codex_hepta_types::Digest32;
use serde::Serialize;

use super::completed_files::CompletedFiles;
use super::completed_files::CompletedFilesData;
use super::*;
use crate::authority_host_service::generation_initial::RootCompletedLearningRefusalV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum CompletedMode {
    Accept,
    CaptureRetired,
    ReadFinalized,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CompletedLearningDeployment {
    schema: u8,
    purpose: String,
    initial: String,
    target: String,
    pub(super) mode: CompletedMode,
    pub(super) original_post_a_deployment: String,
    pub(super) independent_b: PathBuf,
    pub(super) publication: PathBuf,
    pub(super) files: CompletedFilesData,
}

pub(super) struct CompletedLearningRuntime {
    metadata: MetadataFile,
    pub(super) data: CompletedLearningDeployment,
    pub(super) binding: Digest32,
    pub(super) original: Option<(RootCompletedLearningRefusalV1, CompletedFiles)>,
    pub(super) completion_phase: AtomicU8,
}

impl CompletedLearningRuntime {
    pub(super) fn retain_original(
        path: &Path,
        historical: &HistoricalTaskReadRuntime,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
    ) -> io::Result<Self> {
        original_root()?;
        let (metadata, bytes) = MetadataFile::open_metadata(path)?;
        let data: CompletedLearningDeployment =
            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        let initial = historical.deployment.initial.original_initial_data()?;
        let target = Digest32::from_array(
            historical
                .deployment
                .target
                .digest()
                .map_err(io::Error::other)?,
        );
        if data.schema != 1
            || data.purpose != "runtime.learning.completed-deployment.v1"
            || data.initial != initial.head_digest.to_string()
            || data.target != target.to_string()
            || !initial.receipts.is_empty()
        {
            return Err(io::Error::other(
                "original completed-learning deployment differs",
            ));
        }
        let plan: Digest32 = data
            .original_post_a_deployment
            .parse()
            .map_err(io::Error::other)?;
        if plan.is_zero() || plan.to_string() != data.original_post_a_deployment {
            return Err(io::Error::other(
                "original post-A deployment digest required",
            ));
        }
        let binding = Digest32::of_parts(&[
            b"hepta.root.completed-learning.deployment.v1\0",
            &serde_json::to_vec(&(
                &data.initial,
                &data.target,
                &data.original_post_a_deployment,
                &data.independent_b,
                &data.publication,
                &data.files,
            ))
            .map_err(io::Error::other)?,
        ]);
        let original = if data.mode == CompletedMode::Accept {
            Some(RootCompletedLearningRefusalV1::retain_fresh(
                RootAuthorityDirectory::open(&config.state_dir).map_err(io::Error::other)?,
                &historical.deployment.target,
                initial.head_digest,
                || {
                    let files = service.with_learning_profile(
                        config,
                        registration,
                        owner,
                        &historical.deployment.initial,
                        |observed, proof| {
                            metadata.require_metadata_unchanged()?;
                            historical.metadata.require_metadata_unchanged()?;
                            if observed != initial
                                || historical.phase.load(Ordering::Acquire) != PREPARED
                                || historical.profile.require_original_context(
                                    &registration.registered_identity.identity()?,
                                    &proof,
                                    &historical.deployment.initial,
                                )? != initial
                            {
                                return Err(io::Error::other("fresh completion recipient differs"));
                            }
                            RootHistoricalLearningTrustV1::revalidate(
                                &historical.learning_trust,
                                service,
                                &initial,
                            )?;
                            let files = CompletedFiles::retain_original(
                                data.files.clone(),
                                initial.request.envelope.objective_digest,
                            )?;
                            CompletedFiles::require_empty(&files)?;
                            metadata.require_metadata_unchanged()?;
                            RootHistoricalLearningTrustV1::revalidate(
                                &historical.learning_trust,
                                service,
                                &initial,
                            )?;
                            Ok(files)
                        },
                    )?;
                    // The whole real Root context has returned before Ready.
                    CompletedFiles::require_empty(&files)?;
                    metadata.require_metadata_unchanged()?;
                    historical.metadata.require_metadata_unchanged()?;
                    Ok(files)
                },
            )?)
        } else {
            // No original file or fact is opened until a later existing Arm.
            None
        };
        metadata.require_metadata_unchanged()?;
        Ok(Self {
            metadata,
            data,
            binding,
            original,
            completion_phase: AtomicU8::new(0),
        })
    }

    pub(super) fn require_original(&self) -> io::Result<()> {
        self.metadata.require_metadata_unchanged()
    }

    pub(super) fn is_fresh(&self) -> bool {
        self.data.mode == CompletedMode::Accept && self.original.is_some()
    }
}
