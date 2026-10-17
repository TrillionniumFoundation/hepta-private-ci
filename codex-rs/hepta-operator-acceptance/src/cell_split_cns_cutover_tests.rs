use std::fs;
use std::io::ErrorKind;
use std::os::unix::net::UnixListener;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::thread;
use std::time::Duration;

use ed25519_dalek::Signature;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

use super::*;
use crate::CellSplitEffectServiceV1;
use crate::CellSplitExecutionPortV1;
use crate::CellSplitUnixEffectPortV1;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ServingRoute {
    cns: String,
    scope: String,
    generation: u64,
    artifact: String,
    route: String,
    fence: String,
    epoch: u64,
    old_writer_fenced: bool,
    unknown_effects: u32,
}

struct DiskCns {
    root: PathBuf,
    signer: SigningKey,
    migration_ready: Arc<AtomicBool>,
    replay_old_readback: bool,
    stale_durable_sequence: bool,
    advanced_durable_sequence: bool,
    advance_during_live_readback: bool,
}

impl DiskCns {
    fn open(root: PathBuf, signer: SigningKey, ready: Arc<AtomicBool>) -> Self {
        Self {
            root,
            signer,
            migration_ready: ready,
            replay_old_readback: false,
            stale_durable_sequence: false,
            advanced_durable_sequence: false,
            advance_during_live_readback: false,
        }
    }
    fn with_stale_sequence(mut self) -> Self {
        self.stale_durable_sequence = true;
        self
    }
    fn with_advanced_sequence(mut self) -> Self {
        self.advanced_durable_sequence = true;
        self
    }
    fn with_revision_change_during_live(mut self) -> Self {
        self.advance_during_live_readback = true;
        self
    }
    fn with_stale_readback(mut self) -> Self {
        self.replay_old_readback = true;
        self
    }
    fn route_path(&self) -> PathBuf {
        self.root.join("actual-runtime-route.json")
    }
    fn commit_path(&self, key: &str) -> PathBuf {
        self.root.join(format!("runtime-cutover-{key}.json"))
    }
    fn route(&self) -> ServingRoute {
        serde_json::from_slice(&fs::read(self.route_path()).expect("live route")).expect("route")
    }
    fn durable_replace(&self, next: &ServingRoute) -> Result<(), String> {
        crate::durable::write_private_atomic_replace(
            &self.route_path(),
            &self.root.join("route-stage.tmp"),
            &canonical_json(next).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())
    }
}

impl CellSplitCnsRuntimePortV1 for DiskCns {
    type Error = String;

    fn verify_preconditions(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        if !self.migration_ready.load(Ordering::Acquire)
            || intent.previous_receipt_digest != "77".repeat(32)
        {
            return Err("original signed migration or final-use admission missing".into());
        }
        Ok(())
    }

