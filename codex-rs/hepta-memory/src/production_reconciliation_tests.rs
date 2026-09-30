use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::super::*;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

struct Verifier;

impl ProductionAuthorityVerifier for Verifier {
    fn verify(
        &self,
        _authority: &ProductionAuthorityLease,
        _expected_agent: &AgentId,
    ) -> Result<(), String> {
        Ok(())
    }
}

struct Observer {
    destination: &'static str,
    unavailable_operation: &'static str,
    ready: AtomicBool,
    observed: Mutex<Vec<String>>,
}

impl ProductionOutboxTarget for Observer {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async { panic!("terminal reconciliation must never dispatch") })
    }
}

impl FinalUseProductionOutboxTarget for Observer {
    fn destination_id(&self) -> &str {
        self.destination
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            self.observed
                .lock()
                .expect("observations")
                .push(request.occurrence_key.clone());
            if request.occurrence_key == self.unavailable_operation
                && !self.ready.load(Ordering::SeqCst)
            {
                ProductionTerminalObservation::Unavailable {
                    reason: "observer temporarily unavailable".to_string(),
                }
            } else {
                ProductionTerminalObservation::Applied {
                    receipt: "independent applied evidence".to_string(),
                }
            }
        })
    }
}

async fn prepare_unknown(
    writer: &ProductionDurableWriter,
    owner: &AgentId,
    operation_id: &str,
    destination: &str,
) {
    let operation = OperationIntentV1::new(
        StableId::new(operation_id).expect("operation id"),
        StableId::new(owner.as_str()).expect("owner"),
        StableId::new(destination).expect("destination"),
        Digest32::of_bytes(b"{}"),
        Digest32::of_bytes(b"reconciliation scope"),
        Generation::new(1).expect("generation"),
        /*expected_predecessor*/ None,
    )
    .expect("operation");
    writer
        .prepare_operation(operation, "reconciliation", "{}")
        .await
        .expect("prepare");
    writer
        .mark_indeterminate(operation_id, "lost acknowledgement")
        .await
        .expect("unknown outcome");
}

#[tokio::test]
async fn unavailable_prefix_does_not_starve_applied_operations_or_other_destinations() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(87);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"reconciliation grant"),
        1,
        1,
        now_unix_seconds().expect("clock") + 3_600,
        ProductionAuthorityToken::from_verified_bytes(b"reconciliation token".to_vec())
            .expect("token"),
    )
    .expect("authority");
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store,
        authority,
        Arc::new(Verifier),
        "reconciliation:lease",
        1,
    )
    .await
    .expect("writer");
    for (operation_id, destination) in [
        ("a-first", "target:a"),
        ("a-second", "target:a"),
        ("00-other", "target:b"),
    ] {
        prepare_unknown(&writer, &owner, operation_id, destination).await;
    }
    let first = Observer {
        destination: "target:a",
        unavailable_operation: "a-first",
        ready: AtomicBool::new(false),
        observed: Mutex::default(),
    };
    let second = Observer {
        destination: "target:b",
        unavailable_operation: "",
        ready: AtomicBool::new(true),
        observed: Mutex::default(),
    };
    assert_eq!(
        writer
            .reconcile_target_batch(&first, 1)
            .await
            .expect("unavailable observation"),
        0
    );
    prepare_unknown(&writer, &owner, "z-late-0", "target:a").await;
    let clone = writer.clone();
    assert_eq!(
        clone
            .reconcile_target_batch(&second, 1)
            .await
            .expect("other destination"),
        1
    );
    prepare_unknown(&writer, &owner, "z-late-1", "target:a").await;
    assert_eq!(
        clone
            .reconcile_target_batch(&first, 1)
            .await
            .expect("next operation"),
        1
    );
    prepare_unknown(&writer, &owner, "z-late-2", "target:a").await;
    assert_eq!(
        writer.status("a-first").await.expect("unknown status"),
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(
        writer.status("a-second").await.expect("applied status"),
        LocalOutcomeState::Committed
    );
    first.ready.store(true, Ordering::SeqCst);
    assert_eq!(
        writer
            .reconcile_target_batch(&first, 1)
            .await
            .expect("wraparound revisit"),
        1
    );
    assert_eq!(
        writer.status("a-first").await.expect("settled prefix"),
        LocalOutcomeState::Committed
    );
    assert_eq!(
        *first.observed.lock().expect("observations"),
        vec!["a-first", "a-second", "a-first"]
    );
    assert_eq!(
        *second.observed.lock().expect("observations"),
        vec!["00-other"]
    );
    assert_eq!(
        writer.status("z-late-0").await.expect("new tail"),
        LocalOutcomeState::Indeterminate
    );
}
