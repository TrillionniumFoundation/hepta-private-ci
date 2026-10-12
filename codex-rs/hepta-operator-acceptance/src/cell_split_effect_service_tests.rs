use std::fs;
use std::io;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::thread;
use std::time::Duration;

use ed25519_dalek::SigningKey;

use super::*;
use crate::CellSplitExecutionPortV1;
use crate::CellSplitUnixEffectPortV1;
use crate::durable::canonical_json;

struct DiskEffect {
    root: PathBuf,
    commits: usize,
    owner_id: String,
    sequence_override: Option<u64>,
}

impl DiskEffect {
    fn new(root: PathBuf, owner_id: &str) -> Self {
        Self {
            root,
            commits: 0,
            owner_id: owner_id.to_owned(),
            sequence_override: None,
        }
    }

    fn commit_path(&self) -> PathBuf {
        self.root.join("committed")
    }

    fn live_path(&self) -> PathBuf {
        self.root.join("live-owner-state")
    }
}

impl CellSplitDurableEffectBackendV1 for DiskEffect {
    type Error = io::Error;

    fn authorize_execute(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        if intent.owner_id != self.owner_id {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "untrusted owner",
            ));
        }
        Ok(())
    }

    fn commit_once(&mut self, intent: &CellSplitExecutionIntentV1) -> Result<(), Self::Error> {
        let bytes = canonical_json(intent).map_err(io::Error::other)?;
        // Source fixture only: production backends operate their own durable
        // CAS/state/route/fence. Two files model independently re-read state.
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(self.commit_path())?;
        use std::io::Write as _;
        file.write_all(&bytes)?;
        file.sync_all()?;
        let mut live = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(self.live_path())?;
        live.write_all(&bytes)?;
        live.sync_all()?;
        fs::File::open(&self.root)?.sync_all()?;
        self.commits += 1;
        Ok(())
    }

    fn read_committed(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitOwnedEffectV1>, Self::Error> {
        let bytes = match fs::read(self.commit_path()) {
            Ok(value) => value,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error),
        };
        let original: CellSplitExecutionIntentV1 =
            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if original != *intent {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "idempotency collision",
            ));
        }
        Ok(Some(CellSplitOwnedEffectV1 {
            owner_sequence: 7,
            owner_receipt_bytes: bytes,
        }))
    }

    fn verify_current(
        &mut self,
        _intent: &CellSplitExecutionIntentV1,
        effect: &CellSplitOwnedEffectV1,
    ) -> Result<bool, Self::Error> {
        Ok(
            fs::read(self.live_path()).ok() == Some(effect.owner_receipt_bytes.clone())
                && fs::read(self.commit_path()).ok() == Some(effect.owner_receipt_bytes.clone()),
        )
    }

    fn current_sequence(&mut self) -> Result<u64, Self::Error> {
        Ok(self.sequence_override.unwrap_or_else(|| {
            if self.commit_path().exists() {
                7
            } else {
                1
            }
        }))
    }
}

fn intent() -> CellSplitExecutionIntentV1 {
    let plan_digest = "11".repeat(32);
    let predecessor = "22".repeat(32);
    let idempotency_key = sha256(
        format!(
            "hepta.learning.cell-split.execution-owner.v1\0{plan_digest}\0{}\0{predecessor}",
            CellSplitExecutionStepV1::ArtifactCas.index()
        )
        .as_bytes(),
    );
    CellSplitExecutionIntentV1 {
        schema: "hepta.learning.cell-split.execution-owner.v1".into(),
        plan_digest,
        step: CellSplitExecutionStepV1::ArtifactCas,
        owner_id: "cas-owner".into(),
        idempotency_key,
        previous_receipt_digest: predecessor,
    }
}

fn keys() -> [ed25519_dalek::VerifyingKey; 4] {
    [1_u8, 2, 3, 4].map(|n| SigningKey::from_bytes(&[n; 32]).verifying_key())
}

fn client(root: &std::path::Path) -> CellSplitUnixEffectPortV1 {
    CellSplitUnixEffectPortV1::new(
        [
            root.join("cas.sock"),
            root.join("migration.sock"),
            root.join("cns.sock"),
            root.join("supervisor.sock"),
        ],
        keys(),
        Duration::from_secs(2),
    )
    .expect("trusted endpoints")
}

