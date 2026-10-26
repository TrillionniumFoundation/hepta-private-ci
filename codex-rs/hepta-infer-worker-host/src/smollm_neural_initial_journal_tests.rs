//! Actual journal transitions with explicit wire fixtures, not model execution.
//! No issuer, model process, nonce claim or product qualification is created.
use super::*;
use crate::model_worker::ResourceGrant;
use crate::native_app_server::TurnStartAuthorityFuture;
use crate::native_app_server::TurnStartAuthorizer;
use crate::smollm_neural_read::ControlContext;
use crate::smollm_neural_read::runtime_identity::SmolLmRuntimeIdentityV1;
use crate::smollm_neural_read::settled::ReadSource;
use crate::smollm_neural_read::settled::verify;
use codex_hepta_agentd::NeuralCognitivePinV1;
use codex_hepta_agentd::NeuralCognitiveRequestV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

struct NoExecutionAuthority(AtomicUsize);

impl TurnStartAuthorizer for NoExecutionAuthority {
    fn claim<'a>(&'a self, _binding: FinalUseBinding) -> TurnStartAuthorityFuture<'a> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Box::pin(async { Err("journal fixture has no execution authority".into()) })
    }
}

#[test]
fn selected_initial_journal_join_separates_load_domains_and_refuses_changed_observations() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    let authority = Arc::new(NoExecutionAuthority(AtomicUsize::new(0)));
    for load_domain in [
        b"hepta.smollm.selected-initial-runtime-load.v1\0".as_slice(),
        b"hepta.smollm-load.v1\0".as_slice(),
    ] {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("inference.control");
        let context = ControlContext {
            control: Arc::new(Mutex::new(DurableInferenceControl::open(&path, 8).unwrap())),
            authorizer: authority.clone(),
            runtime: runtime.handle().clone(),
            owner_id: AgentId::parse("00000000-0000-4000-8000-000000000219").unwrap(),
            body_generation: 1,
            worker_id: "explicit-journal-boundary-fixture".to_owned(),
            grant: ResourceGrant {
                grant_id: "explicit-journal-boundary-fixture".to_owned(),
                authority_epoch: 9,
                generation: 1,
                expires_at_ms: crate::smollm_neural_read::now_ms().unwrap() + 900_000,
                revoked: false,
                maximum_models: 1,
                maximum_active_requests: 1,
                maximum_memory_bytes: 8 * 1024 * 1024 * 1024,
                semantic_digest: hash("explicit journal-only resource fixture"),
            },
            model_digest: hash("explicit journal-only model fixture"),
        };
        let mut observed = Measurements::default();
        let mut ready = ready();
        ready["generation"] = json!(1);
        observed.retain_ready(&bytes(&ready)).unwrap();
        let mut identity = SmolLmRuntimeIdentityV1 {
            payload_digest: Digest32::of_bytes(b"actual parameter file"),
            generation: Generation::new(1).unwrap(),
            family_digest: Digest32::of_bytes(b"explicit journal-only family fixture"),
            execution_profile_digest: Digest32::of_bytes(b"explicit journal-only profile fixture"),
        };
        let load_payload = Digest32::of_parts(&[
            load_domain,
            context.owner_id.as_str().as_bytes(),
            &context.body_generation.to_be_bytes(),
            identity.payload_digest.as_array(),
            identity.execution_profile_digest.as_array(),
        ]);
        let load = context.admit(load_payload, 2000).unwrap();
        let load_output = Digest32::of_bytes(b"explicit journal-only settled load fixture");
        context.settle(&load, Some(load_output), true, 0).unwrap();
        observed.settle_load_output(&load, load_output).unwrap();
        let query = "explicit journal-only query fixture";
        let payload = Digest32::of_bytes(b"explicit journal-only forward payload fixture");
        let read = context.admit(payload, 2000).unwrap();
        let input = json!({"schema":"hepta-smollm-inference-input-v1",
            "request_id":read.request_id,"prompt":query});
        let mut response = response();
        response["request_id"] = json!(read.request_id);
        response["input_sha256"] = json!(Digest32::of_bytes(&bytes(&input)).to_string());
        let raw = bytes(&response);
        let receipt = Digest32::of_bytes(&raw);
        context.settle(&read, Some(receipt), true, 1).unwrap();
        observed.retain_forward(&read, &raw, receipt).unwrap();
        let request = NeuralCognitiveRequestV1 {
            owner_id: context.owner_id.clone(),
            body_generation: context.body_generation,
            pin: NeuralCognitivePinV1 {
                payload_digest: identity.payload_digest,
                objective_digest: Digest32::of_bytes(b"explicit journal-only objective fixture"),
                dataset_digest: Digest32::of_bytes(b"explicit journal-only dataset fixture"),
                generation: identity.generation,
                family_digest: identity.family_digest,
                execution_profile_digest: identity.execution_profile_digest,
            },
            query: query.to_owned(),
            query_digest: Digest32::of_bytes(query.as_bytes()),
            action_ids: vec![StableId::new("explicit-journal-boundary-action").unwrap()],
        };
        let check = |observed: &Measurements, source: ReadSource<'_>| {
            observed
                .observe(|load, forward| verify(&context, source, payload, receipt, load, forward))
                .unwrap()
        };
        let before = std::fs::read(&path).unwrap();
        let initial_domain = load_domain == b"hepta.smollm.selected-initial-runtime-load.v1\0";
        assert_eq!(
            check(
                &observed,
                ReadSource::SelectedInitial {
                    identity: &identity,
                    query
                }
            )
            .is_ok(),
            initial_domain
        );
        assert_eq!(
            check(&observed, ReadSource::Evaluated(&request)).is_ok(),
            !initial_domain
        );
        if initial_domain {
            let held = context.control.lock().unwrap();
            assert!(
                check(
                    &observed,
                    ReadSource::SelectedInitial {
                        identity: &identity,
                        query
                    }
                )
                .is_err()
            );
            drop(held);
            for (payload, receipt) in [(Digest32::ZERO, receipt), (payload, Digest32::ZERO)] {
                assert!(
                    observed
                        .observe(|load, forward| verify(
                            &context,
                            ReadSource::SelectedInitial {
                                identity: &identity,
                                query
                            },
                            payload,
                            receipt,
                            load,
                            forward,
                        ))
                        .unwrap()
                        .is_err()
                );
            }
            let original_ids = observed.ready.as_mut().unwrap().load_ids.take();
            observed.ready.as_mut().unwrap().load_ids =
                Some(("missing-load".to_owned(), "missing-reservation".to_owned()));
            assert!(
                check(
                    &observed,
                    ReadSource::SelectedInitial {
                        identity: &identity,
                        query
                    }
                )
                .is_err()
            );
            observed.ready.as_mut().unwrap().load_ids = original_ids;
            let forward = observed.forward.as_mut().unwrap();
            let original_id =
                std::mem::replace(&mut forward.request_id, "missing-forward".to_owned());
            let original_input = forward.input_digest;
            forward.input_digest = Digest32::of_bytes(&bytes(&json!({
                "schema":"hepta-smollm-inference-input-v1",
                "request_id":"missing-forward","prompt":query,
            })));
            assert!(
                check(
                    &observed,
                    ReadSource::SelectedInitial {
                        identity: &identity,
                        query
                    }
                )
                .is_err()
            );
            let forward = observed.forward.as_mut().unwrap();
            forward.request_id = original_id;
            forward.input_digest = original_input;
            let original = observed.ready.as_mut().unwrap().settled_load_output.take();
            assert!(
                check(
                    &observed,
                    ReadSource::SelectedInitial {
                        identity: &identity,
                        query
                    }
                )
                .is_err()
            );
            observed.ready.as_mut().unwrap().settled_load_output = original;
            let original = observed.forward.take();
            assert!(
                check(
                    &observed,
                    ReadSource::SelectedInitial {
                        identity: &identity,
                        query
                    }
                )
                .is_err()
            );
            observed.forward = original;
            let original = observed.forward.as_ref().unwrap().input_digest;
            observed.forward.as_mut().unwrap().input_digest =
                Digest32::of_bytes(b"different input");
            assert!(
                check(
                    &observed,
                    ReadSource::SelectedInitial {
                        identity: &identity,
                        query
                    }
                )
                .is_err()
            );
            observed.forward.as_mut().unwrap().input_digest = original;
            identity.generation = Generation::new(2).unwrap();
            assert!(
                check(
                    &observed,
                    ReadSource::SelectedInitial {
                        identity: &identity,
                        query
                    }
                )
                .is_err()
            );
            identity.generation = Generation::new(1).unwrap();
            assert!(
                check(
                    &observed,
                    ReadSource::SelectedInitial {
                        identity: &identity,
                        query
                    }
                )
                .is_ok()
            );
        }
        assert_eq!(std::fs::read(&path).unwrap(), before);
        if initial_domain {
            let original_ids = observed.ready.as_ref().unwrap().load_ids.clone();
            for (terminal, expected) in [
                (true, RequestState::Failed),
                (false, RequestState::Indeterminate),
            ] {
                // Deliberate journal-only transitions, never an execution claim.
                let refused = context.admit(load_payload, 2000).unwrap();
                context.settle(&refused, None, terminal, 0).unwrap();
                assert_eq!(
                    context
                        .control
                        .lock()
                        .unwrap()
                        .get(&refused.request_id)
                        .unwrap()
                        .state,
                    expected
                );
                observed.ready.as_mut().unwrap().load_ids =
                    Some((refused.request_id, refused.reservation_id));
                let before_refusal = std::fs::read(&path).unwrap();
                assert!(
                    check(
                        &observed,
                        ReadSource::SelectedInitial {
                            identity: &identity,
                            query
                        }
                    )
                    .is_err()
                );
                assert_eq!(std::fs::read(&path).unwrap(), before_refusal);
            }
            observed.ready.as_mut().unwrap().load_ids = original_ids;
            assert!(
                check(
                    &observed,
                    ReadSource::SelectedInitial {
                        identity: &identity,
                        query
                    }
                )
                .is_ok()
            );
        }
        assert_eq!(authority.0.load(Ordering::SeqCst), 0);
    }
}
