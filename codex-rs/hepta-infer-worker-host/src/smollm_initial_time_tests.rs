use super::*;
use crate::final_use_authorizer::independent_test_authorizer_v2;
use pretty_assertions::assert_eq;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn initial_consumers_retain_the_real_pq_clock_and_refuse_wall_time_after_failure()
-> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let directory = tempfile::tempdir()?;
    let (authorizer, services) =
        independent_test_authorizer_v2(directory.path(), /*count*/ 0).await?;
    let time = InitialAuthorityTime::from_authorizer(
        &authorizer,
        LearningAuthenticationProfile::MlDsa65V2,
    )?;
    assert!(Arc::ptr_eq(
        &time.protected_clock().ok_or("initial clock missing")?,
        &authorizer.protected_clock().ok_or("owner clock missing")?,
    ));
    assert_eq!(
        time.now_seconds_with_legacy(&mut || panic!("PQ read consulted process wall time"))?,
        1_700_000_000,
    );
    assert!(
        InitialAuthorityTime::from_authorizer(
            &authorizer,
            LearningAuthenticationProfile::ClassicalV1,
        )
        .is_err()
    );
    services.finish().await?;
    assert!(
        time.now_seconds_with_legacy(&mut || panic!("failed PQ clock fell back to wall time"))
            .is_err()
    );
    Ok(())
}
