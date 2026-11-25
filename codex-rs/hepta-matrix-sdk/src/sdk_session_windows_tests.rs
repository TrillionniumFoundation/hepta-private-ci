use std::fs;
use std::io::Write;
use std::process::Command;

use codex_utils_path::PrivateFileAccess;
use matrix_sdk::SessionMeta;
use matrix_sdk::SessionTokens;
use pretty_assertions::assert_eq;

use super::MATRIX_SESSION_MAX_BYTES;
use super::NEXT_SESSION_NAME;
use super::RetainedSessionDirectories;
use super::RetainedSessionStore;
use super::SESSION_NAME;
use crate::MatrixSdkError;
use crate::MatrixSession;
use crate::MatrixSidecarConfigError;

fn session(access_token: &str) -> MatrixSession {
    MatrixSession {
        meta: SessionMeta {
            user_id: "@owner:example.test"
                .try_into()
                .expect("fixture Matrix user"),
            device_id: "WINDOWS_OWNER".into(),
        },
        tokens: SessionTokens {
            access_token: access_token.to_owned(),
            refresh_token: Some("local-fixture-refresh-token".to_owned()),
        },
    }
}

#[test]
fn private_session_owner_pins_directories_and_reopens_durable_session() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let ancestor = temporary.path().join("owner");
    let root = ancestor.join("matrix-sdk-0.18");
    let moved = temporary.path().join("moved");
    let owner = RetainedSessionStore::prepare(&root).expect("private nested session owner");
    assert!(owner.load().expect("new owner has no session").is_none());
    for name in ["state", "cache"] {
        assert!(fs::rename(root.join(name), root.join(format!("moved-{name}"))).is_err());
    }
    assert!(fs::rename(&root, ancestor.join("redirected")).is_err());
    assert!(fs::rename(&ancestor, &moved).is_err());

    let original = session("local-fixture-access-token");
    owner
        .persist(&original)
        .expect("write, replace and flush through original handles");
    assert_eq!(
        serde_json::to_value(owner.load().expect("load original session")).expect("session value"),
        serde_json::to_value(Some(&original)).expect("original session value")
    );
    drop(owner);
    fs::rename(&ancestor, &moved).expect("dropping all owners releases directory pins");
    let reopened = RetainedSessionStore::prepare(&moved.join("matrix-sdk-0.18"))
        .expect("reopen persisted private owner");
    assert_eq!(
        serde_json::to_value(reopened.load().expect("reopen original session"))
            .expect("session value"),
        serde_json::to_value(Some(&original)).expect("original session value")
    );
}

#[test]
fn independent_session_owner_is_refused_until_original_owner_drops() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let root = temporary.path().join("owner");
    let owner = RetainedSessionStore::prepare(&root).expect("original private owner");
    owner
        .persist(&session("original-token"))
        .expect("original durable session");
    let original = fs::read(root.join(SESSION_NAME)).expect("original bytes");

    assert!(matches!(
        RetainedSessionStore::prepare(&root),
        Err(MatrixSidecarConfigError::Unavailable)
    ));
    // Public path preparation remains usable without acquiring another writer.
    drop(RetainedSessionDirectories::prepare(&root).expect("read existing private geometry"));
    assert_eq!(
        fs::read(root.join(SESSION_NAME)).expect("unchanged session"),
        original
    );

    drop(owner);
    let reopened = RetainedSessionStore::prepare(&root).expect("kernel releases dropped owner");
    let updated = session("replacement-token");
    reopened
        .persist(&updated)
        .expect("new owner can publish after release");
    assert_eq!(
        serde_json::to_value(reopened.load().expect("replacement session")).expect("session value"),
        serde_json::to_value(Some(&updated)).expect("replacement value")
    );
}

