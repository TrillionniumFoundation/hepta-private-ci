use super::commands;
use super::commands::Command;
use super::wire;
use super::wire::FINAL;
use super::wire::FIRST;
use super::wire::Operation;
use super::wire::Request;
use super::wire::State;
use super::wire::WireError;
use crate::proposed_plan::PlanTag;
use crate::tagged_line_parser::TaggedLineSegment;
use pretty_assertions::assert_eq;

const NORMAL: State = State {
    detect: 0,
    ..State::INITIAL
};

fn push(payload: &str) -> Request<'_> {
    Request {
        operation: Operation::Push,
        flags: FIRST | FINAL,
        state: State::INITIAL,
        payload,
    }
}

fn packet(request: &Request<'_>, state: State, records: &[[u64; 4]]) -> (u64, Vec<u8>) {
    let mut output = Vec::new();
    for word in [
        state.active,
        state.detect,
        state.prefix_id,
        state.leading_bytes,
        state.trailing_bytes,
        state.pending_bytes,
        state.call_open,
        state.last_text_kind,
        records.len() as u64,
        0,
    ] {
        output.extend_from_slice(&word.to_le_bytes());
    }
    for record in records {
        for word in record {
            output.extend_from_slice(&word.to_le_bytes());
        }
    }
    let returned = output.len() as u64;
    let capacity = match request.capacity() {
        Ok(capacity) => capacity.max(output.len()),
        Err(error) => panic!("fixture capacity: {error:?}"),
    };
    output.resize(capacity, /*value*/ 0xa5);
    (returned, output)
}

fn admitted(
    request: &Request<'_>,
    pending: &str,
    segments: &[TaggedLineSegment<PlanTag>],
    returned: u64,
    output: &[u8],
) -> Result<(State, Vec<Command>), WireError> {
    let response = wire::decode(request, pending.len(), returned, output)?;
    let commands = commands::decode(request, &response, pending.len(), segments)?;
    Ok((response.state, commands))
}

#[test]
fn complete_validation_precedes_mechanical_append_flush_and_utf8_input() {
    let request = push("xé");
    let records = [[0, 0, 1, 0], [1, 0, 1, 0], [4, 1, 2, 1]];
    let (returned, output) = packet(&request, NORMAL, &records);
    let mut pending = String::new();
    let mut segments = Vec::new();
    let Ok((state, commands)) = admitted(&request, &pending, &segments, returned, &output) else {
        panic!("valid literal command frame rejected");
    };
    commands::apply(commands, request.payload, &mut pending, &mut segments);
    assert_eq!(
        (state, pending, segments),
        (
            NORMAL,
            String::new(),
            vec![TaggedLineSegment::Normal("xé".to_owned())],
        )
    );
}

#[test]
fn continuation_is_explicit_across_internal_frames() {
    let first = Request {
        flags: FIRST,
        ..push("x")
    };
    let open = State {
        call_open: 1,
        last_text_kind: 1,
        ..NORMAL
    };
    let (returned, output) = packet(&first, open, &[[0, 0, 1, 0], [1, 0, 1, 0]]);
    let mut pending = String::new();
    let mut segments = Vec::new();
    let Ok((state, commands)) = admitted(&first, &pending, &segments, returned, &output) else {
        panic!("valid first frame rejected");
    };
    commands::apply(commands, first.payload, &mut pending, &mut segments);
    let last = Request {
        flags: FINAL,
        state,
        ..push("y")
    };
    let (returned, output) = packet(&last, NORMAL, &[[4, 0, 1, 1]]);
    let Ok((state, commands)) = admitted(&last, &pending, &segments, returned, &output) else {
        panic!("valid continuation rejected");
    };
    commands::apply(commands, last.payload, &mut pending, &mut segments);
    assert_eq!(
        (state, pending, segments),
        (
            NORMAL,
            String::new(),
            vec![TaggedLineSegment::Normal("xy".to_owned())],
        )
    );
}

