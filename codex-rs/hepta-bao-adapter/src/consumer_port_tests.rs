use std::error::Error;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::consumer_transport::PreparedConnection;
use super::consumer_wire::ConsumerRequest;
use super::consumer_wire::ConsumerResponse;
use super::*;

type TestResult = Result<(), Box<dyn Error>>;

pub(crate) struct Fixture {
    directory: TempDir,
    pub(crate) config: CredentialConsumerServiceConfig,
    pub(crate) port: ConsumerPortConfig,
    pub(crate) credential: Vec<u8>,
}

impl Fixture {
    pub(crate) fn new() -> Result<Self, Box<dyn Error>> {
        let directory = tempfile::tempdir()?;
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
        let socket_home = directory.path().join("ipc");
        std::fs::create_dir(&socket_home)?;
        std::fs::set_permissions(&socket_home, std::fs::Permissions::from_mode(0o750))?;
        let credential = b"independent-credential-authentication-test".to_vec();
        let credential_file = directory.path().join("credential");
        private_file(&credential_file, &credential)?;
        let signing_key_file = directory.path().join("ack-key");
        let key = SigningKey::from_bytes(&[83; 32]);
        private_file(&signing_key_file, &key.to_bytes())?;
        let config = CredentialConsumerServiceConfig {
            schema_version: 1,
            consumer_id: "native-credential-consumer".into(),
            socket_path: socket_home.join("consumer.sock"),
            ipc_group_gid: rustix::process::getegid().as_raw(),
            allowed_caller_uid: rustix::process::geteuid().as_raw(),
            database_path: directory.path().join("owner").join("consumer.sqlite"),
            credential_file,
            credential_sha256: Digest32::of_bytes(&credential).into_array(),
            acknowledgement_signing_key_file: signing_key_file,
            acknowledgement_verifying_key: key.verifying_key().to_bytes(),
            request_timeout_ms: 500,
            shutdown_drain_ms: 1_000,
        };
        let port = ConsumerPortConfig {
            consumer_id: config.consumer_id.clone(),
            socket_path: config.socket_path.clone(),
            service_uid: rustix::process::geteuid().as_raw(),
            acknowledgement_verifying_key: config.acknowledgement_verifying_key,
            credential_reference_sha256: config.credential_sha256,
            timeout_ms: 2_000,
        };
        Ok(Self {
            directory,
            config,
            port,
            credential,
        })
    }