#[test]
fn disk_backed_owner_signs_only_current_state_and_detects_external_revocation() {
    let root = tempfile::tempdir().expect("fixture");
    let listener = UnixListener::bind(root.path().join("cas.sock")).expect("socket");
    let owner_root = root.path().to_path_buf();
    let server = thread::spawn(move || {
        let key = SigningKey::from_bytes(&[1; 32]);
        let mut service = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::ArtifactCas,
            "cas-owner".into(),
            intent().plan_digest,
            key,
            DiskEffect::new(owner_root, "cas-owner"),
        )
        .expect("service");
        // Signed negative preflight and lookup, execution, positive
        // verification and recovery, duplicate-preflight denial, then live
        // state revocation. Every read uses a distinct challenge nonce.
        for _ in 0..7 {
            let (mut stream, _) = listener.accept().expect("accept");
            let _ = service.serve_connection(&mut stream);
        }
        service.backend().commits
    });
    let mut client = client(root.path());
    let operation = intent();
    assert!(
        client
            .reconcile(&operation)
            .expect("negative signed readback")
            .is_none()
    );
    client
        .preflight_uncommitted(&operation)
        .expect("signed uncommitted owner preflight");
    let receipt = client.execute(&operation).expect("disk-backed commit");
    assert_eq!(receipt.owner_sequence, 7);
    client
        .verify_committed(&operation, &receipt)
        .expect("fresh state readback");
    assert_eq!(
        client.reconcile(&operation).expect("idempotent recovery"),
        Some(receipt.clone())
    );
    assert!(matches!(
        client.preflight_uncommitted(&operation),
        Err(CellSplitEffectRpcErrorV1::Invalid(
            "effect exists before coordinator prepared intent"
        ))
    ));
    fs::remove_file(root.path().join("live-owner-state")).expect("external revocation");
    assert!(client.verify_committed(&operation, &receipt).is_err());
    assert_eq!(server.join().expect("server completion"), 1);
}

#[test]
fn committed_effect_cannot_be_signed_ahead_of_durable_frontier() {
    let root = tempfile::tempdir().expect("fixture");
    let mut backend = DiskEffect::new(root.path().to_path_buf(), "cas-owner");
    backend.sequence_override = Some(6);
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        backend,
    )
    .expect("service");

    let (mut sender, mut receiver) = UnixStream::pair().expect("pair");
    send_frame(
        &mut sender,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::Execute,
            intent: intent(),
            challenge_nonce: None,
        },
    )
    .expect("execute");
    assert!(service.serve_connection(&mut receiver).is_err());
    assert_eq!(service.backend().commits, 1);
    assert!(root.path().join("committed").exists());

    // A freshly challenged readback is denied while the authoritative
    // sequence remains behind the original committed effect.
    let (mut sender, mut receiver) = UnixStream::pair().expect("pair");
    send_frame(
        &mut sender,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::ReadBack,
            intent: intent(),
            challenge_nonce: Some("aa".repeat(32)),
        },
    )
    .expect("readback");
    assert!(service.serve_connection(&mut receiver).is_err());
    drop(service);

    // Once a separate owner rereads the recovered sequence, only the
    // original durable effect is signed; it must never execute twice.
    let mut recovered = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        DiskEffect::new(root.path().to_path_buf(), "cas-owner"),
    )
    .expect("recovered service");
    let (mut sender, mut receiver) = UnixStream::pair().expect("pair");
    send_frame(
        &mut sender,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::ReadBack,
            intent: intent(),
            challenge_nonce: Some("bb".repeat(32)),
        },
    )
    .expect("reconcile");
    recovered
        .serve_connection(&mut receiver)
        .expect("frontier recovered");
    let response: CellSplitEffectRpcResponseV1 =
        receive_frame(&mut sender).expect("authenticated recovery");
    assert_eq!(response.receipt.expect("original receipt").owner_sequence, 7);
    assert!(response.readback.is_some());
    assert_eq!(recovered.backend().commits, 0);
}

#[test]
fn invalid_idempotency_key_is_rejected_before_backend_mutation() {
    let root = tempfile::tempdir().expect("fixture");
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        DiskEffect::new(root.path().to_path_buf(), "cas-owner"),
    )
    .expect("service");
    let (mut client_stream, mut service_stream) = UnixStream::pair().expect("pair");
    let mut forged = intent();
    forged.idempotency_key = "aa".repeat(32);
    send_frame(
        &mut client_stream,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::Execute,
            intent: forged,
            challenge_nonce: None,
        },
    )
    .expect("request");
    assert!(service.serve_connection(&mut service_stream).is_err());
    assert_eq!(service.backend().commits, 0);
    assert!(!root.path().join("committed").exists());
}

