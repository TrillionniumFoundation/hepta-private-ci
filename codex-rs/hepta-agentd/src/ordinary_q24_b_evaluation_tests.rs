//! Real independent Evaluate inputs for the ordinary process fixture. Setup
//! creates original input data only; Root consumes the heldout, performs native
//! evaluation and signs the result. No completed evaluation is fabricated here.
#![cfg(test)]

use std::io;
use std::path::PathBuf;

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::post_a_plan::OriginalPostAPlan;
use super::post_a_plan::OriginalPostAResources;
use super::post_a_trust::B_OBSERVER;
use super::post_a_trust::TRAINER;

#[path = "ordinary_q24_b_evaluation_business_tests.rs"]
mod business;
#[path = "ordinary_q24_b_evaluation_data_tests.rs"]
mod data;
#[path = "ordinary_q24_b_evaluation_files_tests.rs"]
mod files;
#[path = "ordinary_q24_b_evaluation_fixed_tests.rs"]
mod fixed;
#[path = "ordinary_q24_b_evaluation_producer_tests.rs"]
mod producer;
#[path = "ordinary_q24_b_evaluation_protocol_tests.rs"]
mod protocol;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum OriginalBusinessCase {
    Adopt,
    EvaluatedNoUpdate,
}

pub(super) struct OriginalIndependentBEvaluationInputs {
    case: OriginalBusinessCase,
    objective: [u8; 32],
    unit_profile: [u8; 32],
    baseline_bundle: [u8; 32],
    baseline: data::BaselineBytes,
    input: Vec<u8>,
    training: Vec<data::TrainingRow>,
    cohort: Vec<data::CohortRow>,
    protocol: protocol::OriginalProtocol,
    files: files::OriginalFiles,
    business_directory: tempfile::TempDir,
}

impl OriginalIndependentBEvaluationInputs {
    pub(super) fn prepare(
        resources: &OriginalPostAResources,
        case: OriginalBusinessCase,
    ) -> anyhow::Result<Self> {
        let original = &resources.original;
        let source = crate::OriginalSingleQ24SourceConfigurationV1::from_original_deployment_bytes(
            &super::observer::read_private(&original.plan.root.source, 65_536)?,
            &original.plan.identity,
        )?;
        let model_directory = original.plan.runtime.path().join("model");
        let (_, bundle, _) = super::super::material::load(&model_directory)?;
        let baseline = data::BaselineBytes {
            base: std::fs::read(model_directory.join("base"))?,
            encoder: std::fs::read(model_directory.join("encoder"))?,
            heads: std::fs::read(model_directory.join("heads"))?,
        };
        let initial: serde_json::Value = serde_json::from_slice(&super::observer::read_private(
            &original.plan.root.initial,
            65_536,
        )?)?;
        let observer: crate::authority_host_runtime::publication_data::ObserverData =
            serde_json::from_value(initial["target"].clone())?;
        let directory = original.plan.protected.path().join("independent-b");
        std::fs::create_dir(&directory)?;
        super::super::owned_mode(&directory, 0, 0, 0o700)?;
        let business_directory = tempfile::Builder::new()
            .prefix("ordinary-original-independent-b-")
            .tempdir()?;
        super::super::owned_mode(business_directory.path(), 60002, 60001, 0o700)?;
        let training = business::prepare_training(business_directory.path(), case, resources.end)?;
        for file in std::fs::read_dir(business_directory.path())? {
            super::super::owned_mode(&file?.path(), 60002, 60001, 0o600)?;
        }
        let cohort = data::cohort();
        let objective = source.source.objective_digest.into_array();
        let unit_profile = Digest32::of_parts(&[
            b"original-independent-b-binary-file-contract-v1\0",
            &serde_json::to_vec(&case)?,
        ])
        .into_array();
        let control = fixed::execute(
            &model_directory,
            &directory,
            &source.source.observation,
            observer.generation.manifest.evolution.structure,
            resources.end,
        )?;
        let protocol = protocol::prepare(
            objective,
            unit_profile,
            &source.source.observation,
            &training,
            &cohort,
            control,
            &directory,
            resources.end,
        )?;
        let files = files::OriginalFiles::reserve(
            resources,
            &protocol,
            &baseline,
            &source.source.observation,
            observer.generation,
            directory,
        )?;
        Ok(Self {
            case,
            objective,
            unit_profile,
            baseline_bundle: bundle.digest()?.into_array(),
            baseline,
            input: source.source.observation,
            training,
            cohort,
            protocol,
            files,
            business_directory,
        })
    }

    pub(super) fn protocol_digest(&self) -> Digest32 {
        self.protocol.digest
    }

    pub(super) fn write_deployment(
        &self,
        plan: &OriginalPostAPlan,
        actual_source_peer: CognitiveCheckpointPeerLifetime,
    ) -> anyhow::Result<PathBuf> {
        anyhow::ensure!(
            plan.profile
                .original_initial_data()?
                .request
                .evaluation_profile
                == self.protocol.digest,
            "actual original Root protocol pin differs"
        );
        self.files.write_deployment(plan, actual_source_peer)
    }

    pub(super) fn producer_json(
        &self,
        plan: &OriginalPostAPlan,
    ) -> anyhow::Result<serde_json::Value> {
        let initial = plan.profile.original_initial_data()?;
        anyhow::ensure!(
            initial.request.evaluation_profile == self.protocol.digest
                && initial.request.envelope.objective_digest.into_array() == self.objective
                && initial.request.selected_bundle.digest()?.into_array() == self.baseline_bundle,
            "original independent producer and actual Root profile differ"
        );
        let data = data::ProducerData {
            schema: 1,
            case: self.case,
            initial: initial.head_digest.into_array(),
            objective: self.objective,
            unit_profile: self.unit_profile,
            protocol: self.protocol.digest.into_array(),
            baseline_bundle: self.baseline_bundle,
            baseline: self.baseline.clone(),
            input: self.input.clone(),
            training: self.training.clone(),
            cohort: self.cohort.clone(),
            training_watermark: self.protocol.training_watermark,
            evaluation_start: self.protocol.evaluation_start,
            outcome_watermark: self.protocol.outcome_watermark,
            expires_at_seconds: initial.request.envelope.expiry_unix_seconds,
            business_directory: self.business_directory.path().to_path_buf(),
            trust: plan.resources.trust.payload.clone(),
            generator_key: files::read_original_key(plan.resources.trust.key(TRAINER)?)?,
            observer_key: files::read_original_key(plan.resources.trust.key(B_OBSERVER)?)?,
        };
        Ok(serde_json::to_value(data)?)
    }

    pub(super) fn business_files(&self) -> Vec<PathBuf> {
        self.files.business_files()
    }

    pub(super) fn preserve_original_business_directory(self) -> PathBuf {
        self.business_directory.keep()
    }
}

pub(super) fn produce(
    value: &serde_json::Value,
    candidate: &crate::OriginalRootBCandidateDataV1,
) -> io::Result<crate::OriginalBSourceSignedDataV1> {
    producer::produce(value, candidate)
}
