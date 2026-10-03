//! Live-owner media-integrity regressions using only disposable local fixtures.

use std::io::Seek;
use std::io::SeekFrom;

use super::*;
use crate::TestMust;

fn model() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_id: StableId::new("model:test").must("model"),
        model_version: "v1".into(),
        model_digest: Digest32::of_bytes(b"model"),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
        template_digest: Digest32::of_bytes(b"template"),
        tool_schema_digest: Digest32::of_bytes(b"tools"),
        context_profile_digest: Digest32::of_bytes(b"context"),
        locale_id: StableId::new("en-US").must("locale"),
    }
}

#[test]
fn selected_payload_corruption_rejects_later_metadata_commit_without_writes() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner =
        DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 64).must("owner");
    owner
        .commit(|core| payload_tests::add_payload(core, /*index*/ 0))
        .must("seed selected payload");
    let manifest = std::fs::read(path.join("registry.json")).must("selected manifest");
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .open(path.join(payloads::FILE_NAME))
        .must("disposable payload");
    file.seek(SeekFrom::Start(64)).must("selected byte");
    file.write_all(b"changed!").must("change selected bytes");
    file.sync_all().must("sync fault");
    let payload = std::fs::read(path.join(payloads::FILE_NAME)).must("faulted payload");

    assert!(matches!(
        owner.commit(|core| payload_tests::add_payload(core, /*index*/ 1)),
        Err(DurableRegistryError::Corrupt)
    ));
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("manifest"),
        manifest
    );
    assert_eq!(
        std::fs::read(path.join(payloads::FILE_NAME)).must("payload"),
        payload
    );
    assert!(owner.requires_reopen());
}

#[test]
fn missing_selected_manifest_rejects_live_authoritative_read() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let owner = DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 64).must("owner");
    std::fs::remove_file(path.join("registry.json")).must("remove disposable manifest");
    assert!(owner.registry().is_err());
    assert!(owner.requires_reopen());
    assert!(!path.join("registry.json").exists());
}

#[test]
fn every_live_read_boundary_rejects_changed_selected_bytes() {
    for port in ["registry", "anchor", "snapshot", "compatible", "delivery"] {
        let temp = tempfile::tempdir().must("temp");
        let path = temp.path().join("owner");
        let mut owner =
            DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 64).must("owner");
        owner
            .commit(|core| payload_tests::add_payload(core, /*index*/ 0))
            .must("payload");
        let generation = Digest32::of_bytes(b"generation");
        let model = model();
        let snapshot = owner.snapshot_v2(generation, &model).must("snapshot");
        let manifest_path = path.join("registry.json");
        let original = std::fs::read(&manifest_path).must("manifest");
        let mut changed = original.clone();
        changed.push(b' '); // Still valid JSON, but not this owner's selected bytes.
        std::fs::write(&manifest_path, &changed).must("change disposable manifest");
        let result = match port {
            "registry" => owner.registry().map(|_| ()),
            "anchor" => owner.recovery_anchor().map(|_| ()),
            "snapshot" => owner.snapshot_v2(generation, &model).map(|_| ()),
            "compatible" => owner
                .read_compatible_v2(
                    &snapshot,
                    generation,
                    &model,
                    /*now_unix_ms*/ 1,
                    vec![],
                    /*maximum_results*/ 4,
                )
                .map(|_| ()),
            "delivery" => owner
                .dereference_realization_v2(
                    &StableId::new("realization:0").must("realization"),
                    &snapshot,
                    generation,
                    &model,
                    /*now_unix_ms*/ 1,
                )
                .map(|_| ()),
            _ => unreachable!(),
        };
        assert!(
            matches!(result, Err(DurableRegistryError::Corrupt)),
            "{port}"
        );
        assert_eq!(
            std::fs::read(&manifest_path).must("retained fault"),
            changed
        );
        assert!(owner.requires_reopen());
        std::fs::write(&manifest_path, original).must("restore fixture bytes");
        assert!(matches!(
            owner.registry(),
            Err(DurableRegistryError::ReopenRequired)
        ));
        drop(owner);
        let reopened = DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 64)
            .must("explicit reopen");
        assert_eq!(
            reopened.snapshot_v2(generation, &model).must("snapshot"),
            snapshot
        );
    }
}

#[test]
fn missing_truncated_and_bad_header_payloads_poison_before_noop_mutation() {
    for fault in ["missing", "truncated", "header"] {
        let temp = tempfile::tempdir().must("temp");
        let path = temp.path().join("owner");
        let mut owner =
            DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 64).must("owner");
        owner
            .commit(|core| payload_tests::add_payload(core, /*index*/ 0))
            .must("payload");
        let payload_path = path.join(payloads::FILE_NAME);
        let original = std::fs::read(&payload_path).must("payload");
        match fault {
            "missing" => std::fs::remove_file(&payload_path).must("remove fixture"),
            "truncated" => std::fs::write(&payload_path, &original[..64]).must("truncate fixture"),
            "header" => {
                let mut changed = original;
                changed[0] ^= 1;
                std::fs::write(&payload_path, changed).must("change header");
            }
            _ => unreachable!(),
        }
        let payload = std::fs::read(&payload_path).ok();
        let manifest = std::fs::read(path.join("registry.json")).must("manifest");
        let ran = Cell::new(false);
        assert!(
            owner
                .commit(|core| {
                    ran.set(true);
                    Ok(core.receipt(crate::MutationDisposition::Unchanged))
                })
                .is_err(),
            "{fault}"
        );
        assert!(!ran.get(), "{fault}");
        assert!(owner.requires_reopen());
        assert_eq!(std::fs::read(&payload_path).ok(), payload);
        assert_eq!(
            std::fs::read(path.join("registry.json")).must("manifest"),
            manifest
        );
    }
}