/// Exercise the real coordinator, RPC transport, independent signer keys and
/// disk-backed effect backends in their required four-step order. The fixture
/// is deliberately NOT a CAS/CNS/Supervisor implementation: it proves the
/// transport/recovery protocol, while actual target-owner adapters remain a
/// separate production integration gate.
#[test]
fn four_independent_socket_owners_recover_exact_committed_prefix_and_fence_revocation() {
    use std::sync::Arc;
    use std::sync::atomic::AtomicBool;
    use std::sync::atomic::Ordering;

    use crate::CellSplitExecutionOwnerV1;
    use crate::CellSplitExecutionPlanV1;
    use crate::CellSplitOwnerTrustV1;

    let root = tempfile::tempdir().expect("fixture");
    let ledger = root.path().join("ledger");
    fs::create_dir(&ledger).expect("ledger");
    use std::os::unix::fs::PermissionsExt as _;
    fs::set_permissions(&ledger, fs::Permissions::from_mode(0o700))
        .expect("private coordinator ledger");
    let owner_ids = [
        "cas-owner".to_owned(),
        "migration-owner".to_owned(),
        "cns-owner".to_owned(),
        "supervisor-owner".to_owned(),
    ];
    let plan = CellSplitExecutionPlanV1 {
        split_id: "signed-owner-four-step-test".into(),
        scope_digest: "11".repeat(32),
        parent_generation: 3,
        child_generation: 4,
        parent_artifact_digest: "22".repeat(32),
        child_artifact_digest: "33".repeat(32),
        ndu_snapshot_digest: "44".repeat(32),
        route_fence_digest: "55".repeat(32),
        owner_ids: owner_ids.clone(),
    };
    let plan_digest = sha256(&canonical_json(&plan).expect("plan"));
    let signer_keys = [1_u8, 2, 3, 4].map(|n| SigningKey::from_bytes(&[n; 32]));
    let trust = CellSplitOwnerTrustV1::new(
        &plan,
        signer_keys
            .iter()
            .map(|key| key.verifying_key())
            .collect::<Vec<_>>()
            .try_into()
            .expect("four owner keys"),
    )
    .expect("distinct trusted owners");
    let running = Arc::new(AtomicBool::new(true));
    let mut threads = Vec::new();
    let mut endpoints = Vec::new();
    for (index, owner_id) in owner_ids.iter().enumerate() {
        let owner_root = root.path().join(format!("owner-{index}"));
        fs::create_dir(&owner_root).expect("private owner root");
        let socket = root.path().join(format!("effect-{index}.sock"));
        let listener = UnixListener::bind(&socket).expect("owner socket");
        listener
            .set_nonblocking(true)
            .expect("nonblocking listener");
        endpoints.push(socket);
        let active = running.clone();
        let frozen_digest = plan_digest.clone();
        let owner_identity = owner_id.clone();
        let key = signer_keys[index].clone();
        threads.push(thread::spawn(move || {
            let step = match index {
                0 => CellSplitExecutionStepV1::ArtifactCas,
                1 => CellSplitExecutionStepV1::ChildStateMigration,
                2 => CellSplitExecutionStepV1::CnsRouteCutover,
                3 => CellSplitExecutionStepV1::SupervisorGenerationFence,
                _ => unreachable!(),
            };
            let backend = DiskEffect::new(owner_root, &owner_identity);
            let mut server =
                CellSplitEffectServiceV1::new(step, owner_identity, frozen_digest, key, backend)
                    .expect("owner server");
            while active.load(Ordering::Acquire) {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        let _ = server.serve_connection(&mut stream);
                    }
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(1));
                    }
                    Err(error) => panic!("owner listener: {error}"),
                }
            }
            server.backend().commits
        }));
    }
    let endpoints: [PathBuf; 4] = endpoints.try_into().expect("four endpoints");
    let port = CellSplitUnixEffectPortV1::new(endpoints.clone(), keys(), Duration::from_secs(3))
        .expect("trusted four-owner transport");
    {
        let mut owner = CellSplitExecutionOwnerV1::open(&ledger, plan.clone(), trust.clone(), port)
            .expect("open frozen coordinator");
        for index in 0..4 {
            let receipt = owner.advance().expect("durable effect").expect("step");
            assert_eq!(receipt.intent.step.index(), index);
            assert_eq!(owner.completed_steps(), index + 1);
        }
        assert!(owner.is_complete());
    }
    {
        let transport =
            CellSplitUnixEffectPortV1::new(endpoints.clone(), keys(), Duration::from_secs(3))
                .expect("reopened transport");
        let mut recovered =
            CellSplitExecutionOwnerV1::open(&ledger, plan.clone(), trust.clone(), transport)
                .expect("read every signed owner on restart");
        assert!(recovered.is_complete());
        assert!(recovered.advance().expect("already complete").is_none());
    }
    fs::remove_file(root.path().join("owner-2/live-owner-state"))
        .expect("independent CNS owner drift");
    let transport = CellSplitUnixEffectPortV1::new(endpoints, keys(), Duration::from_secs(3))
        .expect("transport");
    assert!(CellSplitExecutionOwnerV1::open(&ledger, plan, trust, transport).is_err());
    running.store(false, Ordering::Release);
    for handle in threads {
        assert_eq!(handle.join().expect("owner thread"), 1);
    }
}


