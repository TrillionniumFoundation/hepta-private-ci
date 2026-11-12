//! Fixed Root-only post-A configuration, retained before the freeze is used.
//! It contains original file identities and the training policy, never peer
//! projected rows, a prepared batch digest, private signer or update authority.

use std::fs::File;
use std::io;
use std::os::fd::OwnedFd;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;

use super::super::generation_publication::deployment::files::MetadataFile;
use super::super::generation_publication::deployment::post_a::OriginalPostAPublicationDeployment;
use super::super::generation_publication::deployment::post_a::OriginalPostAPublicationFiles;
use super::super::generation_publication::prepare_original_publication_route;
use super::learning_trust::RootHistoricalLearningTrustV1;
use super::post_a_files::PostABaselineData;
use super::post_a_files::PostABaselineFiles;
use super::post_a_freeze::PostAFreezeData;
use super::post_a_freeze::PostAFreezeFiles;
use super::require_end;
use crate::CellQ24DatasetProjectionV1;
use crate::CellQ24PrivateHeadV1;
use crate::CellQ24SgdRuleV1;
use crate::HostAuthorityQ24ModelFactoryReservationV1;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityService;
use crate::HostAuthorityServiceConfig;
use crate::RootQ24ModelFactoryOfferV1;
use crate::authority_host_runtime::OriginalRootIndependentBEvaluationFilesV1;
use crate::authority_host_runtime::PreparedRootIndependentBEvaluationV1;
use crate::authority_host_service::OriginalDerivedLearningMode;
use crate::authority_host_service::RegisteredHostLearningCheckpointV1;
use crate::authority_host_service::generation_initial::historical_source_pin::RootOriginalHistoricalCompleteTaskObservationV1;
use crate::authority_host_service::generation_initial::original_root;
use crate::authority_host_service::generation_publication::PublicationVersion;

#[path = "authority_host_post_a_derive.rs"]
mod derive;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PostALearningDeploymentData {
    schema: u8,
    purpose: String,
    initial: String,
    target: String,
    learning_trust_mapping: String,
    mode: String,
    baseline: PostABaselineData,
    freeze: PostAFreezeData,
    model_reservation: PathBuf,
    snapshot_id: String,
    head: String,
    index: u16,
    epochs: u16,
    learning_rate_q24: i64,
    input_width: u16,
    inherited_inclusion_policy: [u8; 32],
    unit_profile: [u8; 32],
    maximum_signature_lifetime_seconds: u64,
}

struct PostALearningPlan {
    snapshot_id: StableId,
    head: CellQ24PrivateHeadV1,
    rule: CellQ24SgdRuleV1,
    projection: CellQ24DatasetProjectionV1,
    maximum_signature_lifetime_seconds: u64,
}

pub(super) struct PostALearningRuntime {
    metadata: MetadataFile,
    reservation_metadata: MetadataFile,
    reservation_path: PathBuf,
    reservation: HostAuthorityQ24ModelFactoryReservationV1,
    initial: LearningIterationSnapshotV1,
    target: String,
    learning_trust_mapping: String,
    register: bool,
    baseline: PostABaselineFiles,
    freeze: PostAFreezeFiles,
    publication: Option<Arc<OriginalPostAPublicationFiles>>,
    independent_evaluation_path: Option<PathBuf>,
    plan: PostALearningPlan,
}

/// Original owners and sealed rights produced by this Root service. Only the
/// enclosing physical historical read may release them to the one-shot worker.
pub(super) struct PostALearningInstallation {
    pub(super) learning: RegisteredHostLearningCheckpointV1,
    pub(super) learning_bootstrap: File,
    pub(super) model_offer: RootQ24ModelFactoryOfferV1,
    pub(super) publication: Option<super::super::generation_publication::PublicationRuntime>,
    pub(super) publication_offer: Option<crate::RootGenerationPublicationOfferV1>,
    pub(super) publication_deployment: Option<OriginalPostAPublicationDeployment>,
    pub(super) frozen_scope: String,
    pub(super) independent_b: Option<PreparedRootIndependentBEvaluationV1>,
}

