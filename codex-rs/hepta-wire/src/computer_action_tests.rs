use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn frame(
    opcode: ComputerActionOpcodeV1,
    target_ref: Option<StableId>,
    payload: ComputerActionPayloadV1,
) -> ComputerActionFrameV1 {
    let argument_payload_digest =
        computer_action_payload_digest_v1(opcode, &payload).expect("payload digest");
    ComputerActionFrameV1 {
        operation_id: id("operation-1"),
        subject_id: id("subject-1"),
        actuator_id: id("native-shell"),
        opcode,
        target_ref,
        body_generation: 5,
        session_generation: 8,
        observation_revision: 13,
        deadline_monotonic_micros: 21,
        precondition_digest: digest("precondition"),
        argument_payload_digest,
        final_payload_digest: digest("final-payload"),
        expected_postcondition_digest: digest("postcondition"),
        payload,
        authority: AuthorityPosture::DENY_ALL,
    }
}

#[test]
fn every_registered_opcode_round_trips_canonically() {
    let cases = [
        frame(
            ComputerActionOpcodeV1::FocusTarget,
            Some(id("target-1")),
            ComputerActionPayloadV1::None,
        ),
        frame(
            ComputerActionOpcodeV1::ActivateTarget,
            Some(id("target-1")),
            ComputerActionPayloadV1::None,
        ),
        frame(
            ComputerActionOpcodeV1::TypeTextReference,
            Some(id("target-1")),
            ComputerActionPayloadV1::Reference(id("text-ref-1")),
        ),
        frame(
            ComputerActionOpcodeV1::Scroll,
            Some(id("target-1")),
            ComputerActionPayloadV1::ScrollDelta {
                horizontal_milli: 100,
                vertical_milli: -200,
            },
        ),
        frame(
            ComputerActionOpcodeV1::NavigateReference,
            None,
            ComputerActionPayloadV1::Reference(id("url-ref-1")),
        ),
        frame(
            ComputerActionOpcodeV1::OpenPathReference,
            None,
            ComputerActionPayloadV1::Reference(id("path-ref-1")),
        ),
        frame(
            ComputerActionOpcodeV1::RevealPathReference,
            None,
            ComputerActionPayloadV1::Reference(id("path-ref-1")),
        ),
        frame(
            ComputerActionOpcodeV1::CopyTextReference,
            None,
            ComputerActionPayloadV1::Reference(id("text-ref-1")),
        ),
        frame(
            ComputerActionOpcodeV1::NotifyReference,
            None,
            ComputerActionPayloadV1::Reference(id("notice-ref-1")),
        ),
        frame(
            ComputerActionOpcodeV1::WaitObservation,
            None,
            ComputerActionPayloadV1::WaitMicros(1_000),
        ),
        frame(
            ComputerActionOpcodeV1::RequestEvidence,
            None,
            ComputerActionPayloadV1::None,
        ),
        frame(
            ComputerActionOpcodeV1::Stop,
            None,
            ComputerActionPayloadV1::None,
        ),
    ];
    for case in cases {
        let first = encode_computer_action_frame_v1(&case).expect("encode");
        let decoded = decode_computer_action_frame_v1(&first).expect("decode");
        assert_eq!(decoded, case);
        assert_eq!(
            encode_computer_action_frame_v1(&decoded).expect("re-encode"),
            first
        );
    }
}

#[test]
fn payload_and_target_semantics_fail_closed() {
    let mut targetless = frame(
        ComputerActionOpcodeV1::FocusTarget,
        Some(id("target-1")),
        ComputerActionPayloadV1::None,
    );
    targetless.target_ref = None;
    assert_eq!(
        encode_computer_action_frame_v1(&targetless),
        Err(ComputerActionCodecError::TargetMismatch)
    );

    let mut wrong_payload = frame(
        ComputerActionOpcodeV1::Stop,
        None,
        ComputerActionPayloadV1::None,
    );
    wrong_payload.payload = ComputerActionPayloadV1::Reference(id("reference-1"));
    assert_eq!(
        encode_computer_action_frame_v1(&wrong_payload),
        Err(ComputerActionCodecError::PayloadMismatch)
    );
}

#[test]
fn authority_binding_changes_with_final_payload_and_target_generation() {
    let first = frame(
        ComputerActionOpcodeV1::OpenPathReference,
        None,
        ComputerActionPayloadV1::Reference(id("path-ref-1")),
    );
    let first_digest =
        computer_action_authority_binding_digest_v1(&first).expect("authority binding");
    assert_eq!(
        first_digest,
        computer_action_frame_digest_v1(&first).expect("frame digest")
    );

    let mut changed_payload = first.clone();
    changed_payload.final_payload_digest = digest("resolved-final-payload-2");
    assert_ne!(
        first_digest,
        computer_action_authority_binding_digest_v1(&changed_payload)
            .expect("changed payload binding")
    );

    let mut changed_generation = first;
    changed_generation.session_generation += 1;
    assert_ne!(
        first_digest,
        computer_action_authority_binding_digest_v1(&changed_generation)
            .expect("changed generation binding")
    );
}

