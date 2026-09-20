use codex_hepta_control_plane::RuntimeModuleStateClassV1;

use super::parse;

#[test]
fn runtime_module_state_rejects_unknown_and_substring_aliases() {
    for value in [
        "",
        "stateful_v2",
        "not_stateful",
        "stateless_future",
        "STATELESS",
        "stateless ",
        " stateful",
        "stateful_external_unknown",
        "unknown",
        "stateless\0",
    ] {
        assert!(parse(value).is_err(), "accepted unknown state: {value:?}");
    }
}

#[test]
fn runtime_module_state_preserves_explicit_persistence_classes() {
    let parsed = ["stateless", "ephemeral", "stateful", "stateful_external"]
        .map(|state| parse(state).expect("known registry state"));
    assert_eq!(
        parsed,
        [
            RuntimeModuleStateClassV1::Stateless,
            RuntimeModuleStateClassV1::Stateless,
            RuntimeModuleStateClassV1::Stateful,
            RuntimeModuleStateClassV1::ExternalStateful,
        ]
    );
}
