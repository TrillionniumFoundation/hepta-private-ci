use super::*;
use pretty_assertions::assert_eq;

fn fixture() -> RootNotesHostConfigV1 {
    RootNotesHostConfigV1 {
        schema_version: 1,
        operation: ROOT_NOTES_HOST_CONFIG_OPERATION_V1.into(),
        root: CognitiveCheckpointPeerLifetime {
            uid: 0,
            pid: 42,
            boot_id: "01234567-89ab-4cde-8fab-0123456789ab".into(),
            process_start_ticks: 10,
        },
        launch: RootNotesLaunchEndpointV1 {
            socket_path: "/var/lib/test-runtime/launch/socket".into(),
            wait_lifetime_ms: 300_000,
        },
        agent: RootNotesAgentPathsV1 {
            fleet_root: "/var/lib/test-fleet".into(),
            agent_id: AgentId::parse("01234567-89ab-4cde-8fab-0123456789ab").unwrap(),
            spawn_generation: 2,
            home_root: "/var/lib/test-agent/home".into(),
            run_root: "/var/lib/test-agent/run".into(),
            codex_home: "/var/lib/test-agent/home".into(),
            workspace: "/var/lib/test-workspace".into(),
        },
        authbus: RootNotesAuthBusPathsV1 {
            trust_file: "/var/lib/test-agent/home/trust.json".into(),
            checkpoint_file: "/var/lib/test-witness/checkpoint.json".into(),
            objective_profile_file: "/var/lib/test-agent/home/profile.json".into(),
        },
        session_peer_config_path: "/var/lib/test-runtime/public/peer.json".into(),
        installed_bundle: RootNotesInstalledBundleV1 {
            manifest_path: "/var/lib/test-runtime/public/bundle.json".into(),
            manifest_sha256: Digest32::of_bytes(b"fixture manifest, not installed assets"),
            bindings: RootNotesInstalledBindingsV1 {
                principal_scope_digest: Digest32::of_bytes(b"fixture principal"),
                policy_generation: Generation::new(1).unwrap(),
                locale: "zh-CN".into(),
                runtime_body_digest: Digest32::of_bytes(b"fixture runtime"),
                preference_state_digest: Digest32::of_bytes(b"fixture preference"),
                model_tuple_digest: Digest32::of_bytes(b"fixture model"),
                prompt_registry_digest: Digest32::of_bytes(b"fixture prompt"),
                artifact_set_digest: Digest32::of_bytes(b"fixture artifacts"),
            },
        },
        deployment: RootNotesDeploymentV1::NotesOnly {},
    }
}

#[test]
fn root_notes_host_config_round_trips_both_explicit_profiles() {
    for deployment in [
        RootNotesDeploymentV1::NotesOnly {},
        RootNotesDeploymentV1::NativeHos2 {},
    ] {
        let mut expected = fixture();
        expected.deployment = deployment;
        expected.validate_shape().unwrap();
        let encoded = serde_json::to_vec(&expected).unwrap();
        let actual: RootNotesHostConfigV1 = serde_json::from_slice(&encoded).unwrap();
        assert_eq!(actual, expected);
        assert_eq!(serde_json::to_vec(&actual).unwrap(), encoded);
    }
}

#[test]
fn root_notes_host_config_rejects_unknown_fields_at_each_boundary() {
    for pointer in [
        "",
        "/root",
        "/launch",
        "/agent",
        "/authbus",
        "/installed_bundle",
        "/installed_bundle/bindings",
        "/deployment",
    ] {
        let mut value = serde_json::to_value(fixture()).unwrap();
        value
            .pointer_mut(pointer)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert("authority".into(), serde_json::json!(true));
        assert!(
            serde_json::from_value::<RootNotesHostConfigV1>(value).is_err(),
            "{pointer}"
        );
    }
}

#[test]
fn root_notes_host_config_rejects_duplicate_and_noncanonical_original_types() {
    let bytes = serde_json::to_string(&fixture()).unwrap();
    let duplicate = bytes.replacen(
        "\"schema_version\":1",
        "\"schema_version\":1,\"schema_version\":1",
        1,
    );
    assert!(serde_json::from_str::<RootNotesHostConfigV1>(&duplicate).is_err());
    let duplicate = bytes.replacen(
        "\"kind\":\"notes_only\"",
        "\"kind\":\"notes_only\",\"kind\":\"native_hos2\"",
        1,
    );
    assert!(serde_json::from_str::<RootNotesHostConfigV1>(&duplicate).is_err());
    for (pointer, invalid) in [
        (
            "/installed_bundle/manifest_sha256",
            serde_json::json!("A".repeat(64)),
        ),
        (
            "/installed_bundle/bindings/policy_generation",
            serde_json::json!(0),
        ),
        ("/agent/agent_id", serde_json::json!("not-an-agent")),
        ("/deployment/kind", serde_json::json!("automatic")),
    ] {
        let mut value = serde_json::to_value(fixture()).unwrap();
        *value.pointer_mut(pointer).unwrap() = invalid;
        assert!(serde_json::from_value::<RootNotesHostConfigV1>(value).is_err());
    }
}

#[test]
fn root_notes_host_config_rejects_role_and_identity_confusion() {
    let mutations: &[fn(&mut RootNotesHostConfigV1)] = &[
        |v| v.root.uid = 60001,
        |v| v.root.pid = 0,
        |v| v.root.process_start_ticks = 0,
        |v| v.root.boot_id = "00000000-0000-0000-0000-000000000000".into(),
        |v| v.agent.spawn_generation = 0,
        |v| v.launch.wait_lifetime_ms = 300_001,
        |v| v.agent.codex_home = v.agent.run_root.clone(),
        |v| v.authbus.checkpoint_file = v.agent.home_root.join("checkpoint.json"),
        |v| v.authbus.trust_file = v.agent.home_root.join("nested/trust.json"),
        |v| v.authbus.objective_profile_file = v.authbus.trust_file.clone(),
        |v| v.session_peer_config_path = v.agent.home_root.join("peer.json"),
        |v| v.installed_bundle.manifest_path = v.agent.home_root.join("bundle.json"),
        |v| v.installed_bundle.manifest_sha256 = Digest32::ZERO,
        |v| v.installed_bundle.bindings.runtime_body_digest = Digest32::ZERO,
        |v| v.installed_bundle.bindings.locale = "auto".into(),
    ];
    for mutate in mutations {
        let mut value = fixture();
        mutate(&mut value);
        assert!(value.validate_shape().is_err(), "{value:?}");
    }
}

#[test]
fn root_notes_host_config_rejects_ambiguous_and_unbounded_paths() {
    for path in [
        "relative", "/", "/a/../b", "/a/./b", "/a//b", "/a/", "/a\0b",
    ] {
        let mut value = fixture();
        value.agent.workspace = path.into();
        assert!(value.validate_shape().is_err(), "{path:?}");
    }
    let mut value = fixture();
    value.launch.socket_path = format!("/{}", "a".repeat(107)).into();
    assert!(value.validate_shape().is_err());
    value = fixture();
    value.agent.workspace = format!("/{}", "a".repeat(4096)).into();
    assert!(value.validate_shape().is_err());
}
