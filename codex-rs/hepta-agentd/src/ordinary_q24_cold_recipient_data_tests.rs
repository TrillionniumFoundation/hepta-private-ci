//! Recompute the new recipient's sealed-profile DATA from the exact original
//! Root metadata. This observer opens no writer and constructs no capability.

use std::path::PathBuf;

use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use super::cold_deployment::OriginalColdPlan;
use super::observer::read_private;
use crate::ordinary_q24_cold_snapshot_tests::OriginalBusinessSnapshot;
use crate::root_historical_learning_trust_data::HistoricalLearningTrustPayloadV1;
use crate::root_historical_learning_trust_data::HistoricalLearningTrustPinV1;
use crate::root_historical_task_read_protocol::HistoricalTaskReadProfileV1;
use crate::root_historical_task_read_protocol::PURPOSE;
use crate::root_initial_learning_trust_data::LearningTrustPayloadV1;
use crate::root_initial_learning_trust_data::LearningTrustRoleSelectionV1;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TrustMapping {
    schema: u8,
    purpose: String,
    mode: String,
    initial: String,
    target: CellGenerationOwnerBindingV1,
    learning_scope: String,
    signed_payload: PathBuf,
    freeze_evaluator: LearningTrustRoleSelectionV1,
}

pub(super) struct OriginalColdRecipientData {
    pub(super) profile: HistoricalTaskReadProfileV1,
    files: Vec<PathBuf>,
    unchanged: OriginalBusinessSnapshot,
}

impl OriginalColdRecipientData {
    pub(super) fn observe(plan: &OriginalColdPlan<'_>) -> anyhow::Result<Self> {
        let initial = plan.profile.original_initial_data()?;
        let metadata_pin = OriginalBusinessSnapshot::capture(&[plan.historical.clone()])?;
        let metadata_bytes = read_private(&plan.historical, /*bound*/ 65_536)?;
        let metadata: serde_json::Value = serde_json::from_slice(&metadata_bytes)?;
        anyhow::ensure!(
            metadata["schema_version"] == 1
                && metadata["purpose"] == "runtime.learning.historical-task-deployment.v1"
                && metadata["initial"] == serde_json::to_value(&plan.profile)?
                && metadata["target"]
                    == serde_json::to_value(
                        &plan.original.plan.resources.original.plan.deployment.target
                    )?,
            "actual new Root historical metadata differs"
        );
        let mapping_path = PathBuf::from(
            metadata["learning_trust_deployment"]
                .as_str()
                .ok_or_else(|| anyhow::anyhow!("original recipient trust mapping absent"))?,
        );
        let mapping_pin = OriginalBusinessSnapshot::capture(&[mapping_path.clone()])?;
        let mapping_bytes = read_private(&mapping_path, /*bound*/ 65_536)?;
        let mapping: TrustMapping = serde_json::from_slice(&mapping_bytes)?;
        let files = vec![
            plan.historical.clone(),
            mapping_path.clone(),
            mapping.signed_payload.clone(),
        ];
        let unchanged = OriginalBusinessSnapshot::capture(&files)?;
        metadata_pin.require_unchanged(&[plan.historical.clone()])?;
        mapping_pin.require_unchanged(&[mapping_path.clone()])?;
        let result = (|| {
            anyhow::ensure!(
                mapping.schema == 1
                    && mapping.purpose == "runtime.learning.historical-trust-deployment.v1"
                    && mapping.mode == "pinned_genesis_v1"
                    && mapping.initial == initial.head_digest.to_string()
                    && mapping.target
                        == plan.original.plan.resources.original.plan.deployment.target
                    && mapping.signed_payload == plan.original.plan.resources.trust.payload_file
                    && mapping.freeze_evaluator == plan.original.plan.resources.trust.freezer,
                "original fixed recipient trust metadata differs"
            );
            let signed_bytes = read_private(&mapping.signed_payload, /*bound*/ 65_536)?;
            let signed: LearningTrustPayloadV1 = serde_json::from_slice(&signed_bytes)?;
            anyhow::ensure!(
                signed == plan.original.plan.resources.trust.payload,
                "cold substituted the original public trust distribution"
            );
            let payload = HistoricalLearningTrustPayloadV1 {
                signed,
                freeze_evaluator: mapping.freeze_evaluator,
            };
            // Current public trust is checked at today's actual clock. No old
            // learning receipt is re-signed or validated at a fabricated time.
            let (activated, _) = payload
                .activate_for_recipient(&initial, crate::authbus_ingress::now_ms()? / 1_000)?;
            let pin = HistoricalLearningTrustPinV1 {
                initial: initial.head_digest.to_string(),
                target: Digest32::from_array(mapping.target.digest()?).to_string(),
                mapping: Digest32::of_bytes(&mapping_bytes).to_string(),
                payload: Digest32::of_bytes(&signed_bytes).to_string(),
                root: activated.root_digest().to_string(),
                distribution: activated.distribution_digest().to_string(),
                trust: activated.verifier().trust_digest().to_string(),
                learning_scope: activated.verifier().scope_digest().to_string(),
                objective: activated.verifier().objective_digest().to_string(),
                freeze_evaluator: payload.freeze_evaluator_digest()?.to_string(),
            };
            anyhow::ensure!(
                pin.learning_scope == mapping.learning_scope,
                "original trust scope"
            );
            payload.require_activation_pin(&initial, &activated, &pin)?;
            let identity = &plan.administration.successor.identity;
            let mut profile = HistoricalTaskReadProfileV1 {
                purpose: PURPOSE.into(),
                identity: crate::neuron_generation_process_identity_digest_v1(identity)?
                    .to_string(),
                writer: plan
                    .administration
                    .successor
                    .writer_proof
                    .sha256()?
                    .as_str()
                    .into(),
                initial: Digest32::of_parts(&[
                    b"hepta.root.historical-task-read.initial.v1\0",
                    plan.profile.encoded_initial().as_bytes(),
                ])
                .to_string(),
                deployment: Digest32::of_bytes(&metadata_bytes).to_string(),
                learning_trust: pin,
                binding: String::new(),
            };
            profile.binding = profile.digest()?;
            profile.require_original_context(identity, &profile.writer, &plan.profile)?;
            Ok::<_, anyhow::Error>(profile)
        })();
        unchanged.require_unchanged(&files)?;
        metadata_pin.require_unchanged(&[plan.historical.clone()])?;
        mapping_pin.require_unchanged(&[mapping_path])?;
        Ok(Self {
            profile: result?,
            files,
            unchanged,
        })
    }

    pub(super) fn require_unchanged(&self) -> anyhow::Result<()> {
        self.unchanged.require_unchanged(&self.files)
    }
}
