//! The explicit window purpose uses the original full Ledger and receipt codec.
use super::*;
use codex_hepta_agent_components::learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_agent_components::learning_ledger::DatasetWindowFreezePlanV3;
use codex_hepta_agent_components::learning_ledger::DatasetWindowFreezePlanWireV3;
use codex_hepta_agent_components::learning_ledger::DatasetWindowSnapshotReceiptV3;
use codex_hepta_agent_components::learning_ledger::DatasetWindowSnapshotWireV3;
use codex_hepta_agent_components::learning_ledger::LedgerSnapshot;
use codex_hepta_agent_components::learning_ledger::MAX_DATASET_WINDOW_ENCODED_BYTES_V3;
use codex_hepta_agent_components::learning_ledger::MAX_DATASET_WINDOW_SOURCE_RECORDS_V3;
use codex_hepta_agent_components::learning_ledger::MAX_LEDGER_CANONICAL_SOURCE_BYTES_V1;
use codex_hepta_agent_components::learning_ledger::ReviewDatasetWireV1;
use codex_hepta_agent_components::learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_agent_components::learning_ledger::dataset_window_freeze_signing_payload_v3;
use codex_hepta_agent_components::learning_ledger::freeze_dataset_from_ledger;
use codex_hepta_agent_components::learning_ledger::freeze_dataset_window_from_ledger_v3;
use codex_hepta_agent_components::learning_ledger::verify_dataset_snapshot_receipt_v3;

/// The whole original result can be retained once per Round. Decoding does not
/// authenticate a Ledger witness or independent Evaluator signature.
#[derive(serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct PreparedParameterDatasetWindowV3 {
    pub plan: DatasetWindowFreezePlanWireV3,
    pub window: DatasetWindowSnapshotWireV3,
    pub ledger_head_digest: String,
    pub ledger_record_count: u64,
    pub freeze_payload_hex: String,
    pub proposal_registry_predecessor: String,
    pub installed_artifact_head: String,
    pub ledger_binding: String,
    pub maximum_ledger_records: u64,
    pub ledger_source_hex: String,
}
// Only this finite method receives a complete-source response grant. All
// requests and other responses retain their original 64KiB bound.
pub const MAX_PREPARED_DATASET_WINDOW_BYTES_V3: usize = 2 * MAX_LEDGER_CANONICAL_SOURCE_BYTES_V1
    + 2 * MAX_DATASET_WINDOW_SOURCE_RECORDS_V3 as usize * 32
    + 2 * MAX_DATASET_WINDOW_ENCODED_BYTES_V3 as usize
    + 65_536;
pub(crate) const MAX_DATASET_WINDOW_RESPONSE_BYTES_V3: u64 =
    (2 * MAX_PREPARED_DATASET_WINDOW_BYTES_V3 + 8192) as u64;

