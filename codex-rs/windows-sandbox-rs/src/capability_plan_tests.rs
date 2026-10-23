use super::*;
use crate::capability_registry::MAX_REGISTERED_ROOTS;
use crate::capability_registry::REGISTRY_VERSION;
use pretty_assertions::assert_eq;
use std::collections::HashMap;

fn registry() -> CapSids {
    CapSids {
        version: REGISTRY_VERSION,
        generation: "a".repeat(32),
        workspace: "S-1-5-21-1-2-3-4".into(),
        readonly: "S-1-5-21-2-3-4-5".into(),
        workspace_by_cwd: HashMap::from([("cwd".into(), "S-1-5-21-3-4-5-6".into())]),
        writable_root_by_path: HashMap::new(),
    }
}

#[test]
fn roles_round_trip_without_becoming_prepared_authority() {
    let caps = registry();
    let plan = FilesystemCapabilityPlan::declare(
        &caps,
        "cwd".into(),
        vec!["runtime".into()],
        vec!["cwd".into()],
    )
    .unwrap();
    let decoded: FilesystemCapabilityPlan =
        serde_json::from_slice(&serde_json::to_vec(&plan).unwrap()).unwrap();
    assert_eq!(decoded, plan);
    decoded.validate_registry(&caps).unwrap();
    assert_eq!(decoded.network_route_sid(), None);
    decoded
        .validate_transport_mirror(
            FilesystemCapabilityRole::Write,
            &[caps.workspace_by_cwd["cwd"].clone()],
            None,
        )
        .unwrap();
    assert!(
        decoded
            .validate_transport_mirror(
                FilesystemCapabilityRole::Read,
                &[caps.workspace_by_cwd["cwd"].clone()],
                None
            )
            .is_err()
    );
    assert!(decoded.matches_roots("cwd", &["runtime".into()], &["cwd".into()]));
    assert_eq!(
        decoded.read_sids().collect::<Vec<_>>(),
        vec![caps.readonly.as_str()]
    );
    assert_eq!(
        decoded.write_sids().collect::<Vec<_>>(),
        vec![caps.workspace_by_cwd["cwd"].as_str()]
    );
}

#[test]
fn stale_generation_or_role_reassignment_is_refused() {
    let caps = registry();
    let plan = FilesystemCapabilityPlan::declare(
        &caps,
        "cwd".into(),
        vec!["runtime".into()],
        vec!["cwd".into()],
    )
    .unwrap();
    let mut stale = plan.clone();
    stale.registry_generation = "b".repeat(32);
    assert!(stale.validate_registry(&caps).is_err());
    let mut swapped = plan;
    swapped.read[0].sid = swapped.write[0].sid.clone();
    assert!(swapped.validate_registry(&caps).is_err());
}

#[test]
fn active_root_bound_and_duplicate_roles_are_refused_without_truncation() {
    let caps = registry();
    let roots: Vec<_> = (0..MAX_ACTIVE_ROOTS)
        .map(|index| format!("read-{index}"))
        .collect();
    let plan =
        FilesystemCapabilityPlan::declare(&caps, "cwd".into(), roots.clone(), vec![]).unwrap();
    assert_eq!(plan.read.len(), MAX_ACTIVE_ROOTS);
    let mut over = roots;
    over.push("one-too-many".into());
    assert!(FilesystemCapabilityPlan::declare(&caps, "cwd".into(), over, vec![]).is_err());
    assert!(
        FilesystemCapabilityPlan::declare(
            &caps,
            "cwd".into(),
            vec!["same".into(), "same".into()],
            vec![]
        )
        .is_err()
    );
}

#[test]
fn network_route_cannot_reuse_a_filesystem_identity() {
    let caps = registry();
    let plan =
        FilesystemCapabilityPlan::declare(&caps, "cwd".into(), vec!["runtime".into()], vec![])
            .unwrap();
    assert!(
        plan.clone()
            .with_network_route(Some(caps.readonly.clone()))
            .unwrap()
            .validate_registry(&caps)
            .is_err()
    );
    let routed = plan
        .clone()
        .with_network_route(Some("S-1-5-21-8-9-10-11".into()))
        .unwrap();
    assert!(plan.same_filesystem_declaration(&routed));
    plan.with_network_route(Some("S-1-5-21-8-9-10-11".into()))
        .unwrap()
        .validate_registry(&caps)
        .unwrap();
}

#[test]
fn registry_capacity_and_duplicate_identity_are_refused() {
    let mut caps = registry();
    for index in 1..MAX_REGISTERED_ROOTS {
        caps.writable_root_by_path.insert(
            format!("root-{index}"),
            format!("S-1-5-21-10-11-12-{}", index + 100),
        );
    }
    caps.validate().unwrap();
    caps.writable_root_by_path
        .insert("MAX+1".into(), "S-1-5-21-20-21-22-23".into());
    assert!(caps.validate().is_err());
    let mut duplicate = registry();
    duplicate.readonly = duplicate.workspace.clone();
    assert!(duplicate.validate().is_err());
}

#[test]
fn wire_cannot_supply_a_prepared_flag_or_unknown_role() {
    let caps = registry();
    let plan = FilesystemCapabilityPlan::declare(&caps, "cwd".into(), vec![], vec![]).unwrap();
    let mut value = serde_json::to_value(plan).unwrap();
    value["ready"] = true.into();
    assert!(serde_json::from_value::<FilesystemCapabilityPlan>(value).is_err());
}

#[test]
fn a_valid_plan_does_not_match_another_requests_cwd_or_roots() {
    let caps = registry();
    let plan = FilesystemCapabilityPlan::declare(
        &caps,
        "cwd".into(),
        vec!["runtime".into()],
        vec!["cwd".into()],
    )
    .unwrap();
    plan.validate_transport_mirror(
        FilesystemCapabilityRole::Write,
        &[caps.workspace_by_cwd["cwd"].clone()],
        None,
    )
    .unwrap();
    assert!(!plan.matches_roots("other", &["runtime".into()], &["cwd".into()]));
    assert!(!plan.matches_roots("cwd", &["other-runtime".into()], &["cwd".into()]));
    let mut wire = serde_json::to_value(plan).unwrap();
    let roots = wire["read"].as_array_mut().unwrap();
    let root = roots[0].clone();
    *roots = vec![root; MAX_ACTIVE_ROOTS + 1];
    assert!(serde_json::from_value::<FilesystemCapabilityPlan>(wire).is_err());
}

#[test]
fn original_root_context_is_stable_across_runner_users_and_rejects_changes() {
    let context = RootResolutionContext {
        profile: Some("profile-a".into()),
        temp: [("TEMP".into(), "temp-a".into())].into(),
    };
    let child_environment = HashMap::from([("USERPROFILE".into(), "profile-b".into())]);
    let resolved = context.request_environment(&child_environment).unwrap();
    assert_eq!(
        (resolved["TEMP"].as_str(), resolved["TMP"].as_str()),
        ("temp-a", "")
    );
    let binding = RootRequestBinding {
        permissions: serde_json::json!({"kind":"read-only"}),
        cwd: "cwd".into(),
        codex_home: "home".into(),
        context: context.clone(),
    };
    let plan = FilesystemCapabilityPlan::declare(&registry(), "cwd".into(), vec![], vec![])
        .unwrap()
        .bind_request(binding.clone())
        .unwrap();
    plan.validate_request(&binding).unwrap();
    let mut different = binding;
    different.context.profile = Some("profile-b".into());
    assert!(plan.validate_request(&different).is_err());
    assert!(
        context
            .request_environment(&HashMap::from([("TEMP".into(), "temp-b".into())]))
            .is_err()
    );
}
