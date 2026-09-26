use std::fmt::Debug;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::*;
use crate::NduPlanEvaluationInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlanningEvaluationDispositionV1;
use crate::PlanningRequestV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::bind_ndu_plan_evaluation_v1;
use crate::collect_snapshot;
use crate::finalize_plan;
use crate::prepare_plan;
use crate::request_execution_grants;

static NONCE: AtomicU64 = AtomicU64::new(1);

fn must<T, E: Debug>(value: Result<T, E>) -> T {
    value.unwrap_or_else(|error| panic!("unexpected error: {error:?}"))
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

struct TempRoot(PathBuf);

impl TempRoot {
    fn new(label: &str) -> Self {
        let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-planner-execution-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir(&path).expect("create planner execution temp root");
        Self(path)
    }
}

impl Drop for TempRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn request_set(payloads: usize) -> (crate::FeasiblePlanReceiptV1, GrantRequestSetV1) {
    let snapshot = must(collect_snapshot(
        SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: must(Generation::new(7)),
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocations"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 1_000,
            maximum_owner_age_micros: 100,
            expires_at_micros: 2_000,
            required_owner_ids: vec![id("owner")],
        },
        vec![OwnerSummaryV1 {
            owner_id: id("owner"),
            revision: must(Revision::new(1)),
            objective_digest: digest("objective"),
            body_generation: must(Generation::new(7)),
            configuration_digest: digest("configuration"),
            observed_at_micros: 950,
            expires_at_micros: 1_900,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("frontier"),
            support_digest: digest("support"),
        }],
    ));
    let final_payload_digests = (0..payloads)
        .map(|index| digest(&format!("payload-{index}")))
        .collect();
    let prepared = must(prepare_plan(
        &snapshot,
        PlanningRequestV1 {
            plan_id: id("plan"),
            now_micros: 1_000,
            deadline_micros: 1_800,
            evaluation_policy_digest: digest("policy"),
            resource_profile_digest: digest("resource-profile"),
            candidates: vec![
                PlanCandidateV1 {
                    candidate_id: id("abstain"),
                    operation_id: id("abstain"),
                    plan_digest: digest("abstain-plan"),
                    required_owner_ids: vec![id("owner")],
                    final_payload_digests: Vec::new(),
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: id("compute"),
                        value: FixedQ32::ZERO,
                    }],
                },
                PlanCandidateV1 {
                    candidate_id: id("work"),
                    operation_id: id("operation"),
                    plan_digest: digest("work-plan"),
                    required_owner_ids: vec![id("owner")],
                    final_payload_digests,
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: id("compute"),
                        value: q32(1),
                    }],
                },
            ],
            resource_reservations: vec![ResourceReservationV1 {
                axis: id("compute"),
                endowment: q32(10),
                essential_floor: FixedQ32::ZERO,
            }],
        },
    ));
    let evaluation = must(bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: prepared.objective_digest(),
        body_generation: prepared.body_generation(),
        evaluation_policy_digest: prepared.evaluation_policy_digest(),
        evaluation_digest: digest("evaluation"),
        evaluated_candidate_ids: prepared
            .feasible_candidates()
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect(),
        rejected_candidate_ids: Vec::new(),
        pareto_candidate_ids: vec![id("work")],
        advisory_candidate_id: Some(id("work")),
        uncertainty_digest: digest("uncertainty"),
        disposition: PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
    }));
    let receipt = must(finalize_plan(&snapshot, &prepared, &evaluation, 1_100));
    let requests = must(request_execution_grants(&snapshot, &prepared, &receipt, 1_100));
    (receipt, requests)
}

fn signed_grant(request: &GrantRequestV1, request_digest: Digest32) -> VerifiedExecutionGrantV1 {
    let mut grant = VerifiedExecutionGrantV1 {
        request_digest,
        final_payload_digest: request.final_payload_digest,
        grant_digest: Digest32::ZERO,
        issuer_identity_digest: digest("authority"),
        signature_digest: digest("authority-signature"),
        authority_epoch: 4,
        expires_at_micros: request.expires_at_micros,
        canonical_body: b"signed authority grant body".to_vec(),
    };
    grant.grant_digest = authority_grant_digest(&grant);
    grant
}

fn terminal(
    request: &GrantRequestV1,
    grant: &VerifiedExecutionGrantV1,
    disposition: TerminalDispositionV1,
    label: &str,
) -> SignedTerminalObservationV1 {
    let mut value = SignedTerminalObservationV1 {
        request_digest: grant.request_digest,
        grant_digest: grant.grant_digest,
        final_payload_digest: request.final_payload_digest,
        disposition,
        terminal_digest: Digest32::ZERO,
        executor_identity_digest: digest("executor"),
        signature_digest: digest("executor-signature"),
        canonical_body: label.as_bytes().to_vec(),
    };
    value.terminal_digest = terminal_observation_digest(&value);
    value
}

