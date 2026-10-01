use super::*;
use crate::durable_control::Error;
use crate::durable_control::native::NativeCognitivePreparation;

fn preparation() -> NativeCognitivePreparation {
    NativeCognitivePreparation {
        read_request_id: 1,
        sequence: 7,
        event_digest: "4".repeat(64),
        chain_digest: "5".repeat(64),
    }
}

#[test]
fn persisted_preparation_reopens_without_upgrading_unknown_delivery() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request(), /*maximum_in_flight*/ 1).unwrap();
    let mut dispatch = dispatch();
    dispatch.cognitive_preparation = Some(preparation());
    owner.dispatch_native("request-1", dispatch).unwrap();
    owner.cancel_native("request-1").unwrap();
    let expected = owner.native_record("request-1").unwrap().clone();
    let delivery = owner.cognitive_context_delivery(&request(), context_digest()).unwrap().unwrap();
    let expected_digest = delivery.binding_digest();
    assert_eq!(delivery.preparation(), Some(&preparation()));
    assert_eq!(delivery.state(), CognitiveContextDeliveryStateV1::AcceptanceUnknown);
    drop(owner);
    let reopened = fixture.open();
    assert_eq!(reopened.native_record("request-1"), Some(&expected));
    let delivery = reopened.cognitive_context_delivery(&request(), context_digest()).unwrap().unwrap();
    assert_eq!(delivery.preparation(), Some(&preparation()));
    assert_eq!(delivery.binding_digest(), expected_digest);
    assert_eq!(delivery.state(), CognitiveContextDeliveryStateV1::AcceptanceUnknown);
}

#[test]
fn invalid_preparation_cannot_enter_the_native_journal() {
    let mut invalid = Vec::new();
    let mut receipt = preparation();
    receipt.sequence = 0;
    invalid.push((Some(context_digest().to_string()), receipt));
    let mut receipt = preparation();
    receipt.event_digest = "0".repeat(64);
    invalid.push((Some(context_digest().to_string()), receipt));
    let mut receipt = preparation();
    receipt.chain_digest = "g".repeat(64);
    invalid.push((Some(context_digest().to_string()), receipt));
    invalid.push((None, preparation()));
    for (context, receipt) in invalid {
        let fixture = Fixture::new();
        let mut owner = fixture.open();
        let reserved = owner.reserve_native(request(), /*maximum_in_flight*/ 1).unwrap();
        let before = std::fs::read(fixture.0.join("native.journal")).unwrap();
        let mut dispatch = dispatch();
        dispatch.owner_context_digest = context;
        dispatch.cognitive_preparation = Some(receipt);
        assert!(matches!(owner.dispatch_native("request-1", dispatch), Err(Error::InvalidIdentity(_) | Error::InvalidDigest(_))));
        assert_eq!(owner.native_record("request-1"), Some(&reserved));
        assert_eq!(std::fs::read(fixture.0.join("native.journal")).unwrap(), before);
    }
}

#[test]
fn historical_omission_preserves_canonical_event_and_journal_bytes() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request(), /*maximum_in_flight*/ 1).unwrap();
    owner.dispatch_native("request-1", dispatch()).unwrap();
    let before = std::fs::read(fixture.0.join("native.journal")).unwrap();
    assert!(!String::from_utf8_lossy(&before).contains("cognitive_preparation"));
    let historical = serde_json::to_vec(&dispatch()).unwrap();
    let replayed: NativeDispatch = serde_json::from_slice(&historical).unwrap();
    assert_eq!(replayed, dispatch());
    assert_eq!(serde_json::to_vec(&replayed).unwrap(), historical);
    drop(owner);
    let reopened = fixture.open();
    assert_eq!(reopened.native_record("request-1").unwrap().dispatch, Some(dispatch()));
    assert_eq!(std::fs::read(fixture.0.join("native.journal")).unwrap(), before);
    assert_eq!(reopened.cognitive_context_delivery(&request(), context_digest()).unwrap().unwrap().preparation(), None);
}

#[test]
fn receipt_substitution_changes_the_native_delivery_binding() {
    let mut receipts = vec![Some(preparation()), None];
    let mut changed = preparation();
    changed.read_request_id += 1;
    receipts.push(Some(changed));
    let mut changed = preparation();
    changed.sequence += 1;
    receipts.push(Some(changed));
    let mut changed = preparation();
    changed.event_digest = "6".repeat(64);
    receipts.push(Some(changed));
    let mut changed = preparation();
    changed.chain_digest = "7".repeat(64);
    receipts.push(Some(changed));
    let mut bindings = std::collections::BTreeSet::new();
    for receipt in receipts {
        let fixture = Fixture::new();
        let mut owner = fixture.open();
        owner.reserve_native(request(), /*maximum_in_flight*/ 1).unwrap();
        let mut dispatch = dispatch();
        dispatch.cognitive_preparation = receipt;
        owner.dispatch_native("request-1", dispatch).unwrap();
        let digest = owner.cognitive_context_delivery(&request(), context_digest()).unwrap().unwrap().binding_digest();
        assert!(bindings.insert(digest.to_string()));
    }
}