impl PostALearningRuntime {
    pub(super) fn prepare_original_installation(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        proof: &str,
        initial: &LearningIterationSnapshotV1,
        observed: &RootOriginalHistoricalCompleteTaskObservationV1,
        trust: &RootHistoricalLearningTrustV1,
        end: Instant,
        session_end: Instant,
    ) -> io::Result<PostALearningInstallation> {
        original_root()?;
        if end > session_end {
            return Err(io::Error::other(
                "original post-A request exceeds its session",
            ));
        }
        let identity = registration.registered_identity.identity()?;
        self.with_original_derived_profile(
            service,
            &identity,
            proof,
            initial,
            observed,
            trust,
            end,
            |profile| {
                require_end(end)?;
                let frozen_scope = profile.require_cell_scope(initial)?.binding().to_string();
                let mut learning = service.prepare_original_derived_learning_checkpoint(
                    config,
                    registration,
                    owner,
                    profile,
                    self.original_mode(),
                    end,
                )?;
                if self.register {
                    service.reserve_q24_model_factory_v2_for_profile(
                        config,
                        registration,
                        owner,
                        &learning.profile,
                        &self.reservation,
                        end,
                    )?;
                }
                require_end(end)?;
                let factory = service.open_q24_model_factory_v2(
                    config,
                    registration,
                    owner,
                    &learning.profile,
                    &self.reservation_path,
                    end,
                )?;
                learning.q24_model = Some(factory);
                let independent_b = match &self.independent_evaluation_path {
                    Some(path) => {
                        let files = if self.register {
                            OriginalRootIndependentBEvaluationFilesV1::register_original_b(
                                path,
                                initial,
                                service,
                                config,
                                registration,
                                owner,
                                &learning,
                                end,
                                session_end,
                            )?
                        } else {
                            OriginalRootIndependentBEvaluationFilesV1::reopen_original_b(
                                path,
                                initial,
                                service,
                                config,
                                registration,
                                owner,
                                &learning,
                                end,
                                session_end,
                            )?
                        };
                        let prepared =
                            OriginalRootIndependentBEvaluationFilesV1::prepare_original_b(
                                &files,
                                service,
                                config,
                                registration,
                                owner,
                                &learning,
                                end,
                            )?;
                        RegisteredHostLearningCheckpointV1::attach_original_model_b(
                            &mut learning,
                            PreparedRootIndependentBEvaluationV1::original_custodian(&prepared),
                        )?;
                        Some(prepared)
                    }
                    None => None,
                };
                let learning_bootstrap =
                    service.seal_learning_checkpoint(config, registration, owner, &learning)?;
                let model_offer = service.seal_q24_model_factory_offer(
                    config,
                    registration,
                    owner,
                    learning
                        .q24_model
                        .as_mut()
                        .ok_or_else(|| io::Error::other("original post-A Model factory missing"))?,
                )?;
                let (publication, publication_offer, publication_deployment) =
                    match &self.publication {
                        Some(files) => {
                            let (runtime, capability, offer) = prepare_original_publication_route(
                                service,
                                config,
                                registration,
                                owner,
                                &learning,
                                Some(session_end),
                                PublicationVersion::DurableV2,
                                Some(OriginalPostAPublicationFiles::original_preparation_data(
                                    files,
                                )?),
                            )?;
                            let deployment = OriginalPostAPublicationFiles::attach_original_route(
                                files, initial, capability,
                            )?;
                            (Some(runtime), Some(offer), Some(deployment))
                        }
                        None => (None, None, None),
                    };
                self.require_original_metadata()?;
                require_end(end)?;
                Ok(PostALearningInstallation {
                    learning,
                    learning_bootstrap,
                    model_offer,
                    publication,
                    publication_offer,
                    publication_deployment,
                    frozen_scope,
                    independent_b,
                })
            },
        )
    }