    fn inspect_live(
        &mut self,
        _cns_id: &str,
        _scope_digest: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitCnsLiveRouteV1, Self::Error> {
        let observed = self.route();
        // The independently retained runtime revision advances while the
        // signed serving-route RPC is in flight, leaving the route bytes
        // themselves unchanged. Source-only adversarial race injection.
        if self.advance_during_live_readback {
            self.advance_during_live_readback = false;
            self.advanced_durable_sequence = true;
        }
        let actual_nonce = if self.replay_old_readback {
            "00".repeat(32)
        } else {
            challenge_nonce.to_owned()
        };
        let signed = self
            .signer
            .sign(&canonical_json(&(&observed, &actual_nonce)).map_err(|e| e.to_string())?);
        Ok(CellSplitCnsLiveRouteV1 {
            cns_id: observed.cns,
            scope_digest: observed.scope,
            generation: observed.generation,
            artifact_digest: observed.artifact,
            route_digest: observed.route,
            route_fence_digest: observed.fence,
            authority_epoch: observed.epoch,
            old_writer_fenced: observed.old_writer_fenced,
            unknown_effect_count: observed.unknown_effects,
            challenge_nonce: actual_nonce,
            live_runtime_proof_bytes: signed.to_bytes().to_vec(),
        })
    }

    fn verify_live(&mut self, state: &CellSplitCnsLiveRouteV1) -> Result<(), Self::Error> {
        let actual = self.route();
        if state.cns_id != actual.cns
            || state.scope_digest != actual.scope
            || state.generation != actual.generation
            || state.artifact_digest != actual.artifact
            || state.route_digest != actual.route
            || state.route_fence_digest != actual.fence
            || state.authority_epoch != actual.epoch
            || state.old_writer_fenced != actual.old_writer_fenced
            || state.unknown_effect_count != actual.unknown_effects
        {
            return Err("signed route no longer equals the serving CNS route".into());
        }
        let signature =
            Signature::from_slice(&state.live_runtime_proof_bytes).map_err(|e| e.to_string())?;
        self.signer
            .verifying_key()
            .verify_strict(
                &canonical_json(&(&actual, &state.challenge_nonce)).map_err(|e| e.to_string())?,
                &signature,
            )
            .map_err(|e| e.to_string())
    }

    fn publish_once(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        binding: &CellSplitCnsRouteBindingV1,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        self.verify_preconditions(plan, intent)?;
        let before = self.route();
        if before.generation != plan.parent_generation
            || before.route != binding.predecessor_route_digest
            || !before.old_writer_fenced
            || before.unknown_effects != 0
        {
            return Err("old route or writer fence is not current".into());
        }
        let mut after = before;
        after.generation = plan.child_generation;
        after.artifact = plan.child_artifact_digest.clone();
        after.route = binding.successor_route_digest.clone();
        after.fence = plan.route_fence_digest.clone();
        // Real durable file mutation in the fixture; a production port must
        // instead execute HeptaRuntime's authoritative CNS cutover.
        self.durable_replace(&after)?;
        let mut receipt = CellSplitCnsRuntimeCommitV1 {
            idempotency_key: intent.idempotency_key.clone(),
            cns_id: binding.cns_id.clone(),
            predecessor_route_digest: binding.predecessor_route_digest.clone(),
            successor_route_digest: binding.successor_route_digest.clone(),
            predecessor_generation: plan.parent_generation,
            successor_generation: plan.child_generation,
            authority_epoch: binding.authority_epoch,
            committed_sequence: 11,
            original_runtime_receipt_bytes: Vec::new(),
            original_runtime_signature_bytes: Vec::new(),
        };
        let proof = canonical_json(&CellSplitCnsRuntimeAttestationV1::for_commit(
            plan, &receipt,
        ))
        .map_err(|e| e.to_string())?;
        receipt.original_runtime_signature_bytes = self.signer.sign(&proof).to_bytes().to_vec();
        receipt.original_runtime_receipt_bytes = proof;
        crate::durable::write_private_new(
            &self.commit_path(&intent.idempotency_key),
            &canonical_json(&receipt).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())
    }

    fn read_original_commit(
        &mut self,
        key: &str,
    ) -> Result<Option<CellSplitCnsRuntimeCommitV1>, Self::Error> {
        match fs::read(self.commit_path(key)) {
            Ok(bytes) => serde_json::from_slice(&bytes)
                .map(Some)
                .map_err(|e| e.to_string()),
            Err(e) if e.kind() == ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e.to_string()),
        }
    }

    fn verify_original_commit(
        &mut self,
        receipt: &CellSplitCnsRuntimeCommitV1,
    ) -> Result<(), Self::Error> {
        let signature = Signature::from_slice(&receipt.original_runtime_signature_bytes)
            .map_err(|e| e.to_string())?;
        self.signer
            .verifying_key()
            .verify_strict(&receipt.original_runtime_receipt_bytes, &signature)
            .map_err(|e| e.to_string())
    }

    fn committed_sequence(&mut self, _cns_id: &str) -> Result<u64, Self::Error> {
        Ok(if self.stale_durable_sequence {
            1
        } else if self.advanced_durable_sequence {
            12
        } else if self.route().generation == 4 {
            11
        } else {
            1
        })
    }
}

fn plan() -> CellSplitExecutionPlanV1 {
    CellSplitExecutionPlanV1 {
        split_id: "split.route".into(),
        scope_digest: "11".repeat(32),
        parent_generation: 3,
        child_generation: 4,
        parent_artifact_digest: "22".repeat(32),
        child_artifact_digest: "33".repeat(32),
        ndu_snapshot_digest: "44".repeat(32),
        route_fence_digest: "55".repeat(32),
        owner_ids: [
            "cas-owner".into(),
            "migration-owner".into(),
            "cns-owner".into(),
            "supervisor-owner".into(),
        ],
    }
}

