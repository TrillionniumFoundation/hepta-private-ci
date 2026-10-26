use super::*;
use pretty_assertions::assert_eq;

#[test]
fn original_actions_remain_fifo_while_refresh_is_coalesced_and_cannot_fill_them() {
    let queue = NotesUiQueue::new();
    for _ in 0..200 {
        queue.request(ObjectiveCommand::Availability {});
    }
    let submit = ObjectiveCommand::Submit {
        intent: ObjectiveIntent {
            client_intent_id: "one".into(),
            text: "literal".into(),
        },
    };
    let cancel = ObjectiveCommand::Cancel {
        client_intent_id: "one".into(),
    };
    queue.request(submit.clone());
    queue.request(cancel.clone());
    assert_eq!(queue.take(Instant::now()).unwrap().unwrap().command, submit);
    assert_eq!(queue.take(Instant::now()).unwrap().unwrap().command, cancel);
    assert_eq!(
        queue.take(Instant::now()).unwrap().unwrap().command,
        ObjectiveCommand::Availability {}
    );
    assert!(queue.take(Instant::now()).unwrap().is_none());
}

#[test]
fn expired_actions_never_reach_worker_and_do_not_erase_earlier_retention() {
    let queue = NotesUiQueue::new();
    let command = ObjectiveCommand::Cancel {
        client_intent_id: "one".into(),
    };
    queue.request(command.clone());
    let mut retained = ObjectiveObservation::new(Some("one".into()), ObjectiveStage::SubmitUnknown);
    retained.request_retained = true;
    queue.update(retained).unwrap();
    assert!(
        queue
            .take(Instant::now() + ACTION_LIFETIME)
            .unwrap()
            .is_none()
    );
    let observed = queue.request(command);
    assert_eq!(
        (observed.stage, observed.request_retained, observed.issue),
        (
            ObjectiveStage::SubmitUnknown,
            true,
            Some(ObjectiveHostIssue::Unavailable)
        )
    );
}

#[test]
fn bounded_actions_and_views_refuse_new_work_without_replacing_existing_state() {
    let queue = NotesUiQueue::new();
    for index in 0..ACTION_CAPACITY {
        assert_eq!(
            queue
                .request(ObjectiveCommand::Cancel {
                    client_intent_id: format!("intent-{index}"),
                })
                .issue,
            None
        );
    }
    assert_eq!(
        queue
            .request(ObjectiveCommand::Cancel {
                client_intent_id: "overflow".into(),
            })
            .issue,
        Some(ObjectiveHostIssue::Capacity)
    );
    for index in 0..MAX_OBJECTIVE_VIEWS {
        queue.request(ObjectiveCommand::Status {
            client_intent_id: format!("view-{index}"),
        });
    }
    assert_eq!(
        queue
            .request(ObjectiveCommand::Status {
                client_intent_id: "new-view".into(),
            })
            .issue,
        Some(ObjectiveHostIssue::Capacity)
    );
}

#[test]
fn same_intent_terminal_survives_later_transport_views_and_rejects_replacement() {
    let queue = NotesUiQueue::new();
    let command = ObjectiveCommand::Status {
        client_intent_id: "original-id".into(),
    };
    queue.request(command.clone());
    let mut observed =
        ObjectiveObservation::new(Some("original-id".into()), ObjectiveStage::Admitted);
    observed.notes_terminal = Some(NotesModelTerminalObservation {
        operation_id: "notes.literal.fixture".into(),
        result: NotesModelResult::Applied,
        application_receipt_sha256: "a".repeat(64),
        terminal_event_id: "event:fixture:1".into(),
        terminal_event_sha256: "b".repeat(64),
    });
    queue.update(observed.clone()).unwrap();
    let mut unavailable =
        ObjectiveObservation::new(Some("original-id".into()), ObjectiveStage::SubmitUnknown);
    unavailable.issue = Some(ObjectiveHostIssue::TransportUnknown);
    queue.update(unavailable).unwrap();
    assert_eq!(
        queue.current(&command).unwrap().notes_terminal,
        observed.notes_terminal
    );
    let mut replaced = observed.clone();
    replaced
        .notes_terminal
        .as_mut()
        .unwrap()
        .terminal_event_sha256 = "c".repeat(64);
    assert!(queue.update(replaced).is_err());
    assert_eq!(
        queue.current(&command).unwrap().notes_terminal,
        observed.notes_terminal
    );
}
