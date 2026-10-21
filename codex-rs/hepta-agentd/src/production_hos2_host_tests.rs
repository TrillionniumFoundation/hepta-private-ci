//! Real product host/reconciler composition with an explicit external test
//! issuer and destination. No source writer, grant provider or native process
//! is installed in default Agentd configuration by these fixtures.

use super::run_production_operation_reconciler;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdFinalUseGrantProvider;
use crate::AgentdProductionOperationRuntimeConfig;
use crate::AgentdProductionWriterHost;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::HOS2_CPU_PERIOD_NS;
use codex_hepta_memory::HOS2_DESTINATION_V1;
use codex_hepta_memory::HOS2_INSTALL_TOPIC_V1;
use codex_hepta_memory::Hos2DeliveryId;
use codex_hepta_memory::Hos2DeliveryObservation;
use codex_hepta_memory::Hos2Device;
use codex_hepta_memory::Hos2InstallBudgetV1;
use codex_hepta_memory::Hos2RetirementObservation;
use codex_hepta_memory::Hos2RetirementPermit;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_memory::ProductionHos2Target;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::error::Error;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio_util::sync::CancellationToken;

struct ExternalTestIssuer {
    key: SigningKey,
    enabled: AtomicBool,
    invalid_first_signature: AtomicBool,
    requests: AtomicUsize,
    binding: Mutex<Option<FinalUseBinding>>,
}

impl AgentdFinalUseGrantProvider for ExternalTestIssuer {
    fn signed_grant(&self, binding: &FinalUseBinding) -> Result<SignedFinalUseGrant, AgentdError> {
        let request = self.requests.fetch_add(1, Ordering::SeqCst) + 1;
        *self
            .binding
            .lock()
            .map_err(|error| AgentdError::Protocol(error.to_string()))? = Some(binding.clone());
        if !self.enabled.load(Ordering::SeqCst) {
            return Err(AgentdError::Protocol(
                "external fixture issuer refuses renewal".to_string(),
            ));
        }
        let now = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|error| AgentdError::Protocol(error.to_string()))?
                .as_millis(),
        )
        .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        let mut nonce = [0; 32];
        nonce[..8].copy_from_slice(&(request as u64).to_le_bytes());
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "hos2-host-external-fixture".to_string(),
            authority_epoch: 19,
            grant_id: format!("hos2-host-fixture-{request}"),
            nonce,
            binding: binding.clone(),
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 60_000,
        };
        let mut signature = self
            .key
            .sign(
                &grant
                    .signing_bytes()
                    .map_err(|error| AgentdError::Protocol(error.to_string()))?,
            )
            .to_bytes()
            .to_vec();
        if self.invalid_first_signature.swap(false, Ordering::SeqCst) {
            signature[0] ^= 1;
        }
        Ok(SignedFinalUseGrant { grant, signature })
    }
}

#[derive(Default)]
struct HostTestDevice {
    applied: Mutex<Option<Hos2InstallBudgetV1>>,
    installs: AtomicUsize,
    queries: AtomicUsize,
}

impl Hos2Device for HostTestDevice {
    fn install(
        &self,
        request: &Hos2InstallBudgetV1,
    ) -> Result<codex_hepta_memory::Hos2InstallOutcome, String> {
        self.installs.fetch_add(1, Ordering::SeqCst);
        let mut applied = self.applied.lock().map_err(|error| error.to_string())?;
        if applied.is_some() {
            return Err("fixture received a second native install".to_string());
        }
        *applied = Some(request.clone());
        Ok(codex_hepta_memory::Hos2InstallOutcome::Observed(
            Hos2DeliveryObservation::Applied {
                stable_object_id: [8; 16],
                previous_revision: request.expected_revision,
                revision: request.expected_revision + 1,
                effective_ns: 1_001,
                consumed_ns: 999,
            },
        ))
    }