fn binding() -> CellSplitCnsRouteBindingV1 {
    CellSplitCnsRouteBindingV1 {
        cns_id: "cns.main".into(),
        predecessor_route_digest: "66".repeat(32),
        successor_route_digest: "88".repeat(32),
        authority_epoch: 7,
    }
}

fn intent() -> CellSplitExecutionIntentV1 {
    let plan_digest = sha256(&canonical_json(&plan()).expect("plan"));
    let predecessor = "77".repeat(32);
    let key = sha256(
        format!(
            "hepta.learning.cell-split.execution-owner.v1\0{plan_digest}\0{}\0{predecessor}",
            CellSplitExecutionStepV1::CnsRouteCutover.index()
        )
        .as_bytes(),
    );
    CellSplitExecutionIntentV1 {
        schema: "hepta.learning.cell-split.execution-owner.v1".into(),
        plan_digest,
        step: CellSplitExecutionStepV1::CnsRouteCutover,
        owner_id: "cns-owner".into(),
        idempotency_key: key,
        previous_receipt_digest: predecessor,
    }
}

fn private_root() -> tempfile::TempDir {
    use std::os::unix::fs::PermissionsExt as _;
    let root = tempfile::tempdir().expect("fixture");
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))
        .expect("private filesystem owner");
    let route = ServingRoute {
        cns: "cns.main".into(),
        scope: plan().scope_digest,
        generation: 3,
        artifact: plan().parent_artifact_digest,
        route: binding().predecessor_route_digest,
        fence: "99".repeat(32),
        epoch: 7,
        old_writer_fenced: true,
        unknown_effects: 0,
    };
    crate::durable::write_private_new(
        &root.path().join("actual-runtime-route.json"),
        &canonical_json(&route).expect("route bytes"),
    )
    .expect("initial route");
    root
}

fn owner(root: &Path, ready: Arc<AtomicBool>) -> CellSplitCnsCutoverOwnerV1<DiskCns> {
    CellSplitCnsCutoverOwnerV1::open(
        root,
        plan(),
        binding(),
        DiskCns::open(root.to_path_buf(), SigningKey::from_bytes(&[9; 32]), ready),
    )
    .expect("owner")
}

#[cfg(unix)]
#[test]
fn missing_original_cns_writer_lock_never_creates_second_writer() {
    let root = private_root();
    let ready = Arc::new(AtomicBool::new(true));
    let _original = owner(root.path(), ready.clone());
    let lock = root.path().join(crate::durable::SIDECAR_LOCK_FILE);
    fs::remove_file(&lock).expect("unlink original writer lock");
    let reopened = CellSplitCnsCutoverOwnerV1::open(
        root.path(),
        plan(),
        binding(),
        DiskCns::open(
            root.path().to_path_buf(),
            SigningKey::from_bytes(&[9; 32]),
            ready,
        ),
    );
    assert!(matches!(
        reopened,
        Err(CellSplitCnsCutoverErrorV1::Durable(_))
    ));
    assert!(!lock.exists(), "must not mint a replacement writer lock");
    assert!(root.path().join(FROZEN).exists());
}

#[test]
fn deleted_frozen_binding_before_cutover_does_not_rebind_initialized_owner() {
    let root = private_root();
    let ready = Arc::new(AtomicBool::new(true));
    {
        let original = owner(root.path(), ready.clone());
        drop(original);
    }
    let frozen = root.path().join(FROZEN);
    fs::remove_file(&frozen).expect("simulate missing frozen plan before cutover");
    let runtime = DiskCns::open(
        root.path().to_path_buf(),
        SigningKey::from_bytes(&[9; 32]),
        ready,
    );
    assert_eq!(runtime.route().generation, plan().parent_generation);
    let reopened = CellSplitCnsCutoverOwnerV1::open(root.path(), plan(), binding(), runtime);
    assert!(matches!(reopened, Err(CellSplitCnsCutoverErrorV1::Invalid)));
    assert!(!frozen.exists(), "a missing plan must not be recreated");
}

