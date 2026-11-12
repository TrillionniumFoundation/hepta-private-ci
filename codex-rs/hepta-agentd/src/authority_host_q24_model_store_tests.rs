//! Actual protected CAS and durable file/witness recovery. Scope/proof data
//! is synthetic; these tests do not certify live writer or ordinary execution.

use super::*;
use pretty_assertions::assert_eq;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;

#[test]
#[ignore = "explicit actual Root and protected qualification parent"]
fn root_factory_record_reopens_bound_without_replacing_original_files() -> anyhow::Result<()> {
    // SAFETY: geteuid observes only the actual test process credential.
    anyhow::ensure!(
        unsafe { libc::geteuid() } == 0,
        "actual Root qualification required"
    );
    let parent = std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT")
        .ok_or_else(|| anyhow::anyhow!("explicit Root-owned protected parent required"))?;
    let directory = tempfile::Builder::new()
        .prefix("q24-factory-")
        .tempdir_in(parent)?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let (_scope_files, identity, initial, scope, _) = super::super::profile::tests::fixture()?;
    let journal_path = directory.path().join("proposal.journal");
    let witness_path = directory.path().join("witness");
    let journal = new_file(&journal_path)?;
    let witness_file = new_file(&witness_path)?;
    let profile = HostAuthorityQ24ModelFactoryProfileV1::new(
        &identity,
        &Digest32::of_bytes(b"synthetic-writer-data").to_string(),
        &initial,
        &scope,
        FilePin::capture(&journal)?,
        FilePin::capture(&witness_file)?,
        Digest32::of_bytes(b"test-file-domain-no-independence-claim"),
        Digest32::of_bytes(b"policy"),
    )?;
    let witness_scope = JournalScope {
        scope_digest: profile.binding().parse()?,
        objective_digest: initial.request.envelope.objective_digest,
    };
    let generation = Generation::new(identity.spawn_generation)?;
    let witness =
        FileAnchorWitnessStore::open(witness_file, witness_scope, generation, WITNESS_RECORDS)?;
    assert_eq!(witness.current()?, None);
    drop(witness);
    let vacant = FactoryRecord {
        profile: ReservedFactoryProfile::LegacyV1(profile.clone()),
        epoch: 1,
        material: None,
    };
    let store = HostAuthorityFrontierStore::initialize(
        RootAuthorityDirectory::open(directory.path())?,
        OWNER.into(),
        vacant.clone(),
    )?;
    let bound = FactoryRecord {
        profile: ReservedFactoryProfile::LegacyV1(profile.clone()),
        epoch: 2,
        material: Some(Digest32::of_bytes(b"original-material").to_string()),
    };
    store.compare_and_set(OWNER, &vacant, &bound)?;
    drop(store); // Simulates acknowledgement loss after the durable CAS.
    let store: HostAuthorityFrontierStore<FactoryRecord> = HostAuthorityFrontierStore::open(
        RootAuthorityDirectory::open(directory.path())?,
        OWNER.into(),
    )?;
    assert_eq!(store.load(OWNER)?, bound);
    assert!(
        HostAuthorityFrontierStore::initialize(
            RootAuthorityDirectory::open(directory.path())?,
            OWNER.into(),
            vacant.clone()
        )
        .is_err()
    );
    assert!(store.compare_and_set(OWNER, &vacant, &bound).is_err());
    profile.require_files(&journal, &open_file(&witness_path)?)?;
    // Bound with an empty proposal is an unresolved creation, not permission
    // to retry genesis. Reopening the files/registry performs no writes.
    assert_eq!(journal.metadata()?.len(), 0);
    let saved = std::fs::read(&witness_path)?;
    let witness = FileAnchorWitnessStore::open(
        open_file(&witness_path)?,
        witness_scope,
        generation,
        WITNESS_RECORDS,
    )?;
    assert_eq!(witness.current()?, None);
    drop(witness);
    assert_eq!(std::fs::read(&witness_path)?, saved);
    assert_eq!(store.load(OWNER)?, bound);
    Ok(())
}

#[test]
#[ignore = "explicit actual Root file custody qualification"]
fn root_factory_file_pins_reject_alias_replacement_wrong_access_and_missing_witness()
-> anyhow::Result<()> {
    // SAFETY: geteuid observes only the actual test process credential.
    anyhow::ensure!(
        unsafe { libc::geteuid() } == 0,
        "actual Root qualification required"
    );
    let directory = tempfile::tempdir()?;
    let original_path = directory.path().join("original");
    let original = new_file(&original_path)?;
    let pin = FilePin::capture(&original)?;
    pin.require_writable(&original)?;
    assert!(pin.require_writable(&File::open(&original_path)?).is_err());
    std::fs::hard_link(&original_path, directory.path().join("alias"))?;
    assert!(FilePin::capture(&original).is_err());
    std::fs::remove_file(directory.path().join("alias"))?;
    std::fs::rename(&original_path, directory.path().join("retired"))?;
    let mut replacement = new_file(&original_path)?;
    replacement.write_all(b"different owner")?;
    replacement.sync_all()?;
    assert!(pin.require_writable(&replacement).is_err());
    let (_scope_files, identity, initial, scope, _) = super::super::profile::tests::fixture()?;
    let empty_witness = new_file(&directory.path().join("empty-witness"))?;
    let profile = HostAuthorityQ24ModelFactoryProfileV1::new(
        &identity,
        &Digest32::of_bytes(b"writer").to_string(),
        &initial,
        &scope,
        FilePin::capture(&replacement)?,
        FilePin::capture(&empty_witness)?,
        Digest32::of_bytes(b"domain"),
        Digest32::of_bytes(b"policy"),
    )?;
    assert!(profile.require_files(&replacement, &empty_witness).is_err());
    assert_eq!(empty_witness.metadata()?.len(), 0);
    Ok(())
}
