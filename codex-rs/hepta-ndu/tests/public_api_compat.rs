#![allow(clippy::expect_used)]

use codex_hepta_ndu::NduIterationReceiptV1;
use codex_hepta_ndu::SubjectClass;
use codex_hepta_ndu::ZQ24ConversionReceiptV1;
use codex_hepta_ndu::bind_solver_iteration_receipt_v1;
use codex_hepta_ndu::convert_z_to_original_q24;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

#[test]
fn legacy_v1_public_shapes_and_entry_points_remain_available() {
    let receipt = NduIterationReceiptV1 {
        subject_id: StableId::new("compat-subject").expect("stable id"),
        subject_class: SubjectClass::Agent,
        objective_digest: Digest32::of_bytes(b"objective"),
        generation: Generation::new(1).expect("generation"),
        event_digest: Digest32::of_bytes(b"event"),
        coefficient_digest: Digest32::of_bytes(b"coefficient"),
        iteration: 1,
        predecessor_revision: Revision::new(1).expect("revision"),
        next_revision: Revision::new(2).expect("revision"),
        residual_raw: 0,
        projection_count: 0,
        state_digest: Digest32::of_bytes(b"state"),
        solve_input_digest: Digest32::of_bytes(b"solve-input"),
        receipt_digest: Digest32::of_bytes(b"legacy-receipt"),
        authority: AuthorityPosture::DENY_ALL,
    };
    assert_eq!(receipt.iteration, 1);

    let z = ZQ24ConversionReceiptV1 {
        original_z: vec![vec![0.0]],
        q24_raw: vec![vec![0]],
        maximum_absolute_quantization_error: 0.0,
        profile_digest: Digest32::of_bytes(b"profile"),
        source_digest: Digest32::of_bytes(b"source"),
        receipt_digest: Digest32::of_bytes(b"receipt"),
        authority: AuthorityPosture::DENY_ALL,
    };
    assert_eq!(z.q24_raw[0][0], 0);

    let _legacy_bind = bind_solver_iteration_receipt_v1;
    let _legacy_convert = convert_z_to_original_q24;
}