#[test]
fn decoder_does_not_invent_merging_for_a_zero_continuation() {
    let request = Request {
        flags: FINAL,
        state: State {
            call_open: 1,
            last_text_kind: 1,
            ..NORMAL
        },
        ..push("right")
    };
    let (returned, output) = packet(&request, NORMAL, &[[4, 0, 5, 0]]);
    let mut pending = String::new();
    let mut segments = vec![TaggedLineSegment::Normal("left".to_owned())];
    let Ok((_, commands)) = admitted(&request, &pending, &segments, returned, &output) else {
        panic!("structurally valid explicit new segment rejected");
    };
    commands::apply(commands, request.payload, &mut pending, &mut segments);
    assert_eq!(
        (pending, segments),
        (
            String::new(),
            vec![
                TaggedLineSegment::Normal("left".to_owned()),
                TaggedLineSegment::Normal("right".to_owned()),
            ],
        )
    );
}

#[test]
fn wrapper_status_errors_and_inconsistent_extents_are_rejected() {
    let request = push("x");
    let (returned, output) = packet(&request, NORMAL, &[[4, 0, 1, 0]]);
    for (value, error) in [
        (returned | (1_u64 << 32), WireError::WrapperStatus),
        (4_294_967_295, WireError::NativeError),
        (4_294_967_294, WireError::NativeError),
        (79, WireError::Result),
        (returned + 1, WireError::Result),
    ] {
        assert_eq!(admitted(&request, "", &[], value, &output), Err(error));
    }
    let mut overflow_count = output.clone();
    overflow_count[64..72].copy_from_slice(&u64::MAX.to_le_bytes());
    assert_eq!(
        admitted(&request, "", &[], returned, &overflow_count),
        Err(WireError::Result)
    );
    let mut reserved = output;
    reserved[72..80].copy_from_slice(&1_u64.to_le_bytes());
    assert_eq!(
        admitted(&request, "", &[], returned, &reserved),
        Err(WireError::Result)
    );
}

#[test]
fn full_width_state_and_public_boundary_constraints_are_checked() {
    let request = push("x");
    for state in [
        State {
            active: 1_u64 << 32,
            ..NORMAL
        },
        State {
            detect: 2,
            ..NORMAL
        },
        State {
            prefix_id: 31,
            ..State::INITIAL
        },
        State {
            last_text_kind: 3,
            ..NORMAL
        },
        State {
            call_open: 1,
            ..NORMAL
        },
        State {
            trailing_bytes: 1,
            pending_bytes: 1,
            ..State::INITIAL
        },
        State {
            leading_bytes: u64::MAX,
            prefix_id: 1,
            ..State::INITIAL
        },
        State {
            pending_bytes: 1,
            ..NORMAL
        },
    ] {
        let (returned, output) = packet(&request, state, &[[4, 0, 1, 0]]);
        assert_eq!(
            admitted(&request, "", &[], returned, &output),
            Err(WireError::State)
        );
    }
}

#[test]
fn malformed_command_shapes_and_scalar_ranges_are_rejected() {
    let request = push("é");
    for record in [
        [99, 0, 2, 0],
        [4, 1, 1, 0],
        [4, 0, 0, 0],
        [4, 0, 1, 0],
        [4, 0, u64::MAX, 0],
        [4, u64::MAX, 2, 0],
        [4, 0, 2, 2],
        [0, 0, 2, 1],
        [1, 0, 2, 0],
        [3, 1, 2, 0],
        [6, 0, 1, 0],
        [7, 0, 0, 1],
    ] {
        let (returned, output) = packet(&request, NORMAL, &[record]);
        assert_eq!(
            admitted(&request, "", &[], returned, &output),
            Err(WireError::Command)
        );
    }
    for records in [vec![], vec![[4, 0, 2, 0], [4, 0, 2, 1]]] {
        let (returned, output) = packet(&request, NORMAL, &records);
        assert_eq!(
            admitted(&request, "", &[], returned, &output),
            Err(WireError::Command)
        );
    }
}

#[test]
fn missing_pending_bytes_and_wrong_continuation_destinations_are_rejected() {
    let request = push("x");
    for records in [
        vec![[0, 0, 1, 0]],
        vec![[4, 0, 1, 1]],
        vec![[6, 0, 0, 0], [5, 0, 1, 1]],
    ] {
        let (returned, output) = packet(&request, NORMAL, &records);
        assert_eq!(
            admitted(&request, "", &[], returned, &output),
            Err(WireError::Command)
        );
    }
    let request = Request {
        flags: FINAL,
        state: State {
            call_open: 1,
            last_text_kind: 1,
            ..NORMAL
        },
        ..push("x")
    };
    let (returned, output) = packet(&request, NORMAL, &[[4, 0, 1, 1]]);
    for existing in [
        vec![],
        vec![TaggedLineSegment::TagDelta(
            PlanTag::ProposedPlan,
            "old".to_owned(),
        )],
        vec![TaggedLineSegment::TagStart(PlanTag::ProposedPlan)],
    ] {
        assert_eq!(
            admitted(&request, "", &existing, returned, &output),
            Err(WireError::Command)
        );
    }
}

