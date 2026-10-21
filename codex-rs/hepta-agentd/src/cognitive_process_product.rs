//! Restart replay through the original sealed product-evaluation pipeline.
//! Only an already recorded exact plan and fence can be replayed here. A
//! descriptor cannot consume a new holdout or decode an opaque qualification.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::path::PathBuf;

use codex_hepta_intelligence_eval as eval;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::cognitive_process_bootstrap::FileAccess;
use super::cognitive_process_bootstrap::invalid;
use super::cognitive_process_bootstrap::open_bounded_regular;
use super::cognitive_process_product_wire::*;
use super::cognitive_process_wire::Digest;
use crate::AgentdError;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PinnedProductFileV1 {
    pub path: PathBuf,
    pub digest: Digest,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ProductReplayDescriptorV1 {
    pub candidate_plan: TemporalEvaluationPlanRaw,
    pub baseline_plan: TemporalEvaluationPlanRaw,
    pub metric_sources: Vec<ProductMetricSourceContractV1Raw>,
    pub context: ProductQualificationContextV1Raw,
    pub released_inputs: PinnedProductFileV1,
    pub holdout_material: PinnedProductFileV1,
    pub qualification_evidence: PinnedProductFileV1,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct FencedHoldoutDescriptorV1 {
    pub path: PathBuf,
    pub binding: Digest,
    pub fence: HoldoutWriterFenceV1Raw,
    pub anchor: FinalHoldoutCasAnchorV1Raw,
}

#[allow(clippy::too_many_arguments)]
pub(super) fn replay_product_qualification_v1(
    descriptor: ProductReplayDescriptorV1,
    holdout_descriptor: FencedHoldoutDescriptorV1,
    holdout_file: File,
    plan: eval::CrossFoldPlanV1,
    metric_roles: Vec<eval::MetricRoleContractV2>,
    evidence: &eval::SignedEvaluationEvidenceV1,
    timing: &eval::LongitudinalTimeEvidenceV1,
    minimum_window_micros: u64,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<
    (
        eval::IndependentEvaluationBundleV1,
        eval::ProductQualificationReceiptV1,
    ),
    AgentdError,
> {
    let candidate_plan = descriptor.candidate_plan.into();
    let baseline_plan = descriptor.baseline_plan.into();
    let product_plan = eval::freeze_product_evaluation_plan_v1(
        plan,
        metric_roles,
        descriptor
            .metric_sources
            .into_iter()
            .map(Into::into)
            .collect(),
        &candidate_plan,
        &baseline_plan,
    )
    .map_err(|error| invalid(&format!("cognitive product plan: {error}")))?;
    let anchor: eval::FinalHoldoutCasAnchorV1 = holdout_descriptor.anchor.into();
    let fence: eval::HoldoutWriterFenceV1 = holdout_descriptor.fence.into();
    let binding = holdout_descriptor.binding.into();
    if anchor.record_count == 0 || anchor.state_digest.is_zero() {
        return Err(invalid(
            "cognitive product requires a nonempty acknowledged holdout",
        ));
    }
    let mut store =
        eval::LockedFileFinalHoldoutCasStoreV1::recover(holdout_file, binding, Some(anchor))
            .map_err(|error| invalid(&format!("cognitive product holdout recovery: {error}")))?;
    if store.anchor() != Some(anchor) {
        return Err(invalid(
            "cognitive product holdout has an unwitnessed later tail",
        ));
    }
    let record = store
        .load(binding)
        .map_err(|error| invalid(&format!("cognitive product holdout state: {error}")))?
        .ok_or_else(|| invalid("missing cognitive product holdout state"))?;
    if record.fence != fence
        || !record
            .journal
            .records
            .iter()
            .any(|record| record.plan == product_plan.frozen_plan)
    {
        return Err(invalid(
            "cognitive bootstrap may only replay an exact recorded plan and fence",
        ));
    }
    let parent = holdout_descriptor
        .path
        .parent()
        .ok_or_else(|| invalid("cognitive product holdout has no parent"))?;
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(0x20000 | 0x800);
    }
    #[cfg(target_os = "macos")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(0x100 | 0x4);
    }
    let parent_file = options.open(parent)?;
    let opened_parent = parent_file.metadata()?;
    if !opened_parent.is_dir() || parent.canonicalize()? != parent {
        return Err(invalid("cognitive product holdout parent changed"));
    }
    parent_file.sync_all()?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let named_parent = std::fs::symlink_metadata(parent)?;
        if !named_parent.is_dir()
            || (opened_parent.dev(), opened_parent.ino())
                != (named_parent.dev(), named_parent.ino())
        {
            return Err(invalid("cognitive product holdout parent identity changed"));
        }
    }
    let owner = eval::FencedFinalHoldoutOwnerV1::recover(store, binding, fence)
        .map_err(|error| invalid(&format!("cognitive product owner: {error}")))?;
    let pinned = eval::read_product_qualification_evidence_v1(
        &descriptor.qualification_evidence.path,
        descriptor.qualification_evidence.digest.0,
    )
    .map_err(|error| invalid(&format!("cognitive qualification evidence: {error}")))?;
    let mut provider = PinnedReplayProviderV1 {
        material: descriptor.holdout_material,
        inputs: descriptor.released_inputs,
        expected_plan_digest: product_plan.frozen_plan.plan_digest,
        released: false,
    };
    let mut runner = eval::ProductEvaluationRunnerV1::new(owner);
    let temporal = runner
        .evaluate_temporal_comparison(
            &product_plan,
            &candidate_plan,
            &baseline_plan,
            &mut provider,
        )
        .map_err(|error| invalid(&format!("cognitive product evaluation replay: {error}")))?;
    if runner.holdout_anchor() != anchor || temporal.execution_digest != pinned.execution_digest() {
        return Err(invalid(
            "cognitive product replay changed recorded evaluation",
        ));
    }
    let context = descriptor.context.into();
    let bundle = runner
        .qualification_bundle(&temporal, &context)
        .map_err(|error| invalid(&format!("cognitive product bundle: {error}")))?;
    let mut sink =
        eval::FileProductQualificationEvidenceSinkV1::new(&descriptor.qualification_evidence.path)
            .map_err(|error| invalid(&format!("cognitive qualification sink: {error}")))?;
    let receipt = runner
        .qualify_and_persist(
            &temporal,
            &context,
            evidence,
            eval::ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros,
            },
            verifier,
            now,
            &mut sink,
        )
        .map_err(|error| invalid(&format!("cognitive product qualification replay: {error}")))?;
    if receipt.publication_digest != pinned.publication_digest()
        || &receipt.decision != pinned.decision()
    {
        return Err(invalid(
            "cognitive product replay differs from pinned durable qualification",
        ));
    }
    Ok((bundle, receipt))
}

