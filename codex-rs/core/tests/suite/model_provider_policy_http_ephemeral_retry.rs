use anyhow::Result;
use codex_extension_api::ModelProviderTerminal;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_response_sequence;
use core_test_support::responses::sse;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::test_codex;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::time::timeout;
use wiremock::ResponseTemplate;

use super::client::ProviderAuthCommandFixture;
use super::model_provider_policy::ProviderPolicyState;
use super::model_provider_policy::TestDecision;
use super::model_provider_policy_http_ephemeral::TestEphemeralInput;
use super::model_provider_policy_http_ephemeral::extensions;
use super::model_provider_policy_http_ephemeral::run_http_policy_test;

#[test]
fn http_401_waits_for_terminal_then_resolves_fresh_ephemeral_input() -> Result<()> {
    run_http_policy_test(async {
        let server = start_mock_server().await;
        let response = mount_response_sequence(
            &server,
            vec![
                ResponseTemplate::new(401).set_body_string("unauthorized echoed secret"),
                ResponseTemplate::new(200)
                    .insert_header("content-type", "text/event-stream")
                    .set_body_string(sse(vec![
                        ev_response_created("resp-1"),
                        ev_completed("resp-1"),
                    ])),
            ],
        )
        .await;
        let auth_fixture =
            ProviderAuthCommandFixture::new(&["catalog-token", "first-token", "second-token"])?;
        let auth = auth_fixture.auth();
        let policy = ProviderPolicyState::new(true, TestDecision::Allow);
        let input = TestEphemeralInput::new(Arc::clone(&policy), false);
        let test = test_codex()
            .with_config(move |config| {
                config.model_provider.auth = Some(auth);
                config.model_provider.env_key = None;
                config.model_provider.experimental_bearer_token = None;
                config.model_provider.requires_openai_auth = false;
                config.model_provider.request_max_retries = Some(0);
                config.model_provider.stream_max_retries = Some(0);
            })
            .with_extensions(extensions(Arc::clone(&policy), &[Arc::clone(&input)]))
            .build(&server)
            .await?;

        let submit = test.submit_turn("401 must re-resolve the physical input");
        tokio::pin!(submit);
        tokio::select! {
            result = &mut submit => panic!("turn completed before rejected terminal entered: {result:?}"),
            () = policy.wait_for_terminal_count(1) => {}
        }
        assert_eq!(input.calls(), 1);
        assert_eq!(response.requests().len(), 1);
        assert_eq!(
            policy
                .terminals
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)[0],
            ModelProviderTerminal::Rejected {
                reason_code: "provider_http_unauthorized".to_string(),
            }
        );
        assert!(
            timeout(Duration::from_millis(50), &mut submit)
                .await
                .is_err(),
            "auth recovery must wait for rejected-terminal acknowledgement"
        );

        policy.terminal_release.add_permits(1);
        timeout(Duration::from_secs(5), policy.wait_for_terminal_count(2)).await?;
        assert_eq!(input.calls(), 2);
        let requests = response.requests();
        assert_eq!(requests.len(), 2);
        assert_eq!(
            requests[0].header("authorization").as_deref(),
            Some("Bearer first-token")
        );
        assert_eq!(
            requests[1].header("authorization").as_deref(),
            Some("Bearer second-token")
        );

        let observations = input.observations();
        assert_ne!(observations[0].attempt_id, observations[1].attempt_id);
        assert_eq!(
            observations[0].base_logical_request_sha256,
            observations[1].base_logical_request_sha256
        );
        let bindings = policy
            .bindings
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone();
        assert_ne!(bindings[0].attempt_id, bindings[1].attempt_id);
        assert_eq!(
            bindings[0].request_binding_id,
            bindings[1].request_binding_id
        );
        for (index, request) in requests.iter().enumerate() {
            let body = request.body_json().to_string();
            assert!(body.contains(&observations[index].marker));
            assert!(!body.contains(&observations[1 - index].marker));
        }
        assert_eq!(policy.begin_count.load(Ordering::SeqCst), 2);
        assert!(
            timeout(Duration::from_millis(50), &mut submit)
                .await
                .is_err(),
            "turn must wait for the completed-terminal acknowledgement"
        );
        policy.terminal_release.add_permits(1);
        timeout(Duration::from_secs(5), &mut submit).await??;
        Ok(())
    })
}