    fn observe(
        &self,
        request: &Hos2InstallBudgetV1,
    ) -> Result<codex_hepta_memory::Hos2InstallOutcome, String> {
        request.to_json()?;
        self.query(&request.delivery)
            .map(codex_hepta_memory::Hos2InstallOutcome::Observed)
    }

    fn query(&self, _delivery: &Hos2DeliveryId) -> Result<Hos2DeliveryObservation, String> {
        self.queries.fetch_add(1, Ordering::SeqCst);
        Ok(Hos2DeliveryObservation::NotSeen)
    }

    fn retire(&self, _permit: &Hos2RetirementPermit) -> Result<Hos2RetirementObservation, String> {
        Err("this fixture does not supply a history acknowledgement capability".to_string())
    }
}

#[tokio::test]
async fn actual_reconciler_asks_original_issuer_for_same_k_d_and_does_not_resend_unknown()
-> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c060")?;
    let record = registry.register(AgentManifest::new(
        owner.clone(),
        WorkspaceBinding::new(workspace.clone(), &fleet)?,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(
        &owner,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let config = AgentdConfig::load(
        fleet_path,
        owner.clone(),
        /*spawn_generation*/ 1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )?;
    let store = CognitiveStore::open(&config.identity().layout).await?;
    let cut = store.recovery_anchor().await?;
    store.close().await;
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"hos2-host-source-fixture"),
        /*authority_epoch*/ 13,
        /*owner_epoch*/ 17,
        /*lease_expires_at_unix_seconds*/ 4_000_000_000,
        ProductionAuthorityToken::from_verified_bytes(b"hos2-host-fixture-token".to_vec())?,
    )?;
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        |lease: &ProductionAuthorityLease, expected: &AgentId| -> Result<(), String> {
            if &lease.agent_id != expected
                || lease.grant_digest != Sha256Digest::for_bytes(b"hos2-host-source-fixture")
            {
                return Err("source authority fixture mismatch".to_string());
            }
            Ok(())
        },
    );
    let host = AgentdProductionWriterHost::open_with_recovery(
        &config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&cut),
        authority.clone(),
        verifier.clone(),
        "hos2-host-source",
        /*lease_generation*/ 1,
    )
    .await?;
    let issuer = Arc::new(ExternalTestIssuer {
        key: SigningKey::from_bytes(&[57; 32]),
        enabled: AtomicBool::new(true),
        invalid_first_signature: AtomicBool::new(true),
        requests: AtomicUsize::new(0),
        binding: Mutex::new(None),
    });
    let final_use_path = root.join("final-use");
    fs::create_dir(&final_use_path)?;
    fs::set_permissions(&final_use_path, fs::Permissions::from_mode(0o700))?;
    let final_use = FinalUseAuthority::open_state_dir(
        &final_use_path,
        "hos2-host-external-fixture".to_string(),
        issuer.key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 19,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    let device = Arc::new(HostTestDevice::default());
    let composition = AgentdProductionOperationRuntimeConfig::new(
        authority,
        verifier,
        "hos2-host-source".to_string(),
        /*lease_generation*/ 1,
        final_use,
        Arc::new(ProductionHos2Target::new(device.clone())),
        issuer.clone(),
        Duration::from_millis(20),
    );
    let (host, interval) = composition.attach(Arc::new(host)).await?;
    let request = Hos2InstallBudgetV1 {
        schema_version: 1,
        delivery: Hos2DeliveryId::new([1; 16], [2; 16], /*sequence*/ 1)?,
        manage_slot: 2,
        manage_generation: 1,
        expected_revision: 1,
        period_ns: HOS2_CPU_PERIOD_NS,
        cap_ns: 1_001,
    };
    let operation = OperationIntentV1::new(
        StableId::new("hos2:host:reauthorize")?,
        StableId::new(owner.as_str())?,
        StableId::new(HOS2_DESTINATION_V1)?,
        Digest32::of_bytes(request.to_json()?.as_bytes()),
        request.scope_digest(),
        Generation::new(1)?,
        /*expected_predecessor*/ None,
    )?;
    let queued = host
        .writer()
        .prepare_operation(operation, HOS2_INSTALL_TOPIC_V1, request.to_json()?)
        .await?;
    host.writer()
        .claim_dispatch_lease(&queued, /*lease_duration_ms*/ 5_000)
        .await?;
    let expected = host
        .writer()
        .final_use_binding(&queued, HOS2_DESTINATION_V1)
        .await?;
    assert!(
        host.dispatch_with_grant_provider(queued.clone())
            .await
            .is_err()
    );
    assert_eq!(
        host.writer().status(&queued.occurrence_key).await?,
        LocalOutcomeState::Indeterminate
    );
    issuer.enabled.store(false, Ordering::SeqCst);
    let cancelled = CancellationToken::new();
    cancelled.cancel();
    run_production_operation_reconciler(host.clone(), interval, cancelled).await?;
    assert_eq!(
        issuer.requests.load(Ordering::SeqCst),
        1,
        "shutdown must not ask for another grant"
    );
    let cancellation = CancellationToken::new();
    let _cancel_on_exit = cancellation.clone().drop_guard();
    let worker = tokio::spawn(run_production_operation_reconciler(
        host.clone(),
        interval,
        cancellation.clone(),
    ));
    let result: Result<(), Box<dyn Error>> = async {
        let deadline = Instant::now() + Duration::from_secs(15);
        while issuer.requests.load(Ordering::SeqCst) < 2 {
            if Instant::now() >= deadline {
                return Err("runtime never requested renewal from the external issuer".into());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        assert_eq!(device.installs.load(Ordering::SeqCst), 0);
        assert_eq!(
            device.queries.load(Ordering::SeqCst),
            0,
            "a proven pre-boundary rejection is not an unknown destination query"
        );
        issuer.enabled.store(true, Ordering::SeqCst);
        while host.writer().status(&queued.occurrence_key).await? != LocalOutcomeState::Committed {
            if Instant::now() >= deadline {
                return Err("runtime did not dispatch the freshly authorized original D".into());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        assert_eq!(device.installs.load(Ordering::SeqCst), 1);
        assert_eq!(
            *device.applied.lock().map_err(|error| error.to_string())?,
            Some(request.clone())
        );
        assert_eq!(
            *issuer.binding.lock().map_err(|error| error.to_string())?,
            Some(expected)
        );
        let mut next = request.clone();
        next.delivery = Hos2DeliveryId::new([1; 16], [2; 16], /*sequence*/ 2)?;
        let operation = OperationIntentV1::new(
            StableId::new("hos2:host:unknown")?,
            StableId::new(owner.as_str())?,
            StableId::new(HOS2_DESTINATION_V1)?,
            Digest32::of_bytes(next.to_json()?.as_bytes()),
            next.scope_digest(),
            Generation::new(1)?,
            /*expected_predecessor*/ None,
        )?;
        let unknown = host
            .writer()
            .prepare_operation(operation, HOS2_INSTALL_TOPIC_V1, next.to_json()?)
            .await?;
        host.writer()
            .mark_indeterminate(
                &unknown.occurrence_key,
                "fixture lost its pre-entry process",
            )
            .await?;
        let grants_before = issuer.requests.load(Ordering::SeqCst);
        while device.queries.load(Ordering::SeqCst) == 0 {
            if Instant::now() >= deadline {
                return Err("runtime never queried the original unknown D".into());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        assert_eq!(issuer.requests.load(Ordering::SeqCst), grants_before);
        assert_eq!(device.installs.load(Ordering::SeqCst), 1);
        assert_eq!(
            host.writer().status(&unknown.occurrence_key).await?,
            LocalOutcomeState::Indeterminate
        );
        Ok(())
    }
    .await;
    cancellation.cancel();
    tokio::time::timeout(Duration::from_secs(5), worker).await???;
    result
}
