//! Public Root loader and real staged Session boundary, with explicit fixture
//! authority. Publisher processes remain sleep children; no Agentd, Activate,
//! application effect, five-lane consumer or production deployment is qualified.
use super::*;
use crate::PreparedHostNotesRecovery;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::net::UnixDatagram;
use std::path::PathBuf;

#[path = "root_notes_recovery_session_process_tests.rs"]
mod process;
use process::ActualSession;

fn output() -> PathBuf {
    let path = PathBuf::from(std::env::var_os("HEPTA_NOTES_SESSION_OUTPUT").unwrap());
    assert_eq!(path.canonicalize().unwrap(), path);
    path
}

fn write_json(path: &Path, value: &impl serde::Serialize) {
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)
        .unwrap();
    file.write_all(&serde_json::to_vec(value).unwrap()).unwrap();
    file.sync_all().unwrap();
}

struct PublicFixture {
    _root: tempfile::TempDir,
    _old: Publisher,
    _publisher: Publisher,
    owner_pidfd: OwnedFd,
    config: HostAuthorityServiceConfig,
    registration: HostAuthorityRegistration,
    previous: Option<HostNotesRecoveryPredecessor>,
    config_path: PathBuf,
    registration_path: PathBuf,
    profile_path: PathBuf,
    bindings: serde_json::Value,
    consumers: tempfile::TempDir,
}

