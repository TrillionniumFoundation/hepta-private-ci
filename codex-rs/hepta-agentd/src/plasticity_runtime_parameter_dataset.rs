//! Complete dataset facts from the same held Ledger, without signing or append.
use super::*;
use crate::self_iteration::runtime::plasticity_context::RoundContextFence;
use codex_hepta_agent_components::learning_ledger::DatasetFreezePlanV2;
use codex_hepta_agent_components::learning_ledger::PrincipalWire;
use codex_hepta_agent_components::learning_ledger::ReviewDatasetWireV1;
use codex_hepta_agent_components::learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_agent_components::learning_ledger::freeze_dataset_from_ledger;
use codex_hepta_agent_components::learning_ledger::verify_dataset_snapshot_receipt_v3;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::StableId;
use std::path::PathBuf;

pub struct PreparedParameterDatasetV1 {
    pub dataset: ReviewDatasetWireV1,
    pub ledger_head_digest: String,
    pub ledger_record_count: u64,
    pub freeze_payload_hex: String,
    pub proposal_registry_predecessor: String,
    /// The held owner's installed snapshot, independently of latest CURRENT.
    pub installed_artifact_head: String,
}
pub(crate) struct ProtectedParameterDatasetV1 {
    pub(crate) round: crate::AgentdSelfIterationRoundV1,
    pub(crate) producer: (PathBuf, Digest32),
    pub(crate) plan: (PathBuf, Digest32),
}
#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Plan {
    schema: String,
    snapshot_id: String,
    objective_digest: String,
    inclusion_policy_digest: String,
}

