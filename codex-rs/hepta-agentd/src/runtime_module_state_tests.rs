use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use codex_hepta_fleet::RuntimeModuleCatalogV1;

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

#[test]
fn runtime_module_state_catalog_and_host_admit_the_same_explicit_classes() {
    use RuntimeModuleStateClassV1::ExternalStateful;
    use RuntimeModuleStateClassV1::Stateful;
    use RuntimeModuleStateClassV1::Stateless;

    for (state, expected) in [
        ("stateless", Stateless),
        ("stateless_runtime", Stateless),
        ("ephemeral", Stateless),
        ("ephemeral_isolated", Stateless),
        ("read_only", Stateless),
        ("read_only_remote", Stateless),
        ("stateful", Stateful),
        ("stateful_projection", Stateful),
        ("stateful_rebuildable", Stateful),
        ("stateful_append_only", Stateful),
        ("stateful_shadow", Stateful),
        ("stateful_create_only", Stateful),
        ("isolated_stateful", Stateful),
        ("stateful_external", ExternalStateful),
    ] {
        let json = serde_json::json!({"modules": [{
            "id": "optional.example", "owner": "owner", "state": state,
            "uses": [], "writes": []
        }]})
        .to_string();
        let catalog = RuntimeModuleCatalogV1::from_reviewed_json(&json)
            .expect("explicit state must pass the catalog");
        let row = catalog.module("optional.example").expect("catalog row");
        assert_eq!(
            parse(&row.state).expect("host must consume catalog state"),
            expected
        );
    }
}

#[test]
fn runtime_module_state_every_canonical_module_is_consumable_by_the_host() {
    let catalog = RuntimeModuleCatalogV1::canonical().expect("canonical catalog");
    for id in catalog.module_ids() {
        let module = catalog.module(id).expect("enumerated module");
        assert!(
            parse(&module.state).is_ok(),
            "unmapped canonical state for {id}: {}",
            module.state
        );
    }
}
