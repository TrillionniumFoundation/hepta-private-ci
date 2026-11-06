//! The real original writer/FinalUse path with two explicit in-process fixture
//! endpoints. Counts are actual synchronous fixture entries, not GUI effects.
use super::test_support::Fixture;
use crate::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

const RUN: &str = "desktop.thread.fixture-shared-original-turn";

struct App {
    destination: String,
    values: Mutex<Vec<String>>,
    observations: AtomicUsize,
}
impl ProductionOutboxTarget for App {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        assert_eq!(request.operation_destination_id, self.destination);
        {
            let Ok(mut values) = self.values.lock() else {
                panic!("fixture application values mutex must not be poisoned");
            };
            values.push(request.payload_json);
        }
        Box::pin(async {
            ProductionTargetOutcome::Indeterminate {
                reason: "fixture applied and lost reply".into(),
            }
        })
    }
}
impl FinalUseProductionOutboxTarget for App {
    fn destination_id(&self) -> &str {
        &self.destination
    }
    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        assert_eq!(request.operation_destination_id, self.destination);
        self.observations.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            ProductionTerminalObservation::Indeterminate {
                reason: "fixture independent observation is unknown".into(),
            }
        })
    }
}
struct Clock;
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(1_000_000)
    }
}

fn operations(
    owner: &str,
) -> Result<[(OperationIntentV1, &'static str, String); 2], Box<dyn std::error::Error>> {
    let notes = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    let calculator = CalculatorTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 2,
        incarnation: "3".repeat(32),
    };
    let note = serde_json::json!({"schema_version":1,"action":"replace_note","operation_id":RUN,
        "destination_id":notes.destination_id(),"target":notes,"expected_revision":0,"text":"一次原写入"}).to_string();
    let calc = serde_json::json!({"schema_version":1,"action":"evaluate","operation_id":RUN,
        "destination_id":calculator.destination_id(),"target":calculator,"expected_revision":0,
        "left":"12","operator":"add","right":"30"})
    .to_string();
    let generation = Generation::new(1)?;
    let subject = StableId::new(owner)?;
    Ok([
        (
            notes_operation_intent(&notes, &note, subject.clone(), generation)?,
            NOTES_REPLACE_TOPIC_V1,
            note,
        ),
        (
            calculator_operation_intent(&calculator, &calc, subject, generation)?,
            CALCULATOR_EVALUATE_TOPIC_V1,
            calc,
        ),
    ])
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn two_apps_cannot_cross_the_same_original_turn_effect_boundary_twice()
-> Result<(), Box<dyn std::error::Error>> {
    // Both sequential orders and genuinely overlapping original transactions.
    for mode in [0, 1, 2] {
        let fixture = Fixture::new().await;
        let [notes, calculator] = operations(fixture.writer.owner_agent_id().as_str())?;
        let contenders = [notes, calculator];
        let queued = if mode < 2 {
            let first = &contenders[mode];
            let later = &contenders[1 - mode];
            let queued = fixture
                .writer
                .prepare_operation(first.0.clone(), first.1, first.2.clone())
                .await?;
            assert!(
                fixture
                    .writer
                    .prepare_operation(later.0.clone(), later.1, later.2.clone())
                    .await
                    .is_err()
            );
            queued
        } else {
            let barrier = Arc::new(tokio::sync::Barrier::new(2));
            let tasks = contenders.clone().map(|(intent, topic, payload)| {
                let writer = Arc::clone(&fixture.writer);
                let barrier = Arc::clone(&barrier);
                tokio::spawn(async move {
                    barrier.wait().await;
                    writer.prepare_operation(intent, topic, payload).await
                })
            });
            let [notes, calculator] = tasks;
            let (notes, calculator) = tokio::join!(notes, calculator);
            match (notes?, calculator?) {
                (Ok(queued), Err(_)) | (Err(_), Ok(queued)) => queued,
                _ => panic!("one original operation ID must retain one exact destination"),
            }
        };
        let retained = fixture.writer.retained_operation(RUN).await?.unwrap();
        let apps = contenders.each_ref().map(|(intent, _, _)| {
            Arc::new(App {
                destination: intent.destination_id().as_str().to_owned(),
                values: Mutex::new(Vec::new()),
                observations: AtomicUsize::new(0),
            })
        });
        let selected = usize::from(retained.topic == CALCULATOR_EVALUATE_TOPIC_V1);
        let destination = apps[selected].destination.clone();
        let binding = fixture
            .writer
            .final_use_binding(&queued, &destination)
            .await?;
        let authority_dir = fixture.temp.path().join("fixture-final-use");
        std::fs::create_dir(&authority_dir)?;
        std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700))?;
        let signing = SigningKey::from_bytes(&[81; 32]);
        let authority = FinalUseAuthority::open_state_dir_with_clock(
            &authority_dir,
            "explicit-desktop-fixture".into(),
            signing.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 71,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            Arc::new(Clock),
        )?;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "explicit-desktop-fixture".into(),
            authority_epoch: 71,
            grant_id: "desktop-fixture-one-entry".into(),
            nonce: [82; 32],
            binding: binding.clone(),
            not_before_unix_ms: 999_000,
            expires_at_unix_ms: 1_060_000,
        };
        let signature = signing.sign(&grant.signing_bytes()?).to_bytes().to_vec();
        let signed = SignedFinalUseGrant { grant, signature };
        let dispatcher =
            ProductionFinalUseOutboxDispatcher::attach(authority, apps[selected].clone());
        let outcome = dispatcher
            .dispatch(&fixture.writer, &signed, &binding, queued)
            .await?;
        assert_eq!(outcome.state, LocalOutcomeState::Indeterminate);
        let later = &contenders[1 - selected];
        assert!(
            fixture
                .writer
                .prepare_operation(later.0.clone(), later.1, later.2.clone())
                .await
                .is_err()
        );
        assert_eq!(dispatcher.reconcile(&fixture.writer, 2).await?, 1);
        let before = fixture.writer.recovery_anchor().await?;
        assert_eq!(
            fixture.writer.status(RUN).await?,
            LocalOutcomeState::Indeterminate
        );
        let after = fixture.writer.retained_operation(RUN).await?.unwrap();
        assert_eq!(after.operation, retained.operation);
        assert_eq!(after.payload_json, retained.payload_json);
        assert_eq!(
            apps[selected].values.lock().unwrap().as_slice(),
            &[retained.payload_json]
        );
        assert!(apps[1 - selected].values.lock().unwrap().is_empty());
        assert_eq!(apps[selected].observations.load(Ordering::SeqCst), 1);
        // Independent reads do not mutate the original owner cut or imply a
        // successful terminal receipt for either application.
        if selected == 0 {
            assert!(
                fixture
                    .writer
                    .retained_notes_terminal_receipt(RUN)
                    .await?
                    .is_none()
            );
            assert!(
                fixture
                    .writer
                    .retained_calculator_terminal_receipt(RUN)
                    .await
                    .is_err()
            );
        } else {
            assert!(
                fixture
                    .writer
                    .retained_calculator_terminal_receipt(RUN)
                    .await?
                    .is_none()
            );
            assert!(
                fixture
                    .writer
                    .retained_notes_terminal_receipt(RUN)
                    .await
                    .is_err()
            );
        }
        assert_eq!(fixture.writer.recovery_anchor().await?, before);
    }
    Ok(())
}
