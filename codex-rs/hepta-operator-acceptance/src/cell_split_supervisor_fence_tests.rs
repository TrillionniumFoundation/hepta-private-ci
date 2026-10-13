use std::fs;
use std::io::ErrorKind;
use std::os::unix::net::UnixListener;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::thread;
use std::time::Duration;

use super::*;
use crate::CellSplitEffectServiceV1;
use crate::CellSplitExecutionPortV1;
use crate::CellSplitUnixEffectPortV1;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct HandoffFile {
    supervisor_id: String,
    domain_id: String,
    old_generation: u64,
    new_generation: u64,
    epoch: u64,
    route_fence: String,
    plan_digest: String,
    phase: CellSplitSupervisorPhaseV1,
    old_admission_closed: bool,
    old_result_fenced: bool,
    new_admission_open: bool,
    unknown_effects: u32,
    revision: u64,
}

struct DiskSupervisor {
    root: PathBuf,
    signer: SigningKey,
    authorized: Arc<AtomicBool>,
    replay_old_readback: bool,
}

impl DiskSupervisor {
    fn new(root: PathBuf, authorized: Arc<AtomicBool>) -> Self {
        Self {
            root,
            signer: SigningKey::from_bytes(&[13; 32]),
            authorized,
            replay_old_readback: false,
        }
    }
    fn with_stale_readback(mut self) -> Self {
        self.replay_old_readback = true;
        self
    }
    fn state_path(&self) -> PathBuf {
        self.root.join("actual-writer-handoff.json")
    }
    fn receipt_path(&self, key: &str) -> PathBuf {
        self.root.join(format!("handoff-{key}.json"))
    }
    fn snapshot(&self) -> HandoffFile {
        serde_json::from_slice(&fs::read(self.state_path()).expect("real handoff file"))
            .expect("handoff state")
    }
    fn replace(&self, state: &HandoffFile) -> Result<(), String> {
        crate::durable::write_private_atomic_replace(
            &self.state_path(),
            &self.root.join("staged-handoff.tmp"),
            &canonical_json(state).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())
    }
}

impl CellSplitSupervisorRuntimePortV1 for DiskSupervisor {
    type Error = String;

    fn verify_preconditions(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
        binding: &CellSplitSupervisorFenceBindingV1,
    ) -> Result<(), Self::Error> {
        if !self.authorized.load(Ordering::Acquire)
            || intent.previous_receipt_digest != "77".repeat(32)
            || fs::read_to_string(self.root.join("actual-cns-route.txt"))
                .map_err(|e| e.to_string())?
                != binding.successor_route_digest
        {
            return Err("independent CNS receipt, final-use or route is unavailable".into());
        }
        Ok(())
    }

