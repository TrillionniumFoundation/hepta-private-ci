use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::legacy_evaluation_policy;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use super::*;
use crate::generation_episode_test_support::GenerationFixture;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test identity")
}

fn fixture() -> (GenerationFixture, JointGenerationEpisodePlanV1) {
    let mut fixture = GenerationFixture::new();
    let utility = UtilityProfile {
        profile_id: id("joint-test-utility"),
        axis_registry_digest: Digest32::of_bytes(b"quality-axis"),
        normalization_manifest_digest: Digest32::of_bytes(b"normalization"),
        dimensions: vec![(id("quality"), AxisDirection::Maximize)],
        risk_ceilings: Vec::new(),
        resource_ceilings: Vec::new(),
        required_organs: RequiredOrganSet {
            organ_ids: vec![id("planner")],
        },
    };
    let policy = legacy_evaluation_policy(&utility).expect("explicit policy");
    let profile = JointGenerationPlanningProfileV1 {
        utility,
        policy,
        scalarization: None,
    };
    let mut binding = fixture.frozen.input().clone();
    binding.policy_digest = profile.digest().expect("profile digest");
    binding.sampler_digest = joint_generation_sampler_digest_v1(
        [33; 32],
        /*seed*/ 17,
        JointGenerationSamplerV1::Mean,
    )
    .expect("sampler digest");
    fixture.frozen = FrozenGenerationEpisodeV1::new(binding).expect("frozen binding");
    fixture.config.task_digest = fixture.frozen.task_digest().into_array();
    let plan = JointGenerationEpisodePlanV1::new(
        fixture.frozen.clone(),
        [33; 32],
        /*seed*/ 17,
        JointGenerationSamplerV1::Mean,
        profile,
    )
    .expect("bound plan");
    (fixture, plan)
}

fn step(value: &str) -> JointGenerationStepV1 {
    JointGenerationStepV1 {
        operation_id: id(value),
        planning_attempt_id: id(&format!("plan-{value}")),
        admitted_at_micros: 10,
        deadline_micros: 100,
    }
}

fn contributions(
    fixture: &GenerationFixture,
    observation: &CellGenerationObservationV1,
    preferred: &str,
) -> ContributionSet {
    let objective_digest = fixture.frozen.input().objective_digest;
    let generation = Generation::new(observation.snapshot().generation).expect("generation");
    ContributionSet {
        objective_digest,
        generation,
        contributions: CANDIDATES
            .into_iter()
            .map(|candidate| UtilityContribution {
                candidate_id: id(candidate),
                organ_id: id("planner"),
                objective_digest,
                generation,
                feasibility: FeasibilityPosture::Feasible,
                utility: vec![AxisValue {
                    axis: id("quality"),
                    value: if candidate == preferred {
                        FixedQ32::ONE
                    } else {
                        FixedQ32::ZERO
                    },
                }],
                risk: Vec::new(),
                resource: Vec::new(),
                uncertainty: vec![AxisValue {
                    axis: id("quality"),
                    value: FixedQ32::ZERO,
                }],
                support_digest: joint_generation_contribution_support_v1(
                    observation,
                    &id(candidate),
                    &id("planner"),
                )
                .expect("current support"),
            })
            .collect(),
    }
}