#[test]
fn deleted_frozen_binding_after_real_cutover_cannot_reinitialize_owner() {
    let root = private_root();
    let ready = Arc::new(AtomicBool::new(true));
    let request = intent();
    {
        let mut original = owner(root.path(), ready.clone());
        original.commit_once(&request).expect("durable CNS cutover");
        assert!(
            original
                .read_committed(&request)
                .expect("original signed CNS effect")
                .is_some()
        );
    }

    let frozen = root.path().join(FROZEN);
    fs::remove_file(&frozen).expect("simulate lost frozen local binding");
    let reopened = CellSplitCnsCutoverOwnerV1::open(
        root.path(),
        plan(),
        binding(),
        DiskCns::open(
            root.path().to_path_buf(),
            SigningKey::from_bytes(&[9; 32]),
            ready,
        ),
    );
    assert!(matches!(reopened, Err(CellSplitCnsCutoverErrorV1::Invalid)));
    assert!(
        !frozen.exists(),
        "reopening must not mint new frozen evidence"
    );

    let actual = DiskCns::open(
        root.path().to_path_buf(),
        SigningKey::from_bytes(&[9; 32]),
        Arc::new(AtomicBool::new(true)),
    )
    .route();
    assert_eq!(actual.generation, plan().child_generation);
    assert_eq!(actual.route, binding().successor_route_digest);
}

#[test]
fn new_cns_binding_requires_authenticated_fenced_predecessor() {
    let root = private_root();
    let backend = DiskCns::open(
        root.path().to_path_buf(),
        SigningKey::from_bytes(&[9; 32]),
        Arc::new(AtomicBool::new(true)),
    );
    let mut route = backend.route();
    route.old_writer_fenced = false;
    backend
        .durable_replace(&route)
        .expect("unfenced serving route");
    let opened = CellSplitCnsCutoverOwnerV1::open(root.path(), plan(), binding(), backend);
    assert!(matches!(opened, Err(CellSplitCnsCutoverErrorV1::Invalid)));
    assert!(!root.path().join(FROZEN).exists());
}

#[test]
fn direct_cns_readback_rejects_original_receipt_ahead_of_durable_frontier() {
    let root = private_root();
    let ready = Arc::new(AtomicBool::new(true));
    let request = intent();
    {
        let mut original = owner(root.path(), ready.clone());
        original
            .commit_once(&request)
            .expect("real signed CNS cutover");
        assert!(
            original
                .read_committed(&request)
                .expect("current frontier")
                .is_some()
        );
    }

    // Retain both the valid original signature and the actually serving child
    // route, but make the independent CNS durability frontier lag behind.
    let stale = DiskCns::open(
        root.path().to_path_buf(),
        SigningKey::from_bytes(&[9; 32]),
        ready,
    )
    .with_stale_sequence();
    let mut recovered = CellSplitCnsCutoverOwnerV1::open(root.path(), plan(), binding(), stale)
        .expect("same frozen CNS owner");
    assert!(matches!(
        recovered.read_committed(&request),
        Err(CellSplitCnsCutoverErrorV1::Invalid)
    ));
    assert!(matches!(
        recovered.authorize_execute(&request),
        Err(CellSplitCnsCutoverErrorV1::Invalid)
    ));
}

#[test]
fn original_signed_cns_receipt_behind_current_durable_frontier_cannot_be_replayed() {
    let root = private_root();
    let ready = Arc::new(AtomicBool::new(true));
    let request = intent();
    let signed_effect = {
        let mut original = owner(root.path(), ready.clone());
        original
            .commit_once(&request)
            .expect("original signed CNS cutover");
        original
            .read_committed(&request)
            .expect("original readback")
            .expect("committed original effect")
    };

    // The child still appears to serve the exact old route and its original
    // signature remains valid, but the independently durable CNS high-water
    // has advanced to a NEW revision. Old evidence cannot be promoted again.
    let newer_frontier = DiskCns::open(
        root.path().to_path_buf(),
        SigningKey::from_bytes(&[9; 32]),
        ready,
    )
    .with_advanced_sequence();
    let mut recovered = CellSplitCnsCutoverOwnerV1::open(
        root.path(),
        plan(),
        binding(),
        newer_frontier,
    )
    .expect("same frozen owner for read-only recovery");
    assert_eq!(recovered.port.route().generation, plan().child_generation);
    assert!(matches!(
        recovered.read_committed(&request),
        Err(CellSplitCnsCutoverErrorV1::Invalid)
    ));
    assert!(matches!(
        recovered.verify_current(&request, &signed_effect),
        Err(CellSplitCnsCutoverErrorV1::Invalid)
    ));
    assert!(matches!(
        recovered.authorize_execute(&request),
        Err(CellSplitCnsCutoverErrorV1::Invalid)
    ));
}

