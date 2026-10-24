use super::ensure_legacy_write_policy;
use crate::resolved_permissions::ResolvedWindowsSandboxPermissions;
use codex_protocol::models::PermissionProfile;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::collections::HashMap;

fn parsed_permissions(entries: Value) -> ResolvedWindowsSandboxPermissions {
    let profile: PermissionProfile = serde_json::from_value(json!({
        "type": "managed",
        "file_system": {
            "type": "restricted",
            "entries": entries,
        },
        "network": "restricted",
    }))
    .expect("parse managed permission profile");
    ResolvedWindowsSandboxPermissions::try_from_permission_profile_for_workspace_roots(
        &profile,
        &[],
    )
    .expect("resolve managed permission profile")
}

fn root_read_permissions() -> ResolvedWindowsSandboxPermissions {
    parsed_permissions(json!([{
        "path": { "type": "special", "value": { "kind": "root" } },
        "access": "read",
    }]))
}

fn parsed_policy_decision(entries: Value, has_deny_write_paths: bool) -> (bool, bool, bool, bool) {
    let permissions = parsed_permissions(entries);
    let cwd = std::env::current_dir().expect("absolute working directory");
    let uses_write_capabilities =
        permissions.uses_write_capabilities_for_cwd(&cwd, &HashMap::new());
    let admitted =
        ensure_legacy_write_policy(&permissions, uses_write_capabilities, has_deny_write_paths)
            .is_ok();
    (
        permissions.has_full_disk_read_access(),
        permissions.has_full_disk_write_access(),
        uses_write_capabilities,
        admitted,
    )
}

#[test]
fn legacy_read_only_without_deny_write_paths_is_admitted() {
    let result = ensure_legacy_write_policy(
        &root_read_permissions(),
        /*uses_write_capabilities*/ false,
        /*has_deny_write_paths*/ false,
    );

    assert_eq!(result.map_err(|error| error.to_string()), Ok(()));
}

#[test]
fn legacy_write_capabilities_are_rejected() {
    let error = ensure_legacy_write_policy(
        &root_read_permissions(),
        /*uses_write_capabilities*/ true,
        /*has_deny_write_paths*/ false,
    )
    .expect_err("write capabilities require the elevated backend");

    assert_eq!(
        error.to_string(),
        "write-capable or deny-write requests require the elevated Windows sandbox backend"
    );
}

#[test]
fn legacy_deny_write_paths_without_write_capabilities_are_rejected() {
    let error = ensure_legacy_write_policy(
        &root_read_permissions(),
        /*uses_write_capabilities*/ false,
        /*has_deny_write_paths*/ true,
    )
    .expect_err("deny-write paths require the elevated backend");

    assert_eq!(
        error.to_string(),
        "write-capable or deny-write requests require the elevated Windows sandbox backend"
    );
}

#[test]
fn legacy_write_capabilities_with_deny_write_paths_are_rejected() {
    let error = ensure_legacy_write_policy(
        &root_read_permissions(),
        /*uses_write_capabilities*/ true,
        /*has_deny_write_paths*/ true,
    )
    .expect_err("combined write policy requires the elevated backend");

    assert_eq!(
        error.to_string(),
        "write-capable or deny-write requests require the elevated Windows sandbox backend"
    );
}

#[test]
fn parsed_full_disk_write_is_rejected_despite_empty_writable_roots() {
    let decision = parsed_policy_decision(
        json!([{
            "path": { "type": "special", "value": { "kind": "root" } },
            "access": "write",
        }]),
        /*has_deny_write_paths*/ false,
    );

    // Full read, full write, no enumerated capability roots, not admitted.
    assert_eq!(decision, (true, true, false, false));
}

#[test]
fn parsed_root_read_without_write_overrides_is_admitted() {
    let decision = parsed_policy_decision(
        json!([{
            "path": { "type": "special", "value": { "kind": "root" } },
            "access": "read",
        }]),
        /*has_deny_write_paths*/ false,
    );

    assert_eq!(decision, (true, false, false, true));
}

#[test]
fn parsed_concrete_writable_root_is_rejected() {
    let cwd = std::env::current_dir().expect("absolute working directory");
    let decision = parsed_policy_decision(
        json!([
            {
                "path": { "type": "special", "value": { "kind": "root" } },
                "access": "read",
            },
            {
                "path": { "type": "path", "path": cwd },
                "access": "write",
            },
        ]),
        /*has_deny_write_paths*/ false,
    );

    assert_eq!(decision, (true, false, true, false));
}

#[test]
fn parsed_root_write_with_read_only_carveout_is_rejected() {
    let cwd = std::env::current_dir().expect("absolute working directory");
    let decision = parsed_policy_decision(
        json!([
            {
                "path": { "type": "special", "value": { "kind": "root" } },
                "access": "write",
            },
            {
                "path": { "type": "path", "path": cwd.join("read-only") },
                "access": "read",
            },
        ]),
        /*has_deny_write_paths*/ false,
    );

    assert_eq!(decision, (true, false, true, false));
}

#[test]
fn parsed_root_read_with_deny_write_override_is_rejected() {
    let decision = parsed_policy_decision(
        json!([{
            "path": { "type": "special", "value": { "kind": "root" } },
            "access": "read",
        }]),
        /*has_deny_write_paths*/ true,
    );

    assert_eq!(decision, (true, false, false, false));
}