    pub(crate) fn spawn(&self) -> Result<ConsumerProcess, Box<dyn Error>> {
        let configuration = self.directory.path().join("process-config.json");
        std::fs::write(&configuration, serde_json::to_vec(&self.config)?)?;
        let child = Command::new(std::env::current_exe()?)
            .args([
                "--exact",
                "consumer_port::tests::consumer_process_entry",
                "--ignored",
                "--nocapture",
            ])
            .env("HEPTA_NATIVE_CONSUMER_CONFIGURATION", &configuration)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()?;
        let mut process = ConsumerProcess(child);
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            if process.0.try_wait()?.is_some() {
                return Err("consumer process exited before readiness".into());
            }
            if PreparedConnection::connect(
                &self.port.socket_path,
                self.port.service_uid,
                Duration::from_millis(20),
            )
            .is_ok()
            {
                return Ok(process);
            }
            if Instant::now() >= deadline {
                return Err("consumer process readiness expired".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
    }

    pub(crate) fn client(&self) -> Result<Arc<ConsumerPortClient>, ConsumerPortError> {
        ConsumerPortClient::new(self.port.clone()).map(Arc::new)
    }

    fn authenticate(
        &self,
        client: &ConsumerPortClient,
        operation: &str,
        semantic: [u8; 32],
    ) -> Result<(), ()> {
        let _budget = client
            .begin_original_operation(operation, Instant::now() + Duration::from_secs(2))
            .map_err(|_| ())?;
        client.prepare(operation, semantic).map_err(|_| ())?(&self.credential)
    }
}

fn private_file(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

pub(crate) struct ConsumerProcess(Child);
impl ConsumerProcess {
    pub(crate) fn terminate(&mut self) -> Result<std::process::ExitStatus, Box<dyn Error>> {
        let pid = rustix::process::Pid::from_raw(self.0.id() as i32).ok_or("invalid child PID")?;
        rustix::process::kill_process(pid, rustix::process::Signal::TERM)?;
        let deadline = Instant::now() + Duration::from_secs(4);
        loop {
            if let Some(status) = self.0.try_wait()? {
                return Ok(status);
            }
            if Instant::now() >= deadline {
                return Err("consumer physical shutdown deadline expired".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
    }
}
impl Drop for ConsumerProcess {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
#[ignore = "invoked as the independent consumer child by its native parent"]
fn consumer_process_entry() -> TestResult {
    let configuration = std::env::var_os("HEPTA_NATIVE_CONSUMER_CONFIGURATION")
        .ok_or("missing explicit native consumer configuration")?;
    let config = serde_json::from_slice(&std::fs::read(configuration)?)?;
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?
        .block_on(async {
            let mut terminate =
                tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
            serve_credential_consumer(config, async move {
                terminate.recv().await;
            })
            .await?;
            Ok(())
        })
}

#[test]
fn independent_consumer_authenticates_and_retains_original_signed_ack_after_restart() -> TestResult
{
    let fixture = Fixture::new()?;
    let mut process = fixture.spawn()?;
    let client = fixture.client()?;
    assert!(!client.observe("native-original", [7; 32])?);
    assert!(
        fixture
            .authenticate(&client, "native-original", [7; 32])
            .is_ok()
    );
    assert!(client.observe("native-original", [7; 32])?);
    let intent = client.intent("native-original", [7; 32])?;
    let status = || -> Result<Vec<u8>, Box<dyn Error>> {
        let response: ConsumerResponse = PreparedConnection::connect(
            &fixture.port.socket_path,
            fixture.port.service_uid,
            Duration::from_secs(2),
        )?
        .exchange(&ConsumerRequest::Status {
            intent: intent.clone(),
        })?;
        Ok(serde_json::to_vec(&response)?)
    };
    let original = status()?;
    assert!(process.terminate()?.success());
    assert!(!fixture.port.socket_path.exists());
    let mut process = fixture.spawn()?;
    assert_eq!(status()?, original);
    assert!(
        fixture
            .authenticate(&client, "native-original", [7; 32])
            .is_ok()
    );
    assert_eq!(status()?, original);
    assert_eq!(
        client.observe("native-original", [9; 32]),
        Err(ConsumerPortError::Conflict)
    );
    assert!(process.terminate()?.success());
    Ok(())
}

#[test]
fn wrong_actual_credential_and_wrong_ack_pin_cannot_confirm_delivery() -> TestResult {
    let fixture = Fixture::new()?;
    let mut process = fixture.spawn()?;
    let client = fixture.client()?;
    let intent = client.intent("wrong-authentication", [2; 32])?;
    let response = PreparedConnection::connect(
        &fixture.port.socket_path,
        fixture.port.service_uid,
        Duration::from_secs(2),
    )?
    .exchange(&ConsumerRequest::Authenticate {
        proof: intent.proof(b"wrong-actual-credential")?,
        intent,
    })?;
    assert!(matches!(response, ConsumerResponse::Rejected));
    assert!(!client.observe("wrong-authentication", [2; 32])?);
    let mut wrong_pin = fixture.port.clone();
    wrong_pin.acknowledgement_verifying_key =
        SigningKey::from_bytes(&[84; 32]).verifying_key().to_bytes();
    let wrong_pin = ConsumerPortClient::new(wrong_pin)?;
    assert!(
        fixture
            .authenticate(&wrong_pin, "real-auth-wrong-ack-pin", [3; 32])
            .is_err()
    );
    assert!(client.observe("real-auth-wrong-ack-pin", [3; 32])?);
    assert_eq!(
        wrong_pin.observe("real-auth-wrong-ack-pin", [3; 32]),
        Err(ConsumerPortError::Unavailable)
    );
    assert!(process.terminate()?.success());
    Ok(())
}

#[test]
fn kernel_peer_and_expired_original_budget_reject_before_first_effect() -> TestResult {
    let fixture = Fixture::new()?;
    let mut process = fixture.spawn()?;
    let client = fixture.client()?;
    let mut wrong_uid = fixture.port.clone();
    wrong_uid.service_uid = wrong_uid.service_uid.checked_add(1).ok_or("UID overflow")?;
    let wrong_uid = ConsumerPortClient::new(wrong_uid)?;
    assert!(
        fixture
            .authenticate(&wrong_uid, "wrong-peer", [4; 32])
            .is_err()
    );
    assert!(!client.observe("wrong-peer", [4; 32])?);
    let _budget = client
        .begin_original_operation("expired-budget", Instant::now() + Duration::from_millis(20))?;
    let callback = client.prepare("expired-budget", [5; 32])?;
    std::thread::sleep(Duration::from_millis(25));
    assert!(callback(&fixture.credential).is_err());
    assert!(!client.observe("expired-budget", [5; 32])?);
    assert!(process.terminate()?.success());
    Ok(())
}

#[test]
fn timed_out_partial_request_fences_new_effects_but_keeps_original_status() -> TestResult {
    let fixture = Fixture::new()?;
    let mut process = fixture.spawn()?;
    let client = fixture.client()?;
    assert!(
        fixture
            .authenticate(&client, "before-timeout", [6; 32])
            .is_ok()
    );
    let mut stalled = std::os::unix::net::UnixStream::connect(&fixture.port.socket_path)?;
    stalled.write_all(&100_u32.to_be_bytes())?;
    std::thread::sleep(Duration::from_millis(
        fixture.config.request_timeout_ms + 100,
    ));
    assert!(client.observe("before-timeout", [6; 32])?);
    assert!(
        fixture
            .authenticate(&client, "after-timeout", [8; 32])
            .is_err()
    );
    assert!(!client.observe("after-timeout", [8; 32])?);
    assert!(process.terminate()?.success());
    Ok(())
}

#[test]
fn graceful_shutdown_stops_admission_and_physically_joins_partial_request() -> TestResult {
    let fixture = Fixture::new()?;
    let mut process = fixture.spawn()?;
    let mut stalled = std::os::unix::net::UnixStream::connect(&fixture.port.socket_path)?;
    stalled.write_all(&100_u32.to_be_bytes())?;
    let start = Instant::now();
    assert!(process.terminate()?.success());
    assert!(start.elapsed() < Duration::from_secs(3));
    assert!(!fixture.port.socket_path.exists());
    assert!(std::os::unix::net::UnixStream::connect(&fixture.port.socket_path).is_err());
    Ok(())
}