/// An external writer may revoke an effect between the first live validation
/// and the separately retained frontier read. This fixture deliberately makes
/// that change *inside* the second frontier call, not after an RPC completes.
struct RevokeDuringFrontierRead {
    inner: DiskEffect,
    sequence_reads: usize,
}

impl CellSplitDurableEffectBackendV1 for RevokeDuringFrontierRead {
    type Error = io::Error;

    fn authorize_execute(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        self.inner.authorize_execute(intent)
    }

    fn commit_once(&mut self, intent: &CellSplitExecutionIntentV1) -> Result<(), Self::Error> {
        self.inner.commit_once(intent)
    }

    fn read_committed(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitOwnedEffectV1>, Self::Error> {
        self.inner.read_committed(intent)
    }

    fn verify_current(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        effect: &CellSplitOwnedEffectV1,
    ) -> Result<bool, Self::Error> {
        self.inner.verify_current(intent, effect)
    }

    fn current_sequence(&mut self) -> Result<u64, Self::Error> {
        let sequence = self.inner.current_sequence()?;
        self.sequence_reads += 1;
        if self.sequence_reads == 2 {
            fs::remove_file(self.inner.live_path())?;
        }
        Ok(sequence)
    }
}

#[test]
fn frontier_advance_between_verification_and_signature_rejects_stale_readback() {
    let root = tempfile::tempdir().expect("fixture");
    let mut live = DiskEffect::new(root.path().to_path_buf(), "cas-owner");
    live.commit_once(&intent()).expect("original durable effect");
    let backend = RevokeDuringFrontierRead {
        inner: live,
        sequence_reads: 0,
    };
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        backend,
    )
    .expect("signed service");

    let (mut client, mut server) = UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::ReadBack,
            intent: intent(),
            challenge_nonce: Some("bb".repeat(32)),
        },
    )
    .expect("readback request");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitEffectRpcErrorV1::Invalid(
            "effect changed during signed readback"
        ))
    ));
    assert_eq!(service.backend().sequence_reads, 2);
    assert!(!root.path().join("live-owner-state").exists());
    assert!(root.path().join("committed").exists());
}


#[derive(Clone, Copy)]
enum MutationAtFrontier {
    CommitBeforeNegativeSignature,
    AdvanceDuringPositiveSignature,
    RevokeDuringFinalFrontier,
    RevokeDuringExecuteAcknowledgement,
    AdvanceDuringExecuteAcknowledgement,
}

/// Inject a real effect appearing during an independently sampled frontier,
/// or a later monotonic frontier revision after a positive state check.
struct MutateAtFrontierRead {
    inner: DiskEffect,
    intent: CellSplitExecutionIntentV1,
    mode: MutationAtFrontier,
    sequence_reads: usize,
}

impl CellSplitDurableEffectBackendV1 for MutateAtFrontierRead {
    type Error = io::Error;

    fn authorize_execute(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        self.inner.authorize_execute(intent)
    }

    fn commit_once(&mut self, intent: &CellSplitExecutionIntentV1) -> Result<(), Self::Error> {
        self.inner.commit_once(intent)
    }

