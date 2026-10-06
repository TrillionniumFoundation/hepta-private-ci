#![cfg(all(unix, feature = "qualification-cognitive-write"))]

use std::collections::BTreeSet;
use std::error::Error;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdFinalUseGrantProvider;
use codex_hepta_agentd::AgentdProductionWriterHost;
use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_cognitive_store::ProductionAuthorityToken;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_memory::FinalUseProductionOutboxTarget;
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

struct NoDispatchGrants;
impl AgentdFinalUseGrantProvider for NoDispatchGrants {
    fn signed_grant(&self, _: &FinalUseBinding) -> Result<SignedFinalUseGrant, AgentdError> {
        panic!("observer reconciliation must not request a dispatch grant")
    }
}

struct Observer {
    destination: String,
    calls: Arc<Mutex<Vec<String>>>,
}
impl ProductionOutboxTarget for Observer {
    fn dispatch<'a>(&'a self, _: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        panic!("observer reconciliation must never dispatch")
    }
}
impl FinalUseProductionOutboxTarget for Observer {
    fn destination_id(&self) -> &str {
        &self.destination
    }
    fn observe_terminal<'a>(
        &'a self,
        _: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async {
            self.calls.lock().unwrap().push(self.destination.clone());
            ProductionTerminalObservation::Unavailable {
                reason: "observer offline".into(),
            }
        })
    }
}

#[tokio::test]
async fn actual_host_bounds_unavailable_observers_and_rotates_clones() -> Result<(), Box<dyn Error>>
{
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c059")?;
    let store = DurableCognitiveStore::open(&fleet.layout().agent(&owner)).await?;
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"host-reconcile-test"),
        /*authority_epoch*/ 7,
        /*owner_epoch*/ 11,
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() + 300,
        ProductionAuthorityToken::from_verified_bytes(b"host-reconcile-fence".to_vec())?,
    )?;
    let verifier = |lease: &ProductionAuthorityLease, expected: &AgentId| {
        if lease.agent_id == *expected {
            Ok(())
        } else {
            Err("wrong owner".to_string())
        }
    };
    let host = AgentdProductionWriterHost::open_with_store(
        store,
        authority,
        &verifier,
        "host-reconcile",
        /*lease_generation*/ 1,
    )
    .await?;
    let calls = Arc::new(Mutex::new(Vec::new()));
    let authority_dir = temp.path().join("final-use");
    std::fs::create_dir(&authority_dir)?;
    std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700))?;
    let final_use = FinalUseAuthority::open_state_dir(
        &authority_dir,
        "host-reconcile-authority".into(),
        SigningKey::from_bytes(&[93; 32]).verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    let host = host
        .attach_target(
            final_use.clone(),
            Arc::new(Observer {
                destination: "a".into(),
                calls: Arc::clone(&calls),
            }),
            Arc::new(NoDispatchGrants),
        )?
        .attach_additional_target(
            final_use,
            Arc::new(Observer {
                destination: "b".into(),
                calls: Arc::clone(&calls),
            }),
        )?;
    for destination in ["a", "b"] {
        for index in 0..3 {
            let id = format!("op-{destination}-{index}");
            let payload = format!("{{\"operation\":\"{id}\"}}");
            let intent = OperationIntentV1::new(
                StableId::new(&id)?,
                StableId::new(owner.as_str())?,
                StableId::new(destination)?,
                Digest32::of_bytes(payload.as_bytes()),
                Digest32::of_bytes(b"host-reconcile-scope"),
                Generation::new(/*value*/ 1)?,
                /*expected_predecessor*/ None,
            )?;
            host.writer()
                .prepare_operation(intent, "host.reconcile.test", payload)
                .await?;
            host.writer()
                .mark_indeterminate(id, "unknown provider outcome")
                .await?;
        }
    }
    let clone = host.clone();
    assert_eq!(host.reconcile(/*limit*/ 1).await?, 0);
    assert_eq!(clone.reconcile(/*limit*/ 1).await?, 0);
    assert_eq!(*calls.lock().unwrap(), vec!["a", "b"]);
    calls.lock().unwrap().clear();
    assert_eq!(host.reconcile(/*limit*/ 2).await?, 0);
    assert_eq!(*calls.lock().unwrap(), vec!["a", "b"]);
    for destination in ["a", "b"] {
        for index in 0..3 {
            assert_eq!(
                host.writer()
                    .status(format!("op-{destination}-{index}"))
                    .await?,
                codex_hepta_memory::LocalOutcomeState::Indeterminate
            );
        }
    }
    Ok(())
}