#[test]
fn self_consistent_manifest_rollback_cannot_be_overwritten_by_live_owner() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner =
        DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 64).must("owner");
    let old = std::fs::read(path.join("registry.json")).must("old valid manifest");
    owner
        .commit(|core| payload_tests::add_payload(core, /*index*/ 0))
        .must("payload");
    let payload = std::fs::read(path.join(payloads::FILE_NAME)).must("payload");
    std::fs::write(path.join("registry.json"), &old).must("restore older valid fixture");
    assert!(matches!(
        owner.commit(|core| payload_tests::add_payload(core, /*index*/ 1)),
        Err(DurableRegistryError::Corrupt)
    ));
    assert!(owner.requires_reopen());
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("manifest"),
        old
    );
    assert_eq!(
        std::fs::read(path.join(payloads::FILE_NAME)).must("payload"),
        payload
    );
}

#[test]
fn unselected_tail_remains_unmodified_by_reads_and_unchanged_retries() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner =
        DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 64).must("owner");
    owner
        .commit(|core| payload_tests::add_payload(core, /*index*/ 0))
        .must("payload");
    let expected = owner.registry().must("registry").clone();
    let payload_path = path.join(payloads::FILE_NAME);
    let mut file = std::fs::OpenOptions::new()
        .append(true)
        .open(&payload_path)
        .must("payload");
    file.write_all(b"unselected partial next payload")
        .must("orphan tail");
    file.sync_all().must("sync tail");
    let payload = std::fs::read(&payload_path).must("payload plus tail");
    assert_eq!(
        owner.registry().must("selected prefix remains intact"),
        &expected
    );
    owner
        .commit(|core| Ok(core.receipt(crate::MutationDisposition::Unchanged)))
        .must("unchanged retry");
    assert!(!owner.requires_reopen());
    assert_eq!(
        std::fs::read(&payload_path).must("unmodified tail"),
        payload
    );
    owner
        .commit(|core| payload_tests::add_payload(core, /*index*/ 1))
        .must("publish new selected extent");
    let committed = owner.registry().must("registry").clone();
    drop(owner);
    assert_eq!(
        DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 64)
            .must("reopen")
            .registry()
            .must("registry"),
        &committed
    );
}

#[test]
fn first_integrity_rejection_preserves_the_unclaimed_final_use_grant() {
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner =
        DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 64).must("owner");
    owner
        .commit(|core| payload_tests::add_payload(core, /*index*/ 0))
        .must("payload");
    let mut factor = owner
        .registry()
        .must("registry")
        .factor(&StableId::new("factor:0").must("factor"))
        .must("factor")
        .clone();
    factor.factor_id = StableId::new("factor:pending").must("pending factor");
    factor.lifecycle = Lifecycle::Draft;
    owner.register_factor(factor.clone()).must("pending factor");
    let key = SigningKey::from_bytes(&[81; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &temp.path().join("authority"),
        "fixture-owner".into(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .must("local fixture authority");
    let scope = Digest32::of_bytes(b"reviewed scope");
    let evidence = Digest32::of_bytes(b"review evidence");
    let binding = crate::final_use_admission_binding(
        &factor,
        &StableId::new("reviewer:independent").must("reviewer"),
        scope,
        evidence,
    )
    .must("binding");
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .must("clock")
            .as_millis(),
    )
    .must("time");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "fixture-owner".into(),
        authority_epoch: 1,
        grant_id: "grant:live-integrity".into(),
        nonce: [81; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: key
            .sign(&grant.signing_bytes().must("grant bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    let manifest_path = path.join("registry.json");
    let original = std::fs::read(&manifest_path).must("manifest");
    let mut changed = original.clone();
    changed.push(b' ');
    std::fs::write(&manifest_path, &changed).must("change fixture");
    assert!(matches!(
        owner.admit_factor_final_use(&authority, &signed, &factor.factor_id, scope, evidence),
        Err(DurableRegistryError::Corrupt)
    ));
    assert_eq!(
        std::fs::read(&manifest_path).must("retained fixture"),
        changed
    );
    std::fs::write(&manifest_path, original).must("restore fixture");
    assert!(matches!(
        owner.admit_factor_final_use(&authority, &signed, &factor.factor_id, scope, evidence),
        Err(DurableRegistryError::ReopenRequired)
    ));
    drop(owner);
    let mut reopened = DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 64)
        .must("explicit reopen");
    reopened
        .admit_factor_final_use(&authority, &signed, &factor.factor_id, scope, evidence)
        .must("same grant was not consumed by either rejection");
}

#[test]
fn live_integrity_read_cost_is_reported_for_one_mib_selected_payload() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner =
        DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 512).must("owner");
    owner
        .commit(|core| {
            for index in 0..64 {
                payload_tests::add_payload(core, index)?;
            }
            Ok(core.receipt(crate::MutationDisposition::Inserted))
        })
        .must("one MiB selected payload");
    let manifest_before = std::fs::read(path.join("registry.json")).must("manifest");
    let payload_before = std::fs::read(path.join(payloads::FILE_NAME)).must("payload");
    let started = std::time::Instant::now();
    for _ in 0..8 {
        owner.registry().must("validated read");
    }
    let elapsed = started.elapsed().as_micros();
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("manifest"),
        manifest_before
    );
    assert_eq!(
        std::fs::read(path.join(payloads::FILE_NAME)).must("payload"),
        payload_before
    );
    eprintln!(
        "PREG_LIVE_INTEGRITY reads=8 payload_bytes=1048576 manifest_bytes={} total_us={elapsed} rewritten_bytes=0",
        manifest_before.len()
    );
}