#[test]
fn explicit_ndu_stop_reaches_existing_owner_and_keeps_planning_charge_on_reopen() {
    let (fixture, plan) = fixture();
    let mut owner = fixture.open();
    let initial = owner.observe_generation().expect("initial observation");
    let init = plan
        .initialize(&initial, step("init"))
        .expect("init request");
    assert_eq!(
        init.input,
        JointGenerationInputV1 {
            public_digest: [33; 32],
            command: JointGenerationCommandV1::Init {
                seed: 17,
                sampler: JointGenerationSamplerV1::Mean,
            },
        }
        .encode()
        .expect("canonical input")
    );
    owner
        .admit(init.clone(), /*now_micros*/ 11)
        .expect("admission");
    owner
        .commit(
            fixture.proposal(&init, CellGenerationDispositionV2::Advanced, b""),
            /*now_micros*/ 20,
        )
        .expect("initialized state");
    let observed = owner.observe_generation().expect("initialized observation");
    let attempt = plan
        .plan_advance(
            &observed,
            contributions(&fixture, &observed, "stop"),
            step("stop"),
        )
        .expect("NDU attempt");
    let planning_cost = attempt.planning_cost;
    let planned = attempt.result.expect("NDU plan");
    assert_eq!(
        planned.evaluation.base.advisory_recommendation,
        Some(id("stop"))
    );
    let request = planned.request.expect("explicit STOP request");
    assert_eq!(
        request.input,
        JointGenerationInputV1 {
            public_digest: [33; 32],
            command: JointGenerationCommandV1::Advance {
                action: JointGenerationActionV1::Stop,
            },
        }
        .encode()
        .expect("explicit command")
    );
    owner
        .record_cost(planning_cost.clone())
        .expect("existing cost owner");
    owner
        .admit(request.clone(), /*now_micros*/ 21)
        .expect("stop admission");
    owner
        .commit(
            fixture.proposal(&request, CellGenerationDispositionV2::Stopped, b"immutable"),
            /*now_micros*/ 30,
        )
        .expect("stop commit");
    let awaiting = owner.observe_generation().expect("awaiting delivery");
    assert!(!awaiting.is_terminal());
    let chunk = awaiting.pending_output().expect("committed outbox").clone();
    let cost = CellTaskCostV2::new(awaiting.cost().identity()).expect("ack cost");
    owner
        .acknowledge(chunk, [34; 32], cost)
        .expect("delivery ack");
    let terminal = owner.observe_generation().expect("terminal");
    assert!(terminal.is_terminal());
    assert!(terminal.cost().entries().contains(&planning_cost));
    assert!(terminal.complete_metrics().is_none());
    assert_eq!(terminal.snapshot().prefix, b"immutable");
    drop(owner);
    assert_eq!(
        fixture.open().observe_generation().expect("reopen"),
        terminal
    );
}

#[test]
fn pending_work_and_stale_prediction_cuts_are_refused_before_planning() {
    let (fixture, plan) = fixture();
    let mut owner = fixture.open();
    let initial = owner.observe_generation().expect("initial");
    let init = plan.initialize(&initial, step("init")).expect("init");
    owner.admit(init.clone(), /*now_micros*/ 11).expect("admit");
    let pending = owner.observe_generation().expect("pending");
    assert!(matches!(
        plan.plan_advance(
            &pending,
            contributions(&fixture, &pending, "image"),
            step("blocked")
        ),
        Err(JointGenerationPlanErrorV1::Generation(
            CellGenerationErrorV2::Pending
        ))
    ));
    owner
        .commit(
            fixture.proposal(&init, CellGenerationDispositionV2::Advanced, b""),
            /*now_micros*/ 20,
        )
        .expect("commit");
    let current = owner.observe_generation().expect("current");
    assert!(matches!(
        plan.plan_advance(
            &current,
            contributions(&fixture, &pending, "image"),
            step("stale")
        )
        .expect("metered rejection")
        .result,
        Err(JointGenerationPlanErrorV1::Binding(
            "contribution owner cut"
        ))
    ));
    let mut incomplete = contributions(&fixture, &current, "image");
    incomplete
        .contributions
        .retain(|value| value.candidate_id != id("stop"));
    assert!(matches!(
        plan.plan_advance(&current, incomplete, step("incomplete"))
            .expect("metered rejection")
            .result,
        Err(JointGenerationPlanErrorV1::Binding(_))
    ));
    assert_eq!(owner.observe_generation().expect("unchanged"), current);
}

#[test]
fn frozen_sampler_and_policy_drift_cannot_build_joint_requests() {
    let (fixture, plan) = fixture();
    for (seed, sampler) in [
        (18, JointGenerationSamplerV1::Mean),
        (17, JointGenerationSamplerV1::SplitmixNormalV1),
    ] {
        assert!(
            JointGenerationEpisodePlanV1::new(
                fixture.frozen.clone(),
                [33; 32],
                seed,
                sampler,
                plan.profile.clone()
            )
            .is_err()
        );
    }
    let mut changed = plan.profile;
    changed.utility.normalization_manifest_digest = Digest32::of_bytes(b"new units");
    assert!(
        JointGenerationEpisodePlanV1::new(
            fixture.frozen,
            [33; 32],
            /*seed*/ 17,
            JointGenerationSamplerV1::Mean,
            changed
        )
        .is_err()
    );
}