    fn read_live(
        &mut self,
        _supervisor_id: &str,
        _domain_id: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitSupervisorLiveFenceV1, Self::Error> {
        let state = self.snapshot();
        let actual_nonce = if self.replay_old_readback {
            "00".repeat(32)
        } else {
            challenge_nonce.to_owned()
        };
        let signature = self
            .signer
            .sign(&canonical_json(&(&state, &actual_nonce)).map_err(|e| e.to_string())?);
        Ok(CellSplitSupervisorLiveFenceV1 {
            supervisor_id: state.supervisor_id,
            domain_id: state.domain_id,
            old_generation: state.old_generation,
            new_generation: state.new_generation,
            authority_epoch: state.epoch,
            route_fence_digest: state.route_fence,
            handoff_plan_digest: state.plan_digest,
            phase: state.phase,
            old_writer_admission_closed: state.old_admission_closed,
            old_writer_result_fenced: state.old_result_fenced,
            new_writer_admission_open: state.new_admission_open,
            unknown_effect_count: state.unknown_effects,
            current_revision: state.revision,
            challenge_nonce: actual_nonce,
            signed_live_checkpoint_bytes: signature.to_bytes().to_vec(),
        })
    }

    fn verify_live(
        &mut self,
        observed: &CellSplitSupervisorLiveFenceV1,
    ) -> Result<(), Self::Error> {
        let current = self.snapshot();
        if observed.supervisor_id != current.supervisor_id
            || observed.domain_id != current.domain_id
            || observed.old_generation != current.old_generation
            || observed.new_generation != current.new_generation
            || observed.authority_epoch != current.epoch
            || observed.route_fence_digest != current.route_fence
            || observed.handoff_plan_digest != current.plan_digest
            || observed.phase != current.phase
            || observed.old_writer_admission_closed != current.old_admission_closed
            || observed.old_writer_result_fenced != current.old_result_fenced
            || observed.new_writer_admission_open != current.new_admission_open
            || observed.unknown_effect_count != current.unknown_effects
            || observed.current_revision != current.revision
        {
            return Err("live Supervisor checkpoint drift".into());
        }
        let signature = Signature::from_slice(&observed.signed_live_checkpoint_bytes)
            .map_err(|e| e.to_string())?;
        self.signer
            .verifying_key()
            .verify_strict(
                &canonical_json(&(&current, &observed.challenge_nonce))
                    .map_err(|e| e.to_string())?,
                &signature,
            )
            .map_err(|e| e.to_string())
    }

    fn finalize_once(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
        binding: &CellSplitSupervisorFenceBindingV1,
    ) -> Result<(), Self::Error> {
        self.verify_preconditions(plan, intent, binding)?;
        let mut current = self.snapshot();
        if current.phase != CellSplitSupervisorPhaseV1::RoutePublished
            || !current.old_admission_closed
            || !current.old_result_fenced
            || !current.new_admission_open
            || current.unknown_effects != 0
        {
            return Err("real handoff not ready for terminal retirement".into());
        }
        current.phase = CellSplitSupervisorPhaseV1::Retired;
        current.revision += 1;
        self.replace(&current)?;
        // Test-only durable checkpoint witness. Production uses the
        // authoritative Supervisor journal's original signed checkpoint.
        let proof = canonical_json(&(intent, &current)).map_err(|e| e.to_string())?;
        let signature = self.signer.sign(&proof).to_bytes().to_vec();
        let receipt = CellSplitSupervisorCommitV1 {
            idempotency_key: intent.idempotency_key.clone(),
            domain_id: binding.domain_id.clone(),
            handoff_plan_digest: binding.handoff_plan_digest.clone(),
            old_generation: plan.parent_generation,
            new_generation: plan.child_generation,
            authority_epoch: binding.authority_epoch,
            committed_revision: current.revision,
            original_checkpoint_bytes: proof,
            original_checkpoint_signature_bytes: signature,
        };
        crate::durable::write_private_new(
            &self.receipt_path(&intent.idempotency_key),
            &canonical_json(&receipt).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())
    }

    fn read_original_commit(
        &mut self,
        key: &str,
    ) -> Result<Option<CellSplitSupervisorCommitV1>, Self::Error> {
        match fs::read(self.receipt_path(key)) {
            Ok(bytes) => serde_json::from_slice(&bytes)
                .map(Some)
                .map_err(|e| e.to_string()),
            Err(e) if e.kind() == ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e.to_string()),
        }
    }

    fn verify_original_commit(
        &mut self,
        receipt: &CellSplitSupervisorCommitV1,
    ) -> Result<(), Self::Error> {
        let signature = Signature::from_slice(&receipt.original_checkpoint_signature_bytes)
            .map_err(|e| e.to_string())?;
        self.signer
            .verifying_key()
            .verify_strict(&receipt.original_checkpoint_bytes, &signature)
            .map_err(|e| e.to_string())
    }

    fn durable_revision(&mut self, _id: &str) -> Result<u64, Self::Error> {
        Ok(self.snapshot().revision)
    }
}

