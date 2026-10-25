//! Real durable owner fixtures with explicit test signing and clock capabilities.
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_memory::MemoryCellKeyV1;
use codex_hepta_memory::MemoryCellQueryV1;
use codex_hepta_memory::MemoryCellRoleV1;
use codex_hepta_ndu::AggregationOperator;
use codex_hepta_ndu::AxisAggregationRule;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::NduAuthenticatedOwnerV1;
use codex_hepta_ndu::NduOwnerContextV1;
use codex_hepta_ndu::NduOwnerMutationV1;
use codex_hepta_ndu::NduProductionPolicyV1;
use codex_hepta_ndu::NduProjectionKindV1;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::AgentdNativeMemoryContextHostV1;
use crate::AgentdNativeMemoryPreparedReadV1;
use crate::NativeMemoryClockObservationV1;
use crate::NativeMemoryError;
use crate::NativeMemoryTickClockV1;
use crate::native_memory_subject_digest_v1;
use crate::state::objective_current_tests::ClockCase;
use crate::state::objective_current_tests::CurrentFixture;

pub(crate) fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
pub(crate) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

pub(crate) struct WallClock(pub(crate) AtomicU64);
impl AuthorityClock for WallClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        match self.0.load(Ordering::SeqCst) {
            0 => Err(AuthorityTrustError::Unavailable),
            now => Ok(now),
        }
    }
}
pub(crate) struct TickClock(pub(crate) Mutex<NativeMemoryClockObservationV1>);
impl NativeMemoryTickClockV1 for TickClock {
    fn observe(&self) -> Result<NativeMemoryClockObservationV1, NativeMemoryError> {
        Ok(*self.0.lock().unwrap())
    }
}

pub(crate) struct CurrentMemoryFixture {
    pub(crate) objective: CurrentFixture,
    pub(crate) ndu: Arc<Mutex<NduAuthenticatedOwnerV1>>,
    pub(crate) host: Arc<AgentdNativeMemoryContextHostV1>,
    pub(crate) authority: FinalUseAuthority,
    pub(crate) wall: Arc<WallClock>,
    pub(crate) tick: Arc<TickClock>,
    signing: SigningKey,
    nonce: AtomicU64,
    _store: tempfile::TempDir,
    _authority: tempfile::TempDir,
}

pub(crate) async fn fixture() -> CurrentMemoryFixture {
    let objective = crate::state::objective_current_tests::fixture(ClockCase::Current).await;
    fixture_with_objective(objective)
}

