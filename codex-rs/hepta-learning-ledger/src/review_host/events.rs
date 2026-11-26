//! Shared typed fact construction; observations never grant activation.
use super::files::ReviewResult;
use super::observations::NativeObservation;
use super::observations::PinnedModel;
use crate::AuthenticatedOutcomeV1;
use crate::AuthenticatedPrincipalV1;
use crate::CandidateSetCompletenessReceiptV1;
use crate::OutcomeTerminalityV1;
use crate::OutcomeWatermarkV1;
use crate::ProductionDecisionV2;
use crate::candidate_ids_digest_v2;
use crate::candidate_order_digest_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

pub(super) struct EventBindings {
    pub(super) objective: Digest32,
    pub(super) generator: AuthenticatedPrincipalV1,
    pub(super) observer: AuthenticatedPrincipalV1,
    pub(super) program_digest: Digest32,
}
pub(super) struct ExecutedPolicy<'a> {
    pub(super) label: &'a str,
    pub(super) observation: &'a NativeObservation,
    pub(super) selected: usize,
    pub(super) model: &'a PinnedModel,
    pub(super) support: Digest32,
}

pub(super) fn decision(
    trust: &EventBindings,
    audit: Digest32,
    index: usize,
    policy: ExecutedPolicy<'_>,
    source: Digest32,
) -> ReviewResult<ProductionDecisionV2> {
    let ExecutedPolicy {
        label,
        observation,
        selected,
        model,
        support,
    } = policy;
    let candidates = vec![
        StableId::new("SUPPORT")?,
        StableId::new("CONTRADICT")?,
        StableId::new("abstain")?,
    ];
    let selected_action = if selected < 2 { selected } else { 2 };
    let input: Digest32 = observation.input_digest.parse()?;
    let snapshot = Digest32::of_bytes(
        &[
            source.as_array().as_slice(),
            input.as_array(),
            model.manifest.as_array(),
        ]
        .concat(),
    );
    Ok(ProductionDecisionV2 {
        record_id: StableId::new(format!("calibration.decision.{audit}.{label}.{index}"))?,
        episode_id: StableId::new(format!("calibration.episode.{audit}.{label}.{index}"))?,
        run_snapshot_digest: snapshot,
        objective_digest: trust.objective,
        policy_digest: model.weights,
        selected_candidate_id: candidates[selected_action].clone(),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: StableId::new(format!("calibration.set.{audit}.{label}.{index}"))?,
            state_digest: snapshot,
            generator_id: trust.generator.principal_id.clone(),
            generator_code_digest: trust.program_digest,
            grammar_digest: Digest32::of_bytes(
                b"SUPPORT, CONTRADICT, abstain; HPTNCPU1 argmax drive; lowest-index tie",
            ),
            hard_filter_digest: Digest32::of_bytes(
                b"native drive index 0 SUPPORT; 1 CONTRADICT; all other indices map to abstain",
            ),
            truncation_digest: Digest32::of_bytes(
                b"complete three semantic actions from frozen native output width 10; none omitted",
            ),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: 3,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        candidate_ids: candidates,
        support_digest: support,
    })
}

pub(super) fn outcome(
    trust: &EventBindings,
    decision: &ProductionDecisionV2,
    observation: &NativeObservation,
    correct: bool,
    support: Digest32,
) -> ReviewResult<AuthenticatedOutcomeV1> {
    Ok(AuthenticatedOutcomeV1 {
        record_id: StableId::new(format!("{}.outcome", decision.record_id.as_str()))?,
        outcome_id: StableId::new(format!("{}.outcome", decision.episode_id.as_str()))?,
        episode_id: decision.episode_id.clone(),
        observer: trust.observer.clone(),
        observed_at: Some(observation.executed_at_ms),
        value: Some(if correct {
            FixedQ32::ONE
        } else {
            FixedQ32::ZERO
        }),
        unit_profile_digest: Digest32::of_bytes(
            b"SciFact original expert-label exact correctness; unknown never negative",
        ),
        support_digest: support,
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: observation.executed_at_ms,
            expected_delay_profile_digest: Digest32::of_bytes(
                b"bounded completed offline native calibration inference",
            ),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(observation.executed_at_ms),
        },
    })
}