impl PublicFixture {
    async fn new() -> Self {
        let mountpoint = PathBuf::from(std::env::var_os("HEPTA_NOTES_RECOVERY_BIND").unwrap());
        let source = PathBuf::from(std::env::var_os("HEPTA_NOTES_RECOVERY_BIND_SOURCE").unwrap());
        let metadata = std::fs::metadata(&source).unwrap();
        let bind = HostAuthorityBindIdentity {
            mountpoint,
            source_path: source,
            device: metadata.dev(),
            inode: metadata.ino(),
        };
        let OriginalFixture {
            _root,
            _old,
            _new,
            config,
            registration,
            clock,
            registry,
            issuer,
            old_writer,
            old_proof,
            previous,
            old_target,
            new_target: _,
            lease_owner: _,
        } = OriginalFixture::with_layout(FixtureLayout::OriginalHostBind(bind)).await;
        let owner_pidfd = process::pidfd(&_new.child);
        let config_path = _root.path().join("existing-config.json");
        let registration_path = _root.path().join("existing-registration.json");
        let profile_path = _root.path().join("fixture-notes-profile.json");
        write_json(&config_path, &config);
        write_json(&registration_path, &registration);
        let fixture_digest =
            Sha256Digest::for_bytes(b"explicit nonproduction Notes loader fixture");
        let bindings = serde_json::json!({
            "principal_scope":"explicit-notes-root-session-fixture",
            "principal_scope_digest":fixture_digest.as_str(),
            "issuer_id":config.signer_id,"policy_generation":1,"locale":"en-US",
            "runtime_body_digest":fixture_digest.as_str(),
            "preference_state_digest":fixture_digest.as_str(),
            "model_tuple_digest":fixture_digest.as_str(),
            "prompt_registry_digest":fixture_digest.as_str(),
            "artifact_set_digest":fixture_digest.as_str()
        });
        write_json(
            &profile_path,
            &serde_json::json!({
                "schema":"hepta.root.notes_launch_profile.v1","grant_lifetime_ms":1000,
                "bindings":bindings
            }),
        );
        let consumers =
            tempfile::tempdir_in(std::env::var_os("HEPTA_NOTES_SESSION_RUNTIME_ROOT").unwrap())
                .unwrap();
        let local = File::open(consumers.path()).unwrap();
        // SAFETY: this changes only the newly created, empty test journal parent.
        assert_eq!(unsafe { libc::fchown(local.as_raw_fd(), 60001, 60001) }, 0);
        std::fs::set_permissions(consumers.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        // Only the original public opener owns the reopened runtime handles.
        // Setup factories are gone; no lookalike Registry/service is injected.
        drop((issuer, registry, clock));
        Self {
            _root,
            _old,
            _publisher: _new,
            owner_pidfd,
            config,
            registration,
            previous: Some(HostNotesRecoveryPredecessor {
                writer: old_writer,
                writer_proof: old_proof,
                checkpoint: previous,
                notes_target: old_target,
                notes_lifetime_ms: 1_000,
            }),
            config_path,
            registration_path,
            profile_path,
            bindings,
            consumers,
        }
    }

    fn open(&mut self) -> PreparedHostNotesRecovery {
        PreparedHostNotesRecovery::open(
            &self.config_path,
            &self.registration_path,
            self.owner_pidfd.try_clone().unwrap(),
            self.previous.take().unwrap(),
        )
        .unwrap()
    }
}

fn deployment() -> (File, File) {
    // SAFETY: the static name is NUL-terminated and the call returns a new FD.
    let raw = unsafe {
        libc::memfd_create(
            c"hepta-notes-recovery-fixture".as_ptr(),
            libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING,
        )
    };
    assert!(raw >= 0);
    // SAFETY: successful memfd_create returned exactly this fresh descriptor.
    let producer = unsafe { File::from_raw_fd(raw) };
    assert_eq!(unsafe { libc::fchmod(raw, 0o600) }, 0);
    let reader = File::open(format!("/proc/self/fd/{raw}")).unwrap();
    // SAFETY: fcntl only reads flags of the retained independent description.
    assert_eq!(
        unsafe { libc::fcntl(reader.as_raw_fd(), libc::F_GETFL) } & libc::O_ACCMODE,
        libc::O_RDONLY
    );
    (producer, reader)
}

fn read_sealed(file: &mut File) -> serde_json::Value {
    let size = file.metadata().unwrap().len();
    assert!(size > 0 && size <= crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64);
    crate::authority_host_bootstrap_seal::validate_sealed(file, size).unwrap();
    file.rewind().unwrap();
    let mut bytes = Vec::new();
    Read::by_ref(file)
        .take(size + 1)
        .read_to_end(&mut bytes)
        .unwrap();
    assert_eq!(bytes.len() as u64, size);
    serde_json::from_slice(&bytes).unwrap()
}

#[tokio::test]
#[ignore = "explicit private Root bind and pinned real staged Session/App/Xvfb fixture"]
async fn root_notes_recovery_public_loader_actual_session_seals_exact_reservation() {
    let mut f = PublicFixture::new().await;
    let before = snapshot_original(&f.config, "root-authority-leases-v1");
    let mut recovery = f.open();
    let mut session = ActualSession::spawn("public-loader-positive");
    let target: NotesTargetIdentity =
        serde_json::from_value(session.reserved["target"].clone()).unwrap();
    let (producer, mut reader) = deployment();
    recovery
        .reserve_session(
            &f.profile_path,
            session.channel.try_clone().unwrap(),
            session.pidfd.try_clone().unwrap(),
            producer,
        )
        .unwrap();
    assert_eq!(
        snapshot_original(&f.config, "root-authority-leases-v1"),
        before
    );
    session.assert_waiting();
    recovery.advance().unwrap();
    let after = snapshot_original(&f.config, "root-authority-leases-v1");
    recovery.advance().unwrap();
    assert_eq!(
        snapshot_original(&f.config, "root-authority-leases-v1"),
        after
    );
    session.assert_waiting();
    let prepared = recovery.finish().unwrap();
    let sealed = read_sealed(&mut reader);
    assert_eq!(
        sealed,
        serde_json::json!({
            "schema":"hepta.agentd.original_notes_launch.v1",
            "agent_id":f.registration.registered_identity.agent_id.as_str(),
            "spawn_generation":f.registration.registered_identity.spawn_generation,
            "session":session.birth,"bindings":f.bindings,"previous_recovery":null,
            "startup_release":{"target":session.reserved["target"],"nonce":session.reserved["nonce"]}
        })
    );
    let mut bootstrap = prepared.seal_bootstrap(f.consumers.path()).unwrap();
    let public = read_sealed(&mut bootstrap);
    assert_eq!(
        public["checkpoint"],
        serde_json::to_value(&after.1).unwrap()
    );
    assert_eq!(
        public["writer"],
        serde_json::to_value(f.config.writer.as_ref().unwrap()).unwrap()
    );
    let mut expected = before.0.clone();
    expected["sequence"] = (before.0["sequence"].as_u64().unwrap() + 1).into();
    expected["writer_authorization"] = public["writer_proof"].clone();
    expected["policies"][0] = serde_json::to_value(DeploymentGrantPolicy {
        subject_id: f.registration.registered_identity.agent_id.as_str().into(),
        destination_id: target.destination_id(),
        scope_sha256: target.scope_digest().into_array(),
        lifetime_ms: 1_000,
    })
    .unwrap();
    assert_eq!(after.0, expected);
    assert_eq!(after.1.last_current, before.1.last_current);
    assert_eq!(after.1.counter, before.1.counter + 1);
    assert_eq!((&after.2, &after.3), (&before.2, &before.3));
    assert_eq!(
        snapshot_original(&f.config, "root-authority-leases-v1"),
        after
    );
    session.assert_waiting();
    write_json(
        &output().join("public-loader-positive.json"),
        &serde_json::json!({
            "schema":"hepta.notes-recovery-staged-session-fixture.v1","passed":true,
            "production_authority":false,"actual_agentd_owner":false,"activation_sent":false,
            "effect_dispatched":false,"five_lane_consumers_connected":false,
            "public_loader_executed":true,"actual_session_reserved":true,"deployment_sealed":true,
            "exact_repeat_unchanged":true,"bootstrap_sealed":true,
        "reserved":session.reserved,"session_birth":session.birth,"binaries":session.binaries,
        "actual_initial_app_pid":session.app_pid,"app_window_qualified":false
        }),
    );
}

#[tokio::test]
#[ignore = "explicit private Root bind and pinned real staged Session/App/Xvfb fixture"]
async fn root_notes_recovery_public_loader_dead_session_preserves_all_original_state() {
    let mut f = PublicFixture::new().await;
    let before = snapshot_original(&f.config, "root-authority-leases-v1");
    let mut recovery = f.open();
    let mut session = ActualSession::spawn("public-loader-dead-session");
    let (producer, reader) = deployment();
    recovery
        .reserve_session(
            &f.profile_path,
            session.channel.try_clone().unwrap(),
            session.pidfd.try_clone().unwrap(),
            producer,
        )
        .unwrap();
    session.assert_waiting();
    session.stop();
    assert!(recovery.advance().is_err());
    assert!(recovery.finish().is_err());
    assert_eq!(
        snapshot_original(&f.config, "root-authority-leases-v1"),
        before
    );
    assert_eq!(reader.metadata().unwrap().len(), 0);
    // SAFETY: this only reads seals of this retained original fixture memfd.
    assert_eq!(
        unsafe { libc::fcntl(reader.as_raw_fd(), libc::F_GET_SEALS) },
        0
    );
    write_json(
        &output().join("public-loader-dead-session.json"),
        &serde_json::json!({
            "schema":"hepta.notes-recovery-staged-session-fixture.v1","passed":true,
            "production_authority":false,"actual_agentd_owner":false,"activation_sent":false,
            "effect_dispatched":false,"five_lane_consumers_connected":false,
            "public_loader_executed":true,"actual_session_reserved":true,"session_reaped":true,
            "advance_refused":true,"finish_refused":true,"original_state_unchanged":true,
            "deployment_empty_unsealed":true,
        "reserved":session.reserved,"session_birth":session.birth,"binaries":session.binaries,
        "actual_initial_app_pid":session.app_pid,"app_window_qualified":false
        }),
    );
}