    fn read_committed(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitOwnedEffectV1>, Self::Error> {
        self.inner.read_committed(intent)
    }

    fn verify_current(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        effect: &CellSplitOwnedEffectV1,
    ) -> Result<bool, Self::Error> {
        self.inner.verify_current(intent, effect)
    }

    fn current_sequence(&mut self) -> Result<u64, Self::Error> {
        self.sequence_reads += 1;
        if matches!(self.mode, MutationAtFrontier::CommitBeforeNegativeSignature)
            && self.sequence_reads == 1
        {
            self.inner.commit_once(&self.intent)?;
        }
        if matches!(
            self.mode,
            MutationAtFrontier::AdvanceDuringPositiveSignature
                | MutationAtFrontier::AdvanceDuringExecuteAcknowledgement
        ) && self.sequence_reads == 3
        {
            self.inner.sequence_override = Some(8);
        }
        if matches!(
            self.mode,
            MutationAtFrontier::RevokeDuringFinalFrontier
                | MutationAtFrontier::RevokeDuringExecuteAcknowledgement
        ) && self.sequence_reads == 3
        {
            fs::remove_file(self.inner.live_path())?;
        }
        self.inner.current_sequence()
    }
}

#[test]
fn negative_readback_refuses_commit_appearing_during_frontier_check() {
    let root = tempfile::tempdir().expect("private owner root");
    let backend = MutateAtFrontierRead {
        inner: DiskEffect::new(root.path().to_path_buf(), "cas-owner"),
        intent: intent(),
        mode: MutationAtFrontier::CommitBeforeNegativeSignature,
        sequence_reads: 0,
    };
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        backend,
    )
    .expect("owner");
    let (mut client, mut server) = UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::ReadBack,
            intent: intent(),
            challenge_nonce: Some("aa".repeat(32)),
        },
    )
    .expect("signed negative query");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitEffectRpcErrorV1::Invalid(
            "effect changed during signed readback"
        ))
    ));
    assert_eq!(service.backend().sequence_reads, 1);
    assert!(root.path().join("committed").exists());
    assert!(root.path().join("live-owner-state").exists());
}

#[test]
fn positive_readback_refuses_frontier_revision_after_live_verification() {
    let root = tempfile::tempdir().expect("private owner root");
    let mut disk = DiskEffect::new(root.path().to_path_buf(), "cas-owner");
    disk.commit_once(&intent()).expect("real durable first effect");
    let backend = MutateAtFrontierRead {
        inner: disk,
        intent: intent(),
        mode: MutationAtFrontier::AdvanceDuringPositiveSignature,
        sequence_reads: 0,
    };
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        backend,
    )
    .expect("owner");
    let (mut client, mut server) = UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::ReadBack,
            intent: intent(),
            challenge_nonce: Some("bb".repeat(32)),
        },
    )
    .expect("positive query");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitEffectRpcErrorV1::Invalid(
            "owner frontier changed during signed readback"
        ))
    ));
    assert_eq!(service.backend().sequence_reads, 3);
    assert_eq!(service.backend().inner.commits, 1);
}

#[test]
fn last_frontier_read_cannot_launder_revoked_effect_into_signed_positive() {
    let root = tempfile::tempdir().expect("private owner root");
    let mut disk = DiskEffect::new(root.path().to_path_buf(), "cas-owner");
    disk.commit_once(&intent()).expect("real original effect");
    let backend = MutateAtFrontierRead {
        inner: disk,
        intent: intent(),
        mode: MutationAtFrontier::RevokeDuringFinalFrontier,
        sequence_reads: 0,
    };
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        backend,
    )
    .expect("pinned owner");
    let (mut client, mut server) = UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::ReadBack,
            intent: intent(),
            challenge_nonce: Some("cc".repeat(32)),
        },
    )
    .expect("request");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitEffectRpcErrorV1::Invalid(
            "effect changed after final frontier read"
        ))
    ));
    assert_eq!(service.backend().sequence_reads, 3);
    assert!(!root.path().join("live-owner-state").exists());
    assert!(root.path().join("committed").exists());
}

