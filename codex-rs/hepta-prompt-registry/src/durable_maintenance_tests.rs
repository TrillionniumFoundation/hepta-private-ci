use super::*;
use crate::FactorSource;
use crate::Lifecycle;
use crate::LifecycleEvent;
use crate::LifecycleEventKind;
use crate::PromptFactor;
use crate::PromptModelTupleV2;
use crate::PromptRealizationBindingV2;
use crate::PromptRoleV2;
use crate::RegistryReceipt;
use crate::TestMust;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use std::io::Seek;
use std::io::SeekFrom;
use std::time::Instant;

fn id(value: &str) -> StableId {
    StableId::new(value).must("test identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn factor(index: usize) -> PromptFactor {
    PromptFactor {
        factor_id: id(&format!("factor:{index}")),
        proposer_id: id("proposer:test"),
        semantic_version: id("v1"),
        semantic_purpose: "prompt registry operations test".into(),
        authority_class: "registered_prompt_factor".into(),
        eligible_objective_dimensions: vec![id("dimension:quality")],
        content_digest: digest(&format!("factor-content:{index}")),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    }
}

fn model_tuple() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_id: id("model:test"),
        model_version: "v1".into(),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        context_profile_digest: digest("context"),
        locale_id: id("en-US"),
    }
}

pub(in crate::durable) fn add_payload(
    core: &mut PromptRegistry,
    index: usize,
) -> Result<RegistryReceipt, crate::Error> {
    let factor = factor(index);
    let factor_id = factor.factor_id.clone();
    core.register_factor(factor)?;
    core.admit_factor(&factor_id, &id("reviewer:test"), digest("review-evidence"))?;
    let payload = vec![65 + u8::try_from(index % 26).unwrap_or(0); 16 * 1024];
    core.register_realization_payload_v2(
        PromptRealizationBindingV2 {
            realization_id: id(&format!("realization:{index}")),
            factor_id,
            model_id: id("model:test"),
            model_version: "v1".into(),
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tools"),
            context_profile_digest: digest("context"),
            locale_id: id("en-US"),
            role: PromptRoleV2::DeveloperInstruction,
            payload_digest: Digest32::of_bytes(&payload),
            token_cost: 4096,
            expires_unix_ms: None,
        },
        payload,
        None,
    )
}

pub(in crate::durable) fn seeded(path: &Path) -> DurablePromptRegistry {
    let mut owner = DurablePromptRegistry::open_state_dir(path, 64).must("owner");
    owner.commit(|core| add_payload(core, 0)).must("payload");
    owner
}

#[test]
fn operational_consistent_export_reopens_exactly() {
    let temporary = tempfile::tempdir().must("tempdir");
    let owner = seeded(&temporary.path().join("source"));
    let destination = temporary.path().join("export");
    let receipt = owner
        .export_consistent_checkpoint(&destination)
        .must("export");
    assert_eq!(
        receipt.source_registry_digest,
        receipt.checkpoint_registry_digest
    );
    assert_eq!(
        receipt.source_history_digest,
        receipt.checkpoint_history_digest
    );
    assert!(!receipt.source_erased);
    let metadata_before = std::fs::read(destination.join("registry.json")).must("metadata");
    let payload_before = std::fs::read(destination.join(payloads::FILE_NAME)).must("payload");
    let restored = DurablePromptRegistry::verify_restore_checkpoint(
        &destination,
        64,
        Some(receipt.checkpoint_revision),
        Some(receipt.checkpoint_registry_digest),
    )
    .must("verify");
    assert!(restored.verified);
    assert_eq!(
        metadata_before,
        std::fs::read(destination.join("registry.json")).must("metadata")
    );
    assert_eq!(
        payload_before,
        std::fs::read(destination.join(payloads::FILE_NAME)).must("payload")
    );
}