#[test]
fn changed_payload_digest_and_authority_are_rejected() {
    let mut value = frame(
        ComputerActionOpcodeV1::OpenPathReference,
        None,
        ComputerActionPayloadV1::Reference(id("path-ref-1")),
    );
    value.argument_payload_digest = digest("changed");
    assert_eq!(
        encode_computer_action_frame_v1(&value),
        Err(ComputerActionCodecError::PayloadDigestMismatch)
    );

    value.argument_payload_digest =
        computer_action_payload_digest_v1(value.opcode, &value.payload).expect("digest");
    assert!(!value.authority.grants_any());
    assert!(AuthorityPosture::try_from_wire_bytes(&[1]).is_err());
}

#[test]
fn checksum_and_unknown_opcode_are_rejected() {
    let value = frame(
        ComputerActionOpcodeV1::WaitObservation,
        None,
        ComputerActionPayloadV1::WaitMicros(10),
    );
    let mut bytes = encode_computer_action_frame_v1(&value).expect("encode");
    bytes[20] ^= 1;
    assert_eq!(
        decode_computer_action_frame_v1(&bytes),
        Err(ComputerActionCodecError::ChecksumMismatch)
    );

    let mut bytes = encode_computer_action_frame_v1(&value).expect("encode");
    bytes[6..8].copy_from_slice(&99_u16.to_be_bytes());
    let body_len = bytes.len() - CHECKSUM_BYTES;
    let checksum = Digest32::of_parts(&[FRAME_DOMAIN, &bytes[..body_len]]);
    bytes[body_len..].copy_from_slice(checksum.as_array());
    assert_eq!(
        decode_computer_action_frame_v1(&bytes),
        Err(ComputerActionCodecError::UnknownOpcode(99))
    );
}

#[test]
fn generation_deadline_and_scroll_bounds_are_enforced() {
    let mut value = frame(
        ComputerActionOpcodeV1::Scroll,
        Some(id("target-1")),
        ComputerActionPayloadV1::ScrollDelta {
            horizontal_milli: 0,
            vertical_milli: 1,
        },
    );
    value.body_generation = 0;
    assert_eq!(
        encode_computer_action_frame_v1(&value),
        Err(ComputerActionCodecError::InvalidGeneration)
    );

    value.body_generation = 1;
    value.deadline_monotonic_micros = 0;
    assert_eq!(
        encode_computer_action_frame_v1(&value),
        Err(ComputerActionCodecError::InvalidDeadline)
    );

    value.deadline_monotonic_micros = 1;
    value.payload = ComputerActionPayloadV1::ScrollDelta {
        horizontal_milli: 0,
        vertical_milli: 0,
    };
    assert_eq!(
        computer_action_payload_digest_v1(value.opcode, &value.payload),
        Err(ComputerActionCodecError::PayloadLimit)
    );
}

#[test]
fn cross_runtime_golden_frame_is_frozen() {
    let value = frame(
        ComputerActionOpcodeV1::OpenPathReference,
        None,
        ComputerActionPayloadV1::Reference(id("path-ref-1")),
    );
    let bytes = encode_computer_action_frame_v1(&value).expect("encode");
    let hex = bytes
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    assert_eq!(
        hex,
        "48414331000100060000000000000000000000050000000000000008000000000000000d0000000000000015000b6f7065726174696f6e2d3100097375626a6563742d31000c6e61746976652d7368656c6cac27cf5248407a85a0cfe7e4b899851d938c9b7d25e4039993332b1d769924dcb0ce1457f27c72529e170e766a645ecf041df62b3c7f6015b02063216029744d4e291d88e42d06d51721cbd10ce87fb65b5410fd880d493d2d974f4125b5fe2825bcb6e219f560fd3fb6419d9655353a0b17cffa60ecf00ed4715b2f9f5928680000000c000a706174682d7265662d310b86962fda869a8c716db9b07513eae16de01d804e38608bdc105558012484ac"
    );
}

#[test]
fn portable_integer_boundary_matches_the_javascript_consumer() {
    let mut value = frame(
        ComputerActionOpcodeV1::Stop,
        None,
        ComputerActionPayloadV1::None,
    );
    value.body_generation = MAX_PORTABLE_INTEGER;
    value.session_generation = MAX_PORTABLE_INTEGER;
    value.observation_revision = MAX_PORTABLE_INTEGER;
    value.deadline_monotonic_micros = MAX_PORTABLE_INTEGER;
    let encoded = encode_computer_action_frame_v1(&value).expect("portable maximum");
    assert_eq!(
        decode_computer_action_frame_v1(&encoded).expect("decode maximum"),
        value
    );
    for offset in [12, 20, 28, 36] {
        let mut hostile = encoded.clone();
        hostile[offset..offset + 8].copy_from_slice(&(MAX_PORTABLE_INTEGER + 1).to_be_bytes());
        let body_len = hostile.len() - CHECKSUM_BYTES;
        let checksum = Digest32::of_parts(&[FRAME_DOMAIN, &hostile[..body_len]]);
        hostile[body_len..].copy_from_slice(checksum.as_array());
        assert_eq!(
            decode_computer_action_frame_v1(&hostile),
            Err(if offset == 36 {
                ComputerActionCodecError::InvalidDeadline
            } else {
                ComputerActionCodecError::InvalidGeneration
            }),
        );
    }
}