#[test]
fn execute_acknowledgement_fails_if_live_effect_disappears_after_frontier() {
    let root = tempfile::tempdir().expect("private owner root");
    let backend = MutateAtFrontierRead {
        inner: DiskEffect::new(root.path().to_path_buf(), "cas-owner"),
        intent: intent(),
        mode: MutationAtFrontier::RevokeDuringExecuteAcknowledgement,
        sequence_reads: 0,
    };
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        backend,
    )
    .expect("signed effect owner");
    let (mut client, mut server) = UnixStream::pair().expect("pair");
    send_frame(
        &mut client,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::Execute,
            intent: intent(),
            challenge_nonce: None,
        },
    )
    .expect("request");

    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitEffectRpcErrorV1::Invalid(
            "effect changed before signed execute acknowledgement"
        ))
    ));
    assert_eq!(service.backend().sequence_reads, 3);
    assert_eq!(service.backend().inner.commits, 1);
    assert!(root.path().join("committed").exists());
    assert!(!root.path().join("live-owner-state").exists());
}

#[test]
fn execute_acknowledgement_rejects_a_changing_durable_frontier() {
    let root = tempfile::tempdir().expect("private owner root");
    let backend = MutateAtFrontierRead {
        inner: DiskEffect::new(root.path().to_path_buf(), "cas-owner"),
        intent: intent(),
        mode: MutationAtFrontier::AdvanceDuringExecuteAcknowledgement,
        sequence_reads: 0,
    };
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        backend,
    )
    .expect("signed effect owner");
    let (mut client, mut server) = UnixStream::pair().expect("pair");
    send_frame(
        &mut client,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::Execute,
            intent: intent(),
            challenge_nonce: None,
        },
    )
    .expect("request");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitEffectRpcErrorV1::Invalid(
            "effect changed before signed execute acknowledgement"
        ))
    ));
    assert_eq!(service.backend().sequence_reads, 3);
    assert_eq!(service.backend().inner.commits, 1);
    assert!(root.path().join("committed").exists());
    assert!(root.path().join("live-owner-state").exists());
}


/// Simulate the independent Selector withdrawing final-use during the real
/// disk commit. The effect may exist, but it must not receive a fresh signed
/// Execute acknowledgement after the current authorization has been revoked.
struct RevokeFinalUseAfterCommit {
    inner: DiskEffect,
    authorized: bool,
    authority_checks: usize,
}

impl CellSplitDurableEffectBackendV1 for RevokeFinalUseAfterCommit {
    type Error = io::Error;

    fn authorize_execute(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        self.authority_checks += 1;
        if !self.authorized {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "independent final-use revoked",
            ));
        }
        self.inner.authorize_execute(intent)
    }

    fn commit_once(&mut self, intent: &CellSplitExecutionIntentV1) -> Result<(), Self::Error> {
        self.inner.commit_once(intent)?;
        self.authorized = false;
        Ok(())
    }

    fn read_committed(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitOwnedEffectV1>, Self::Error> {
        self.inner.read_committed(intent)
    }

    fn verify_current(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        effect: &CellSplitOwnedEffectV1,
    ) -> Result<bool, Self::Error> {
        self.inner.verify_current(intent, effect)
    }

    fn current_sequence(&mut self) -> Result<u64, Self::Error> {
        self.inner.current_sequence()
    }
}

#[test]
fn execute_does_not_sign_after_independent_final_use_revocation() {
    let root = tempfile::tempdir().expect("durable fixture");
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        RevokeFinalUseAfterCommit {
            inner: DiskEffect::new(root.path().to_path_buf(), "cas-owner"),
            authorized: true,
            authority_checks: 0,
        },
    )
    .expect("independent owner");
    let (mut client, mut server) = UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::Execute,
            intent: intent(),
            challenge_nonce: None,
        },
    )
    .expect("execute request");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitEffectRpcErrorV1::Rejected(_))
    ));
    assert_eq!(service.backend().authority_checks, 2);
    assert_eq!(service.backend().inner.commits, 1);
    assert!(root.path().join("committed").exists());
    assert!(root.path().join("live-owner-state").exists());
}


