use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use ed25519_dalek::VerifyingKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::AgentdConfig;
use crate::DeploymentGrantPolicy;

struct Clock {
    now: AtomicU64,
    step: AtomicU64,
}
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self
            .now
            .fetch_add(self.step.load(Ordering::SeqCst), Ordering::SeqCst))
    }
}

struct Fixture {
    root: tempfile::TempDir,
    config: AgentdConfig,
    clock: Arc<Clock>,
    issuer: DeploymentFinalUseIssuer,
}

impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().expect("temporary root");
        let path = root.path().canonicalize().expect("canonical root");
        let fleet = HeptaFleetRoot::parse(path.join("fleet")).expect("fleet");
        let registry = FleetRegistry::initialize(fleet.clone()).expect("registry");
        let workspace = path.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner");
        let record = registry
            .register(
                AgentManifest::new(
                    owner.clone(),
                    WorkspaceBinding::new(workspace.clone(), &fleet).expect("binding"),
                    ResourceBudget::local_default(),
                )
                .expect("manifest"),
            )
            .expect("register");
        registry
            .compare_and_transition(
                &owner,
                /*expected_generation*/ 0,
                AgentLifecycle::Starting,
            )
            .expect("start generation");
        let config = AgentdConfig::load(
            path.join("fleet"),
            owner,
            /*spawn_generation*/ 1,
            record.layout.home_root().to_path_buf(),
            record.layout.run_root().to_path_buf(),
            record.layout.home_root().to_path_buf(),
            workspace,
        )
        .expect("registered host identity");
        let clock = Arc::new(Clock {
            now: AtomicU64::new(10_000),
            step: AtomicU64::new(0),
        });
        let issuer = DeploymentFinalUseIssuer::create(
            &path.join("authority"),
            "objective-issuer".into(),
            vec![DeploymentGrantPolicy {
                subject_id: config.identity().agent_id.to_string(),
                destination_id: DeploymentFinalUseIssuer::OBJECTIVE_DESTINATION.into(),
                scope_sha256: *objective_scope(config.identity()).as_array(),
                lifetime_ms: 300_000,
            }],
            clock.clone(),
        )
        .expect("provision real random issuer");
        Self {
            root,
            config,
            clock,
            issuer,
        }
    }

    fn body(&self) -> AuthBusObjectiveBody {
        AuthBusObjectiveBody {
            spawn_generation: self.config.identity().spawn_generation,
            run_id: "objective-run".into(),
            objective_revision: 1,
            source_envelope_json: "{}".into(),
            runtime_body_digest: "11".repeat(32),
            preference_state_digest: "22".repeat(32),
            model_tuple_digest: "33".repeat(32),
            prompt_registry_digest: "44".repeat(32),
            artifact_set_digest: "55".repeat(32),
            authority_epoch: 1,
        }
    }

    fn sign(&self) -> AuthBusObjectiveIngress {
        self.issuer
            .sign_objective(self.config.identity(), self.body())
            .expect("signed Objective")
    }

    fn sequence(&self) -> u64 {
        self.issuer
            .store
            .load(STATE_OWNER)
            .expect("durable head")
            .sequence
    }
}

fn signed_message(fixture: &Fixture, request: &AuthBusObjectiveIngress) -> SignedMessage {
    let bytes: Vec<u8> = request
        .signature_hex
        .as_bytes()
        .chunks_exact(2)
        .map(|chunk| {
            u8::from_str_radix(std::str::from_utf8(chunk).expect("hex"), 16)
                .expect("signature byte")
        })
        .collect();
    SignedMessage {
        claims: authbus_objective_claims(fixture.config.identity(), request).expect("claims"),
        signature: bytes.try_into().expect("64-byte original signature"),
    }
}

#[test]
fn deployment_authbus_uses_original_signature_and_registered_host_identity() {
    let fixture = Fixture::new();
    let request = fixture.sign();
    let message = signed_message(&fixture, &request);
    let trust = fixture.issuer.trust_key().expect("public key");
    let registration = IssuerRegistration {
        issuer_id: message.claims.issuer_id.clone(),
        key_epoch: message.claims.key_epoch,
        verifying_key: VerifyingKey::from_bytes(&trust.verifying_key).expect("public key"),
        revoked: false,
    };
    let authenticated = message
        .authenticate(
            &registration,
            objective_scope(fixture.config.identity()),
            message.claims.payload_digest,
            /*now_ms*/ 10_000,
        )
        .expect("original AuthBus verifier accepts service signature");
    assert_eq!(authenticated.claims(), &message.claims);
    assert_eq!(request.body, fixture.body());
    assert_eq!(
        (request.sequence, request.expires_at_ms, request.key_epoch),
        (1, 310_000, 1)
    );
    let mut altered = request;
    altered.body.run_id = "different-run".into();
    let altered = signed_message(&fixture, &altered);
    assert!(
        altered
            .authenticate(
                &registration,
                altered.claims.scope_digest,
                altered.claims.payload_digest,
                /*now_ms*/ 10_000
            )
            .is_err()
    );
}