fn plan() -> CellSplitExecutionPlanV1 {
    CellSplitExecutionPlanV1 {
        split_id: "split.supervisor".into(),
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
fn binding() -> CellSplitSupervisorFenceBindingV1 {
    CellSplitSupervisorFenceBindingV1 {
        supervisor_id: "supervisor.main".into(),
        domain_id: "scope.domain".into(),
        authority_epoch: 7,
        handoff_plan_digest: "66".repeat(32),
        successor_route_digest: "88".repeat(32),
    }
}
fn intent() -> CellSplitExecutionIntentV1 {
    let digest = sha256(&canonical_json(&plan()).expect("plan"));
    let predecessor = "77".repeat(32);
    let key = sha256(
        format!(
            "hepta.learning.cell-split.execution-owner.v1\0{digest}\0{}\0{predecessor}",
            CellSplitExecutionStepV1::SupervisorGenerationFence.index()
        )
        .as_bytes(),
    );
    CellSplitExecutionIntentV1 {
        schema: "hepta.learning.cell-split.execution-owner.v1".into(),
        plan_digest: digest,
        step: CellSplitExecutionStepV1::SupervisorGenerationFence,
        owner_id: "supervisor-owner".into(),
        idempotency_key: key,
        previous_receipt_digest: predecessor,
    }
}
fn root() -> tempfile::TempDir {
    use std::os::unix::fs::PermissionsExt as _;
    let root = tempfile::tempdir().expect("private root");
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).expect("root permissions");
    let state = HandoffFile {
        supervisor_id: binding().supervisor_id,
        domain_id: binding().domain_id,
        old_generation: 3,
        new_generation: 4,
        epoch: 7,
        route_fence: plan().route_fence_digest,
        plan_digest: binding().handoff_plan_digest,
        phase: CellSplitSupervisorPhaseV1::RoutePublished,
        old_admission_closed: true,
        old_result_fenced: true,
        new_admission_open: true,
        unknown_effects: 0,
        revision: 8,
    };
    crate::durable::write_private_new(
        &root.path().join("actual-writer-handoff.json"),
        &canonical_json(&state).expect("handoff"),
    )
    .expect("initial durable handoff");
    crate::durable::write_private_new(
        &root.path().join("actual-cns-route.txt"),
        binding().successor_route_digest.as_bytes(),
    )
    .expect("CNS currently serves successor");
    root
}

fn owner(root: &Path, allowed: Arc<AtomicBool>) -> CellSplitSupervisorFenceOwnerV1<DiskSupervisor> {
    CellSplitSupervisorFenceOwnerV1::open(
        root,
        plan(),
        binding(),
        DiskSupervisor::new(root.to_path_buf(), allowed),
    )
    .expect("verified frozen Supervisor")
}

#[cfg(unix)]
#[test]
fn missing_original_supervisor_writer_lock_never_creates_second_writer() {
    let fixture = root();
    let allowed = Arc::new(AtomicBool::new(true));
    let _original = owner(fixture.path(), allowed.clone());
    let lock = fixture.path().join(crate::durable::SIDECAR_LOCK_FILE);
    fs::remove_file(&lock).expect("unlink original writer lock");
    let reopened = CellSplitSupervisorFenceOwnerV1::open(
        fixture.path(),
        plan(),
        binding(),
        DiskSupervisor::new(fixture.path().to_path_buf(), allowed),
    );
    assert!(matches!(
        reopened,
        Err(CellSplitSupervisorFenceErrorV1::Durable(_))
    ));
    assert!(!lock.exists(), "must not mint a replacement writer lock");
    assert!(fixture.path().join(FROZEN).exists());
}

#[test]
fn requires_closed_old_writer_and_current_route_before_finalizing() {
    let root = root();
    let allowed = Arc::new(AtomicBool::new(false));
    let mut owner = owner(root.path(), allowed.clone());
    assert!(owner.commit_once(&intent()).is_err());
    allowed.store(true, Ordering::Release);
    owner
        .commit_once(&intent())
        .expect("actual journal retirement");
    let original = owner
        .read_committed(&intent())
        .expect("read")
        .expect("committed");
    assert_eq!(original.owner_sequence, 9);
    assert!(owner.verify_current(&intent(), &original).expect("live"));
    assert!(matches!(
        owner.commit_once(&intent()),
        Err(CellSplitSupervisorFenceErrorV1::Ambiguous)
    ));
    drop(owner);
    let mut reopened = owner_factory(root.path(), allowed.clone());
    assert_eq!(
        reopened.read_committed(&intent()).unwrap(),
        Some(original.clone())
    );
    allowed.store(false, Ordering::Release);
    assert!(reopened.verify_current(&intent(), &original).is_err());
}
fn owner_factory(
    root: &Path,
    allowed: Arc<AtomicBool>,
) -> CellSplitSupervisorFenceOwnerV1<DiskSupervisor> {
    owner(root, allowed)
}

#[test]
fn missing_original_checkpoint_or_old_result_fence_blocks_recovery() {
    let root = root();
    let allowed = Arc::new(AtomicBool::new(true));
    let mut instance = owner(root.path(), allowed);
    let disk = DiskSupervisor::new(root.path().to_path_buf(), Arc::new(AtomicBool::new(true)));
    let mut state = disk.snapshot();
    state.old_result_fenced = false;
    disk.replace(&state)
        .expect("external old-writer fence regression");
    assert!(instance.commit_once(&intent()).is_err());
    state.old_result_fenced = true;
    state.phase = CellSplitSupervisorPhaseV1::Retired;
    state.revision = 9;
    disk.replace(&state)
        .expect("unknown terminal state without original");
    assert!(matches!(
        instance.read_committed(&intent()),
        Err(CellSplitSupervisorFenceErrorV1::Ambiguous)
    ));
}

#[test]
fn signed_supervisor_rpc_reopens_original_terminal_checkpoint() {
    let root = root();
    let listener =
        UnixListener::bind(root.path().join("supervisor.sock")).expect("real Supervisor socket");
    let root_copy = root.path().to_path_buf();
    let allowed = Arc::new(AtomicBool::new(true));
    let server = thread::spawn(move || {
        let mut service = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::SupervisorGenerationFence,
            "supervisor-owner".into(),
            sha256(&canonical_json(&plan()).expect("plan")),
            SigningKey::from_bytes(&[4; 32]),
            owner(&root_copy, allowed.clone()),
        )
        .expect("signature owner");
        for _ in 0..2 {
            let (mut stream, _) = listener.accept().expect("RPC");
            service
                .serve_connection(&mut stream)
                .expect("signed original");
        }
        drop(service);
        let mut reopened = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::SupervisorGenerationFence,
            "supervisor-owner".into(),
            sha256(&canonical_json(&plan()).expect("plan")),
            SigningKey::from_bytes(&[4; 32]),
            owner(&root_copy, allowed),
        )
        .expect("reopened owner");
        let (mut stream, _) = listener.accept().expect("reopen read");
        reopened
            .serve_connection(&mut stream)
            .expect("current signed readback");
    });
    let keys = [1u8, 2, 3, 4].map(|n| SigningKey::from_bytes(&[n; 32]).verifying_key());
    let mut client = CellSplitUnixEffectPortV1::new(
        [
            root.path().join("cas.sock"),
            root.path().join("migration.sock"),
            root.path().join("cns.sock"),
            root.path().join("supervisor.sock"),
        ],
        keys,
        Duration::from_secs(3),
    )
    .expect("trusted client");
    let committed = client.execute(&intent()).expect("actual terminal");
    client
        .verify_committed(&intent(), &committed)
        .expect("fresh readback");
    assert_eq!(
        client.reconcile(&intent()).expect("reopened"),
        Some(committed)
    );
    server.join().expect("real socket owner");
}

