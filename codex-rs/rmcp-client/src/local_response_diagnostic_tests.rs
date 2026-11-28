use std::sync::Arc;

use pretty_assertions::assert_eq;
use rmcp::model::RequestId;

use super::LocalResponseOwner;

#[test]
fn only_the_bound_request_can_consume_its_local_failure() {
    let owner = LocalResponseOwner::new();
    let observer = owner.observer();
    let connection = Arc::new(());
    let request_id = RequestId::String("request".into());
    let bound = observer.bind(&connection, &request_id).expect("live owner");
    bound.record_response_too_large(/*maximum_bytes*/ 8);

    assert_eq!(owner.finish(&request_id), Some(8));
    assert!(observer.bind(&connection, &request_id).is_none());
    bound.record_response_too_large(/*maximum_bytes*/ 16);
}

#[test]
fn ordinary_close_has_no_size_diagnostic() {
    let owner = LocalResponseOwner::new();
    let connection = Arc::new(());
    let request_id = RequestId::String("ordinary-close".into());
    let _bound = owner
        .observer()
        .bind(&connection, &request_id)
        .expect("live owner");

    assert_eq!(owner.finish(&request_id), None);
}

#[test]
fn a_mismatched_sdk_handle_cannot_consume_the_failure() {
    let owner = LocalResponseOwner::new();
    let connection = Arc::new(());
    let bound = owner
        .observer()
        .bind(&connection, &RequestId::String("bound".into()))
        .expect("live owner");
    bound.record_response_too_large(/*maximum_bytes*/ 8);

    assert_eq!(owner.finish(&RequestId::String("other".into())), None);
}

#[test]
fn reusing_an_extension_on_a_different_connection_invalidates_the_slot() {
    let owner = LocalResponseOwner::new();
    let observer = owner.observer();
    let request_id = RequestId::String("reused-id".into());
    let first_connection = Arc::new(());
    let second_connection = Arc::new(());
    let first = observer
        .bind(&first_connection, &request_id)
        .expect("original binding");
    first.record_response_too_large(/*maximum_bytes*/ 8);

    assert!(observer.bind(&second_connection, &request_id).is_none());
    first.record_response_too_large(/*maximum_bytes*/ 16);
    assert_eq!(owner.finish(&request_id), None);
}

#[test]
fn concurrent_request_slots_do_not_share_a_failure() {
    let failed_owner = LocalResponseOwner::new();
    let ordinary_owner = LocalResponseOwner::new();
    let connection = Arc::new(());
    let failed_id = RequestId::String("failed".into());
    let ordinary_id = RequestId::String("ordinary".into());
    let failed = failed_owner
        .observer()
        .bind(&connection, &failed_id)
        .expect("first request");
    let _ordinary = ordinary_owner
        .observer()
        .bind(&connection, &ordinary_id)
        .expect("second request");
    failed.record_response_too_large(/*maximum_bytes*/ 8);

    assert_eq!(ordinary_owner.finish(&ordinary_id), None);
    assert_eq!(failed_owner.finish(&failed_id), Some(8));
}

#[test]
fn dropping_the_owner_closes_late_observers() {
    let owner = LocalResponseOwner::new();
    let observer = owner.observer();
    let connection = Arc::new(());
    let request_id = RequestId::String("abandoned".into());
    let bound = observer.bind(&connection, &request_id).expect("live owner");
    drop(owner);

    bound.record_response_too_large(/*maximum_bytes*/ 8);
    assert!(observer.bind(&connection, &request_id).is_none());
}

#[test]
fn disqualification_clears_and_closes_all_bound_observers() {
    let owner = LocalResponseOwner::new();
    let observer = owner.observer();
    let connection = Arc::new(());
    let id = RequestId::Number(7.into());
    let first = observer.bind(&connection, &id).expect("first");
    let late = observer.bind(&connection, &id).expect("second");
    first.record_response_too_large(/*maximum_bytes*/ 8);
    first.disqualify();
    late.record_response_too_large(/*maximum_bytes*/ 16);
    assert!(observer.bind(&connection, &id).is_none());
    assert_eq!(owner.finish(&id), None);
}
