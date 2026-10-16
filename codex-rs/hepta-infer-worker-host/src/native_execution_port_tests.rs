use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;

use super::*;

fn reserved() -> NativeRunRecord {
    NativeRunRecord {
        request: NativeRequest {
            request_id: "native-request-one".to_string(),
            principal_id: "owner-one".to_string(),
            worker_generation: 7,
            model: "model-one".to_string(),
            payload_digest: Digest32::of_bytes(b"durably-admitted-input").to_string(),
        },
        revision: 1,
        state: NativeReservationState::Reserved,
        dispatch: None,
        turn_id: None,
        cancel_requested: false,
        pre_dispatch_stop: None,
        dispatch_rejection: None,
        observation: None,
    }
}

fn bind(record: &NativeRunRecord) -> Result<ReservedNativePortBindingV1, NativePortBindingErrorV1> {
    bind_reserved_native_port_v1(record, "native-request-one", "owner-one", 7, "model-one")
}

#[test]
fn reserved_owner_record_binds_legacy_operation_identity_and_source() {
    let record = reserved();
    let bound = bind(&record).unwrap();
    assert_eq!(
        bound.operation_id,
        StableId::new(format!(
            "native:{}",
            Digest32::of_bytes(record.request.request_id.as_bytes())
        ))
        .unwrap()
    );
    assert_eq!(bound.generation, Generation::new(7).unwrap());
    assert_eq!(
        bound.source_admission_digest.to_string(),
        record.request.payload_digest
    );
}

#[test]
fn original_request_principal_generation_and_model_must_match() {
    let record = reserved();
    for (request_id, principal_id, generation, model, expected) in [
        (
            "wrong-request",
            "owner-one",
            7,
            "model-one",
            NativePortBindingErrorV1::BindingMismatch("request"),
        ),
        (
            "native-request-one",
            "wrong-owner",
            7,
            "model-one",
            NativePortBindingErrorV1::BindingMismatch("principal"),
        ),
        (
            "native-request-one",
            "owner-one",
            8,
            "model-one",
            NativePortBindingErrorV1::BindingMismatch("generation"),
        ),
        (
            "native-request-one",
            "owner-one",
            7,
            "other-model",
            NativePortBindingErrorV1::BindingMismatch("model"),
        ),
    ] {
        assert_eq!(
            bind_reserved_native_port_v1(&record, request_id, principal_id, generation, model),
            Err(expected)
        );
    }
}

#[test]
fn dispatched_reopened_or_partially_settled_state_must_not_create_a_port() {
    let base = reserved();
    for state in [
        NativeReservationState::Dispatching,
        NativeReservationState::Running,
        NativeReservationState::Cancelling,
        NativeReservationState::Indeterminate,
        NativeReservationState::Released,
    ] {
        let mut changed = base.clone();
        changed.state = state;
        assert_eq!(
            bind(&changed),
            Err(NativePortBindingErrorV1::NotFreshlyReserved)
        );
    }

    let mut changed = base.clone();
    changed.revision = 2;
    assert_eq!(
        bind(&changed),
        Err(NativePortBindingErrorV1::NotFreshlyReserved)
    );

    let mut changed = base.clone();
    changed.turn_id = Some("turn-already-started".to_string());
    assert_eq!(
        bind(&changed),
        Err(NativePortBindingErrorV1::NotFreshlyReserved)
    );

    let mut changed = base.clone();
    changed.cancel_requested = true;
    assert_eq!(
        bind(&changed),
        Err(NativePortBindingErrorV1::NotFreshlyReserved)
    );

    let mut changed = base.clone();
    changed.pre_dispatch_stop = Some("stopped".to_string());
    assert_eq!(
        bind(&changed),
        Err(NativePortBindingErrorV1::NotFreshlyReserved)
    );
}

#[test]
fn malformed_or_zero_owner_digest_and_zero_generation_fail_closed() {
    let mut changed = reserved();
    changed.request.payload_digest = "bad".to_string();
    assert_eq!(
        bind(&changed),
        Err(NativePortBindingErrorV1::InvalidSourceDigest)
    );

    let mut changed = reserved();
    changed.request.payload_digest = Digest32::ZERO.to_string();
    assert_eq!(
        bind(&changed),
        Err(NativePortBindingErrorV1::InvalidSourceDigest)
    );

    let mut changed = reserved();
    changed.request.worker_generation = 0;
    assert_eq!(
        bind_reserved_native_port_v1(&changed, "native-request-one", "owner-one", 0, "model-one"),
        Err(NativePortBindingErrorV1::InvalidGeneration)
    );
}
