//! Synthetic content and human scope; real original signatures, Registry,
//! issuer CAS/reopen, held FDs and peer-pinned sockets. No production enrollment.
use super::*;
use base64::Engine as _;
use pretty_assertions::assert_eq;

#[path = "deployment_paired_material_support_tests.rs"]
mod support;
use support::CORRECTION;
use support::FAILURE;
use support::PeerInput;
use support::TrainingFixture;

#[path = "deployment_paired_admission_tests.rs"]
mod admission;

fn frame(raw: &[u8]) -> serde_json::Value {
    assert!(raw.len() >= 4);
    let count = u32::from_be_bytes(raw[..4].try_into().unwrap()) as usize;
    assert_eq!(raw.len(), count + 4);
    serde_json::from_slice(&raw[4..]).unwrap()
}

#[test]
fn paired_material_original_fds_read_once_and_reopen_is_retained() {
    let f = TrainingFixture::new();
    let raw = f.request_bytes();
    let before = f.original.issuer.store.load(STATE_OWNER).unwrap();
    let failure = File::open(f.original.directory.path().join("failure")).unwrap();
    let correction = File::open(f.original.directory.path().join("correction")).unwrap();
    let original = f.original.directory.path().join("failure-original");
    std::fs::rename(f.original.directory.path().join("failure"), &original).unwrap();
    // Rename can change ctime: capture the already held original descriptor
    // after the rename, then replace only its old pathname with another inode.
    let owner = f.owner_with_files(failure, correction);
    let mut replacement = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(f.original.directory.path().join("failure"))
        .unwrap();
    replacement.write_all(&vec![b'x'; FAILURE.len()]).unwrap();
    replacement.sync_all().unwrap();
    drop(replacement);
    let (result, bytes) = f.exchange(&owner, &raw, PeerInput::Open);
    assert_eq!(result, Ok(true));
    assert_eq!(
        frame(&bytes),
        serde_json::json!({
            "outcome":"fresh_read", "original_delivery":f.original.registration.request.original.delivery_id.to_string(),
            "materials_sha256":f.manifest.commitment().unwrap().to_string(),
            "failure_base64":base64::engine::general_purpose::STANDARD.encode(FAILURE),
            "correction_base64":base64::engine::general_purpose::STANDARD.encode(CORRECTION),
        })
    );
    let after = f.original.issuer.store.load(STATE_OWNER).unwrap();
    assert_eq!(after.sequence, before.sequence + 2);
    assert!(after.head == before.head && after.text_signatures == before.text_signatures);
    assert_eq!(after.paired_material_entries_v1.len(), 1);
    // Changing the held inode now would reject any attempted second read.
    std::fs::write(&original, vec![b'y'; FAILURE.len()]).unwrap();
    let expected = serde_json::json!({"outcome":"retained_read_only", "original_delivery":f.original.registration.request.original.delivery_id.to_string()});
    let (result, bytes) = f.exchange(&owner, &raw, PeerInput::Open);
    assert_eq!(result, Ok(true));
    assert_eq!(frame(&bytes), expected);
    assert!(f.original.issuer.store.load(STATE_OWNER).unwrap() == after);
    drop(owner);
    let f = f.reopen();
    let owner = f.owner();
    let (result, bytes) = f.exchange(&owner, &raw, PeerInput::Open);
    assert_eq!(result, Ok(true));
    assert_eq!(frame(&bytes), expected);
    assert!(f.original.issuer.store.load(STATE_OWNER).unwrap() == after);
}

#[test]
fn paired_material_bad_content_consumes_entry_without_response_or_replay() {
    let f = TrainingFixture::new();
    std::fs::write(
        f.original.directory.path().join("correction"),
        vec![b'z'; CORRECTION.len()],
    )
    .unwrap();
    let owner = f.owner();
    let before = f.original.issuer.store.load(STATE_OWNER).unwrap();
    let raw = f.request_bytes();
    let (result, bytes) = f.exchange(&owner, &raw, PeerInput::Open);
    assert_eq!(
        result,
        Err(codex_hepta_contracts::HostIssuerTransportError::Unavailable)
    );
    assert!(bytes.is_empty());
    let after = f.original.issuer.store.load(STATE_OWNER).unwrap();
    assert_eq!(after.sequence, before.sequence + 1);
    let value = serde_json::to_value(&after).unwrap();
    assert_eq!(
        value["paired_material_entries_v1"][f
            .original
            .registration
            .request
            .original
            .delivery_id
            .to_string()]["state"]["state"],
        "entered"
    );
    drop(owner);
    std::fs::write(f.original.directory.path().join("correction"), CORRECTION).unwrap();
    let f = f.reopen();
    let owner = f.owner();
    let (result, bytes) = f.exchange(&owner, &raw, PeerInput::Open);
    assert_eq!(result, Ok(true));
    assert_eq!(
        frame(&bytes),
        serde_json::json!({"outcome":"retained_read_only", "original_delivery":f.original.registration.request.original.delivery_id.to_string()})
    );
    assert!(f.original.issuer.store.load(STATE_OWNER).unwrap() == after);
}

