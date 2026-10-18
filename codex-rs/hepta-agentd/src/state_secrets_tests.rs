#![allow(clippy::expect_used)]
//! Physical ownership survives control cancellation and original-budget expiry.
use super::*;
use crate::AgentdMethod;
use crate::SecretsOriginalObservation;
use crate::secrets_host::tests::fixture;
use std::time::Duration;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn secrets_cancelled_control_retains_physical_slot_until_actual_join() {
    let fixture = fixture();
    let joining = {
        let _guard = fixture
            .state
            .runtime
            .lock()
            .expect("block generation observation");
        let reply = fixture
            .host
            .dispatch(AgentdMethod::SecretsOriginalStatus {
                original_id: "cancelled-original".into(),
            })
            .expect("admit worker");
        drop(reply);
        assert_eq!(fixture.host.pending_workers(), 1);
        let host = Arc::clone(&fixture.host);
        let joining = tokio::spawn(async move { host.shutdown().await });
        let wait_until = std::time::Instant::now() + Duration::from_secs(2);
        while !fixture.host.closed() && std::time::Instant::now() < wait_until {
            std::thread::yield_now();
        }
        assert!(fixture.host.closed());
        assert!(!joining.is_finished());
        assert_eq!(fixture.host.pending_workers(), 1);
        assert!(
            fixture
                .host
                .dispatch(AgentdMethod::SecretsOriginalStatus {
                    original_id: "new-original".into()
                })
                .is_err()
        );
        joining
    };
    joining.await.expect("join owner").expect("physical join");
    assert_eq!(fixture.host.pending_workers(), 0);
}

#[tokio::test]
async fn secrets_worker_bound_survives_abandoned_callers_and_zero_budget() {
    let fixture = fixture();
    {
        let _guard = fixture
            .state
            .runtime
            .lock()
            .expect("physical scheduling barrier");
        for index in 0..4 {
            drop(
                fixture
                    .host
                    .dispatch(AgentdMethod::SecretsOriginalStatus {
                        original_id: format!("held-{index}"),
                    })
                    .expect("physical slot"),
            );
        }
        assert_eq!(fixture.host.pending_workers(), 4);
        assert!(
            fixture
                .host
                .dispatch(AgentdMethod::SecretsOriginalStatus {
                    original_id: "overflow".into()
                })
                .is_err()
        );
        assert!(
            fixture
                .host
                .dispatch(AgentdMethod::SecretsConsumeOriginal {
                    original_id: "zero".into(),
                    budget_ms: 0
                })
                .is_err()
        );
        assert_eq!(fixture.host.pending_workers(), 4);
    }
    fixture
        .host
        .shutdown()
        .await
        .expect("join four actual workers");
    assert_eq!(fixture.host.pending_workers(), 0);
}

#[tokio::test]
async fn secrets_expired_scheduling_budget_never_connects_to_daemon() {
    let fixture = fixture();
    let reply = {
        let mut guard = fixture
            .state
            .runtime
            .lock()
            .expect("hold worker before actual SDK");
        guard.app_server_ready = true;
        guard.critical_stores_ready = true;
        guard.revocation_ready = true;
        guard.required_ports_ready = true;
        guard.admission_open = true;
        let reply = fixture
            .host
            .dispatch(AgentdMethod::SecretsConsumeOriginal {
                original_id: "expired-in-scheduler".into(),
                budget_ms: 1,
            })
            .expect("admit original");
        std::thread::sleep(Duration::from_millis(5));
        reply
    };
    let observation = reply.await.expect("original observation");
    assert_eq!(
        observation,
        SecretsOriginalObservation::Unknown {
            original_operation_id: fixture
                .client
                .original_operation_id("expired-in-scheduler")
                .expect("original coordinate")
        }
    );
    assert_eq!(
        fixture
            .listener
            .accept()
            .expect_err("no SDK connection after expiry")
            .kind(),
        std::io::ErrorKind::WouldBlock
    );
    fixture.host.shutdown().await.expect("join original");
}

#[tokio::test]
async fn secrets_unenrolled_agent_never_advertises_or_dispatches_capability() {
    let fixture = fixture();
    assert!(!fixture.state.secrets_capability_available());
    assert!(
        fixture
            .state
            .secrets_original(AgentdMethod::SecretsConsumeOriginal {
                original_id: "not-enrolled".into(),
                budget_ms: 1000
            })
            .await
            .is_err()
    );
    assert_eq!(
        fixture
            .listener
            .accept()
            .expect_err("no bypass connection")
            .kind(),
        std::io::ErrorKind::WouldBlock
    );
    assert_eq!(fixture.host.pending_workers(), 0);
}
