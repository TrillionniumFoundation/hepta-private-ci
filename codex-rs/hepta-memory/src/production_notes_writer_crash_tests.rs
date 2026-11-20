//! Process crash coverage for the real original SQLite writer. Test authority
//! and initial cut are fixtures; no replacement journal or issuer is created.
use super::*;
use pretty_assertions::assert_eq;
use std::io::Write;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

struct OwnedChild(std::process::Child);
impl std::ops::Deref for OwnedChild {
    type Target = std::process::Child;
    fn deref(&self) -> &Self::Target {
        &self.0
    }
}
impl std::ops::DerefMut for OwnedChild {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}
impl Drop for OwnedChild {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

const CHILD_TEST: &str =
    "production_writer::notes_owner::tests::process_crash_tests::notes_writer_process_worker";

#[tokio::test]
#[ignore = "internal explicit subprocess worker; run only through its parent test"]
async fn notes_writer_process_worker() -> TestResult {
    let role = std::env::var("HEPTA_NOTES_WRITER_CRASH_ROLE")?;
    let path = std::path::PathBuf::from(
        std::env::var_os("HEPTA_NOTES_WRITER_CRASH_ROOT").ok_or("fixture root missing")?,
    );
    let fleet = HeptaFleetRoot::parse(path.join("fleet").canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d25")?;
    let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        source(&owner, 1)?,
        Arc::new(Verifier),
        LEASE,
        /*generation*/ 1,
    )
    .await?;
    let (payload, identity, _) = fixture()?;
    let operation = match role.as_str() {
        "prepare" => prepare(&writer, payload.clone(), &identity).await?,
        "observe" => serde_json::from_str::<serde_json::Value>(&payload)?["operation_id"]
            .as_str()
            .ok_or("operation id missing")?
            .to_string(),
        _ => return Err("unknown fixture role".into()),
    };
    assert_eq!(
        writer.status(&operation).await?,
        LocalOutcomeState::Indeterminate
    );
    let stored: (String, String) = sqlx::query_as("SELECT payload_json, payload_sha256 FROM cognitive_local_outbox WHERE lease_id = ? AND occurrence_key = ?")
        .bind(LEASE).bind(&operation).fetch_one(&store.pool).await?;
    assert_eq!(
        stored,
        (
            payload.clone(),
            Sha256Digest::for_bytes(payload.as_bytes())
                .as_str()
                .to_string()
        )
    );
    let count: i64 =
        sqlx::query_scalar("SELECT count(*) FROM cognitive_local_outbox WHERE lease_id = ?")
            .bind(LEASE)
            .fetch_one(&store.pool)
            .await?;
    assert_eq!(count, 1);
    let proof = serde_json::json!({"role":role,"state":"indeterminate","outbox_rows":count,
        "payload_sha256":Sha256Digest::for_bytes(payload.as_bytes()).as_str(),"production_authority":false});
    let mut file = std::fs::File::create(path.join(format!("{role}.json")))?;
    file.write_all(&serde_json::to_vec(&proof)?)?;
    file.sync_all()?;
    if role == "prepare" {
        // Keep both real owners alive until the parent kills this exact child.
        loop {
            std::thread::sleep(Duration::from_secs(1));
        }
    }
    writer.close().await?;
    store.close().await;
    Ok(())
}

#[test]
fn notes_writer_sigkill_other_process_reopens_original_outbox_without_dispatch() -> TestResult {
    let directory = tempfile::tempdir()?;
    std::fs::create_dir(directory.path().join("fleet"))?;
    let spawn = |role: &str| -> TestResult<OwnedChild> {
        let log = std::fs::File::create(directory.path().join(format!("{role}.log")))?;
        Ok(OwnedChild(
            Command::new(std::env::current_exe()?)
                .args(["--exact", CHILD_TEST, "--ignored", "--nocapture"])
                .env("HEPTA_NOTES_WRITER_CRASH_ROLE", role)
                .env("HEPTA_NOTES_WRITER_CRASH_ROOT", directory.path())
                .stdout(Stdio::from(log.try_clone()?))
                .stderr(Stdio::from(log))
                .spawn()?,
        ))
    };
    let mut first = spawn("prepare")?;
    let deadline = Instant::now() + Duration::from_secs(40);
    let before = loop {
        if let Ok(raw) = std::fs::read(directory.path().join("prepare.json"))
            && let Ok(proof) = serde_json::from_slice::<serde_json::Value>(&raw)
        {
            break proof;
        }
        if let Some(status) = first.try_wait()? {
            return Err(format!("writer child exited before durable admission: {status}").into());
        }
        if Instant::now() > deadline {
            first.kill()?;
            first.wait()?;
            return Err("writer child durable admission timeout".into());
        }
        std::thread::sleep(Duration::from_millis(20));
    };
    // Child::kill targets only the retained test-owned child and is SIGKILL on
    // Unix. The original pool/writer never receive a clean close call here.
    first.kill()?;
    assert!(!first.wait()?.success());
    let mut second = spawn("observe")?;
    let deadline = Instant::now() + Duration::from_secs(40);
    loop {
        if let Some(status) = second.try_wait()? {
            if !status.success() {
                return Err(format!(
                    "recovery child failed: {}",
                    std::fs::read_to_string(directory.path().join("observe.log"))?
                )
                .into());
            }
            break;
        }
        if Instant::now() > deadline {
            second.kill()?;
            second.wait()?;
            return Err("writer recovery child timeout".into());
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    let after: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.path().join("observe.json"))?)?;
    assert_eq!(
        (
            &before["state"],
            &before["payload_sha256"],
            &before["outbox_rows"]
        ),
        (
            &after["state"],
            &after["payload_sha256"],
            &after["outbox_rows"]
        )
    );
    Ok(())
}
