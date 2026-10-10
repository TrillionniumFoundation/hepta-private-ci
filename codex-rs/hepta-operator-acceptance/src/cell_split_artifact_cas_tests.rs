use std::os::unix::net::UnixListener;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::thread;
use std::time::Duration;

use ed25519_dalek::SigningKey;

use super::*;
use crate::CellSplitEffectServiceV1;
use crate::CellSplitExecutionPortV1;
use crate::CellSplitUnixEffectPortV1;

#[derive(Clone)]
struct ExternalFinalUse(Arc<AtomicBool>);

impl CellSplitCasFinalUsePortV1 for ExternalFinalUse {
    type Error = &'static str;

    fn verify_current_authority(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        if self.0.load(Ordering::Acquire) &&
            plan.owner_ids[0] == intent.owner_id &&
            plan.ndu_snapshot_digest == "44".repeat(32) {
            Ok(())
        } else {
            Err("independent final-use source denies mutation")
        }
    }
}

fn plan() -> CellSplitExecutionPlanV1 {
    CellSplitExecutionPlanV1 {
        split_id: "artifact-cas-test".into(),
        scope_digest: "11".repeat(32),
        parent_generation: 5,
        child_generation: 6,
        parent_artifact_digest: sha256(b"parent immutable artifact"),
        child_artifact_digest: sha256(b"real child artifact bytes"),
        ndu_snapshot_digest: "44".repeat(32),
        route_fence_digest: "55".repeat(32),
        owner_ids: [
            "artifact-cas-owner".into(),
            "state-migration-owner".into(),
            "cns-owner".into(),
            "supervisor-owner".into(),
        ],
    }
}

fn intent(plan: &CellSplitExecutionPlanV1) -> CellSplitExecutionIntentV1 {
    let plan_digest = sha256(&canonical_json(plan).expect("plan"));
    let step = CellSplitExecutionStepV1::ArtifactCas;
    let idempotency_key = sha256(format!(
        "hepta.learning.cell-split.execution-owner.v1\0{plan_digest}\0{}\0{plan_digest}",
        step.index()
    ).as_bytes());
    CellSplitExecutionIntentV1 {
        schema: "hepta.learning.cell-split.execution-owner.v1".into(),
        plan_digest: plan_digest.clone(),
        step,
        owner_id: plan.owner_ids[0].clone(),
        idempotency_key,
        previous_receipt_digest: plan_digest,
    }
}

struct Fixture {
    root: tempfile::TempDir,
    store: PathBuf,
    parent: PathBuf,
    child: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        use std::os::unix::fs::PermissionsExt as _;
        let root = tempfile::tempdir().expect("fixture");
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))
            .expect("private root");
        let store = root.path().join("cas");
        fs::create_dir(&store).expect("cas root");
        fs::set_permissions(&store, fs::Permissions::from_mode(0o700))
            .expect("private CAS root");
        let parent = root.path().join("parent");
        let child = root.path().join("child");
        fs::write(&parent, b"parent immutable artifact").expect("parent");
        fs::write(&child, b"real child artifact bytes").expect("child");
        for path in [&parent, &child] {
            fs::set_permissions(path, fs::Permissions::from_mode(0o600)).expect("private file");
        }
        Self { root, store, parent, child }
    }

    fn owner(&self, authority: ExternalFinalUse) -> CellSplitArtifactCasOwnerV1<ExternalFinalUse> {
        CellSplitArtifactCasOwnerV1::open(
            &self.store, &self.parent, &self.child, plan(), authority
        ).expect("durable CAS owner")
    }
}

#[test]
fn create_only_cas_has_real_bytes_and_fails_closed_when_final_use_denied() {
    let fixture = Fixture::new();
    let allowed = Arc::new(AtomicBool::new(false));
    let mut owner = fixture.owner(ExternalFinalUse(allowed.clone()));
    let request = intent(&plan());
    assert!(owner.authorize_execute(&request).is_err());
    assert!(owner.commit_once(&request).is_err());
    assert!(owner.read_committed(&request).expect("no owner receipt").is_none());
    assert!(!owner.object_path().exists());

    allowed.store(true, Ordering::Release);
    owner.commit_once(&request).expect("create-only effect");
    let receipt = owner.read_committed(&request).expect("receipt").expect("committed");
    assert!(owner.verify_current(&request, &receipt).expect("live CAS"));
    assert_eq!(fs::read(owner.object_path()).expect("object"), b"real child artifact bytes");
    assert_eq!(owner.current_sequence().expect("durable frontier"), 1);
    owner.commit_once(&request).expect("exact idempotent replay");
    assert_eq!(owner.read_committed(&request).unwrap(), Some(receipt.clone()));

    fs::write(owner.object_path(), b"tampered object").expect("external CAS drift");
    assert!(!owner.verify_current(&request, &receipt).expect("state readback"));
    assert!(owner.commit_once(&request).is_err());
}