#[test]
fn partial_owner_rpc_frame_times_out_without_signing_or_mutation() {
    use std::io::Write as _;

    let root = tempfile::tempdir().expect("private fixture");
    let backend = DiskEffect::new(root.path().to_path_buf(), "cas-owner");
    let mut service = CellSplitEffectServiceV1::new_with_io_timeout(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        backend,
        Duration::from_millis(20),
    )
    .expect("bounded serving owner");
    let (mut sender, mut receiver) = UnixStream::pair().expect("socket pair");
    // A peer sends only half a length header and remains connected. Without
    // an owner-enforced deadline the only service thread would block forever.
    sender.write_all(&[0, 0]).expect("truncated length prefix");
    assert!(matches!(
        service.serve_connection(&mut receiver),
        Err(CellSplitEffectRpcErrorV1::Io(error))
            if matches!(error.kind(), io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock)
    ));
    assert_eq!(service.backend().commits, 0);
    assert!(!root.path().join("committed").exists());
    assert!(!root.path().join("live-owner-state").exists());
}

#[test]
fn owner_rpc_timeout_must_be_bounded_and_nonzero() {
    for timeout in [
        Duration::ZERO,
        Duration::from_nanos(1),
        Duration::from_secs(31),
    ] {
        assert!(matches!(
            CellSplitEffectServiceV1::new_with_io_timeout(
                CellSplitExecutionStepV1::ArtifactCas,
                "cas-owner".into(),
                intent().plan_digest,
                SigningKey::from_bytes(&[1; 32]),
                DiskEffect::new(PathBuf::from("/tmp"), "cas-owner"),
                timeout,
            ),
            Err(CellSplitEffectRpcErrorV1::Invalid(
                "effect service transport timeout"
            ))
        ));
    }
}


#[test]
fn partial_owner_rpc_payload_times_out_before_any_authority_check() {
    use std::io::Write as _;

    let root = tempfile::tempdir().expect("private fixture");
    let backend = DiskEffect::new(root.path().to_path_buf(), "cas-owner");
    let mut service = CellSplitEffectServiceV1::new_with_io_timeout(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        backend,
        Duration::from_millis(20),
    )
    .expect("bounded owner");
    let (mut sender, mut receiver) = UnixStream::pair().expect("socket pair");
    // A valid small declared frame size followed by an incomplete body
    // cannot leave the signing owner indefinitely waiting for JSON bytes.
    sender
        .write_all(&32_u32.to_be_bytes())
        .expect("length header");
    sender.write_all(b"{").expect("incomplete JSON body");
    assert!(matches!(
        service.serve_connection(&mut receiver),
        Err(CellSplitEffectRpcErrorV1::Io(error))
            if matches!(error.kind(), io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock)
    ));
    assert_eq!(service.backend().commits, 0);
    assert!(!root.path().join("committed").exists());
}


#[test]
fn trickled_owner_request_cannot_extend_total_frame_deadline() {
    use std::io::Write as _;

    let root = tempfile::tempdir().expect("private owner root");
    let mut service = CellSplitEffectServiceV1::new_with_io_timeout(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        DiskEffect::new(root.path().to_path_buf(), "cas-owner"),
        Duration::from_millis(45),
    )
    .expect("bounded signed service");
    let (mut sender, mut receiver) = UnixStream::pair().expect("socket pair");
    let peer = thread::spawn(move || {
        // Eight bytes arrive slowly, with every individual gap smaller than
        // the configured timeout. A per-read timeout would accept the frame
        // and produce a JSON parse error instead of enforcing 45 ms overall.
        for byte in [0_u8, 0, 0, 4, b'n', b'u', b'l', b'l'] {
            if sender.write_all(&[byte]).is_err() {
                break;
            }
            thread::sleep(Duration::from_millis(10));
        }
    });
    let outcome = service.serve_connection(&mut receiver);
    assert!(matches!(
        outcome,
        Err(CellSplitEffectRpcErrorV1::Invalid(
            "RPC frame deadline exceeded"
        )) | Err(CellSplitEffectRpcErrorV1::Io(_))
    ));
    peer.join().expect("slow peer finished");
    assert_eq!(service.backend().commits, 0);
    assert!(!root.path().join("committed").exists());
}

