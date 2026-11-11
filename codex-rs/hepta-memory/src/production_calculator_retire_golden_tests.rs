//! Original writer retirement with exact Desktop core serialization bytes.
//!
//! Fixture producer: Desktop 5a8684cc4591a4163c162f198b4121ca4cfc6ebc,
//! calculator-wire-fixture.json SHA256:
//! 3fe384300463b8692cba32e720df5ac5f61403c4dfa6223e0ffdd1e6dbb303c7.
//! The authority verifier and inherited channel below are explicit fixtures.
//! This exercises the real SQLite writer, typed settlement and target codec;
//! it is neither a production issuer proof nor native GUI/effect acceptance.

use std::error::Error;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use crate::CALCULATOR_EVALUATE_TOPIC_V1;
use crate::CalculatorPrivateChannel;
use crate::CalculatorRecoveryChannel;
use crate::CalculatorTargetIdentity;
use crate::CognitiveStore;
use crate::LocalOutcomeState;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityToken;
use crate::ProductionAuthorityVerifier;
use crate::ProductionCalculatorTarget;
use crate::ProductionDurableWriter;
use crate::calculator_operation_intent;
use crate::production_writer::RecordedRetirementAck;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

// These four strings are copied without reserialization from the actual
// Desktop fixture. OBSERVE below is the expected recovery protocol request.
const REQUEST: &str = r#"{"schema_version":1,"action":"evaluate","operation_id":"original-1","destination_id":"trill.calculator:11111111111111111111111111111111:2:22222222222222222222222222222222","target":{"session_instance":"11111111111111111111111111111111","task_id":2,"incarnation":"22222222222222222222222222222222"},"expected_revision":0,"left":"12","operator":"add","right":"30"}"#;
const APPLIED: &str = r#"{"schema_version":1,"target":{"session_instance":"11111111111111111111111111111111","task_id":2,"incarnation":"22222222222222222222222222222222"},"operation_id":"original-1","payload_sha256":"f2604897d0641366919a36284d53dfa621f994206a3d30301d1cc13c6332bbc0","result":{"status":"applied","previous_revision":0,"revision":1,"state":{"left":"12","operator":"add","right":"30","result":"42"},"state_sha256":"1ce69e4a380ebbccdc1ff31a3671359cf5418a5fb34ba59968387d6de253172f"}}"#;
const ACKNOWLEDGE: &str = r#"{"schema_version":1,"action":"acknowledge","target":{"session_instance":"11111111111111111111111111111111","task_id":2,"incarnation":"22222222222222222222222222222222"},"operation_id":"original-1","payload_sha256":"f2604897d0641366919a36284d53dfa621f994206a3d30301d1cc13c6332bbc0","receipt_sha256":"6ccbc1b07aa43ac2f1ad7a7f0b67474a659ebc31868fc36adabeae54b275bd4c"}"#;
const ACKNOWLEDGED: &str = r#"{"schema_version":1,"action":"acknowledged","target":{"session_instance":"11111111111111111111111111111111","task_id":2,"incarnation":"22222222222222222222222222222222"},"operation_id":"original-1","payload_sha256":"f2604897d0641366919a36284d53dfa621f994206a3d30301d1cc13c6332bbc0","receipt_sha256":"6ccbc1b07aa43ac2f1ad7a7f0b67474a659ebc31868fc36adabeae54b275bd4c","status":"retired"}"#;
const OBSERVE: &str = r#"{"schema_version":1,"action":"observe","target":{"session_instance":"11111111111111111111111111111111","task_id":2,"incarnation":"22222222222222222222222222222222"},"operation_id":"original-1","payload_sha256":"f2604897d0641366919a36284d53dfa621f994206a3d30301d1cc13c6332bbc0"}"#;

struct FixtureVerifier(ProductionAuthorityLease);

impl ProductionAuthorityVerifier for FixtureVerifier {
    fn verify(&self, authority: &ProductionAuthorityLease, owner: &AgentId) -> Result<(), String> {
        if authority != &self.0 || owner != &self.0.agent_id {
            return Err("not the exact golden-test fixture authority".into());
        }
        Ok(())
    }
}

struct GoldenRecovery {
    requests: Mutex<Vec<Vec<u8>>>,
    lose_first_ack: AtomicBool,
}

impl CalculatorRecoveryChannel for GoldenRecovery {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        self.requests
            .lock()
            .expect("golden request recorder is not poisoned")
            .push(request.to_vec());
        if request == OBSERVE.as_bytes() {
            return Ok(APPLIED.as_bytes().to_vec());
        }
        assert_eq!(request, ACKNOWLEDGE.as_bytes());
        if self.lose_first_ack.swap(false, Ordering::SeqCst) {
            return Err("explicit fixture lost the first metadata ACK exchange".into());
        }
        Ok(ACKNOWLEDGED.as_bytes().to_vec())
    }
}

struct NeverEffect {
    recovery: Arc<GoldenRecovery>,
}

impl CalculatorPrivateChannel for NeverEffect {
    fn exchange(&self, _request: &[u8]) -> Result<Vec<u8>, String> {
        panic!("writer retirement must never enter or retry an application effect")
    }

