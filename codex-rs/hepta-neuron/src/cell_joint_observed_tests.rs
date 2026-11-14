use super::JointGenerationCommandV2;
use super::JointGenerationDeliveryContractV2;
use super::JointGenerationInputV2;
use super::request_bytes;
use crate::CellGenerationErrorV2;
use crate::CellGenerationRequestV2;
use crate::CellGenerationScopeV2;
use crate::CellRuntimeSnapshotV2;

fn input() -> JointGenerationInputV2 {
    JointGenerationInputV2 {
        public_digest: [2; 32],
        delivery: JointGenerationDeliveryContractV2 {
            required_mask: 8,
            optional_mask: 1,
            budget_total_micros: 1_000_000,
            task_deadline_micros: 1_000_100,
        },
        command: JointGenerationCommandV2::Auto,
    }
}

fn request(input: &JointGenerationInputV2) -> CellGenerationRequestV2 {
    CellGenerationRequestV2 {
        operation_id: "observed-auto-1".into(),
        task_digest: [3; 32],
        source_frontier: [4; 32],
        predecessor: CellRuntimeSnapshotV2 {
            scope: CellGenerationScopeV2 {
                principal_digest: [5; 32],
                agent_id: "agent".into(),
                cell_id: "cell".into(),
                run_id: "run".into(),
            },
            manifest_digest: [6; 32],
            generation: 1,
            writer_epoch: 1,
            revision: 0,
            state: vec![7],
            prefix: vec![8],
            stopped: false,
        },
        input: serde_json::to_vec(input).unwrap(),
        admitted_at_micros: 100,
        deadline_micros: 1_000_100,
    }
}

#[test]
fn host_clock_derives_remaining_and_auto_fraction_from_one_contract() {
    let input = input();
    let request = request(&input);
    let bytes = request_bytes(&request, &input, &[1], &[2], /*now_micros*/ 500_100).unwrap();
    assert_eq!(&bytes[..8], b"HJREQV02");
    assert_eq!(&bytes[8..40], request.digest().unwrap().as_slice());
    assert_eq!(&bytes[40..42], &[8, 1]);
    assert_eq!(
        u64::from_le_bytes(bytes[42..50].try_into().unwrap()),
        1_000_000
    );
    assert_eq!(
        u64::from_le_bytes(bytes[50..58].try_into().unwrap()),
        500_000
    );
    assert_eq!(bytes[bytes.len() - 5], 2);
    assert_eq!(
        u32::from_le_bytes(bytes[bytes.len() - 4..].try_into().unwrap()),
        500_000
    );
}

#[test]
fn deadline_and_obligation_changes_alter_the_bound_owner_identity() {
    let mut input = input();
    let original = request_bytes(
        &request(&input),
        &input,
        &[1],
        &[2],
        /*now_micros*/ 500_100,
    )
    .unwrap();
    input.delivery.task_deadline_micros += 1;
    let mut shifted = request(&input);
    shifted.admitted_at_micros += 1;
    shifted.deadline_micros += 1;
    let changed = request_bytes(&shifted, &input, &[1], &[2], /*now_micros*/ 500_100).unwrap();
    assert_ne!(&original[58..90], &changed[58..90]);
    input.delivery.required_mask = 1;
    input.delivery.optional_mask = 8;
    shifted.input = serde_json::to_vec(&input).unwrap();
    let obligations = request_bytes(&shifted, &input, &[1], &[2], /*now_micros*/ 500_100).unwrap();
    assert_ne!(&changed[58..90], &obligations[58..90]);
}

#[test]
fn clock_regression_and_expired_or_changed_request_deadline_are_rejected() {
    let input = input();
    let mut request = request(&input);
    assert_eq!(
        request_bytes(&request, &input, &[1], &[2], /*now_micros*/ 99),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(
        request_bytes(&request, &input, &[1], &[2], /*now_micros*/ 1_000_100),
        Err(CellGenerationErrorV2::Deadline)
    );
    request.deadline_micros += 1;
    assert_eq!(
        request_bytes(&request, &input, &[1], &[2], /*now_micros*/ 500_100),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    request.deadline_micros -= 2;
    assert_eq!(
        request_bytes(&request, &input, &[1], &[2], /*now_micros*/ 500_100),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
}
