#![cfg(unix)]

use std::fs;
use std::io::Read;
use std::io::Write;
use std::net::Shutdown;
use std::net::TcpListener;
use std::net::TcpStream;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::thread;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_learning_artifacts::DatasetWithdrawalScopeV1;
use codex_hepta_learning_artifacts::SignedArtifactWriterLeaseV1;
use codex_hepta_learning_artifacts::owner::ArtifactOwnerActionV1;
use codex_hepta_learning_artifacts::owner::SignedArtifactOwnerRequestV1;
use codex_hepta_learning_artifacts::owner::restore_owner_root_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

struct TestRoot(PathBuf);

impl TestRoot {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "hepta-learning-artifactd-process-{}-{}",
            std::process::id(),
            now()
        ));
        fs::create_dir(&root).expect("test root");
        Self(root)
    }
}

impl Drop for TestRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs()
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}

fn secure_write(path: &Path, bytes: &[u8]) {
    fs::write(path, bytes).expect("write fixture");
    let mut permissions = fs::metadata(path).expect("fixture metadata").permissions();
    permissions.set_mode(0o600);
    fs::set_permissions(path, permissions).expect("secure fixture");
}

fn free_address() -> std::net::SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").expect("reserve port");
    let address = listener.local_addr().expect("local address");
    drop(listener);
    address
}

fn prepare(root: &TestRoot, address: std::net::SocketAddr) -> (PathBuf, PathBuf, PathBuf, SigningKey) {
    let store = root.0.join("store");
    let backup = root.0.join("backup");
    fs::create_dir(&backup).expect("backup root");
    let mut backup_permissions = fs::metadata(&backup).expect("backup metadata").permissions();
    backup_permissions.set_mode(0o700);
    fs::set_permissions(&backup, backup_permissions).expect("private backup root");
    let authz = root.0.join("authz.conf");
    let config = root.0.join("owner.conf");
    let owner_key = SigningKey::from_bytes(&[31; 32]);
    let client_key = SigningKey::from_bytes(&[47; 32]);
    let issued = now().saturating_sub(5);
    let expires = issued.saturating_add(3600);
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
        authority_domain_id: id("dataset-authority"),
        registry_id: id("withdrawals"),
        scope_id: id("production-scope"),
    });
    let scope = withdrawals.scope_digest().expect("scope digest");
    let signing_key_digest = Digest32::of_bytes(&owner_key.verifying_key().to_bytes());
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("daemon-writer-lease"),
        producer_id: id("trainer"),
        registry_id: id("learning-artifacts"),
        withdrawal_scope_digest: scope,
        signer_id: id("owner-authority"),
        signing_key_digest,
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: issued,
        expires_at: expires,
        signature: [0; 64],
    };
    lease.signature = owner_key.sign(&lease.signing_bytes()).to_bytes();

    secure_write(
        &authz,
        format!(
            concat!(
                "schema=hepta.learning-artifactd.authz.v1\n",
                "generation=1\n",
                "client.operator=operator|{}|{}|{}|-|health,metrics,backup,reload_authz,shutdown\n"
            ),
            hex(&client_key.verifying_key().to_bytes()),
            issued,
            expires,
        )
        .as_bytes(),
    );
    let signer = format!(
        "owner-authority|{}|1|9|{}|{}|-",
        hex(&owner_key.verifying_key().to_bytes()),
        issued,
        expires
    );
    secure_write(
        &config,
        format!(
            concat!(
                "schema=hepta.learning-artifactd.config.v1\n",
                "root={}\nlisten={}\nauthz_file={}\nbackup_root={}\n",
                "registry_id=learning-artifacts\nwithdrawal_scope_digest={}\n",
                "minimum_registry_generation=1\ngenesis_predecessor_head_digest={}\n",
                "minimum_authority_epoch=1\nwriter_signer.primary={}\nhead_signer.primary={}\n",
                "lease_id={}\nproducer_id={}\nlease_signer_id={}\n",
                "lease_signing_key_digest={}\nlease_authority_epoch=1\nlease_generation=1\n",
                "lease_issued_at={}\nlease_expires_at={}\nlease_signature={}\n",
                "storage_binding={}\nwithdrawal_mode=genesis\n",
                "withdrawal_authority_domain_id=dataset-authority\n",
                "withdrawal_registry_id=withdrawals\nwithdrawal_scope_id=production-scope\n",
                "maximum_request_bytes=1048576\n"
            ),
            store.display(),
            address,
            authz.display(),
            backup.display(),
            scope,
            Digest32::ZERO,
            signer,
            signer,
            lease.lease_id,
            lease.producer_id,
            lease.signer_id,
            lease.signing_key_digest,
            lease.issued_at,
            lease.expires_at,
            hex(&lease.signature),
            digest("daemon-storage-binding"),
        )
        .as_bytes(),
    );
    (config, authz, backup, client_key)
}

