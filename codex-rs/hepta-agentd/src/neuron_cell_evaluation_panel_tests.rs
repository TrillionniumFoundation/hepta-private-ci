//! Registration mechanisms only. Actual original member readback, B execution
//! and a nonempty task-outcome cohort still require their separate qualification.
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::Error;
use super::OriginalCellEvaluationPanelRegistrationV1 as Registration;
use super::OriginalCellEvaluationPanelTaskV1 as Task;

fn task(plan: &str, input: &str) -> Task {
    Task {
        plan_id: StableId::new(plan).expect("test plan identity"),
        task_digest: Digest32::of_bytes(input.as_bytes()),
        cohort_rule_digest: Digest32::of_bytes(format!("fixed-cohort-rule:{plan}:{input}").as_bytes()),
    }
}

#[test]
fn original_panel_registration_commits_full_nonempty_membership_before_any_result() {
    let primary = task("ordinary-B", "independent-B-input");
    let first = task("retention-A", "old-capability-A-input");
    let second = task("retention-B", "old-capability-B-input");
    let registered = Registration::new(
        primary.clone(),
        vec![second.clone(), first.clone()],
    )
    .expect("original nonempty panel");
    let reordered = Registration::new(primary.clone(), vec![first.clone(), second.clone()])
        .expect("same canonical panel");
    assert_eq!(registered, reordered);
    assert_eq!(registered.primary(), &primary);
    assert_eq!(registered.retention(), &[first.clone(), second.clone()]);
    let changed_input = Registration::new(
        primary.clone(),
        vec![task("retention-A", "changed-original-input"), second.clone()],
    )
    .expect("a different original profile");
    let changed_plan = Registration::new(
        primary,
        vec![first, task("retention-C", "old-capability-B-input")],
    )
    .expect("a different original profile");
    assert_ne!(registered.evaluation_profile(), changed_input.evaluation_profile());
    assert_ne!(registered.evaluation_profile(), changed_plan.evaluation_profile());
    let mut changed_rule = second.clone();
    changed_rule.cohort_rule_digest = Digest32::of_bytes(b"changed-window-or-cluster-policy");
    let changed_rule = Registration::new(registered.primary().clone(), vec![
        registered.retention()[0].clone(), changed_rule,
    ]).expect("a different frozen cohort rule");
    assert_ne!(registered.evaluation_profile(), changed_rule.evaluation_profile());
    assert_ne!(registered.evaluation_profile(), Digest32::ZERO);
}

#[test]
fn original_panel_registration_refuses_empty_duplicate_and_shared_b_tasks() {
    let primary = task("ordinary-B", "independent-B-input");
    let retained = task("retention-A", "old-capability-A-input");
    for invalid in [
        Vec::new(),
        vec![task("ordinary-B", "different-input")],
        vec![task("another-plan", "independent-B-input")],
        vec![retained.clone(), retained.clone()],
        vec![retained.clone(), task("another-plan", "old-capability-A-input")],
        vec![retained.clone(), task("retention-A", "different-input")],
        vec![Task { task_digest: Digest32::ZERO, ..retained.clone() }],
        vec![Task { cohort_rule_digest: Digest32::ZERO, ..retained.clone() }],
        (0..17)
            .map(|index| task(&format!("retention-{index}"), &format!("input-{index}")))
            .collect(),
    ] {
        assert!(matches!(
            Registration::new(primary.clone(), invalid),
            Err(Error::Binding(_))
        ));
    }
}