#[test]
fn paired_material_wrong_binding_or_closed_peer_cannot_enter() {
    let f = TrainingFixture::new();
    let owner = f.owner();
    let before = f.original.issuer.store.load(STATE_OWNER).unwrap();
    let frontier = f.original.registry.frontier().unwrap();
    let raw = f.request_bytes();
    let mut changed: serde_json::Value = serde_json::from_slice(&raw).unwrap();
    changed["binding"]["destination_id"] = serde_json::json!("notes.alias.forbidden");
    for (raw, input) in [
        (serde_json::to_vec(&changed).unwrap(), PeerInput::Open),
        (raw, PeerInput::Closed),
    ] {
        let (result, bytes) = f.exchange(&owner, &raw, input);
        assert_eq!(
            result,
            Err(codex_hepta_contracts::HostIssuerTransportError::Unavailable)
        );
        assert!(bytes.is_empty());
        assert!(f.original.issuer.store.load(STATE_OWNER).unwrap() == before);
        assert_eq!(f.original.registry.frontier().unwrap(), frontier);
    }
}

#[test]
fn paired_material_original_registry_lock_covers_the_blocked_response() {
    let f = TrainingFixture::new();
    let owner = f.owner();
    let raw = f.request_bytes();
    let (mut server, mut client, buffered) = f.blocked_channel(&raw);
    let (started_tx, started_rx) = std::sync::mpsc::sync_channel(1);
    let (done_tx, done_rx) = std::sync::mpsc::sync_channel(1);
    std::thread::scope(|scope| {
        let serving = scope.spawn(|| f.serve(&owner, &mut server));
        f.wait_for_read_commit();
        let revoking = scope.spawn(|| {
            started_tx.send(()).unwrap();
            let result = f.original.registry.revoke(
                &f.original.registration.effect_id(),
                /*expected_revision*/ 2,
                [8; 32],
            );
            done_tx.send(result).unwrap();
        });
        started_rx.recv_timeout(Duration::from_millis(100)).unwrap();
        assert!(matches!(
            done_rx.recv_timeout(Duration::from_millis(50)),
            Err(std::sync::mpsc::RecvTimeoutError::Timeout)
        ));
        let mut filler = vec![0; buffered];
        client.read_exact(&mut filler).unwrap();
        assert_eq!(filler, vec![0x5a; buffered]);
        let mut size = [0; 4];
        client.read_exact(&mut size).unwrap();
        let mut bytes = vec![0; u32::from_be_bytes(size) as usize];
        client.read_exact(&mut bytes).unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&bytes).unwrap()["outcome"],
            "fresh_read"
        );
        assert_eq!(serving.join().unwrap(), Ok(true));
        done_rx
            .recv_timeout(Duration::from_millis(500))
            .unwrap()
            .unwrap();
        revoking.join().unwrap();
    });
}

#[test]
fn paired_material_expiry_during_blocked_send_cannot_release_a_prefix() {
    let f = TrainingFixture::new();
    let owner = f.owner();
    let raw = f.request_bytes();
    let (mut server, mut client, buffered) = f.blocked_channel(&raw);
    std::thread::scope(|scope| {
        let serving = scope.spawn(|| f.serve(&owner, &mut server));
        f.wait_for_read_commit();
        f.original
            .clock
            .0
            .store(f.ingress.expires_at_ms, Ordering::SeqCst);
        let mut filler = vec![0; buffered];
        client.read_exact(&mut filler).unwrap();
        assert_eq!(filler, vec![0x5a; buffered]);
        assert_eq!(
            serving.join().unwrap(),
            Err(codex_hepta_contracts::HostIssuerTransportError::Unavailable)
        );
        let mut response = Vec::new();
        client.read_to_end(&mut response).unwrap();
        assert!(response.is_empty());
    });
    let state = f.original.issuer.store.load(STATE_OWNER).unwrap();
    assert_eq!(state.paired_material_entries_v1.len(), 1);
    assert_eq!(
        serde_json::to_value(&state).unwrap()["paired_material_entries_v1"][f
            .original
            .registration
            .request
            .original
            .delivery_id
            .to_string()]["state"]["state"],
        "read_committed"
    );
}

