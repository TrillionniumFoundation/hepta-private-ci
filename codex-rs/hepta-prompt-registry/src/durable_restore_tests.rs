//! Adversarial restore fixtures use recomputed checksums to exercise semantics.

use super::*;
use crate::TestMust;

fn id(value: &str) -> StableId {
    StableId::new(value).must("test identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn factor(index: usize) -> PromptFactor {
    PromptFactor {
        factor_id: id(&format!("factor:restore:{index}")),
        proposer_id: id("proposer:restore"),
        semantic_version: id("v1"),
        semantic_purpose: "restore invariants".into(),
        authority_class: "registered_prompt_factor".into(),
        eligible_objective_dimensions: Vec::new(),
        content_digest: digest(&format!("factor-content:{index}")),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    }
}

fn registered_and_admitted(core: &mut PromptRegistry, index: usize) {
    let factor = factor(index);
    let factor_id = factor.factor_id.clone();
    core.register_factor(factor).must("register");
    core.admit_factor(&factor_id, &id("reviewer:restore"), digest("review"))
        .must("admit fixture");
}

#[test]
fn invalid_capacity_does_not_mark_a_new_directory_as_initialized() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&path, 0),
        Err(DurableRegistryError::Core(_))
    ));
    assert!(!path.exists());
    DurablePromptRegistry::open_state_dir(&path, 64).must("valid retry");
}

#[test]
fn known_precommit_bootstrap_failures_leave_a_retryable_owner_directory() {
    for fault in ["storage-full", "blocked-staging"] {
        let temp = tempfile::tempdir().must("temp");
        let path = temp.path().join("owner");
        let (store, stored) = Store::open(&path, /*maximum_records*/ 64).must("fresh owner");
        assert!(stored.is_none());
        assert!(store.new_owner_marker);
        if fault == "storage-full" {
            store.fail_storage_full_before_rename_once.set(true);
        } else {
            std::fs::create_dir(path.join("registry.next")).must("block staging");
        }
        let core = PromptRegistry::new(64).must("core");
        let result = store.initialize(&core);
        if fault == "storage-full" {
            assert!(matches!(result, Err(DurableRegistryError::StorageFull)));
        } else {
            assert!(matches!(result, Err(DurableRegistryError::Unavailable)));
        }
        assert!(!path.join("registry.lock").exists());
        assert!(!path.join("registry.json").exists());
        if fault == "blocked-staging" {
            std::fs::remove_dir(path.join("registry.next")).must("restore staging availability");
        }
        let owner = DurablePromptRegistry::open_state_dir(&path, 64).must("retry initialization");
        assert_eq!(owner.registry().must("registry"), &core);
    }
}

#[test]
fn concurrent_bootstrap_cannot_create_or_steal_a_marker_before_owner_locking() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    // Hold precisely the bootstrap boundary before the marker is created.
    let directory = prepare_directory(&path).must("directory");
    directory.try_lock().must("bootstrap owner");
    assert!(matches!(
        Store::open(&path, /*maximum_records*/ 64),
        Err(DurableRegistryError::StateLocked)
    ));
    assert!(!path.join("registry.lock").exists());
    assert!(!path.join("registry.json").exists());
    drop(directory);
    let owner = DurablePromptRegistry::open_state_dir(&path, 64).must("complete bootstrap");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&path, 64),
        Err(DurableRegistryError::StateLocked)
    ));
    drop(owner);
    DurablePromptRegistry::open_state_dir(&path, 64).must("reopen committed owner");
}

#[test]
fn indeterminate_initialization_and_deleted_committed_state_retain_the_owner_marker() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let (store, _) = Store::open(&path, /*maximum_records*/ 64).must("fresh owner");
    store.fail_directory_sync_after_rename_once.set(true);
    assert!(matches!(
        store.initialize(&PromptRegistry::new(64).must("core")),
        Err(DurableRegistryError::IndeterminateDurability)
    ));
    assert!(path.join("registry.lock").exists());
    assert!(path.join("registry.json").exists());
    drop(DurablePromptRegistry::open_state_dir(&path, 64).must("reconcile initialization"));
    std::fs::remove_file(path.join("registry.json")).must("simulate lost committed state");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&path, 64),
        Err(DurableRegistryError::Corrupt)
    ));
    assert!(path.join("registry.lock").exists());
}