pub(crate) fn fixture_with_objective(objective: CurrentFixture) -> CurrentMemoryFixture {
    let store = tempfile::tempdir().unwrap();
    let authority_dir = tempfile::tempdir().unwrap();
    for path in [store.path(), authority_dir.path()] {
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
    }
    let signing = SigningKey::from_bytes(&[94; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        authority_dir.path(),
        "current-issuer".to_string(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: Default::default(),
        },
    )
    .unwrap();
    let policy = NduProductionPolicyV1 {
        utility_profile: UtilityProfile {
            profile_id: id("current-policy"),
            axis_registry_digest: digest("current-axes"),
            normalization_manifest_digest: digest("current-normalization"),
            dimensions: vec![(id("success"), AxisDirection::Maximize)],
            risk_ceilings: vec![],
            resource_ceilings: vec![],
            required_organs: RequiredOrganSet {
                organ_ids: vec![id("planner")],
            },
        },
        evaluation_policy: EvaluationPolicyV1 {
            policy_id: id("current-evaluation"),
            utility_rules: vec![AxisAggregationRule {
                axis: id("success"),
                operator: AggregationOperator::Sum,
            }],
            risk_rules: vec![],
            resource_rules: vec![],
            uncertainty_rules: vec![AxisAggregationRule {
                axis: id("success"),
                operator: AggregationOperator::Maximum,
            }],
            pareto_absolute_tolerances: vec![AxisValue {
                axis: id("success"),
                value: FixedQ32::ZERO,
            }],
        },
        scalarization: None,
    };
    let now = crate::authbus_ingress::now_ms().unwrap();
    let wall = Arc::new(WallClock(AtomicU64::new(now)));
    let tick = Arc::new(TickClock(Mutex::new(NativeMemoryClockObservationV1 {
        domain: digest("test-only-clock-continuity"),
        monotonic_micros: 1,
    })));
    let owner = NduAuthenticatedOwnerV1::open(
        store.path(),
        authority.clone(),
        NduOwnerContextV1 {
            principal_id: id(objective.state.identity().agent_id.as_str()),
            owner_id: id("utility.ndu"),
            host_generation: objective
                .state
                .identity()
                .spawn_generation
                .checked_add(1)
                .unwrap(),
            principal_scope_digest: digest("current-principal-scope"),
            fence_digest: digest("current-ndu-fence"),
            revocation_frontier_digest: digest("current-revocation-frontier"),
        },
        policy,
    )
    .unwrap()
    .with_current_reads(
        FinalUseRevocationFeedVerifier::new(
            "current-feed".into(),
            SigningKey::from_bytes(&[95; 32]).verifying_key().to_bytes(),
        )
        .unwrap(),
        wall.clone(),
    );
    let ndu = Arc::new(Mutex::new(owner));
    let host =
        AgentdNativeMemoryContextHostV1::attach(&objective.state, Arc::clone(&ndu), tick.clone())
            .unwrap();
    let f = CurrentMemoryFixture {
        objective,
        ndu,
        host,
        authority,
        wall,
        tick,
        signing,
        nonce: AtomicU64::new(1),
        _store: store,
        _authority: authority_dir,
    };
    for label in ["first", "second"] {
        f.mutate(
            NduOwnerMutationV1::AppendProjection {
                kind: NduProjectionKindV1::Preference,
                identity_digest: digest(&format!("append-{label}")),
                objective_digest: f.objective.record.snapshot.objective_digest,
                subject_digest: f.subject(),
                projection_digest: digest(label),
            },
            &format!("append-{label}"),
        );
    }
    f.select("first", "select-first");
    f.feed(/*revision*/ 2, &[]);
    f
}

impl CurrentMemoryFixture {
    pub(crate) fn query(&self, label: &str) -> MemoryCellQueryV1 {
        MemoryCellQueryV1 {
            request_id: id(label),
            key: MemoryCellKeyV1 {
                role: MemoryCellRoleV1::Procedural,
                entity: "project".into(),
                relation: "repair".into(),
            },
            deadline_unix_ms: crate::authbus_ingress::now_ms().unwrap() + 30_000,
        }
    }
    pub(crate) fn prepare(&self, label: &str) -> AgentdNativeMemoryPreparedReadV1 {
        self.host
            .prepare_read("run.current", self.query(label))
            .unwrap()
    }
    pub(crate) fn sign(&self, binding: FinalUseBinding, label: &str) -> SignedFinalUseGrant {
        let now = self.wall.0.load(Ordering::SeqCst);
        let mut nonce = [0; 32];
        nonce[..8].copy_from_slice(&self.nonce.fetch_add(1, Ordering::SeqCst).to_be_bytes());
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "current-issuer".into(),
            authority_epoch: 1,
            grant_id: label.into(),
            nonce,
            binding,
            not_before_unix_ms: now - 1_000,
            expires_at_unix_ms: now + 60_000,
        };
        let signature = self
            .signing
            .sign(&grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        SignedFinalUseGrant { grant, signature }
    }
    pub(crate) fn subject(&self) -> Digest32 {
        native_memory_subject_digest_v1(&id(self.objective.state.identity().agent_id.as_str()))
    }
    pub(crate) fn mutate(&self, mutation: NduOwnerMutationV1, label: &str) {
        let mut owner = self.ndu.lock().unwrap();
        let signed = self.sign(owner.final_use_binding(&mutation).unwrap(), label);
        owner.apply_mutation(&signed, mutation).unwrap();
    }
    pub(crate) fn select(&self, projection: &str, label: &str) {
        self.mutate(
            NduOwnerMutationV1::SelectProjection {
                identity_digest: digest(label),
                objective_digest: self.objective.record.snapshot.objective_digest,
                subject_digest: self.subject(),
                projection_digest: digest(projection),
            },
            label,
        );
    }
    pub(crate) fn feed(&self, revision: u64, revoked: &[&str]) {
        let now = self.wall.0.load(Ordering::SeqCst);
        let update = FinalUseRevocationUpdate::new(
            "current-feed".into(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision,
                revoked_grant_ids: revoked.iter().map(|id| (*id).to_owned()).collect(),
            },
            now - 1_000,
            now + 120_000,
        );
        let signature = SigningKey::from_bytes(&[95; 32])
            .sign(&update.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        self.ndu
            .lock()
            .unwrap()
            .apply_read_revocation_update(&SignedFinalUseRevocationUpdate { update, signature })
            .unwrap();
    }
}
