use super::HeldRecord;
use super::ManagedAccountSource;
use crate::identity::SandboxCreds;
use crate::setup::OFFLINE_USERNAME;
use crate::setup::ONLINE_USERNAME;
use crate::setup::SETUP_VERSION;
use crate::setup::SandboxUserRecord;
use crate::setup::SandboxUsersFile;
use crate::setup::SetupMarker;
use crate::setup::sandbox_users_path;
use crate::setup::setup_marker_path;
use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use std::fs;

#[test]
fn held_source_rejects_in_place_record_change() {
    let home = tempfile::tempdir().unwrap();
    let path = home.path().join("record");
    fs::write(&path, "original").unwrap();
    let mut held = HeldRecord::open(path.clone()).unwrap();
    held.revalidate().unwrap();
    fs::write(&path, "different").unwrap();
    assert!(held.revalidate().is_err());
}

#[test]
fn held_source_rejects_same_bytes_at_a_replacement_path() {
    let home = tempfile::tempdir().unwrap();
    let path = home.path().join("record");
    fs::write(&path, "original").unwrap();
    let mut held = HeldRecord::open(path.clone()).unwrap();
    fs::rename(&path, home.path().join("old")).unwrap();
    fs::write(&path, "original").unwrap();
    assert!(held.revalidate().is_err());
}

#[test]
fn oversized_source_is_refused_before_readback_allocation() {
    let home = tempfile::tempdir().unwrap();
    let path = home.path().join("record");
    fs::File::create(&path)
        .unwrap()
        .set_len(super::RECORD_BOUND + 1)
        .unwrap();
    assert!(HeldRecord::open(path).is_err());
}

#[test]
fn missing_malformed_and_stale_original_sources_never_create_a_witness() {
    let home = tempfile::tempdir().unwrap();
    let credentials = SandboxCreds {
        username: OFFLINE_USERNAME.into(),
        password: "password".into(),
    };
    assert!(ManagedAccountSource::select(home.path(), &credentials).is_err());
    let marker_path = setup_marker_path(home.path());
    fs::create_dir_all(marker_path.parent().unwrap()).unwrap();
    fs::write(&marker_path, "{}").unwrap();
    assert!(ManagedAccountSource::select(home.path(), &credentials).is_err());
    fs::create_dir_all(sandbox_users_path(home.path()).parent().unwrap()).unwrap();
    fs::write(
        &marker_path,
        serde_json::to_vec(&marker(SETUP_VERSION - 1)).unwrap(),
    )
    .unwrap();
    write_users(home.path());
    assert!(ManagedAccountSource::select(home.path(), &credentials).is_err());
}

#[test]
fn dto_name_password_and_foreign_marker_cannot_substitute_for_original_selection() {
    let home = tempfile::tempdir().unwrap();
    let path = setup_marker_path(home.path());
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(&path, serde_json::to_vec(&marker(SETUP_VERSION)).unwrap()).unwrap();
    write_users(home.path());
    for credentials in [
        SandboxCreds {
            username: "caller".into(),
            password: "password".into(),
        },
        SandboxCreds {
            username: OFFLINE_USERNAME.into(),
            password: "wrong".into(),
        },
    ] {
        assert!(ManagedAccountSource::select(home.path(), &credentials).is_err());
    }
    let mut foreign = marker(SETUP_VERSION);
    foreign.offline_username = "caller".into();
    fs::write(path, serde_json::to_vec(&foreign).unwrap()).unwrap();
    assert!(
        ManagedAccountSource::select(
            home.path(),
            &SandboxCreds {
                username: OFFLINE_USERNAME.into(),
                password: "password".into()
            }
        )
        .is_err()
    );
}

fn marker(version: u32) -> SetupMarker {
    SetupMarker {
        version,
        filesystem_roles: None,
        offline_username: OFFLINE_USERNAME.into(),
        online_username: ONLINE_USERNAME.into(),
        created_at: None,
        proxy_ports: Vec::new(),
        allow_local_binding: false,
    }
}

fn write_users(home: &std::path::Path) {
    let record = |name: &str| SandboxUserRecord {
        username: name.into(),
        password: STANDARD.encode(crate::dpapi::protect(b"password").unwrap()),
    };
    let users = SandboxUsersFile {
        version: SETUP_VERSION,
        offline: record(OFFLINE_USERNAME),
        online: record(ONLINE_USERNAME),
    };
    let path = sandbox_users_path(home);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, serde_json::to_vec(&users).unwrap()).unwrap();
}