#[test]
fn cns_frontier_advancing_during_signed_route_lookup_denies_old_original_effect() {
    let root = private_root();
    let ready = Arc::new(AtomicBool::new(true));
    let request = intent();
    {
        let mut original = owner(root.path(), ready.clone());
        original
            .commit_once(&request)
            .expect("signed original CNS effect");
    }

    let racing = DiskCns::open(
        root.path().to_path_buf(),
        SigningKey::from_bytes(&[9; 32]),
        ready,
    )
    .with_revision_change_during_live();
    let mut recovered =
        CellSplitCnsCutoverOwnerV1::open(root.path(), plan(), binding(), racing)
            .expect("frozen original CNS");
    assert!(matches!(
        recovered.read_committed(&request),
        Err(CellSplitCnsCutoverErrorV1::Invalid)
    ));
    assert_eq!(recovered.port.route().generation, plan().child_generation);
    assert!(
        recovered
            .port
            .read_original_commit(&request.idempotency_key)
            .expect("original signed record remains retained")
            .is_some()
    );
}

#[test]
fn requires_original_runtime_effect_and_exact_live_route() {
    let root = private_root();
    let ready = Arc::new(AtomicBool::new(false));
    let request = intent();
    let mut cns = owner(root.path(), ready.clone());
    assert!(cns.commit_once(&request).is_err());
    assert_eq!(
        cns.read_committed(&request)
            .expect_err("missing authority")
            .to_string()
            .contains("unavailable"),
        true
    );
    ready.store(true, Ordering::Release);
    cns.commit_once(&request)
        .expect("real route mutation and durable receipt");
    let first = cns.read_committed(&request).expect("live").expect("effect");
    assert_eq!(first.owner_sequence, 11);
    assert!(
        cns.verify_current(&request, &first)
            .expect("current runtime route")
    );
    assert!(matches!(
        cns.commit_once(&request),
        Err(CellSplitCnsCutoverErrorV1::Ambiguous)
    ));
    drop(cns);

    let mut recovered = owner(root.path(), ready);
    assert_eq!(
        recovered.read_committed(&request).expect("reopened CNS"),
        Some(first.clone())
    );
    let backend = DiskCns::open(
        root.path().to_path_buf(),
        SigningKey::from_bytes(&[9; 32]),
        Arc::new(AtomicBool::new(true)),
    );
    let mut mutated = backend.route();
    mutated.route = "aa".repeat(32);
    backend
        .durable_replace(&mutated)
        .expect("out-of-band route drift");
    assert!(recovered.verify_current(&request, &first).is_err());
}

#[test]
fn lost_runtime_ack_is_ambiguous_and_cannot_forge_success() {
    let root = private_root();
    let ready = Arc::new(AtomicBool::new(true));
    let mut owner = owner(root.path(), ready);
    let request = intent();
    // A simulated crash between real route mutation and the separately
    // persisted original owner receipt. No second cutover is permitted.
    let backend = DiskCns::open(
        root.path().to_path_buf(),
        SigningKey::from_bytes(&[9; 32]),
        Arc::new(AtomicBool::new(true)),
    );
    let mut route = backend.route();
    route.route = binding().successor_route_digest;
    route.generation = plan().child_generation;
    route.artifact = plan().child_artifact_digest;
    route.fence = plan().route_fence_digest;
    backend
        .durable_replace(&route)
        .expect("cutover interrupted");
    assert!(matches!(
        owner.read_committed(&request),
        Err(CellSplitCnsCutoverErrorV1::Ambiguous)
    ));
    assert!(owner.commit_once(&request).is_err());
    assert!(!backend.commit_path(&request.idempotency_key).exists());
}