#[test]
fn operational_compacted_checkpoint_reclaims_only_inactive_payloads() {
    let temporary = tempfile::tempdir().must("tempdir");
    let mut owner = seeded(&temporary.path().join("source"));
    owner
        .commit(|core| add_payload(core, 1))
        .must("second payload");
    owner
        .retire_factor(&id("factor:0"), &id("operator:test"), digest("retire"))
        .must("retire");
    let before = owner.registry().must("registry").clone();
    let destination = temporary.path().join("compacted");
    let receipt = owner.checkpoint_compacted(&destination).must("compact");
    assert_eq!(receipt.reclaimed_payload_records, 1);
    assert_eq!(receipt.reclaimed_payload_bytes, 16 * 1024);
    assert_eq!(receipt.checkpoint_payload_records, 1);
    assert_eq!(
        receipt.source_history_digest,
        receipt.checkpoint_history_digest
    );
    assert!(!receipt.source_erased);
    assert_eq!(owner.registry().must("source unchanged"), &before);
    let checkpoint = load_strict_checkpoint(&destination, 64).must("read checkpoint");
    assert_eq!(checkpoint.registry.factors, before.factors);
    assert_eq!(checkpoint.registry.relations, before.relations);
    assert_eq!(
        checkpoint.registry.lifecycle_events,
        before.lifecycle_events
    );
    assert!(
        !checkpoint
            .registry
            .realization_payloads
            .contains_key(&id("realization:0"))
    );
    assert_eq!(
        checkpoint
            .registry
            .realization_payloads
            .get(&id("realization:1")),
        before.realization_payloads.get(&id("realization:1"))
    );
}

#[test]
fn operational_compaction_retry_is_idempotent_and_conflicting_destination_is_untouched() {
    let temporary = tempfile::tempdir().must("tempdir");
    let mut owner = seeded(&temporary.path().join("source"));
    let destination = temporary.path().join("checkpoint");
    let first = owner.checkpoint_compacted(&destination).must("first");
    let second = owner.checkpoint_compacted(&destination).must("retry");
    assert_eq!(first, second);
    let before = std::fs::read(destination.join("registry.json")).must("metadata");
    owner
        .retire_factor(&id("factor:0"), &id("operator:test"), digest("retire"))
        .must("retire");
    assert!(owner.checkpoint_compacted(&destination).is_err());
    assert_eq!(
        before,
        std::fs::read(destination.join("registry.json")).must("unchanged")
    );
}

#[test]
fn operational_restore_does_not_create_missing_paths_or_accept_unpinned_identity() {
    let temporary = tempfile::tempdir().must("tempdir");
    let missing = temporary.path().join("missing");
    assert!(matches!(
        DurablePromptRegistry::verify_restore_checkpoint(&missing, 64, None, None),
        Err(PromptRegistryMaintenanceError::RestoreIdentityRequired)
    ));
    assert!(
        DurablePromptRegistry::verify_restore_checkpoint(&missing, 64, Some(1), Some([1; 32]))
            .is_err()
    );
    assert!(!missing.exists());
}

#[test]
fn operational_partial_checkpoint_and_symlink_are_never_overwritten() {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::symlink;

    let temporary = tempfile::tempdir().must("tempdir");
    let owner = seeded(&temporary.path().join("source"));
    let partial = temporary.path().join("partial");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&partial)
        .must("partial dir");
    std::fs::write(partial.join("registry.next"), b"incomplete-checkpoint").must("partial bytes");
    assert!(owner.export_consistent_checkpoint(&partial).is_err());
    assert!(!partial.join("registry.lock").exists());
    assert_eq!(
        std::fs::read(partial.join("registry.next")).must("partial preserved"),
        b"incomplete-checkpoint"
    );
    let alias = temporary.path().join("alias");
    symlink(&partial, &alias).must("symlink");
    assert!(owner.export_consistent_checkpoint(&alias).is_err());
    assert!(!partial.join("registry.json").exists());
}

#[test]
fn operational_stale_restore_is_rejected_after_revocation() {
    let temporary = tempfile::tempdir().must("tempdir");
    let mut owner = seeded(&temporary.path().join("source"));
    let backup = temporary.path().join("old-backup");
    owner.export_consistent_checkpoint(&backup).must("backup");
    owner
        .revoke_factor(&id("factor:0"), &id("operator:test"), digest("revoke"), 100)
        .must("revoke");
    let metrics = owner.operational_metrics().must("current identity");
    assert!(matches!(
        DurablePromptRegistry::verify_restore_checkpoint(
            &backup,
            64,
            Some(metrics.revision),
            Some(metrics.registry_digest)
        ),
        Err(PromptRegistryMaintenanceError::CheckpointVerificationMismatch)
    ));
    let current = temporary.path().join("current");
    let receipt = owner.checkpoint_compacted(&current).must("compact revoked");
    let restored = load_strict_checkpoint(&current, 64).must("restore");
    assert_eq!(
        restored
            .registry
            .factor(&id("factor:0"))
            .must("factor")
            .lifecycle,
        Lifecycle::Revoked
    );
    assert_eq!(
        receipt.source_history_digest,
        receipt.checkpoint_history_digest
    );
}

