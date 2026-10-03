use super::*;
use super::super::FinalUseBinding;
use super::super::ModelRelayPolicy;
use super::super::Observation;
use super::super::Peer;
use super::super::RootModelFailureV1;
use super::super::http;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;

const SUBJECT: &str = "original.fixture.agent";
const REQUEST: &str = "original.fixture.generator";

fn directory() -> anyhow::Result<tempfile::TempDir> {
    assert_eq!(rustix::process::geteuid().as_raw(), 0);
    Ok(tempfile::Builder::new()
        .prefix("hepta-original-model-reader-")
        .tempdir_in("/run")?)
}

// Actual original reserve/stream/publication filesystem path. Peer/model
// fields are explicit fixtures and make no provider or current Fleet claim.
fn reserved(directory: &Path, input: &str) -> anyhow::Result<Observation> {
    let binding = serde_json::to_string(&(
        "hepta.self-iteration.model-assessment.v1",
        REQUEST,
        "Generator",
        Digest32::of_bytes(b"original envelope").to_string(),
        Option::<String>::None,
        200_u64,
        1024_u32,
    ))?;
    let prompt = format!(
        "{} Your output grants no authority. Return at most 1024 UTF-8 bytes.\nBinding: {binding}\nInput:\n{input}",
        super::super::PURPOSE
    );
    let request = http::Request {
        body: serde_json::to_vec(&serde_json::json!({
            "model":"fixture.model", "stream":true, "store":false,
            "input":[{"role":"user","content":[{"type":"input_text","text":prompt}]}],
        }))?,
        headers: Default::default(),
        model: "fixture.model".into(),
    };
    let policy: ModelRelayPolicy = serde_json::from_value(serde_json::json!({
        "socket":"/run/unused-fixture.sock", "terminal_receipt_directory":directory,
        "credential_profile_home":"/never-open-fixture-credentials", "credential_uid":991,
        "credential_gid":991, "allowed_models":["fixture.model"], "max_concurrent_calls":1,
        "ingress_timeout_ms":1000, "credential_timeout_ms":1000, "call_timeout_ms":1000,
    }))?;
    let peer = Peer {
        pid: 17,
        start_ticks: 33,
        subject: SUBJECT.into(),
        cgroup: "/fixture/original-generation".into(),
        cgroup_device: 1,
        cgroup_inode: 2,
        executable_device: 3,
        executable_inode: 4,
        executable_sha256: Digest32::of_bytes(b"fixture-only-executable").to_string(),
    };
    let final_use = FinalUseBinding {
        subject_id: SUBJECT.into(),
        destination_id: "fixture-only-relay".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    };
    Observation::reserve(&policy, &request, &peer, &final_use, 100)?
        .ok_or_else(|| anyhow::anyhow!("original reserve did not recognize model binding"))
}

fn terminal(directory: &Path) -> anyhow::Result<std::path::PathBuf> {
    Ok(directory.join(format!(
        "{}.terminal.json",
        original_identity(SUBJECT, REQUEST)?
    )))
}

fn complete(original: &mut Observation) -> anyhow::Result<()> {
    let event = format!(
        "data: {}\n\n",
        serde_json::json!({
            "type":"response.completed", "response":{
                "id":"original.fixture.response","status":"completed","output":[
                    {"type":"message","role":"assistant","content":[
                        {"type":"output_text","text":"  中文\n🙂\t  "}
                    ]}
                ],
            },
        })
    );
    for fragment in event.as_bytes().chunks(1) {
        original.observe(fragment)?;
    }
    Ok(())
}

#[test]
fn workload_reader_cannot_treat_its_projection_as_root_model_custody() {
    if rustix::process::geteuid().as_raw() == 0 {
        return;
    }
    let error = RootModelOutcomeReceiptV1::read_original_protected(Path::new("/"), SUBJECT, REQUEST)
        .expect_err("workload must be refused before file reads");
    assert_eq!(
        error.to_string(),
        "original model facts require the actual Root reader"
    );
}

