use super::tests::TestService;
use super::tests::signed;
use super::*;
use pretty_assertions::assert_eq;
use std::fs;

type TestResult = Result<(), Box<dyn std::error::Error + Send + Sync>>;
const OWNER: &str = "hepta.fleet.release.fixture";

fn initial() -> ReleaseFrontierV1 {
    ReleaseFrontierV1 {
        generation: 1,
        initial_root_sha256: [1; 32],
        checkpoint_sha256: [2; 32],
        state_sha256: [3; 32],
    }
}

#[test]
fn actual_release_frontier_retains_exact_history_after_client_restart() -> TestResult {
    let root = tempfile::tempdir()?;
    let path = root.path().join("release-frontier.json");
    let retained_path = path.clone();
    let service = TestService::start(
        root.path(),
        "release.sock",
        /*seed*/ 85,
        move |request, key| {
            let current: Option<ReleaseFrontierV1> = if path.exists() {
                Some(serde_json::from_slice(&fs::read(&path)?)?)
            } else {
                None
            };
            let outcome = match &request.operation {
                PqTrustOperationV2::ReleaseFrontierLoad { owner_id } if owner_id == OWNER => {
                    PqTrustOutcomeV2::ReleaseFrontier { value: current }
                }
                PqTrustOperationV2::ReleaseFrontierCompareAndSet {
                    owner_id,
                    expected,
                    next,
                } if owner_id == OWNER && *expected == current => {
                    let temporary = path.with_extension("next");
                    fs::write(&temporary, serde_json::to_vec(next)?)?;
                    fs::File::open(&temporary)?.sync_all()?;
                    fs::rename(&temporary, &path)?;
                    fs::File::open(path.parent().ok_or("missing frontier parent")?)?.sync_all()?;
                    PqTrustOutcomeV2::ReleaseCompareAndSetApplied { value: *next }
                }
                PqTrustOperationV2::ReleaseFrontierCompareAndSet { .. } => {
                    PqTrustOutcomeV2::Conflict
                }
                PqTrustOperationV2::ClockNow
                | PqTrustOperationV2::FrontierLoad { .. }
                | PqTrustOperationV2::FrontierCompareAndSet { .. }
                | PqTrustOperationV2::LearningFrontierLoad { .. }
                | PqTrustOperationV2::LearningFrontierCompareAndSet { .. }
                | PqTrustOperationV2::ReleaseFrontierLoad { .. } => PqTrustOutcomeV2::Unavailable,
            };
            signed(request, outcome, key)
        },
    )?;
    let first = initial();
    // A local deny event advances the complete journal without replacing the
    // independently authorized M15 publication checkpoint or bootstrap root.
    let next = ReleaseFrontierV1 {
        generation: 2,
        state_sha256: [4; 32],
        ..first
    };
    let client = UnixPqReleaseFrontier::new(service.config.clone())?;
    assert_eq!(client.load(OWNER), Ok(None));
    assert_eq!(
        client.compare_and_set(OWNER, /*expected*/ &None, &Some(first)),
        Ok(())
    );
    assert_eq!(
        client.compare_and_set(OWNER, &Some(first), &Some(next)),
        Ok(())
    );
    drop(client);
    let client = UnixPqReleaseFrontier::new(service.config.clone())?;
    assert_eq!(client.load(OWNER), Ok(Some(next)));
    assert_eq!(
        client.compare_and_set(OWNER, /*expected*/ &None, &Some(first)),
        Err(AuthorityTrustError::Conflict)
    );
    assert_eq!(
        client.compare_and_set(OWNER, &Some(first), &Some(next)),
        Err(AuthorityTrustError::Conflict)
    );
    assert_eq!(
        serde_json::from_slice::<ReleaseFrontierV1>(&fs::read(&retained_path)?)?,
        next
    );
    let requests = service.requests.load(Ordering::Relaxed);
    let mut wrong_peer = service.config.clone();
    wrong_peer.peer_uid = wrong_peer.peer_uid.wrapping_add(1);
    assert_eq!(
        UnixPqReleaseFrontier::new(wrong_peer)?.load(OWNER),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(service.requests.load(Ordering::Relaxed), requests);
    drop(service);
    assert_eq!(client.load(OWNER), Err(AuthorityTrustError::Unavailable));
    assert_eq!(
        serde_json::from_slice::<ReleaseFrontierV1>(&fs::read(retained_path)?)?,
        next
    );
    Ok(())
}

#[test]
fn malformed_release_updates_are_refused_before_external_io() -> TestResult {
    let root = tempfile::tempdir()?;
    let service = TestService::start(
        root.path(),
        "release-input.sock",
        /*seed*/ 86,
        |request, key| signed(request, PqTrustOutcomeV2::Unavailable, key),
    )?;
    let client = UnixPqReleaseFrontier::new(service.config.clone())?;
    let first = initial();
    let next = ReleaseFrontierV1 {
        generation: 2,
        state_sha256: [4; 32],
        ..first
    };
    let malformed = [
        (None, None),
        (None, Some(next)),
        (Some(first), Some(first)),
        (
            Some(first),
            Some(ReleaseFrontierV1 {
                generation: 3,
                ..next
            }),
        ),
        (
            Some(first),
            Some(ReleaseFrontierV1 {
                initial_root_sha256: [9; 32],
                ..next
            }),
        ),
        (
            Some(ReleaseFrontierV1 {
                generation: u64::MAX,
                ..first
            }),
            Some(first),
        ),
        (
            Some(ReleaseFrontierV1 {
                generation: 0,
                ..first
            }),
            Some(next),
        ),
        (
            None,
            Some(ReleaseFrontierV1 {
                state_sha256: [0; 32],
                ..first
            }),
        ),
        (
            None,
            Some(ReleaseFrontierV1 {
                checkpoint_sha256: [0; 32],
                ..first
            }),
        ),
        (
            None,
            Some(ReleaseFrontierV1 {
                initial_root_sha256: [0; 32],
                ..first
            }),
        ),
    ];
    for (expected, next) in malformed {
        assert_eq!(
            client.compare_and_set(OWNER, &expected, &next),
            Err(AuthorityTrustError::Invalid)
        );
    }
    for owner in [
        "",
        "issuer",
        "hepta.fleet.release.",
        "hepta-learning-trust:01",
    ] {
        assert_eq!(client.load(owner), Err(AuthorityTrustError::Invalid));
        assert_eq!(
            client.compare_and_set(owner, /*expected*/ &None, &Some(first)),
            Err(AuthorityTrustError::Invalid)
        );
    }
    assert_eq!(
        client.load(&format!("hepta.fleet.release.{}", "a".repeat(129))),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(service.requests.load(Ordering::Relaxed), 0);
    Ok(())
}

#[test]
fn actual_release_frontier_rejects_replay_wrong_types_and_uncertain_acknowledgments() -> TestResult
{
    let root = tempfile::tempdir()?;
    let first = initial();
    let next = ReleaseFrontierV1 {
        generation: 2,
        state_sha256: [4; 32],
        ..first
    };
    let mut previous = None;
    let mut index = 0;
    let service = TestService::start(
        root.path(),
        "release-replies.sock",
        /*seed*/ 87,
        move |request, key| {
            let outcome = match index {
                2 => PqTrustOutcomeV2::Frontier {
                    value: FinalUseFrontier {
                        authority_epoch: 1,
                        revocation_revision: 1,
                        state_sha256: [1; 32],
                    },
                },
                3 => PqTrustOutcomeV2::ReleaseFrontier {
                    value: Some(ReleaseFrontierV1 {
                        initial_root_sha256: [0; 32],
                        ..first
                    }),
                },
                4 => PqTrustOutcomeV2::ReleaseCompareAndSetApplied {
                    value: ReleaseFrontierV1 {
                        state_sha256: [9; 32],
                        ..next
                    },
                },
                _ => PqTrustOutcomeV2::ReleaseFrontier { value: Some(first) },
            };
            let mut response = signed(request, outcome, key)?;
            match index {
                0 => previous = Some(response.clone()),
                1 => response = previous.clone().ok_or("missing prior signed response")?,
                5 => response.signature[100] ^= 1,
                6 => {
                    response.body.valid_for_ms = 1;
                    response.signature = key
                        .sign_exact_message(&response.body.signing_bytes()?)?
                        .to_vec();
                    std::thread::sleep(Duration::from_millis(20));
                }
                _ => {}
            }
            index += 1;
            Ok(response)
        },
    )?;
    let client = UnixPqReleaseFrontier::new(service.config.clone())?;
    assert_eq!(client.load(OWNER), Ok(Some(first)));
    for _ in 0..3 {
        assert_eq!(client.load(OWNER), Err(AuthorityTrustError::Invalid));
    }
    // A rejected acknowledgment is not proof of non-dispatch. This adapter
    // neither retries nor substitutes the expected local frontier for it.
    assert_eq!(
        client.compare_and_set(OWNER, &Some(first), &Some(next)),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(client.load(OWNER), Err(AuthorityTrustError::Invalid));
    assert_eq!(client.load(OWNER), Err(AuthorityTrustError::Unavailable));
    assert_eq!(client.load(OWNER), Ok(Some(first)));
    assert_eq!(service.requests.load(Ordering::Relaxed), 8);
    Ok(())
}