#[test]
fn committed_artifact_restarts_and_refuses_changed_parent_or_plan() {
    let fixture = Fixture::new();
    let authority = ExternalFinalUse(Arc::new(AtomicBool::new(true)));
    let request = intent(&plan());
    fixture.owner(authority.clone()).commit_once(&request).expect("first CAS");
    let mut reopened = fixture.owner(authority.clone());
    let committed = reopened.read_committed(&request).unwrap().expect("original bytes");
    assert!(reopened.verify_current(&request, &committed).unwrap());
    let mut different = plan();
    different.child_generation += 1;
    assert!(CellSplitArtifactCasOwnerV1::open(
        &fixture.store, &fixture.parent, &fixture.child, different, authority
    ).is_err());
    fs::write(&fixture.parent, b"replacement parent artifact").expect("drift");
    assert!(reopened.verify_current(&request, &committed).is_err());
}

#[test]
fn real_cas_socket_receipt_requires_fresh_state_even_after_backend_restart() {
    let fixture = Fixture::new();
    let socket = fixture.root.path().join("cas.sock");
    let listener = UnixListener::bind(&socket).expect("socket");
    let plan = plan();
    let request = intent(&plan);
    let key = SigningKey::from_bytes(&[1; 32]);
    let authority = ExternalFinalUse(Arc::new(AtomicBool::new(true)));
    let store = fixture.store.clone();
    let parent = fixture.parent.clone();
    let child = fixture.child.clone();
    let plan_copy = plan.clone();
    let server = thread::spawn(move || {
        let backend = CellSplitArtifactCasOwnerV1::open(
            &store, &parent, &child, plan_copy.clone(), authority.clone()
        ).expect("first owner");
        let mut service = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::ArtifactCas, plan_copy.owner_ids[0].clone(),
            request.plan_digest.clone(), key.clone(), backend
        ).expect("service");
        for _ in 0..3 {
            let (mut stream, _) = listener.accept().expect("first owner RPC");
            service.serve_connection(&mut stream).expect("signed RPC");
        }
        drop(service);
        let reopened = CellSplitArtifactCasOwnerV1::open(
            &store, &parent, &child, plan_copy.clone(), authority
        ).expect("reopened owner");
        let mut service = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::ArtifactCas, plan_copy.owner_ids[0].clone(),
            sha256(&canonical_json(&plan_copy).expect("plan")), key, reopened
        ).expect("reopened service");
        for _ in 0..2 {
            let (mut stream, _) = listener.accept().expect("restart RPC");
            let _ = service.serve_connection(&mut stream);
        }
    });
    let trust = [1u8, 2, 3, 4].map(|x|
        SigningKey::from_bytes(&[x; 32]).verifying_key()
    );
    let mut client = CellSplitUnixEffectPortV1::new(
        [
            socket, fixture.root.path().join("migration.sock"),
            fixture.root.path().join("cns.sock"),
            fixture.root.path().join("supervisor.sock"),
        ],
        trust, Duration::from_secs(3)
    ).expect("client");
    let operation = intent(&plan);
    assert!(client.reconcile(&operation).unwrap().is_none());
    let signed = client.execute(&operation).expect("committed CAS");
    client.verify_committed(&operation, &signed).expect("fresh original owner state");
    assert_eq!(client.reconcile(&operation).expect("restart readback"), Some(signed.clone()));
    fs::write(fixture.store.join(format!("sha256-{}", plan.child_artifact_digest)),
        b"corrupted on external host").expect("external corruption");
    assert!(client.verify_committed(&operation, &signed).is_err());
    server.join().expect("server");
}