#[test]
#[ignore = "requires an actual Root process and isolated protected /run directory"]
fn actual_root_writer_reader_retains_full_escaped_prompt_and_original_failure() -> anyhow::Result<()> {
    let directory = directory()?;
    // A valid original 32KiB prompt can exceed a 16KiB JSON read bound by an
    // order of magnitude. The reader keeps its whole admission intact.
    let mut original = reserved(directory.path(), &"\0".repeat(31 * 1024))?;
    let intent = directory
        .path()
        .join(format!("{}.intent.json", original.identity));
    assert!(std::fs::metadata(&intent)?.len() > 128 * 1024);
    complete(&mut original)?;
    // Preserve a late completion as a provider observation, not current use.
    original.finish(201)?;
    let expected: RootModelOutcomeReceiptV1 = serde_json::from_slice(&store::read_protected(
        &terminal(directory.path())?, MAX_ORIGINAL_MODEL_FACT_BYTES, /*private*/ true,
    )?)?;
    assert_eq!(
        RootModelOutcomeReceiptV1::read_original_protected(directory.path(), SUBJECT, REQUEST)?,
        expected
    );
    let failed_directory = self::directory()?;
    let original = reserved(failed_directory.path(), "original real refusal input")?;
    let failure = RootModelFailureV1::HttpRejection { status: 503 };
    original.fail(failure.clone(), 150)?;
    let actual = RootModelOutcomeReceiptV1::read_original_protected(
        failed_directory.path(), SUBJECT, REQUEST,
    )?;
    let RootModelOutcomeReceiptV1::Failed { failure: observed, observed_at_ms, .. } = actual else {
        anyhow::bail!("original failure was converted to completion")
    };
    assert_eq!((observed, observed_at_ms), (failure, 150));
    Ok(())
}

#[test]
#[ignore = "requires an actual Root process and isolated protected /run directory"]
fn actual_root_reader_denies_whole_admission_tamper_and_unsettled_files() -> anyhow::Result<()> {
    let directory = directory()?;
    let mut original = reserved(directory.path(), "original")?;
    assert!(RootModelOutcomeReceiptV1::read_original_protected(directory.path(), SUBJECT, REQUEST).is_err());
    assert_eq!(std::fs::read_dir(directory.path())?.count(), 1);
    complete(&mut original)?;
    original.finish(150)?;
    let path = terminal(directory.path())?;
    let original_bytes = std::fs::read(&path)?;
    for field in ["native_prompt", "cgroup", "model", "executable_sha256"] {
        let mut changed: serde_json::Value = serde_json::from_slice(&original_bytes)?;
        changed["receipt"][field] = serde_json::json!("substituted");
        std::fs::write(&path, serde_json::to_vec(&changed)?)?;
        assert!(RootModelOutcomeReceiptV1::read_original_protected(directory.path(), SUBJECT, REQUEST).is_err(), "{field}");
    }
    std::fs::write(&path, b"{\"outcome\":\"completed\",\"receipt\":")?;
    assert!(RootModelOutcomeReceiptV1::read_original_protected(directory.path(), SUBJECT, REQUEST).is_err());
    std::fs::write(&path, vec![b' '; MAX_ORIGINAL_MODEL_FACT_BYTES + 1])?;
    assert!(RootModelOutcomeReceiptV1::read_original_protected(directory.path(), SUBJECT, REQUEST).is_err());
    assert_eq!(std::fs::read_dir(directory.path())?.count(), 2);
    Ok(())
}

#[test]
#[ignore = "requires an actual Root process and isolated protected /run directory"]
fn actual_root_reader_denies_other_links_modes_and_replaced_file_kinds() -> anyhow::Result<()> {
    let directory = directory()?;
    let mut original = reserved(directory.path(), "original")?;
    complete(&mut original)?;
    original.finish(150)?;
    let path = terminal(directory.path())?;
    let link = directory.path().join("fixture-alias");
    std::fs::hard_link(&path, &link)?;
    assert!(RootModelOutcomeReceiptV1::read_original_protected(directory.path(), SUBJECT, REQUEST).is_err());
    std::fs::remove_file(&link)?;
    for mode in [0o640, 0o400] {
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(mode))?;
        assert!(RootModelOutcomeReceiptV1::read_original_protected(directory.path(), SUBJECT, REQUEST).is_err());
    }
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    std::fs::rename(&path, &link)?;
    std::os::unix::fs::symlink(&link, &path)?;
    assert!(RootModelOutcomeReceiptV1::read_original_protected(directory.path(), SUBJECT, REQUEST).is_err());
    Ok(())
}