#[test]
fn corrupted_terminal_handoff_signature_never_grants_finalization() {
    let root = root();
    let mut owner = owner(root.path(), Arc::new(AtomicBool::new(true)));
    let request = intent();
    owner
        .commit_once(&request)
        .expect("real terminal checkpoint");
    let original = owner.read_committed(&request).unwrap().expect("original");
    let path = root
        .path()
        .join(format!("handoff-{}.json", request.idempotency_key));
    let mut tampered: CellSplitSupervisorCommitV1 =
        serde_json::from_slice(&fs::read(&path).expect("checkpoint")).expect("receipt");
    tampered.original_checkpoint_signature_bytes[0] ^= 0x80;
    fs::write(&path, canonical_json(&tampered).expect("modified terminal"))
        .expect("external tamper");
    assert!(owner.verify_current(&request, &original).is_err());
    assert!(owner.read_committed(&request).is_err());
}

#[test]
fn replayed_supervisor_checkpoint_is_not_a_fresh_readback() {
    let root = root();
    let port = DiskSupervisor::new(root.path().to_path_buf(), Arc::new(AtomicBool::new(true)))
        .with_stale_readback();
    let mut owner = CellSplitSupervisorFenceOwnerV1::open(root.path(), plan(), binding(), port)
        .expect("frozen Supervisor");
    assert!(matches!(
        owner.read_committed(&intent()),
        Err(CellSplitSupervisorFenceErrorV1::Invalid)
    ));
}

#[test]
fn lost_frozen_supervisor_identity_cannot_be_reinitialized() {
    // A preexisting sidecar proves a frozen identity once existed. Losing that
    // identity before or after finalization must never bootstrap fresh pins.
    for completed in [false, true] {
        let fixture = root();
        let allowed = Arc::new(AtomicBool::new(true));
        let mut first = owner(fixture.path(), allowed.clone());
        if completed {
            first
                .commit_once(&intent())
                .expect("original terminal transition");
        }
        let frozen = fixture.path().join("cell-split-supervisor-frozen.json");
        fs::remove_file(&frozen).expect("simulate partial backup or deletion");
        assert!(first.read_committed(&intent()).is_err());
        drop(first);
        let replay = CellSplitSupervisorFenceOwnerV1::open(
            fixture.path(),
            plan(),
            binding(),
            DiskSupervisor::new(fixture.path().to_path_buf(), allowed),
        );
        assert!(matches!(
            replay,
            Err(CellSplitSupervisorFenceErrorV1::Invalid)
        ));
        assert!(
            !frozen.exists(),
            "recovery must not rewrite deleted identity"
        );
    }
}

#[test]
fn retired_supervisor_requires_the_exact_terminal_revision() {
    let fixture = root();
    let mut first = owner(fixture.path(), Arc::new(AtomicBool::new(true)));
    let request = intent();
    first
        .commit_once(&request)
        .expect("original fsynced retirement");
    let receipt = first
        .read_committed(&request)
        .unwrap()
        .expect("original effect");
    let disk = DiskSupervisor::new(
        fixture.path().to_path_buf(),
        Arc::new(AtomicBool::new(true)),
    );
    let mut drift = disk.snapshot();
    assert_eq!(drift.phase, CellSplitSupervisorPhaseV1::Retired);
    drift.revision += 1; // A valid retired journal is terminal; this is drift.
    disk.replace(&drift)
        .expect("simulate unrelated runtime append");
    assert!(matches!(
        first.read_committed(&request),
        Err(CellSplitSupervisorFenceErrorV1::Invalid)
    ));
    assert!(matches!(
        first.verify_current(&request, &receipt),
        Err(CellSplitSupervisorFenceErrorV1::Invalid)
    ));
}
