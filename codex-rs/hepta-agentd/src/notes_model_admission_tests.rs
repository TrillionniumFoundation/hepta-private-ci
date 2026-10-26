//! Capacity-state regression only. Original writer/effect behavior is covered
//! by the Notes Objective and retained-terminal owner integration fixtures.

use super::*;
use pretty_assertions::assert_eq;

fn closed_view(id: String) -> NotesModelProposalObservation {
    NotesModelProposalObservation {
        proposal_id: id,
        proposal_sha256: "a".repeat(64),
        thread_id: "original-thread".into(),
        turn_id: "original-turn".into(),
        call_id: "original-call".into(),
        text: "original fixture proposal".into(),
        reviewed_document: None,
        phase: NotesModelPhase::Closed,
        result: None,
        application_receipt_sha256: None,
        owner_terminal: None,
    }
}

#[test]
fn model_closed_unprepared_slots_recycle_after_capacity_without_an_absence_lookup() {
    let mut slots = BTreeMap::new();
    for index in 0..8 {
        let id = format!("model-{index}");
        slots.insert(id.clone(), (ModelAdmission::NotStarted, closed_view(id)));
    }
    for index in 8..64 {
        let released = slots
            .iter()
            .find(|(_, (admission, view))| admission.can_release_tracking(view))
            .map(|(id, _)| id.clone())
            .expect("a never-prepared closed preview must release its slot");
        slots.remove(&released);
        let id = format!("model-{index}");
        slots.insert(id.clone(), (ModelAdmission::NotStarted, closed_view(id)));
        assert_eq!(slots.len(), 8);
    }
    assert!(slots.values().all(|(admission, view)| {
        *admission == ModelAdmission::NotStarted && admission.can_release_tracking(view)
    }));
}

#[test]
fn model_closed_preparing_or_recovered_slots_keep_original_capacity_until_terminal() {
    let mut preparing = ModelAdmission::NotStarted;
    preparing.mark_may_exist();
    preparing.mark_may_exist();
    assert_eq!(preparing, ModelAdmission::MayExist);
    let mut slots = BTreeMap::new();
    for index in 0..8 {
        let id = format!("model-{index}");
        let mut view = closed_view(id.clone());
        view.result = Some(NotesModelResult::Unknown);
        let admission = if index % 2 == 0 {
            preparing
        } else {
            // A recovered original operation starts in the same conservative
            // state even though this process never called prepare itself.
            ModelAdmission::MayExist
        };
        slots.insert(id, (admission, view));
    }
    assert!(
        slots
            .values()
            .all(|(admission, view)| !admission.can_release_tracking(view))
    );
    let (admission, view) = slots.get_mut("model-0").unwrap();
    // Presentation state cannot override possible original preparation.
    view.result = Some(NotesModelResult::Declined);
    assert!(!admission.can_release_tracking(view));
    view.result = Some(NotesModelResult::Unknown);
    view.owner_terminal = Some(NotesModelTerminalObservation {
        operation_id: "notes.literal.fixture".into(),
        result: NotesModelResult::Applied,
        application_receipt_sha256: "b".repeat(64),
        terminal_event_id: "event:fixture:1".into(),
        terminal_event_sha256: "c".repeat(64),
    });
    assert!(admission.can_release_tracking(view));
    assert_eq!(view.result, Some(NotesModelResult::Unknown));
    let releasable = slots
        .iter()
        .filter(|(_, (admission, view))| admission.can_release_tracking(view))
        .map(|(id, _)| id.as_str())
        .collect::<Vec<_>>();
    assert_eq!(releasable, vec!["model-0"]);
    assert_eq!(slots.len(), 8);
}