#[test]
fn signed_socket_fences_forged_positive_readback_after_restart() {
    let root = private_root();
    let socket = root.path().join("cns.sock");
    let listener = UnixListener::bind(&socket).expect("CNS owner socket");
    let root_copy = root.path().to_path_buf();
    let ready = Arc::new(AtomicBool::new(true));
    let server = thread::spawn(move || {
        let mut service = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::CnsRouteCutover,
            "cns-owner".into(),
            sha256(&canonical_json(&plan()).expect("plan")),
            SigningKey::from_bytes(&[3; 32]),
            DiskCnsOwner::new(&root_copy, ready.clone()),
        )
        .expect("server");
        for _ in 0..2 {
            let (mut stream, _) = listener.accept().expect("RPC");
            service.serve_connection(&mut stream).expect("trusted call");
        }
        drop(service);
        let mut reopened = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::CnsRouteCutover,
            "cns-owner".into(),
            sha256(&canonical_json(&plan()).expect("plan")),
            SigningKey::from_bytes(&[3; 32]),
            DiskCnsOwner::new(&root_copy, ready),
        )
        .expect("reopened");
        let (mut stream, _) = listener.accept().expect("recovered read");
        reopened.serve_connection(&mut stream).expect("read");
    });
    let keys = [1u8, 2, 3, 4].map(|n| SigningKey::from_bytes(&[n; 32]).verifying_key());
    let mut client = CellSplitUnixEffectPortV1::new(
        [
            root.path().join("cas.sock"),
            root.path().join("migration.sock"),
            socket,
            root.path().join("supervisor.sock"),
        ],
        keys,
        Duration::from_secs(3),
    )
    .expect("client");
    let request = intent();
    let signed = client
        .execute(&request)
        .expect("original signed CNS cutover");
    client
        .verify_committed(&request, &signed)
        .expect("fresh serving route");
    assert_eq!(
        client
            .reconcile(&request)
            .expect("recovered original runtime proof"),
        Some(signed)
    );
    server.join().expect("server");
}