#[test]
fn paired_material_entry_conflict_and_unknown_version_never_reopen_fresh() {
    let f = TrainingFixture::new();
    let owner = f.owner();
    let state = f.original.issuer.store.load(STATE_OWNER).unwrap();
    let semantic = Digest32::of_bytes(b"synthetic component entry");
    let PreparedMaterialEntry::Fresh { retained_state } = owner
        .retain_material_entry(&state, semantic, 10_000)
        .unwrap()
    else {
        panic!("original empty record must enter once");
    };
    // A stale physical CAS cannot overwrite the first successful entry, even
    // when its caller presents different semantics for the same delivery.
    assert!(
        owner
            .retain_material_entry(&state, Digest32::of_bytes(b"changed"), 10_000)
            .is_err()
    );
    assert!(
        owner
            .retain_material_entry(&retained_state, Digest32::of_bytes(b"changed"), 10_000)
            .is_err()
    );
    assert!(matches!(
        owner
            .retain_material_entry(&retained_state, semantic, 10_000)
            .unwrap(),
        PreparedMaterialEntry::Retained(_)
    ));
    assert!(f.original.issuer.store.load(STATE_OWNER).unwrap() == retained_state);
    let mut corrupt = serde_json::to_value(&retained_state).unwrap();
    corrupt["paired_material_entries_v1"][f
        .original
        .registration
        .request
        .original
        .delivery_id
        .to_string()]["schema_version"] = serde_json::json!(2);
    let corrupt: IssuerState = serde_json::from_value(corrupt).unwrap();
    f.original
        .issuer
        .store
        .compare_and_set(STATE_OWNER, &retained_state, &corrupt)
        .unwrap();
    drop(owner);
    let f = f.reopen();
    let owner = f.owner();
    assert!(
        owner
            .retain_material_entry(&corrupt, semantic, 10_000)
            .is_err()
    );
    let (result, bytes) = f.exchange(&owner, &f.request_bytes(), PeerInput::Open);
    assert_eq!(
        result,
        Err(codex_hepta_contracts::HostIssuerTransportError::Unavailable)
    );
    assert!(bytes.is_empty());
    assert!(f.original.issuer.store.load(STATE_OWNER).unwrap() == corrupt);
}

#[test]
fn paired_material_nonempty_version_is_not_decodable_by_the_old_strict_shape() {
    // These are the exact pre-entry field names. The production old decoder
    // already denies unknown fields; this control checks the serialized fence,
    // not a claim that an old executable was run or that Root disk can roll back.
    #[derive(Deserialize, Serialize)]
    #[serde(deny_unknown_fields)]
    struct PreEntryState {
        signer_id: String,
        policies: Vec<DeploymentGrantPolicy>,
        head: FinalUseRevocations,
        sequence: u64,
        writer_authorization: Option<crate::HostSignedWriterAuthorizationV1>,
        text_signatures: Vec<serde_json::Value>,
        text_intent_sequence: u64,
    }
    let f = TrainingFixture::new();
    let owner = f.owner();
    let before = f.original.issuer.store.load(STATE_OWNER).unwrap();
    let before_raw = serde_json::to_value(&before).unwrap();
    assert!(before_raw.get("paired_material_entries_v1").is_none());
    let old: PreEntryState = serde_json::from_value(before_raw.clone()).unwrap();
    assert_eq!(serde_json::to_value(old).unwrap(), before_raw);
    owner
        .retain_material_entry(&before, Digest32::of_bytes(b"synthetic entry"), 10_000)
        .unwrap();
    let after = serde_json::to_value(f.original.issuer.store.load(STATE_OWNER).unwrap()).unwrap();
    let error = serde_json::from_value::<PreEntryState>(after.clone())
        .err()
        .unwrap();
    assert!(
        error
            .to_string()
            .contains("unknown field `paired_material_entries_v1`")
    );
    assert_eq!(
        after["paired_material_entries_v1"]
            .as_object()
            .unwrap()
            .len(),
        1
    );
    drop(owner);
    let f = f.reopen();
    assert_eq!(
        serde_json::to_value(f.original.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        after
    );
}

#[test]
fn paired_material_every_pread_refusal_precedes_actual_content_access() {
    // FD component only: no fabricated human/journal authority is consumed.
    // Linux IN_ACCESS observes actual kernel reads of the two original files.
    let f = TrainingFixture::new();
    let failure = vec![b'f'; 5000];
    std::fs::write(f.original.directory.path().join("failure"), &failure).unwrap();
    let manifest = PairedTrainingMaterialManifestV1 {
        failure_sha256: Digest32::of_bytes(&failure),
        failure_bytes: failure.len() as u64,
        correction_sha256: Digest32::of_bytes(CORRECTION),
        correction_bytes: CORRECTION.len() as u64,
    };
    let mut registration = f.original.registration.clone();
    registration.preparation.frozen_materials = manifest.commitment().unwrap();
    registration.request.materials = manifest.commitment().unwrap();
    registration.request.original.usage =
        crate::PairedLearningDataUse::TrainOnFailureAndCorrection {
            failure: manifest.failure_sha256,
            correction: manifest.correction_sha256,
        };
    let material = FixedTrainingMaterials::capture(
        &registration,
        manifest,
        File::open(f.original.directory.path().join("failure")).unwrap(),
        File::open(f.original.directory.path().join("correction")).unwrap(),
        unsafe { libc::geteuid() },
    )
    .unwrap();
    // First read, second chunk, and first correction read respectively.
    for reject_at in [1, 2, 4] {
        let mut watch = support::ReadWatch::new(f.original.directory.path());
        let mut checks = 0;
        let error = material
            .read_after_entry(Instant::now() + Duration::from_secs(1), &mut || {
                checks += 1;
                if checks == reject_at {
                    Err(io::Error::other("original synthetic fence refused"))
                } else {
                    Ok(())
                }
            })
            .err()
            .unwrap();
        assert_eq!(error.to_string(), "original synthetic fence refused");
        assert_eq!(checks, reject_at);
        assert_eq!(watch.content_accesses(), (reject_at != 1, false));
    }
}