#[test]
fn operational_metrics_unify_logical_payload_and_byte_quotas() {
    let temporary = tempfile::tempdir().must("tempdir");
    let mut owner = seeded(&temporary.path().join("source"));
    owner
        .retire_factor(&id("factor:0"), &id("operator:test"), digest("retire"))
        .must("retire");
    let metrics = owner.operational_metrics().must("metrics");
    assert!(metrics.authoritative);
    assert_eq!(metrics.reclaimable_payload_records, 1);
    assert_eq!(metrics.reclaimable_payload_bytes, 16 * 1024);
    assert_eq!(metrics.oldest_reclaimable_age_ms, None);
    assert_eq!(metrics.remaining_logical_records, 62);
    assert_eq!(metrics.quota.maximum_full_sized_payload_records, 512);
    assert_eq!(
        metrics.remaining_payload_bytes + metrics.physical_payload_file_bytes,
        metrics.quota.maximum_payload_file_bytes
    );
}

#[test]
fn operational_poisoned_owner_exposes_diagnostics_but_not_authority() {
    let temporary = tempfile::tempdir().must("tempdir");
    let mut owner = seeded(&temporary.path().join("source"));
    owner.fail_directory_sync_after_rename_once();
    assert!(matches!(
        owner.register_factor(factor(1)),
        Err(DurableRegistryError::IndeterminateDurability)
    ));
    let metrics = owner.operational_metrics().must("poisoned diagnostics");
    assert!(metrics.requires_reopen);
    assert!(!metrics.authoritative);
    assert!(owner.registry().is_err());
    assert!(
        owner
            .export_consistent_checkpoint(&temporary.path().join("forbidden"))
            .is_err()
    );
}

#[test]
fn operational_fsync_probe_is_bounded_and_cleans_up() {
    let temporary = tempfile::tempdir().must("tempdir");
    let directory = temporary.path().join("probe");
    let receipt = DurablePromptRegistry::probe_fsync(&directory, 4096).must("probe");
    assert_eq!(receipt.bytes, 4096);
    assert!(
        std::fs::read_dir(&directory)
            .must("read dir")
            .next()
            .is_none()
    );
    assert!(DurablePromptRegistry::probe_fsync(&directory, 0).is_err());
    assert!(DurablePromptRegistry::probe_fsync(&directory, 1024 * 1024 + 1).is_err());
}

#[test]
fn operational_unrenamed_metadata_is_never_selected() {
    let temporary = tempfile::tempdir().must("tempdir");
    let source = temporary.path().join("source");
    let owner = seeded(&source);
    let expected = owner.registry().must("registry").clone();
    let mut staged = open_private(&owner.store.root, "registry.next", Access::Create).must("next");
    staged.write_all(b"incomplete-next-image").must("write");
    staged.sync_all().must("sync");
    drop(staged);
    drop(owner);
    let reopened = DurablePromptRegistry::open_state_dir(&source, 64).must("reopen");
    assert_eq!(reopened.registry().must("registry"), &expected);
}

#[test]
fn operational_orphan_payload_tail_reconciliation_is_idempotent() {
    let temporary = tempfile::tempdir().must("tempdir");
    let source = temporary.path().join("source");
    let owner = seeded(&source);
    let expected = owner.registry().must("registry").clone();
    let committed = file_bytes(&owner.store, payloads::FILE_NAME).must("length");
    let mut file =
        open_private(&owner.store.root, payloads::FILE_NAME, Access::Create).must("payload file");
    file.seek(SeekFrom::End(0)).must("seek");
    file.write_all(b"orphan-tail").must("tail");
    file.sync_all().must("sync");
    drop(file);
    drop(owner);
    for _ in 0..2 {
        let reopened = DurablePromptRegistry::open_state_dir(&source, 64).must("reopen");
        assert_eq!(reopened.registry().must("registry"), &expected);
        assert_eq!(
            file_bytes(&reopened.store, payloads::FILE_NAME).must("length"),
            committed
        );
    }
}

