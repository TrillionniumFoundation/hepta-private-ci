use super::*;

fn initial(cell: &str) -> State {
    State {
        admin: [2; 32],
        cell: Cell {
            id: cell.into(),
            owner: [3; 32],
            epoch: 1,
            bundle: [1; 32],
            phase: CellPhase::Active,
        },
        transfers: BTreeMap::new(),
    }
}

fn prepare(cell: &str, transfer: &str) -> Request {
    Request {
        cell: cell.into(),
        transfer: transfer.into(),
        actor: [3; 32],
        expected_epoch: 1,
        expected_bundle: [1; 32],
        operation: Operation::Prepare { target: [4; 32] },
    }
}

#[test]
fn invalid_identifier_bytes_reject_every_transition_without_mutating_state() {
    let state = initial("cell");
    let before = state.clone();
    for (cell, transfer) in [
        (String::new(), "transfer".into()),
        ("a".repeat(257), "transfer".into()),
        ("界".repeat(86), "transfer".into()),
        ("cell".into(), String::new()),
        ("cell".into(), "t".repeat(129)),
        ("cell".into(), "🙂".repeat(33)),
    ] {
        for operation in [
            Operation::Prepare { target: [4; 32] },
            Operation::RecoverPrepare { target: [4; 32] },
            Operation::Ready {
                verified_bundle: [1; 32],
            },
            Operation::Commit,
            Operation::Abort,
        ] {
            let request = Request {
                operation,
                ..prepare(&cell, &transfer)
            };
            assert_eq!(
                transition(&state, &request, Sources::Current),
                Err(Rejection::InvalidIdentifier)
            );
            assert_eq!(state, before);
        }
    }
    let next = transition(&state, &prepare("cell", "valid"), Sources::Current).unwrap();
    let abort = Request {
        expected_epoch: 2,
        operation: Operation::Abort,
        ..prepare("cell", "valid")
    };
    let aborted = transition(&next, &abort, Sources::Stale).unwrap();
    assert_eq!(aborted.cell.phase, CellPhase::Active);
    assert_eq!(aborted.cell.owner, state.cell.owner);
    assert_eq!(aborted.cell.epoch, 3);
}

#[test]
fn exact_utf8_boundary_names_can_complete_handoff() {
    for (cell, transfer) in [
        ("a".repeat(256), "t".repeat(128)),
        (format!("{}a", "界".repeat(85)), "🙂".repeat(32)),
        ("é".repeat(128), format!("{}ab", "界".repeat(42))),
    ] {
        let state = initial(&cell);
        let mut request = prepare(&cell, &transfer);
        let prepared = transition(&state, &request, Sources::Current).unwrap();
        request.actor = [4; 32];
        request.expected_epoch = 2;
        request.operation = Operation::Ready {
            verified_bundle: [1; 32],
        };
        let ready = transition(&prepared, &request, Sources::Current).unwrap();
        request.operation = Operation::Commit;
        let committed = transition(&ready, &request, Sources::Current).unwrap();
        let mut expected = ready;
        expected.cell.owner = [4; 32];
        expected.cell.epoch = 3;
        expected.cell.phase = CellPhase::Active;
        expected.transfers.get_mut(&transfer).unwrap().phase = TransferPhase::Committed;
        assert_eq!(committed, expected);
    }
}

#[test]
fn unicode_normalization_never_aliases_a_different_cell() {
    let state = initial("e\u{301}");
    assert_eq!(
        transition(&state, &prepare("é", "valid"), Sources::Current),
        Err(Rejection::StaleCell)
    );
    let accepted = transition(&state, &prepare("e\u{301}", "valid"), Sources::Current).unwrap();
    assert_eq!(accepted.cell.id, state.cell.id);
}
