use std::time::Duration;

use super::QualificationTrial;

#[tokio::test]
async fn rejects_an_unbounded_trial_before_creating_runtime_state() {
    let temp = tempfile::tempdir().expect("tempdir");
    let runtime = temp.path().join("runtime");
    let error = match QualificationTrial::run(
        temp.path().join("missing-product"),
        &runtime,
        Duration::from_secs(301),
    )
    .await
    {
        Ok(_) => panic!("unbounded timeout must fail"),
        Err(error) => error,
    };
    assert!(error.to_string().contains("trial timeout"));
    assert!(!runtime.exists());
}
