use std::collections::BTreeSet;
use std::sync::Mutex as StdMutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_store::ProductionAuthorityToken;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::ProductionDispatchFuture;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_hepta_memory::ProductionOutboxTarget;
use codex_hepta_memory::ProductionTerminalObservation;
use codex_hepta_memory::ProductionTerminalObservationFuture;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use super::*;

struct Observer {
    destination: String,
    observations: Arc<StdMutex<Vec<String>>>,
}

impl ProductionOutboxTarget for Observer {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async { panic!("observer-only reconciliation must never dispatch") })
    }
}

impl FinalUseProductionOutboxTarget for Observer {
    fn destination_id(&self) -> &str {
        &self.destination
    }

    fn observe_terminal<'a>(
        &'a self,
        _request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            self.observations
                .lock()
                .expect("observations")
                .push(self.destination.clone());
            if self.destination == "target:a" {
                ProductionTerminalObservation::Indeterminate {
                    reason: "independent target still has no terminal observation".to_string(),
                }
            } else {
                ProductionTerminalObservation::Applied {
                    receipt: "independent target terminal receipt".to_string(),
                }
            }
        })
    }
}

struct UnusedGrants;

impl AgentdFinalUseGrantProvider for UnusedGrants {
    fn signed_grant(&self, _binding: &FinalUseBinding) -> Result<SignedFinalUseGrant, AgentdError> {
        panic!("observer-only reconciliation must never request a dispatch grant")
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    host: AgentdProductionWriterHost,
    final_use: FinalUseAuthority,
    observations: Arc<StdMutex<Vec<String>>>,
    revoked: Arc<AtomicBool>,
}

async fn fixture() -> Fixture {
    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path().canonicalize().expect("canonical fixture root");
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000123").expect("owner");
    let layout = HeptaFleetRoot::parse(root.join("fleet"))
        .expect("fleet")
        .layout()
        .agent(&owner);
    let store = CognitiveStore::open(&layout).await.expect("store");
    let runtime_store = store.clone();
    let grant_digest = Sha256Digest::for_bytes(b"host reconciliation authority");
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs();
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        grant_digest.clone(),
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        now + 3_600,
        ProductionAuthorityToken::from_verified_bytes(b"host reconciliation token".to_vec())
            .expect("token"),
    )
    .expect("authority");
    let revoked = Arc::new(AtomicBool::new(/*v*/ false));
    let verifier_revoked = Arc::clone(&revoked);
    let verifier =
        move |authority: &ProductionAuthorityLease, expected: &AgentId| -> Result<(), String> {
            if verifier_revoked.load(Ordering::SeqCst)
                || authority.agent_id != *expected
                || authority.grant_digest != grant_digest
            {
                return Err("independent authority rejected".to_string());
            }
            Ok(())
        };
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store,
            authority,
            Arc::new(verifier),
            "host-reconciliation",
            /*generation*/ 1,
        )
        .await
        .expect("writer"),
    );
    for (operation_id, destination) in [("unknown-a", "target:a"), ("applied-b", "target:b")] {
        let operation = OperationIntentV1::new(
            StableId::new(operation_id).expect("operation"),
            StableId::new(owner.as_str()).expect("subject"),
            StableId::new(destination).expect("destination"),
            Digest32::of_bytes(b"{}"),
            Digest32::of_bytes(b"host reconciliation scope"),
            Generation::new(/*value*/ 1).expect("generation"),
            /*expected_predecessor*/ None,
        )
        .expect("intent");
        writer
            .prepare_operation(operation, "host.reconciliation", "{}")
            .await
            .expect("prepare");
        writer
            .mark_indeterminate(operation_id, "lost acknowledgement")
            .await
            .expect("unknown effect");
    }
    let issuer = SigningKey::from_bytes(&[83; 32]);
    let authority_root = root.join("final-use");
    std::fs::create_dir(&authority_root).expect("authority directory");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(
            &authority_root,
            std::fs::Permissions::from_mode(/*mode*/ 0o700),
        )
        .expect("private authority directory");
    }
    let final_use = FinalUseAuthority::open_state_dir(
        &authority_root,
        "host-reconciliation-issuer".to_string(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("final-use authority");
    let observations = Arc::new(StdMutex::new(Vec::new()));
    let mutation = Arc::new(
        writer
            .cognitive_mutation_capability()
            .expect("mutation capability"),
    );
    let host = AgentdProductionWriterHost {
        writer,
        dispatchers: BTreeMap::new(),
        reconciliation_after: Arc::default(),
        grants: None,
        cognitive_runtime: codex_hepta_memory::CognitiveRuntime::Available(Arc::new(runtime_store)),
        mutation: Some(mutation),
    }
    .attach_target(
        final_use.clone(),
        Arc::new(Observer {
            destination: "target:a".to_string(),
            observations: Arc::clone(&observations),
        }),
        Arc::new(UnusedGrants),
    )
    .expect("primary target")
    .attach_additional_target(
        final_use.clone(),
        Arc::new(Observer {
            destination: "target:b".to_string(),
            observations: Arc::clone(&observations),
        }),
    )
    .expect("additional target");
    Fixture {
        _temp: temp,
        host,
        final_use,
        observations,
        revoked,
    }
}

#[tokio::test]
async fn indeterminate_destination_cannot_starve_applied_destination_across_host_clones() {
    let fixture = fixture().await;
    assert_eq!(
        fixture
            .host
            .reconcile(/*limit*/ 1)
            .await
            .expect("first destination"),
        1
    );
    assert_eq!(
        fixture
            .host
            .writer
            .status("unknown-a")
            .await
            .expect("unknown state"),
        LocalOutcomeState::Indeterminate
    );
    let clone = fixture.host.clone();
    assert_eq!(
        clone
            .reconcile(/*limit*/ 1)
            .await
            .expect("second destination"),
        1
    );
    assert_eq!(
        fixture
            .host
            .writer
            .status("applied-b")
            .await
            .expect("applied state"),
        LocalOutcomeState::Committed
    );
    assert_eq!(
        fixture
            .host
            .reconcile(/*limit*/ 1)
            .await
            .expect("wraparound"),
        1
    );
    assert_eq!(
        *fixture.observations.lock().expect("observations"),
        vec!["target:a", "target:b", "target:a"]
    );
    fixture.revoked.store(/*val*/ true, Ordering::SeqCst);
    assert!(clone.reconcile(/*limit*/ 1).await.is_err());
    assert_eq!(fixture.observations.lock().expect("observations").len(), 3);
}

#[tokio::test]
async fn additional_destinations_respect_the_writer_reconciliation_inventory_bound() {
    let mut fixture = fixture().await;
    for index in fixture.host.destination_count()..MAX_PRODUCTION_DESTINATIONS {
        fixture.host = fixture
            .host
            .attach_additional_target(
                fixture.final_use.clone(),
                Arc::new(Observer {
                    destination: format!("target:{index:03}"),
                    observations: Arc::clone(&fixture.observations),
                }),
            )
            .expect("bounded target");
    }
    assert_eq!(
        fixture.host.destination_count(),
        MAX_PRODUCTION_DESTINATIONS
    );
    assert!(matches!(
        fixture.host.attach_additional_target(
            fixture.final_use,
            Arc::new(Observer {
                destination: "target:overflow".to_string(),
                observations: fixture.observations,
            }),
        ),
        Err(AgentdError::Invalid(_))
    ));
}