    fn invalidate(&self) {
        panic!("recovery must not access the effect channel")
    }

    fn recovery_handle(&self) -> Arc<dyn CalculatorRecoveryChannel> {
        self.recovery.clone()
    }
}

#[tokio::test]
async fn original_writer_retries_exact_desktop_ack_after_typed_terminal_without_redispatch()
-> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d19")?;
    let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"calculator-retire-golden-fixture-grant"),
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        /*lease_expires_at_unix_seconds*/ 4_000_000_000,
        ProductionAuthorityToken::from_verified_bytes(
            b"calculator-retire-golden-fixture-token".to_vec(),
        )?,
    )?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        authority.clone(),
        Arc::new(FixtureVerifier(authority)),
        "calculator-retire-golden-fixture",
        /*generation*/ 1,
    )
    .await?;
    let identity = CalculatorTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 2,
        incarnation: "2".repeat(32),
    };
    let recovery = Arc::new(GoldenRecovery {
        requests: Mutex::new(Vec::new()),
        lose_first_ack: AtomicBool::new(true),
    });
    let target = ProductionCalculatorTarget::new(
        identity.clone(),
        Arc::new(NeverEffect {
            recovery: recovery.clone(),
        }),
    )?;
    let intent = calculator_operation_intent(
        &identity,
        REQUEST,
        StableId::new(owner.as_str())?,
        Generation::new(1)?,
    )?;
    let queued = writer
        .prepare_operation(intent, CALCULATOR_EVALUATE_TOPIC_V1, REQUEST)
        .await?;
    let operation = &queued.occurrence_key;
    writer
        .mark_indeterminate(
            operation,
            "fixture retains an applied effect with a lost reply",
        )
        .await?;

    // The real writer cannot create a retirement permit before its original
    // typed terminal has been persisted. No hand-built permit is used here.
    assert!(
        writer
            .retire_calculator_receipt(&target, operation)
            .await
            .is_err()
    );
    assert!(
        recovery
            .requests
            .lock()
            .expect("request recorder")
            .is_empty()
    );
    assert_eq!(
        writer.reconcile_target_batch(&target, /*limit*/ 1).await?,
        1
    );
    assert_eq!(
        writer.status(operation).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(
        writer
            .retained_calculator_terminal_receipt(operation)
            .await?,
        Some(APPLIED.to_string())
    );
    assert_eq!(
        *recovery.requests.lock().expect("request recorder"),
        vec![OBSERVE.as_bytes().to_vec(), ACKNOWLEDGE.as_bytes().to_vec()]
    );

    // The first ACK transport failed after source terminality. The original
    // writer derives a fresh permit from that same durable event, and the real
    // target must accept the actual Desktop response bytes on this retry.
    let before_ack = writer.recovery_anchor().await?;
    assert!(retirement_records(&store, operation).await?.is_empty());
    writer.retire_calculator_receipt(&target, operation).await?;
    let acknowledged = writer.recovery_anchor().await?;
    assert_ne!(acknowledged, before_ack);
    let records = retirement_records(&store, operation).await?;
    assert_eq!(records.len(), 1);
    let recorded: RecordedRetirementAck = serde_json::from_str(&records[0])?;
    assert_eq!(
        recorded,
        RecordedRetirementAck {
            schema_version: 1,
            lease_id: writer.lease_id().to_string(),
            operation_id: operation.clone(),
            destination_id: identity.destination_id(),
            topic: CALCULATOR_EVALUATE_TOPIC_V1.to_string(),
            payload_sha256: Sha256Digest::for_bytes(REQUEST.as_bytes()),
            terminal_receipt_sha256: Sha256Digest::for_bytes(APPLIED.as_bytes()),
        }
    );

    // The first successful target ACK adds exactly one original source event.
    // An exact cached re-ACK must neither append nor change that new whole cut.
    writer.retire_calculator_receipt(&target, operation).await?;
    assert_eq!(writer.recovery_anchor().await?, acknowledged);
    assert_eq!(retirement_records(&store, operation).await?, records);
    assert_eq!(
        writer.status(operation).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(
        *recovery.requests.lock().expect("request recorder"),
        vec![
            OBSERVE.as_bytes().to_vec(),
            ACKNOWLEDGE.as_bytes().to_vec(),
            ACKNOWLEDGE.as_bytes().to_vec(),
        ]
    );
    assert_eq!(
        writer
            .retained_calculator_terminal_receipt(operation)
            .await?,
        Some(APPLIED.to_string())
    );
    drop(writer);
    store.close().await;
    Ok(())
}

async fn retirement_records(store: &CognitiveStore, operation: &str) -> TestResult<Vec<String>> {
    // This codec fixture is intentionally unmanaged. Inspect its actual journal
    // without claiming the protected Current qualification of the public reader.
    Ok(sqlx::query_scalar(
        "SELECT payload_json FROM cognitive_local_events WHERE occurrence_key = ? AND event_kind = 'retirement_acknowledged'",
    )
    .bind(operation)
    .fetch_all(&store.pool)
    .await?)
}