fn spawn(config: &Path) -> Child {
    Command::new(env!("CARGO_BIN_EXE_hepta-learning-artifactd"))
        .arg(config)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::inherit())
        .spawn()
        .expect("spawn artifact daemon")
}

fn signed_request(
    action: ArtifactOwnerActionV1,
    sequence: u64,
    generation: u64,
    client_key: &SigningKey,
) -> SignedArtifactOwnerRequestV1 {
    let issued = now();
    let mut request = SignedArtifactOwnerRequestV1 {
        keyring_generation: generation,
        request_id: id(&format!("request-{sequence}")),
        client_id: id("operator"),
        action,
        issued_at: issued,
        expires_at: issued.saturating_add(60),
        nonce: id(&format!("nonce-{sequence}")),
        payload: Vec::new(),
        signature: [0; 64],
    };
    request.signature = client_key.sign(&request.signing_bytes()).to_bytes();
    request
}

fn exchange(
    address: std::net::SocketAddr,
    request: &SignedArtifactOwnerRequestV1,
) -> Vec<u8> {
    let deadline = std::time::Instant::now() + Duration::from_secs(10);
    let mut stream = loop {
        match TcpStream::connect(address) {
            Ok(stream) => break stream,
            Err(_error) if std::time::Instant::now() < deadline => {
                thread::sleep(Duration::from_millis(10));
            }
            Err(error) => panic!("connect daemon: {error}"),
        }
    };
    stream.write_all(&request.encode()).expect("write request");
    stream.shutdown(Shutdown::Write).expect("finish request");
    let mut response = Vec::new();
    stream.read_to_end(&mut response).expect("read response");
    response
}

#[test]
fn real_daemon_bootstrap_backup_rotate_kill_restore_restart_and_durable_shutdown() {
    let root = TestRoot::new();
    let address = free_address();
    let (config, authz, backup_root, client_key) = prepare(&root, address);

    let mut first = spawn(&config);
    let health = exchange(
        address,
        &signed_request(ArtifactOwnerActionV1::Health, 1, 1, &client_key),
    );
    assert!(String::from_utf8_lossy(&health).contains("\"live\":true"));

    let backup = exchange(
        address,
        &signed_request(ArtifactOwnerActionV1::Backup, 2, 1, &client_key),
    );
    assert!(String::from_utf8_lossy(&backup).contains("hepta.learning-artifactd.backup.v1"));
    assert!(backup_root.join("request-2/BACKUP.complete").is_file());

    let authz_text = fs::read_to_string(&authz).expect("read authz");
    secure_write(&authz, authz_text.replacen("generation=1", "generation=2", 1).as_bytes());
    let rotated = exchange(
        address,
        &signed_request(ArtifactOwnerActionV1::ReloadAuthz, 3, 1, &client_key),
    );
    assert!(String::from_utf8_lossy(&rotated).contains("\"generation\":2"));

    first.kill().expect("kill first daemon");
    let status = first.wait().expect("reap first daemon");
    assert!(!status.success());

    let restored_root = root.0.join("restored-store");
    let receipt = restore_owner_root_v1(backup_root.join("request-2"), &restored_root)
        .expect("restore owner backup");
    assert_eq!(receipt.backup_id, id("request-2"));
    assert!(restored_root.join("host/RESTORE.complete").is_file());

    let restored_config = root.0.join("restored-owner.conf");
    let config_text = fs::read_to_string(&config).expect("read owner config");
    let original_root = root.0.join("store");
    secure_write(
        &restored_config,
        config_text
            .replacen(
                &format!("root={}\n", original_root.display()),
                &format!("root={}\n", restored_root.display()),
                1,
            )
            .as_bytes(),
    );

    let mut second = spawn(&restored_config);
    let health = exchange(
        address,
        &signed_request(ArtifactOwnerActionV1::Health, 4, 2, &client_key),
    );
    assert!(String::from_utf8_lossy(&health).contains("\"live\":true"));

    let metrics = exchange(
        address,
        &signed_request(ArtifactOwnerActionV1::Metrics, 5, 2, &client_key),
    );
    let metrics = String::from_utf8(metrics).expect("Prometheus text");
    assert!(metrics.contains("hepta_learning_artifact_requests_received_total"));
    assert!(!metrics.contains("hepta_learning_artifact_oldest_pending_attempt_age_seconds"));

    let shutdown = exchange(
        address,
        &signed_request(ArtifactOwnerActionV1::Shutdown, 6, 2, &client_key),
    );
    assert!(String::from_utf8_lossy(&shutdown).contains("\"accepted\":true"));
    assert!(second.wait().expect("graceful daemon exit").success());
    assert!(restored_root.join("writer/DRAIN.v1").is_file());
}