    pub(super) fn retain_original_plan(
        path: &Path,
        initial: &LearningIterationSnapshotV1,
        target: &CellGenerationOwnerBindingV1,
        peer_uid: u32,
        peer_gid: u32,
        publication_path: Option<&Path>,
        independent_evaluation_path: Option<&Path>,
    ) -> io::Result<Self> {
        original_root()?;
        let (metadata, bytes) = MetadataFile::open_metadata(path)?;
        let data: PostALearningDeploymentData =
            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        let actual_target = Digest32::from_array(target.digest().map_err(io::Error::other)?);
        if data.schema != 1
            || data.purpose != "runtime.learning.post-a-deployment.v1"
            || data.initial != initial.head_digest.to_string()
            || !initial.receipts.is_empty()
            || data.target != actual_target.to_string()
            || !(1..=86_400).contains(&data.maximum_signature_lifetime_seconds)
            || !(1..=256).contains(&data.epochs)
            || !(1..=(1 << 24)).contains(&data.learning_rate_q24)
        {
            return Err(io::Error::other(
                "original post-A recipient and bounded policy required",
            ));
        }
        let mapping: Digest32 = data
            .learning_trust_mapping
            .parse()
            .map_err(io::Error::other)?;
        if mapping.is_zero() || mapping.to_string() != data.learning_trust_mapping {
            return Err(io::Error::other(
                "fixed current recipient trust mapping required",
            ));
        }
        let register = match data.mode.as_str() {
            "register" => true,
            "reopen" => false,
            _ => {
                return Err(io::Error::other(
                    "explicit original registration mode required",
                ));
            }
        };
        let head = match data.head.as_str() {
            "drive" => CellQ24PrivateHeadV1::Drive { index: data.index },
            "prediction" => CellQ24PrivateHeadV1::Prediction { index: data.index },
            _ => return Err(io::Error::other("one fixed original Q24 head required")),
        };
        let projection = CellQ24DatasetProjectionV1 {
            inherited_inclusion_policy: Digest32::from_array(data.inherited_inclusion_policy),
            unit_profile_digest: Digest32::from_array(data.unit_profile),
            baseline_bundle: initial
                .request
                .selected_bundle
                .digest()
                .map_err(io::Error::other)?,
            input_width: data.input_width,
        };
        projection
            .inclusion_policy_digest()
            .map_err(io::Error::other)?;
        let baseline = PostABaselineFiles::retain_original_baseline(data.baseline)?;
        let freeze = PostAFreezeFiles::retain_original_freeze(
            data.freeze,
            initial.request.envelope.objective_digest,
            peer_uid,
            peer_gid,
        )?;
        let (reservation_metadata, bytes) = MetadataFile::open_metadata(&data.model_reservation)?;
        let reservation: HostAuthorityQ24ModelFactoryReservationV1 =
            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        let publication = publication_path
            .map(|path| {
                OriginalPostAPublicationFiles::retain_original_publication(
                    path, initial, peer_uid, peer_gid,
                )
            })
            .transpose()?;
        let held = Self {
            metadata,
            reservation_metadata,
            reservation_path: data.model_reservation,
            reservation,
            initial: initial.clone(),
            target: data.target,
            learning_trust_mapping: data.learning_trust_mapping,
            register,
            baseline,
            freeze,
            publication,
            independent_evaluation_path: independent_evaluation_path.map(Path::to_path_buf),
            plan: PostALearningPlan {
                snapshot_id: StableId::new(data.snapshot_id).map_err(io::Error::other)?,
                head,
                rule: CellQ24SgdRuleV1 {
                    epochs: data.epochs,
                    learning_rate_q24: data.learning_rate_q24,
                },
                projection,
                maximum_signature_lifetime_seconds: data.maximum_signature_lifetime_seconds,
            },
        };
        held.require_original_metadata()?;
        Ok(held)
    }

    fn require_original_metadata(&self) -> io::Result<()> {
        original_root()?;
        self.metadata.require_metadata_unchanged()?;
        self.reservation_metadata.require_metadata_unchanged()
    }

    fn original_mode(&self) -> OriginalDerivedLearningMode {
        if self.register {
            OriginalDerivedLearningMode::Register
        } else {
            OriginalDerivedLearningMode::Reopen
        }
    }
}