#[test]
#[cfg(target_os = "linux")]
fn fifo_state_file_is_rejected_without_waiting_for_a_writer() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let directory = prepare_directory(&path).must("directory");
    rustix::fs::mkfifoat(
        &directory,
        "registry.json",
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
    )
    .must("FIFO state file");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&path, 64),
        Err(DurableRegistryError::UnsafeStateDirectory)
    ));
}

#[test]
fn repeated_json_members_are_rejected_at_every_storage_level() {
    for fault in ["top-level", "state", "factor", "reference"] {
        let temp = tempfile::tempdir().must("temp");
        let path = temp.path().join("owner");
        let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
        owner
            .commit(|core| super::payload_tests::add_payload(core, 0))
            .must("payload");
        drop(owner);
        let manifest = path.join("registry.json");
        let text = String::from_utf8(std::fs::read(&manifest).must("manifest")).must("UTF-8");
        let malformed = match fault {
            "top-level" => text.replacen("\"schema\":3", "\"schema\":3,\"schema\":3", 1),
            "state" => text.replacen("\"revision\":4", "\"revision\":4,\"revision\":4", 1),
            "factor" => text.replacen("\"source\":0", "\"source\":0,\"source\":0", 1),
            "reference" => {
                text.replacen("\"length\":16384", "\"length\":16384,\"length\":16384", 1)
            }
            _ => unreachable!(),
        };
        assert_ne!(
            malformed, text,
            "fixture must introduce {fault} duplication"
        );
        std::fs::write(&manifest, malformed.as_bytes()).must("ambiguous manifest");
        let payload_path = path.join(payloads::FILE_NAME);
        let original_payloads = std::fs::read(&payload_path).must("payloads");
        assert!(matches!(
            DurablePromptRegistry::open_state_dir(&path, 64),
            Err(DurableRegistryError::Corrupt)
        ));
        assert_eq!(
            std::fs::read(&manifest).must("manifest"),
            malformed.as_bytes()
        );
        assert_eq!(
            std::fs::read(&payload_path).must("payloads"),
            original_payloads
        );
    }
}

#[test]
fn active_profiles_with_distinct_model_names_or_versions_survive_restart() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
    owner
        .commit(|core| {
            registered_and_admitted(core, 0);
            for (index, (model_name, model_version)) in [
                ("model:primary", "v1"),
                ("model:primary", "v2"),
                ("model:alias", "v1"),
            ]
            .into_iter()
            .enumerate()
            {
                let payload = format!("profile {index}").into_bytes();
                core.register_realization_payload_v2(
                    PromptRealizationBindingV2 {
                        realization_id: id(&format!("realization:profile:{index}")),
                        factor_id: factor(0).factor_id,
                        model_id: id(model_name),
                        model_version: model_version.into(),
                        model_digest: digest("shared-model-bytes"),
                        tokenizer_digest: digest("tokenizer"),
                        template_digest: digest("template"),
                        tool_schema_digest: digest("tools"),
                        context_profile_digest: digest("context"),
                        locale_id: id("en-US"),
                        role: PromptRoleV2::DeveloperInstruction,
                        payload_digest: Digest32::of_bytes(&payload),
                        token_cost: 4,
                        expires_unix_ms: None,
                    },
                    payload,
                    None,
                )?;
            }
            Ok(core.receipt(crate::MutationDisposition::Inserted))
        })
        .must("distinct profiles");
    let expected = owner.registry().must("registry").clone();
    drop(owner);
    let reopened = DurablePromptRegistry::open_state_dir(&path, 64).must("reopen profiles");
    assert_eq!(reopened.registry().must("registry"), &expected);
}