fn large_registry(count: usize) -> PromptRegistry {
    let mut registry = PromptRegistry::new(16_384).must("registry");
    for index in 0..count {
        let factor = factor(index);
        let revision = Revision::new(u64::try_from(index).must("index") + 2).must("revision");
        let mut event = LifecycleEvent {
            revision,
            factor_id: factor.factor_id.clone(),
            kind: LifecycleEventKind::Registered,
            from: None,
            to: Lifecycle::Draft,
            actor_id: factor.proposer_id.clone(),
            admission_grant_id: None,
            evidence_digest: factor.content_digest,
            scope_digest: None,
            reason_digest: None,
            cutoff_unix_ms: None,
            event_digest: Digest32::ZERO,
        };
        event.event_digest = event.compute_digest();
        registry.factors.insert(factor.factor_id.clone(), factor);
        registry.lifecycle_events.push(event);
    }
    registry.revision = Revision::new(u64::try_from(count).must("count") + 1).must("revision");
    registry.lifecycle_frontier = registry.revision.get();
    validate_restored(&registry).must("fixture integrity");
    registry
}

fn distribution(mut samples: Vec<u128>) -> serde_json::Value {
    samples.sort_unstable();
    let quantile =
        |percent: usize| samples[(samples.len() * percent).div_ceil(100).saturating_sub(1)];
    serde_json::json!({"samples": samples.len(), "p50Nanos": quantile(50), "p95Nanos": quantile(95), "p99Nanos": quantile(99), "maxNanos": samples.last()})
}

#[test]
#[ignore = "qualification operational profile; diagnostic, not production SLA"]
fn operational_scale_profile_1k_8k_16k() {
    for count in [1000_usize, 8000, 16_384] {
        let temporary = tempfile::tempdir().must("tempdir");
        let path = temporary.path().join("source");
        let fixture_started = Instant::now();
        let mut registry = large_registry(count - 3);
        add_payload(&mut registry, count + 1).must("profile payload");
        let fixture_nanos = fixture_started.elapsed().as_nanos();
        let persist_started = Instant::now();
        let (mut store, _) = Store::open(&path).must("store");
        store.persist(&registry).must("initial persist");
        drop(store);
        let initial_persist_nanos = persist_started.elapsed().as_nanos();
        let reopen_started = Instant::now();
        let mut owner = DurablePromptRegistry::open_state_dir(&path, 16_384).must("reopen");
        let reopen_nanos = reopen_started.elapsed().as_nanos();
        let register_started = Instant::now();
        owner
            .register_factor(factor(count + 2))
            .must("measured durable register");
        let register_nanos = register_started.elapsed().as_nanos();
        let model = model_tuple();
        let generation = digest("profile-generation");
        let mut snapshots = Vec::new();
        let mut dereferences = Vec::new();
        for _ in 0..31 {
            let started = Instant::now();
            let snapshot = owner.snapshot_v2(generation, &model).must("snapshot");
            snapshots.push(started.elapsed().as_nanos());
            let started = Instant::now();
            std::hint::black_box(
                owner
                    .dereference_realization_v2(
                        &id(&format!("realization:{}", count + 1)),
                        &snapshot,
                        generation,
                        &model,
                        1,
                    )
                    .must("dereference"),
            );
            dereferences.push(started.elapsed().as_nanos());
        }
        let update_started = Instant::now();
        owner
            .retire_factor(
                &id(&format!("factor:{}", count + 1)),
                &id("operator:test"),
                digest("retire"),
            )
            .must("lifecycle update");
        let lifecycle_update_nanos = update_started.elapsed().as_nanos();
        let metrics = owner.operational_metrics().must("metrics");
        let compact_started = Instant::now();
        let receipt = owner
            .checkpoint_compacted(&temporary.path().join("checkpoint"))
            .must("checkpoint");
        let compaction_nanos = compact_started.elapsed().as_nanos();
        let gc = owner.collect_payload_garbage().must("in-place collection");
        let after_gc = owner.operational_metrics().must("post-collection metrics");
        assert_eq!(gc.collected_payload_records, 1);
        assert!(!gc.cleanup_pending);
        let vm_hwm = std::fs::read_to_string("/proc/self/status")
            .ok()
            .and_then(|text| {
                text.lines()
                    .find(|line| line.starts_with("VmHWM:"))
                    .map(str::to_owned)
            });
        println!(
            "{}",
            serde_json::json!({
                "schema": "hepta.prompt-registry.operational-scale.v2",
                "logicalRecords": count, "fixtureNanos": fixture_nanos,
                "initialPersistNanos": initial_persist_nanos, "reopenNanos": reopen_nanos,
                "durableRegisterNanos": register_nanos, "lifecycleUpdateNanos": lifecycle_update_nanos,
                "snapshot": distribution(snapshots), "dereference": distribution(dereferences),
                "compactionNanos": compaction_nanos, "metadataBytes": metrics.metadata_file_bytes,
                "inPlaceGc": gc, "afterGc": after_gc, "ioBeforeGc": metrics.io,
                "payloadFileBytes": metrics.physical_payload_file_bytes,
                "checkpointPayloadBytes": receipt.checkpoint_physical_payload_file_bytes,
                "processHighWaterMark": vm_hwm,
                "memoryScope": "process-lifetime; not per-operation allocation",
                "writeSampleCount": 1, "productionSla": false,
                "compileRenderFinalUseMeasured": false,
            })
        );
    }
}