#[test]
fn abstention_or_tie_does_not_become_an_unrecorded_worker_auto_action() {
    let (fixture, plan) = fixture();
    let mut owner = fixture.open();
    let init = plan
        .initialize(&owner.observe_generation().expect("initial"), step("init"))
        .expect("init");
    owner.admit(init.clone(), /*now_micros*/ 11).expect("admit");
    owner
        .commit(
            fixture.proposal(&init, CellGenerationDispositionV2::Advanced, b""),
            /*now_micros*/ 20,
        )
        .expect("commit");
    let current = owner.observe_generation().expect("current");
    for preferred in ["abstain", "no-unique-winner"] {
        let attempt = plan
            .plan_advance(
                &current,
                contributions(&fixture, &current, preferred),
                step(preferred),
            )
            .expect("metered abstention");
        let planning_cost = attempt.planning_cost;
        let planned = attempt.result.expect("evaluated abstention");
        assert!(planned.request.is_none());
        assert!(planning_cost.metrics.wall_micros.is_some());
        assert!(planning_cost.metrics.cpu_micros.is_none());
        assert_eq!(owner.observe_generation().expect("no dispatch"), current);
    }
}

#[test]
fn actual_init_cannot_silently_change_the_frozen_sampler_even_after_reopen() {
    let (fixture, plan) = fixture();
    let mut owner = fixture.open();
    let mut request = plan
        .initialize(&owner.observe_generation().expect("initial"), step("init"))
        .expect("init");
    request.input = JointGenerationInputV1 {
        public_digest: [33; 32],
        command: JointGenerationCommandV1::Init {
            seed: 18,
            sampler: JointGenerationSamplerV1::Mean,
        },
    }
    .encode()
    .expect("different actual sampler seed");
    owner
        .admit(request.clone(), /*now_micros*/ 11)
        .expect("generic admission");
    owner
        .commit(
            fixture.proposal(&request, CellGenerationDispositionV2::Advanced, b""),
            /*now_micros*/ 20,
        )
        .expect("actual state commit");
    drop(owner);
    let owner = fixture.open();
    let observed = owner.observe_generation().expect("reopened observation");
    fixture
        .frozen
        .validate_observation(&observed)
        .expect("declaration still matches");
    let attempted = plan
        .plan_advance(
            &observed,
            contributions(&fixture, &observed, "stop"),
            step("must-reject"),
        )
        .expect("metered attempt");
    assert!(matches!(
        attempted.result,
        Err(JointGenerationPlanErrorV1::Binding(
            "actual Joint initialization differs from frozen sampler"
        ))
    ));
    assert_eq!(attempted.planning_cost.outcome, CellCostOutcomeV2::Failed);
}

#[test]
fn failed_planning_attempts_are_charged_separately_and_recorded_attempts_are_not_recomputed() {
    let (fixture, plan) = fixture();
    let mut owner = fixture.open();
    let init = plan
        .initialize(&owner.observe_generation().expect("initial"), step("init"))
        .expect("init");
    owner.admit(init.clone(), /*now_micros*/ 11).expect("admit");
    owner
        .commit(
            fixture.proposal(&init, CellGenerationDispositionV2::Advanced, b""),
            /*now_micros*/ 20,
        )
        .expect("commit");
    for attempt_id in ["first-attempt", "second-attempt"] {
        let observed = owner.observe_generation().expect("current cut");
        let mut invalid = contributions(&fixture, &observed, "image");
        invalid.contributions.pop();
        let mut request = step("same-worker-operation");
        request.planning_attempt_id = id(attempt_id);
        let attempt = plan
            .plan_advance(&observed, invalid, request.clone())
            .expect("metered attempt");
        assert!(attempt.result.is_err());
        assert_eq!(attempt.planning_cost.outcome, CellCostOutcomeV2::Failed);
        assert!(attempt.planning_cost.metrics.wall_micros.is_some());
        owner
            .record_cost(attempt.planning_cost)
            .expect("retain failed cost");
        let observed = owner.observe_generation().expect("charged cut");
        assert!(matches!(
            plan.plan_advance(
                &observed,
                contributions(&fixture, &observed, "image"),
                request
            ),
            Err(JointGenerationPlanErrorV1::Binding(
                "planning attempt already recorded"
            ))
        ));
    }
    let observed = owner.observe_generation().expect("complete observations");
    assert_eq!(
        observed
            .cost()
            .entries()
            .iter()
            .filter(|entry| entry.stage == CellCostStageV2::Planning)
            .count(),
        2
    );
    assert_eq!(observed.snapshot().revision, 1);
    assert!(observed.pending_request_digest().is_none());
}