/// Thin test-only adapter so the real generic signing service can own the
/// file-backed CNS port without inventing a second positive-receipt route.
struct DiskCnsOwner(CellSplitCnsCutoverOwnerV1<DiskCns>);
impl DiskCnsOwner {
    fn new(root: &Path, ready: Arc<AtomicBool>) -> Self {
        Self(owner(root, ready))
    }
}
impl CellSplitDurableEffectBackendV1 for DiskCnsOwner {
    type Error = CellSplitCnsCutoverErrorV1;
    fn authorize_execute(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        self.0.authorize_execute(intent)
    }
    fn commit_once(&mut self, intent: &CellSplitExecutionIntentV1) -> Result<(), Self::Error> {
        self.0.commit_once(intent)
    }
    fn read_committed(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitOwnedEffectV1>, Self::Error> {
        self.0.read_committed(intent)
    }
    fn verify_current(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        receipt: &CellSplitOwnedEffectV1,
    ) -> Result<bool, Self::Error> {
        self.0.verify_current(intent, receipt)
    }
    fn current_sequence(&mut self) -> Result<u64, Self::Error> {
        self.0.current_sequence()
    }
}

#[test]
fn corrupted_runtime_signature_cannot_become_a_signed_cns_readback() {
    let root = private_root();
    let ready = Arc::new(AtomicBool::new(true));
    let mut cns = owner(root.path(), ready);
    let request = intent();
    cns.commit_once(&request).expect("committed original");
    let signed = cns
        .read_committed(&request)
        .unwrap()
        .expect("signed original");
    let path = root
        .path()
        .join(format!("runtime-cutover-{}.json", request.idempotency_key));
    let mut tampered: CellSplitCnsRuntimeCommitV1 =
        serde_json::from_slice(&fs::read(&path).expect("original")).expect("receipt");
    tampered.original_runtime_signature_bytes[0] ^= 0x80;
    fs::write(&path, canonical_json(&tampered).expect("mutated receipt"))
        .expect("external modification");
    assert!(cns.verify_current(&request, &signed).is_err());
    assert!(cns.read_committed(&request).is_err());
}

#[test]
fn replayed_signed_cns_snapshot_is_not_a_fresh_readback() {
    let denied_root = private_root();
    let port = DiskCns::open(
        denied_root.path().to_path_buf(),
        SigningKey::from_bytes(&[9; 32]),
        Arc::new(AtomicBool::new(true)),
    )
    .with_stale_readback();

    // A rejected bootstrap can leave the persistent writer-lock inode. It
    // must not turn that directory into a fresh install: never reuse it for
    // an independently admitted owner or bypass anti-resurrection.
    let denied = CellSplitCnsCutoverOwnerV1::open(denied_root.path(), plan(), binding(), port);
    assert!(matches!(denied, Err(CellSplitCnsCutoverErrorV1::Invalid)));
    assert!(!denied_root.path().join(FROZEN).exists());
    assert!(
        CellSplitCnsCutoverOwnerV1::open(
            denied_root.path(),
            plan(),
            binding(),
            DiskCns::open(
                denied_root.path().to_path_buf(),
                SigningKey::from_bytes(&[9; 32]),
                Arc::new(AtomicBool::new(true)),
            ),
        )
        .is_err(),
        "failed bootstrap must never be resurrected on the same owner history"
    );

    // Exercise successful enrollment in an independent pristine directory.
    // The negative fixture above is intentionally never reset or reused.
    let root = private_root();
    let admitted = owner(root.path(), Arc::new(AtomicBool::new(true)));
    drop(admitted);
    let stale = DiskCns::open(
        root.path().to_path_buf(),
        SigningKey::from_bytes(&[9; 32]),
        Arc::new(AtomicBool::new(true)),
    )
    .with_stale_readback();
    let mut reopened = CellSplitCnsCutoverOwnerV1::open(root.path(), plan(), binding(), stale)
        .expect("preexisting frozen CNS binding");
    assert!(matches!(
        reopened.read_committed(&intent()),
        Err(CellSplitCnsCutoverErrorV1::Invalid)
    ));
}

#[test]
fn genuinely_signed_but_wrong_scope_runtime_cutover_is_denied() {
    let root = private_root();
    let ready = Arc::new(AtomicBool::new(true));
    let request = intent();
    let mut cns = owner(root.path(), ready);
    cns.commit_once(&request)
        .expect("original live CNS cutover");
    let original = cns
        .read_committed(&request)
        .expect("current CNS")
        .expect("original commit");

    // An adversary with a valid unrelated CNS runtime signature may not
    // replace the original proof while preserving an otherwise valid outer
    // record. Signed bytes must be bound to this exact scope and route.
    let path = root
        .path()
        .join(format!("runtime-cutover-{}.json", request.idempotency_key));
    let mut forged: CellSplitCnsRuntimeCommitV1 =
        serde_json::from_slice(&fs::read(&path).expect("CNS receipt")).expect("typed commit");
    let mut inner: CellSplitCnsRuntimeAttestationV1 =
        serde_json::from_slice(&forged.original_runtime_receipt_bytes)
            .expect("typed independent CNS attestation");
    inner.scope_digest = "aa".repeat(32);
    let unrelated = canonical_json(&inner).expect("canonical unrelated signed proof");
    let signer = SigningKey::from_bytes(&[9; 32]);
    forged.original_runtime_signature_bytes = signer.sign(&unrelated).to_bytes().to_vec();
    forged.original_runtime_receipt_bytes = unrelated;
    fs::write(
        &path,
        canonical_json(&forged).expect("changed outer commit"),
    )
    .expect("simulate out-of-band receipt substitution");
    assert!(
        cns.verify_current(&request, &original).is_err(),
        "independently signed but wrong-scope CNS proof cannot be current"
    );
    assert!(cns.read_committed(&request).is_err());
}

#[test]
fn re_signed_noncanonical_runtime_statement_cannot_be_replayed() {
    let root = private_root();
    let request = intent();
    let mut cns = owner(root.path(), Arc::new(AtomicBool::new(true)));
    cns.commit_once(&request)
        .expect("authentic CNS route publication");
    let committed = cns
        .read_committed(&request)
        .expect("authenticated readback")
        .expect("original commit");
    let path = root
        .path()
        .join(format!("runtime-cutover-{}.json", request.idempotency_key));
    let original: CellSplitCnsRuntimeCommitV1 =
        serde_json::from_slice(&fs::read(&path).expect("original receipt")).expect("typed commit");
    let typed: CellSplitCnsRuntimeAttestationV1 =
        serde_json::from_slice(&original.original_runtime_receipt_bytes)
            .expect("typed runtime statement");
    let noncanonical = serde_json::to_vec(&typed).expect("struct-order encoding");
    assert_ne!(
        noncanonical,
        typed.canonical_bytes().expect("sorted-key encoding"),
        "fixture must exercise two distinct encodings"
    );

    // The runtime signer is genuine, but the payload is not the mandated
    // canonical envelope. Reject it rather than accepting two byte encodings
    // for the same cutover identity across the owner and Supervisor.
    let mut forged = original;
    forged.original_runtime_signature_bytes = SigningKey::from_bytes(&[9; 32])
        .sign(&noncanonical)
        .to_bytes()
        .to_vec();
    forged.original_runtime_receipt_bytes = noncanonical;
    fs::write(
        &path,
        canonical_json(&forged).expect("mutated original commit"),
    )
    .expect("out-of-band source replacement");
    assert!(cns.verify_current(&request, &committed).is_err());
    assert!(cns.read_committed(&request).is_err());
}
