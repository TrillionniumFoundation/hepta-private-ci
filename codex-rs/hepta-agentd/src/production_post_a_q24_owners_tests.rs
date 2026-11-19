//! Real private files and public signer data; no actual Root capsule is forged.

use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;

use super::*;

fn private(path: &std::path::Path, bytes: &[u8]) -> std::io::Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

#[test]
fn post_a_owner_open_rejects_missing_wrong_lifecycle_and_prior_reader_alias() -> anyhow::Result<()>
{
    let directory = tempfile::tempdir()?;
    let data = JournalData {
        journal: directory.path().join("journal"),
        witness: directory.path().join("witness"),
        scope: [1; 32],
        generation: 1,
        max_records: 4,
    };
    let objective = Digest32::of_bytes(b"original objective");
    assert!(
        data.open(&mut OriginalFiles::new()?, objective, OpenMode::Create)
            .is_err()
    );
    assert!(!data.journal.exists());
    private(&data.journal, &[])?;
    private(&data.witness, &[])?;
    assert!(
        data.open(&mut OriginalFiles::new()?, objective, OpenMode::Recover)
            .is_err()
    );
    let mut files = OriginalFiles::new()?;
    let _baseline = files.read(&data.journal)?;
    assert!(data.open(&mut files, objective, OpenMode::Create).is_err());
    let opened = data.open(&mut OriginalFiles::new()?, objective, OpenMode::Create)?;
    drop(opened);
    assert_eq!(std::fs::read(&data.journal)?, Vec::<u8>::new());
    assert_eq!(std::fs::read(&data.witness)?, Vec::<u8>::new());
    std::fs::write(&data.journal, b"retained original journal")?;
    assert!(
        data.open(&mut OriginalFiles::new()?, objective, OpenMode::Create)
            .is_err()
    );
    assert!(
        data.open(&mut OriginalFiles::new()?, objective, OpenMode::Recover)
            .is_err()
    );
    assert_eq!(std::fs::read(&data.journal)?, b"retained original journal");
    Ok(())
}

#[test]
fn post_a_signing_files_require_exact_existing_key_before_witness_initialization()
-> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let key = SigningKey::from_bytes(&[37; 32]);
    let payload = crate::root_initial_learning_trust_data::tests::payload();
    let first = payload
        .distribution
        .signers
        .first()
        .ok_or_else(|| std::io::Error::other("signer fixture absent"))?;
    let mut signer = first.original_signer()?;
    signer.verifying_key = key.verifying_key().to_bytes();
    let data = SigningFilesData {
        owner: JournalData {
            journal: directory.path().join("journal"),
            witness: directory.path().join("witness"),
            scope: [2; 32],
            generation: 1,
            max_records: 4,
        },
        key: directory.path().join("key"),
        signature_lifetime_seconds: 30,
    };
    for path in [&data.owner.journal, &data.owner.witness] {
        private(path, &[])?;
    }
    private(&data.key, &[38; 32])?;
    assert!(
        data.open_original(
            &mut OriginalFiles::new()?,
            &signer,
            Digest32::of_bytes(b"objective"),
            OpenMode::Create
        )
        .is_err()
    );
    assert!(std::fs::read(&data.owner.witness)?.is_empty());
    std::fs::write(&data.key, key.to_bytes())?;
    let (original, original_key) = data.open_original(
        &mut OriginalFiles::new()?,
        &signer,
        Digest32::of_bytes(b"objective"),
        OpenMode::Create,
    )?;
    assert_eq!(
        original_key.verifying_key().to_bytes(),
        signer.verifying_key
    );
    assert_eq!(original.witness.metadata()?.len(), 0);
    Ok(())
}