#[test]
fn checksummed_lifecycle_images_cannot_bypass_historical_owner_rules() {
    for fault in [
        "self-review",
        "external-history",
        "registered-actor",
        "registered-evidence",
        "scope-without-grant",
        "zero-scope",
        "admission-reason",
        "revocation-without-cutoff",
        "zero-content",
        "shared-native-revision",
        "import-after-native",
        "reused-grant",
    ] {
        let mut core = PromptRegistry::new(64).must("core");
        registered_and_admitted(&mut core, 0);
        core.revoke_factor_governed(&factor(0).factor_id, &id("operator"), digest("reason"), 9)
            .must("revocation fixture");
        match fault {
            "self-review" => core.lifecycle_events[1].actor_id = factor(0).proposer_id,
            "external-history" => {
                core.factors
                    .get_mut(&factor(0).factor_id)
                    .must("factor")
                    .source = FactorSource::ExternalUntrusted;
            }
            "registered-actor" => core.lifecycle_events[0].actor_id = id("other-proposer"),
            "registered-evidence" => core.lifecycle_events[0].evidence_digest = digest("other"),
            "scope-without-grant" => core.lifecycle_events[1].scope_digest = Some(digest("scope")),
            "zero-scope" => {
                core.lifecycle_events[1].admission_grant_id = Some(id("grant"));
                core.lifecycle_events[1].scope_digest = Some(Digest32::ZERO);
            }
            "admission-reason" => core.lifecycle_events[1].reason_digest = Some(digest("reason")),
            "revocation-without-cutoff" => core.lifecycle_events[2].cutoff_unix_ms = None,
            "zero-content" => {
                core.factors
                    .get_mut(&factor(0).factor_id)
                    .must("factor")
                    .content_digest = Digest32::ZERO;
                core.lifecycle_events[0].evidence_digest = Digest32::ZERO;
                core.lifecycle_events[2].evidence_digest = Digest32::ZERO;
            }
            "shared-native-revision" => {
                core.lifecycle_events[1].revision = core.lifecycle_events[0].revision;
            }
            "import-after-native" => {
                core.register_factor(factor(1)).must("later factor");
                let event = core.lifecycle_events.last_mut().must("later event");
                event.kind = LifecycleEventKind::Imported;
                event.actor_id = id("migration:v1");
                event.reason_digest = Some(Digest32::of_bytes(MIGRATION_REASON_DOMAIN));
            }
            "reused-grant" => {
                registered_and_admitted(&mut core, 1);
                for event in &mut core.lifecycle_events {
                    if event.kind == LifecycleEventKind::Admitted {
                        event.admission_grant_id = Some(id("grant:repeated"));
                        event.scope_digest = Some(digest("scope"));
                    }
                }
            }
            _ => unreachable!(),
        }
        for event in &mut core.lifecycle_events {
            event.event_digest = event.compute_digest();
        }
        assert!(
            matches!(
                restore_v2(stored_v2(&core), 64),
                Err(DurableRegistryError::Corrupt)
            ),
            "{fault}"
        );
    }
}

#[test]
fn unrepresentable_relation_state_is_rejected_before_any_publication() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
    owner
        .commit(|core| super::payload_tests::add_payload(core, 0))
        .must("initial");
    let before = std::fs::read(path.join("registry.json")).must("manifest");
    let expected = owner.registry().must("registry").clone();
    assert!(matches!(
        owner.commit(|core| {
            registered_and_admitted(core, 1);
            core.register_factor_relation(crate::PromptFactorRelation {
                relation_id: id("relation:test"),
                left_factor_id: id("factor:0"),
                right_factor_id: factor(1).factor_id,
                kind: crate::PromptFactorRelationKind::Complements,
                evidence_digest: digest("relation-evidence"),
            })
        }),
        Err(DurableRegistryError::Corrupt)
    ));
    assert_eq!(owner.registry().must("registry"), &expected);
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("manifest"),
        before
    );
}

#[test]
fn long_supersession_lineage_restores_and_a_checksummed_cycle_is_rejected() {
    let mut core = PromptRegistry::new(1024).must("core");
    super::payload_tests::add_payload(&mut core, 0).must("initial realization");
    let initial = id("realization:0");
    let template = core.realization_binding(&initial).must("binding").clone();
    let payload = b"bounded successor payload".to_vec();
    let mut previous = initial.clone();
    for index in 1..=512 {
        let mut binding = template.clone();
        binding.realization_id = id(&format!("realization:lineage:{index:04}"));
        binding.payload_digest = Digest32::of_bytes(&payload);
        let next = binding.realization_id.clone();
        core.register_realization_payload_v2(binding, payload.clone(), Some(previous))
            .must("supersede immutable realization");
        previous = next;
    }
    assert_eq!(
        restore_v2(stored_v2(&core), 1024).must("long lineage"),
        core
    );
    core.retire_factor_governed(&id("factor:0"), &id("operator"), digest("retirement"))
        .must("deactivate terminal realization");
    assert_eq!(
        restore_v2(stored_v2(&core), 1024).must("retired lineage"),
        core
    );
    // Every predecessor is now inactive and unique, so only graph traversal can
    // distinguish this forged, self-consistently checksummed image from history.
    core.realization_supersessions.insert(initial, previous);
    assert!(matches!(
        restore_v2(stored_v2(&core), 1024),
        Err(DurableRegistryError::Corrupt)
    ));
}