struct PinnedReplayProviderV1 {
    material: PinnedProductFileV1,
    inputs: PinnedProductFileV1,
    expected_plan_digest: Digest32,
    released: bool,
}

impl eval::FinalHoldoutProviderV1 for PinnedReplayProviderV1 {
    fn manifest_digest(&mut self) -> Result<Digest32, eval::ProductProviderErrorV1> {
        read_pinned(&self.material, 4 * 1024 * 1024)?;
        Ok(self.material.digest.0)
    }

    fn release_after_consumption(
        &mut self,
        receipt: &eval::FinalHoldoutJournalReceiptV1,
    ) -> Result<eval::TemporalComparisonInputsV1, eval::ProductProviderErrorV1> {
        if self.released
            || receipt.disposition != eval::HoldoutUseDispositionV1::IdempotentReplay
            || receipt.use_receipt.plan_digest != self.expected_plan_digest
            || receipt.authority.grants_any()
        {
            return Err(eval::ProductProviderErrorV1::Rejected);
        }
        self.released = true;
        let bytes = read_pinned(&self.inputs, 32 * 1024 * 1024)?;
        let inputs: TemporalComparisonInputsV1Raw =
            serde_json::from_slice(&bytes).map_err(|_| eval::ProductProviderErrorV1::Rejected)?;
        Ok(inputs.into())
    }
}

fn read_pinned(
    input: &PinnedProductFileV1,
    maximum: u64,
) -> Result<Vec<u8>, eval::ProductProviderErrorV1> {
    let file = open_bounded_regular(&input.path, maximum, FileAccess::Read)
        .map_err(|_| eval::ProductProviderErrorV1::Unavailable)?;
    let mut bytes = Vec::new();
    file.take(maximum + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| eval::ProductProviderErrorV1::Unavailable)?;
    if bytes.len() as u64 > maximum
        || input.digest.0.is_zero()
        || Digest32::of_bytes(&bytes) != input.digest.0
    {
        return Err(eval::ProductProviderErrorV1::Rejected);
    }
    Ok(bytes)
}
