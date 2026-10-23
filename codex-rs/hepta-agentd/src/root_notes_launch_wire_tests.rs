use super::*;
use pretty_assertions::assert_eq;

#[test]
fn fixed_launch_codec_refuses_extra_fields_and_never_serializes_authority() {
    let raw = r#"{"action":"recovered_owner_ready_v1","schema_version":1,"launch_nonce":"11111111111111111111111111111111"}"#;
    let frame: RootNotesLaunchFrame = serde_json::from_str(raw).unwrap();
    frame.validate().unwrap();
    assert_eq!(frame.descriptor_count(), 0);
    assert_eq!(serde_json::to_string(&frame).unwrap(), raw);
    for added in [
        r#", "path":"/tmp/chosen"}"#,
        r#", "cut":{}}"#,
        r#", "uid":0}"#,
    ] {
        let malicious = format!("{}{added}", &raw[..raw.len() - 1]);
        assert!(serde_json::from_str::<RootNotesLaunchFrame>(&malicious).is_err());
    }
}

#[test]
fn versions_nonces_and_root_session_role_are_not_negotiable() {
    for (version, nonce) in [
        (2, "1".repeat(32)),
        (1, "A".repeat(32)),
        (1, "0".repeat(31)),
    ] {
        assert!(
            RootNotesLaunchFrame::SessionChannelsV1 {
                schema_version: version,
                launch_nonce: nonce
            }
            .validate()
            .is_err()
        );
    }
    for uid in [0, 60_001, 1001] {
        assert!(
            RootNotesLaunchFrame::SessionSpawnedV1 {
                schema_version: 1,
                launch_nonce: "1".repeat(32),
                session: CognitiveCheckpointPeerLifetime {
                    uid,
                    pid: 1,
                    boot_id: "0".repeat(36),
                    process_start_ticks: 1
                },
            }
            .validate()
            .is_err()
        );
    }
}