#[test]
fn junction_ancestry_refuses_session_creation_without_touching_target() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let target = temporary.path().join("target");
    let alias = temporary.path().join("alias");
    fs::create_dir(&target).expect("junction target");
    let output = Command::new("cmd.exe")
        .args(["/D", "/C", "mklink", "/J"])
        .arg(&alias)
        .arg(&target)
        .output()
        .expect("create real junction fixture");
    assert!(output.status.success(), "{output:?}");

    assert!(matches!(
        RetainedSessionStore::prepare(&alias.join("owner")),
        Err(MatrixSidecarConfigError::Unavailable)
    ));
    assert!(!target.join("owner").exists());
    fs::remove_dir(&alias).expect("remove junction without traversing its target");
}

#[test]
fn hardlinked_session_refuses_read_and_update_without_changing_bytes() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let root = temporary.path().join("owner");
    let owner = RetainedSessionStore::prepare(&root).expect("private session owner");
    owner
        .persist(&session("original-token"))
        .expect("original durable session");
    let path = root.join(SESSION_NAME);
    let original = fs::read(&path).expect("original bytes");
    let alias = root.join("session-alias");
    fs::hard_link(&path, &alias).expect("real NTFS hardlink fixture");

    assert!(matches!(owner.load(), Err(MatrixSdkError::Initialization)));
    assert!(matches!(
        owner.persist(&session("replacement-token")),
        Err(MatrixSdkError::Initialization)
    ));
    assert_eq!(fs::read(&path).expect("unchanged session"), original);
    assert_eq!(fs::read(&alias).expect("unchanged alias"), original);
    assert!(!root.join(NEXT_SESSION_NAME).exists());
}

#[test]
fn hardlinked_next_session_is_refused_before_truncation() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let root = temporary.path().join("owner");
    let owner = RetainedSessionStore::prepare(&root).expect("private session owner");
    owner
        .persist(&session("original-token"))
        .expect("original durable session");
    let original = fs::read(root.join(SESSION_NAME)).expect("original bytes");
    let next_bytes = b"previous uncommitted session";
    let mut next = codex_utils_path::open_private_state_child(
        &owner.directories.directory,
        NEXT_SESSION_NAME,
        PrivateFileAccess::Create,
    )
    .expect("private staging fixture");
    next.write_all(next_bytes).expect("staging bytes");
    next.sync_all().expect("flush staging fixture");
    drop(next);
    let alias = root.join("next-alias");
    fs::hard_link(root.join(NEXT_SESSION_NAME), &alias).expect("real NTFS staging hardlink");

    assert!(matches!(
        owner.persist(&session("replacement-token")),
        Err(MatrixSdkError::Initialization)
    ));
    assert_eq!(
        fs::read(root.join(SESSION_NAME)).expect("unchanged session"),
        original
    );
    assert_eq!(
        fs::read(root.join(NEXT_SESSION_NAME)).expect("untruncated staging"),
        next_bytes
    );
    assert_eq!(
        fs::read(&alias).expect("untruncated staging alias"),
        next_bytes
    );
}

#[test]
fn empty_or_oversized_private_session_is_refused_without_rewrite() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let root = temporary.path().join("owner");
    let owner = RetainedSessionStore::prepare(&root).expect("private session owner");
    for bytes in [
        Vec::new(),
        vec![b'a'; MATRIX_SESSION_MAX_BYTES as usize + 1],
    ] {
        let mut file = codex_utils_path::open_private_state_child(
            &owner.directories.directory,
            SESSION_NAME,
            PrivateFileAccess::Create,
        )
        .expect("private bounded-size fixture");
        file.set_len(/*size*/ 0).expect("truncate private fixture");
        file.write_all(&bytes).expect("fixture bytes");
        file.sync_all().expect("flush bounded-size fixture");
        drop(file);

        assert!(matches!(owner.load(), Err(MatrixSdkError::Initialization)));
        assert_eq!(
            fs::read(root.join(SESSION_NAME)).expect("unchanged bytes"),
            bytes
        );
    }
}
