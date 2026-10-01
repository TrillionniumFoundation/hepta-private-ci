//! Real ledger effects occur only after private issuance admits a response.

use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_cognitive_store::DurableCognitiveStoreError as CognitiveStoreError;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;

use crate::cognitive_context::CognitiveContextError;
use crate::cognitive_context::read_with_retrieval_context_and_learning;
use crate::cognitive_context_delivery::PendingContextDelivery;
use crate::cognitive_context_issuer::ContextPlanIssuer;
use crate::cognitive_context_issuer::PlannedContextRead;

use super::observation;
use super::owner;
use super::sink;

#[tokio::test]
async fn early_expiry_or_capacity_refusal_does_not_append_exposure_fact() {
    let (_ledger_directory, sink) = sink();
    let sink = Arc::new(sink);
    let directory = tempfile::tempdir().unwrap();
    let fleet = directory.path().join("fleet");
    std::fs::create_dir(&fleet).unwrap();
    let layout = HeptaFleetRoot::parse(fleet)
        .unwrap()
        .layout()
        .agent(&owner());
    let store = CognitiveStore::open(&layout).await.unwrap();
    for scenario in ["expired", "capacity", "clock_regressed", "issued"] {
        let mut read = read_with_retrieval_context_and_learning(
            &store,
            &owner(),
            /*body_generation*/ 1,
            "lemon",
            /*limit*/ 4,
            /*ranker*/ None,
            /*current_retrieval*/ None,
            /*learning_sink*/ None,
            /*request_id*/ None,
        )
        .await
        .unwrap();
        // Reuse the native learning sink's explicit assignment fixture. This
        // isolates issuance/append ordering from HNMF selection and socket I/O.
        read.delivery = Some(PendingContextDelivery {
            sink: Arc::clone(&sink),
            owner: owner(),
            body_generation: 1,
            request_id: 77,
            assignment: observation("publication-boundary"),
            delivered_candidates: Vec::new(),
            context_exposed: false,
            published_context_digest: None,
            downstream_policy_digest: None,
            delivery_propensity: ProbabilityQ32::ONE,
        });
        let issuer = ContextPlanIssuer::default();
        if scenario == "expired" {
            read.planned = PlannedContextRead::new(
                read.planned.snapshot.clone(),
                owner().as_str(),
                /*body_generation*/ 1,
                Instant::now() - Duration::from_secs(2),
                /*observed_at_micros*/ 100,
                /*expires_at_micros*/ 1_000_100,
            )
            .unwrap();
        } else if scenario == "clock_regressed" {
            read.observed_at_unix_seconds = crate::cognitive_context::now_seconds().unwrap() + 3600;
        } else if scenario == "capacity" {
            for index in 0_u64..256 {
                let mut snapshot = read.planned.snapshot.clone();
                snapshot.plan.as_mut().unwrap().plan_receipt_digest =
                    Digest32::of_bytes(&index.to_be_bytes()).to_string();
                issuer
                    .issue(
                        PlannedContextRead::new(
                            snapshot,
                            owner().as_str(),
                            /*body_generation*/ 1,
                            Instant::now(),
                            /*observed_at_micros*/ 100,
                            /*expires_at_micros*/ 1_000_100,
                        )
                        .unwrap(),
                    )
                    .unwrap();
            }
        }
        let result = read
            .publish(
                &store,
                &owner(),
                /*body_generation*/ 1,
                &issuer,
                /*ranker*/ None,
                /*current_retrieval*/ None,
            )
            .await;
        if scenario == "issued" {
            assert!(result.is_ok());
        } else if scenario == "clock_regressed" {
            assert!(matches!(
                result,
                Err(CognitiveContextError::Store(CognitiveStoreError::Invalid(message)))
                    if message == "snapshot clock regressed"
            ));
        } else {
            assert!(matches!(
                result,
                Err(CognitiveContextError::ReadUnavailable(_))
            ));
        }
        let snapshot = sink.writer.lock().unwrap().snapshot().unwrap();
        assert_eq!(snapshot.records().len(), usize::from(scenario == "issued"));
    }
}
