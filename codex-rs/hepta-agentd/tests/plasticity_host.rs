use std::fs::OpenOptions;
use std::io::Write;

use codex_hepta_agentd::AgentdPlasticityAnchorFenceStoreV1;
use codex_hepta_intelligence::{DurableRegistryAnchorV1, PlasticityAnchorCommitterV1};
use codex_hepta_types::Digest32;
use tempfile::NamedTempFile;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn open_file(path: &std::path::Path) -> std::fs::File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .expect("open anchor journal")
}

#[test]
fn plasticity_anchor_fence_journal_reopens_exact_monotonic_state() {
    let fixture = NamedTempFile::new().expect("named tempfile");
    let path = fixture.path().to_path_buf();
    let scope = digest("plasticity-registry-scope");
    let expected_anchor = DurableRegistryAnchorV1 {
        sequence: 1,
        frame_digest: digest("proposal-frame:1"),
    };

    {
        let mut store = AgentdPlasticityAnchorFenceStoreV1::open(open_file(&path), scope)
            .expect("open store");
        assert_eq!(store.issue_new_registry_fence().expect("fence"), 1);
        assert!(store.persist_anchor(scope, 1, expected_anchor));
        assert_eq!(store.state().writer_fence, 1);
        assert_eq!(store.state().anchor, Some(expected_anchor));

        let rollback = DurableRegistryAnchorV1 {
            sequence: 1,
            frame_digest: digest("different-frame"),
        };
        assert!(!store.persist_anchor(scope, 1, rollback));
        assert_eq!(store.state().anchor, Some(expected_anchor));
    }

    let reopened = AgentdPlasticityAnchorFenceStoreV1::open(open_file(&path), scope)
        .expect("reopen store");
    assert_eq!(reopened.state().writer_fence, 1);
    assert_eq!(reopened.state().anchor, Some(expected_anchor));
}

#[test]
fn plasticity_anchor_fence_journal_rejects_wrong_scope_and_stale_fence() {
    let fixture = NamedTempFile::new().expect("named tempfile");
    let path = fixture.path().to_path_buf();
    let scope = digest("plasticity-registry-scope");
    let anchor = DurableRegistryAnchorV1 {
        sequence: 1,
        frame_digest: digest("proposal-frame:1"),
    };
    let mut store = AgentdPlasticityAnchorFenceStoreV1::open(open_file(&path), scope)
        .expect("open store");
    assert_eq!(store.issue_new_registry_fence().expect("fence"), 1);
    assert!(!store.persist_anchor(digest("wrong-scope"), 1, anchor));
    assert!(!store.persist_anchor(scope, 2, anchor));
    assert_eq!(store.state().anchor, None);
}


#[test]
fn plasticity_anchor_fence_journal_repairs_only_incomplete_tail() {
    let fixture = NamedTempFile::new().expect("named tempfile");
    let path = fixture.path().to_path_buf();
    let scope = digest("plasticity-registry-scope:torn-tail");
    let expected_anchor = DurableRegistryAnchorV1 {
        sequence: 1,
        frame_digest: digest("proposal-frame:torn-tail"),
    };

    {
        let mut store = AgentdPlasticityAnchorFenceStoreV1::open(open_file(&path), scope)
            .expect("open store");
        assert_eq!(store.issue_new_registry_fence().expect("fence"), 1);
        assert!(store.persist_anchor(scope, 1, expected_anchor));
    }
    let valid_len = std::fs::metadata(&path).expect("metadata").len();
    {
        let mut file = OpenOptions::new()
            .append(true)
            .open(&path)
            .expect("append torn tail");
        file.write_all(&[0, 1, 2, 3, 4]).expect("write torn tail");
        file.sync_all().expect("sync torn tail");
    }

    let reopened = AgentdPlasticityAnchorFenceStoreV1::open(open_file(&path), scope)
        .expect("recover torn tail");
    assert_eq!(reopened.state().writer_fence, 1);
    assert_eq!(reopened.state().anchor, Some(expected_anchor));
    drop(reopened);
    assert_eq!(
        std::fs::metadata(&path).expect("metadata after recovery").len(),
        valid_len
    );
}
