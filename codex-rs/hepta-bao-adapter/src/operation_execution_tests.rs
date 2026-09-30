use super::*;
#[test]
fn concurrent_same_operation_is_busy_and_drop_releases_only_its_identity() {
    let executions = OperationExecutionSet::default();
    let first = executions.enter("operation:a").unwrap();
    let second = executions.enter("operation:b").unwrap();
    assert!(matches!(
        executions.enter("operation:a"),
        Err(LeaseRegistryErrorV1::WriterBusy)
    ));
    drop(first);
    let again = executions.enter("operation:a").unwrap();
    assert!(matches!(
        executions.enter("operation:b"),
        Err(LeaseRegistryErrorV1::WriterBusy)
    ));
    drop((again, second));
    assert!(executions.active.lock().unwrap().is_empty());
}
#[test]
fn unwind_releases_operation_without_poisoning_registry() {
    let executions = OperationExecutionSet::default();
    let result = std::panic::catch_unwind(|| {
        let _guard = executions.enter("operation:unwind").unwrap();
        panic!("synthetic callback panic");
    });
    assert!(result.is_err());
    assert!(executions.enter("operation:unwind").is_ok());
}
