//! Actual ordinary binary routes for candidate adoption and post-evaluation
//! retention. No embedded aggregate, reconstructed grant or test result owner
//! is used by these parent cases.

use std::time::Duration;
use std::time::Instant;

use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningLocalDispositionV2;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;

use super::b_evaluate::OriginalBusinessCase;
use super::b_evaluate::OriginalIndependentBEvaluationInputs;
use super::b_publication_observer::OriginalBPublicationObserver;
use super::post_a_launch::RunningOrdinaryPostA;
use super::post_a_plan::OriginalPostAResources;
use super::post_a_retained::RetainedOrdinaryQ24Fixture;
use crate::cell_q24_publication_driver::validation::Decision;
use crate::learning_iteration_checkpoint::ordinary_observer::OriginalCheckpointData;

#[test]
#[ignore = "actual UID0, original protected binds and exact production binaries; full ordinary Adopt"]
fn ordinary_main_adopts_after_independent_b_and_executes_original_c() -> anyhow::Result<()> {
    run_original_business_case(OriginalBusinessCase::Adopt)?.archive_actual_phase()
}

#[test]
#[ignore = "actual UID0, original protected binds and exact production binaries; actual B NoUpdate"]
fn ordinary_main_retains_after_completed_independent_b_and_executes_original_c()
-> anyhow::Result<()> {
    run_original_business_case(OriginalBusinessCase::EvaluatedNoUpdate)?.archive_actual_phase()
}

pub(super) fn run_original_business_case(
    case: OriginalBusinessCase,
) -> anyhow::Result<RetainedOrdinaryQ24Fixture> {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    let original =
        super::run_original_a(&runtime, /*independent business value*/ 2_i64 << 32)?;
    // This one parent budget includes actual expiry/retirement of A. The
    // separate Root/daemon/input owners keep their originally declared ends.
    let end = Instant::now()
        .checked_add(Duration::from_millis(super::root::LIFETIME_MS))
        .ok_or_else(|| anyhow::anyhow!("ordinary post-A parent deadline overflow"))?;
    let resources =
        OriginalPostAResources::reserve_after_original_retirement(original, &runtime, end)?;
    let independent = OriginalIndependentBEvaluationInputs::prepare(&resources, case)?;
    let plan = resources.configure_original_evaluation(independent.protocol_digest())?;
    let mut source_report = None;
    let mut publication = None;
    let mut running = RunningOrdinaryPostA::start(plan, |handoff, plan| {
        let initial = plan.profile.original_initial_data()?;
        let (child, report) = super::source_keeper::spawn_original_source(
            handoff,
            initial.head_digest,
            plan.resources.end,
            independent.producer_json(plan)?,
        )?;
        let actual = child.lifetime();
        let path = independent.write_deployment(
            plan,
            CognitiveCheckpointPeerLifetime {
                uid: 60002,
                pid: actual.pid,
                boot_id: actual.boot_id.clone(),
                process_start_ticks: actual.start_ticks,
            },
        )?;
        anyhow::ensure!(
            path == plan.root.independent_b,
            "actual Root B deployment path changed"
        );
        publication = Some(OriginalBPublicationObserver::capture_original_reservation(
            plan,
        )?);
        source_report = Some(report);
        child.require_live()?;
        Ok(child)
    })?;
    runtime.block_on(running.promote_when_initialized())?;
    let (decision_cut, decision) =
        runtime.block_on(super::post_a_progress::wait_for_original_decision(&running))?;
    require_actual_business_decision(case, &decision)?;
    // The product source client returns only after its actual Root finalization
    // notice. Reaping this child is not a stand-in for B's own completion.
    let source = running.join_original_source()?;
    let source_data = source_report
        .as_mut()
        .ok_or_else(|| anyhow::anyhow!("actual original source report absent"))?
        .read_after_actual_exit(&source)?;
    let candidate = super::post_a_progress::original_candidate_model(
        &running,
        &decision_cut,
        &decision,
        &source_data,
    )?;
    let qualified = publication
        .as_mut()
        .ok_or_else(|| anyhow::anyhow!("original B publication files absent"))?
        .read_original_after_decision(&running.plan, &decision)?;
    let expected_current = if decision.adopts() {
        super::post_a_artifact_inputs::write_original_candidate_head(
            &running.plan,
            &decision,
            qualified.manifest(),
        )?
    } else {
        running
            .plan
            .root
            .publication_inputs
            .retained_current
            .original_current()?
    };
    // All external head inputs are ready before the product opens its sole
    // Artifact writer. Neither branch publishes a fixture-owned registry.
    super::post_a_artifact_inputs::write_original_writer_input(&running.plan)?;
    if decision.adopts() {
        runtime.block_on(super::post_a_selection::wait_for_original_publication(
            &running, &decision,
        ))?;
    }
    let selected = super::post_a_selection::sign_original_selection(
        &running.plan,
        &decision,
        &expected_current,
    )?;
    let model = if decision.adopts() {
        candidate
    } else {
        super::super::material::load(
            &running
                .plan
                .resources
                .original
                .plan
                .runtime
                .path()
                .join("model"),
        )?
        .0
    };
    let target = running.plan.resources.c.publish_selected_input_data(
        &running.plan.resources.successor,
        &decision.bundle,
        &model,
        &selected.manifest,
    )?;
    let terminal = runtime.block_on(super::post_a_progress::wait_for_original_terminal(
        &running,
        decision_cut,
    ))?;
    running.require_live()?;
    running.daemon.request_original_shutdown()?;
    let RunningOrdinaryPostA {
        plan, daemon, root, ..
    } = running;
    let daemon = daemon.wait_success_until(plan.resources.end)?;
    let root = root.wait_success_until(plan.resources.end)?;
    daemon.require_dead()?;
    root.require_dead()?;
    source.require_dead()?;
    let confirmed = OriginalCheckpointData::read_existing(
        &plan
            .resources
            .original
            .plan
            .root
            .authority
            .join("learning-checkpoint"),
        &plan.profile.original_initial_data()?,
    )?;
    pretty_assertions::assert_eq!(confirmed, terminal);
    let snapshot = confirmed.snapshot.as_ref().ok_or_else(|| {
        anyhow::anyhow!("actual terminal Root checkpoint disappeared after process exit")
    })?;
    let completed =
        super::post_a_completed_data::OriginalCompletedCData::observe_after_original_exit(
            &plan, &selected, &target, snapshot, &daemon, &root,
        )?;
    Ok(RetainedOrdinaryQ24Fixture {
        case,
        plan,
        independent,
        decision,
        selected,
        target,
        terminal: confirmed,
        completed,
        daemon,
        root,
        source,
        source_data,
        publication: qualified,
    })
}