pub(crate) enum DatasetPlan {
    OriginalV2(DatasetFreezePlanV2),
    WindowV3(DatasetWindowFreezePlanV3),
}
impl DatasetPlan {
    pub(crate) fn objective(&self) -> Digest32 {
        match self {
            Self::OriginalV2(p) => p.objective_digest,
            Self::WindowV3(p) => p.objective_digest,
        }
    }
}
pub(crate) fn read_plan(bytes: &[u8]) -> Result<DatasetPlan, PlasticityRuntimeCallErrorV1> {
    let wire: DatasetWindowFreezePlanWireV3 =
        serde_json::from_slice(bytes).map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
    Ok(DatasetPlan::WindowV3(
        wire.native()
            .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?,
    ))
}
pub(crate) enum Derived {
    OriginalV2(PreparedParameterDatasetV1),
    WindowV3(
        PreparedParameterDatasetWindowV3,
        DatasetWindowSnapshotReceiptV3,
    ),
}
pub(crate) fn derive(
    ledger: &DurableLedger,
    snapshot: &LedgerSnapshot,
    plan: DatasetPlan,
    producer: AuthenticatedPrincipalV1,
    now: u64,
    predecessor: Digest32,
    installed_head: Digest32,
) -> Result<Derived, PlasticityRuntimeCallErrorV1> {
    use PlasticityRuntimeCallErrorV1::Unavailable;
    let head = snapshot.head_digest.to_string();
    let count = u64::try_from(snapshot.records().len()).map_err(|_| Unavailable)?;
    match plan {
        DatasetPlan::OriginalV2(plan) => {
            let payload =
                dataset_freeze_signing_payload_v2(snapshot, &plan).map_err(|_| Unavailable)?;
            let dataset = freeze_dataset_from_ledger(snapshot, plan, producer, now)
                .map_err(|_| Unavailable)?;
            Ok(Derived::OriginalV2(PreparedParameterDatasetV1 {
                dataset: ReviewDatasetWireV1::from_native(&dataset),
                ledger_head_digest: head,
                ledger_record_count: count,
                freeze_payload_hex: crate::client::encode_hex(&payload),
                proposal_registry_predecessor: predecessor.to_string(),
                installed_artifact_head: installed_head.to_string(),
            }))
        }
        DatasetPlan::WindowV3(plan) => {
            let payload = dataset_window_freeze_signing_payload_v3(snapshot, &plan)
                .map_err(|_| Unavailable)?;
            let window =
                freeze_dataset_window_from_ledger_v3(snapshot, plan.clone(), producer, now)
                    .map_err(|_| Unavailable)?;
            // This is the SAME retained FD and complete original replay. It is
            // not a witness or a reopened writer; missing custody stays missing.
            let source = ledger
                .export_canonical_source_v1()
                .map_err(|_| Unavailable)?;
            if ledger.snapshot().map_err(|_| Unavailable)? != *snapshot {
                return Err(Unavailable);
            }
            Ok(Derived::WindowV3(
                PreparedParameterDatasetWindowV3 {
                    plan: DatasetWindowFreezePlanWireV3::from_native(&plan),
                    window: DatasetWindowSnapshotWireV3::from_native(&window),
                    ledger_head_digest: head,
                    ledger_record_count: count,
                    freeze_payload_hex: crate::client::encode_hex(&payload),
                    proposal_registry_predecessor: predecessor.to_string(),
                    installed_artifact_head: installed_head.to_string(),
                    ledger_binding: source.binding().to_string(),
                    maximum_ledger_records: u64::try_from(source.maximum_records())
                        .map_err(|_| Unavailable)?,
                    ledger_source_hex: crate::client::encode_hex(source.bytes()),
                },
                window,
            ))
        }
    }
}
impl Derived {
    pub(crate) fn verify_at(&self, now: u64) -> Result<(), PlasticityRuntimeCallErrorV1> {
        use PlasticityRuntimeCallErrorV1::Unavailable;
        match self {
            Self::OriginalV2(v) => verify_dataset_snapshot_receipt_v3(
                &v.dataset.native().map_err(|_| Unavailable)?,
                now,
            ),
            Self::WindowV3(_, native) => verify_dataset_snapshot_receipt_v3(&native.receipt, now),
        }
        .map_err(|_| Unavailable)
    }
    pub(crate) fn finish(self) -> Result<PreparedDataset, PlasticityRuntimeCallErrorV1> {
        use PlasticityRuntimeCallErrorV1::Unavailable;
        match self {
            Self::OriginalV2(result) => {
                let size = serde_json::to_vec(&result.dataset)
                    .map_err(|_| Unavailable)?
                    .len();
                if size
                    .checked_mul(2)
                    .and_then(|n| n.checked_add(result.freeze_payload_hex.len()))
                    .and_then(|n| n.checked_add(8192))
                    .is_none_or(|n| n > crate::MAX_CONTROL_FRAME_BYTES as usize)
                {
                    return Err(Unavailable);
                }
                Ok(PreparedDataset::OriginalV2(result))
            }
            Self::WindowV3(result, _) => {
                if serde_json::to_vec(&result).map_err(|_| Unavailable)?.len()
                    > MAX_PREPARED_DATASET_WINDOW_BYTES_V3
                {
                    return Err(Unavailable);
                }
                Ok(PreparedDataset::WindowV3(result))
            }
        }
    }
}