#[test]
fn new_execute_cannot_adopt_effect_created_after_negative_preflight() {
    let root = tempfile::tempdir().expect("private owner root");
    let operation = intent();
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        operation.plan_digest.clone(),
        SigningKey::from_bytes(&[1; 32]),
        DiskEffect::new(root.path().to_path_buf(), "cas-owner"),
    )
    .expect("pinned signing owner");

    // The real coordinator's negative preflight is signed by the original
    // owner, but cannot act as a permanent reservation against another writer.
    let (mut client, mut server) = UnixStream::pair().expect("preflight socket");
    send_frame(
        &mut client,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::ReadBack,
            intent: operation.clone(),
            challenge_nonce: Some("aa".repeat(32)),
        },
    )
    .expect("readback request");
    service.serve_connection(&mut server).expect("negative owner readback");
    let negative: CellSplitEffectRpcResponseV1 =
        receive_frame(&mut client).expect("signed negative response");
    assert!(negative.receipt.is_none());
    assert!(negative.readback.is_some());

    // A different writer commits exactly the same idempotency key between
    // the negative preflight and Execute; this signing service did not do it.
    let mut external = DiskEffect::new(root.path().to_path_buf(), "cas-owner");
    external.commit_once(&operation).expect("racing external durable commit");
    assert_eq!(external.commits, 1);
    assert_eq!(service.backend().commits, 0);

    let (mut client, mut server) = UnixStream::pair().expect("execute socket");
    send_frame(
        &mut client,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::Execute,
            intent: operation.clone(),
            challenge_nonce: None,
        },
    )
    .expect("new execute request");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitEffectRpcErrorV1::Invalid(
            "effect already committed before new execute intent"
        ))
    ));
    assert_eq!(service.backend().commits, 0);

    // Existing effects are recoverable only through nonce-bound ReadBack.
    let (mut client, mut server) = UnixStream::pair().expect("recovery socket");
    send_frame(
        &mut client,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::ReadBack,
            intent: operation,
            challenge_nonce: Some("bb".repeat(32)),
        },
    )
    .expect("read-only reconciliation");
    service.serve_connection(&mut server).expect("original durable readback");
    let recovery: CellSplitEffectRpcResponseV1 =
        receive_frame(&mut client).expect("recovered owner response");
    assert_eq!(recovery.receipt.expect("original effect").owner_sequence, 7);
    assert!(recovery.readback.is_some());
    assert_eq!(service.backend().commits, 0);
}

#[test]
fn new_execute_rejects_an_effect_that_appears_during_precommit_frontier_read() {
    let root = tempfile::tempdir().expect("owner root");
    let backend = MutateAtFrontierRead {
        inner: DiskEffect::new(root.path().to_path_buf(), "cas-owner"),
        intent: intent(),
        mode: MutationAtFrontier::CommitBeforeNegativeSignature,
        sequence_reads: 0,
    };
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        backend,
    )
    .expect("service");
    let (mut client, mut server) = UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::Execute,
            intent: intent(),
            challenge_nonce: None,
        },
    )
    .expect("execute request");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitEffectRpcErrorV1::Invalid(
            "effect already committed before new execute intent"
        ))
    ));
    // The independently racing mutation is the only committed effect.
    assert_eq!(service.backend().sequence_reads, 1);
    assert_eq!(service.backend().inner.commits, 1);
}

#[test]
fn new_execute_requires_fresh_original_owner_frontier_advance() {
    let root = tempfile::tempdir().expect("owner root");
    let mut backend = DiskEffect::new(root.path().to_path_buf(), "cas-owner");
    // Create real durable effect bytes while falsely retaining the same
    // original owner frontier before and after commit.
    backend.sequence_override = Some(7);
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        backend,
    )
    .expect("service");
    let (mut client, mut server) = UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::Execute,
            intent: intent(),
            challenge_nonce: None,
        },
    )
    .expect("execute request");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitEffectRpcErrorV1::Invalid(
            "effect did not advance original durable owner frontier"
        ))
    ));
    assert_eq!(service.backend().commits, 1);
    assert!(root.path().join("committed").exists());
    // An ambiguous effect is reconciled read-only, not retried.
}

#[test]
fn new_execute_rejects_unavailable_frontier_without_committing() {
    let root = tempfile::tempdir().expect("owner root");
    let mut backend = DiskEffect::new(root.path().to_path_buf(), "cas-owner");
    backend.sequence_override = Some(0);
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        backend,
    )
    .expect("service");
    let (mut client, mut server) = UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action: CellSplitEffectRpcActionV1::Execute,
            intent: intent(),
            challenge_nonce: None,
        },
    )
    .expect("execute request");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitEffectRpcErrorV1::Invalid(
            "owner frontier unavailable before execute"
        ))
    ));
    assert_eq!(service.backend().commits, 0);
    assert!(!root.path().join("committed").exists());
}