#[test]
fn a_late_invalid_command_cannot_partially_change_host_containers() {
    let pending = " ".to_owned();
    let segments = Vec::new();
    let snapshot = (pending.clone(), segments.clone());
    let request = Request {
        state: State {
            leading_bytes: 1,
            pending_bytes: 1,
            ..State::INITIAL
        },
        ..push("x")
    };
    let records = [[0, 0, 1, 0], [1, 0, 2, 0], [99, 0, 0, 0]];
    let (returned, output) = packet(&request, NORMAL, &records);
    assert_eq!(
        admitted(&request, &pending, &segments, returned, &output),
        Err(WireError::Command)
    );
    assert_eq!((pending, segments), snapshot);
}

#[test]
fn finish_requires_reset_and_allows_only_non_input_commands() {
    let request = Request {
        operation: Operation::Finish,
        flags: 0,
        state: State {
            active: 1,
            prefix_id: 16,
            pending_bytes: 2,
            ..State::INITIAL
        },
        payload: "",
    };
    let mut pending = "</".to_owned();
    let mut segments = Vec::new();
    let (returned, output) = packet(&request, State::INITIAL, &[[2, 0, 2, 0], [7, 0, 0, 0]]);
    let Ok((state, commands)) = admitted(&request, &pending, &segments, returned, &output) else {
        panic!("valid finish rejected");
    };
    commands::apply(commands, "", &mut pending, &mut segments);
    assert_eq!(
        (state, pending, segments),
        (
            State::INITIAL,
            String::new(),
            vec![
                TaggedLineSegment::TagDelta(PlanTag::ProposedPlan, "</".to_owned()),
                TaggedLineSegment::TagEnd(PlanTag::ProposedPlan),
            ],
        )
    );
    let (returned, output) = packet(&request, NORMAL, &[]);
    assert_eq!(
        admitted(&request, "</", &[], returned, &output),
        Err(WireError::State)
    );
    let (returned, output) = packet(&request, State::INITIAL, &[[4, 0, 1, 0]]);
    assert_eq!(
        admitted(&request, "</", &[], returned, &output),
        Err(WireError::Command)
    );
}

#[test]
fn inspect_requires_identical_state_and_no_commands() {
    let state = State {
        prefix_id: 1,
        pending_bytes: 1,
        ..State::INITIAL
    };
    let request = Request {
        operation: Operation::Inspect,
        flags: 0,
        state,
        payload: "",
    };
    let (returned, output) = packet(&request, state, &[]);
    assert_eq!(
        admitted(&request, "<", &[], returned, &output),
        Ok((state, vec![]))
    );
    let (returned, output) = packet(&request, State::INITIAL, &[]);
    assert_eq!(
        admitted(&request, "<", &[], returned, &output),
        Err(WireError::State)
    );
    let (returned, output) = packet(&request, state, &[[3, 0, 1, 0]]);
    assert_eq!(
        admitted(&request, "<", &[], returned, &output),
        Err(WireError::Result)
    );
}

#[test]
fn request_validation_binds_pending_and_public_call_ownership() {
    let request = push("x");
    let (returned, output) = packet(&request, NORMAL, &[[4, 0, 1, 0]]);
    assert_eq!(
        admitted(&request, " ", &[], returned, &output),
        Err(WireError::Request)
    );
    let existing = vec![TaggedLineSegment::Normal("earlier call".to_owned())];
    assert_eq!(
        admitted(&request, "", &existing, returned, &output),
        Err(WireError::Command)
    );
    for flags in [0, 2, 4, 1_u64 << 32] {
        let invalid = Request { flags, ..request };
        assert_eq!(
            admitted(&invalid, "", &[], returned, &output),
            Err(WireError::Request)
        );
    }
}