#[test]
#[ignore = "qualification operational profile; diagnostic, not production SLA"]
fn operational_fsync_profile() {
    let temporary = tempfile::tempdir().must("tempdir");
    for bytes in [4096_u64, 64 * 1024, 1024 * 1024] {
        let directory = temporary.path().join(format!("probe-{bytes}"));
        let mut total = Vec::new();
        let mut file_sync = Vec::new();
        let mut directory_sync = Vec::new();
        for _ in 0..31 {
            let receipt = DurablePromptRegistry::probe_fsync(&directory, bytes).must("probe");
            total.push(receipt.total_nanos);
            file_sync.push(receipt.file_sync_nanos);
            directory_sync.push(receipt.directory_sync_nanos);
        }
        println!(
            "{}",
            serde_json::json!({"schema": "hepta.prompt-registry.fsync-profile.v2", "bytes": bytes, "total": distribution(total), "fileSync": distribution(file_sync), "directorySync": distribution(directory_sync), "productionSla": false})
        );
    }
}

#[test]
fn operational_restore_rejects_tail_without_repair_or_mutation() {
    let temporary = tempfile::tempdir().must("tempdir");
    let owner = seeded(&temporary.path().join("source"));
    let checkpoint = temporary.path().join("checkpoint");
    let receipt = owner
        .export_consistent_checkpoint(&checkpoint)
        .must("export");
    let root = open_existing_directory(&checkpoint).must("directory");
    let mut file = open_private(&root, payloads::FILE_NAME, Access::Create).must("file");
    file.seek(SeekFrom::End(0)).must("seek");
    file.write_all(b"must-not-silently-trim").must("tail");
    file.sync_all().must("sync");
    drop(file);
    let before = std::fs::read(checkpoint.join(payloads::FILE_NAME)).must("before");
    assert!(
        DurablePromptRegistry::verify_restore_checkpoint(
            &checkpoint,
            64,
            Some(receipt.checkpoint_revision),
            Some(receipt.checkpoint_registry_digest)
        )
        .is_err()
    );
    assert_eq!(
        std::fs::read(checkpoint.join(payloads::FILE_NAME)).must("after"),
        before
    );
}

#[test]
#[ignore = "qualification actual registration/update latency samples; not a production SLA"]
fn operational_writer_latency_profile() {
    for ceiling in [1000_usize, 8000, 16_384] {
        let temporary = tempfile::tempdir().must("tempdir");
        let path = temporary.path().join("source");
        let registry = large_registry(ceiling - 31);
        let (mut store, _) = Store::open(&path).must("store");
        store.persist(&registry).must("seed");
        drop(store);
        let mut owner = DurablePromptRegistry::open_state_dir(&path, 16_384).must("owner");
        let mut registrations = Vec::new();
        let mut retirements = Vec::new();
        for index in 0..31 {
            let candidate = factor(ceiling + index);
            let factor_id = candidate.factor_id.clone();
            let started = Instant::now();
            owner
                .register_factor(candidate)
                .must("durable registration");
            registrations.push(started.elapsed().as_nanos());
            owner
                .commit(|core| {
                    core.admit_factor(&factor_id, &id("reviewer:test"), digest("review"))
                })
                .must("admit outside measured update interval");
            let started = Instant::now();
            owner
                .retire_factor(&factor_id, &id("operator:test"), digest("retire"))
                .must("durable retirement");
            retirements.push(started.elapsed().as_nanos());
        }
        let metrics = owner.operational_metrics().must("writer metrics");
        assert_eq!(metrics.io.successful_publications, 93);
        println!(
            "{}",
            serde_json::json!({
                "schema": "hepta.prompt-registry.writer-profile.v1",
                "finalLogicalRecords": ceiling, "initialLogicalRecords": ceiling - 31,
                "registration": distribution(registrations), "retirement": distribution(retirements),
                "io": metrics.io, "metadataBytes": metrics.metadata_file_bytes,
                "productionSla": false, "includesAdmissionGrantVerification": false,
            })
        );
    }
}
