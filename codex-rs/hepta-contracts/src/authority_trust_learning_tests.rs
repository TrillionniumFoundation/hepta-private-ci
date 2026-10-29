use super::tests::TestService;
use super::tests::signed;
use super::*;
use std::fs;

#[test]
fn external_learning_floor_is_typed_exact_and_retains_rotation_after_client_restart() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("learning-floor.json");
    let initial = LearningTrustFrontier {
        root_digest: [1; 32],
        distribution_digest: [2; 32],
        generation: 4,
        authority_epoch: 2,
    };
    let next = LearningTrustFrontier {
        distribution_digest: [3; 32],
        generation: 5,
        authority_epoch: 3,
        ..initial
    };
    fs::write(&path, serde_json::to_vec(&initial).unwrap()).unwrap();
    let service = TestService::start(
        root.path(),
        "learning-floor.sock",
        /*seed*/ 84,
        move |request, key| {
            let current: LearningTrustFrontier =
                serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
            let outcome = match &request.operation {
                PqTrustOperationV2::LearningFrontierLoad { .. } => {
                    PqTrustOutcomeV2::LearningFrontier { value: current }
                }
                PqTrustOperationV2::LearningFrontierCompareAndSet { expected, next, .. }
                    if *expected == current =>
                {
                    fs::write(&path, serde_json::to_vec(next).unwrap()).unwrap();
                    fs::File::open(&path).unwrap().sync_all().unwrap();
                    PqTrustOutcomeV2::LearningCompareAndSetApplied { value: *next }
                }
                PqTrustOperationV2::LearningFrontierCompareAndSet { .. } => {
                    PqTrustOutcomeV2::Conflict
                }
                PqTrustOperationV2::ClockNow
                | PqTrustOperationV2::FrontierLoad { .. }
                | PqTrustOperationV2::FrontierCompareAndSet { .. } => PqTrustOutcomeV2::Unavailable,
            };
            signed(request, outcome, key)
        },
    );
    let owner = format!("hepta-learning-trust:{}", "01".repeat(32));
    let client = UnixPqLearningTrustFrontier::new(service.config.clone()).unwrap();
    assert_eq!(client.load(&owner), Ok(initial));
    assert_eq!(client.compare_and_set(&owner, &initial, &next), Ok(()));
    drop(client);
    let reopened = UnixPqLearningTrustFrontier::new(service.config.clone()).unwrap();
    assert_eq!(reopened.load(&owner), Ok(next));
    assert_eq!(
        reopened.compare_and_set(&owner, &initial, &next),
        Err(AuthorityTrustError::Conflict)
    );
    assert_eq!(reopened.load("issuer"), Err(AuthorityTrustError::Invalid));
    assert_eq!(
        reopened.compare_and_set(&owner, &next, &initial),
        Err(AuthorityTrustError::Invalid)
    );
    drop(service);
    assert_eq!(reopened.load(&owner), Err(AuthorityTrustError::Unavailable));
}