#[test]
fn deployment_authbus_shares_durable_sequence_with_final_use_and_reopen() {
    let fixture = Fixture::new();
    assert_eq!(fixture.sign().sequence, 1);
    let policy = fixture
        .issuer
        .store
        .load(STATE_OWNER)
        .expect("state")
        .policies[0]
        .clone();
    let grant = fixture
        .issuer
        .issue(&FinalUseBinding {
            subject_id: policy.subject_id,
            destination_id: policy.destination_id,
            scope_sha256: policy.scope_sha256,
            request_sha256: [1; 32],
            payload_sha256: [2; 32],
        })
        .expect("issue")
        .expect("allowed grant");
    assert_eq!(grant.grant.grant_id, "objective-issuer:1:2");
    let reopened = DeploymentFinalUseIssuer::open(
        &fixture.root.path().join("authority"),
        fixture.clock.clone(),
    )
    .expect("same persisted issuer");
    assert_eq!(
        reopened
            .sign_objective(fixture.config.identity(), fixture.body())
            .expect("reopened Objective")
            .sequence,
        3
    );
    assert_eq!(
        fixture.issuer.trust_key().expect("key"),
        reopened.trust_key().expect("same key")
    );
}

#[test]
fn deployment_authbus_rejects_body_scope_subject_route_and_epoch_without_consuming_sequence() {
    let fixture = Fixture::new();
    for change in 0..9 {
        let mut body = fixture.body();
        match change {
            0 => body.spawn_generation += 1,
            1 => body.authority_epoch += 1,
            2 => body.objective_revision = 0,
            3 => body.run_id = "invalid run".into(),
            4 => body.runtime_body_digest = "00".repeat(32),
            5 => body.source_envelope_json.clear(),
            6 => body.source_envelope_json = "x".repeat(32 * 1024 + 1),
            7 => body.source_envelope_json = "\n".repeat(32 * 1024),
            8 => body.artifact_set_digest = "bad".into(),
            _ => unreachable!(),
        }
        assert!(
            fixture
                .issuer
                .sign_objective(fixture.config.identity(), body)
                .is_err()
        );
        assert_eq!(fixture.sequence(), 0);
    }
    let initial = fixture.issuer.store.load(STATE_OWNER).expect("head");
    for change in 0..3 {
        let mut state = initial.clone();
        match change {
            0 => state.policies[0].subject_id = "different-owner".into(),
            1 => state.policies[0].destination_id = "different-route".into(),
            2 => state.policies[0].scope_sha256 = [9; 32],
            _ => unreachable!(),
        }
        fixture
            .issuer
            .store
            .compare_and_set(STATE_OWNER, &initial, &state)
            .expect("installed test policy");
        assert!(
            fixture
                .issuer
                .sign_objective(fixture.config.identity(), fixture.body())
                .is_err()
        );
        assert_eq!(fixture.sequence(), 0);
        fixture
            .issuer
            .store
            .compare_and_set(STATE_OWNER, &state, &initial)
            .expect("restore policy");
    }
}

#[test]
fn deployment_authbus_fails_closed_on_counter_or_time_overflow() {
    let fixture = Fixture::new();
    fixture.clock.now.store(u64::MAX, Ordering::SeqCst);
    assert!(
        fixture
            .issuer
            .sign_objective(fixture.config.identity(), fixture.body())
            .is_err()
    );
    assert_eq!(fixture.sequence(), 0);
    fixture.clock.now.store(10_000, Ordering::SeqCst);
    let state = fixture.issuer.store.load(STATE_OWNER).expect("state");
    let mut exhausted = state.clone();
    exhausted.sequence = u64::MAX;
    fixture
        .issuer
        .store
        .compare_and_set(STATE_OWNER, &state, &exhausted)
        .expect("exhaust counter");
    assert!(
        fixture
            .issuer
            .sign_objective(fixture.config.identity(), fixture.body())
            .is_err()
    );
    assert_eq!(fixture.sequence(), u64::MAX);
}

#[test]
fn deployment_authbus_discards_expired_response_and_never_reuses_reserved_sequence() {
    let fixture = Fixture::new();
    fixture.clock.step.store(300_000, Ordering::SeqCst);
    assert!(
        fixture
            .issuer
            .sign_objective(fixture.config.identity(), fixture.body())
            .is_err()
    );
    assert_eq!(fixture.sequence(), 1);
    fixture.clock.step.store(0, Ordering::SeqCst);
    assert_eq!(fixture.sign().sequence, 2);
}

#[test]
fn deployment_authbus_concurrent_requests_get_unique_durable_sequences() {
    let fixture = Fixture::new();
    let identity = fixture.config.identity();
    let issuer = &fixture.issuer;
    let body = fixture.body();
    let mut sequences = std::thread::scope(|scope| {
        (0..8)
            .map(|_| {
                scope.spawn(|| {
                    issuer
                        .sign_objective(identity, body.clone())
                        .expect("signed Objective")
                        .sequence
                })
            })
            .collect::<Vec<_>>()
            .into_iter()
            .map(|join| join.join().expect("request"))
            .collect::<Vec<_>>()
    });
    sequences.sort_unstable();
    assert_eq!(sequences, (1..=8).collect::<Vec<_>>());
    assert_eq!(fixture.sequence(), 8);
}