#[derive(Default)]
struct GrantAuthority {
    calls: usize,
    tamper_payload: bool,
}

impl IndependentPlannerAuthorityV1 for GrantAuthority {
    fn authorize(
        &mut self,
        request: &GrantRequestV1,
        request_digest: Digest32,
        _now_micros: u64,
    ) -> Result<IndependentAuthorityDecisionV1, String> {
        self.calls += 1;
        let mut grant = signed_grant(request, request_digest);
        if self.tamper_payload {
            grant.final_payload_digest = digest("drifted-payload");
            grant.grant_digest = authority_grant_digest(&grant);
        }
        Ok(IndependentAuthorityDecisionV1::Granted(grant))
    }
}

struct DenyAuthority;

impl IndependentPlannerAuthorityV1 for DenyAuthority {
    fn authorize(
        &mut self,
        _request: &GrantRequestV1,
        request_digest: Digest32,
        _now_micros: u64,
    ) -> Result<IndependentAuthorityDecisionV1, String> {
        let mut observation = SignedAuthorityObservationV1 {
            request_digest,
            disposition: AuthorityDispositionV1::Denied,
            observation_digest: Digest32::ZERO,
            issuer_identity_digest: digest("authority"),
            signature_digest: digest("denial-signature"),
            canonical_body: b"signed denial".to_vec(),
        };
        observation.observation_digest = authority_observation_digest(&observation);
        Ok(IndependentAuthorityDecisionV1::Observation(observation))
    }
}

struct IndeterminateAuthority;

impl IndependentPlannerAuthorityV1 for IndeterminateAuthority {
    fn authorize(
        &mut self,
        _request: &GrantRequestV1,
        request_digest: Digest32,
        _now_micros: u64,
    ) -> Result<IndependentAuthorityDecisionV1, String> {
        let mut observation = SignedAuthorityObservationV1 {
            request_digest,
            disposition: AuthorityDispositionV1::Indeterminate,
            observation_digest: Digest32::ZERO,
            issuer_identity_digest: digest("authority"),
            signature_digest: digest("indeterminate-signature"),
            canonical_body: b"signed authority indeterminate observation".to_vec(),
        };
        observation.observation_digest = authority_observation_digest(&observation);
        Ok(IndependentAuthorityDecisionV1::Observation(observation))
    }
}

struct FixtureExecutor {
    calls: usize,
    dispositions: Vec<TerminalDispositionV1>,
}

impl FixtureExecutor {
    fn new(dispositions: Vec<TerminalDispositionV1>) -> Self {
        Self {
            calls: 0,
            dispositions,
        }
    }
}

impl PlannerEffectExecutorV1 for FixtureExecutor {
    fn execute(
        &mut self,
        request: &GrantRequestV1,
        grant: &VerifiedExecutionGrantV1,
        _now_micros: u64,
    ) -> Result<SignedTerminalObservationV1, String> {
        let disposition = self
            .dispositions
            .get(self.calls)
            .copied()
            .unwrap_or(TerminalDispositionV1::Succeeded);
        self.calls += 1;
        Ok(terminal(request, grant, disposition, "signed terminal body"))
    }
}

struct FixtureReconciler {
    calls: usize,
    disposition: ReconciliationDispositionV1,
}

impl PlannerTerminalReconcilerV1 for FixtureReconciler {
    fn reconcile(
        &mut self,
        pending: &PlannerIndeterminateV1,
        _now_micros: u64,
    ) -> Result<SignedReconciliationReceiptV1, String> {
        self.calls += 1;
        let mut receipt = SignedReconciliationReceiptV1 {
            request_digest: pending.request_digest,
            observed_digest: pending.observation_digest,
            disposition: self.disposition,
            reconciliation_digest: Digest32::ZERO,
            reconciler_identity_digest: digest("reconciler"),
            signature_digest: digest("reconciler-signature"),
            canonical_body: b"signed reconciliation body".to_vec(),
        };
        receipt.reconciliation_digest = reconciliation_digest(&receipt);
        Ok(receipt)
    }
}

fn open_store_with_decision(
    root: &TempRoot,
    receipt: &crate::FeasiblePlanReceiptV1,
) -> PlannerStoreV1 {
    let mut store = must(PlannerStoreV1::open(&root.0));
    must(store.record_decision(receipt, b"canonical decision envelope"));
    store
}
