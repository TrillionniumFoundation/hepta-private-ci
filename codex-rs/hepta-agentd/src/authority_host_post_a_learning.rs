//! Fixed Root-only post-A configuration, retained before the freeze is used.
//! It contains original file identities and the training policy, never peer
//! projected rows, a prepared batch digest, private signer or update authority.

use std::io;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;

use super::super::generation_publication::deployment::files::MetadataFile;
use super::post_a_files::PostABaselineData;
use super::post_a_files::PostABaselineFiles;
use super::post_a_freeze::PostAFreezeData;
use super::post_a_freeze::PostAFreezeFiles;
use crate::CellQ24DatasetProjectionV1;
use crate::CellQ24PrivateHeadV1;
use crate::CellQ24SgdRuleV1;
use crate::HostAuthorityQ24ModelFactoryReservationV1;
use crate::authority_host_service::OriginalDerivedLearningMode;
use crate::authority_host_service::generation_initial::original_root;

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
    plan: PostALearningPlan,
}

impl PostALearningRuntime {
    pub(super) fn retain_original_plan(
        path: &Path,
        initial: &LearningIterationSnapshotV1,
        target: &CellGenerationOwnerBindingV1,
        peer_uid: u32,
        peer_gid: u32,
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
