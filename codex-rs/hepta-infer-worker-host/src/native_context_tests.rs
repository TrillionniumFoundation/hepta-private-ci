//! Real local Agentd/App Server traffic with a deterministic mock provider.
//! These are mechanism fixtures, not model-success or independent-owner results.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agentd::CognitiveContextSnapshot;
use codex_hepta_agentd::test_support::CognitiveTestHost;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error as ControlError;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use core_test_support::responses;
use tokio_util::sync::CancellationToken;

use super::super::AppServerModelDriver;
use super::super::FinalRevalidationTestHook;
use super::super::NativeAdmission;
use super::super::NativeWorkerConfig;
use super::super::install_final_revalidation_test_hook;
use super::NativeContextDelivery;
use super::Result;
use super::control;

struct PreparedObservation {
    delivery: NativeContextDelivery,
    snapshot: Option<CognitiveContextSnapshot>,
}

static PREPARED: OnceLock<Mutex<Vec<PreparedObservation>>> = OnceLock::new();

pub(super) fn observe_prepared_context(
    context: Option<&CognitiveContextSnapshot>,
    delivery: NativeContextDelivery,
) {
    if let Some(observed) = PREPARED.get() {
        let mut observed = observed.lock().expect("prepared context observation");
        assert!(
            observed.len() < 3,
            "unexpected extra retrieval in isolated fixture"
        );
        observed.push(PreparedObservation {
            delivery,
            snapshot: context.cloned(),
        });
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn delivery_off_withholds_physical_context_but_keeps_revalidation_and_replay() -> Result<()> {
    let Some(completion) = super::super::test_process::isolate_host(
        "native_app_server::context::tests::delivery_off_withholds_physical_context_but_keeps_revalidation_and_replay",
    ).await? else { return Ok(()); };
    PREPARED
        .set(Mutex::new(Vec::new()))
        .map_err(|_| "fixture observer already initialized")?;
    let server = responses::start_mock_server().await;
    let sequence = ["attached", "withheld"].map(|id| {
        responses::sse_response(responses::sse(vec![
            responses::ev_response_created(id),
            responses::ev_assistant_message(id, "fixture acknowledged"),
            responses::ev_completed(id),
        ]))
    });
    let mock = responses::mount_response_sequence(&server, sequence.to_vec()).await;
    let fixture = tempfile::Builder::new()
        .prefix("hdlv-")
        .tempdir_in("/tmp")?;
    let host = CognitiveTestHost::start_explicit_context_only(
        fixture.path().join("host"),
        std::env::current_exe()?,
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c16")?,
        "mock-model",
        &format!("{}/v1", server.uri()),
    )
    .await?;
    let marker = format!(
        "mangosteen private fact {:x}",
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos()
    );
    let memory = host
        .seed_verified_memory("delivery-source", &marker)
        .await?;
    let authority = tempfile::tempdir()?;
    let (authorizer, issuer) = crate::final_use_authorizer::tests::independent_test_authorizer(
        authority.path(),
        /*expected_claims*/ 3,
    )
    .await?;
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: host.control_socket().to_path_buf(),
        agent_id: host.agent_id().clone(),
        generation: 1,
        model: "mock-model".to_string(),
        timeout: Duration::from_secs(20),
    })?
    .with_turn_start_authorizer(Arc::new(authorizer));
    let journal = fixture.path().join("worker.journal");
    let mut durable = DurableInferenceControl::open(&journal, /*capacity*/ 8)?;
    let prompt = "Return the qualification acknowledgement.";
    let mut completed = Vec::new();
    for (id, delivery) in [
        ("delivery-attach", NativeContextDelivery::Attach),
        ("delivery-withhold", NativeContextDelivery::Withhold),
    ] {
        let output = driver
            .run_with_context_delivery(
                &mut durable,
                NativeAdmission {
                    request_id: id.to_string(),
                    maximum_in_flight: 1,
                },
                prompt.to_string(),
                "mangosteen".to_string(),
                delivery,
                &CancellationToken::new(),
            )
            .await?;
        assert!(output.succeeded());
        completed.push(output);
    }
    assert_ne!(completed[0].thread_id, completed[1].thread_id);
    let attached = durable
        .native_record("delivery-attach")
        .cloned()
        .ok_or("attached record missing")?;
    let withheld = durable
        .native_record("delivery-withhold")
        .cloned()
        .ok_or("withheld record missing")?;
    let attached_dispatch = attached
        .dispatch
        .as_ref()
        .ok_or("attached dispatch missing")?;
    let withheld_dispatch = withheld
        .dispatch
        .as_ref()
        .ok_or("withheld dispatch missing")?;
    {
        let observed = PREPARED
            .get()
            .ok_or("fixture observer missing")?
            .lock()
            .map_err(|_| "fixture observer poisoned")?;
        assert_eq!(observed.len(), 2);
        assert_eq!(
            (observed[0].delivery, observed[1].delivery),
            (
                NativeContextDelivery::Attach,
                NativeContextDelivery::Withhold
            )
        );
        let on = observed[0]
            .snapshot
            .as_ref()
            .ok_or("Attach did not retrieve")?;
        let off = observed[1]
            .snapshot
            .as_ref()
            .ok_or("Withhold did not retrieve")?;
        // plan_receipt_digest includes per-read clock/expiry. Compare actual
        // source/item bindings, then bind each complete observation to its journal.
        assert_eq!(
            (&on.snapshot_digest, &on.read_digest, &on.items),
            (&off.snapshot_digest, &off.read_digest, &off.items)
        );
        assert_eq!(on.items.len(), 1);
        assert_eq!(on.items[0].content, marker);
        assert!(on.plan.as_ref().is_some_and(|plan| plan.read_allowed));
        assert!(off.plan.as_ref().is_some_and(|plan| plan.read_allowed));
        assert_eq!(
            attached_dispatch.owner_context_digest,
            Some(control::digest(&serde_json::to_vec(on)?))
        );
        assert_eq!(
            withheld_dispatch.owner_context_digest,
            Some(control::digest(&serde_json::to_vec(off)?))
        );
    }
    assert_eq!(withheld_dispatch.context_digest, control::digest(b"null"));
    assert_ne!(
        attached_dispatch.context_digest,
        withheld_dispatch.context_digest
    );
    assert_ne!(
        attached.request.payload_digest,
        withheld.request.payload_digest
    );
    let requests = server.received_requests().await.unwrap_or_default();
    let physical: Vec<_> = requests
        .iter()
        .filter(|request| request.url.path().ends_with("/responses"))
        .collect();
    assert_eq!(physical.len(), 2);
    assert!(String::from_utf8_lossy(&physical[0].body).contains(&marker));
    assert!(!String::from_utf8_lossy(&physical[1].body).contains(&marker));
    assert!(!String::from_utf8_lossy(&physical[1].body).contains("hepta-cognitive-owner"));

    // Reopen the original journal. Exact repeats settle without a new provider
    // request; changing delivery under the same ID conflicts before connection.
    drop(durable);
    let mut durable = DurableInferenceControl::open(&journal, /*capacity*/ 8)?;
    assert_eq!(
        driver
            .run_with_context_delivery(
                &mut durable,
                NativeAdmission {
                    request_id: "delivery-withhold".to_string(),
                    maximum_in_flight: 1
                },
                prompt.to_string(),
                "mangosteen".to_string(),
                NativeContextDelivery::Withhold,
                &CancellationToken::new(),
            )
            .await?,
        completed[1]
    );
    let conflict = driver
        .run_with_context_delivery(
            &mut durable,
            NativeAdmission {
                request_id: "delivery-withhold".to_string(),
                maximum_in_flight: 1,
            },
            prompt.to_string(),
            "mangosteen".to_string(),
            NativeContextDelivery::Attach,
            &CancellationToken::new(),
        )
        .await
        .unwrap_err();
    assert_eq!(
        conflict.downcast_ref::<ControlError>(),
        Some(&ControlError::Conflict)
    );
    assert_eq!(durable.native_record("delivery-withhold"), Some(&withheld));

    let hook = Arc::new(FinalRevalidationTestHook {
        reached: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
    });
    install_final_revalidation_test_hook(Arc::clone(&hook));
    let cancellation = CancellationToken::new();
    let worker = driver.run_with_context_delivery(
        &mut durable,
        NativeAdmission {
            request_id: "withheld-revocation".to_string(),
            maximum_in_flight: 1,
        },
        prompt.to_string(),
        "mangosteen".to_string(),
        NativeContextDelivery::Withhold,
        &cancellation,
    );
    let revoke = async {
        hook.reached.notified().await;
        let result = host
            .tombstone(&memory, "withdrawn before withheld final use")
            .await;
        hook.release.notify_one();
        result
    };
    let (outcome, revoked) = tokio::time::timeout(Duration::from_secs(30), async {
        tokio::join!(worker, revoke)
    })
    .await?;
    revoked?;
    assert!(outcome.is_err());
    let stopped = durable
        .native_record("withheld-revocation")
        .ok_or("revocation record missing")?;
    assert_eq!(stopped.state, NativeReservationState::Released);
    assert!(
        stopped
            .dispatch
            .as_ref()
            .is_some_and(|d| d.owner_context_digest.is_some())
    );
    assert!(
        stopped
            .pre_dispatch_stop
            .as_deref()
            .is_some_and(|reason| reason.contains("cognitive final-use revalidation failed"))
    );
    assert_eq!(stopped.turn_id, None);
    assert_eq!(mock.requests().len(), 2);
    issuer.await??;
    host.shutdown().await;
    completion.complete()?;
    Ok(())
}
