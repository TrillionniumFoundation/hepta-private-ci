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
}

impl DiskEffect {
    fn new(root: PathBuf) -> Self {
        Self { root, commits: 0 }
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

    fn authorize_execute(&mut self, intent: &CellSplitExecutionIntentV1)
        -> Result<(), Self::Error>
    {
        if intent.owner_id != "cas-owner" {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied, "untrusted owner"));
        }
        Ok(())
    }

    fn commit_once(&mut self, intent: &CellSplitExecutionIntentV1)
        -> Result<(), Self::Error>
    {
        let bytes = canonical_json(intent).map_err(io::Error::other)?;
        // Source fixture only: production backends operate their own durable
        // CAS/state/route/fence. Two files model independently re-read state.
        let mut file = fs::OpenOptions::new().write(true).create_new(true)
            .open(self.commit_path())?;
        use std::io::Write as _;
        file.write_all(&bytes)?;
        file.sync_all()?;
        let mut live = fs::OpenOptions::new().write(true).create_new(true)
            .open(self.live_path())?;
        live.write_all(&bytes)?;
        live.sync_all()?;
        fs::File::open(&self.root)?.sync_all()?;
        self.commits += 1;
        Ok(())
    }

    fn read_committed(&mut self, intent: &CellSplitExecutionIntentV1)
        -> Result<Option<CellSplitOwnedEffectV1>, Self::Error>
    {
        let bytes = match fs::read(self.commit_path()) {
            Ok(value) => value,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error),
        };
        let original: CellSplitExecutionIntentV1 = serde_json::from_slice(&bytes)?;
        if original != *intent {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "idempotency collision"));
        }
        Ok(Some(CellSplitOwnedEffectV1 { owner_sequence: 7, owner_receipt_bytes: bytes }))
    }

    fn verify_current(
        &mut self,
        _intent: &CellSplitExecutionIntentV1,
        effect: &CellSplitOwnedEffectV1,
    ) -> Result<bool, Self::Error> {
        Ok(fs::read(self.live_path()).ok() == Some(effect.owner_receipt_bytes.clone())
            && fs::read(self.commit_path()).ok() == Some(effect.owner_receipt_bytes.clone()))
    }

    fn current_sequence(&mut self) -> Result<u64, Self::Error> {
        Ok(if self.commit_path().exists() { 7 } else { 1 })
    }
}

fn intent() -> CellSplitExecutionIntentV1 {
    let plan_digest = "11".repeat(32);
    let predecessor = "22".repeat(32);
    let idempotency_key = sha256(
        format!(
            "hepta.learning.cell-split.execution-owner.v1\0{plan_digest}\0{}\0{predecessor}",
            CellSplitExecutionStepV1::ArtifactCas.index()
        ).as_bytes(),
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
    ).expect("trusted endpoints")
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
            DiskEffect::new(owner_root),
        ).expect("service");
        // Negative signed lookup, execution, positive verification, recovery,
        // and verification after the actual live state has disappeared.
        for _ in 0..5 {
            let (mut stream, _) = listener.accept().expect("accept");
            let _ = service.serve_connection(&mut stream);
        }
        service.backend().commits
    });
    let mut client = client(root.path());
    let operation = intent();
    assert!(client.reconcile(&operation).expect("negative signed readback").is_none());
    let receipt = client.execute(&operation).expect("disk-backed commit");
    assert_eq!(receipt.owner_sequence, 7);
    client.verify_committed(&operation, &receipt).expect("fresh state readback");
    assert_eq!(client.reconcile(&operation).expect("idempotent recovery"), Some(receipt.clone()));
    fs::remove_file(root.path().join("live-owner-state")).expect("external revocation");
    assert!(client.verify_committed(&operation, &receipt).is_err());
    assert_eq!(server.join().expect("server completion"), 1);
}

#[test]
fn invalid_idempotency_key_is_rejected_before_backend_mutation() {
    let root = tempfile::tempdir().expect("fixture");
    let mut service = CellSplitEffectServiceV1::new(
        CellSplitExecutionStepV1::ArtifactCas,
        "cas-owner".into(),
        intent().plan_digest,
        SigningKey::from_bytes(&[1; 32]),
        DiskEffect::new(root.path().to_path_buf()),
    ).expect("service");
    let (mut client_stream, mut service_stream) = UnixStream::pair().expect("pair");
    let mut forged = intent();
    forged.idempotency_key = "aa".repeat(32);
    send_frame(&mut client_stream, &CellSplitEffectRpcRequestV1 {
        schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
        action: CellSplitEffectRpcActionV1::Execute,
        intent: forged,
        challenge_nonce: None,
    }).expect("request");
    assert!(service.serve_connection(&mut service_stream).is_err());
    assert_eq!(service.backend().commits, 0);
    assert!(!root.path().join("committed").exists());
}