impl PlasticityRuntimeHandleV1 {
    pub(crate) async fn prepare_parameter_dataset_v1(
        &self,
        runtime: &crate::AgentdSelfIterationHandleV1,
        request: ProtectedParameterDatasetV1,
    ) -> Result<PreparedParameterDatasetV1, PlasticityRuntimeCallErrorV1> {
        runtime
            .prepare_plasticity_dataset_v1(self.clone(), request)
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)
    }
    pub(crate) fn prepare_dataset_while_round_owned(
        &self,
        fence: RoundContextFence,
        request: ProtectedParameterDatasetV1,
    ) -> Result<PreparedParameterDatasetV1, PlasticityRuntimeCallErrorV1> {
        let (response, receive) = oneshot::channel();
        self.sender
            .blocking_send(PlasticityRuntimeCommandV1::PrepareParameterDataset {
                fence,
                request,
                response,
            })
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
        receive
            .blocking_recv()
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?
    }
}
impl PlasticityRuntimeOwnerV1 {
    pub(super) fn prepare_parameter_dataset(
        &mut self,
        state: &Arc<AgentdState>,
        cancellation: &CancellationToken,
        generation: u64,
        ready: bool,
        fence: RoundContextFence,
        request: ProtectedParameterDatasetV1,
    ) -> Result<PreparedParameterDatasetV1, PlasticityRuntimeCallErrorV1> {
        use PlasticityRuntimeCallErrorV1::Unavailable;
        let installed = state.self_iteration_handle.get().ok_or(Unavailable)?;
        if !ready
            || cancellation.is_cancelled()
            || !fence.same_owner(installed)
            || fence.view().status.terminal
            || !super::input_context::permits_refresh(fence.view(), &request.round)
        {
            return Err(Unavailable);
        }
        let now = observe_plasticity_clock_v1(self.clock.as_mut(), &mut self.last_observed_unix_ms)
            .map_err(|_| PlasticityRuntimeCallErrorV1::ClockUnavailable)?;
        if now < request.round.admitted_at_ms() || now >= request.round.deadline_ms() {
            return Err(Unavailable);
        }
        fence
            .revalidate_learning_trust(now)
            .map_err(|_| Unavailable)?;
        let source = |value: &(PathBuf, Digest32)| {
            crate::plasticity_process_bootstrap::protected_context_bytes(&value.0, value.1, 8192)
                .map_err(|_| Unavailable)
        };
        let producer_bytes = source(&request.producer)?;
        let plan_bytes = source(&request.plan)?;
        let producer: PrincipalWire =
            serde_json::from_slice(&producer_bytes).map_err(|_| Unavailable)?;
        let producer = producer.principal().map_err(|_| Unavailable)?;
        let plan: Plan = serde_json::from_slice(&plan_bytes).map_err(|_| Unavailable)?;
        if plan.schema != "hepta.parameter.dataset-freeze-plan.v1" {
            return Err(Unavailable);
        }
        let plan = DatasetFreezePlanV2 {
            snapshot_id: StableId::new(plan.snapshot_id).map_err(|_| Unavailable)?,
            objective_digest: plan.objective_digest.parse().map_err(|_| Unavailable)?,
            inclusion_policy_digest: plan
                .inclusion_policy_digest
                .parse()
                .map_err(|_| Unavailable)?,
        };
        if plan.objective_digest != fence.learning_objective()
            || !self.owner_evidence_policy.allows(
                crate::PlasticityOwnerEvidenceKindV1::Dataset,
                &producer.principal_id,
            )
        {
            return Err(Unavailable);
        }
        // Producer authority/expiry is independently pinned, not synthesized
        // from the user's Goal or extended to this Round's deadline.
        producer.validate(now).map_err(|_| Unavailable)?;
        let current = self.current_artifacts.as_ref().ok_or(Unavailable)?;
        let before_current = current.read_current_at(now).map_err(|_| Unavailable)?;
        let installed_artifact_head = self.artifacts.head_digest();
        if installed_artifact_head.is_zero() {
            return Err(Unavailable);
        }
        let snapshot = self.ledger.snapshot().map_err(|_| Unavailable)?;
        let predecessor = self
            .parameter_writer
            .current_anchor()
            .map_err(|_| Unavailable)?
            .map_or(Digest32::ZERO, |anchor| anchor.frame_digest);
        let payload =
            dataset_freeze_signing_payload_v2(&snapshot, &plan).map_err(|_| Unavailable)?;
        let dataset =
            freeze_dataset_from_ledger(&snapshot, plan, producer, now).map_err(|_| Unavailable)?;
        if source(&request.producer)? != producer_bytes
            || source(&request.plan)? != plan_bytes
            || self.ledger.snapshot().map_err(|_| Unavailable)? != snapshot
            || self.artifacts.head_digest() != installed_artifact_head
            || self
                .parameter_writer
                .current_anchor()
                .map_err(|_| Unavailable)?
                .map_or(Digest32::ZERO, |anchor| anchor.frame_digest)
                != predecessor
        {
            return Err(Unavailable);
        }
        let observed =
            observe_plasticity_clock_v1(self.clock.as_mut(), &mut self.last_observed_unix_ms)
                .map_err(|_| PlasticityRuntimeCallErrorV1::ClockUnavailable)?;
        let after_current = current.read_current_at(observed).map_err(|_| Unavailable)?;
        let final_now =
            observe_plasticity_clock_v1(self.clock.as_mut(), &mut self.last_observed_unix_ms)
                .map_err(|_| PlasticityRuntimeCallErrorV1::ClockUnavailable)?;
        if final_now < request.round.admitted_at_ms()
            || final_now >= request.round.deadline_ms()
            || cancellation.is_cancelled()
            || before_current.receipt() != after_current.receipt()
            || before_current.witness_digest() != after_current.witness_digest()
            || before_current.trust_digest() != after_current.trust_digest()
            || self.artifacts.head_digest() != installed_artifact_head
        {
            return Err(Unavailable);
        }
        before_current
            .revalidate_at(final_now)
            .map_err(|_| Unavailable)?;
        after_current
            .revalidate_at(final_now)
            .map_err(|_| Unavailable)?;
        fence
            .revalidate_learning_trust(final_now)
            .map_err(|_| Unavailable)?;
        verify_dataset_snapshot_receipt_v3(&dataset, final_now).map_err(|_| Unavailable)?;
        let _guard = state
            .plasticity_final_admission_guard(generation)
            .map_err(|_| Unavailable)?;
        if cancellation.is_cancelled() {
            return Err(Unavailable);
        }
        let result = PreparedParameterDatasetV1 {
            dataset: ReviewDatasetWireV1::from_native(&dataset),
            ledger_head_digest: snapshot.head_digest.to_string(),
            ledger_record_count: u64::try_from(snapshot.records().len())
                .map_err(|_| Unavailable)?,
            freeze_payload_hex: crate::client::encode_hex(&payload),
            proposal_registry_predecessor: predecessor.to_string(),
            installed_artifact_head: installed_artifact_head.to_string(),
        };
        // The ordinary transport remains 64KiB. Reject complete oversized
        // facts here; never truncate a receipt or add a larger response grant.
        let json_size = serde_json::to_vec(&result.dataset)
            .map_err(|_| Unavailable)?
            .len();
        if json_size
            .checked_mul(2)
            .and_then(|n| n.checked_add(result.freeze_payload_hex.len()))
            .and_then(|n| n.checked_add(8192))
            .is_none_or(|n| n > crate::MAX_CONTROL_FRAME_BYTES as usize)
        {
            return Err(Unavailable);
        }
        Ok(result)
    }
}