impl PreparedParameterDatasetWindowV3 {
    /// Complete original held-ledger bytes; this is not a witness or custody grant.
    pub fn ledger_source_bytes(&self) -> Result<Vec<u8>, crate::AgentdError> {
        bounded_hex(
            &self.ledger_source_hex,
            MAX_LEDGER_CANONICAL_SOURCE_BYTES_V1,
        )
    }
    /// The sole whole-result codec. It preserves the original Window and facts;
    /// successful parsing does not grant witness or signature authority.
    pub fn canonical_source_bytes(&self) -> Result<Vec<u8>, crate::AgentdError> {
        let bytes = serde_json::to_vec(self)?;
        if bytes.len() > MAX_PREPARED_DATASET_WINDOW_BYTES_V3 {
            return Err(crate::AgentdError::Protocol(
                "whole window facts capacity".into(),
            ));
        }
        Ok(bytes)
    }
    pub fn from_source_bytes(bytes: &[u8]) -> Result<Self, crate::AgentdError> {
        if bytes.is_empty() || bytes.len() > MAX_PREPARED_DATASET_WINDOW_BYTES_V3 {
            return Err(crate::AgentdError::Protocol(
                "whole window facts capacity".into(),
            ));
        }
        Ok(serde_json::from_slice(bytes)?)
    }
    pub(crate) fn validate_at(
        &self,
        round: &crate::AgentdSelfIterationRoundV1,
        now: u64,
    ) -> Result<(), crate::AgentdError> {
        let bad = || crate::AgentdError::Protocol("whole window facts binding".into());
        let plan = self.plan.native().map_err(|_| bad())?;
        let window = self.window.native().map_err(|_| bad())?;
        verify_dataset_snapshot_receipt_v3(&window.receipt, now).map_err(|_| bad())?;
        let head: Digest32 = self.ledger_head_digest.parse().map_err(|_| bad())?;
        let predecessor: Digest32 = self
            .proposal_registry_predecessor
            .parse()
            .map_err(|_| bad())?;
        let installed: Digest32 = self.installed_artifact_head.parse().map_err(|_| bad())?;
        let binding: Digest32 = self.ledger_binding.parse().map_err(|_| bad())?;
        let source = self.ledger_source_bytes()?;
        let payload = bounded_hex(
            &self.freeze_payload_hex,
            MAX_DATASET_WINDOW_SOURCE_RECORDS_V3 as usize * 32 + 4096,
        )?;
        if head.is_zero()
            || head.to_string() != self.ledger_head_digest
            || head != window.receipt.snapshot.ledger_head_digest
            || self.ledger_record_count < window.receipt.snapshot.eligible_frontier
            || self.ledger_record_count > self.maximum_ledger_records
            || self.maximum_ledger_records == 0
            || usize::try_from(self.maximum_ledger_records).is_err()
            || predecessor.to_string() != self.proposal_registry_predecessor
            || installed.is_zero()
            || installed.to_string() != self.installed_artifact_head
            || binding.is_zero()
            || binding.to_string() != self.ledger_binding
            || source.is_empty()
            || payload.is_empty()
            || plan.policy_digest() != window.window_policy_digest
            || plan.snapshot_id != window.receipt.snapshot.snapshot_id
            || plan.objective_digest != window.receipt.snapshot.objective_digest
            || plan.inclusion_policy_digest != window.receipt.inclusion_policy_digest
            || now < round.admitted_at_ms()
            || now >= round.deadline_ms()
        {
            return Err(bad());
        }
        Ok(())
    }
}
pub(crate) fn bounded_hex(value: &str, maximum: usize) -> Result<Vec<u8>, crate::AgentdError> {
    if value.is_empty()
        || value.len() > maximum * 2
        || !value.len().is_multiple_of(2)
        || !value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(crate::AgentdError::Protocol(
            "whole window lowercase hex capacity".into(),
        ));
    }
    crate::parameter_admission_query::decode_hex_bounded(value, maximum.saturating_mul(2))
}