fn require_actual_business_decision(
    case: OriginalBusinessCase,
    decision: &Decision,
) -> anyhow::Result<()> {
    decision.require_root_publication()?;
    anyhow::ensure!(
        decision.snapshot.training_no_update_v2().is_none()
            && decision.snapshot.receipts.iter().any(|receipt| matches!(
                receipt.observation,
                LearningIterationObservationV1::Training { .. }
            )),
        "both business cases require actual candidate Training"
    );
    let evaluation = decision
        .snapshot
        .receipts
        .iter()
        .find_map(|receipt| match &receipt.observation {
            LearningIterationObservationV1::Evaluation { disposition, .. } => Some(*disposition),
            _ => None,
        })
        .ok_or_else(|| anyhow::anyhow!("actual independent B evaluation missing"))?;
    match case {
        OriginalBusinessCase::Adopt => anyhow::ensure!(
            evaluation == LearningEvaluationDispositionV1::Qualified
                && decision.adopts()
                && decision.snapshot.local_decision_v2().is_some_and(
                    |local| local.disposition == LearningLocalDispositionV2::AdoptCandidate
                ),
            "actual B qualification and original local Adopt decision required"
        ),
        OriginalBusinessCase::EvaluatedNoUpdate => anyhow::ensure!(
            evaluation == LearningEvaluationDispositionV1::NoUpdate
                && !decision.adopts()
                && decision.bundle == decision.snapshot.request.selected_bundle,
            "actual completed independent B NoUpdate required; closed-source or absent-owner is not a result"
        ),
    }
    Ok(())
}
